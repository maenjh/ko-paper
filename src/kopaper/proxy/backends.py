"""Translator backends behind the OpenAI-compatible proxy."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from dataclasses import dataclass
from typing import Protocol

from ..config import DATA_DIR


class BackendError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int


class TranslatorBackend(Protocol):
    name: str

    async def complete(self, system: str, prompt: str, model: str) -> Completion: ...


_LIMIT_RE = re.compile(r"rate.?limit|quota|usage limit|overloaded|\b(429|529)\b", re.I)


class ClaudeCodeBackend:
    """Calls the locally logged-in Claude Code CLI in headless mode (Claude subscription)."""

    name = "claude-code"

    def __init__(self) -> None:
        name = os.environ.get("KOPAPER_CLAUDE_BIN", "claude")
        self.bin = shutil.which(name) or name  # full path: on Windows this also finds claude.cmd
        self.timeout = int(os.environ.get("KOPAPER_CALL_TIMEOUT", "300"))

    async def complete(self, system: str, prompt: str, model: str) -> Completion:
        # Trimmed flags: custom system prompt, no tools, no settings/MCP → ~850 token overhead per call.
        cmd = [
            self.bin, "-p", "--output-format", "json", "--model", model,
            "--system-prompt", system, "--tools", "", "--strict-mcp-config",
            "--setting-sources", "", "--no-session-persistence",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=str(DATA_DIR),
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise BackendError(504, "claude -p timed out")
        try:
            data = json.loads(out.decode())
        except json.JSONDecodeError:
            msg = (out[:300] + err[:300]).decode(errors="replace")
            raise BackendError(429 if _LIMIT_RE.search(msg) else 502, f"claude -p bad output: {msg}")
        if data.get("is_error"):
            msg = str(data.get("result", ""))
            raise BackendError(429 if _LIMIT_RE.search(msg) else 502, msg)
        u = data.get("usage", {})
        tin = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
        return Completion(str(data.get("result", "")), tin, u.get("output_tokens", 0))


# Proxy-facing short names → Claude API model IDs
API_MODELS = {
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5-5",
    "haiku": "claude-haiku-4-5",
}


class AnthropicAPIBackend:
    """Pay-as-you-go Claude API (ANTHROPIC_API_KEY or `ant auth login` profile)."""

    name = "anthropic-api"

    def __init__(self) -> None:
        import anthropic  # optional dependency: `uv sync --extra api`

        self._anthropic = anthropic
        self.client = anthropic.AsyncAnthropic()
        self.effort = os.environ.get("KOPAPER_EFFORT", "medium")

    async def complete(self, system: str, prompt: str, model: str) -> Completion:
        a = self._anthropic
        model_id = API_MODELS.get(model, model)
        try:
            async with self.client.beta.messages.stream(
                model=model_id,
                max_tokens=32000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": self.effort},
                # Server-side refusal fallback: routes a declined request to a suitable model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                msg = await stream.get_final_message()
        except a.RateLimitError as e:
            raise BackendError(429, e.message)
        except a.APIStatusError as e:
            raise BackendError(e.status_code if e.status_code >= 500 else 502, e.message)
        except a.APIConnectionError as e:
            raise BackendError(502, str(e))
        if msg.stop_reason == "refusal":
            raise BackendError(502, f"refused: {getattr(msg, 'stop_details', None)}")
        text = "".join(b.text for b in msg.content if b.type == "text")
        return Completion(text, msg.usage.input_tokens, msg.usage.output_tokens)


class CodexBackend:
    """Calls the locally logged-in Codex CLI (`codex exec`) — for people with ChatGPT/Codex but no Claude."""

    name = "codex"
    # The proxy speaks Claude model names; map them to Codex reasoning effort instead.
    EFFORT = {"haiku": "low", "sonnet": "low", "opus": "medium"}

    def __init__(self) -> None:
        name = os.environ.get("KOPAPER_CODEX_BIN", "codex")
        self.bin = shutil.which(name) or name  # full path: on Windows this also finds npm's codex.cmd
        self.model = os.environ.get("KOPAPER_CODEX_MODEL")  # unset → Codex's default model
        self.effort = os.environ.get("KOPAPER_CODEX_EFFORT")
        self.timeout = int(os.environ.get("KOPAPER_CALL_TIMEOUT", "300"))
        self.workdir = DATA_DIR / "codex"
        self.workdir.mkdir(parents=True, exist_ok=True)

    def _instructions(self, system: str) -> str:
        # Replacing Codex's agent instructions with ours halves the per-call overhead (~17k → ~9k tokens).
        import hashlib

        f = self.workdir / f"instructions-{hashlib.sha256(system.encode()).hexdigest()[:16]}.md"
        if not f.exists():
            f.write_text(system, encoding="utf-8")
        return str(f)

    async def complete(self, system: str, prompt: str, model: str) -> Completion:
        cmd = [
            self.bin, "exec", "--json", "--skip-git-repo-check", "--ephemeral",
            "--ignore-user-config", "--ignore-rules", "--sandbox", "read-only",
            "-c", f"model_instructions_file={json.dumps(self._instructions(system))}",
            "-c", f"model_reasoning_effort={json.dumps(self.effort or self.EFFORT.get(model, 'low'))}",
            "-c", 'web_search="disabled"',
            # Paper text is untrusted: no shell, so a planted instruction can't read local files.
            "-c", "features.shell_tool=false",
        ]
        if self.model:
            cmd += ["--model", self.model]
        cmd.append("-")
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=str(self.workdir),
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise BackendError(504, "codex exec timed out")
        return parse_codex_events(out.decode(errors="replace"), err.decode(errors="replace"))


def parse_codex_events(stdout: str, stderr: str = "") -> Completion:
    """Last agent message + usage from `codex exec --json` output."""
    text, usage, errors = None, {}, []
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = ev.get("type")
        if t == "item.completed" and ev.get("item", {}).get("type") == "agent_message":
            text = ev["item"].get("text", "")
        elif t == "turn.completed":
            usage = ev.get("usage") or {}
        elif t in ("error", "turn.failed"):
            errors.append(str(ev.get("message") or (ev.get("error") or {}).get("message") or ev))
    if text is None:
        msg = (" | ".join(errors) or stderr.strip() or stdout.strip())[:500]
        raise BackendError(429 if _LIMIT_RE.search(msg) else 502, f"codex exec failed: {msg}")
    return Completion(text, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)))


def make_backend(name: str) -> TranslatorBackend:
    if name == "claude-code":
        return ClaudeCodeBackend()
    if name == "anthropic-api":
        return AnthropicAPIBackend()
    if name == "codex":
        return CodexBackend()
    raise ValueError(f"unknown backend: {name}")
