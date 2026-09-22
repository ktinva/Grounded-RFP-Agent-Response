# agents/

| File | Role |
|---|---|
| `pipeline.py` | Classifier, Drafter, Verifier, and the `RFPAgent` orchestrator (five terminal statuses) |
| `policy.py` | Topic taxonomy with owner teams, hard escalation rules, missing-attachment rule |
| `prompts.py` | System prompts and output schemas |
| `llm.py` | Claude client with forced structured output, disk cache, and a scripted test double |
| `run_questionnaire.py` | Answer any .xlsx/.docx and write `review.md` + `results.jsonl` |
