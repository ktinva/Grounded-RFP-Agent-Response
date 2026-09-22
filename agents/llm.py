"""Thin LLM layer: one method, `json()`, that returns schema-shaped output.

* AnthropicLLM   calls Claude with a single forced tool, so the reply is always a
                 JSON object matching the schema (no free-text parsing).
* Disk cache     identical calls (model + prompts + schema) are replayed from
                 .cache/llm/, which makes eval re-runs free and reproducible.
                 Disable with LLM_CACHE=0.
* ScriptedLLM    deterministic stand-in used by the tests; answers by `purpose`.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / ".cache" / "llm"
DEFAULT_MODEL = "claude-sonnet-5"


class MissingAPIKey(RuntimeError):
    pass


class LLM(Protocol):
    def json(self, *, system: str, user: str, schema: dict | None = None, purpose: str = "",
             max_tokens: int = 1500) -> dict: ...


@dataclass
class Usage:
    calls: int = 0
    cached: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, cached: bool, inp: int = 0, out: int = 0) -> None:
        with self._lock:
            self.calls += 1
            self.cached += int(cached)
            self.input_tokens += inp
            self.output_tokens += out

    def to_dict(self) -> dict:
        return {"calls": self.calls, "cached": self.cached,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class AnthropicLLM:
    def __init__(self, model: str | None = None, cache: bool | None = None, client=None,
                 cache_dir: Path | None = None):
        _load_dotenv()
        if client is None:
            key = os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise MissingAPIKey("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")
            import anthropic  # imported here so the rest of the repo works without the SDK
            client = anthropic.Anthropic(api_key=key, max_retries=4)
        self.client = client
        self.cache_dir = cache_dir or CACHE_DIR
        self.model = model or os.environ.get("RFP_AGENT_MODEL", DEFAULT_MODEL)
        self.cache = (os.environ.get("LLM_CACHE", "1") != "0") if cache is None else cache
        self.usage = Usage()

    def json(self, *, system: str, user: str, schema: dict | None = None, purpose: str = "",
             max_tokens: int = 1500) -> dict:
        schema = schema or {"type": "object"}
        key = hashlib.sha256(json.dumps([self.model, system, user, schema], sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if self.cache and path.exists():
            self.usage.add(cached=True)
            return json.loads(path.read_text())["output"]

        resp = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
            tools=[{"name": "respond", "description": f"Return the {purpose or 'result'} as structured data.",
                    "input_schema": schema}],
            tool_choice={"type": "tool", "name": "respond"},
        )
        out = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
        if out is None:
            raise RuntimeError(f"model returned no structured output for {purpose}")
        self.usage.add(cached=False, inp=resp.usage.input_tokens, out=resp.usage.output_tokens)
        if self.cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"purpose": purpose, "model": self.model, "output": out}, indent=1))
        return out


class ScriptedLLM:
    """Test double: `handlers[purpose](system, user) -> dict`."""

    def __init__(self, handlers: dict[str, Callable[[str, str], dict]]):
        self.handlers = handlers
        self.calls: list[tuple[str, str]] = []
        self.usage = Usage()

    def json(self, *, system: str, user: str, schema: dict | None = None, purpose: str = "",
             max_tokens: int = 1500) -> dict:
        self.calls.append((purpose, user))
        self.usage.add(cached=False)
        return self.handlers[purpose](system, user)


def get_llm() -> LLM:
    return AnthropicLLM()
