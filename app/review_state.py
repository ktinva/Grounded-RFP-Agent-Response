"""Reviewer decisions for one agent run, kept beside the run's results.

A run folder (written by agents.run_questionnaire or evals.run_evals) contains:
  results.jsonl       agent output, one record per question (never modified here)
  run.json            which customer file the run was made from
  review_state.json   reviewer decisions (this module)

Decisions:
  approved   the agent's answer is accepted unchanged (only for status "answered")
  edited     the reviewer's own wording is used (any status); marked as human-written
  rejected   nothing is written back for this question
  (absent)   pending; nothing is written back
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DECISIONS = ("approved", "edited", "rejected")
CHOICES = ("", "Yes", "No", "N/A")


class ReviewError(ValueError):
    pass


@dataclass
class Decision:
    decision: str
    final_answer: str = ""
    choice: str = ""                 # Yes / No / N/A for questionnaires with a choice column
    reviewer: str = ""
    note: str = ""
    decided_at: str = ""
    human_written: bool = False


@dataclass
class Run:
    folder: Path
    source: Path | None
    results: list[dict]
    decisions: dict[str, Decision] = field(default_factory=dict)

    # --- loading / saving ----------------------------------------------------
    @classmethod
    def load(cls, folder: str | Path) -> "Run":
        folder = Path(folder)
        results_path = folder / "results.jsonl"
        if not results_path.exists():
            raise ReviewError(f"{folder} has no results.jsonl")
        results = [json.loads(l) for l in results_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        meta = json.loads((folder / "run.json").read_text()) if (folder / "run.json").exists() else {}
        source = Path(meta["source"]) if meta.get("source") else None
        if source is None or not source.exists():      # folder moved, or run made elsewhere
            source = guess_source(folder) or source
        state_path = folder / "review_state.json"
        decisions = {}
        if state_path.exists():
            for ref, d in json.loads(state_path.read_text(encoding="utf-8")).get("decisions", {}).items():
                decisions[ref] = Decision(**d)
        return cls(folder=folder, source=source, results=results, decisions=decisions)

    def save(self) -> None:
        payload = {"decisions": {ref: asdict(d) for ref, d in self.decisions.items()}}
        tmp = self.folder / "review_state.json.tmp"
        tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.folder / "review_state.json")

    # --- queries ---------------------------------------------------------------
    def result(self, ref: str) -> dict:
        for r in self.results:
            if r["ref"] == ref:
                return r
        raise ReviewError(f"unknown question ref {ref!r}")

    def status_of(self, ref: str) -> str:
        d = self.decisions.get(ref)
        return d.decision if d else "pending"

    def progress(self) -> dict[str, int]:
        counts = {"approved": 0, "edited": 0, "rejected": 0, "pending": 0}
        for r in self.results:
            counts[self.status_of(r["ref"])] += 1
        return counts

    # --- decisions -------------------------------------------------------------
    def decide(self, ref: str, decision: str, final_answer: str | None = None, choice: str = "",
               reviewer: str = "", note: str = "") -> Decision:
        r = self.result(ref)
        if decision not in DECISIONS:
            raise ReviewError(f"decision must be one of {DECISIONS}")
        if choice not in CHOICES:
            raise ReviewError(f"choice must be one of {CHOICES[1:]}")
        if decision == "approved":
            if r["status"] != "answered":
                raise ReviewError(f"{ref} has status {r['status']!r}; only answered questions can be approved "
                                  "as-is. Write the answer yourself with 'edited' instead.")
            text, human = r["answer"], False
        elif decision == "edited":
            text = (final_answer or "").strip()
            if not text:
                raise ReviewError("an edited decision needs the final answer text")
            human = True
        else:
            text, human = "", False
        d = Decision(decision=decision, final_answer=text, choice=choice, reviewer=reviewer, note=note,
                     decided_at=dt.datetime.now().isoformat(timespec="seconds"), human_written=human)
        self.decisions[ref] = d
        return d

    def clear(self, ref: str) -> None:
        self.decisions.pop(ref, None)


def guess_source(folder: Path) -> Path | None:
    """Runs made before run.json existed: look for <folder name>.xlsx/.docx in the usual places."""
    root = Path(__file__).resolve().parents[1]
    for base in (root / "data" / "sample" / "questionnaires", root / "data" / "generated"):
        for ext in (".xlsx", ".xlsm", ".docx"):
            p = base / f"{folder.name}{ext}"
            if p.exists():
                return p
    return None


def write_run_meta(folder: Path, source: Path) -> None:
    (folder / "run.json").write_text(json.dumps({
        "source": str(Path(source).resolve()),
        "created": dt.datetime.now().isoformat(timespec="seconds"),
    }, indent=1), encoding="utf-8")
