"""Extract questions from a customer questionnaire (.xlsx) or RFP (.docx).

The parser does not know which generator layout produced a file. It finds
questions the way it must for real customer files:

  xlsx  scan every sheet for a header row containing a question-like column
        (Question / Requirement / Control ...) and a response-like column
        (Response / Answer ...). Rows below it are questions.
  docx  walk paragraphs and tables in document order. Headings set the current
        section; paragraphs starting with a requirement number (4.2.1, A-3, Q12)
        are questions; tables with Requirement + Response columns contribute rows.

Each question records WHERE its answer belongs, so a later export step can write
responses back into the customer's own file.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook

QUESTION_HDR = re.compile(r"\b(question|requirement|control|description|query|item text)\b", re.I)
QUESTION_HDR_STRONG = re.compile(r"\b(question|requirement)s?\b", re.I)
RESPONSE_HDR = re.compile(r"\b(response|answer|vendor reply|reply)\b", re.I)
REF_HDR = re.compile(r"^\s*(ref(erence)?\.?|id|#|no\.?|number|item|q\s*#?)\s*$", re.I)
SECTION_HDR = re.compile(r"\b(section|domain|category|area|topic)\b", re.I)
EVIDENCE_HDR = re.compile(r"\b(evidence|reference|source|supporting)\b", re.I)
COMMENT_HDR = re.compile(r"\b(comment|comments|explanation|notes?|justification)\b", re.I)
NUMBERED = re.compile(r"^\s*((?:\d+\.)+\d+|[A-Z]{1,4}-\d+|Q\d+)[.)]?\s+(.{8,})$")
HEADING_NUM = re.compile(r"^\s*[\d.]+\s+")


@dataclass
class ParsedQuestion:
    ref: str
    text: str
    section: str | None
    location: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class ParseError(ValueError):
    pass


def _s(v) -> str:
    return "" if v is None else str(v).strip()


# --- xlsx -------------------------------------------------------------------

def _pick_question_col(labels: dict):
    """Prefer 'Question'/'Requirement' headers over weaker ones like 'Control Domain'."""
    for rx in (QUESTION_HDR_STRONG, QUESTION_HDR):
        col = next((k for k, v in labels.items() if rx.search(v) and not RESPONSE_HDR.search(v)
                    and not SECTION_HDR.search(v)), None)
        if col is not None:
            return col
    return None


def _find_header(ws, max_scan: int = 40):
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, max_scan)):
        labels = {c.column: _s(c.value) for c in row if _s(c.value)}
        q_col = _pick_question_col(labels)
        r_col = next((col for col, v in labels.items() if RESPONSE_HDR.search(v)), None)
        if q_col and r_col and len(labels) >= 2:
            find = lambda rx, excl=(): next((col for col, v in labels.items()   # noqa: E731
                                             if rx.search(v) and col not in excl), None)
            used = {q_col, r_col}
            ref_col = find(REF_HDR, used)
            sec_col = find(SECTION_HDR, used | {ref_col})
            ev_col = find(EVIDENCE_HDR, used | {ref_col, sec_col})
            cm_col = find(COMMENT_HDR, used | {ref_col, sec_col, ev_col})
            return row[0].row, dict(question=q_col, response=r_col, ref=ref_col, section=sec_col,
                                    evidence=ev_col, comments=cm_col, labels=labels)
    return None


def _answer_is_choice(ws, col: int, header_row: int, label: str) -> bool:
    if re.search(r"yes\s*/\s*no", label, re.I):
        return True
    for dv in ws.data_validations.dataValidation:
        if dv.type == "list" and any(
                c.min_col <= col <= c.max_col and c.max_row > header_row for c in dv.sqref.ranges):
            return True
    return False


def parse_xlsx(path: Path) -> list[ParsedQuestion]:
    wb = load_workbook(path)
    out: list[ParsedQuestion] = []
    for ws in wb.worksheets:
        found = _find_header(ws)
        if not found:
            continue
        hdr_row, cols = found
        choice = _answer_is_choice(ws, cols["response"], hdr_row, cols["labels"][cols["response"]])
        # Where the prose answer goes: explanation column if the response column is Yes/No.
        prose_col = (cols["comments"] or cols["evidence"] or cols["response"]) if choice else cols["response"]
        for r in range(hdr_row + 1, ws.max_row + 1):
            text = _s(ws.cell(r, cols["question"]).value)
            if len(text) < 5:
                continue
            ref = _s(ws.cell(r, cols["ref"]).value) if cols["ref"] else ""
            if not ref:
                if ws.cell(r, cols["question"]).font.bold:
                    continue  # section banner row inside the table
                ref = f"{ws.title}!R{r}"
            section = _s(ws.cell(r, cols["section"]).value) if cols["section"] else ""
            if not section and ws.title.lower() not in {"sheet", "sheet1", "questionnaire", "questions"}:
                section = ws.title
            out.append(ParsedQuestion(ref=ref, text=text, section=section or None, location={
                "kind": "xlsx_cell", "sheet": ws.title, "row": r,
                "response_col": cols["response"], "answer_col": prose_col,
                "choice_col": cols["response"] if choice else None,
                "evidence_col": cols["evidence"],
            }))
    if not out:
        raise ParseError(f"{path.name}: no sheet has a recognizable Question + Response header row")
    return out


# --- docx -------------------------------------------------------------------

def _iter_block_items(doc):
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, doc)
        elif child.tag.endswith("}tbl"):
            yield Table(child, doc)


def parse_docx(path: Path) -> list[ParsedQuestion]:
    doc = Document(path)
    out: list[ParsedQuestion] = []
    section: str | None = None
    p_idx = t_idx = -1
    for block in _iter_block_items(doc):
        if isinstance(block, Paragraph):
            p_idx += 1
            text = block.text.strip()
            if not text:
                continue
            style = (block.style.name or "").lower() if block.style is not None else ""
            if style.startswith("heading") or style == "title":
                if style.startswith("heading 2") or style.startswith("heading 3"):
                    section = HEADING_NUM.sub("", text).strip() or section
                continue
            m = NUMBERED.match(text)
            if m:
                out.append(ParsedQuestion(ref=m.group(1), text=m.group(2).strip(), section=section,
                                          location={"kind": "docx_paragraph", "paragraph_index": p_idx}))
        else:
            t_idx += 1
            rows = block.rows
            if not rows:
                continue
            labels = [c.text.strip() for c in rows[0].cells]
            q_col = _pick_question_col(dict(enumerate(labels)))
            r_col = next((i for i, v in enumerate(labels) if RESPONSE_HDR.search(v)), None)
            if q_col is None or r_col is None:
                continue
            ref_col = next((i for i, v in enumerate(labels) if REF_HDR.search(v)), None)
            for ri, row in enumerate(rows[1:], 1):
                cells = row.cells
                text = cells[q_col].text.strip()
                if len(text) < 5:
                    continue
                ref = cells[ref_col].text.strip() if ref_col is not None else f"T{t_idx}R{ri}"
                out.append(ParsedQuestion(ref=ref, text=text, section=section, location={
                    "kind": "docx_table_cell", "table_index": t_idx, "row": ri, "col": r_col}))
    if not out:
        raise ParseError(f"{path.name}: no numbered requirements or requirement tables found")
    return out


def parse_questionnaire(path: str | Path) -> list[ParsedQuestion]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        qs = parse_xlsx(path)
    elif suffix == ".docx":
        qs = parse_docx(path)
    else:
        raise ParseError(f"unsupported file type {suffix}; expected .xlsx or .docx")
    seen: dict[str, int] = {}
    for q in qs:  # make refs unique if the customer file repeats one
        if q.ref in seen:
            seen[q.ref] += 1
            q.ref = f"{q.ref}#{seen[q.ref]}"
        else:
            seen[q.ref] = 1
    return qs


if __name__ == "__main__":
    import sys
    for q in parse_questionnaire(sys.argv[1]):
        print(f"{q.ref:<10} [{q.section}] {q.text}")
