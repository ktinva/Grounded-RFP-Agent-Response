"""A scripted 'perfect model' built from the golden set, for plumbing tests.

It behaves the way a correct model should on each golden question, using ONLY
what the pipeline actually hands it (the question text and retrieved passages).
If the pipeline drops the right passage, mangles ids, or mis-scores a correct
answer, tests using this oracle fail. It says nothing about real model quality.
"""
from __future__ import annotations

import re

from agents.llm import ScriptedLLM
from evals.validate_golden_set import load_golden
from tools import rewordings as rw
from tools.kb_text import load_manifest, normalize

PASSAGE_RE = re.compile(r"^\[(P\d+)\] (.+?) \(v[^)]*\), page (\d+), .*?\n(.*?)(?=\n\n\[P\d+\] |\Z)", re.S | re.M)


def _golden_by_text() -> dict[str, dict]:
    out = {}
    bank = rw.load()
    for q in load_golden()["questions"]:
        out[normalize(q["question"])] = q
        for r in bank.get(q["id"], []):
            out[normalize(r["text"])] = q
    return out


def _question(user: str) -> str:
    m = re.search(r"Question: (.*?)(\n|$)", user)
    return m.group(1).strip() if m else ""


def _passages(user: str) -> list[dict]:
    title_to_doc = {d.title: d.doc_id for d in load_manifest().values()}
    return [{"pid": m.group(1), "doc": title_to_doc.get(m.group(2)), "page": int(m.group(3)), "text": m.group(4)}
            for m in PASSAGE_RE.finditer(user)]


def oracle_llm() -> ScriptedLLM:
    golden = _golden_by_text()

    def classify(_s, user):
        q = golden[normalize(_question(user))]
        return {"topic": "general", "sensitive": q["category"] == "sensitive",
                "sensitive_reason": "oracle", "ambiguous": q["category"] == "ambiguous",
                "clarification_options": q.get("clarification_options", []) * 2 if q["category"] == "ambiguous" else [],
                "search_queries": [e["evidence"] for e in q.get("expected_citations", [])][:2]
                + [s["evidence"] for s in (q.get("conflict") or {}).get("sources", [])]}

    def draft(_s, user):
        q = golden[normalize(_question(user))]
        ps = _passages(user)
        if q["category"] == "covered":
            claims = []
            for e in q["expected_citations"]:
                p = next((p for p in ps if p["doc"] == e["doc"] and p["page"] == e["page"]
                          and normalize(e["evidence"]) in normalize(p["text"])), None)
                if p:
                    claims.append({"text": e["evidence"], "passage_ids": [p["pid"]]})
            if not claims:
                return {"status": "insufficient_evidence", "missing": "oracle: expected passage not retrieved"}
            return {"status": "answered", "claims": claims}
        if q["category"] == "conflict":
            sides = []
            for s in q["conflict"]["sources"]:
                p = next((p for p in ps if p["doc"] == s["doc"] and normalize(s["evidence"]) in normalize(p["text"])), None)
                if p:
                    sides.append({"passage_id": p["pid"], "value": s["evidence"]})
            return {"status": "conflict", "conflict": {"topic": q["conflict"]["topic"], "sides": sides}}
        return {"status": "insufficient_evidence", "missing": "oracle"}

    def verify(_s, user):
        results = []
        for i, block in enumerate(user.split("\n\n=====\n\n")):
            claim = re.search(r"Claim \d+: (.*?)\nSource text:", block, re.S).group(1)
            src = block.split("Source text:\n", 1)[1]
            ok = normalize(claim) in normalize(src)
            results.append({"claim_index": i, "supported": ok, "quote": claim if ok else ""})
        return {"results": results}

    return ScriptedLLM({"classify": classify, "draft": draft, "verify": verify})
