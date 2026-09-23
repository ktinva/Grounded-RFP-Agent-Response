"""Review state, write-back export, and the review screen (no API key needed)."""
from __future__ import annotations

import hashlib
import json

import pytest
from docx import Document
from openpyxl import load_workbook

from agents.consistency import check_consistency
from agents.pipeline import RFPAgent, results_to_jsonl
from app.review_state import ReviewError, Run, write_run_meta
from tests.oracle_llm import oracle_llm
from tools.export_response import export
from tools.generate_questionnaire import Spec, generate
from tools.parse_questionnaire import parse_questionnaire


def make_run(tmp_path, fmt, layout, record_locations=True, count=20, seed=21):
    src, _, key = generate(Spec(buyer="Export Test", fmt=fmt, layout=layout, count=count, seed=seed,
                                out_dir=tmp_path / "in"))
    parsed = parse_questionnaire(src)
    results = RFPAgent(oracle_llm()).answer_many([q.to_dict() for q in parsed], workers=4)
    if record_locations:
        for r, q in zip(results, parsed):
            r.trace["location"] = q.location
    check_consistency(results)
    folder = tmp_path / "run"
    folder.mkdir()
    (folder / "results.jsonl").write_text(results_to_jsonl(results))
    write_run_meta(folder, src)
    return src, folder


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_decisions_are_validated_and_persisted(tmp_path):
    _, folder = make_run(tmp_path, "xlsx", "standard")
    run = Run.load(folder)
    answered = next(r for r in run.results if r["status"] == "answered")
    other = next(r for r in run.results if r["status"] != "answered")
    with pytest.raises(ReviewError, match="only answered"):
        run.decide(other["ref"], "approved")
    with pytest.raises(ReviewError, match="needs the final answer"):
        run.decide(other["ref"], "edited", final_answer="  ")
    run.decide(answered["ref"], "approved", reviewer="kt")
    run.decide(other["ref"], "edited", final_answer="Legal will respond separately.", reviewer="kt")
    run.save()
    again = Run.load(folder)
    assert again.decisions[answered["ref"]].final_answer == answered["answer"]
    assert again.decisions[other["ref"]].human_written is True
    assert again.progress()["pending"] == len(run.results) - 2


@pytest.mark.parametrize("fmt, layout", [("xlsx", "standard"), ("xlsx", "yes_no"), ("xlsx", "by_section"),
                                         ("docx", "numbered"), ("docx", "table")])
def test_export_writes_only_approved_answers_into_a_copy(tmp_path, fmt, layout):
    src, folder = make_run(tmp_path, fmt, layout)
    before = _sha(src)
    run = Run.load(folder)
    answered = [r for r in run.results if r["status"] == "answered"]
    approved, rejected = answered[0], answered[1]
    run.decide(approved["ref"], "approved", choice="Yes" if layout == "yes_no" else "")
    run.decide(rejected["ref"], "rejected")
    run.save()

    dest, n = export(folder)
    assert n == 1 and dest != src and _sha(src) == before           # original untouched

    parsed = {q.ref: q for q in parse_questionnaire(dest)}          # still a valid questionnaire
    assert set(parsed) == {r["ref"] for r in run.results}
    if fmt == "xlsx":
        wb = load_workbook(dest)
        loc = approved["trace"]["location"]
        ws = wb[loc["sheet"]]
        assert ws.cell(loc["row"], loc["answer_col"]).value == approved["answer"]
        if layout == "yes_no":
            assert ws.cell(loc["row"], loc["choice_col"]).value == "Yes"
        elif loc.get("evidence_col"):
            assert approved["citations"][0]["doc"] in ws.cell(loc["row"], loc["evidence_col"]).value
        rl = rejected["trace"]["location"]
        assert not wb[rl["sheet"]].cell(rl["row"], rl["answer_col"]).value
    else:
        text = "\n".join(p.text for p in Document(dest).paragraphs)
        text += "\n".join(c.text for t in Document(dest).tables for row in t.rows for c in row.cells)
        assert approved["answer"] in text and rejected["answer"] not in text


def test_export_recovers_locations_for_older_runs(tmp_path):
    src, folder = make_run(tmp_path, "docx", "numbered", record_locations=False)
    run = Run.load(folder)
    r = next(r for r in run.results if r["status"] == "answered")
    run.decide(r["ref"], "approved")
    run.save()
    dest, n = export(folder)
    assert n == 1 and r["answer"] in "\n".join(p.text for p in Document(dest).paragraphs)


def test_export_refuses_to_overwrite_the_original(tmp_path):
    src, folder = make_run(tmp_path, "xlsx", "standard")
    with pytest.raises(ReviewError, match="overwrite"):
        export(folder, out=src)


def test_review_screen_approve_and_export(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    _, folder = make_run(tmp_path, "xlsx", "standard", count=12)
    monkeypatch.setenv("RFP_RUN_DIR", str(folder))
    from pathlib import Path
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app" / "review_app.py"), default_timeout=30).run()
    assert not at.exception
    ref = next(json.loads(l)["ref"] for l in (folder / "results.jsonl").read_text().splitlines()
               if json.loads(l)["status"] == "answered")
    at.button(key=f"approve_{ref}").click().run()
    assert not at.exception
    assert Run.load(folder).status_of(ref) == "approved"
    export_btn = next(b for b in at.button if b.label == "Export approved answers")
    export_btn.click().run()
    assert not at.exception and any("Wrote 1 answers" in s.value for s in at.success)


def test_moved_project_falls_back_to_finding_the_source_by_name(tmp_path):
    import shutil
    from pathlib import Path
    folder = tmp_path / "northgate_rfp"
    folder.mkdir()
    (folder / "results.jsonl").write_text('{"ref": "4.1.1", "question": "q", "status": "answered"}\n')
    (folder / "run.json").write_text(json.dumps({"source": "/Users/someone/elsewhere/northgate_rfp.docx"}))
    run = Run.load(folder)
    assert run.source is not None and run.source.exists() and run.source.name == "northgate_rfp.docx"
    shutil.rmtree(folder)
