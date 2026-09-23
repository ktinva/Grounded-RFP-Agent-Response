"""Tests for the questionnaire generator, the rewording review workflow, and the parser."""
from __future__ import annotations

import pytest
from openpyxl import load_workbook

from agents.pipeline import RFPAgent
from evals.scoring import aggregate, score_one, unapproved_docs
from evals.validate_golden_set import load_golden
from tests.oracle_llm import oracle_llm
from tools import rewordings as rw
from tools.generate_questionnaire import CATEGORIES, Spec, SpecError, default_mix, generate
from tools.parse_questionnaire import parse_questionnaire
from tools.questionnaire_formats import DOCX_LAYOUTS, XLSX_LAYOUTS

LAYOUTS = [("xlsx", l) for l in XLSX_LAYOUTS] + [("docx", l) for l in DOCX_LAYOUTS]


@pytest.mark.parametrize("n", [5, 12, 25, 40, 83])
def test_default_mix_adds_up_and_covers_every_category(n):
    mix = default_mix(n)
    assert sum(mix.values()) == n and all(mix[c] >= 1 for c in CATEGORIES)


@pytest.mark.parametrize("fmt, layout", LAYOUTS)
def test_every_layout_round_trips_through_the_parser(tmp_path, fmt, layout):
    path, _, key = generate(Spec(buyer="Test Buyer", fmt=fmt, layout=layout, count=20, seed=5,
                                 reworded=0.6, include_pending=True, out_dir=tmp_path))
    parsed = parse_questionnaire(path)
    assert [(q.ref, q.text) for q in parsed] == [(q["ref"], q["text"]) for q in key["questions"]]
    assert all(q.section for q in parsed)


def test_same_seed_same_questionnaire(tmp_path):
    a = generate(Spec(buyer="A", count=30, seed=9, out_dir=tmp_path / "1"))[2]
    b = generate(Spec(buyer="A", count=30, seed=9, out_dir=tmp_path / "2"))[2]
    c = generate(Spec(buyer="A", count=30, seed=10, out_dir=tmp_path / "3"))[2]
    assert a["questions"] == b["questions"] and a["questions"] != c["questions"]


def test_mix_and_sections_are_respected(tmp_path):
    secs = ["Business Continuity", "Incident Response", "Data Protection"]
    key = generate(Spec(buyer="B", mix={"covered": 3, "conflict": 4}, sections=secs, seed=2, out_dir=tmp_path))[2]
    golden = {q["id"]: q for q in load_golden()["questions"]}
    cats = [q["category"] for q in key["questions"]]
    assert cats.count("covered") == 3 and cats.count("conflict") == 4 and len(cats) == 7
    assert all(golden[q["golden_id"]]["section"] in secs for q in key["questions"])


def test_asking_for_too_many_is_a_clear_error(tmp_path):
    with pytest.raises(SpecError, match="only 15 exist"):
        generate(Spec(buyer="C", mix={"sensitive": 16}, out_dir=tmp_path))


def _bank_copy(tmp_path, status_for):
    """Copy of the real rewordings with statuses set by the test, so results don't depend on
    what has been approved in evals/rewordings.yaml."""
    bank = rw.load()
    for items in bank.values():
        for i, r in enumerate(items):
            r["status"] = status_for(i)
    store = tmp_path / "rewordings.yaml"
    rw.save(bank, store)
    return store


def test_unapproved_rewordings_are_excluded_unless_asked(tmp_path):
    store = _bank_copy(tmp_path, lambda i: "approved" if i == 0 else "pending")   # R1 approved, R2 pending
    approved = {r["id"] for items in rw.load(store).values() for r in items if r["status"] == "approved"}

    trusted = generate(Spec(buyer="D", count=30, reworded=1.0, seed=3, out_dir=tmp_path / "t",
                            rewordings_store=store))[2]
    assert trusted["scored"] is True
    assert all(q["variant"] == "original" or q["variant"] in approved for q in trusted["questions"])
    assert any(q["variant"] in approved for q in trusted["questions"])

    explore = generate(Spec(buyer="D", count=30, reworded=1.0, include_pending=True, seed=3,
                            out_dir=tmp_path / "e", rewordings_store=store))[2]
    assert explore["scored"] is False and "warning" in explore
    assert any(q["variant_status"] == "pending" for q in explore["questions"])


def test_customer_file_never_contains_labels(tmp_path):
    path, key_path, _ = generate(Spec(buyer="E", count=25, seed=4, out_dir=tmp_path))
    text = " ".join(str(c.value) for ws in load_workbook(path).worksheets for row in ws.iter_rows() for c in row if c.value)
    for word in ("covered", "not_covered", "COV-", "SEN-", "insufficient_evidence", "golden"):
        assert word not in text


def test_rewording_review_round_trip(tmp_path):
    real_before = rw.REWORDINGS.read_bytes()
    store = _bank_copy(tmp_path, lambda i: "pending")          # start from an all-pending copy
    sheet = tmp_path / "review.xlsx"
    assert rw.export_review(sheet, store=store) == sum(len(v) for v in rw.load(store).values())

    wb = load_workbook(sheet)
    ws = wb["Review"]
    decisions = {"COV-001-R1": ("approve", None), "COV-001-R2": ("edit", "Which algorithm encrypts data at rest?"),
                 "CF-010-R2": ("reject", None)}
    for row in ws.iter_rows(min_row=2):
        if row[0].value in decisions:
            d, text = decisions[row[0].value]
            row[6].value, row[7].value, row[8].value = d, text, "reviewer@example.com"
    wb.save(sheet)

    assert dict(rw.import_review(sheet, store=store)) == {"approve": 1, "edit": 1, "reject": 1}
    after = {r["id"]: r for items in rw.load(store).values() for r in items}
    assert after["COV-001-R1"]["status"] == "approved"
    assert after["COV-001-R2"]["status"] == "approved" and after["COV-001-R2"]["text"].startswith("Which algorithm")
    assert after["CF-010-R2"]["status"] == "rejected" and after["CF-010-R2"]["reviewer"] == "reviewer@example.com"
    assert not rw.validate(rw.load(store), {q["id"] for q in load_golden()["questions"]})
    # the real bank is untouched (all edits went to the temp copy)
    assert rw.REWORDINGS.read_bytes() == real_before


def test_oracle_end_to_end_on_generated_reworded_file(tmp_path):
    """New layout + reworded questions + a docx table: the full chain still scores perfectly."""
    path, _, key = generate(Spec(buyer="Borealis Bank", fmt="docx", layout="table", count=30, seed=11,
                                 reworded=0.7, include_pending=True, out_dir=tmp_path))
    golden = {q["id"]: q for q in load_golden()["questions"]}
    by_ref = {q["ref"]: q for q in key["questions"]}
    parsed = parse_questionnaire(path)
    results = RFPAgent(oracle_llm()).answer_many([q.to_dict() for q in parsed], workers=4)
    bad = unapproved_docs()
    rows = []
    for q, r in zip(parsed, results):
        g = golden[by_ref[q.ref]["golden_id"]]
        rows.append({"golden": g, "result": r.to_dict(), "score": score_one(g, r.to_dict(), bad)})
    fails = [(r["golden"]["id"], r["result"]["status"], r["score"]["why"]) for r in rows if not r["score"]["pass"]]
    assert not fails, fails
    assert aggregate(rows)["all_gates_pass"]
