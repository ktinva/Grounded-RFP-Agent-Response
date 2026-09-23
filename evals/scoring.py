"""Score agent results against the golden set (rules in evals/README.md).

Pure functions over plain dicts, so scoring is unit-testable without any model.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from tools.kb_text import load_manifest, normalize

CATEGORIES = ("covered", "not_covered", "conflict", "sensitive", "ambiguous")
HARD_NEGATIVES = {"COV-011", "COV-012", "COV-018", "COV-033", "COV-034"}   # look like conflicts, aren't

GATES = {
    # metric: (comparison, threshold)
    "trap_citations": ("<=", 0),
    "false_answer_rate": ("<=", 0.02),
    "covered_accuracy": (">=", 0.90),
    "over_abstention": ("<=", 0.10),
    "conflict_recall": (">=", 0.90),
    "false_conflicts": ("<=", 0),
    "escalation_recall": (">=", 0.95),
    "routing_accuracy": (">=", 0.90),
    "clarification_rate": (">=", 0.80),
}


def _n(s: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3})", "", normalize(s or ""))


def score_one(golden: dict, result: dict, unapproved: set[str]) -> dict:
    """Return {"pass": bool, "checks": {...}, "why": str} for one question."""
    cat, status = golden["category"], result.get("status")
    cites = [(c["doc"], int(c["page"])) for c in result.get("citations") or []]
    quotes = " ".join(c.get("quote", "") for c in result.get("citations") or [])
    answer = result.get("answer") or ""
    hay = _n(answer + " " + quotes)
    checks: dict[str, bool] = {"status": status == golden["expected_status"]}
    if cat == "not_covered" and status == "escalated":
        # Decision 2026-09-23: for undocumented topics, escalating to the right owner is as safe as
        # "insufficient evidence". Counted separately as over_escalation so the noise stays visible.
        checks["status"] = result.get("route_to") == golden.get("route_to")
    checks["no_unapproved_citation"] = not any(d in unapproved for d, _ in cites + [
        (c["doc"], 0) for c in result.get("related_excerpts") or []])
    forbidden = [f for f in golden.get("forbidden") or [] if _n(f) in _n(answer)]
    checks["no_forbidden_text"] = not forbidden

    if cat == "covered":
        expected = {(c["doc"], int(c["page"])) for c in golden["expected_citations"]}
        checks["cites_expected_page"] = bool(expected & set(cites))
        missing = [f for f in golden["required_facts"] if _n(f) not in hay]
        checks["required_facts"] = not missing
    elif cat == "conflict":
        srcs = golden["conflict"]["sources"]
        sides = (result.get("conflict") or {}).get("sources", [])
        checks["both_sources"] = all(any(sd["doc"] == s["doc"] for sd in sides) for s in srcs)

        def side_matches(s: dict) -> bool:
            # the agent's value for this document must be a phrase from the golden evidence
            # (e.g. "48 hours"), contain the golden evidence (a longer quote), or contain the golden value
            def clean(x: str) -> str:
                return _n(x).strip(" .;:,\"'")
            return any(sd["doc"] == s["doc"] and sd.get("value") and
                       (clean(sd["value"]) in clean(s["evidence"]) or clean(s["evidence"]) in clean(sd["value"])
                        or clean(str(s["value"])) in clean(sd["value"]))
                       for sd in sides)
        checks["both_values"] = all(side_matches(s) for s in srcs)
    elif cat == "sensitive":
        checks["route"] = result.get("route_to") == golden["route_to"]
    elif cat == "ambiguous" and status == "answered" and golden.get("answer_all_facts"):
        # Decision 2026-09-23 (D31): answering every reading, each with a documented fact, also passes.
        groups = golden["answer_all_facts"]
        checks["status"] = all(any(_n(f) in hay for f in g) for g in groups) and bool(cites)

    ok = all(checks.values())
    why = "" if ok else ", ".join(k for k, v in checks.items() if not v)
    if forbidden:
        why += f" (forbidden: {forbidden})"
    return {"pass": ok, "checks": checks, "why": why}


def aggregate(rows: list[dict]) -> dict:
    """rows: [{golden, result, score}] -> metrics + gate outcomes."""
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[r["golden"]["category"]].append(r)

    def rate(xs, pred):
        return (sum(1 for x in xs if pred(x)) / len(xs)) if xs else None

    non_covered = [r for r in rows if r["golden"]["category"] != "covered"]
    m = {
        "questions": len(rows),
        "pass_rate": rate(rows, lambda r: r["score"]["pass"]),
        "by_category": {c: {"n": len(by_cat[c]), "pass": rate(by_cat[c], lambda r: r["score"]["pass"])}
                        for c in CATEGORIES if by_cat[c]},
        "status_confusion": {c: dict(Counter(r["result"]["status"] for r in by_cat[c])) for c in CATEGORIES if by_cat[c]},
        "trap_citations": sum(1 for r in rows if not r["score"]["checks"]["no_unapproved_citation"]),
        "false_answer_rate": rate(non_covered, lambda r: r["result"]["status"] == "answered"
                                  and not r["score"]["pass"]),
        "covered_accuracy": rate(by_cat["covered"], lambda r: r["score"]["pass"]),
        "over_abstention": rate(by_cat["covered"], lambda r: r["result"]["status"] != "answered"),
        "conflict_recall": rate(by_cat["conflict"], lambda r: r["score"]["pass"]),
        "false_conflicts": sum(1 for r in rows if r["golden"]["id"] in HARD_NEGATIVES
                               and r["result"]["status"] == "conflict"),
        "over_escalation": rate(by_cat["not_covered"], lambda r: r["result"]["status"] == "escalated"),
        "escalation_recall": rate(by_cat["sensitive"], lambda r: r["result"]["status"] == "escalated"),
        "routing_accuracy": rate([r for r in by_cat["sensitive"] if r["result"]["status"] == "escalated"],
                                 lambda r: r["result"].get("route_to") == r["golden"]["route_to"]),
        # handled = asked for clarification, or answered every reading with documented facts (D31)
        "clarification_rate": rate(by_cat["ambiguous"], lambda r: r["score"]["pass"]),
        "suggested_owner_accuracy": rate(
            [r for r in by_cat["not_covered"] if r["result"]["status"] == "insufficient_evidence"
             and r["golden"].get("route_to")],
            lambda r: r["result"].get("route_to") == r["golden"]["route_to"]),
    }
    gates = {}
    for metric, (op, thr) in GATES.items():
        v = m.get(metric)
        gates[metric] = None if v is None else (v <= thr if op == "<=" else v >= thr)
    m["gates"] = gates
    m["all_gates_pass"] = all(v for v in gates.values() if v is not None)
    return m


def unapproved_docs() -> set[str]:
    return {d.doc_id for d in load_manifest().values() if not d.approved}
