"""Validate evals/golden_set.yaml against the rendered knowledge-base PDFs.

This keeps the golden set honest: a test case that cites a page which does not
actually say the thing would reward the wrong behaviour. Checks:

  * schema: unique ids, id prefix matches category, status matches category, teams valid
  * every cited doc exists, is APPROVED, and the page exists
  * every evidence quote appears verbatim (whitespace/case-normalized) on the cited page
  * every required fact appears in at least one evidence quote
  * conflicts: >= 2 sources from different docs with different values, value inside its quote
  * not-covered: no absent_term appears (whole word) in ANY approved document
  * trap docs: exist, are NOT approved, and really contain the tempting claim

Run:  python -m evals.validate_golden_set
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import yaml

from tools.kb_text import get_page, load_manifest, normalize

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "evals" / "golden_set.yaml"

CATEGORY_STATUS = {
    "covered": "answered",
    "not_covered": "insufficient_evidence",
    "conflict": "conflict",
    "sensitive": "escalated",
    "ambiguous": "needs_clarification",
}
CATEGORY_PREFIX = {"covered": "COV", "not_covered": "NC", "conflict": "CF",
                   "sensitive": "SEN", "ambiguous": "AMB"}
MIN_PER_CATEGORY = 10


def load_golden(path: Path = GOLDEN) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _contains_term(text: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(normalize(term))}(?![a-z0-9])", normalize(text)) is not None


def _check_citation(qid: str, cite: dict, docs, errors: list[str], label: str) -> None:
    doc = docs.get(cite.get("doc"))
    if doc is None:
        errors.append(f"{qid}: {label} cites unknown doc {cite.get('doc')}")
        return
    if not doc.approved:
        errors.append(f"{qid}: {label} cites unapproved doc {doc.doc_id}")
        return
    try:
        text = get_page(doc, int(cite["page"]))
    except (IndexError, KeyError, ValueError) as e:
        errors.append(f"{qid}: {label} bad page: {e}")
        return
    ev = cite.get("evidence")
    if not ev:
        errors.append(f"{qid}: {label} {doc.doc_id} p{cite['page']} has no evidence quote")
    elif normalize(ev) not in normalize(text):
        errors.append(f"{qid}: {label} quote not found on {doc.doc_id} p{cite['page']}: {ev!r}")


def validate(golden: dict | None = None) -> tuple[list[str], Counter]:
    golden = golden or load_golden()
    docs = load_manifest()
    teams = set(golden["teams"])
    approved_text = {d.doc_id: " ".join(get_page(d, p) for p in range(1, d.pages + 1))
                     for d in docs.values() if d.approved}
    errors: list[str] = []
    counts: Counter = Counter()
    seen: set[str] = set()

    for q in golden["questions"]:
        qid, cat = q.get("id", "?"), q.get("category")
        counts[cat] += 1

        # --- schema ---------------------------------------------------------
        if qid in seen:
            errors.append(f"{qid}: duplicate id")
        seen.add(qid)
        if cat not in CATEGORY_STATUS:
            errors.append(f"{qid}: unknown category {cat!r}")
            continue
        if not qid.startswith(CATEGORY_PREFIX[cat] + "-"):
            errors.append(f"{qid}: id prefix does not match category {cat}")
        if q.get("expected_status") != CATEGORY_STATUS[cat]:
            errors.append(f"{qid}: expected_status should be {CATEGORY_STATUS[cat]}")
        for field in ("question", "section"):
            if not q.get(field):
                errors.append(f"{qid}: missing {field}")
        if "route_to" in q and q["route_to"] not in teams:
            errors.append(f"{qid}: route_to {q['route_to']!r} not in {sorted(teams)}")

        # --- trap docs --------------------------------------------------------
        if trap := q.get("trap_doc"):
            tdoc = docs.get(trap)
            if tdoc is None:
                errors.append(f"{qid}: trap_doc {trap} not in manifest")
            elif tdoc.approved:
                errors.append(f"{qid}: trap_doc {trap} must NOT be approved")
            else:
                trap_text = " ".join(get_page(tdoc, p) for p in range(1, tdoc.pages + 1))
                bait = q.get("absent_terms", []) + q.get("forbidden", [])
                if not any(_contains_term(trap_text, t) for t in bait):
                    errors.append(f"{qid}: trap_doc {trap} does not contain any bait term {bait}")

        # --- per category ----------------------------------------------------
        if cat == "covered":
            cites = q.get("expected_citations") or []
            if not cites:
                errors.append(f"{qid}: covered question needs expected_citations")
            for c in cites:
                _check_citation(qid, c, docs, errors, "citation")
            quotes = " ".join(normalize(c.get("evidence", "")) for c in cites)
            for fact in q.get("required_facts") or []:
                if normalize(fact) not in quotes:
                    errors.append(f"{qid}: required fact {fact!r} not in any evidence quote")
            if not q.get("required_facts"):
                errors.append(f"{qid}: covered question needs required_facts")

        elif cat == "not_covered":
            terms = q.get("absent_terms") or []
            if not terms:
                errors.append(f"{qid}: not_covered question needs absent_terms")
            for term in terms:
                for doc_id, text in approved_text.items():
                    if _contains_term(text, term):
                        errors.append(f"{qid}: absent term {term!r} appears in approved doc {doc_id}")

        elif cat == "conflict":
            conf = q.get("conflict") or {}
            sources = conf.get("sources") or []
            if len(sources) < 2:
                errors.append(f"{qid}: conflict needs >= 2 sources")
            if len({s.get("doc") for s in sources}) < 2:
                errors.append(f"{qid}: conflict sources must come from different documents")
            if len({normalize(str(s.get("value"))) for s in sources}) < 2:
                errors.append(f"{qid}: conflict sources must have different values")
            for s in sources:
                _check_citation(qid, s, docs, errors, "conflict source")
            if not conf.get("topic"):
                errors.append(f"{qid}: conflict needs a topic")

        elif cat == "sensitive":
            if not q.get("route_to"):
                errors.append(f"{qid}: sensitive question needs route_to")
            for c in q.get("supporting_evidence") or []:
                _check_citation(qid, c, docs, errors, "supporting evidence")

        elif cat == "ambiguous":
            if not q.get("clarification_options"):
                errors.append(f"{qid}: ambiguous question needs clarification_options")

    for cat in CATEGORY_STATUS:
        if counts[cat] < MIN_PER_CATEGORY:
            errors.append(f"category {cat} has {counts[cat]} questions (< {MIN_PER_CATEGORY})")

    return errors, counts


def main() -> int:
    errors, counts = validate()
    total = sum(counts.values())
    print(f"Golden set: {total} questions  " +
          "  ".join(f"{c}={n}" for c, n in counts.items()))
    if errors:
        print(f"\n{len(errors)} problem(s):")
        for e in errors:
            print("  -", e)
        return 1
    print("All citations, evidence quotes, conflicts, and absent-term checks verified against the PDFs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
