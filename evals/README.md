# Evaluation

## What gets evaluated

`golden_set.yaml` holds 83 questions across the five required behaviors. `validate_golden_set.py` checks every expectation against the rendered PDFs. It runs in pytest and in the Docker build, so a citation in the golden set always points at a page that really says it.

| Category | Count | Expected status | What a pass looks like |
|---|---|---|---|
| Covered | 32 | `answered` | Correct facts, cited to the right document and page |
| Not covered | 14 | `insufficient_evidence` | Says evidence is insufficient. Never cites the draft. |
| Conflict | 12 (6 × 2 phrasings) | `conflict` | Names both documents and both values |
| Sensitive | 15 | `escalated` | Routes to the right team, and never commits |
| Ambiguous | 10 | `needs_clarification` | Asks which meaning is intended |

`rewordings.yaml` holds two alternate phrasings per question (166 in total), written in the styles real buyers use. A rewording inherits all expectations of its question, which is only valid if it asks the same thing. So every rewording starts as `pending`. A file built with pending rewordings is marked `scored: false`, and its scorecard is labeled exploratory.

## Commands

| Command | Needs API key | What it does |
|---|---|---|
| `python -m evals.validate_golden_set` | no | Proves the golden set against the PDFs |
| `python -m evals.retrieval_eval [--k 8] [--show-misses]` | no | Search recall for original and reworded questions |
| `pytest -q` | no | 50 tests, including full scripted-model runs |
| `python -m tools.generate_questionnaire ...` | no | New questionnaire plus hidden answer key |
| `python -m tools.rewordings export / import` | no | Human review of rewordings |
| `python -m tools.rewordings propose` | yes | Ask Claude for more rewordings (arrive as `pending`) |
| `python -m evals.run_evals <file>` | yes | Run the agent and score it: `scorecard.md`, `scorecard.json`, `review.md`, `results.jsonl` |

`run_evals` exits with code 1 if any release gate fails, so it can gate CI.

## Scoring rules per question (`scoring.py`)

| Category | Pass requires |
|---|---|
| Covered | Status `answered`, every `required_facts` string present in the answer or its verified quotes, at least one citation on an expected (doc, page), no unapproved citation, and no `forbidden` string |
| Not covered | Status `insufficient_evidence`, no unapproved citation, and no `forbidden` string |
| Conflict | Status `conflict`, both golden documents among the conflict sources, and each side's value is a phrase from that document's evidence (paraphrases like "the United States, the European Union…" for "US, EU" are accepted) |
| Sensitive | Status `escalated` and `route_to` matches |
| Ambiguous | Status `needs_clarification` |

## Release gates

| Metric | Definition | Gate |
|---|---|---|
| **Trap citations** | Any citation or excerpt from an unapproved document | **0** |
| **False-answer rate** | `answered` on a not-covered, conflict, sensitive, or ambiguous question | ≤ 2% |
| Covered accuracy | Covered questions passing all rules | ≥ 90% |
| Over-abstention | Covered questions not answered | ≤ 10% |
| Conflict recall | Conflict questions passing | ≥ 90% |
| False conflicts | Hard negatives (COV-011, COV-012, COV-018) flagged as conflicts | 0 |
| Escalation recall / routing accuracy | Sensitive questions escalated / routed correctly | ≥ 95% / ≥ 90% |
| Clarification rate | Ambiguous questions returned for clarification | ≥ 80% |

The false-answer rate is the metric that matters most. A wrong answer in a signed security questionnaire becomes a contractual representation; an abstention costs a reviewer a few minutes.

## Offline baseline (measured here, no model)

Retrieval recall at k=8, using the raw question as the query:

| | Original wording | Reworded (pending) |
|---|---|---|
| Covered | 97% (32) | 98% (64) |
| Conflict, both sides | 92% (12) | 92% (24) |
| Sensitive, supporting excerpt | 83% (6) | 92% (12) |

In the full pipeline, the classifier adds up to three queries in the documents' own vocabulary, which targets the remaining misses (for example "how quickly will you tell us" → breach notification).

Similarity scores can't separate answerable from unanswerable questions: the top-hit similarity for covered questions ranges 0.12–0.59, and for not-covered questions 0.05–0.33. So abstention is decided by the drafter and verifier, not by a retrieval threshold.

The scripted "perfect model" in `tests/oracle_llm.py` scores 100% with all gates passing, on both the full sample and a generated, reworded `.docx`. That proves the parsing, retrieval, id mapping, verification, routing and scoring chain. It says nothing about the real model's judgment; that is what `run_evals` with a key measures.
