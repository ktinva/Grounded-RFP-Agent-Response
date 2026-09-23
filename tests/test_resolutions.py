"""Reviewed rulings (data/sample/resolutions.yaml) and the answer-every-reading rule (D30, D31)."""
from __future__ import annotations

import re

import yaml

from agents.llm import ScriptedLLM
from agents.pipeline import RFPAgent
from evals.scoring import aggregate, score_one
from evals.validate_golden_set import load_golden
from tools import resolutions as rs

AUDIT_Q = "How far back can we retrieve audit events for our workspace?"
ONE_YEAR = "Customer audit logs are retained for 1 year."
API_180 = "Audit events are available through the Audit Log API for 180 days."


def _pid(user, needle):
    for m in re.finditer(r"^\[(P\d+)\][^\n]*\n([^\n]*)", user, re.M):
        if needle.lower() in m.group(2).lower():
            return m.group(1)
    raise AssertionError(needle)


def _cls(queries):
    return lambda s, u: {"topic": "security_controls", "sensitive": False, "ambiguous": False,
                         "search_queries": queries}


def _verify_exact(s, u):
    claims = re.findall(r"Claim (\d+): (.*)", u)
    return {"results": [{"claim_index": int(i), "supported": True, "quote": c} for i, c in claims]}


def test_shipped_rulings_are_valid():
    assert rs.validate() == [] and [r.id for r in rs.load()] == ["RES-001"]


def test_validator_catches_a_ruling_whose_text_changed(tmp_path):
    data = yaml.safe_load(rs.DEFAULT_PATH.read_text())
    data["resolutions"][0]["statements"][0]["quote"] = "Customer audit logs are retained for 2 years."
    data["resolutions"][0]["statements"][1]["doc"] = "KR-SEC-010"          # the unapproved draft
    p = tmp_path / "r.yaml"
    p.write_text(yaml.safe_dump(data))
    errs = rs.validate(p)
    assert any("no longer on" in e for e in errs) and any("not an approved document" in e for e in errs)


def test_ruling_is_shown_only_when_its_statements_are_retrieved():
    seen = {}

    def draft(s, u):
        seen[u.split("\n")[0]] = "RES-001" in u
        return {"status": "insufficient_evidence", "missing": "x"}
    llm = ScriptedLLM({"classify": _cls(["audit log retention API 180 days 1 year"]), "draft": draft, "verify": None})
    RFPAgent(llm).answer(AUDIT_Q)
    llm2 = ScriptedLLM({"classify": _cls(["encryption at rest"]), "draft": draft, "verify": None})
    RFPAgent(llm2).answer("Is customer data encrypted at rest?")
    assert seen == {f"Question: {AUDIT_Q}": True, "Question: Is customer data encrypted at rest?": False}


def _conflict_then(answer_on_redraft: bool):
    def draft(s, u):
        if "reviewer ruling RES-001" in u and answer_on_redraft:
            return {"status": "answered", "claims": [
                {"text": ONE_YEAR, "passage_ids": [_pid(u, ONE_YEAR)]},
                {"text": API_180, "passage_ids": [_pid(u, "Audit Log API for 180 days")]}]}
        return {"status": "conflict", "conflict": {"topic": "audit logs", "sides": [
            {"passage_id": _pid(u, ONE_YEAR), "value": "retained for 1 year"},
            {"passage_id": _pid(u, "Audit Log API for 180 days"), "value": "Audit Log API for 180 days"}]}}
    return ScriptedLLM({"classify": _cls(["audit log retention API 180 days 1 year"]), "draft": draft,
                        "verify": _verify_exact})


def test_ruled_pair_is_answered_with_both_figures():
    r = RFPAgent(_conflict_then(answer_on_redraft=True)).answer(AUDIT_Q)
    assert r.status == "answered" and "1 year" in r.answer and "180 days" in r.answer
    assert r.trace["redraft_for_ruling"]["ruling"] == "RES-001"
    g = next(q for q in load_golden()["questions"] if q["id"] == "COV-034")
    assert score_one(g, r.to_dict(), set())["pass"]


def test_ruled_pair_stays_a_conflict_if_the_drafter_insists():
    """Safe fallback: a human still sees both figures."""
    r = RFPAgent(_conflict_then(answer_on_redraft=False)).answer(AUDIT_Q)
    assert r.status == "conflict"


def test_without_rulings_the_pair_is_a_conflict():
    r = RFPAgent(_conflict_then(answer_on_redraft=True), resolutions=()).answer(AUDIT_Q)
    assert r.status == "conflict" and "redraft_for_ruling" not in r.trace


# --- D31: answering every reading of an ambiguous question ---------------------------------

def _g(qid):
    return next(q for q in load_golden()["questions"] if q["id"] == qid)


def _res(answer, docs=(("KR-SLA-005", 1),)):
    return {"status": "answered", "answer": answer,
            "citations": [{"doc": d, "page": p, "quote": ""} for d, p in docs]}


def test_ambiguous_question_answered_for_every_reading_passes():
    g = _g("AMB-008")
    both = _res("For service availability: at least 99.9% monthly uptime. For support: Standard Support is "
                "available 08:00 to 20:00, Monday to Friday.", docs=(("KR-SLA-005", 1), ("KR-SUP-008", 1)))
    one = _res("The service has a 99.9% monthly uptime commitment.")
    assert score_one(g, both, set())["pass"] and not score_one(g, one, set())["pass"]
    m = aggregate([{"golden": g, "result": both, "score": score_one(g, both, set())},
                   {"golden": g, "result": one, "score": score_one(g, one, set())}])
    assert m["false_answer_rate"] == 0.5 and m["clarification_rate"] == 0.5


def test_ambiguous_questions_without_answer_facts_stay_strict():
    g = _g("AMB-001")                      # readings include a conflicted fact: must clarify
    assert not g.get("answer_all_facts")
    assert not score_one(g, _res("Backups are retained for 30 days."), set())["pass"]


# --- Borealis re-run (2026-09-23): the ruled audit-log answer was lost twice ------------------

def test_quote_stitched_across_two_cited_chunks_is_accepted_with_a_citation_each():
    """Live 4.7.1: one claim stated both figures, cited P2 and P1, and its quote joined a sentence
    from each. Every piece is verbatim in a cited chunk, so it now passes and cites both pages."""
    def draft(s, u):
        return {"status": "answered", "claims": [{
            "text": "Customer audit logs are retained for 1 year, and audit events are available through "
                    "the Audit Log API for 180 days.",
            "passage_ids": [_pid(u, "Audit Log API for 180 days"), _pid(u, ONE_YEAR)]}]}
    llm = ScriptedLLM({"classify": _cls(["audit log retention API 180 days 1 year"]), "draft": draft,
                       "verify": lambda s, u: {"results": [
                           {"claim_index": 0, "supported": True, "quote": f"{ONE_YEAR} ... {API_180}"}]}})
    r = RFPAgent(llm).answer(AUDIT_Q)
    assert r.status == "answered" and "1 year" in r.answer and "180 days" in r.answer
    assert {(c.doc, c.page) for c in r.citations} == {("KR-SEC-002", 3), ("KR-ARC-009", 3)}
    assert {c.quote for c in r.citations} == {ONE_YEAR, API_180}
    assert score_one(_g("COV-034"), r.to_dict(), set())["pass"]


def test_stitched_quote_with_a_piece_from_no_cited_chunk_is_rejected():
    from agents.pipeline import match_quote
    from tools.ingest import ingest
    chunks = [c for c in ingest() if ONE_YEAR.lower() in c.text.lower() or API_180.lower() in c.text.lower()]
    assert len(match_quote(f"{ONE_YEAR} ... {API_180}", chunks)) == 2
    assert match_quote(f"{ONE_YEAR} ... Audit events are available for 2 years.", chunks) == []
    assert match_quote(f"{ONE_YEAR} ... {API_180}", chunks[:1]) == []      # other page not cited


def test_repair_draft_keeps_the_reviewer_ruling():
    """Live 4.7.1: the repair draft was sent without the ruling, said "conflict", and was discarded."""
    seen = []

    def draft(s, u):
        seen.append("RES-001" in u)
        if "previous answer" not in u:            # first draft: one claim whose quote will fail
            return {"status": "answered", "claims": [
                {"text": ONE_YEAR, "passage_ids": [_pid(u, ONE_YEAR)]},
                {"text": "Audit events can be retrieved for 18 months.", "passage_ids": [_pid(u, API_180)]}]}
        return {"status": "answered", "claims": [
            {"text": ONE_YEAR, "passage_ids": [_pid(u, ONE_YEAR)]},
            {"text": API_180, "passage_ids": [_pid(u, "Audit Log API for 180 days")]}]}
    llm = ScriptedLLM({"classify": _cls(["audit log retention API 180 days 1 year"]), "draft": draft,
                       "verify": _verify_exact})
    r = RFPAgent(llm).answer(AUDIT_Q)
    assert seen == [True, True]
    assert r.status == "answered" and "1 year" in r.answer and "180 days" in r.answer
