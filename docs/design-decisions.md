# Design decisions

A running log. Each entry states the decision, why, and what it costs.

## D1. Build the corpus and eval set before any agent code

**Decision:** Phase 0 delivers a fictional knowledge base, a golden eval set, and sample questionnaires. The agent itself comes later.
**Why:** "Grounded" has no meaning without a fixed definition of the right answer. Writing the evals first stops prompts from being tuned against a moving target.
**Cost:** Nothing is demoable until Phase 1.

## D2. Fictional company, documents written for the test

**Decision:** Kestrel Ridge Software and its documents are invented, with conflicts, hard negatives, and a draft trap planted on purpose.
**Why:** Real vendor documents can't be redistributed, and they would not contain known, labeled conflicts. Planting them makes conflict recall measurable.
**Cost:** Real documents are messier (scanned tables, contradictory versions, boilerplate). A later phase should add a messy-document test set.

## D3. Markdown source, rendered to PDF with fixed page breaks

**Decision:** Documents are authored in Markdown with explicit `===PAGE===` markers and rendered to PDF deterministically.
**Why:** Page-level citation is a stated requirement, so page numbers must be stable and reviewable in diffs. The Markdown is readable in code review; the PDFs are what the agent ingests, which matches production.
**Cost:** The renderer supports only a tiny Markdown subset. That is fine for sample data.

## D4. The golden set is machine-verified against the PDFs

**Decision:** Every evidence quote must appear verbatim on the cited page. Every "not covered" term must be absent from all approved documents. Every trap document must actually contain the bait. The validator runs in pytest and in the Docker build, and has its own negative tests.
**Why:** A hand-written eval set drifts. A single wrong page number in the expectations would reward the agent for citing the wrong page.
**Cost:** Evidence quotes must track document wording exactly, so editing a source document can break the evals. That breakage is intended.

## D5. Approval status is a first-class field, and a draft is in the corpus

**Decision:** The manifest carries `approval_status`, and one draft document with attractive false claims is included.
**Why:** In real companies, the worst hallucinations are not invented from nothing. They are copied from an unapproved draft or an outdated deck. Filtering must happen before retrieval, and the eval proves it does.
**Cost:** None significant.

## D6. Five terminal statuses, not a confidence score

**Decision:** Each question ends in exactly one status: `answered`, `insufficient_evidence`, `conflict`, `escalated`, or `needs_clarification`.
**Why:** Reviewers act on categories, not on a 0.73 score. The categories map one-to-one onto the brief's five tests, so eval scoring is exact.
**Cost:** Borderline cases, such as a partially covered question, must be forced into one bucket. The rule is that anything not fully supported is not `answered`.

## D7. Sensitive topics escalate even when evidence exists

**Decision:** Liability, indemnity, breach history, pricing, roadmap commitments, contract-paper changes, audits, financials, references, escrow, insurance, and AI warranties always escalate. Related excerpts may be attached for the human.
**Why:** These answers create commitments. A document that is merely *related* (for example, the SLA's "sole remedy" clause for a liability-cap question) is exactly what a model will over-extend.
**Cost:** Some questions a human could answer in seconds still go to a queue. That trade-off is acceptable.

## D8. Hard negatives for conflict detection

**Decision:** The eval includes three cases that look like conflicts but aren't: a tiered uptime figure, a reused "30 days", and an RTO stated next to the conflicting RPO.
**Why:** A conflict detector that fires on every repeated number is useless. Reviewers would learn to ignore it.

## D9. Questionnaires are generated from the golden set, never hand-typed

**Decision:** Every customer file, including the shipped samples, comes from one generator. It selects golden questions by count, category mix, and section, renders them in one of five layouts, and writes a hidden answer key.
**Why:** It makes any number of fresh, scorable questionnaires without hand-labeling, and the layouts exercise the parser the way real customer files will.
**Cost:** Generated questions can only be as varied as the golden set plus rewordings. Real questionnaires should still be added to the golden set over time.

## D10. Rewordings need human approval before they count

**Decision:** Alternate phrasings inherit their question's expectations, but they start as `pending` and are reviewed in a spreadsheet (approve / reject / edit). Runs that use pending rewordings are marked exploratory.
**Why:** A rewording can quietly change a question. "Can you guarantee UK data residency?" is closer to a sensitive commitment than "Can our data be stored in the UK?". A mislabeled test is worse than no test.
**Cost:** Reviewer time, roughly 166 rows for the initial bank.

## D11. No retrieval-score threshold for abstention

**Decision:** Abstention is decided by the drafter and then enforced by the verifier. A similarity cutoff plays no part.
**Why:** Measured on the golden set, top-hit similarity for answerable questions (0.12–0.59) overlaps heavily with unanswerable ones (0.05–0.33). Any threshold would either abstain on real answers or let unanswerable questions through.

## D12. The answer is the verified claims; the verifier's quote is re-checked in code

**Decision:** The drafter writes its answer as claims with passage references. The customer-facing answer is the concatenation of the claims that pass verification. A claim passes only if the verifier model says "supported" and its quote appears verbatim in the cited chunk.
**Why:** A model verifier can be wrong in the same way as the drafter. Checking the quote with a plain substring test cannot be argued with. Composing the answer from verified claims removes the gap where an unverified sentence could slip into prose written separately.
**Cost:** Answers read slightly more list-like than free prose.

## D13. Lexical hybrid retrieval, no embeddings (for now)

**Decision:** BM25 plus character n-gram TF-IDF, fused with reciprocal rank fusion, and a small domain synonym table. The classifier adds query rewrites.
**Why:** At about 65 chunks this is deterministic, offline, fast, and already reaches 97% covered recall@8. Embeddings would add a download or API dependency without a measured need.
**Cost:** It will not scale to large, loosely worded corpora unchanged. The fusion accepts another retriever when needed.

## D14. Rules first, model second, for escalation

**Decision:** A regex list of hard escalations runs before any model call. The classifier model can escalate more, but can never un-escalate a rule hit.
**Why:** These are the answers with the worst downside. Rules are auditable by legal and security leads, cannot be prompt-injected, and cost nothing.
**Cost:** The rules were tuned on this question set (0 false positives and 0 misses on 249 wordings). Novel phrasings rely on the classifier, so escalation recall on new questionnaires should be watched.

## D15. Every model call is cached on disk

**Decision:** Identical (model, prompt, schema) calls replay from `.cache/llm/`.
**Why:** Eval runs become repeatable and re-runs are free. That matters because scoring changes and questionnaire regeneration happen far more often than prompt changes.
**Cost:** After changing documents or prompts, stale entries are simply never hit again. Set `LLM_CACHE=0` to force fresh calls.

## D16. Tolerate and repair malformed structured output

**Context:** In the first live run, 18% of drafter replies were malformed: `status` was missing, or the fields were wrapped in `{"params": ...}`. The pipeline treated these as "insufficient evidence" and discarded correct answers and six correct conflict detections.
**Decision:**
1. Unwrap known wrapper keys.
2. If a required field is still missing, retry once, telling the model which field is missing. Only valid replies are cached.
3. As a last resort, the pipeline infers the status from what came back: conflict sides mean `conflict`, claims mean `answered`.
**Why:** Inferring `answered` is safe because the claims still go through verification. A format slip should never cost a correct answer.

## D17. "What do your published terms say?" is factual; "Will you agree to…?" is sensitive

**Context:** The classifier escalated questions about service credits, maintenance windows, breach-notification timelines, and AI training on customer data, treating them as commitments.
**Decision:** The classifier prompt now separates reporting what approved documents state (not sensitive) from making a new commitment, disclosing something confidential, or deciding something unwritten (sensitive). Asking whether something is offered is not sensitive; missing evidence is the drafter's call.
**Guardrail:** The hard escalation rules are unchanged and still run first, so this relaxation cannot un-escalate a rule hit.

## D18. Ambiguity is checked before sensitivity, and needs a missing subject

**Decision:**
- A question is ambiguous only when it leaves out *which thing* it asks about. Conditions, edition differences, and possible document conflicts do not make it ambiguous.
- When the classifier flags a question as both ambiguous and sensitive, the agent asks for clarification first.
**Why:** Clarification is cheap. The right owner for an ambiguous question isn't known until the buyer says what they mean.

## D19. One redraft round after verification

**Decision:** When the verifier rejects claims, the drafter sees the rejected claims and the reasons, and gets one chance to restate them faithfully or drop them. The redraft replaces the original only if at least as many claims verify.
**Why:** In the live run, the verifier correctly rejected an added "only". Without a repair path, a correct answer became an abstention.
**Cost:** Up to two extra model calls, only for questions with rejected claims.

## D20. Eval questions must never appear in prompts

**Context:** While fixing the live failures, it turned out that several prompt examples were golden-set questions quoted verbatim ("What is your retention period?", "Are you compliant?"). The drafter's examples came from the golden set's notes. That lets the eval partly measure recall of its own examples.
**Decision:** All prompt examples were replaced with ones from outside the eval set. `test_prompts_contain_no_eval_questions` fails if any golden question or rewording appears in a prompt.
**Remaining risk:** The prompt fixes were still motivated by golden-set failures. Scores on freshly generated questionnaires and approved rewordings are the fairer check.

## D21. Consistency: rule first, then model, and flags must be concrete

**Decision:**
- **Rule:** an answer is flagged when it cites a passage that another question found to be in conflict *and* its text contains a value unique to one side ("United Kingdom", "4"). Sharing a passage alone is not enough; the live RTO answer shares a sentence with the RPO conflict and is correctly not flagged.
- **Model:** a per-topic check looks for contradictions. Its flags are discarded unless they name two real, answered questions.
**Why:** In the live run, the rule caught "Which cloud provider hosts the service?" volunteering UK hosting that the DPA contradicts. No per-question check could have seen that.

## D22. Review before export, and export into a copy of the customer's file

**Decision:**
- Reviewer decisions live in `review_state.json` beside the run. Only answered questions can be approved unchanged; anything else must be written by the reviewer and is marked human-written.
- Export writes approved and edited answers into a copy of the original file, at the cell or paragraph the parser recorded. It refuses to overwrite the original.
**Why:** Buyers want their own file back. "The agent drafted it, a named person approved it" must hold for every sentence that leaves the company.

## D23. Second live run: the remaining silent picks and format slips

**Context:** Run 2 (2026-09-23) passed 90% overall (from 73%) and covered accuracy reached 97%, but conflict recall was 58% and the false-answer rate was 6%. Tracing the failures turned up four causes:
1. The drafter answered "UK hosting is available" from the product overview without noticing that the DPA disagrees.
2. A correct 30-vs-90-day backup conflict was rejected because the quoted value ended in a full stop, and the draft sent `"claims": "null"`.
3. The scorer failed a correct conflict because the agent quoted a longer sentence than the golden evidence.
4. The two audit-log answers stated both figures, which, as it turned out, is the right behaviour (D24).

**Decision:**
- The drafter prompt now tells it to check other documents, contracts especially, for a different value before answering.
- Draft fields are type-sanitised.
- Conflict values are compared without trailing punctuation.
- The scorer accepts a quote that contains the evidence.
- An answer that repeats one side of a conflict found elsewhere in the questionnaire is resolved automatically (`resolve_conflict_reliance`):
  - If the question is *about* the contested value (it names "United Kingdom"), or no uncontested statement remains, the question becomes a conflict.
  - Otherwise the contested statement is removed, and the rest of the answer stays, flagged for review.

## D24. Audit logs: 1 year stored vs 180 days via API is not a conflict (reviewed 2026-09-23)

**Decision (product owner):** An answer that states both figures with both citations is correct. CF-011 and CF-012 became covered questions COV-033 and COV-034. They must state "1 year" *and* "180 days", and they are also hard negatives for conflict detection. The entries were edited in place, so questionnaire references stay stable.

## D25. Escalating an undocumented topic to the right owner is a pass (reviewed 2026-09-23)

**Decision (product owner):** For not-covered questions, `escalated` to the golden owner scores the same as `insufficient_evidence`. Escalation to the wrong team still fails. Over-escalation is reported as its own number (14% in run 2), so the noise it creates for legal and SE stays visible.

## D26. Re-score without re-running

**Decision:** `python -m evals.rescore <run>` re-scores saved results under the current golden set and rules. `--consistency` re-applies the rule-based consistency resolution. No model calls are made, and the previous scorecard is kept as `*.prev`.
**Caveat:** a re-scored run shows the effect of scoring and post-processing changes only. Prompt and code changes to drafting still need a live run.

## D27. Verbatim means same words in the same order, not same punctuation (run 3)

**Context:** Run 3 (2026-09-23) passed every release gate on both the sample (96%) and a generated Acme Health file (98%). The two questions it lost were both caused by checks in my code that were stricter than intended:
- **On-premises:** a correct answer was dropped because the verifier supported it with two sentences from the same passage. The code required one continuous quote.
- **Breach notification:** a real conflict was rejected because the drafter quoted "within 48 hours after becoming aware" and the DPA has a comma after "hours".

**Decision:** Quote and conflict-value checks now ignore case, whitespace, and punctuation, but not words, numbers, or their order. A quote made of several pieces (joined by "..." or placed one after another) passes only if every piece is verbatim in the cited passage. Tests show that fabricated text, an inserted "only", and a changed number are still rejected. The verifier prompt now tells it how to quote multi-sentence support.

## D28. A generated questionnaire is only an independent test if its wording is new

**Context:** The Acme Health run (40 questions, Yes/No layout, seed 42) reused 78 of its 83 model responses from the cache, because its questions are worded exactly like the golden set. It proves the Yes/No layout parses and scores correctly, but its answers are the sample run's answers.
**Decision:** For a generalization check, generate with reworded questions (`--reworded 1.0`). Until rewordings are approved, that means `--include-pending`, and the run is labeled exploratory.

## D29. A rule-based check on what the model verifier approves (reworded run)

**Context:** In the first run on approved rewordings (Borealis Bank, 40 questions, 95% pass), the agent answered "Do you offer round-the-clock availability?" with "The service is **available continuously**, with an uptime commitment of at least 99.9%…". The model verifier approved it, quoting only the uptime sentence. The code check (D12) confirmed that the quote was verbatim, but not that it supported every part of the claim.
**Decision:** After the model verifier approves a claim, code checks that every number, and every overclaiming word (continuously, always, never, only, guaranteed, fully, all, every, 24/7…), in the claim also appears in the cited passage. If one doesn't, the claim is rejected and goes through the redraft round.
**Validation:** Replayed over all 211 claims the verifier approved in four live runs, the check rejects exactly one: the "continuously" overclaim. It wrongly rejects none.
**Limit:** it catches invented numbers and absolute words, not every paraphrase that shifts meaning. The model verifier and human review remain the main defence for those.

## D30. Reviewer rulings reach the agent through a checked data file (decided 2026-09-23)

**Context:** In the reworded run, "How far back can we retrieve audit events?" was flagged as a conflict (1 year vs 180 days), even though the product owner had ruled these are different things (D24). The agent had no way to know about that ruling.
**Decision:**
- Rulings live in `data/sample/resolutions.yaml`. Each one records the exact statements involved, the ruling (`not_a_conflict`), short guidance, who decided, and when.
- The drafter sees a ruling only when all of its statements are among the retrieved passages.
- If the drafter still reports a conflict on a ruled pair, it gets one redraft that points to the ruling. If it insists, the conflict stands, which is the safe outcome.
- A ruling is guidance, never evidence: it cannot be cited, and every claim is still verified against the documents.
- `python -m tools.resolutions` and the tests confirm that every quoted statement still appears in an approved document, so a ruling cannot outlive the text it is about.

**Why a file and not a prompt tweak:** rulings are company decisions with an owner and a date. They should be reviewable and auditable, and they should apply only where relevant. This is the first piece of the approved-answer library.

## D31. An ambiguous question may be answered if every reading is answered (decided 2026-09-23)

**Decision:**
- An ambiguous golden question with `answer_all_facts` also passes when the answer covers every reading, with one documented fact per reading, and cites a source.
- An answer to only one reading still fails, and it counts toward the false-answer rate.
- The rule applies only where every reading can be answered from the documents and told apart by a fact: AMB-005 (limits) and AMB-008 (24/7). The others stay strict. The notice-period question is excluded because its readings mostly share "30 days", so a text check can't confirm that all five were covered.
- The drafter prompt allows answering every reading explicitly, and forbids answering just one.
- The clarification-rate gate now counts ambiguous questions that were handled either way.

**Live trigger:** the reworded run answered "Do you offer round-the-clock availability?" with uptime only. Under this rule it still fails, correctly.
