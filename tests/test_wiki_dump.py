"""The wiki dump tool against a local fake MediaWiki API (no network)."""

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

_spec = importlib.util.spec_from_file_location("wiki_dump", Path(__file__).parents[1] / "tools" / "wiki_dump.py")
wiki_dump = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wiki_dump)

TITLES = {0: [f"Page {i}" for i in range(5)], 14: ["Category:Zones"]}


def _page(ns, i, title):
    return {"pageid": ns * 100 + i, "ns": ns, "title": title,
            "revisions": [{"revid": i + 1, "timestamp": "2020-01-01T00:00:00Z",
                           "slots": {"main": {"content": f"text of {title} [[Категория:Зоны]]"}}}]}


class FakeApi(BaseHTTPRequestHandler):
    fail_once = set()
    hits = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        FakeApi.hits += 1
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        if "flaky" in FakeApi.fail_once:
            FakeApi.fail_once.discard("flaky")
            self.send_response(503)
            self.send_header("Retry-After", "0")
            self.end_headers()
            return
        ns, start = int(q["gapnamespace"]), int(q.get("gapcontinue", 0))
        titles = TITLES[ns]
        chunk = titles[start:start + 2]  # the fake server returns 2 pages per request
        body = {"query": {"pages": [_page(ns, start + i, t) for i, t in enumerate(chunk)]}}
        if start + 2 < len(titles):
            body["continue"] = {"gapcontinue": str(start + 2), "continue": "gapcontinue||"}
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    FakeApi.fail_once, FakeApi.hits = set(), 0
    httpd = HTTPServer(("127.0.0.1", 0), FakeApi)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def _client(base, **kw):
    return wiki_dump.Client(base, delay=0, sleep=lambda s: None, **kw)


def _lines(path):
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def test_dump_follows_continuation_and_writes_jsonl(server, tmp_path):
    wiki_dump.dump(_client(server), tmp_path, [0, 14], log=lambda *_: None)
    pages = _lines(tmp_path / "ns0.jsonl")
    assert [p["title"] for p in pages] == TITLES[0]
    assert pages[0]["text"].startswith("text of Page 0") and pages[0]["revid"] == 1
    assert [p["title"] for p in _lines(tmp_path / "ns14.jsonl")] == TITLES[14]


def test_finished_namespaces_are_skipped_on_rerun(server, tmp_path):
    wiki_dump.dump(_client(server), tmp_path, [0], log=lambda *_: None)
    hits = FakeApi.hits
    wiki_dump.dump(_client(server), tmp_path, [0], log=lambda *_: None)
    assert FakeApi.hits == hits
    assert len(_lines(tmp_path / "ns0.jsonl")) == 5


def test_interrupted_run_resumes_without_duplicates(server, tmp_path):
    client = _client(server)
    gen = wiki_dump.batches(client, 0, None)
    first, cont = next(gen)
    state = {"namespaces": {"0": {"done": False, "pages": len(first), "continue": cont}}}
    (tmp_path / "ns0.jsonl").write_text("".join(json.dumps(p) + "\n" for p in first), "utf-8")
    (tmp_path / "state.json").write_text(json.dumps(state), "utf-8")
    wiki_dump.dump(client, tmp_path, [0], log=lambda *_: None)
    assert [p["title"] for p in _lines(tmp_path / "ns0.jsonl")] == TITLES[0]


def test_retries_on_503(server, tmp_path):
    FakeApi.fail_once = {"flaky"}
    wiki_dump.dump(_client(server), tmp_path, [14], log=lambda *_: None)
    assert len(_lines(tmp_path / "ns14.jsonl")) == 1


def test_gives_up_after_retries(server):
    FakeApi.fail_once = set()
    with pytest.raises(wiki_dump.WikiError):
        _client("http://127.0.0.1:9", retries=1).get(action="query")


def test_categories_from_wikitext():
    text = "x [[Category:Zones]] y [[Категория:Города|Орг]] [[Категорія:Зони]] [[Category:Zones]]"
    assert wiki_dump.categories(text) == ["Zones", "Города", "Зони"]


def test_no_redirects_asks_the_api_to_filter(server, tmp_path):
    seen = []
    client = _client(server)
    real_get = client.get
    client.get = lambda **kw: (seen.append(kw), real_get(**kw))[1]
    wiki_dump.dump(client, tmp_path, [14], redirects=False, log=lambda *_: None)
    assert seen and all(kw.get("gapfilterredir") == "nonredirects" for kw in seen)
