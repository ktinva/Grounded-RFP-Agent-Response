"""Draw architecture/architecture-diagram.png from the implemented pipeline.

Run:  python -m tools.draw_architecture
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "architecture" / "architecture-diagram.png"

INK, MUTED, LINE = "#1d2733", "#5b6573", "#8a94a3"
FILL = {"input": "#eef2f7", "step": "#ffffff", "gate": "#fff4e5", "out": "#eaf5ee", "eval": "#f3eefa"}
EDGE = {"input": "#9aa8b8", "step": "#3d5a80", "gate": "#c77d1a", "out": "#3c8d5a", "eval": "#7a5cb0"}


def box(ax, x, y, w, h, title, sub="", kind="step"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc=FILL[kind], ec=EDGE[kind], lw=1.4))
    ax.text(x + w / 2, y + h / 2 + (0.16 if sub else 0), title, ha="center", va="center",
            fontsize=10.5, fontweight="bold", color=INK)
    if sub:
        ax.text(x + w / 2, y + h / 2 - 0.2, sub, ha="center", va="center", fontsize=8.3, color=MUTED)


def arrow(ax, a, b, color=LINE, style="-|>", ls="-"):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle=style, mutation_scale=12, color=color, lw=1.3, linestyle=ls))


def main() -> Path:
    fig, ax = plt.subplots(figsize=(15, 9.2), dpi=150)
    ax.set_xlim(0, 15)
    ax.set_ylim(0, 9.2)
    ax.axis("off")
    ax.text(0.3, 8.85, "Grounded RFP Response Agent", fontsize=16, fontweight="bold", color=INK)
    ax.text(0.3, 8.5, "Every question ends in exactly one status. Nothing is answered without a verified, "
                      "cited quote from an approved document.", fontsize=9.5, color=MUTED)

    # inputs
    box(ax, 0.3, 6.6, 3.0, 1.1, "Company documents", "PDF + manifest (owner, version, status)", "input")
    box(ax, 0.3, 5.0, 3.0, 1.1, "Ingestion", "approved only · page-exact chunks", "gate")
    box(ax, 0.3, 3.4, 3.0, 1.1, "Hybrid search index", "BM25 + char n-gram TF-IDF (RRF)", "step")
    box(ax, 0.3, 1.6, 3.0, 1.1, "Customer file", ".xlsx questionnaire / .docx RFP", "input")
    arrow(ax, (1.8, 6.6), (1.8, 6.1))
    arrow(ax, (1.8, 5.0), (1.8, 4.5))
    ax.text(3.4, 5.25, "draft docs\nnever indexed", fontsize=8, color=EDGE["gate"], va="center")

    # pipeline
    steps = [
        ("1  Policy rules", "hard escalation list · missing attachment", "gate"),
        ("2  Classifier", "topic · sensitive · ambiguous · search queries", "step"),
        ("3  Retriever", "top-8 approved chunks", "step"),
        ("4  Drafter", "answer / insufficient / conflict / clarify", "step"),
        ("5  Verifier", "independent check · quote must match source", "gate"),
        ("6  Router", "owner team from topic or rule", "step"),
    ]
    x0, w, h, gap = 4.9, 3.6, 0.72, 0.22
    ax.add_patch(FancyBboxPatch((x0, 7.72), w, 0.36, boxstyle="round,pad=0.02,rounding_size=0.1",
                                fc=FILL["input"], ec=EDGE["input"], lw=1.2))
    ax.text(x0 + w / 2, 7.9, "Parser: finds questions in any layout", fontsize=8.8, ha="center", va="center", color=INK)
    tops, y = [], 7.4
    for t, s_, k in steps:
        box(ax, x0, y - h, w, h, t, s_, k)
        tops.append(y)
        y -= h + gap
    arrow(ax, (x0 + w / 2, 7.72), (x0 + w / 2, tops[0]))
    for a, b in zip(tops[:-1], tops[1:]):
        arrow(ax, (x0 + w / 2, a - h), (x0 + w / 2, b))
    arrow(ax, (3.3, 2.15), (x0, 7.9))
    arrow(ax, (3.3, 3.95), (x0, tops[2] - h / 2))

    # outputs, joined by one connector bar
    outs = [("Answered (cited)", "doc + page + verbatim quote"),
            ("Insufficient evidence", "says what is missing · suggests owner"),
            ("Conflict", "both documents and both values"),
            ("Escalated", "legal · security · product · SE"),
            ("Needs clarification", "readings offered back to the buyer")]
    ox, ow, oh, og = 10.2, 3.2, 0.72, 0.2
    centers, oy = [], 7.4
    for t, s_ in outs:
        box(ax, ox, oy - oh, ow, oh, t, s_, "out")
        centers.append(oy - oh / 2)
        oy -= oh + og
    bus = 9.55
    ax.plot([bus, bus], [min(centers[-1], tops[-1] - h / 2), centers[0]], color=EDGE["out"], lw=1.3)
    for c in centers:
        arrow(ax, (bus, c), (ox, c), color=EDGE["out"])
    ax.plot([x0 + w, bus], [tops[-1] - h / 2, tops[-1] - h / 2], color=EDGE["out"], lw=1.3)
    esc = centers[3]
    ax.plot([x0 + w, 9.25, 9.25], [tops[0] - h / 2, tops[0] - h / 2, esc + 0.12], color=EDGE["gate"], lw=1.2, ls="--")
    arrow(ax, (9.25, esc + 0.12), (ox, esc + 0.12), color=EDGE["gate"], ls="--")
    ax.text(8.62, tops[0] - h / 2 + 0.1, "rules escalate before\nany model call", fontsize=7.6, color=EDGE["gate"])

    box(ax, 13.75, centers[4] - 0.3, 1.1, centers[0] - centers[4] + 0.6, "Human\nreview", "", "input")
    arrow(ax, (ox + ow, (centers[0] + centers[4]) / 2), (13.75, (centers[0] + centers[4]) / 2))
    ax.text(13.3, centers[4] - 0.75, "every answer is approved\nbefore export", fontsize=7.6, color=MUTED)

    # eval loop
    ax.add_patch(FancyBboxPatch((4.6, 0.2), 10.25, 1.3, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc="none", ec=EDGE["eval"], lw=1.1, ls="--"))
    ax.text(4.8, 1.28, "Evaluation loop", fontsize=9.5, fontweight="bold", color=EDGE["eval"])
    box(ax, 4.8, 0.32, 2.5, 0.75, "Golden set", "83 questions, PDF-verified", "eval")
    box(ax, 7.5, 0.32, 2.3, 0.75, "Rewordings", "human-approved", "eval")
    box(ax, 10.0, 0.32, 2.2, 0.75, "Generator", "any buyer · 5 layouts", "eval")
    box(ax, 12.4, 0.32, 2.2, 0.75, "Scorecard", "release gates", "eval")
    arrow(ax, (7.3, 0.7), (7.5, 0.7), color=EDGE["eval"])
    arrow(ax, (9.8, 0.7), (10.0, 0.7), color=EDGE["eval"])
    ax.plot([11.1, 11.1, 3.6], [1.07, 1.75, 1.75], color=EDGE["eval"], lw=1.2, ls="--")
    arrow(ax, (3.6, 1.75), (3.3, 1.9), color=EDGE["eval"], ls="--")
    ax.text(5.0, 1.82, "generated questionnaire (answer key kept hidden from the agent)", fontsize=7.8, color=EDGE["eval"])
    ax.text(12.45, 1.2, "run_evals scores agent output", fontsize=7.4, color=EDGE["eval"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, bbox_inches="tight", facecolor="white")
    return OUT


if __name__ == "__main__":
    print("wrote", main())
