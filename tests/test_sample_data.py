"""Tests for the sample knowledge base, golden eval set, and sample questionnaires."""
from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path

import pytest
import yaml
from docx import Document
from openpyxl import load_workbook

from evals.validate_golden_set import load_golden, validate
from tools.kb_text import get_page, load_manifest, normalize

ROOT = Path(__file__).resolve().parents[1]
QDIR = ROOT / "data" / "sample" / "questionnaires"


@pytest.fixture(scope="module")
def docs():
    return load_manifest()


@pytest.fixture(scope="module")
def golden():
    return load_golden()


# --- knowledge base ---------------------------------------------------------

def test_manifest_matches_pdfs(docs):
    for d in docs.values():
        assert d.file.exists(), d.file
        manifest = yaml.safe_load((d.file.parent / "manifest.yaml").read_text())
        entry = next(e for e in manifest["documents"] if e["doc_id"] == d.doc_id)
        assert hashlib.sha256(d.file.read_bytes()).hexdigest() == entry["sha256"], \
            f"{d.doc_id}: PDF changed without rebuilding the manifest"


def test_printed_page_numbers_match_pdf_pages(docs):
    """Citations use the printed footer; it must equal the physical page index."""
    for d in docs.values():
        for p in range(1, d.pages + 1):
            assert f"Page {p} of {d.pages}" in get_page(d, p), f"{d.doc_id} page {p}"


def test_exactly_one_unapproved_trap_document(docs):
    unapproved = [d for d in docs.values() if not d.approved]
    assert [d.doc_id for d in unapproved] == ["KR-SEC-010"]
    assert "draft - not approved" in normalize(get_page(unapproved[0], 1))


def test_every_approved_doc_has_owner_and_version(docs):
    for d in docs.values():
        if d.approved:
            assert d.owner_team in {"legal", "security", "product", "solutions_engineering"}
            assert d.version and d.effective_date


# --- golden set -------------------------------------------------------------

def test_golden_set_is_valid(golden):
    errors, counts = validate(golden)
    assert not errors, "\n".join(errors)
    assert sum(counts.values()) >= 80


@pytest.mark.parametrize("mutation, expected_error", [
    (lambda g: g["questions"][0]["expected_citations"][0].update(page=3), "quote not found"),
    (lambda g: g["questions"][0]["expected_citations"][0].update(doc="KR-SEC-010"), "unapproved doc"),
    (lambda g: next(q for q in g["questions"] if q["id"] == "NC-001")["absent_terms"].append("SOC 2"),
     "appears in approved doc"),
    (lambda g: next(q for q in g["questions"] if q["id"] == "CF-001")["conflict"]["sources"][1].update(value="72 hours"),
     "different values"),
    (lambda g: next(q for q in g["questions"] if q["id"] == "SEN-001").update(route_to="sales"), "not in"),
    (lambda g: g["questions"].append(copy.deepcopy(g["questions"][0])), "duplicate id"),
])
def test_validator_catches_broken_cases(golden, mutation, expected_error):
    """The validator must not be vacuous: each deliberate break is reported."""
    broken = copy.deepcopy(golden)
    mutation(broken)
    errors, _ = validate(broken)
    assert any(expected_error in e for e in errors), errors


def test_conflicts_come_in_pairs(golden):
    """Each planted conflict is asked two different ways."""
    topics = [q["conflict"]["topic"] for q in golden["questions"] if q["category"] == "conflict"]
    assert all(topics.count(t) == 2 for t in topics)


# --- sample questionnaires --------------------------------------------------

def _xlsx_questions() -> dict[str, str]:
    ws = load_workbook(QDIR / "northgate_security_questionnaire.xlsx")["Vendor Security Assessment"]
    rows = {}
    for ref, _section, question, *_ in ws.iter_rows(min_row=5, values_only=True):
        if ref:
            rows[ref] = question
    return rows


def _docx_questions() -> dict[str, str]:
    out = {}
    for p in Document(QDIR / "northgate_rfp.docx").paragraphs:
        m = re.match(r"^(4\.\d+\.\d+)\s+(.*)$", p.text)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def test_questionnaires_match_answer_keys(golden):
    by_id = {q["id"]: q["question"] for q in golden["questions"]}
    for name, parsed in [("northgate_security_questionnaire", _xlsx_questions()),
                         ("northgate_rfp", _docx_questions())]:
        key = yaml.safe_load((QDIR / f"{name}.key.yaml").read_text())
        refs = {q["ref"]: q for q in key["questions"]}
        assert set(parsed) == set(refs), name
        for ref, q in refs.items():
            assert parsed[ref] == q["text"] == by_id[q["golden_id"]], (name, ref)
    xlsx_key = yaml.safe_load((QDIR / "northgate_security_questionnaire.key.yaml").read_text())
    assert sorted(q["golden_id"] for q in xlsx_key["questions"]) == sorted(by_id)


def test_customer_files_do_not_leak_expected_behaviour():
    leaked = re.compile(r"\b(COV|NC|CF|SEN|AMB)-\d{3}\b|not_covered|needs_clarification|"
                        r"insufficient_evidence|expected_status", re.I)
    text = " ".join(str(v) for v in _xlsx_questions().values())
    text += " ".join(p.text for p in Document(QDIR / "northgate_rfp.docx").paragraphs)
    assert not leaked.search(text)
