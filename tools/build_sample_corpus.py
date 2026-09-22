"""Render the fictional Kestrel Ridge knowledge base from Markdown to paginated PDFs.

Source of truth: data/sample/kb_source/*.md
  - YAML front matter holds document metadata (doc_id, version, approval_status ...)
  - A line containing only ``===PAGE===`` forces a page break, so the page numbers
    printed in each PDF are fixed and the golden eval set can cite them exactly.

Outputs:
  - data/sample/kb/<doc_id>.pdf
  - data/sample/kb/manifest.yaml   (metadata + page count + sha256 per document)

Run:  python -m tools.build_sample_corpus
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

rl_config.invariant = 1  # deterministic PDFs (no timestamps / random IDs)

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "data" / "sample" / "kb_source"
OUT_DIR = ROOT / "data" / "sample" / "kb"
PAGE_MARKER = "===PAGE==="
COMPANY_NOTICE = "FICTIONAL SAMPLE DOCUMENT - Kestrel Ridge Software is not a real company."

_styles = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=_styles["BodyText"], fontName="Helvetica",
                      fontSize=10, leading=13.5, spaceAfter=6, alignment=TA_LEFT)
H1 = ParagraphStyle("h1", parent=BODY, fontName="Helvetica-Bold", fontSize=17,
                    leading=21, spaceAfter=4)
META = ParagraphStyle("meta", parent=BODY, fontSize=8.5, textColor=colors.HexColor("#555555"),
                      spaceAfter=14)
H2 = ParagraphStyle("h2", parent=BODY, fontName="Helvetica-Bold", fontSize=12.5,
                    leading=16, spaceBefore=8, spaceAfter=5, textColor=colors.HexColor("#1F3A5F"))
CELL = ParagraphStyle("cell", parent=BODY, fontSize=9, leading=11.5, spaceAfter=0)
CELL_HEAD = ParagraphStyle("cellhead", parent=CELL, fontName="Helvetica-Bold")


def parse_source(path: Path) -> tuple[dict, list[str]]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path.name}: missing YAML front matter")
    meta = yaml.safe_load(m.group(1))
    pages = [p.strip("\n") for p in m.group(2).split(PAGE_MARKER)]
    return meta, pages


def _inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def _table(rows: list[str]) -> Table:
    cells = []
    for i, row in enumerate(r for r in rows if not re.match(r"^\|[\s\-|:]+\|$", r)):
        parts = [c.strip() for c in row.strip().strip("|").split("|")]
        style = CELL_HEAD if i == 0 else CELL
        cells.append([Paragraph(_inline(c), style) for c in parts])
    t = Table(cells, hAlign="LEFT", repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF5")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9AA8B8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def page_flowables(page_md: str) -> list:
    """Convert one page of the tiny Markdown dialect into flowables."""
    out: list = []
    blocks = re.split(r"\n\s*\n", page_md.strip())
    for block in blocks:
        lines = block.strip().splitlines()
        if not lines:
            continue
        if lines[0].startswith("## "):
            out.append(Paragraph(_inline(lines[0][3:]), H2))
            lines = lines[1:]
            if not lines:
                continue
        if all(l.startswith("|") for l in lines):
            out.append(_table(lines))
            out.append(Spacer(1, 8))
        elif all(re.match(r"^(- |\d+\. )", l) for l in lines):
            numbered = lines[0][0].isdigit()
            items = [ListItem(Paragraph(_inline(re.sub(r"^(- |\d+\. )", "", l)), BODY),
                              leftIndent=14) for l in lines]
            out.append(ListFlowable(items, bulletType="1" if numbered else "bullet",
                                    start="1" if numbered else None, leftIndent=14,
                                    bulletFontSize=8 if not numbered else 10))
            out.append(Spacer(1, 4))
        else:
            out.append(Paragraph(_inline(" ".join(lines)), BODY))
    return out


def render(meta: dict, pages: list[str], out_path: Path) -> None:
    total = len(pages)
    is_draft = meta["approval_status"] != "approved"

    def decorate(canvas, doc):
        canvas.saveState()
        w, h = LETTER
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawString(0.9 * inch, h - 0.55 * inch, f"Kestrel Ridge Software, Inc.  |  {meta['doc_id']}")
        if is_draft:
            canvas.setFillColor(colors.HexColor("#B00020"))
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawRightString(w - 0.9 * inch, h - 0.55 * inch, "DRAFT - NOT APPROVED")
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.setFont("Helvetica", 8)
        canvas.drawString(0.9 * inch, 0.55 * inch, f"{meta['title']}  |  Version {meta['version']}")
        canvas.drawRightString(w - 0.9 * inch, 0.55 * inch, f"Page {doc.page} of {total}")
        canvas.setFont("Helvetica-Oblique", 7)
        canvas.drawString(0.9 * inch, 0.38 * inch, COMPANY_NOTICE)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(out_path), pagesize=LETTER, leftMargin=0.9 * inch,
                            rightMargin=0.9 * inch, topMargin=0.85 * inch,
                            bottomMargin=0.85 * inch, title=meta["title"],
                            author="Kestrel Ridge Software (fictional)", subject=meta["doc_id"])
    story: list = [
        Paragraph(_inline(meta["title"]), H1),
        Paragraph(f"Document {meta['doc_id']} &nbsp;|&nbsp; Version {meta['version']} &nbsp;|&nbsp; "
                  f"Effective {meta.get('effective_date') or 'not set'} &nbsp;|&nbsp; "
                  f"Owner: {meta['owner_team'].replace('_', ' ').title()}", META),
    ]
    for i, page in enumerate(pages):
        if i:
            story.append(PageBreak())
        story.extend(page_flowables(page))
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)


def build() -> list[dict]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for src in sorted(SRC_DIR.glob("*.md")):
        meta, pages = parse_source(src)
        pdf = OUT_DIR / f"{meta['doc_id']}.pdf"
        render(meta, pages, pdf)
        manifest.append({
            **{k: (str(v) if v is not None else None) for k, v in meta.items()},
            "file": pdf.name,
            "source": f"kb_source/{src.name}",
            "pages": len(pages),
            "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        })
    header = ("# Generated by tools/build_sample_corpus.py - do not edit by hand.\n"
              "# Only documents with approval_status: approved may be retrieved or cited.\n")
    (OUT_DIR / "manifest.yaml").write_text(
        header + yaml.safe_dump({"documents": manifest}, sort_keys=False), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    for d in build():
        print(f"{d['doc_id']:<11} {d['approval_status']:<9} {d['pages']} pages  {d['file']}")
