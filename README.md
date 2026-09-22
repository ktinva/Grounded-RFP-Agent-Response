# Grounded RFP Response Agent

An AI agent that drafts answers to RFPs and security questionnaires using **only** a company's approved documentation. Every answer cites a document and page. When the documentation can't support an answer, the agent says so, flags conflicts, or routes the question to the right team instead of guessing.

> **Status: Phase 0 complete.** The sample knowledge base, golden eval set, sample questionnaires, and validation suite are built. The agent (Phase 1+) is next. Sections below marked *planned* describe the design; they are not yet implemented.

## 1. What business problem does this solve?

Security questionnaires and RFPs take solutions engineers days per deal, and most questions repeat. The risk isn't slowness; it's a confident wrong answer that becomes a contractual representation. This agent makes the repetitive 70% fast and pushes the risky 30% to the right people with evidence attached.

## 2. Who would use it?

Solutions engineers and pre-sales teams (primary). Security, legal, and product teams receive routed questions. Deal desks and proposal managers own the final submission.

## 3. What does the demo do? *(planned)*

Upload `data/sample/questionnaires/northgate_security_questionnaire.xlsx`. The agent drafts every row, and each row lands in one of five statuses: **Answered (cited)**, **Insufficient evidence**, **Conflict**, **Escalated → team**, or **Needs clarification**. A reviewer approves the answers, and the completed workbook is exported with citations filled in.

## 4. What is the architecture? *(planned)*

Ingestion → approved-only chunk store → classifier → hybrid retriever → drafter → independent verifier → consistency checker → router → review UI → export. Diagram: `architecture/architecture-diagram.png` (added in Phase 1).

## 5. Which tools can the agents call? *(planned)*

`parse_questionnaire`, `search_kb`, `get_page`, `verify_claim`, `compare_answers`, `route_question`, `export_response`.

## 6. How do you prevent hallucinations?

- Retrieval is limited to approved documents; an unapproved draft in the sample corpus tests this.
- Generation uses retrieved passages only, with a mandatory citation for each claim.
- A separate verifier checks every claim against its cited page.
- The agent abstains when evidence is thin.
- Sensitive topics are always escalated.
- A human approves every answer before export.

## 7. How is the system evaluated?

83 golden questions across the five required behaviors, all machine-verified against the PDFs. The headline metric is the **false-answer rate**; the gate for citations of the unapproved draft is zero. See [`evals/README.md`](evals/README.md).

| Test | Count | Expected |
|---|---|---|
| Covered in documentation | 32 | Answer with citation |
| Not covered | 14 | Say evidence is insufficient |
| Conflicting documents | 12 | Identify the conflict |
| Sensitive | 15 | Escalate |
| Ambiguous | 10 | Request clarification |

## 8. How could it be deployed in an enterprise? *(planned)*

SSO and RBAC per document collection. Connectors to SharePoint, Confluence, or Google Drive with an approval workflow. A full audit trail of answers, sources, and approvers. VPC deployment. An approved-answer library that grows with every signed-off questionnaire.

## 9. What are its limitations?

The agent is only as good as the knowledge base: stale documents give stale answers. The sample corpus is synthetic and cleaner than real documents. PDF tables and diagrams parse imperfectly. The verifier reduces unsupported claims but does not eliminate them. Legal language still needs a lawyer.

## 10. How can someone run it locally?

```bash
pip install -r requirements.txt
python -m tools.build_sample_corpus          # render KB PDFs + manifest
python -m tools.build_sample_questionnaires  # generate sample RFP + questionnaire
python -m evals.validate_golden_set          # verify eval set against the PDFs
pytest -q
```

Or with Docker: `docker compose up --build`

## Repository layout

```
├── app/            API, review UI, export writers              (planned)
├── agents/         orchestrator, classifier, drafter, verifier, router  (planned)
├── tools/          corpus + questionnaire builders, KB page reader
├── data/sample/    fictional knowledge base + customer questionnaires
├── evals/          golden set, validator, scoring rules
├── tests/          pytest suite
├── docs/           design decisions
└── architecture/   architecture diagram                        (Phase 1)
```

*All companies and documents in this repository are fictional.*
