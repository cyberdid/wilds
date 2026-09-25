"""Brain backed by OpenAI Codex CLI (`codex exec`), e.g. GPT-5.6-Luna.

Uses the user's Codex login (ChatGPT plan or API key - whatever `codex` is
set up with). The reply is forced into a strict schema with
``--output-schema`` and read from the ``-o`` last-message file.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .cli import CLIBrain, Runner, decision_schema, last_line

SCHEMA = decision_schema(strict=True)
DEFAULT_MODEL = "gpt-5.6-luna"

_PREAMBLE = """You are playing a game, not working on code. Do not run any commands, do not read
or write files, do not use tools. Read the situation below and answer immediately with the JSON object.

"""


class CodexBrain(CLIBrain):
    name = "codex"
    strict_schemas = True

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        effort: str | None = "low",
        lang: str = "Ukrainian",
        timeout: float = 180,
        codex_bin: str = "codex",
        log_dir: Path | None = None,
        runner: Runner = subprocess.run,
    ) -> None:
        super().__init__(model, lang, timeout, log_dir, runner)
        self.effort = effort
        self.codex_bin = codex_bin
        self.reply_path = self.workdir / "reply.json"

    def schema_file(self, schema: dict[str, Any]) -> Path:
        text = json.dumps(schema, sort_keys=True)
        path = self.workdir / f"schema-{hashlib.sha1(text.encode()).hexdigest()[:10]}.json"
        if not path.exists():
            path.write_text(text)
        return path

    def command(self, schema: dict[str, Any] | None = None) -> list[str]:
        cmd = [
            self.codex_bin, "exec",
            "--model", self.model,
            "--ignore-user-config",  # no plugins/MCP servers from ~/.codex/config.toml
            "--ignore-rules",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox", "read-only",
            "--color", "never",
            "--output-schema", str(self.schema_file(schema or SCHEMA)),
            "--output-last-message", str(self.reply_path),
        ]
        if self.effort:
            cmd += ["-c", f"model_reasoning_effort={self.effort}"]
        return cmd + ["-"]  # prompt from stdin

    def run(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.reply_path.unlink(missing_ok=True)
        proc = self.runner(self.command(schema), input=_PREAMBLE + system + "\n---\n\n" + prompt,
                           capture_output=True, text=True, timeout=self.timeout, cwd=self.workdir)
        return self.read_reply(proc)

    def read_reply(self, proc: subprocess.CompletedProcess) -> dict[str, Any]:
        match = re.search(r"tokens used\s*\n?\s*([\d,]+)", (proc.stderr or "") + (proc.stdout or ""))
        if match:
            self.tokens_in += int(match.group(1).replace(",", ""))
        if proc.returncode != 0:
            raise ValueError(f"exit {proc.returncode}: {last_line(proc)}")
        text = self.reply_path.read_text() if self.reply_path.exists() else ""
        if not text.strip():
            raise ValueError("codex gave no final message")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            found = re.search(r"\{.*\}", text, re.S)  # tolerate prose around the object
            if found:
                try:
                    return json.loads(found.group(0))
                except json.JSONDecodeError:
                    pass
            raise ValueError("reply was not valid JSON") from None
