---
doc_id: KR-AI-007
title: AI Data Use and Model Governance
version: "1.1"
effective_date: 2026-04-01
owner_team: product
approval_status: approved
---
## 1. Use of Customer Data

Kestrel does not use Customer Data, including prompts, uploaded documents, and generated outputs, to train or fine-tune any AI models. Kestrel's contracts with third-party model providers prohibit them from using Customer Data to train their models.

## 2. Prompt and Output Logs

Prompts and generated outputs are logged for abuse monitoring and troubleshooting. Prompt and output logs are retained for 30 days and then deleted. Enterprise Premium customers can configure prompt log retention down to 0 days.

## 3. How Generative Features Work

Kestrel Insight uses large language models from a third-party provider, accessed over an encrypted API. The model receives only the question and the document passages that the requesting user is permitted to see. Retrieval enforces the same collection permissions as search.
===PAGE===
## 4. Grounding and Citations

Generated answers are grounded in the customer's own documents. Each answer includes citations to the source document and page number, so users can verify the answer. When the retrieved passages do not support an answer, Kestrel Insight states that it could not find enough information instead of guessing.

## 5. Evaluation and Testing

- Before each model or prompt change is released, Kestrel evaluates it on an internal benchmark that measures answer accuracy, citation correctness, and unsupported-answer rate.
- Kestrel performs adversarial testing, including prompt injection testing, before major releases.
- Kestrel monitors production answer quality through user feedback.
===PAGE===
## 6. Governance

An AI Governance Committee, chaired by the Chief Technology Officer and including representatives from security, legal, and product, reviews new AI features before release and reviews AI risks quarterly.

## 7. Customer Controls

- Administrators can disable generative AI features for an entire workspace or for individual collections.
- Kestrel notifies Enterprise and Enterprise Premium customers at least 30 days before changing the underlying model provider.
- Administrators can export a log of AI interactions for their workspace.
