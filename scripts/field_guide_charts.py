"""Draw the field guide's three charts for the README from the engine data in web/field-guide.html.

    python -m scripts.field_guide_charts

Writes docs/images/field-guide-grades.png, field-guide-criteria.png and field-guide-cost.png.
The engine table is read from the page, so the charts cannot drift from it. Needs matplotlib.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
# The field guide's own category colours (validated: lightness, chroma, colour-blind separation, contrast).
CAT = {"native": ("#3949ab", "Native graph store"), "over": ("#00897b", "Graph over existing data"),
       "doc": ("#b7791f", "Document store with graph features"), "embed": ("#8e3b8e", "Embedded")}
INK, MUTED, GRID, SURFACE = "#16202b", "#5a6878", "#e3e8ee", "#ffffff"
GRADE = {"A": 4, "A-": 3.7, "B+": 3.3, "B": 3, "B-": 2.7, "C+": 2.3, "C": 2, "C-": 1.7, "D": 1, "F": 0}


def engines() -> list[dict]:
    """Parse the `const E=[...]` table out of the field guide page."""
    text = (ROOT / "web" / "field-guide.html").read_text(encoding="utf-8")
    block = text[text.index("const E=["):]
    block = block[len("const E="):block.index("];") + 1]
    as_json = re.sub(r"([{,])(\w+):", r'\1"\2":', block)
    return json.loads(as_json)


def _style(ax) -> None:
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=INK, length=0)
    ax.set_facecolor(SURFACE)


def _legend(fig, cats) -> None:
    handles = [Patch(facecolor=CAT[c][0], label=CAT[c][1]) for c in CAT if c in cats]
    fig.legend(handles=handles, loc="lower center", ncol=len(handles), frameon=False, fontsize=10.5,
               labelcolor=INK, bbox_to_anchor=(0.5, 0.0))


def grades(E: list[dict]) -> None:
    shared = sorted([e for e in E if e.get("shared")], key=lambda e: (-GRADE[e["shared"]], E.index(e)))
    embed = sorted([e for e in E if e.get("embed")], key=lambda e: (-GRADE[e["embed"]], E.index(e)))
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.6), gridspec_kw={"width_ratios": [2.4, 1]}, facecolor=SURFACE)
    for ax, rows, key, title in ((axes[0], shared, "shared", "Shared production service"),
                                 (axes[1], embed, "embed", "Embedded, per session")):
        names = [e["n"] + (" (prov.)" if e.get("prov") and key == "shared" else "") for e in rows]
        vals = [GRADE[e[key]] for e in rows]
        ys = range(len(rows))[::-1]
        ax.barh(list(ys), vals, height=0.68, color=[CAT[e["cat"]][0] for e in rows], edgecolor=SURFACE, linewidth=2)
        for y, v, e in zip(ys, vals, rows):
            ax.text(v + 0.05, y, e[key], va="center", ha="left", fontsize=11, fontweight="bold", color=INK)
        ax.set_yticks(list(ys), names, fontsize=11)
        ax.set_xlim(0, 4.4)
        ax.set_xticks([0, 1, 2, 3, 4], ["F", "D", "C", "B", "A"], color=MUTED)
        ax.xaxis.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color=INK, pad=10)
        _style(ax)
    fig.suptitle("Graph engines for agent context: grades by job", x=0.01, ha="left", fontsize=15,
                 fontweight="bold", color=INK)
    _legend(fig, {e["cat"] for e in E})
    fig.tight_layout(rect=(0, 0.07, 1, 0.95))
    fig.savefig(OUT / "field-guide-grades.png", dpi=160, facecolor=SURFACE)
    plt.close(fig)


def criteria(E: list[dict]) -> None:
    cols = [("d", "Depth (30%)"), ("o", "Ops (25%)"), ("c", "Cost (20%)"), ("v", "Viability (15%)")]
    data = [[e[k] for k, _ in cols] for e in E]
    fig, ax = plt.subplots(figsize=(8.6, 0.56 * len(E) + 1.7), facecolor=SURFACE)
    ax.imshow(data, cmap="Blues", vmin=-0.5, vmax=5.5, aspect="auto")
    for i, row in enumerate(data):
        for j, v in enumerate(row):
            ax.text(j, i, str(v), ha="center", va="center", fontsize=12, fontweight="bold",
                    color=SURFACE if v >= 3 else INK)
    ax.set_xticks(range(len(cols)), [label for _, label in cols], fontsize=11, color=INK)
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(E)), [e["n"] for e in E], fontsize=11, color=INK)
    ax.tick_params(axis="y", length=0, pad=34)
    ax.tick_params(axis="x", length=0, pad=8)
    for i, e in enumerate(E):   # category marker beside each label; the label itself stays in ink
        ax.add_patch(plt.Rectangle((-0.5 - 0.12, i - 0.18), 0.07, 0.36, color=CAT[e["cat"]][0], clip_on=False,
                                   transform=ax.transData))
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_title("Scores by criterion, 0 to 5", loc="left", fontsize=13, fontweight="bold", color=INK, pad=30)
    handles = [Patch(facecolor=CAT[c][0], label=CAT[c][1]) for c in CAT]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.42, -0.02), ncol=2, frameon=False,
              fontsize=10, labelcolor=INK)
    fig.tight_layout()
    fig.savefig(OUT / "field-guide-criteria.png", dpi=160, facecolor=SURFACE)
    plt.close(fig)


def cost(E: list[dict]) -> None:
    rows = sorted(E, key=lambda e: -((e.get("hi") or e["cost"]) if e["cost"] is not None else -1))
    fig, ax = plt.subplots(figsize=(11, 0.55 * len(rows) + 1.9), facecolor=SURFACE)
    ys = list(range(len(rows)))[::-1]
    for y, e in zip(ys, rows):
        colour = CAT[e["cat"]][0]
        if e["cost"] is None:
            ax.text(40, y, e["note"], va="center", fontsize=10.5, color=MUTED, style="italic")
        elif e["cost"] == 0:
            ax.text(40, y, "\\$0 licence, your own compute", va="center", fontsize=10.5, color=MUTED)
        else:
            ax.barh(y, e["cost"], height=0.68, color=colour, edgecolor=SURFACE, linewidth=2)
            end = e["cost"]
            if e.get("hi"):
                ax.barh(y, e["hi"] - e["cost"], left=e["cost"], height=0.68, color=colour, alpha=0.35,
                        edgecolor=SURFACE, linewidth=2)
                end = e["hi"]
            label = f"\\${e['cost']:,} to \\${e['hi']:,}" if e.get("hi") else f"\\${e['cost']:,}"
            ax.text(end + 60, y, label, va="center", fontsize=11, color=INK)
    ax.set_yticks(ys, [e["n"] for e in rows], fontsize=11, color=INK)
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.set_xlim(0, 5600)
    ax.set_xlabel("Approximate entry production cost, USD a month", color=INK, fontsize=11)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title("Entry production cost (list prices, 25 September 2026; check before quoting)", loc="left",
                 fontsize=13, fontweight="bold", color=INK, pad=10)
    _style(ax)
    handles = [Patch(facecolor=CAT[c][0], label=CAT[c][1]) for c in CAT]
    ax.legend(handles=handles, loc="center right", frameon=False, fontsize=10, labelcolor=INK)
    fig.tight_layout()
    fig.savefig(OUT / "field-guide-cost.png", dpi=160, facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    E = engines()
    OUT.mkdir(parents=True, exist_ok=True)
    grades(E)
    criteria(E)
    cost(E)
    print("wrote", ", ".join(f"field-guide-{n}.png" for n in ("grades", "criteria", "cost")), "for", len(E), "engines")


if __name__ == "__main__":
    main()
