# Sample data

Everything in `data/sample/` is **fictional**. Kestrel Ridge Software, its product Kestrel Insight, and the buyer Northgate Mutual are invented. The documents were written to exercise the agent's five required behaviors, and some of them contain deliberate errors.

```
data/sample/
├── kb_source/        Markdown source of truth for every knowledge-base document
├── kb/               Rendered PDFs + manifest.yaml (generated, do not edit)
└── questionnaires/   Customer files the agent is asked to complete + answer key (generated)
```

Rebuild everything with:

```bash
python -m tools.build_sample_corpus          # kb_source/*.md  -> kb/*.pdf + manifest.yaml
python -m tools.build_sample_questionnaires  # golden_set.yaml -> questionnaires/*
python -m evals.validate_golden_set          # prove every expectation against the PDFs
```

PDFs are rendered deterministically, so a rebuild with unchanged sources is byte-identical, and the SHA-256 hashes in the manifest stay stable.

## Knowledge base

| Doc ID | Title | Ver. | Pages | Owner | Status |
|---|---|---|---|---|---|
| KR-PROD-001 | Kestrel Insight Product Overview | 4.0 | 3 | product | approved |
| KR-SEC-002 | Kestrel Insight Security Whitepaper | 2.3 | 4 | security | approved |
| KR-CMP-003 | Compliance and Certifications Overview | 1.4 | 2 | security | approved |
| KR-BCP-004 | Business Continuity and Disaster Recovery Summary | 1.2 | 2 | security | approved |
| KR-SLA-005 | Kestrel Insight Service Level Agreement | 3.1 | 3 | legal | approved |
| KR-DPA-006 | Data Processing Addendum | 2.0 | 3 | legal | approved |
| KR-AI-007 | AI Data Use and Model Governance | 1.1 | 3 | product | approved |
| KR-SUP-008 | Support and Maintenance Policy | 2.2 | 2 | solutions_engineering | approved |
| KR-ARC-009 | Technical Architecture and Integrations Guide | 1.5 | 3 | solutions_engineering | approved |
| KR-SEC-010 | Security Whitepaper v3.0 **DRAFT** | 3.0-draft | 1 | security | **draft** |

Each page carries a `Page N of M` footer. A test asserts that the footer equals the physical page index, so a citation of "KR-SEC-002 p.4" always refers to the same page a human reviewer sees.

## Planted conflicts

Each conflict involves two approved documents that disagree. The correct behavior is to show both, not to pick one.

| # | Topic | Source A | Source B |
|---|---|---|---|
| 1 | Breach notification | SEC-002 p.4: **72 hours** after confirmation | DPA-006 p.3: **48 hours** after awareness |
| 2 | Backup retention | SEC-002 p.4: **30 days** | BCP-004 p.1: **90 days** |
| 3 | RPO | BCP-004 p.1: **4 hours** | SLA-005 p.3: **1 hour** |
| 4 | Sev 1 initial response | SLA-005 p.3: **1 hour** | SUP-008 p.1: **30 minutes** |
| 5 | Hosting regions | PROD-001 p.2: **US, EU, UK** | DPA-006 p.2: **US or EU** |

## Hard negatives: look like conflicts but aren't

- **Uptime:** 99.9% (Business/Enterprise) and 99.95% (Enterprise Premium) are tiered by edition. They are consistent across PROD-001 and SLA-005.
- **"30 days":** used for prompt log retention (AI-007), post-termination deletion (DPA-006), subprocessor notice (DPA-006), and object versioning (BCP-004). The number is the same, but the subjects differ.
- **Audit logs:** 1 year stored (SEC-002 p.3) and 180 days via the Audit Log API (ARC-009 p.3). This was planted as a conflict, but the product owner decided on 2026-09-23 that these are two different things; a correct answer states both (golden COV-033 and COV-034).
- **RTO (12 hours):** stated once, in BCP-004. It sits right next to the conflicting RPO and must not inherit that conflict.

## Trap document

`KR-SEC-010` is an unapproved draft. It claims FedRAMP Moderate, a HIPAA BAA, PCI DSS compliance, a bug bounty program, and semiannual penetration tests. **None of these appear in any approved document.** An agent that searches the draft will produce confident, cited, wrong answers. The retriever must filter on `approval_status: approved` before search, not after.

## Sample questionnaires

| File | Questions | Layout |
|---|---|---|
| `northgate_security_questionnaire.xlsx` | 83 (all golden-set questions) | `standard`: Ref / Section / Question / Response / Evidence / Comments |
| `northgate_rfp.docx` | 20 (mixed subset) | `numbered`: narrative RFP, requirements numbered 4.x.y |

Each file has an answer key beside it (`<name>.key.yaml`) that maps each questionnaire reference to its golden-set ID and records the wording used. Only the eval runner reads the key; the agent never sees it. Neither customer file contains category labels or expected behavior, and a test enforces this.

Both files are ordinary generator runs with pinned arguments (`tools/build_sample_questionnaires.py`).

## Generating more

`python -m tools.generate_questionnaire` writes new files to `data/generated/`, which git ignores. You choose the buyer name, format, layout, question count or exact category mix, sections, and the fraction of reworded questions. The same seed always produces the same questions. See the top-level README for examples.

| Format | Layouts |
|---|---|
| xlsx | `standard`, `yes_no` (header lower down, Yes/No column plus explanation column), `by_section` (one sheet per section) |
| docx | `numbered`, `table` (a requirements table per section) |

Reworded questions come from `evals/rewordings.yaml`. Only human-approved rewordings are used unless `--include-pending` is passed.
