"""Polite, resumable dump of a public MediaWiki (Fandom, wiki.gg, ...) to JSONL.

    python tools/wiki_dump.py --base https://wowwiki.fandom.com/ru --out data/wow/ru
    python tools/wiki_dump.py --base https://warcraft.wiki.gg --out data/wow/en --namespaces 0,10,14

Standard library only. For every namespace it walks ``generator=allpages`` and
stores the current wikitext of each page in ``<out>/ns<N>.jsonl`` (one JSON
object per line: pageid, ns, title, revid, timestamp, text). Progress is kept in
``<out>/state.json`` after every batch, so an interrupted run resumes where it
stopped and a finished namespace is skipped. Requests are sequential, paced
(``--delay``), retried with backoff and honour ``Retry-After``.

Text on Fandom and wiki.gg is CC BY-SA: keep attribution if you redistribute it.
Uses ``HTTPS_PROXY`` / ``SSL_CERT_FILE`` from the environment like any urllib client.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator

DEFAULT_UA = "wilds-wiki-dump/0.1 (personal research; polite sequential crawler)"
NS_NAMES = {0: "main", 10: "template", 14: "category"}


class WikiError(RuntimeError):
    pass


class Client:
    def __init__(self, base: str, user_agent: str = DEFAULT_UA, delay: float = 0.5, retries: int = 6,
                 timeout: float = 60, sleep=time.sleep) -> None:
        self.api = base.rstrip("/") + "/api.php"
        self.user_agent = user_agent
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.sleep = sleep
        self.requests = 0

    def get(self, **params: Any) -> dict[str, Any]:
        params = {"format": "json", "formatversion": "2", **params}
        url = self.api + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent,
                                                       "Accept-Encoding": "identity"})
        wait = 2.0
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                self.requests += 1
                self.sleep(self.delay)
                if "error" in data:
                    raise WikiError(f"{data['error'].get('code')}: {data['error'].get('info')}")
                return data
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise WikiError(f"HTTP {exc.code} for {self.api}") from exc
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                pause = float(retry_after) if retry_after.isdigit() else wait
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
                if attempt == self.retries:
                    raise WikiError(f"{type(exc).__name__}: {exc}") from exc
                pause = wait
            print(f"  retry {attempt + 1}/{self.retries} in {pause:.0f}s", file=sys.stderr)
            self.sleep(pause)
            wait = min(wait * 2, 120)
        raise WikiError("unreachable")


def batches(client: Client, namespace: int, resume: dict[str, str] | None,
            batch_size: int = 50) -> Iterator[tuple[list[dict[str, Any]], dict[str, str] | None]]:
    """Yield (pages, continue-token) for one namespace; the token is None after the last batch."""
    cont = dict(resume) if resume else {}
    while True:
        data = client.get(action="query", generator="allpages", gapnamespace=namespace, gaplimit=batch_size,
                          prop="revisions", rvprop="ids|timestamp|content", rvslots="main", **cont)
        pages = []
        for page in data.get("query", {}).get("pages", []):
            revs = page.get("revisions") or []
            if page.get("missing") or not revs:
                continue
            rev = revs[0]
            slot = (rev.get("slots") or {}).get("main") or {}
            pages.append({"pageid": page["pageid"], "ns": page["ns"], "title": page["title"],
                          "revid": rev.get("revid"), "timestamp": rev.get("timestamp"),
                          "text": slot.get("content", "")})
        cont = data.get("continue")
        yield pages, (dict(cont) if cont else None)
        if not cont:
            return


def dump(client: Client, out: Path, namespaces: list[int], batch_size: int = 50,
         log=print) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.json"
    state = json.loads(state_path.read_text("utf-8")) if state_path.exists() else {}
    state.setdefault("namespaces", {})
    state["api"] = client.api
    for ns in namespaces:
        entry = state["namespaces"].setdefault(str(ns), {"done": False, "pages": 0, "continue": None})
        if entry["done"]:
            log(f"ns {ns}: already done ({entry['pages']} pages)")
            continue
        log(f"ns {ns} ({NS_NAMES.get(ns, 'other')}): {'resuming' if entry['continue'] else 'starting'}")
        with (out / f"ns{ns}.jsonl").open("a", encoding="utf-8") as f:
            for pages, cont in batches(client, ns, entry["continue"], batch_size):
                for page in pages:
                    f.write(json.dumps(page, ensure_ascii=False) + "\n")
                f.flush()
                entry["pages"] += len(pages)
                entry["continue"], entry["done"] = cont, cont is None
                state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                log(f"  ns {ns}: {entry['pages']} pages")
    return state


_CATEGORY = re.compile(r"\[\[\s*(?:Category|Категория|Категорія)\s*:\s*([^\]|]+)", re.I)


def categories(wikitext: str) -> list[str]:
    """Category names mentioned in a page's wikitext (en/ru/uk prefixes)."""
    return sorted({m.group(1).strip() for m in _CATEGORY.finditer(wikitext)})


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--base", required=True, help="wiki root, e.g. https://wowwiki.fandom.com/ru")
    p.add_argument("--out", type=Path, required=True, help="output directory")
    p.add_argument("--namespaces", default="0,10,14",
                   help="comma-separated namespace ids (0 articles, 10 templates, 14 categories)")
    p.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    p.add_argument("--batch", type=int, default=50, help="pages per request (max 50)")
    p.add_argument("--user-agent", default=DEFAULT_UA)
    args = p.parse_args(argv)
    client = Client(args.base, args.user_agent, args.delay)
    try:
        dump(client, args.out, [int(n) for n in args.namespaces.split(",")], min(50, args.batch))
    except WikiError as exc:
        sys.exit(f"stopped: {exc}\nrun the same command again to resume")
    print(f"done: {client.requests} requests -> {args.out}")


if __name__ == "__main__":
    main()
