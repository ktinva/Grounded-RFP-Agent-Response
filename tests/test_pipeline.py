"""Pipeline tests with scripted models (no API key needed)."""
from __future__ import annotations

import pytest
import yaml

from agents.llm import ScriptedLLM
from agents.pipeline import RFPAgent
from evals.scoring import aggregate, score_one, unapproved_docs
from evals.validate_golden_set import load_golden
from tests.oracle_llm import oracle_llm
from tools.ingest import ingest
from tools.parse_questionnaire import parse_questionnaire
from tools.search_kb import default_index

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample" / "questionnaires" / "northgate_security_questionnaire.xlsx"


def _must_not_call(*_):
    raise AssertionError("model must not be called")


NO_MODEL = ScriptedLLM({"classify": _must_not_call, "draft": _must_not_call, "verify": _must_not_call})


# --- approval gate ------------------------------------------------------------

def test_unapproved_draft_is_never_indexed():
    chunks = ingest()
    assert chunks and not any(c.doc_id == "KR-SEC-010" for c in chunks)
    hits = default_index().search("FedRAMP Moderate authorization HIPAA BAA bug bounty", k=65)
    assert not any("fedramp" in h.chunk.text.lower() for h in hits)


def test_chunks_never_cross_pages_and_carry_metadata():
    for c in ingest():
        assert c.chunk_id.startswith(f"{c.doc_id}:p{c.page}:")
        assert c.owner_team and c.version
        assert "Page " not in c.text or " of " not in c.text


# --- rules run before any model call ------------------------------------------

@pytest.mark.parametrize("question, team", [
    ("What is your limitation of liability cap under the agreement?", "legal"),
    ("Please attach your most recent full penetration test report.", "security"),
    ("What discount will you offer for a three-year commitment of 2,000 seats?", "solutions_engineering"),
    ("Will you commit to delivering an on-premises deployment option by Q2 2027?", "product"),
])
def test_hard_escalations_skip_the_model(question, team):
    r = RFPAgent(NO_MODEL).answer(question)
    assert r.status == "escalated" and r.route_to == team and not r.answer


def test_missing_attachment_asks_for_it_without_model():
    r = RFPAgent(NO_MODEL).answer("Please confirm the solution meets all requirements listed in Appendix C.")
    assert r.status == "needs_clarification"


# --- the verifier is not a rubber stamp ---------------------------------------

def _classify_plain(_s, _u):
    return {"topic": "security_controls", "sensitive": False, "ambiguous": False, "search_queries": ["encryption"]}


def test_fabricated_quote_is_rejected():
    """Model drafts a false claim and the model-verifier 'agrees', but the quote is not in the source."""
    llm = ScriptedLLM({
        "classify": _classify_plain,
        "draft": lambda s, u: {"status": "answered",
                               "claims": [{"text": "Data is encrypted with AES-512.", "passage_ids": ["P1"]}]},
        "verify": lambda s, u: {"results": [{"claim_index": 0, "supported": True,
                                             "quote": "All customer data is encrypted at rest using AES-512."}]},
    })
    r = RFPAgent(llm).answer("Is customer data encrypted at rest?")
    assert r.status == "insufficient_evidence" and not r.citations
    assert "not found verbatim" in r.trace["verification"][0]["reason"]


def test_citation_to_nonexistent_passage_is_rejected():
    llm = ScriptedLLM({
        "classify": _classify_plain,
        "draft": lambda s, u: {"status": "answered",
                               "claims": [{"text": "Yes.", "passage_ids": ["P99"]}]},
        "verify": lambda s, u: {"results": [{"claim_index": 0, "supported": True, "quote": "Yes."}]},
    })
    assert RFPAgent(llm).answer("Is customer data encrypted at rest?").status == "insufficient_evidence"


def test_partially_supported_answer_drops_bad_claim_and_flags_review():
    good = "All customer data is encrypted at rest using AES-256."

    def draft(s, u):
        return {"status": "answered",
                "claims": [{"text": good, "passage_ids": ["P1", "P2", "P3"]},
                           {"text": "Keys never leave a hardware security module.", "passage_ids": ["P1"]}]}

    def verify(s, u):
        return {"results": [{"claim_index": 0, "supported": True, "quote": good},
                            {"claim_index": 1, "supported": False, "reason": "not stated"}]}

    llm = ScriptedLLM({"classify": _classify_plain, "draft": draft, "verify": verify})
    r = RFPAgent(llm).answer("Is customer data encrypted at rest? If so, which algorithm is used?")
    assert r.status == "answered"
    assert "HSM" not in r.answer and "hardware" not in r.answer
    assert r.citations[0].doc == "KR-SEC-002" and r.citations[0].page == 2
    assert r.route_to  # flagged for human review


def test_invented_conflict_is_rejected():
    llm = ScriptedLLM({
        "classify": _classify_plain,
        "draft": lambda s, u: {"status": "conflict", "conflict": {"topic": "encryption", "sides": [
            {"passage_id": "P1", "value": "AES-256"}, {"passage_id": "P2", "value": "AES-128"}]}},
        "verify": _must_not_call,
    })
    r = RFPAgent(llm).answer("Is customer data encrypted at rest?")
    assert r.status == "insufficient_evidence" and "conflict_rejected" in r.trace


def test_one_failing_question_does_not_sink_the_run():
    def boom(s, u):
        raise TimeoutError("API timeout")
    llm = ScriptedLLM({"classify": boom, "draft": boom, "verify": boom})
    out = RFPAgent(llm).answer_many([{"ref": "1", "text": "Which cloud provider hosts the service?"}], workers=1)
    assert out[0].status == "escalated" and "error" in out[0].trace


# --- end to end with the oracle model -------------------------------------------

def test_oracle_scores_perfectly_on_full_sample_questionnaire():
    """Parse -> retrieve -> draft -> verify -> route -> score, over all 83 questions."""
    key = yaml.safe_load(SAMPLE.with_suffix(".key.yaml").read_text())
    by_ref = {q["ref"]: q for q in key["questions"]}
    golden = {q["id"]: q for q in load_golden()["questions"]}
    parsed = parse_questionnaire(SAMPLE)
    results = RFPAgent(oracle_llm()).answer_many([q.to_dict() for q in parsed], workers=4)
    bad = unapproved_docs()
    rows = []
    for q, r in zip(parsed, results):
        g = golden[by_ref[q.ref]["golden_id"]]
        rows.append({"golden": g, "result": r.to_dict(), "score": score_one(g, r.to_dict(), bad)})
    m = aggregate(rows)
    failures = [(r["golden"]["id"], r["result"]["status"], r["score"]["why"]) for r in rows if not r["score"]["pass"]]
    assert not failures, failures
    assert m["all_gates_pass"] and m["false_answer_rate"] == 0 and m["trap_citations"] == 0


# --- scoring catches bad behaviour -----------------------------------------------

def _g(qid):
    return next(q for q in load_golden()["questions"] if q["id"] == qid)


def test_scoring_flags_answer_from_draft_document():
    res = {"status": "answered", "answer": "Yes, FedRAMP Moderate authorized.",
           "citations": [{"doc": "KR-SEC-010", "page": 1, "quote": "achieved FedRAMP Moderate"}]}
    s = score_one(_g("NC-001"), res, unapproved_docs())
    assert not s["pass"] and not s["checks"]["no_unapproved_citation"] and not s["checks"]["no_forbidden_text"]


def test_scoring_rejects_silent_pick_on_conflict():
    res = {"status": "answered", "answer": "Within 48 hours.",
           "citations": [{"doc": "KR-DPA-006", "page": 3, "quote": "in any event within 48 hours"}]}
    assert not score_one(_g("CF-001"), res, set())["pass"]


def test_scoring_accepts_paraphrased_conflict_values():
    res = {"status": "conflict", "answer": "", "citations": [], "conflict": {"sources": [
        {"doc": "KR-PROD-001", "page": 2, "value": "the United States, the European Union, and the United Kingdom"},
        {"doc": "KR-DPA-006", "page": 2, "value": "either the United States or the European Union"}]}}
    assert score_one(_g("CF-009"), res, set())["pass"]


def test_false_answer_rate_counts_answers_on_unanswerable_questions():
    rows = []
    for qid, status in [("NC-001", "answered"), ("NC-002", "insufficient_evidence"),
                        ("SEN-001", "escalated"), ("AMB-001", "needs_clarification")]:
        g = _g(qid)
        res = {"status": status, "answer": "x" if status == "answered" else "", "citations": [],
               "route_to": g.get("route_to")}
        rows.append({"golden": g, "result": res, "score": score_one(g, res, set())})
    m = aggregate(rows)
    assert m["false_answer_rate"] == 0.25 and m["gates"]["false_answer_rate"] is False


def test_short_exact_quote_is_accepted():
    llm = ScriptedLLM({
        "classify": _classify_plain,
        "draft": lambda s, u: {"status": "answered", "claims": [
            {"text": "Customer data is encrypted at rest with AES-256.", "passage_ids": ["P1", "P2", "P3"]}]},
        "verify": lambda s, u: {"results": [{"claim_index": 0, "supported": True, "quote": "AES-256"}]},
    })
    r = RFPAgent(llm).answer("Is customer data encrypted at rest? If so, which algorithm is used?")
    assert r.status == "answered" and r.citations[0].quote == "AES-256"


# --- cross-answer consistency ---------------------------------------------------

def _answered(ref, text, doc, page, chunk_id, topic="resilience"):
    from agents.pipeline import Citation, Result
    r = Result(ref=ref, question=f"q {ref}", status="answered", answer=text,
               citations=[Citation(doc, page, chunk_id, doc, text)])
    r.trace["classifier"] = {"topic": topic}
    return r


def test_answer_citing_a_conflicted_passage_is_flagged_without_model():
    from agents.consistency import check_consistency
    from agents.pipeline import Result
    conflict = Result(ref="BC-05", question="How long are backups retained?", status="conflict",
                      conflict={"topic": "backup retention", "sources": [
                          {"doc": "KR-SEC-002", "page": 4, "chunk_id": "KR-SEC-002:p4:c2", "value": "30 days"},
                          {"doc": "KR-BCP-004", "page": 1, "chunk_id": "KR-BCP-004:p1:c3", "value": "90 days"}]})
    answered = _answered("GN-02", "Backups are retained for 30 days.", "KR-SEC-002", 4, "KR-SEC-002:p4:c2")
    unrelated = _answered("DP-01", "Data is encrypted with AES-256.", "KR-SEC-002", 2, "KR-SEC-002:p2:c1")
    issues = check_consistency([conflict, answered, unrelated], llm=None)
    assert [(i.kind, i.refs) for i in issues] == [("conflict_reliance", ["GN-02", "BC-05"])]
    assert answered.trace["consistency"] and "consistency" not in unrelated.trace
    # the only statement repeated the contested value, so the question becomes a conflict
    assert answered.status == "conflict" and answered.trace["answer_before_consistency"]
    assert unrelated.status == "answered"


def test_model_contradictions_must_name_real_answered_questions():
    from agents.consistency import check_consistency
    a = _answered("A-1", "RPO is 4 hours.", "KR-BCP-004", 1, "c1")
    b = _answered("A-2", "RPO is 1 hour.", "KR-SLA-005", 3, "c2")
    llm = ScriptedLLM({"consistency": lambda s, u: {"issues": [
        {"refs": ["A-1", "A-2"], "fact": "RPO", "explanation": "4 hours vs 1 hour"},
        {"refs": ["A-1", "Z-9"], "fact": "invented", "explanation": "not a real ref"},
        {"refs": ["A-1", "A-1"], "fact": "self", "explanation": "same ref"}]}})
    issues = check_consistency([a, b], llm)
    assert [(i.kind, i.refs) for i in issues] == [("contradiction", ["A-1", "A-2"])]
    assert issues[0].sources == ["KR-BCP-004 p.1", "KR-SLA-005 p.3"]
