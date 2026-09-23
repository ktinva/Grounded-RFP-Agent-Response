"""Re-score an existing run with the current golden set and scoring rules, without calling the model.

  python -m evals.rescore evals/results/northgate_security_questionnaire [--consistency]

Use after changing scoring rules or golden-set expectations. --consistency also re-applies the
rule-based consistency resolution (agents/consistency.py) to the saved answers.
Writes scorecard.md / scorecard.json in the run folder (the previous ones are kept as *.prev).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from agents.consistency import check_consistency
from agents.pipeline import Citation, Result
from app.review_state import Run
from evals.run_evals import scorecard_md
from evals.scoring import aggregate, score_one, unapproved_docs
from evals.validate_golden_set import load_golden


def load_results(folder: Path) -> list[Result]:
    out = []
    for line in (folder / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        d["citations"] = [Citation(**c) for c in d.get("citations") or []]
        d["related_excerpts"] = [Citation(**c) for c in d.get("related_excerpts") or []]
        out.append(Result(**d))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_folder", type=Path)
    ap.add_argument("--key", type=Path)
    ap.add_argument("--consistency", action="store_true")
    a = ap.parse_args(argv)

    run = Run.load(a.run_folder)
    key_path = a.key or (run.source.with_suffix(".key.yaml") if run.source else None)
    if not key_path or not key_path.exists():
        print("error: answer key not found; pass --key", file=sys.stderr)
        return 2
    key = yaml.safe_load(key_path.read_text())
    by_ref = {q["ref"]: q for q in key["questions"]}
    golden = {q["id"]: q for q in load_golden()["questions"]}

    results = load_results(a.run_folder)
    issues = None
    if a.consistency:
        for r in results:
            r.trace.pop("consistency", None)
        issues = check_consistency(results)
    old = {}
    if (a.run_folder / "scorecard.json").exists():
        old = json.loads((a.run_folder / "scorecard.json").read_text())
    bad = unapproved_docs()
    rows = []
    for r in results:
        k = by_ref.get(r.ref)
        if not k:
            continue
        g = golden[k["golden_id"]]
        rd = r.to_dict()
        rows.append({"ref": r.ref, "text": r.question, "golden": g, "variant": k["variant"],
                     "result": rd, "score": score_one(g, rd, bad)})
    m = aggregate(rows)
    m["model"] = (old.get("metrics") or {}).get("model")
    m["consistency_issues"] = len(issues) if issues is not None else (old.get("metrics") or {}).get("consistency_issues")
    m["rescored"] = True
    for name in ("scorecard.md", "scorecard.json"):
        p = a.run_folder / name
        if p.exists():
            p.replace(a.run_folder / f"{name}.prev")
    (a.run_folder / "scorecard.md").write_text(
        scorecard_md(a.run_folder.name + " (re-scored)", key, m, rows, old.get("usage"), issues), encoding="utf-8")
    (a.run_folder / "scorecard.json").write_text(json.dumps({
        "file": old.get("file", key.get("file")), "scored": key.get("scored", True), "metrics": m,
        "usage": old.get("usage"), "rows": [{k_: v for k_, v in r.items() if k_ != "golden"}
                                            | {"golden_id": r["golden"]["id"]} for r in rows]},
        indent=1, default=str), encoding="utf-8")
    print(f"pass {m['pass_rate']:.0%} · false-answer rate {m['false_answer_rate']:.0%} · "
          f"gates {'PASS' if m['all_gates_pass'] else 'FAIL'}  (re-scored, no model calls)")
    return 0 if m["all_gates_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
