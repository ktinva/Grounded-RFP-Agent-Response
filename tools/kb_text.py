"""Read the knowledge base manifest and per-page PDF text.

Shared by the eval validator today and by the ingestion pipeline in Phase 1.
Page numbers are 1-based, matching the "Page N of M" footer printed on every page.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KB_DIR = ROOT / "data" / "sample" / "kb"


@dataclass(frozen=True)
class KBDocument:
    doc_id: str
    title: str
    version: str
    effective_date: str | None
    owner_team: str
    approval_status: str
    file: Path
    pages: int

    @property
    def approved(self) -> bool:
        return self.approval_status == "approved"


def normalize(text: str) -> str:
    """Lower-case, unify dashes/quotes, collapse whitespace. Used for fact matching."""
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip().lower()


@lru_cache(maxsize=4)
def load_manifest(kb_dir: Path = DEFAULT_KB_DIR) -> dict[str, KBDocument]:
    data = yaml.safe_load((kb_dir / "manifest.yaml").read_text(encoding="utf-8"))
    docs = {}
    for d in data["documents"]:
        docs[d["doc_id"]] = KBDocument(
            doc_id=d["doc_id"], title=d["title"], version=d["version"],
            effective_date=d.get("effective_date"), owner_team=d["owner_team"],
            approval_status=d["approval_status"], file=kb_dir / d["file"], pages=int(d["pages"]),
        )
    return docs


@lru_cache(maxsize=64)
def page_texts(pdf_path: Path) -> tuple[str, ...]:
    """Raw text of each page, index 0 == page 1."""
    return tuple(p.extract_text() or "" for p in PdfReader(str(pdf_path)).pages)


def get_page(doc: KBDocument, page: int) -> str:
    texts = page_texts(doc.file)
    if not 1 <= page <= len(texts):
        raise IndexError(f"{doc.doc_id} has {len(texts)} pages; page {page} requested")
    return texts[page - 1]
