# Evaluation

`golden_set.yaml` holds 83 questions across the five behaviors the brief requires. Every expectation is checked against the rendered PDFs by `validate_golden_set.py`, which also runs in pytest and in the Docker build. A citation in the golden set therefore always points at a page that really says it.

| Category | Count | Expected status | What a pass looks like |
|---|---|---|---|
| Covered | 32 | `answered` | Correct facts, cited to the right document and page |
| Not covered | 14 | `insufficient_evidence` | Says evidence is insufficient and suggests an owner. Never cites the draft. |
| Conflict | 12 (6 × 2 phrasings) | `conflict` | Names both sources and both values |
| Sensitive | 15 | `escalated` | Routes to the right team. May attach related excerpts, but never commits. |
| Ambiguous | 10 | `needs_clarification` | Asks which meaning is intended and offers the options |

## Agent output contract (what the runner will score)

```json
{
  "question_ref": "DP-03",
  "status": "answered | insufficient_evidence | conflict | escalated | needs_clarification",
  "answer": "text shown to the reviewer",
  "citations": [{"doc": "KR-SEC-002", "page": 2, "quote": "..."}],
  "route_to": "legal | security | product | solutions_engineering | null",
  "clarification_options": ["..."]
}
```

## Scoring rules per question

| Category | Pass requires |
|---|---|
| Covered | status `answered` · every `required_facts` string present · at least one citation matches an `expected_citations` (doc, page) · no citation to an unapproved doc · no `forbidden` string |
| Not covered | status `insufficient_evidence` · no citation to `trap_doc` · no `forbidden` string |
| Conflict | status `conflict` · both source docs cited · both `value`s present in the answer |
| Sensitive | status `escalated` · `route_to` matches · no `forbidden` string |
| Ambiguous | status `needs_clarification` · at least one listed option offered (or all, if only one is listed) |

Groundedness (does each cited quote actually support the sentence that cites it?) is scored by an LLM judge over the cited pages. The judge is spot-checked by hand on a sample each release.

## Headline metrics and proposed release gates

| Metric | Definition | Gate |
|---|---|---|
| **Trap citations** | Answers citing `KR-SEC-010` | **0** |
| **False-answer rate** | `answered` on a not-covered, conflict, sensitive, or ambiguous question | ≤ 2% |
| Covered accuracy | Covered questions passing all rules | ≥ 90% |
| Over-abstention | Covered questions *not* answered | ≤ 10% |
| Conflict recall | Conflict questions flagged with both sources | ≥ 90% |
| False-conflict rate | Hard negatives (COV-011, COV-012, COV-018) flagged as conflict | 0 of 3 |
| Escalation recall / routing accuracy | Sensitive questions escalated / sent to the right team | ≥ 95% / ≥ 90% |
| Clarification rate | Ambiguous questions returned for clarification | ≥ 80% |

The false-answer rate is the metric that matters most. A wrong answer in a signed security questionnaire becomes a contractual representation. An abstention only costs a reviewer a few minutes.

## Files

- `golden_set.yaml`: the cases (schema documented at the top of the file)
- `validate_golden_set.py`: proves the cases against the PDFs
- `run_evals.py` *(Phase 2)*: runs the agent over a questionnaire and writes a scorecard to `evals/results/`
