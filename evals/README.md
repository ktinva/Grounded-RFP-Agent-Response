# Evaluation

## What gets evaluated

`golden_set.yaml` holds 83 questions across the five required behaviors. `validate_golden_set.py` checks every expectation against the rendered PDFs. It runs in pytest and in the Docker build, so a citation in the golden set always points at a page that really says it.

| Category | Count | Expected status | What a pass looks like |
|---|---|---|---|
| Covered | 34 | `answered` | Correct facts, cited to the right document and page |
| Not covered | 14 | `insufficient_evidence` (or `escalated` to the right owner, D25) | Says evidence is insufficient. Never cites the draft. |
| Conflict | 10 (5 × 2 phrasings) | `conflict` | Names both documents and both values |
| Sensitive | 15 | `escalated` | Routes to the right team, and never commits |
| Ambiguous | 10 | `needs_clarification` | Asks which meaning is intended |

`rewordings.yaml` holds two alternate phrasings per question (166 in total), written in the styles real buyers use. A rewording inherits all expectations of its question, which is only valid if it asks the same thing. So every rewording starts as `pending`. A file built with pending rewordings is marked `scored: false`, and its scorecard is labeled exploratory.

## Commands

| Command | Needs API key | What it does |
|---|---|---|
| `python -m evals.validate_golden_set` | no | Proves the golden set against the PDFs |
| `python -m evals.retrieval_eval [--k 8] [--show-misses]` | no | Search recall for original and reworded questions |
| `pytest -q` | no | 102 tests, including full scripted-model runs and live-run regressions |
| `python -m tools.resolutions` | no | Check reviewer rulings against the approved documents (D30) |
| `python -m evals.rescore <run> [--consistency]` | no | Re-score saved results under the current rules (D26) |
| `python -m tools.generate_questionnaire ...` | no | New questionnaire plus hidden answer key |
| `python -m tools.rewordings export / import` | no | Human review of rewordings |
| `python -m tools.rewordings propose` | yes | Ask Claude for more rewordings (arrive as `pending`) |
| `python -m evals.run_evals <file> [--out DIR]` | yes | Run the agent and score it: `scorecard.md`, `scorecard.json`, `review.md`, `results.jsonl` |
| `python -m evals.compare_runs <before> <after>` | no | Metric changes and questions that flipped between two runs |

`run_evals` exits with code 1 if any release gate fails, so it can gate CI.

## Scoring rules per question (`scoring.py`)

| Category | Pass requires |
|---|---|
| Covered | Status `answered`, every `required_facts` string present in the answer or its verified quotes, at least one citation on an expected (doc, page), no unapproved citation, and no `forbidden` string |
| Not covered | Status `insufficient_evidence`, or `escalated` to the golden owner (reported as over-escalation); no unapproved citation, and no `forbidden` string |
| Conflict | Status `conflict`, both golden documents among the conflict sources, and each side's value is a phrase from that document's evidence (paraphrases like "the United States, the European Union…" for "US, EU" are accepted) |
| Sensitive | Status `escalated` and `route_to` matches |
| Ambiguous | Status `needs_clarification`; or, for questions with `answer_all_facts`, an answer covering every reading with a documented fact (D31) |

## Release gates

| Metric | Definition | Gate |
|---|---|---|
| **Trap citations** | Any citation or excerpt from an unapproved document | **0** |
| **False-answer rate** | `answered` on a not-covered, conflict, sensitive, or ambiguous question | ≤ 2% |
| Covered accuracy | Covered questions passing all rules | ≥ 90% |
| Over-abstention | Covered questions not answered | ≤ 10% |
| Conflict recall | Conflict questions passing | ≥ 90% |
| False conflicts | Hard negatives (COV-011, COV-012, COV-018, COV-033, COV-034) flagged as conflicts | 0 |
| Escalation recall / routing accuracy | Sensitive questions escalated / routed correctly | ≥ 95% / ≥ 90% |
| Clarification rate | Ambiguous questions handled: clarification asked, or every reading answered (D31) | ≥ 80% |

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

## Live runs

| Date | Model | File | Pass | False-answer | Covered | Conflict recall | Notes |
|---|---|---|---|---|---|---|---|
| 2026-09-22 | default (`RFP_AGENT_MODEL`) | 83-question sample | 73% | 2% | 75% | 25% | Safety gates held. Too cautious; see design decisions D16–D22. |
| 2026-09-22 | default (`RFP_AGENT_MODEL`) | 20-question RFP | 65% | 8% | 62% | 33% | The one false answer: Salesforce "not listed" (fixed in the drafter prompt) |
| 2026-09-23 | claude-sonnet-5 | 83-question sample | 90% | 6% | 97% | 58% | After D16–D22. Remaining failures traced in D23. |
| 2026-09-23 (re-scored) | same answers | 83-question sample | 98% | 0% | 97% | 90% | Run 2 answers under D24/D25 rules plus the D23 consistency resolution. All gates pass; the BC-06 code fix still needs a live run. |
| 2026-09-23 run 3 | claude-sonnet-5 | 83-question sample | 96% | 0% | 94% | 90% | **All gates pass on a live run.** BC-06 fixed. Two losses traced to over-strict matching (D27). |
| 2026-09-23 | claude-sonnet-5 | Borealis Bank, 40 questions, **all reworded** (approved), Word table layout | 95% | 4% | 94% | 100% | First run on new wording. One false answer was a verifier-approved overclaim ("available continuously"), now blocked in code (D29). |
| 2026-09-23 run 3 | claude-sonnet-5 | Acme Health, 40 questions, Yes/No layout | 98% | 0% | 94% | 100% | All gates pass. Not independent: 78 of 83 calls came from the cache, because the wording matches the golden set (D28). |

When re-running after a change, keep the previous results so you can compare:

```bash
mv evals/results/northgate_security_questionnaire evals/results/baseline_2026-09-22
python -m evals.run_evals data/sample/questionnaires/northgate_security_questionnaire.xlsx
python -m evals.compare_runs evals/results/baseline_2026-09-22 evals/results/northgate_security_questionnaire
```

**Tuning caveat:** the fixes after the first live run were motivated by golden-set failures. No eval question appears in any prompt (enforced by a test), but for a fair read on generalization, also score a freshly generated questionnaire with a new seed, and approved rewordings once they exist.
