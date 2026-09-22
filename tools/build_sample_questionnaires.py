"""Generate the sample customer documents the agent is asked to complete.

Outputs (data/sample/questionnaires/):
  - northgate_security_questionnaire.xlsx  every golden-set question, grouped by
    section, in the column layout typical of vendor security questionnaires
  - northgate_rfp.docx                     a narrative RFP whose requirements
    section contains a mixed subset of golden-set questions
  - answer_key.yaml                        questionnaire ref -> golden-set id

Category labels are never written into the customer files, so the agent cannot
read the expected behaviour off the page. The answer key lives beside them and
is only used by the eval runner.

Northgate Mutual is a fictional buyer.

Run:  python -m tools.build_sample_questionnaires
"""
from __future__ import annotations

import random
from collections import OrderedDict
from pathlib import Path

import yaml
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "evals" / "golden_set.yaml"
OUT = ROOT / "data" / "sample" / "questionnaires"
SEED = 20260922

SECTION_ORDER = [
    "Company Information", "Security Program", "Compliance", "Identity and Access",
    "Data Protection", "Hosting and Deployment", "Logging and Monitoring",
    "Vulnerability Management", "Incident Response", "Business Continuity", "Availability",
    "Privacy", "AI and Data Use", "Product Capabilities", "Integrations", "Support",
    "Legal and Commercial", "General",
]
SECTION_CODE = {
    "Company Information": "CO", "Security Program": "SP", "Compliance": "CP",
    "Identity and Access": "IA", "Data Protection": "DP", "Hosting and Deployment": "HD",
    "Logging and Monitoring": "LM", "Vulnerability Management": "VM", "Incident Response": "IR",
    "Business Continuity": "BC", "Availability": "AV", "Privacy": "PR", "AI and Data Use": "AI",
    "Product Capabilities": "PC", "Integrations": "IN", "Support": "SU",
    "Legal and Commercial": "LC", "General": "GN",
}

# Golden ids included in the narrative RFP (a realistic mix of all five categories).
RFP_IDS = [
    "COV-006", "COV-001", "COV-004", "COV-008", "COV-010", "COV-012", "COV-024", "COV-027",
    "NC-001", "NC-006", "NC-009",
    "CF-001", "CF-006", "CF-010",
    "SEN-001", "SEN-005", "SEN-006",
    "AMB-004", "AMB-008", "AMB-001",
]


def load_questions() -> list[dict]:
    return yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["questions"]


def build_xlsx(questions: list[dict]) -> dict[str, str]:
    rng = random.Random(SEED)
    by_section: "OrderedDict[str, list[dict]]" = OrderedDict((s, []) for s in SECTION_ORDER)
    for q in questions:
        by_section[q["section"]].append(q)

    wb = Workbook()
    ws = wb.active
    ws.title = "Vendor Security Assessment"
    thin = Side(style="thin", color="A6A6A6")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws["A1"] = "Northgate Mutual - Vendor Security and AI Assessment"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = ("Vendor: please complete the Response column for every question. Where a "
                "statement is supported by documentation, reference the document and page. "
                "Fictional sample for demonstration purposes.")
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells("A2:F2")
    ws.row_dimensions[2].height = 45

    headers = ["Ref", "Section", "Question", "Response", "Supporting Evidence (document, page)", "Vendor Comments"]
    ws.append([])
    ws.append(headers)
    hdr_row = ws.max_row
    for c in ws[hdr_row]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3A5F")
        c.alignment = Alignment(wrap_text=True, vertical="center")
        c.border = border

    key: dict[str, str] = {}
    for section, qs in by_section.items():
        rng.shuffle(qs)  # interleave categories inside each section
        for i, q in enumerate(qs, 1):
            ref = f"{SECTION_CODE[section]}-{i:02d}"
            key[ref] = q["id"]
            ws.append([ref, section, q["question"], "", "", ""])
            for c in ws[ws.max_row]:
                c.alignment = Alignment(wrap_text=True, vertical="top")
                c.border = border

    for col, width in zip("ABCDEF", [8, 22, 60, 50, 30, 30]):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = ws.cell(row=hdr_row + 1, column=3)
    ws.auto_filter.ref = f"A{hdr_row}:F{ws.max_row}"

    info = wb.create_sheet("Instructions")
    for row in [
        ["How to complete this assessment"],
        ["1. Answer every question in the Response column of the Vendor Security Assessment sheet."],
        ["2. Cite the supporting document and page number for each factual statement."],
        ["3. If a question does not apply or cannot be answered, say so in Vendor Comments."],
        ["4. Return the completed workbook to the Northgate Mutual procurement team."],
    ]:
        info.append(row)
    info["A1"].font = Font(bold=True, size=12)
    info.column_dimensions["A"].width = 100

    wb.save(OUT / "northgate_security_questionnaire.xlsx")
    return key


def build_docx(questions: list[dict]) -> dict[str, str]:
    by_id = {q["id"]: q for q in questions}
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    t = doc.add_heading("Request for Proposal: Enterprise Document Intelligence Platform", level=0)
    t.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p = doc.add_paragraph("Issued by Northgate Mutual Insurance Company  |  RFP No. NGM-2026-114  |  "
                          "Responses due 30 October 2026")
    p.runs[0].font.color.rgb = RGBColor(0x55, 0x55, 0x55)
    note = doc.add_paragraph("Fictional sample RFP for demonstration purposes. Northgate Mutual is not a real company.")
    note.runs[0].italic = True
    note.runs[0].font.size = Pt(9)

    doc.add_heading("1. Introduction", level=1)
    doc.add_paragraph(
        "Northgate Mutual is seeking a cloud-based document intelligence platform to help its "
        "claims, underwriting, and legal teams search, summarize, and extract information from "
        "policy documents, claims files, and contracts. The selected vendor will support "
        "approximately 2,000 users across the United States and the United Kingdom.")

    doc.add_heading("2. Scope", level=1)
    for line in [
        "Ingestion of policy, claims, and contract documents from existing repositories.",
        "Semantic search and question answering with verifiable sources.",
        "Integration with Northgate's identity provider and security monitoring tools.",
        "Enterprise-grade security, privacy, and availability commitments.",
    ]:
        doc.add_paragraph(line, style="List Bullet")

    doc.add_heading("3. Submission Instructions", level=1)
    doc.add_paragraph(
        "Respond to each numbered requirement in Section 4 directly beneath the requirement. "
        "Reference supporting documentation, including document name and page number, for "
        "every factual claim. Clearly identify any requirement the vendor cannot meet.")

    doc.add_heading("4. Requirements", level=1)
    key: dict[str, str] = {}
    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    for gid in RFP_IDS:
        q = by_id[gid]
        groups.setdefault(q["section"], []).append(q)
    for s_idx, (section, qs) in enumerate(groups.items(), 1):
        doc.add_heading(f"4.{s_idx} {section}", level=2)
        for q_idx, q in enumerate(qs, 1):
            ref = f"4.{s_idx}.{q_idx}"
            key[ref] = q["id"]
            para = doc.add_paragraph()
            para.add_run(f"{ref}  ").bold = True
            para.add_run(q["question"])
            resp = doc.add_paragraph("Vendor response: ")
            resp.runs[0].italic = True
            resp.runs[0].font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    doc.add_heading("5. Evaluation Criteria", level=1)
    doc.add_paragraph("Responses will be evaluated on functional fit (35%), security and "
                      "compliance (30%), total cost of ownership (20%), and vendor viability (15%).")

    doc.save(OUT / "northgate_rfp.docx")
    return key


def build() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    questions = load_questions()
    key = {
        "northgate_security_questionnaire.xlsx": build_xlsx(questions),
        "northgate_rfp.docx": build_docx(questions),
    }
    header = ("# Generated by tools/build_sample_questionnaires.py - do not edit by hand.\n"
              "# Maps each questionnaire reference to its golden-set id (evals/golden_set.yaml).\n"
              "# Used only by the eval runner; the agent never sees this file.\n")
    (OUT / "answer_key.yaml").write_text(header + yaml.safe_dump(key, sort_keys=False), encoding="utf-8")
    return key


if __name__ == "__main__":
    k = build()
    for f, refs in k.items():
        print(f"{f}: {len(refs)} questions")
