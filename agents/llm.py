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


# Wrapper keys models sometimes nest a tool input under (seen in live runs: "params", "parameters").
_WRAPPER_KEYS = {"params", "parameters", "input", "arguments", "args", "properties", "result", "response", "output"}


def normalize_structured(out, schema: dict | None) -> dict:
    """Undo common structured-output slips: a single wrapper object around the real fields."""
    if not isinstance(out, dict):
        return {}
    props = set((schema or {}).get("properties", {}))
    for _ in range(2):
        if len(out) == 1:
            (k, v), = out.items()
            if isinstance(v, dict) and k in _WRAPPER_KEYS and k not in props:
                out = v
                continue
        break
    return out


def missing_required(out: dict, schema: dict | None) -> list[str]:
    return [k for k in (schema or {}).get("required", []) if k not in out]


REPAIR_NOTE = ("\n\n[Your previous reply could not be used: it was missing the required field(s) {fields}. "
               "Reply again with every required field at the top level of the tool input, not nested "
               "inside another object.]")


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

    repairs: int = 0

    def add_repair(self) -> None:
        with self._lock:
            self.repairs += 1

    def add(self, cached: bool, inp: int = 0, out: int = 0) -> None:
        with self._lock:
            self.calls += 1
            self.cached += int(cached)
            self.input_tokens += inp
            self.output_tokens += out

    def to_dict(self) -> dict:
        return {"calls": self.calls, "cached": self.cached, "repairs": self.repairs,
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

        out: dict = {}
        prompt = user
        for attempt in range(2):  # one repair attempt if a required field is missing
            resp = self.client.messages.create(
                model=self.model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": prompt}],
                tools=[{"name": "respond",
                        "description": (f"Submit the {purpose or 'result'}. Put every field directly at the top "
                                        f"level of the input; do not wrap it in another object."),
                        "input_schema": schema}],
                tool_choice={"type": "tool", "name": "respond"},
            )
            raw = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
            self.usage.add(cached=False, inp=resp.usage.input_tokens, out=resp.usage.output_tokens)
            out = normalize_structured(raw, schema)
            missing = missing_required(out, schema)
            if not missing:
                break
            self.usage.add_repair()
            prompt = user + REPAIR_NOTE.format(fields=", ".join(missing))
        else:
            return out  # still incomplete: return as-is (callers infer or abstain) and do not cache it
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
        handler = self.handlers.get(purpose) or (self.handlers.get("draft") if purpose == "redraft" else None)
        if handler is None:
            raise KeyError(f"no scripted handler for {purpose!r}")
        return normalize_structured(handler(system, user), schema)


def get_llm() -> LLM:
    return AnthropicLLM()
