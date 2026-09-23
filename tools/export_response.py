"""Write reviewer-approved answers back into a copy of the customer's own file.

  python -m tools.export_response evals/results/northgate_rfp
  python -m tools.export_response evals/results/northgate_rfp --source path/to/original.docx --out filled.docx

Only questions whose decision is `approved` or `edited` are written; pending and
rejected questions are left blank so nothing unreviewed can leave the building.
The original file is never modified.

Where answers go (from the locations the parser recorded):
  xlsx            answer column (the explanation column when the response column is Yes/No),
                  evidence column if present, Yes/No column if the reviewer chose a value
  docx paragraph  the "Vendor response:" line under the requirement, or a new paragraph
  docx table      the requirement row's response cell
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

from docx import Document
from openpyxl import load_workbook

from app.review_state import Run, ReviewError
from tools.parse_questionnaire import parse_questionnaire

RESPONSE_LABEL = "Vendor response:"


def _evidence_text(result: dict) -> str:
    seen, parts = set(), []
    for c in result.get("citations") or []:
        key = (c["doc"], c["page"])
        if key not in seen:
            seen.add(key)
            parts.append(f"{c['doc_title']} ({c['doc']}), p.{c['page']}")
    return "; ".join(parts)


def _approved(run: Run) -> list[tuple[dict, object]]:
    out = []
    for r in run.results:
        d = run.decisions.get(r["ref"])
        if d and d.decision in ("approved", "edited") and d.final_answer:
            out.append((r, d))
    return out


def _export_xlsx(src: Path, dest: Path, items) -> int:
    wb = load_workbook(src)
    n = 0
    for r, d in items:
        loc = (r.get("trace") or {}).get("location") or {}
        if loc.get("kind") != "xlsx_cell":
            continue
        ws = wb[loc["sheet"]]
        ws.cell(loc["row"], loc["answer_col"]).value = d.final_answer
        if loc.get("choice_col") and d.choice:
            ws.cell(loc["row"], loc["choice_col"]).value = d.choice
        ev_col = loc.get("evidence_col")
        # do not overwrite the answer if evidence and answer share a column (e.g. "Explanation / Evidence")
        if ev_col and ev_col != loc["answer_col"] and not d.human_written:
            ws.cell(loc["row"], ev_col).value = _evidence_text(r)
        n += 1
    wb.save(dest)
    return n


def _insert_paragraph_after(paragraph, text: str):
    new_p = copy.deepcopy(paragraph._p)
    for child in list(new_p):
        if child.tag.endswith("}r"):
            new_p.remove(child)
    paragraph._p.addnext(new_p)
    from docx.text.paragraph import Paragraph
    para = Paragraph(new_p, paragraph._parent)
    para.add_run(text)
    return para


def _export_docx(src: Path, dest: Path, items) -> int:
    doc = Document(src)
    paragraphs = doc.paragraphs       # body paragraphs in order, same indexing as the parser
    tables = doc.tables
    n = 0
    # insert from the bottom up so earlier paragraph indexes stay valid
    para_items = sorted([(r, d) for r, d in items
                         if ((r.get("trace") or {}).get("location") or {}).get("kind") == "docx_paragraph"],
                        key=lambda x: -x[0]["trace"]["location"]["paragraph_index"])
    for r, d in para_items:
        idx = r["trace"]["location"]["paragraph_index"]
        nxt = paragraphs[idx + 1] if idx + 1 < len(paragraphs) else None
        if nxt is not None and nxt.text.strip().startswith(RESPONSE_LABEL):
            for run in nxt.runs[1:]:
                run.text = ""
            nxt.runs[0].text = f"{RESPONSE_LABEL} "
            nxt.runs[0].italic = False
            nxt.add_run(d.final_answer)
        else:
            _insert_paragraph_after(paragraphs[idx], f"{RESPONSE_LABEL} {d.final_answer}")
        n += 1
    for r, d in items:
        loc = (r.get("trace") or {}).get("location") or {}
        if loc.get("kind") == "docx_table_cell":
            tables[loc["table_index"]].rows[loc["row"]].cells[loc["col"]].text = d.final_answer
            n += 1
    doc.save(dest)
    return n


def export(run_folder: str | Path, source: str | Path | None = None, out: str | Path | None = None) -> tuple[Path, int]:
    run = Run.load(run_folder)
    src = Path(source) if source else run.source
    if src is None or not src.exists():
        raise ReviewError("original customer file not found; pass --source")
    dest = Path(out) if out else run.folder / f"{src.stem}_response{src.suffix}"
    if dest.resolve() == src.resolve():
        raise ReviewError("refusing to overwrite the original customer file")
    items = _approved(run)
    # Older runs did not record answer locations: recover them by re-parsing the original file.
    if any(not (r.get("trace") or {}).get("location") for r, _ in items):
        locs = {q.ref: q.location for q in parse_questionnaire(src)}
        for r, _ in items:
            r.setdefault("trace", {}).setdefault("location", locs.get(r["ref"]))
            if r["trace"]["location"] is None:
                raise ReviewError(f"question {r['ref']} was not found in {src.name}; is this the right file?")
    if src.suffix.lower() in (".xlsx", ".xlsm"):
        n = _export_xlsx(src, dest, items)
    elif src.suffix.lower() == ".docx":
        n = _export_docx(src, dest, items)
    else:
        raise ReviewError(f"unsupported file type {src.suffix}")
    return dest, n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_folder", type=Path)
    ap.add_argument("--source", type=Path, help="original customer file (default: recorded in run.json)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    try:
        dest, n = export(a.run_folder, a.source, a.out)
    except ReviewError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    run = Run.load(a.run_folder)
    p = run.progress()
    print(f"Wrote {n} approved answers to {dest}")
    print(f"  approved {p['approved']} · edited {p['edited']} · rejected {p['rejected']} · still pending {p['pending']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
