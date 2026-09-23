# app/

| File | Role |
|---|---|
| `review_app.py` | Review screen: `streamlit run app/review_app.py`. Filter by status, see sources and consistency flags, approve / edit / reject, export. |
| `review_state.py` | Reviewer decisions, saved to `review_state.json` in the run folder on every click, so a review can be paused and resumed. |

Export logic lives in `tools/export_response.py` so it can also run without the UI.
