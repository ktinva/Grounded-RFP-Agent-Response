"""Reviewed rulings on apparent conflicts (data/sample/resolutions.yaml).

  python -m tools.resolutions        # validate every ruling against the approved documents
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from tools.kb_text import get_page, load_manifest, normalize

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "sample" / "resolutions.yaml"
RULINGS = {"not_a_conflict"}


@dataclass(frozen=True)
class Resolution:
    id: str
    topic: str
    ruling: str
    statements: tuple[tuple[str, int, str], ...]     # (doc, page, quote)
    guidance: str
    decided_by: str
    decided_on: str

    def applies_to(self, passages: list) -> bool:
        """True if every statement of the ruling is among the retrieved passages (chunks)."""
        return all(any(c.doc_id == doc and c.page == page and normalize(q) in normalize(c.text) for c in passages)
                   for doc, page, q in self.statements)

    def prompt_text(self) -> str:
        quotes = "; ".join(f'"{q}" ({d} p.{p})' for d, p, q in self.statements)
        return (f"[{self.id}] A reviewer ruled that these statements do NOT conflict: {quotes}. "
                f"Guidance: {self.guidance.strip()}")


def validate(path: Path = DEFAULT_PATH) -> list[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    docs = load_manifest()
    errors, seen = [], set()
    for r in data.get("resolutions") or []:
        rid = r.get("id", "?")
        if rid in seen:
            errors.append(f"{rid}: duplicate id")
        seen.add(rid)
        if r.get("ruling") not in RULINGS:
            errors.append(f"{rid}: unknown ruling {r.get('ruling')!r}")
        for f in ("topic", "guidance", "decided_by", "decided_on"):
            if not r.get(f):
                errors.append(f"{rid}: missing {f}")
        stmts = r.get("statements") or []
        if len(stmts) < 2:
            errors.append(f"{rid}: needs at least two statements")
        for s in stmts:
            d = docs.get(s.get("doc"))
            if d is None or not d.approved:
                errors.append(f"{rid}: {s.get('doc')} is not an approved document")
                continue
            try:
                page = get_page(d, int(s["page"]))
            except (IndexError, KeyError, ValueError):
                errors.append(f"{rid}: bad page for {s.get('doc')}")
                continue
            if normalize(s.get("quote", "")) not in normalize(page):
                errors.append(f"{rid}: quote no longer on {s['doc']} p.{s['page']}: {s.get('quote')!r}")
    return errors


@lru_cache(maxsize=4)
def load(path: Path = DEFAULT_PATH) -> tuple[Resolution, ...]:
    if not path.exists():
        return ()
    errors = validate(path)
    if errors:
        raise ValueError("invalid resolutions file:\n  " + "\n  ".join(errors))
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return tuple(Resolution(
        id=r["id"], topic=r["topic"], ruling=r["ruling"],
        statements=tuple((s["doc"], int(s["page"]), s["quote"]) for s in r["statements"]),
        guidance=r["guidance"], decided_by=r["decided_by"], decided_on=str(r["decided_on"]))
        for r in data.get("resolutions") or [])


if __name__ == "__main__":
    errs = validate()
    n = len((yaml.safe_load(DEFAULT_PATH.read_text()) or {}).get("resolutions") or [])
    print(f"{n} ruling(s); " + ("all statements verified against approved documents" if not errs else "problems:"))
    for e in errs:
        print("  -", e)
    sys.exit(1 if errs else 0)
