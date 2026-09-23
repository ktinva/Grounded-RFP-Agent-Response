"""Cross-answer consistency checks over a finished questionnaire.

Per-question checks cannot see that two answers in the same file disagree. This
module runs once after all questions are answered:

  1. conflict_reliance (rule, no model)
     An answer repeats one side of a conflict that another question in the same file
     surfaced: it cites the conflicted passage AND its text contains a value that only
     that side has (e.g. "United Kingdom", "4"). Both questions are flagged.
     Live example: "Which cloud provider hosts the service?" volunteered UK hosting,
     which the DPA contradicts.
  2. contradiction (model, one call per topic group)
     Two answered questions state different values for the same fact, or one says
     yes where another says no. Differences explained by edition/tier or by
     different subjects are not contradictions. Every flag must name two real,
     answered questions or it is discarded.

Issues are attached to each affected Result (trace["consistency"]) and returned
as a list for the review report.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass

from agents.llm import LLM
from agents.pipeline import Citation, Result

CONSISTENCY_SYSTEM = """You review a vendor's draft answers to one customer questionnaire, all on the same topic.
Find pairs of answers that contradict each other: they state different values for the same fact
(a different number of days, hours, or percent for the same thing), or one says something is
available or true while another says it is not.

These are NOT contradictions:
- values that apply to different editions, tiers, or plans
- values about different things that happen to share a number or a word
- one answer being more detailed than another

Only report a pair if a careful reader would see the two answers cannot both be true.
Refer to answers by their ref exactly as given. If there are no contradictions, return an empty list."""

CONSISTENCY_SCHEMA = {
    "type": "object",
    "properties": {"issues": {"type": "array", "items": {
        "type": "object",
        "properties": {"refs": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2},
                       "fact": {"type": "string"}, "explanation": {"type": "string"}},
        "required": ["refs", "fact"]}}},
    "required": ["issues"],
}

MAX_GROUP = 15  # keep each model call small and focused


@dataclass
class Issue:
    kind: str            # conflict_reliance | contradiction
    refs: list[str]
    detail: str
    sources: list[str]   # doc p.N references involved

    def to_dict(self) -> dict:
        return asdict(self)


_STOP = {"the", "a", "an", "and", "or", "either", "of", "for", "to", "in", "on", "is", "are", "be", "by",
         "within", "at", "least", "most", "up", "hour", "hours", "day", "days", "minute", "minutes",
         "year", "years", "month", "months", "percent", "recovery", "point", "objective", "rpo", "rto"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower()) if t not in _STOP}


def _distinguishing(conflict: dict) -> dict[str, set[str]]:
    """For each conflict side, the tokens that only that side has (e.g. {'kingdom'} or {'4'})."""
    sides = conflict.get("sources", [])
    out = {}
    for i, s in enumerate(sides):
        others = set().union(*[_tokens(o["value"]) for j, o in enumerate(sides) if j != i]) if len(sides) > 1 else set()
        out[s["chunk_id"]] = _tokens(s["value"]) - others
    return out


def conflict_reliance(results: list[Result]) -> list[Issue]:
    """Flag answers that repeat one side of a conflict found elsewhere in the same questionnaire.

    Citing the same passage is not enough (a passage can hold an unrelated fact next to the
    conflicted one); the customer-facing answer must contain a value that distinguishes one side.
    """
    conflicted: dict[str, tuple[Result, set[str]]] = {}
    for r in results:
        if r.status == "conflict" and r.conflict:
            for chunk_id, toks in _distinguishing(r.conflict).items():
                conflicted[chunk_id] = (r, toks)
    issues = []
    for r in results:
        if r.status != "answered":
            continue
        answer_tokens = _tokens(r.answer)
        for c in r.citations:
            other, toks = conflicted.get(c.chunk_id, (None, set()))
            if other is not None and toks and toks & answer_tokens:
                topic = other.conflict.get("topic") or "this topic"
                issues.append(Issue(
                    kind="conflict_reliance", refs=[r.ref, other.ref],
                    detail=(f"{r.ref} is answered from {c.doc} p.{c.page}, which {other.ref} found to conflict "
                            f"with another document on {topic}. Confirm the correct value before sending."),
                    sources=[f"{s['doc']} p.{s['page']}" for s in other.conflict.get("sources", [])]))
                break
    return issues


def contradictions(results: list[Result], llm: LLM) -> list[Issue]:
    answered = [r for r in results if r.status == "answered" and r.answer]
    by_ref = {r.ref: r for r in answered}
    groups: dict[str, list[Result]] = defaultdict(list)
    for r in answered:
        groups[(r.trace.get("classifier") or {}).get("topic") or "general"].append(r)

    issues: list[Issue] = []
    for topic, group in groups.items():
        for i in range(0, len(group), MAX_GROUP):
            chunk = group[i:i + MAX_GROUP]
            if len(chunk) < 2:
                continue
            user = "\n\n".join(f"[{r.ref}] Q: {r.question}\nA: {r.answer}" for r in chunk)
            out = llm.json(system=CONSISTENCY_SYSTEM, user=f"Topic: {topic}\n\n{user}",
                           schema=CONSISTENCY_SCHEMA, purpose="consistency", max_tokens=1200)
            for it in out.get("issues") or []:
                refs = [x.strip().strip("[]") for x in it.get("refs") or []]
                if len(refs) != 2 or refs[0] == refs[1] or not all(x in by_ref for x in refs):
                    continue  # must name two real, answered questions
                srcs = sorted({f"{c.doc} p.{c.page}" for x in refs for c in by_ref[x].citations})
                issues.append(Issue(kind="contradiction", refs=refs,
                                    detail=f"{it.get('fact', '')}: {it.get('explanation', '')}".strip(": "),
                                    sources=srcs))
    return issues


def _claims_from_answer(r: Result) -> list[dict]:
    """Older results have no per-claim trace: pair answer sentences with citations when counts match."""
    sents = [x for x in re.split(r"(?<=[.!?])\s+", r.answer.strip()) if x]
    cites = r.citations
    if len(sents) == len(cites):
        pairs = zip(sents, cites)
    else:
        pairs = [(r.answer, cites[0])] if cites else []
    return [{"text": t, "chunk_id": c.chunk_id, "doc": c.doc, "page": c.page, "doc_title": c.doc_title,
             "quote": c.quote} for t, c in pairs]


def resolve_conflict_reliance(results: list[Result], issues: list[Issue]) -> list[str]:
    """Stop answers that repeat a contested value from going out as settled facts.

    For each flagged answer, remove the statements that contain a value unique to one side of the
    conflict. If the question itself names that contested value (for example it asks about the
    United Kingdom), or nothing is left, the question becomes a conflict. Otherwise the remaining,
    uncontested statements stay as the answer and the question is flagged for review.
    Returns the refs that changed.
    """
    by_ref = {r.ref: r for r in results}
    changed = []
    for i in issues:
        if i.kind != "conflict_reliance":
            continue
        r, other = by_ref.get(i.refs[0]), by_ref.get(i.refs[1])
        if r is None or other is None or r.status != "answered" or not other.conflict:
            continue
        toks = set().union(*_distinguishing(other.conflict).values())
        claims = r.trace.get("answer_claims") or _claims_from_answer(r)
        keep = [c for c in claims if not (_tokens(c["text"]) & toks)]
        r.trace["answer_before_consistency"] = r.answer
        if keep and not (_tokens(r.question) & toks):
            r.answer = " ".join(c["text"].strip().rstrip(".") + "." for c in keep)
            r.citations = [Citation(c["doc"], c["page"], c["chunk_id"], c["doc_title"], c["quote"]) for c in keep]
            r.trace["answer_claims"] = keep
            r.route_to = other.route_to
            r.route_reason = (f"A statement repeating a contested value was removed (see {other.ref}); "
                              "confirm before sending.")
        else:
            r.status = "conflict"
            r.conflict = dict(other.conflict)
            sides = other.conflict.get("sources", [])
            r.answer = "Approved documents disagree: " + "; ".join(
                f"{s.get('doc_title', s['doc'])} (p.{s['page']}) says {s['value']}" for s in sides) + "."
            r.citations = [Citation(s["doc"], s["page"], s["chunk_id"], s.get("doc_title", s["doc"]), s["value"])
                           for s in sides]
            r.route_to, r.route_reason = other.route_to, (f"The drafted answer repeated one side of a conflict "
                                                          f"found in {other.ref}; the owning team must confirm.")
        changed.append(r.ref)
    return changed


def check_consistency(results: list[Result], llm: LLM | None = None, resolve: bool = True) -> list[Issue]:
    issues = conflict_reliance(results)
    if llm is not None:
        seen = {tuple(sorted(i.refs)) for i in issues}
        issues += [i for i in contradictions(results, llm) if tuple(sorted(i.refs)) not in seen]
    by_ref = {r.ref: r for r in results}
    for i in issues:
        for ref in i.refs:
            if ref in by_ref:
                by_ref[ref].trace.setdefault("consistency", []).append(i.to_dict())
    if resolve:
        resolve_conflict_reliance(results, issues)
    return issues
