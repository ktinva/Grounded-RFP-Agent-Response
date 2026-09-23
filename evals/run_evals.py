"""Run the agent over a questionnaire that has an answer key, and score it.

  # score the shipped samples
  python -m evals.run_evals data/sample/questionnaires/northgate_security_questionnaire.xlsx

  # generate a fresh questionnaire and score it in one go
  python -m tools.generate_questionnaire --buyer "Acme Health" --count 40 --layout yes_no --seed 7
  python -m evals.run_evals data/generated/acme_health_xlsx_yes_no_s7.xlsx

The answer key is read from <file>.key.yaml next to the questionnaire (or --key).
The agent only ever sees the customer file; the key is used afterwards to score.

Outputs in evals/results/<file stem>/:
  results.jsonl     raw agent output
  scorecard.md      metrics, release gates, and every failing question with the reason
  scorecard.json    the same, machine-readable
Exit code is 1 if any release gate fails (useful in CI).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from agents.consistency import check_consistency
from agents.llm import MissingAPIKey, get_llm
from app.review_state import write_run_meta
from agents.pipeline import RFPAgent, results_to_jsonl
from agents.run_questionnaire import review_markdown
from evals.scoring import GATES, aggregate, score_one, unapproved_docs
from evals.validate_golden_set import load_golden
from tools.parse_questionnaire import parse_questionnaire

ROOT = Path(__file__).resolve().parents[1]


def _pct(v) -> str:
    return "n/a" if v is None else (f"{v:.0%}" if isinstance(v, float) else str(v))


def scorecard_md(name: str, key: dict, m: dict, rows: list[dict], usage: dict | None,
                 issues: list | None = None) -> str:
    L = [f"# Scorecard: {name}", ""]
    L.append(f"Buyer: {key.get('buyer')} · layout: {key.get('layout')} · questions: {m['questions']} · "
             f"model: {m.get('model', 'n/a')} · overall pass: **{_pct(m['pass_rate'])}**")
    if not key.get("scored", True):
        L += ["", "> **Exploratory run:** this file uses unapproved rewordings, so these numbers are not "
                  "trusted scores."]
    if usage:
        L += ["", f"Model calls: {usage['calls']} ({usage['cached']} cached) · tokens in/out: "
                  f"{usage['input_tokens']:,}/{usage['output_tokens']:,}"]
    L += ["", "## Release gates", "", "| Metric | Value | Gate | Result |", "|---|---|---|---|"]
    for metric, (op, thr) in GATES.items():
        ok = m["gates"][metric]
        L.append(f"| {metric.replace('_', ' ')} | {_pct(m.get(metric))} | {op} {_pct(thr) if isinstance(thr, float) else thr} "
                 f"| {'n/a' if ok is None else ('PASS' if ok else '**FAIL**')} |")
    L += ["", f"Suggested-owner accuracy on not-covered questions (informational): "
              f"{_pct(m.get('suggested_owner_accuracy'))}",
          f"Over-escalation: not-covered questions escalated instead of marked insufficient (informational; "
          f"passes if routed to the right owner): {_pct(m.get('over_escalation'))}", "",
          "## By category", "", "| Category | n | Pass | Status distribution |", "|---|---|---|---|"]
    for c, v in m["by_category"].items():
        L.append(f"| {c} | {v['n']} | {_pct(v['pass'])} | {m['status_confusion'][c]} |")
    if issues is not None:
        L += ["", f"Cross-answer consistency issues flagged (informational): {len(issues)}"]
        for i in issues:
            L.append(f"- {i.kind}: {' vs '.join(i.refs)}: {i.detail}")
    fails = [r for r in rows if not r["score"]["pass"]]
    L += ["", f"## Failures ({len(fails)})", ""]
    for r in fails:
        g, res = r["golden"], r["result"]
        L.append(f"- **{r['ref']}** ({g['id']}, {g['category']}) · expected `{g['expected_status']}`, got "
                 f"`{res['status']}` · failed: {r['score']['why']}  \n  Q: {r['text']}"
                 + (f"  \n  A: {res['answer'][:300]}" if res.get("answer") else ""))
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--key", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-consistency", action="store_true", help="skip the cross-answer consistency check")
    a = ap.parse_args(argv)

    key_path = a.key or a.file.with_suffix(".key.yaml")
    if not key_path.exists():
        print(f"error: no answer key at {key_path}. Use agents.run_questionnaire for unscored runs.", file=sys.stderr)
        return 2
    key = yaml.safe_load(key_path.read_text())
    golden = {q["id"]: q for q in load_golden()["questions"]}
    by_ref = {q["ref"]: q for q in key["questions"]}

    parsed = parse_questionnaire(a.file)
    unknown = [q.ref for q in parsed if q.ref not in by_ref]
    if unknown:
        print(f"warning: {len(unknown)} parsed questions are not in the key and will not be scored: {unknown[:5]}")
    try:
        llm = get_llm()
    except MissingAPIKey as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    results = RFPAgent(llm).answer_many([q.to_dict() for q in parsed], workers=a.workers)
    for r, q in zip(results, parsed):
        r.trace["location"] = q.location
    issues = [] if a.no_consistency else check_consistency(results, llm)

    bad = unapproved_docs()
    rows = []
    for q, res in zip(parsed, results):
        k = by_ref.get(q.ref)
        if not k:
            continue
        g = golden[k["golden_id"]]
        rd = res.to_dict()
        rows.append({"ref": q.ref, "text": q.text, "golden": g, "variant": k["variant"],
                     "result": rd, "score": score_one(g, rd, bad)})
    m = aggregate(rows)
    m["consistency_issues"] = len(issues)
    m["model"] = getattr(llm, "model", None)
    usage = getattr(llm, "usage", None)
    usage = usage.to_dict() if usage else None

    out = a.out or ROOT / "evals" / "results" / a.file.stem
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.jsonl").write_text(results_to_jsonl(results), encoding="utf-8")
    write_run_meta(out, a.file)
    (out / "review.md").write_text(review_markdown(a.file.name, results, usage, issues), encoding="utf-8")
    (out / "scorecard.md").write_text(scorecard_md(a.file.name, key, m, rows, usage, issues), encoding="utf-8")
    (out / "scorecard.json").write_text(json.dumps({"file": a.file.name, "scored": key.get("scored", True),
                                                    "metrics": m, "usage": usage,
                                                    "consistency_issues": [i.to_dict() for i in issues],
                                                    "rows": [{k_: v for k_, v in r.items() if k_ != "golden"}
                                                             | {"golden_id": r["golden"]["id"]} for r in rows]},
                                                   indent=1, default=str), encoding="utf-8")
    print(f"pass {_pct(m['pass_rate'])} · false-answer rate {_pct(m['false_answer_rate'])} · "
          f"gates {'PASS' if m['all_gates_pass'] else 'FAIL'}")
    print(f"Wrote {out / 'scorecard.md'}")
    return 0 if m["all_gates_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
