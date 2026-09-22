"""Turn approved knowledge-base PDFs into page-exact, section-level chunks.

Rules that the rest of the system relies on:
  * Only documents with approval_status == "approved" are ingested. Drafts never
    reach the index, so they can never be retrieved or cited.
  * A chunk never crosses a page boundary, so every chunk has exactly one page
    number and a citation is always precise.
  * Repeated page furniture (running headers, footers, "Page N of M") is removed
    so it does not pollute search.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from tools.kb_text import DEFAULT_KB_DIR, KBDocument, load_manifest, page_texts

SECTION_RE = re.compile(r"^(\d+\.)\s+[A-Z][^\n]{2,80}$")
PAGE_FOOTER_RE = re.compile(r"^Page \d+ of \d+$")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str          # e.g. KR-SEC-002:p2:c1
    doc_id: str
    doc_title: str
    version: str
    effective_date: str | None
    owner_team: str
    page: int
    section: str | None
    text: str

    @property
    def citation(self) -> str:
        return f"{self.doc_id} p.{self.page}"

    def search_text(self) -> str:
        """Text used for indexing: body plus a short contextual header."""
        return f"{self.doc_title}. {self.section or ''}. {self.text}"

    def to_dict(self) -> dict:
        return asdict(self)


def _boilerplate_lines(pages: list[list[str]]) -> set[str]:
    """Lines that appear on every page of a multi-page document are page furniture."""
    if len(pages) < 2:
        return set()
    counts = Counter(line for lines in pages for line in set(lines))
    return {line for line, n in counts.items() if n == len(pages)}


_PRIVATE_USE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\ue000-\uf8ff\u2022\u25aa\u25cf]")  # PDF bullet glyphs


def _clean_lines(raw: str) -> list[str]:
    lines = (_PRIVATE_USE.sub(" ", l) for l in raw.splitlines())
    return [re.sub(r"\s+", " ", l).strip() for l in lines if l.strip()]


def chunk_document(doc: KBDocument) -> list[Chunk]:
    pages = [_clean_lines(t) for t in page_texts(doc.file)]
    furniture = _boilerplate_lines(pages)
    chunks: list[Chunk] = []
    for page_no, lines in enumerate(pages, 1):
        body = [l for l in lines if l not in furniture and not PAGE_FOOTER_RE.match(l)
                and not l.startswith("FICTIONAL SAMPLE DOCUMENT")]
        # Single-page docs have no repetition to learn from: drop known header/footer shapes.
        body = [l for l in body if not re.match(rf"^.*\|\s*{re.escape(doc.doc_id)}$", l)
                and not l.startswith(f"{doc.title}  |  Version")]
        if page_no == 1 and body and body[0] == doc.title:
            body = body[1:]
        body = [l for l in body if not l.startswith(f"Document {doc.doc_id}")]

        sections: list[tuple[str | None, list[str]]] = []
        current: tuple[str | None, list[str]] = (None, [])
        for line in body:
            if SECTION_RE.match(line):
                if current[1]:
                    sections.append(current)
                current = (line, [])
            else:
                current[1].append(line)
        if current[1]:
            sections.append(current)

        carried = None  # a section continued from the previous page keeps its heading
        for i, (heading, lines_) in enumerate(sections, 1):
            text = re.sub(r"\s+", " ", " ".join(lines_)).strip()
            if not text:
                continue
            if heading is None and chunks and chunks[-1].doc_id == doc.doc_id:
                carried = chunks[-1].section
            chunks.append(Chunk(
                chunk_id=f"{doc.doc_id}:p{page_no}:c{i}", doc_id=doc.doc_id, doc_title=doc.title,
                version=doc.version, effective_date=doc.effective_date, owner_team=doc.owner_team,
                page=page_no, section=heading or carried, text=text))
    return chunks


def ingest(kb_dir: Path = DEFAULT_KB_DIR) -> list[Chunk]:
    docs = load_manifest(kb_dir)
    out: list[Chunk] = []
    for doc in docs.values():
        if not doc.approved:
            continue  # the approval gate: unapproved documents are never indexed
        out.extend(chunk_document(doc))
    return out


if __name__ == "__main__":
    chunks = ingest()
    print(f"{len(chunks)} chunks from {len({c.doc_id for c in chunks})} approved documents")
    for c in chunks[:4]:
        print(f"\n[{c.chunk_id}] {c.section}\n  {c.text[:160]}...")
