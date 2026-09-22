"""Run the agent over any questionnaire or RFP and write a review package.

  python -m agents.run_questionnaire data/sample/questionnaires/northgate_rfp.docx
  python -m agents.run_questionnaire path/to/customer.xlsx --out results/customer --workers 4

Outputs in --out (default evals/results/<file name>/):
  results.jsonl   one record per question: status, answer, citations, routing, full trace
  review.md       reviewer-friendly report grouped by status

No answer key is needed. To score a run against the golden set, use evals.run_evals.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from agents.llm import MissingAPIKey, get_llm
from agents.pipeline import STATUSES, RFPAgent, Result, results_to_jsonl
from tools.parse_questionnaire import parse_questionnaire

ROOT = Path(__file__).resolve().parents[1]
LABEL = {"answered": "Answered (cited)", "insufficient_evidence": "Insufficient evidence",
         "conflict": "Conflict between documents", "escalated": "Escalated",
         "needs_clarification": "Needs clarification"}


def review_markdown(source: str, results: list[Result], usage: dict | None = None) -> str:
    counts = Counter(r.status for r in results)
    lines = [f"# Review: {source}", "",
             " | ".join(f"**{LABEL[s]}**: {counts.get(s, 0)}" for s in STATUSES), ""]
    if usage:
        lines += [f"_Model calls: {usage['calls']} ({usage['cached']} from cache), "
                  f"tokens in/out: {usage['input_tokens']:,}/{usage['output_tokens']:,}_", ""]
    for s in ("conflict", "escalated", "insufficient_evidence", "needs_clarification", "answered"):
        group = [r for r in results if r.status == s]
        if not group:
            continue
        lines += [f"## {LABEL[s]} ({len(group)})", ""]
        for r in group:
            lines.append(f"### {r.ref}: {r.question}")
            if r.answer:
                lines.append(f"> {r.answer}")
            for c in r.citations:
                lines.append(f"- Source: **{c.doc_title}** ({c.doc}, p.{c.page}): \"{c.quote}\"")
            if r.clarification_options:
                lines.append("- Ask the customer which they mean: " + "; ".join(r.clarification_options))
            if r.route_to:
                lines.append(f"- Route to **{r.route_to.replace('_', ' ')}**: {r.route_reason}")
            for c in r.related_excerpts:
                lines.append(f"- Related (for the reviewer, not an answer): {c.doc} p.{c.page}: \"{c.quote}\"")
            lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)

    qs = parse_questionnaire(a.file)
    print(f"Parsed {len(qs)} questions from {a.file.name}")
    try:
        llm = get_llm()
    except MissingAPIKey as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    agent = RFPAgent(llm)
    results = agent.answer_many([q.to_dict() for q in qs], workers=a.workers)
    for r, q in zip(results, qs):
        r.trace["location"] = q.location

    out = a.out or ROOT / "evals" / "results" / a.file.stem
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.jsonl").write_text(results_to_jsonl(results), encoding="utf-8")
    usage = getattr(llm, "usage", None)
    (out / "review.md").write_text(review_markdown(a.file.name, results, usage.to_dict() if usage else None),
                                   encoding="utf-8")
    print(json.dumps(dict(Counter(r.status for r in results))))
    print(f"Wrote {out / 'review.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
