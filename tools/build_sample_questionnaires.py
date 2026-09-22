"""Build the two fixed sample customer files shipped with the repo.

These are ordinary generator runs with pinned arguments, so they share one code
path and one answer-key format with anything you generate yourself:

  data/sample/questionnaires/northgate_security_questionnaire.xlsx (+ .key.yaml)
      every golden-set question, standard layout
  data/sample/questionnaires/northgate_rfp.docx (+ .key.yaml)
      a 20-question narrative RFP mixing all five categories

Northgate Mutual is a fictional buyer.

Run:  python -m tools.build_sample_questionnaires
"""
from __future__ import annotations

from pathlib import Path

from tools.generate_questionnaire import Spec, generate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "sample" / "questionnaires"
BUYER = "Northgate Mutual"

RFP_IDS = [
    "COV-006", "COV-001", "COV-004", "COV-008", "COV-010", "COV-012", "COV-024", "COV-027",
    "NC-001", "NC-006", "NC-009",
    "CF-001", "CF-006", "CF-010",
    "SEN-001", "SEN-005", "SEN-006",
    "AMB-004", "AMB-008", "AMB-001",
]

SAMPLES = [
    Spec(buyer=BUYER, fmt="xlsx", layout="standard", seed=20260922, out_dir=OUT,
         filename="northgate_security_questionnaire", doc_number="NGM-TPRM-2026"),
    Spec(buyer=BUYER, fmt="docx", layout="numbered", seed=20260922, out_dir=OUT, ids=RFP_IDS,
         shuffle_within_section=False, filename="northgate_rfp", doc_number="NGM-2026-114"),
]


def build() -> list[Path]:
    return [generate(spec)[0] for spec in SAMPLES]


if __name__ == "__main__":
    for p in build():
        print("wrote", p.relative_to(ROOT))
