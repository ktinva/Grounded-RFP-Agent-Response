"""Writers for customer questionnaire layouts.

Real questionnaires arrive in many shapes. Each layout here mimics a common one,
so the questionnaire parser is tested against more than a single format.

  xlsx  standard    Ref | Section | Question | Response | Evidence | Comments  (one sheet)
  xlsx  yes_no      # | Control Domain | Control Question | Answer (Yes/No/N/A) | Explanation
                    header row lower down, after a cover block
  xlsx  by_section  one sheet per section: ID | Requirement | Vendor Response | Reference
  docx  numbered    narrative RFP, requirements as numbered paragraphs (4.x.y)
  docx  table       RFP with a requirements table per section: No. | Requirement | Vendor Response

Every writer takes items [{section, text}] (already ordered) and returns the refs it
assigned, in the same order.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

XLSX_LAYOUTS = ("standard", "yes_no", "by_section")
DOCX_LAYOUTS = ("numbered", "table")

SECTION_CODE = {
    "Company Information": "CO", "Security Program": "SP", "Compliance": "CP",
    "Identity and Access": "IA", "Data Protection": "DP", "Hosting and Deployment": "HD",
    "Logging and Monitoring": "LM", "Vulnerability Management": "VM", "Incident Response": "IR",
    "Business Continuity": "BC", "Availability": "AV", "Privacy": "PR", "AI and Data Use": "AI",
    "Product Capabilities": "PC", "Integrations": "IN", "Support": "SU",
    "Legal and Commercial": "LC", "General": "GN",
}

_THIN = Side(style="thin", color="A6A6A6")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


@dataclass
class DocMeta:
    buyer: str
    doc_number: str
    due_date: str
    fictional_note: bool = True


def _group(items: list[dict]) -> "OrderedDict[str, list[dict]]":
    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    for it in items:
        groups.setdefault(it["section"], []).append(it)
    return groups


def _header_style(row) -> None:
    for c in row:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3A5F")
        c.alignment = Alignment(wrap_text=True, vertical="center")
        c.border = _BORDER


def _body_style(row) -> None:
    for c in row:
        c.alignment = Alignment(wrap_text=True, vertical="top")
        c.border = _BORDER


def _note(meta: DocMeta) -> str:
    return (f" Fictional sample for demonstration purposes; {meta.buyer} is not a real company."
            if meta.fictional_note else "")


def sheet_title(name: str) -> str:
    return re.sub(r"[\[\]:*?/\\]", "", name)[:31]


# --- xlsx -------------------------------------------------------------------

def write_xlsx(layout: str, items: list[dict], path: Path, meta: DocMeta) -> list[str]:
    wb = Workbook()
    refs: list[str] = []

    if layout == "standard":
        ws = wb.active
        ws.title = "Vendor Security Assessment"
        ws["A1"] = f"{meta.buyer} - Vendor Security and AI Assessment"
        ws["A1"].font = Font(bold=True, size=14)
        ws["A2"] = ("Vendor: please complete the Response column for every question. Where a statement "
                    "is supported by documentation, reference the document and page." + _note(meta))
        ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells("A2:F2")
        ws.row_dimensions[2].height = 45
        ws.append([])
        ws.append(["Ref", "Section", "Question", "Response", "Supporting Evidence (document, page)",
                   "Vendor Comments"])
        hdr = ws.max_row
        _header_style(ws[hdr])
        for section, qs in _group(items).items():
            for i, q in enumerate(qs, 1):
                ref = f"{SECTION_CODE.get(section, 'Q')}-{i:02d}"
                refs.append(ref)
                ws.append([ref, section, q["text"], "", "", ""])
                _body_style(ws[ws.max_row])
        for col, w in zip("ABCDEF", [8, 22, 60, 50, 30, 30]):
            ws.column_dimensions[col].width = w
        ws.freeze_panes = ws.cell(row=hdr + 1, column=3)

    elif layout == "yes_no":
        ws = wb.active
        ws.title = "Questionnaire"
        cover = [
            [f"{meta.buyer} Third-Party Risk Questionnaire"],
            [f"Reference: {meta.doc_number}    Due: {meta.due_date}"],
            ["Answer Yes, No, or N/A for each control question and explain your answer."
             " Attach or reference evidence where available." + _note(meta)],
            ["Vendor name:", ""],
            [],
        ]
        for r in cover:
            ws.append(r)
        ws["A1"].font = Font(bold=True, size=14)
        ws.append(["#", "Control Domain", "Control Question", "Answer (Yes/No/N/A)", "Explanation / Evidence"])
        hdr = ws.max_row
        _header_style(ws[hdr])
        n = 0
        for section, qs in _group(items).items():
            for q in qs:
                n += 1
                refs.append(str(n))
                ws.append([n, section, q["text"], "", ""])
                _body_style(ws[ws.max_row])
        dv = DataValidation(type="list", formula1='"Yes,No,N/A"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"D{hdr + 1}:D{max(ws.max_row, hdr + 1)}")
        for col, w in zip("ABCDE", [6, 24, 60, 14, 60]):
            ws.column_dimensions[col].width = w
        ws.freeze_panes = ws.cell(row=hdr + 1, column=1)

    elif layout == "by_section":
        cover = wb.active
        cover.title = "Cover"
        cover.append([f"{meta.buyer} - Request for Information: Security and Compliance"])
        cover.append([f"Document {meta.doc_number}. Complete every section tab. Due {meta.due_date}.{_note(meta)}"])
        cover["A1"].font = Font(bold=True, size=14)
        cover.column_dimensions["A"].width = 110
        for section, qs in _group(items).items():
            ws = wb.create_sheet(sheet_title(section))
            ws.append(["ID", "Requirement", "Vendor Response", "Reference"])
            _header_style(ws[1])
            code = SECTION_CODE.get(section, "Q")
            for i, q in enumerate(qs, 1):
                ref = f"{code}.{i}"
                refs.append(ref)
                ws.append([ref, q["text"], "", ""])
                _body_style(ws[ws.max_row])
            for col, w in zip("ABCD", [8, 60, 60, 30]):
                ws.column_dimensions[col].width = w
    else:
        raise ValueError(f"unknown xlsx layout {layout!r}; choose from {XLSX_LAYOUTS}")

    wb.save(path)
    return refs


# --- docx -------------------------------------------------------------------

def _docx_front_matter(doc, meta: DocMeta) -> None:
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    t = doc.add_heading("Request for Proposal: Enterprise Document Intelligence Platform", level=0)
    t.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p = doc.add_paragraph(f"Issued by {meta.buyer}  |  RFP No. {meta.doc_number}  |  Responses due {meta.due_date}")
    p.runs[0].font.color.rgb = RGBColor(0x55, 0x55, 0x55)
    if meta.fictional_note:
        n = doc.add_paragraph(f"Fictional sample RFP for demonstration purposes. {meta.buyer} is not a real company.")
        n.runs[0].italic = True
        n.runs[0].font.size = Pt(9)
    doc.add_heading("1. Introduction", level=1)
    doc.add_paragraph(
        f"{meta.buyer} is seeking a cloud-based document intelligence platform to help its business, "
        "legal, and technical teams search, summarize, and extract information from large document "
        "collections.")
    doc.add_heading("2. Scope", level=1)
    for line in [
        "Ingestion of documents from existing repositories.",
        "Semantic search and question answering with verifiable sources.",
        "Integration with the buyer's identity provider and security monitoring tools.",
        "Enterprise-grade security, privacy, and availability commitments.",
    ]:
        doc.add_paragraph(line, style="List Bullet")
    doc.add_heading("3. Submission Instructions", level=1)
    doc.add_paragraph(
        "Respond to each numbered requirement in Section 4. Reference supporting documentation, "
        "including document name and page number, for every factual claim. Clearly identify any "
        "requirement the vendor cannot meet.")
    doc.add_heading("4. Requirements", level=1)


def write_docx(layout: str, items: list[dict], path: Path, meta: DocMeta) -> list[str]:
    doc = Document()
    _docx_front_matter(doc, meta)
    refs: list[str] = []
    for s_idx, (section, qs) in enumerate(_group(items).items(), 1):
        doc.add_heading(f"4.{s_idx} {section}", level=2)
        if layout == "numbered":
            for q_idx, q in enumerate(qs, 1):
                ref = f"4.{s_idx}.{q_idx}"
                refs.append(ref)
                para = doc.add_paragraph()
                para.add_run(f"{ref}  ").bold = True
                para.add_run(q["text"])
                resp = doc.add_paragraph("Vendor response: ")
                resp.runs[0].italic = True
                resp.runs[0].font.color.rgb = RGBColor(0x80, 0x80, 0x80)
        elif layout == "table":
            table = doc.add_table(rows=1, cols=3)
            table.style = "Table Grid"
            for cell, label in zip(table.rows[0].cells, ["No.", "Requirement", "Vendor Response"]):
                cell.text = label
                cell.paragraphs[0].runs[0].bold = True
            for q_idx, q in enumerate(qs, 1):
                ref = f"4.{s_idx}.{q_idx}"
                refs.append(ref)
                row = table.add_row().cells
                row[0].text, row[1].text, row[2].text = ref, q["text"], ""
        else:
            raise ValueError(f"unknown docx layout {layout!r}; choose from {DOCX_LAYOUTS}")
    doc.add_heading("5. Evaluation Criteria", level=1)
    doc.add_paragraph("Responses will be evaluated on functional fit (35%), security and compliance (30%), "
                      "total cost of ownership (20%), and vendor viability (15%).")
    doc.save(path)
    return refs
