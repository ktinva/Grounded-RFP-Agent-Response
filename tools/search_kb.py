"""Hybrid search over approved knowledge-base chunks.

Two lexical retrievers, fused with reciprocal rank fusion (RRF):
  * BM25 over word tokens (with a small domain synonym/acronym expansion), which is
    strong on exact terms such as "SCIM", "RPO", "AES-256"
  * TF-IDF over character n-grams, which is tolerant of spelling and morphology
    ("sub-processor" vs "subprocessor", "encrypt" vs "encryption")

Why no neural embeddings by default: the corpus is ~65 chunks, the runtime must
work offline and deterministically, and lexical recall is measured (see
evals/retrieval_eval.py). The Retriever interface allows an embedding retriever
to be added to the fusion without changing callers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer

from tools.ingest import Chunk, ingest

STOPWORDS = set("""a an and are as at be by can do does for from has have how i if in is it its of on or our
please provide describe state confirm list what which who whom will with you your yours we us they this that
these those there any all into than then so such via per""".split())

# Acronyms and buyer phrasings mapped to the wording used in the documents.
SYNONYMS: dict[str, list[str]] = {
    "rpo": ["recovery point objective"], "rto": ["recovery time objective"],
    "sso": ["single sign-on", "saml", "openid"], "scim": ["provisioning"],
    "byok": ["customer-managed encryption keys", "bring your own key"],
    "cmk": ["customer-managed encryption keys"], "kms": ["key management"],
    "dpa": ["data processing addendum"], "siem": ["splunk", "datadog", "audit"],
    "pentest": ["penetration test"], "pen": ["penetration"], "mfa": ["multi-factor authentication"],
    "sla": ["service level", "uptime"], "uptime": ["availability"], "availability": ["uptime"],
    "p1": ["severity 1"], "sev1": ["severity 1"], "sev": ["severity"], "outage": ["severity 1", "downtime"],
    "breach": ["security incident", "personal data breach", "notify"], "notify": ["notification", "notice"],
    "residency": ["hosting region", "data location"], "region": ["hosting region"],
    "subprocessor": ["subprocessors"], "sub-processor": ["subprocessors"], "subprocessors": ["subprocessor"],
    "tenant": ["tenant isolation", "multi-tenant"], "segregation": ["tenant isolation", "separated"],
    "train": ["training", "fine-tune"], "training": ["train"], "llm": ["large language model"],
    "ai": ["generative", "model"], "backup": ["backups"], "backups": ["backup"],
    "retention": ["retained"], "retain": ["retained"], "kept": ["retained"], "keep": ["retained"],
    "delete": ["deletion", "deleted"], "termination": ["terminated"], "deprecation": ["deprecated", "versions"],
    "iso": ["iso/iec 27001"], "soc": ["soc 2 type ii"], "gdpr": ["processor"], "dr": ["disaster recovery"],
    "on-premises": ["on-premises", "customer-hosted"], "self-hosted": ["on-premises", "customer-hosted"],
    "cipher": ["aes-256"], "algorithm": ["aes-256"], "tls": ["transit"], "privatelink": ["private connectivity"],
    "throttling": ["rate limits"], "connectors": ["native connectors"], "logs": ["logged", "audit"],
    "patch": ["remediated", "vulnerabilities"], "remediation": ["remediated"],
    "loss": ["recovery point objective"], "lose": ["recovery point objective"],
    "restore": ["recovery", "backup"], "failure": ["outage", "disaster recovery"],
}


def tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+(?:[-/.][a-z0-9]+)*", text.lower())
    return [t for t in toks if t not in STOPWORDS]


def expand(query: str) -> str:
    extra = [s for t in tokenize(query) for s in SYNONYMS.get(t, [])]
    return query + (" " + " ".join(extra) if extra else "")


@dataclass
class Hit:
    chunk: Chunk
    score: float        # fused RRF score (rank-based, for ordering)
    lexical: float      # best TF-IDF cosine for this chunk across queries (0-1, for evidence floor)

    def to_dict(self) -> dict:
        return {**self.chunk.to_dict(), "score": round(self.score, 4), "lexical": round(self.lexical, 4)}


class KBIndex:
    RRF_K = 60

    def __init__(self, chunks: list[Chunk]):
        if not chunks:
            raise ValueError("no chunks to index (are any documents approved?)")
        self.chunks = chunks
        self.by_id = {c.chunk_id: c for c in chunks}
        docs = [c.search_text() for c in chunks]
        self.bm25 = BM25Okapi([tokenize(d) for d in docs])
        self.tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, lowercase=True)
        self.matrix = self.tfidf.fit_transform(docs)

    def _rank(self, query: str) -> tuple[list[int], list[int], np.ndarray]:
        q = expand(query)
        bm = self.bm25.get_scores(tokenize(q))
        cos = (self.matrix @ self.tfidf.transform([q]).T).toarray().ravel()
        return list(np.argsort(-bm)), list(np.argsort(-cos)), cos

    def search(self, queries: str | list[str], k: int = 8, doc_ids: set[str] | None = None) -> list[Hit]:
        """Fuse results for one or more query phrasings; returns the top-k chunks."""
        queries = [queries] if isinstance(queries, str) else [q for q in queries if q and q.strip()]
        fused: dict[int, float] = {}
        best_cos: dict[int, float] = {}
        for q in queries:
            bm_order, cos_order, cos = self._rank(q)
            for order in (bm_order, cos_order):
                for rank, idx in enumerate(order):
                    fused[idx] = fused.get(idx, 0.0) + 1.0 / (self.RRF_K + rank + 1)
            for idx, v in enumerate(cos):
                best_cos[idx] = max(best_cos.get(idx, 0.0), float(v))
        ranked = sorted(fused, key=lambda i: -fused[i])
        hits = [Hit(self.chunks[i], fused[i], best_cos[i]) for i in ranked
                if doc_ids is None or self.chunks[i].doc_id in doc_ids]
        return hits[:k]

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        return self.by_id.get(chunk_id)


@lru_cache(maxsize=1)
def default_index() -> KBIndex:
    return KBIndex(ingest())


def search_kb(query: str | list[str], k: int = 8) -> list[dict]:
    """Tool entry point: search approved documents only."""
    return [h.to_dict() for h in default_index().search(query, k=k)]


if __name__ == "__main__":
    import sys
    for h in default_index().search(" ".join(sys.argv[1:]) or "breach notification", k=5):
        print(f"{h.score:.4f} cos={h.lexical:.2f} [{h.chunk.chunk_id}] {h.chunk.section}: {h.chunk.text[:90]}")
