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
