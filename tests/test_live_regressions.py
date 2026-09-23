"""Regression tests built from the first live run (2026-09-22, 83-question sample).

Each malformed shape below was returned by the real model and caused a wrong result.
"""
from __future__ import annotations

import json
import re

import anthropic
import pytest

try:
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

from agents import prompts as P
from agents.llm import AnthropicLLM, ScriptedLLM, missing_required, normalize_structured
from agents.pipeline import RFPAgent, infer_status
from agents.prompts import DRAFTER_SCHEMA
from evals.validate_golden_set import load_golden
from tools import rewordings as rw
from tools.kb_text import normalize

# Shapes observed live (passage ids and values abbreviated)
LIVE_SHAPES = [
    ({"params": {"status": "answered", "claims": [{"text": "x", "passage_ids": ["P2"]}]}}, "answered"),
    ({"parameters": {"status": "conflict", "conflict": {"sides": [{"passage_id": "P1", "value": "4 hours"},
                                                                  {"passage_id": "P3", "value": "1 hour"}]}}}, "conflict"),
    ({"claims": [{"text": "All customer data is encrypted at rest using AES-256.", "passage_ids": ["P1"]}]}, "answered"),
    ({"conflict": {"sides": [{"passage_id": "P1", "value": "Within 1 hour, 24x7"},
                             {"passage_id": "P2", "value": "Within 30 minutes, 24x7"}]}}, "conflict"),
    ({"parameter name": "status"}, "insufficient_evidence"),
]


@pytest.mark.parametrize("raw, expected", LIVE_SHAPES)
def test_live_malformed_shapes_are_recovered(raw, expected):
    assert infer_status(normalize_structured(raw, DRAFTER_SCHEMA)) == expected


def test_unwrap_does_not_eat_real_fields():
    schema = {"properties": {"result": {"type": "object"}}, "required": ["result"]}
    assert normalize_structured({"result": {"a": 1}}, schema) == {"result": {"a": 1}}
    assert missing_required({"parameter name": "status"}, DRAFTER_SCHEMA) == ["status"]


def _mock_client(bodies: list[dict], captured: list):
    def handler(request):
        captured.append(json.loads(request.content))
        body = bodies[min(len(captured) - 1, len(bodies) - 1)]
        return httpx.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": "claude-sonnet-5",
            "content": [{"type": "tool_use", "id": "t", "name": "respond", "input": body}],
            "stop_reason": "tool_use", "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 5}})
    return anthropic.Anthropic(api_key="test", base_url="https://api.test",
                               http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_missing_required_field_triggers_one_repair_and_only_valid_output_is_cached(tmp_path):
    captured: list = []
    good = {"status": "insufficient_evidence", "missing": "x"}
    llm = AnthropicLLM(client=_mock_client([{"parameter name": "status"}, good], captured),
                       cache=True, cache_dir=tmp_path)
    assert llm.json(system="s", user="Question: q", schema=DRAFTER_SCHEMA, purpose="draft") == good
    assert len(captured) == 2 and llm.usage.repairs == 1
    assert "missing the required field(s) status" in captured[1]["messages"][0]["content"]
    assert len(list(tmp_path.iterdir())) == 1


def test_wrapped_output_is_unwrapped_without_a_retry(tmp_path):
    captured: list = []
    llm = AnthropicLLM(client=_mock_client([{"params": {"status": "answered", "claims": []}}], captured),
                       cache=False, cache_dir=tmp_path)
    assert llm.json(system="s", user="u", schema=DRAFTER_SCHEMA, purpose="draft")["status"] == "answered"
    assert len(captured) == 1


def _cls(sensitive=False, ambiguous=False, options=(), queries=("private connectivity",)):
    return lambda s, u: {"topic": "security_controls", "sensitive": sensitive, "ambiguous": ambiguous,
                         "clarification_options": list(options), "search_queries": list(queries)}


def _pid(user: str, needle: str) -> str:
    for m in re.finditer(r"^\[(P\d+)\][^\n]*\n([^\n]*)", user, re.M):
        if needle.lower() in m.group(2).lower():
            return m.group(1)
    raise AssertionError(f"{needle!r} not retrieved")


def test_claims_only_draft_is_answered_not_discarded():
    """Live DP-03: the model returned claims without a status and the answer was thrown away."""
    q = "Is customer data encrypted at rest? If so, which algorithm is used?"
    llm = ScriptedLLM({
        "classify": _cls(queries=["encryption at rest AES-256"]),
        "draft": lambda s, u: {"claims": [{"text": "All customer data is encrypted at rest using AES-256.",
                                           "passage_ids": [_pid(u, "AES-256")]}]},
        "verify": lambda s, u: {"results": [{"claim_index": 0, "supported": True,
                                             "quote": "All customer data is encrypted at rest using AES-256."}]},
    })
    r = RFPAgent(llm).answer(q)
    assert r.status == "answered" and r.citations[0].doc == "KR-SEC-002" and r.trace["status_inferred"] == "answered"


def test_wrapped_conflict_is_detected():
    """Live BC-02: a correct RPO conflict wrapped in {"parameters": ...} was reported as no evidence."""
    q = "What is your Recovery Point Objective (RPO)?"

    def draft(s, u):
        return {"parameters": {"status": "conflict", "conflict": {"topic": "RPO", "sides": [
            {"passage_id": _pid(u, "RPO) of 4 hours"), "value": "4 hours"},
            {"passage_id": _pid(u, "RPO) of 1 hour"), "value": "1 hour"}]}}}
    llm = ScriptedLLM({"classify": _cls(queries=["recovery point objective RPO"]), "draft": draft, "verify": None})
    r = RFPAgent(llm).answer(q)
    assert r.status == "conflict" and {s["doc"] for s in r.conflict["sources"]} == {"KR-BCP-004", "KR-SLA-005"}


def test_redraft_repairs_an_overstated_claim():
    """Live HD-01: the drafter added 'only'; the verifier rightly rejected it and the answer was lost."""
    q = "Do you support private network connectivity such as AWS PrivateLink?"
    exact = "Private connectivity through AWS PrivateLink is available on the Enterprise Premium edition."
    calls = []

    def draft(s, u):
        pid = _pid(u, "PrivateLink")
        if "fact checker rejected" in u:
            calls.append("redraft")
            return {"status": "answered", "claims": [{"text": exact, "passage_ids": [pid]}]}
        return {"status": "answered", "claims": [{"text": "PrivateLink is supported, but only on Enterprise Premium.",
                                                  "passage_ids": [pid]}]}

    def verify(s, u):
        claim = re.search(r"Claim 0: (.*)", u).group(1)
        ok = claim == exact
        return {"results": [{"claim_index": 0, "supported": ok, "quote": exact if ok else "",
                             "reason": "" if ok else "source does not say 'only'"}]}

    r = RFPAgent(ScriptedLLM({"classify": _cls(), "draft": draft, "verify": verify})).answer(q)
    assert calls == ["redraft"]
    assert r.status == "answered" and "only" not in r.answer and r.route_to is None


def test_ambiguity_is_checked_before_sensitivity():
    """Live GN-01: flagged both ambiguous and sensitive; clarification is the right first step."""
    r = RFPAgent(ScriptedLLM({"classify": _cls(sensitive=True, ambiguous=True, options=["a", "b"]),
                              "draft": None, "verify": None})).answer("What is the notice period?")
    assert r.status == "needs_clarification"


def test_prompts_contain_no_eval_questions():
    """Prompt examples must not be golden-set questions or rewordings, or the eval measures recall."""
    text = normalize(" ".join(v for v in vars(P).values() if isinstance(v, str)))
    qs = [q["question"] for q in load_golden()["questions"]]
    qs += [r["text"] for items in rw.load().values() for r in items]
    leaked = [q for q in qs if normalize(q).rstrip("?.") in text]
    assert not leaked, leaked


def test_consistency_rule_on_live_answers():
    """Live run: HD-05 volunteered UK hosting (a real catch); BC-07 (RTO) merely shares a sentence with the RPO conflict."""
    from pathlib import Path

    from agents.consistency import conflict_reliance
    from agents.pipeline import Citation, Result
    rs = []
    for line in (Path(__file__).parent / "fixtures" / "live_run_2026-09-22_consistency.jsonl").read_text().splitlines():
        d = json.loads(line)
        d["citations"] = [Citation(**c) for c in d["citations"]]
        d["related_excerpts"] = [Citation(**c) for c in d["related_excerpts"]]
        rs.append(Result(**d))
    assert [i.refs for i in conflict_reliance(rs)] == [["HD-05", "HD-07"]]


def test_compare_runs_reports_flips():
    from evals.compare_runs import compare
    row = lambda ref, ok, st: {"ref": ref, "golden_id": "G", "score": {"pass": ok, "why": "" if ok else "status"},  # noqa: E731
                               "result": {"status": st}}
    old = {"file": "f", "metrics": {"pass_rate": 0.5, "false_answer_rate": 0.02},
           "rows": [row("A", False, "insufficient_evidence"), row("B", True, "answered")]}
    new = {"file": "f", "metrics": {"pass_rate": 0.5, "false_answer_rate": 0.0},
           "rows": [row("A", True, "answered"), row("B", False, "escalated")]}
    out = compare(old, new)
    assert "Now passing (1)" in out and "- A (G): insufficient_evidence -> answered" in out
    assert "Now failing (1)" in out and "| false answer rate | 2% | 0% | better |" in out
