"""Compare two scored runs of the same questionnaire: metric changes and questions that flipped.

  python -m evals.compare_runs evals/results/baseline_northgate_security_questionnaire \\
                               evals/results/northgate_security_questionnaire

Each argument is a run folder (or its scorecard.json).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

METRICS = ["pass_rate", "false_answer_rate", "covered_accuracy", "over_abstention", "conflict_recall",
           "false_conflicts", "escalation_recall", "routing_accuracy", "clarification_rate", "trap_citations",
           "consistency_issues"]
LOWER_IS_BETTER = {"false_answer_rate", "over_abstention", "false_conflicts", "trap_citations"}


def load(path: str | Path) -> dict:
    p = Path(path)
    p = p / "scorecard.json" if p.is_dir() else p
    return json.loads(p.read_text())


def _fmt(v) -> str:
    return "n/a" if v is None else (f"{v:.0%}" if isinstance(v, float) else str(v))


def compare(old: dict, new: dict) -> str:
    mo, mn = old["metrics"], new["metrics"]
    L = [f"# {old.get('file')} : before vs after", "", "| Metric | Before | After | |", "|---|---|---|---|"]
    for k in METRICS:
        a, b = mo.get(k), mn.get(k)
        if a is None and b is None:
            continue
        mark = ""
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a != b:
            better = (b < a) if k in LOWER_IS_BETTER else (b > a)
            mark = "better" if better else "**worse**"
        L.append(f"| {k.replace('_', ' ')} | {_fmt(a)} | {_fmt(b)} | {mark} |")
    ro = {r["ref"]: r for r in old.get("rows", [])}
    rn = {r["ref"]: r for r in new.get("rows", [])}
    fixed = [ref for ref in rn if ref in ro and rn[ref]["score"]["pass"] and not ro[ref]["score"]["pass"]]
    broke = [ref for ref in rn if ref in ro and not rn[ref]["score"]["pass"] and ro[ref]["score"]["pass"]]
    L += ["", f"## Now passing ({len(fixed)})"]
    L += [f"- {ref} ({rn[ref]['golden_id']}): {ro[ref]['result']['status']} -> {rn[ref]['result']['status']}"
          for ref in fixed]
    L += ["", f"## Now failing ({len(broke)})"]
    L += [f"- {ref} ({rn[ref]['golden_id']}): {ro[ref]['result']['status']} -> {rn[ref]['result']['status']} "
          f"({rn[ref]['score']['why']})" for ref in broke]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("before")
    ap.add_argument("after")
    a = ap.parse_args(argv)
    print(compare(load(a.before), load(a.after)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
