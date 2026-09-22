"""The agents and the orchestrator that runs them for each question.

Per question:
  1. Policy rules      hard escalation list and missing-attachment check (no model call)
  2. Classifier        topic, sensitivity, ambiguity, search queries
  3. Retriever         hybrid search over APPROVED chunks only
  4. Drafter           answer / insufficient / conflict / clarification, with cited claims
  5. Verifier          independent claim-by-claim check; quotes must match the source text exactly
  6. Router            owner team for anything a human must handle

Every question ends in exactly one of five statuses (design decision D6).
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Iterable

from agents import policy
from agents.llm import LLM
from agents.prompts import (CLASSIFIER_SCHEMA, CLASSIFIER_SYSTEM, DRAFTER_SCHEMA, DRAFTER_SYSTEM,
                            VERIFIER_SCHEMA, VERIFIER_SYSTEM)
from tools.ingest import Chunk
from tools.kb_text import normalize
from tools.search_kb import Hit, KBIndex, default_index

STATUSES = ("answered", "insufficient_evidence", "conflict", "escalated", "needs_clarification")


@dataclass
class Citation:
    doc: str
    page: int
    chunk_id: str
    doc_title: str
    quote: str


@dataclass
class Result:
    ref: str
    question: str
    status: str
    answer: str = ""
    citations: list[Citation] = field(default_factory=list)
    route_to: str | None = None
    route_reason: str = ""
    clarification_options: list[str] = field(default_factory=list)
    conflict: dict | None = None
    related_excerpts: list[Citation] = field(default_factory=list)   # attached for human reviewers
    trace: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- helpers

def _passages(hits: list[Hit]) -> tuple[str, dict[str, Chunk]]:
    """Render retrieved chunks as P1..Pn so the model never handles raw chunk ids."""
    ids: dict[str, Chunk] = {}
    blocks = []
    for i, h in enumerate(hits, 1):
        pid = f"P{i}"
        c = h.chunk
        ids[pid] = c
        blocks.append(f"[{pid}] {c.doc_title} (v{c.version}), page {c.page}, {c.section or ''}\n{c.text}")
    return "\n\n".join(blocks), ids


def _quote_in(quote: str, text: str) -> bool:
    q = normalize(quote).strip(" .\"'")
    return len(q) >= 5 and q in normalize(text)


def _num_norm(s: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3})", "", normalize(s))


def _cite(c: Chunk, quote: str) -> Citation:
    return Citation(doc=c.doc_id, page=c.page, chunk_id=c.chunk_id, doc_title=c.doc_title, quote=quote)


def _excerpts(hits: list[Hit], n: int = 2, min_lexical: float = 0.15) -> list[Citation]:
    out = []
    for h in hits[:n]:
        if h.lexical >= min_lexical:
            first = re.split(r"(?<=[.!?])\s+", h.chunk.text)[0]
            out.append(_cite(h.chunk, first))
    return out


# --------------------------------------------------------------------------- agents

class Classifier:
    def __init__(self, llm: LLM):
        self.llm = llm

    def __call__(self, question: str, section: str | None) -> dict:
        user = f"Questionnaire section: {section or 'unknown'}\nQuestion: {question}"
        out = self.llm.json(system=CLASSIFIER_SYSTEM, user=user, schema=CLASSIFIER_SCHEMA,
                            purpose="classify", max_tokens=600)
        out.setdefault("search_queries", [])
        out["topic"] = out.get("topic") if out.get("topic") in policy.TOPICS else "general"
        return out


class Drafter:
    def __init__(self, llm: LLM):
        self.llm = llm

    def __call__(self, question: str, passages_text: str) -> dict:
        user = f"Question: {question}\n\nPassages:\n{passages_text}"
        return self.llm.json(system=DRAFTER_SYSTEM, user=user, schema=DRAFTER_SCHEMA,
                             purpose="draft", max_tokens=1500)


class Verifier:
    """Checks claims independently, then re-checks the model's quotes mechanically."""

    def __init__(self, llm: LLM):
        self.llm = llm

    def __call__(self, claims: list[dict], pid_map: dict[str, Chunk]) -> list[dict]:
        items, prepared = [], []
        for i, cl in enumerate(claims):
            chunks = [pid_map[p] for p in cl.get("passage_ids", []) if p in pid_map]
            prepared.append(chunks)
            src = "\n---\n".join(c.text for c in chunks) or "(no valid source cited)"
            items.append(f"Claim {i}: {cl.get('text', '')}\nSource text:\n{src}")
        out = self.llm.json(system=VERIFIER_SYSTEM, user="\n\n=====\n\n".join(items),
                            schema=VERIFIER_SCHEMA, purpose="verify", max_tokens=1500)
        by_idx = {r.get("claim_index"): r for r in out.get("results", [])}
        results = []
        for i, (cl, chunks) in enumerate(zip(claims, prepared)):
            r = by_idx.get(i, {"supported": False, "reason": "verifier returned no result"})
            quote = (r.get("quote") or "").strip()
            src = next((c for c in chunks if quote and _quote_in(quote, c.text)), None)
            ok = bool(r.get("supported")) and src is not None
            reason = r.get("reason", "")
            if r.get("supported") and src is None:
                reason = "quote not found verbatim in the cited source"
            results.append({"claim": cl.get("text", ""), "supported": ok, "reason": reason,
                            "quote": quote if ok else "", "chunk": src})
        return results


# --------------------------------------------------------------------------- orchestrator

class RFPAgent:
    def __init__(self, llm: LLM, index: KBIndex | None = None, top_k: int = 8):
        self.llm = llm
        self.index = index or default_index()
        self.top_k = top_k
        self.classify = Classifier(llm)
        self.draft = Drafter(llm)
        self.verify = Verifier(llm)

    # public -----------------------------------------------------------------
    def answer(self, question: str, ref: str = "", section: str | None = None) -> Result:
        res = Result(ref=ref, question=question, status="insufficient_evidence")
        t = res.trace

        # 1. policy rules: no model involved
        rule = policy.match_escalation(question)
        if rule:
            hits = self.index.search(question, k=self.top_k)
            res.status, res.route_to, res.route_reason = "escalated", rule.team, rule.reason
            res.related_excerpts = _excerpts(hits)
            t["rule"] = rule.name
            return res
        if policy.references_missing_attachment(question):
            res.status = "needs_clarification"
            res.clarification_options = ["Please provide the referenced attachment; it was not included."]
            res.route_to, res.route_reason = "solutions_engineering", "Referenced document is missing."
            t["rule"] = "missing_attachment"
            return res

        # 2. classifier
        cls = self.classify(question, section)
        t["classifier"] = cls
        owner = policy.topic_owner(cls["topic"])
        queries = [question] + list(cls.get("search_queries", []))[:3]
        hits = self.index.search(queries, k=self.top_k)
        t["retrieved"] = [h.chunk.chunk_id for h in hits]

        if cls.get("sensitive"):
            res.status, res.route_to = "escalated", owner
            res.route_reason = cls.get("sensitive_reason") or "Flagged as sensitive by the classifier."
            res.related_excerpts = _excerpts(hits)
            return res
        if cls.get("ambiguous") and len(cls.get("clarification_options") or []) >= 2:
            res.status = "needs_clarification"
            res.clarification_options = cls["clarification_options"]
            return res

        # 3-4. retrieve + draft
        passages_text, pid_map = _passages(hits)
        d = self.draft(question, passages_text)
        t["draft"] = d
        status = d.get("status")

        if status == "needs_clarification":
            res.status = "needs_clarification"
            res.clarification_options = d.get("clarification_options") or []
            return res

        if status == "conflict":
            return self._finish_conflict(res, d, pid_map, owner)

        if status == "answered":
            return self._finish_answer(res, d, pid_map, owner, hits)

        return self._insufficient(res, d.get("missing") or "The approved documents do not address this question.",
                                  owner, hits)

    def answer_many(self, questions: Iterable[dict], workers: int = 4) -> list[Result]:
        qs = list(questions)

        def run(q: dict) -> Result:
            try:
                return self.answer(q["text"], ref=q.get("ref", ""), section=q.get("section"))
            except Exception as e:  # one bad call must not sink a whole questionnaire
                r = Result(ref=q.get("ref", ""), question=q["text"], status="escalated",
                           route_to="solutions_engineering", route_reason=f"Agent error: {e}")
                r.trace["error"] = repr(e)
                return r

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            return list(pool.map(run, qs))

    # internals --------------------------------------------------------------
    def _insufficient(self, res: Result, why: str, owner: str, hits: list[Hit]) -> Result:
        res.status = "insufficient_evidence"
        res.answer = ""
        res.route_to, res.route_reason = owner, why
        res.related_excerpts = _excerpts(hits)
        return res

    def _finish_answer(self, res: Result, d: dict, pid_map: dict[str, Chunk], owner: str,
                       hits: list[Hit]) -> Result:
        claims = [c for c in d.get("claims") or [] if c.get("text")]
        if not claims:
            return self._insufficient(res, "Draft had no cited claims.", owner, hits)
        checks = self.verify(claims, pid_map)
        res.trace["verification"] = [{k: v for k, v in c.items() if k != "chunk"} |
                                     {"chunk_id": c["chunk"].chunk_id if c["chunk"] else None} for c in checks]
        supported = [c for c in checks if c["supported"]]
        if len(supported) < len(checks):
            res.trace["dropped_claims"] = [c["claim"] for c in checks if not c["supported"]]
        if not supported:
            return self._insufficient(res, "No drafted claim could be verified against the cited documents.",
                                      owner, hits)
        # The answer is exactly the verified claims, in order: no unverified sentence can reach the customer.
        res.answer = " ".join(c["claim"].strip().rstrip(".") + "." for c in supported)
        seen = set()
        for c in supported:
            key = (c["chunk"].chunk_id, c["quote"])
            if key not in seen:
                seen.add(key)
                res.citations.append(_cite(c["chunk"], c["quote"]))
        res.status = "answered"
        if len(supported) < len(checks):
            res.route_to = owner
            res.route_reason = "Some drafted statements could not be verified and were removed; please review."
        return res

    def _finish_conflict(self, res: Result, d: dict, pid_map: dict[str, Chunk], owner: str) -> Result:
        conf = d.get("conflict") or {}
        sides = []
        for s in conf.get("sides") or []:
            c = pid_map.get(s.get("passage_id", ""))
            value = (s.get("value") or "").strip()
            # mechanical check: the stated value must literally appear in its source
            if c and value and _num_norm(value) in _num_norm(c.text):
                sides.append({"doc": c.doc_id, "page": c.page, "chunk_id": c.chunk_id,
                              "doc_title": c.doc_title, "value": value})
        docs = {s["doc"] for s in sides}
        values = {_num_norm(s["value"]) for s in sides}
        if len(docs) < 2 or len(values) < 2:
            res.trace["conflict_rejected"] = conf
            return self._insufficient(res, "A possible conflict was detected but could not be verified; "
                                           "please review the related documents.", owner, [])
        res.status = "conflict"
        res.conflict = {"topic": conf.get("topic", ""), "sources": sides}
        res.answer = "Approved documents disagree: " + "; ".join(
            f"{s['doc_title']} (p.{s['page']}) says {s['value']}" for s in sides) + "."
        res.citations = [Citation(s["doc"], s["page"], s["chunk_id"], s["doc_title"], s["value"]) for s in sides]
        res.route_to = owner
        res.route_reason = "Documents conflict; the owning team must confirm the correct figure and fix the source."
        return res


def results_to_jsonl(results: list[Result]) -> str:
    return "\n".join(json.dumps(r.to_dict(), ensure_ascii=False, default=str) for r in results) + "\n"
