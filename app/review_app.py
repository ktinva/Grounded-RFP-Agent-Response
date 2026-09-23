"""Review screen: approve, edit, or reject each drafted answer, then export.

  streamlit run app/review_app.py
  streamlit run app/review_app.py -- --run evals/results/northgate_rfp

Decisions are saved to review_state.json in the run folder on every click, so a
review can be stopped and resumed, or split between reviewers. Export writes only
approved or edited answers into a copy of the customer's file.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.review_state import CHOICES, ReviewError, Run  # noqa: E402
from tools.export_response import export  # noqa: E402

RESULTS_DIR = ROOT / "evals" / "results"
STATUS_LABEL = {
    "answered": ("Answered", "green"), "insufficient_evidence": ("Insufficient evidence", "orange"),
    "conflict": ("Conflict", "red"), "escalated": ("Escalated", "violet"),
    "needs_clarification": ("Needs clarification", "blue"),
}
DECISION_LABEL = {"approved": "✅ Approved", "edited": "✏️ Edited (human-written)", "rejected": "⛔ Rejected",
                  "pending": "⏳ Pending"}


def _cli_run_dir() -> str | None:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--run")
    known, _ = ap.parse_known_args(sys.argv[1:])
    return known.run or os.environ.get("RFP_RUN_DIR")


def _run_folders() -> list[Path]:
    if not RESULTS_DIR.exists():
        return []
    return sorted((p for p in RESULTS_DIR.iterdir() if (p / "results.jsonl").exists()),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def _badge(status: str) -> str:
    label, color = STATUS_LABEL.get(status, (status, "gray"))
    return f":{color}-background[{label}]"


def _sources(r: dict) -> None:
    if r.get("conflict"):
        st.markdown("**Documents disagree:**")
        for s in r["conflict"]["sources"]:
            st.markdown(f"- {s['doc_title']} ({s['doc']}, p.{s['page']}): *{s['value']}*")
    elif r.get("citations"):
        with st.expander(f"Sources ({len(r['citations'])})", expanded=False):
            for c in r["citations"]:
                st.markdown(f"- **{c['doc_title']}** ({c['doc']}, p.{c['page']})  \n  > {c['quote']}")
    if r.get("related_excerpts"):
        with st.expander("Related excerpts (for the reviewer, not an answer)"):
            for c in r["related_excerpts"]:
                st.markdown(f"- {c['doc']} p.{c['page']}: {c['quote']}")


def question_card(run: Run, r: dict, reviewer: str) -> None:
    ref, status = r["ref"], r["status"]
    decision = run.decisions.get(ref)
    loc = (r.get("trace") or {}).get("location") or {}
    with st.container(border=True):
        top = st.columns([6, 2])
        top[0].markdown(f"**{ref}** · {_badge(status)}  \n{r['question']}")
        top[1].markdown(DECISION_LABEL[run.status_of(ref)])

        if r.get("clarification_options"):
            st.markdown("**Ask the customer which they mean:** " + "; ".join(r["clarification_options"]))
        if r.get("route_to"):
            st.caption(f"Route to **{r['route_to'].replace('_', ' ')}**: {r.get('route_reason', '')}")
        for issue in (r.get("trace") or {}).get("consistency", []):
            st.warning(issue["detail"], icon="⚠️")
        _sources(r)

        default_text = decision.final_answer if decision and decision.final_answer else (
            r.get("answer", "") if status == "answered" else "")
        text = st.text_area("Answer to send (drafted by the agent; edit to change)" if status == "answered"
                            else "Answer to send (write it yourself if one should be given)",
                            value=default_text, key=f"text_{ref}", height=90,
                            help="Edit to write the answer in your own words. Saved as human-written.")
        choice = ""
        if loc.get("choice_col"):
            current = decision.choice if decision else ""
            choice = st.selectbox("Yes / No / N/A column", CHOICES, index=CHOICES.index(current),
                                  key=f"choice_{ref}")
        cols = st.columns(4)
        try:
            if cols[0].button("Approve as drafted", key=f"approve_{ref}", disabled=status != "answered",
                              help="Only answered questions can be approved unchanged."):
                run.decide(ref, "approved", choice=choice, reviewer=reviewer)
                run.save()
                st.rerun()
            if cols[1].button("Save my wording", key=f"edit_{ref}"):
                run.decide(ref, "edited", final_answer=text, choice=choice, reviewer=reviewer)
                run.save()
                st.rerun()
            if cols[2].button("Reject", key=f"reject_{ref}"):
                run.decide(ref, "rejected", reviewer=reviewer)
                run.save()
                st.rerun()
            if decision and cols[3].button("Reset", key=f"reset_{ref}"):
                run.clear(ref)
                run.save()
                st.rerun()
        except ReviewError as e:
            st.error(str(e))


def main() -> None:
    st.set_page_config(page_title="RFP Review", layout="wide")
    st.title("RFP Response Review")

    folders = _run_folders()
    preset = _cli_run_dir()
    with st.sidebar:
        st.header("Run")
        options = [str(p) for p in folders]
        if preset and preset not in options:
            options.insert(0, preset)
        if not options:
            st.info("No runs yet. Create one with `python -m agents.run_questionnaire <file>`.")
            return
        run_dir = st.selectbox("Results folder", options, index=0,
                               format_func=lambda p: Path(p).name)
        reviewer = st.text_input("Reviewer name", key="reviewer")

    run = Run.load(run_dir)
    prog = run.progress()
    agent_counts = {s: sum(1 for r in run.results if r["status"] == s) for s in STATUS_LABEL}

    with st.sidebar:
        st.header("Filter")
        show_status = st.multiselect("Agent status", list(STATUS_LABEL), default=list(STATUS_LABEL),
                                     format_func=lambda s: f"{STATUS_LABEL[s][0]} ({agent_counts[s]})")
        show_decision = st.multiselect("Review decision", list(DECISION_LABEL), default=["pending"],
                                       format_func=lambda s: DECISION_LABEL[s])
        query = st.text_input("Search questions")
        order = st.radio("Order", ["Needs attention first", "Questionnaire order"], horizontal=False)

        st.header("Export")
        src = run.source
        src_text = st.text_input("Original customer file", value=str(src) if src else "",
                                 help="Answers are written into a copy of this file; the original is never changed.")
        if st.button("Export approved answers", type="primary", disabled=not src_text):
            try:
                dest, n = export(run.folder, source=src_text)
                st.success(f"Wrote {n} answers to {dest.name}")
                st.download_button("Download filled file", dest.read_bytes(), file_name=dest.name)
            except (ReviewError, OSError) as e:
                st.error(str(e))

    m = st.columns(4)
    m[0].metric("Questions", len(run.results))
    m[1].metric("Approved / edited", prog["approved"] + prog["edited"])
    m[2].metric("Rejected", prog["rejected"])
    m[3].metric("Pending review", prog["pending"])

    issues = {tuple(i["refs"]): i for r in run.results for i in (r.get("trace") or {}).get("consistency", [])}
    if issues:
        with st.expander(f"⚠️ Consistency issues across answers ({len(issues)})", expanded=True):
            for i in issues.values():
                st.markdown(f"- **{' vs '.join(i['refs'])}**: {i['detail']}")

    shown = [r for r in run.results
             if r["status"] in show_status and run.status_of(r["ref"]) in show_decision
             and (not query or query.lower() in r["question"].lower() or query.lower() in r["ref"].lower())]
    if order == "Needs attention first":
        rank = {"conflict": 0, "escalated": 1, "insufficient_evidence": 2, "needs_clarification": 3, "answered": 4}
        shown.sort(key=lambda r: (not (r.get("trace") or {}).get("consistency"), rank.get(r["status"], 9)))
    st.caption(f"Showing {len(shown)} of {len(run.results)} questions")
    for r in shown:
        question_card(run, r, reviewer)


main()
