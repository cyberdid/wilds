"""Brain backed by Claude through the Claude Code CLI (`claude -p`).

Uses the user's Claude subscription login - no API key. Each call is one
headless run with a JSON schema, so the reply is always structured.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .cli import CLIBrain, Runner, decision_schema, last_line

SCHEMA = decision_schema(strict=False)


class ClaudeBrain(CLIBrain):
    name = "claude"
    strict_schemas = False

    def __init__(
        self,
        model: str = "haiku",
        effort: str | None = "low",
        thinking: bool = False,
        lang: str = "Ukrainian",
        timeout: float = 180,
        claude_bin: str = "claude",
        log_dir: Path | None = None,
        runner: Runner = subprocess.run,
    ) -> None:
        super().__init__(model, lang, timeout, log_dir, runner)
        self.effort = effort
        self.thinking = thinking
        self.claude_bin = claude_bin

    def command(self, system: str | None = None, schema: dict[str, Any] | None = None) -> list[str]:
        cmd = [
            self.claude_bin, "-p",
            "--model", self.model,
            "--tools", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--setting-sources", "",
            "--no-session-persistence",
            "--output-format", "json",
            "--system-prompt", system or self.system,
            "--json-schema", json.dumps(schema or SCHEMA),
        ]
        if self.effort:
            cmd += ["--effort", self.effort]
        if not self.thinking:  # extended thinking makes each move 10-100 s instead of ~6 s
            cmd += ["--settings", json.dumps({"alwaysThinkingEnabled": False})]
        return cmd

    def run(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        proc = self.runner(self.command(system, schema), input=prompt, capture_output=True, text=True,
                           timeout=self.timeout, cwd=self.workdir)
        return self.read_reply(proc)

    def read_reply(self, proc: subprocess.CompletedProcess) -> dict[str, Any]:
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise ValueError(f"exit {proc.returncode}: {last_line(proc)}") from None
        if data.get("is_error") or proc.returncode != 0:
            raise ValueError(str(data.get("result") or data.get("subtype") or f"exit {proc.returncode}"))
        usage = data.get("usage") or {}
        self.tokens_in += int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0)
        self.tokens_out += int(usage.get("output_tokens") or 0)
        out = data.get("structured_output")
        if isinstance(out, dict):
            return out
        try:
            return json.loads(data.get("result") or "")
        except (json.JSONDecodeError, TypeError):
            raise ValueError("reply was not valid JSON") from None
