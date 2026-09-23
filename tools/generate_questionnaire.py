"""Generate a new customer questionnaire or RFP, plus its answer key.

Examples
  # 40-question Excel questionnaire, default category mix, yes/no layout
  python -m tools.generate_questionnaire --buyer "Acme Health" --format xlsx --layout yes_no --count 40

  # Word RFP weighted toward security topics, half the questions reworded
  python -m tools.generate_questionnaire --buyer "Borealis Bank" --format docx --layout table \\
      --mix covered=8,not_covered=4,conflict=6,sensitive=5,ambiguous=3 \\
      --sections "Data Protection,Compliance,Incident Response,Business Continuity,Legal and Commercial,General" \\
      --reworded 0.5 --seed 11

Outputs (default folder data/generated/):
  <buyer>_<format>_<layout>_s<seed>.<xlsx|docx>      the customer file (no labels inside)
  <same name>.key.yaml                                answer key: ref -> golden id + wording used

The same arguments and seed always produce the same file.

Rewordings: only APPROVED rewordings are used unless --include-pending is given.
Files built with pending rewordings are marked `scored: false` in the key, so the
eval runner reports them separately from trusted results.
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from evals.validate_golden_set import load_golden
from tools import rewordings as rw
from tools.questionnaire_formats import DOCX_LAYOUTS, XLSX_LAYOUTS, DocMeta, write_docx, write_xlsx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "generated"
CATEGORIES = ("covered", "not_covered", "conflict", "sensitive", "ambiguous")
# Default proportions, roughly those of a real questionnaire run through this corpus.
DEFAULT_SHARE = {"covered": 0.40, "not_covered": 0.17, "conflict": 0.15, "sensitive": 0.16, "ambiguous": 0.12}
SECTION_ORDER = [
    "Company Information", "Security Program", "Compliance", "Identity and Access",
    "Data Protection", "Hosting and Deployment", "Logging and Monitoring",
    "Vulnerability Management", "Incident Response", "Business Continuity", "Availability",
    "Privacy", "AI and Data Use", "Product Capabilities", "Integrations", "Support",
    "Legal and Commercial", "General",
]


@dataclass
class Spec:
    buyer: str
    fmt: str = "xlsx"
    layout: str | None = None
    count: int | None = None
    mix: dict[str, int] | None = None
    sections: list[str] | None = None
    reworded: float = 0.0
    include_pending: bool = False
    seed: int = 1
    ids: list[str] | None = None          # explicit golden ids (overrides count/mix/sections)
    order: str = "section"                # section | as_given
    shuffle_within_section: bool = True
    doc_number: str | None = None
    due_date: str = "30 October 2026"
    out_dir: Path = DEFAULT_OUT
    filename: str | None = None
    fictional_note: bool = True
    rewordings_store: Path | None = None  # default: evals/rewordings.yaml (tests pass their own copy)
    notes: list[str] = field(default_factory=list)


class SpecError(ValueError):
    pass


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def parse_mix(text: str) -> dict[str, int]:
    mix = {}
    for part in filter(None, (p.strip() for p in text.split(","))):
        k, _, v = part.partition("=")
        k = k.strip()
        if k not in CATEGORIES:
            raise SpecError(f"unknown category {k!r} in --mix; use {', '.join(CATEGORIES)}")
        mix[k] = int(v)
    return mix


def default_mix(count: int) -> dict[str, int]:
    """Largest-remainder apportionment; every category gets >= 1 when count >= 5."""
    raw = {c: count * DEFAULT_SHARE[c] for c in CATEGORIES}
    mix = {c: int(raw[c]) for c in CATEGORIES}
    if count >= len(CATEGORIES):
        for c in CATEGORIES:
            mix[c] = max(mix[c], 1)
    while sum(mix.values()) < count:
        c = max(CATEGORIES, key=lambda c: raw[c] - mix[c])
        mix[c] += 1
    while sum(mix.values()) > count:
        c = max((c for c in CATEGORIES if mix[c] > 1), key=lambda c: mix[c] - raw[c])
        mix[c] -= 1
    return mix


def select(spec: Spec, golden: list[dict], rng: random.Random) -> list[dict]:
    by_id = {q["id"]: q for q in golden}
    if spec.ids:
        missing = [i for i in spec.ids if i not in by_id]
        if missing:
            raise SpecError(f"unknown golden ids: {missing}")
        return [by_id[i] for i in spec.ids]

    pool = golden
    if spec.sections:
        unknown = set(spec.sections) - {q["section"] for q in golden}
        if unknown:
            raise SpecError(f"unknown section(s) {sorted(unknown)}; available: "
                            f"{sorted({q['section'] for q in golden})}")
        pool = [q for q in golden if q["section"] in spec.sections]

    if spec.mix:
        mix = {c: spec.mix.get(c, 0) for c in CATEGORIES}
    else:
        count = spec.count or len(pool)
        if count >= len(pool):
            return list(pool)
        mix = default_mix(count)

    chosen: list[dict] = []
    for cat in CATEGORIES:
        avail = [q for q in pool if q["category"] == cat]
        if mix[cat] > len(avail):
            raise SpecError(f"asked for {mix[cat]} {cat} questions but only {len(avail)} exist"
                            + (" in the chosen sections" if spec.sections else "")
                            + ". Lower the number or add questions to evals/golden_set.yaml.")
        chosen += rng.sample(avail, mix[cat])
    return chosen


def choose_wording(q: dict, spec: Spec, rng: random.Random, bank: dict[str, list[dict]]) -> dict:
    original = {"variant": "original", "variant_status": "approved", "text": q["question"]}
    if spec.reworded <= 0 or rng.random() >= spec.reworded:
        return original
    allowed = {"approved", "pending"} if spec.include_pending else {"approved"}
    options = [r for r in bank.get(q["id"], []) if r["status"] in allowed]
    if not options:
        return original
    r = rng.choice(options)
    return {"variant": r["id"], "variant_status": r["status"], "text": r["text"]}


def order_items(chosen: list[dict], spec: Spec, rng: random.Random) -> list[dict]:
    if spec.order == "as_given":
        return chosen
    rank = {s: i for i, s in enumerate(SECTION_ORDER)}
    out: list[dict] = []
    for section in sorted({q["section"] for q in chosen}, key=lambda s: rank.get(s, 99)):
        group = [q for q in chosen if q["section"] == section]
        if spec.shuffle_within_section:
            rng.shuffle(group)
        out += group
    return out


def generate(spec: Spec) -> tuple[Path, Path, dict]:
    if spec.fmt not in ("xlsx", "docx"):
        raise SpecError("--format must be xlsx or docx")
    layouts = XLSX_LAYOUTS if spec.fmt == "xlsx" else DOCX_LAYOUTS
    layout = spec.layout or layouts[0]
    if layout not in layouts:
        raise SpecError(f"layout {layout!r} is not valid for {spec.fmt}; choose from {layouts}")
    if not 0 <= spec.reworded <= 1:
        raise SpecError("--reworded must be between 0 and 1")

    rng = random.Random(spec.seed)
    golden = load_golden()["questions"]
    bank = rw.load(spec.rewordings_store) if spec.rewordings_store else rw.load()

    chosen = order_items(select(spec, golden, rng), spec, rng)
    wordings = [choose_wording(q, spec, rng, bank) for q in chosen]
    items = [{"section": q["section"], "text": w["text"]} for q, w in zip(chosen, wordings)]

    spec.out_dir.mkdir(parents=True, exist_ok=True)
    name = spec.filename or f"{slug(spec.buyer)}_{spec.fmt}_{layout}_s{spec.seed}"
    path = spec.out_dir / f"{name}.{spec.fmt}"
    meta = DocMeta(buyer=spec.buyer, doc_number=spec.doc_number or f"{slug(spec.buyer)[:3].upper()}-{spec.seed:04d}",
                   due_date=spec.due_date, fictional_note=spec.fictional_note)
    writer = write_xlsx if spec.fmt == "xlsx" else write_docx
    refs = writer(layout, items, path, meta)

    uses_pending = any(w["variant_status"] == "pending" for w in wordings)
    key = {
        "file": path.name,
        "buyer": spec.buyer,
        "format": spec.fmt,
        "layout": layout,
        "seed": spec.seed,
        "scored": not uses_pending,
        "questions": [
            {"ref": ref, "golden_id": q["id"], "category": q["category"], "variant": w["variant"],
             "variant_status": w["variant_status"], "text": w["text"]}
            for ref, q, w in zip(refs, chosen, wordings)
        ],
    }
    if uses_pending:
        key["warning"] = ("Built with unapproved rewordings. Results are useful for exploration but are "
                          "not counted as trusted scores until the rewordings are approved.")
    key_path = path.with_suffix(".key.yaml")
    header = ("# Answer key generated by tools/generate_questionnaire.py.\n"
              "# Maps each questionnaire ref to its golden-set question. Never give this file to the agent.\n")
    key_path.write_text(header + yaml.safe_dump(key, sort_keys=False, allow_unicode=True, width=120),
                        encoding="utf-8")
    return path, key_path, key


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--buyer", required=True, help="fictional buyer name shown in the document")
    ap.add_argument("--format", dest="fmt", choices=["xlsx", "docx"], default="xlsx")
    ap.add_argument("--layout", help=f"xlsx: {', '.join(XLSX_LAYOUTS)} | docx: {', '.join(DOCX_LAYOUTS)}")
    ap.add_argument("--count", type=int, help="total questions, split using the default category mix")
    ap.add_argument("--mix", help="exact counts, e.g. covered=10,not_covered=4,conflict=3,sensitive=3,ambiguous=2")
    ap.add_argument("--sections", help="comma-separated section names to draw from")
    ap.add_argument("--reworded", type=float, default=0.0, help="fraction of questions to reword (0-1)")
    ap.add_argument("--include-pending", action="store_true", help="allow unapproved rewordings (unscored)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--name", help="output file name without extension")
    a = ap.parse_args(argv)

    if a.count and a.mix:
        ap.error("use either --count or --mix, not both")
    spec = Spec(buyer=a.buyer, fmt=a.fmt, layout=a.layout, count=a.count,
                mix=parse_mix(a.mix) if a.mix else None,
                sections=[s.strip() for s in a.sections.split(",")] if a.sections else None,
                reworded=a.reworded, include_pending=a.include_pending, seed=a.seed,
                out_dir=a.out, filename=a.name)
    try:
        path, key_path, key = generate(spec)
    except SpecError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    cats = {c: sum(1 for q in key["questions"] if q["category"] == c) for c in CATEGORIES}
    reworded = sum(1 for q in key["questions"] if q["variant"] != "original")
    print(f"Wrote {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")
    print(f"      {key_path.name}")
    print(f"  {len(key['questions'])} questions  " + "  ".join(f"{c}={n}" for c, n in cats.items() if n))
    print(f"  reworded: {reworded}   scored: {key['scored']}")
    if spec.reworded and reworded == 0 and not spec.include_pending:
        print("  note: no approved rewordings exist yet; run `python -m tools.rewordings export` to review them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
