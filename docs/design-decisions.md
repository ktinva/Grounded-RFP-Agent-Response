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
