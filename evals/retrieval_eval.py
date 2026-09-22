"""Measure search quality against the golden set, without calling any model.

For each question (original wording, plus every rewording):
  covered    hit if ANY expected citation page is in the top-k chunks
  conflict   hit if BOTH sides of the conflict are in the top-k (both-sides recall)
  sensitive  hit if the supporting excerpt (when one exists) is in the top-k

Also reports the "evidence floor": the best lexical similarity for covered vs
not-covered questions, which shows whether retrieval scores alone could separate
answerable from unanswerable questions (they cannot; see design decision D11).

Run:  python -m evals.retrieval_eval [--k 8]
"""
from __future__ import annotations

import argparse
import statistics
from collections import defaultdict

from evals.validate_golden_set import load_golden
from tools import rewordings as rw
from tools.search_kb import default_index


def targets(q: dict) -> tuple[list[set[tuple[str, int]]], str]:
    """Return groups of acceptable (doc, page); every group must be hit."""
    if q["category"] == "covered":
        return [{(c["doc"], c["page"]) for c in q["expected_citations"]}], "any expected page"
    if q["category"] == "conflict":
        return [{(s["doc"], s["page"])} for s in q["conflict"]["sources"]], "both sides"
    if q["category"] == "sensitive" and q.get("supporting_evidence"):
        return [{(c["doc"], c["page"]) for c in q["supporting_evidence"]}], "supporting excerpt"
    return [], ""


def run(k: int = 8) -> dict:
    idx = default_index()
    golden = load_golden()["questions"]
    bank = rw.load()
    stats: dict[tuple[str, str], list[bool]] = defaultdict(list)
    misses: list[str] = []
    floor: dict[str, list[float]] = defaultdict(list)
    for q in golden:
        wordings = [("original", q["question"])] + [(r["status"], r["text"]) for r in bank.get(q["id"], [])
                                                     if r["status"] != "rejected"]
        groups, _ = targets(q)
        for kind, text in wordings:
            hits = idx.search(text, k=k)
            got = {(h.chunk.doc_id, h.chunk.page) for h in hits}
            if kind == "original":
                floor[q["category"]].append(max(h.lexical for h in hits))
            if not groups:
                continue
            ok = all(g & got for g in groups)
            stats[(q["category"], "original" if kind == "original" else "reworded")].append(ok)
            if not ok:
                misses.append(f"{q['id']} [{kind}] {text}")
    return {"stats": stats, "misses": misses, "floor": floor, "k": k}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--show-misses", action="store_true")
    a = ap.parse_args()
    res = run(a.k)
    print(f"Retrieval recall@{a.k} (approved documents only, raw question as query)\n")
    print(f"{'category':<12} {'wording':<10} {'recall':>7}  n")
    for (cat, kind), v in sorted(res["stats"].items()):
        print(f"{cat:<12} {kind:<10} {sum(v)/len(v):>7.0%}  {len(v)}")
    print("\nBest lexical similarity of top hit (original wording):")
    for cat, v in res["floor"].items():
        print(f"  {cat:<12} median {statistics.median(v):.2f}  min {min(v):.2f}  max {max(v):.2f}")
    if a.show_misses:
        print("\nMisses:")
        for m in res["misses"]:
            print("  -", m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
