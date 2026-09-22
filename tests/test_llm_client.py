"""Exercise the real Anthropic SDK request/response path through a mocked HTTP transport."""
from __future__ import annotations

import json

import anthropic
try:  # newer SDK releases ship their own fork of httpx
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

from agents.llm import AnthropicLLM


def _client(captured: list):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-sonnet-5",
            "content": [{"type": "tool_use", "id": "toolu_1", "name": "respond",
                         "input": {"status": "insufficient_evidence", "missing": "x"}}],
            "stop_reason": "tool_use", "stop_sequence": None,
            "usage": {"input_tokens": 120, "output_tokens": 30}})
    return anthropic.Anthropic(api_key="test", base_url="https://api.test",
                               http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_structured_call_and_cache(tmp_path):
    captured: list = []
    llm = AnthropicLLM(model="claude-sonnet-5", client=_client(captured), cache=True, cache_dir=tmp_path)
    schema = {"type": "object", "properties": {"status": {"type": "string"}}}
    out = llm.json(system="sys", user="Question: q", schema=schema, purpose="draft")
    assert out["status"] == "insufficient_evidence"
    req = captured[0]
    assert req["tool_choice"] == {"type": "tool", "name": "respond"}
    assert req["tools"][0]["input_schema"] == schema and req["model"] == "claude-sonnet-5"
    assert llm.usage.input_tokens == 120

    again = llm.json(system="sys", user="Question: q", schema=schema, purpose="draft")
    assert again == out and len(captured) == 1 and llm.usage.cached == 1   # replayed from disk
