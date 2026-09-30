"""Watts–Strogatz small-world example shown in the lab.

The on-screen figures are the visual from Anthony's notes (N=500, K=25, p=0.15,
seed 1). They are not recomputed at serve time, so a clone sees the same numbers
without NetworkX, MATLAB, or a key.

Claim: rewiring a locally clustered ring collapses average path length while
clustering stays high. Two hops therefore reach most of a real knowledge graph,
and retrieval should be bounded by tokens or rank, not by hop count.

Citations:
- D. J. Watts and S. H. Strogatz, Collective dynamics of small-world networks,
  Nature 393, 440–442 (1998), doi:10.1038/30918
- MathWorks, Build Watts–Strogatz Small World Graph Model
  https://www.mathworks.com/help/matlab/math/build-watts-strogatz-small-world-graph-model.html

NetworkX uses k=2K, so the equivalent call is watts_strogatz_graph(n=500, k=50, p=0.15).
"""
from __future__ import annotations

import random
from typing import Any

NATURE = {
    "authors": "D. J. Watts and S. H. Strogatz",
    "title": "Collective dynamics of small-world networks",
    "journal": "Nature",
    "volume": 393,
    "pages": "440–442",
    "year": 1998,
    "doi": "10.1038/30918",
    "url": "https://doi.org/10.1038/30918",
}

MATHWORKS = {
    "title": "Build Watts–Strogatz Small World Graph Model",
    "publisher": "MathWorks",
    "url": "https://www.mathworks.com/help/matlab/math/build-watts-strogatz-small-world-graph-model.html",
}

# Visual on screen. Seed 1, 1,912 rewires. Do not replace these with a fresh draw.
EXAMPLE: dict[str, Any] = {
    "n": 500,
    "k": 25,
    "p": 0.15,
    "seed": 1,
    "rewires": 1912,
    "average_path_length": 2.06,
    "average_path_length_exact": 2.0617,
    "clustering": 0.464,
    "from_node": 0,
    "hops": [
        {"hop": 1, "nodes": 47, "pct": 0.09},
        {"hop": 2, "nodes": 373, "pct": 0.75},
        {"hop": 3, "nodes": 499, "pct": 1.00},
    ],
    "two_hop_tokens": 22380,
    "two_hop_budget_pct": 0.70,
    "networkx": {"n": 500, "k": 50, "p": 0.15, "note": "NetworkX uses k=2K"},
    "mathworks_check": [
        {"beta": 0.0, "matlab": 5.48, "visual": 5.48},
        {"beta": 0.15, "matlab": 2.0715, "visual": 2.0617},
        {"beta": 0.5, "matlab": 1.9101, "visual": 1.9091},
        {"beta": 1.0, "matlab": 1.9008, "visual": None},
    ],
}

CLAIM = (
    "Rewiring a locally clustered ring collapses average path length while clustering "
    "stays high. Two hops reach most of a real knowledge graph, so retrieval should be "
    "bounded by tokens or rank, not by hop count."
)


def example() -> dict[str, Any]:
    """Cited visual plus the claim and sources. Safe to bake into the page."""
    return {
        "claim": CLAIM,
        "example": EXAMPLE,
        "citations": [NATURE, MATHWORKS],
        "why_here": (
            "The compliance graph only needs a short expansion from the matched pattern: "
            "prior attempts, the filter decision, and the downstream agent. That is the "
            "same two-hop neighbourhood this ring demonstrates."
        ),
    }


def generate(n: int = 80, k: int = 4, p: float = 0.15, seed: int = 1) -> list[set[int]]:
    """MathWorks ring: each node has K clockwise edges; each is rewired with probability p.

    Used in tests to show two hops cover most nodes. Not the on-screen N=500 visual.
    """
    rng = random.Random(seed)
    adj: list[set[int]] = [set() for _ in range(n)]
    for i in range(n):
        for d in range(1, k + 1):
            j = (i + d) % n
            adj[i].add(j)
            adj[j].add(i)
    for i in range(n):
        for d in range(1, k + 1):
            j = (i + d) % n
            if rng.random() >= p:
                continue
            candidates = [x for x in range(n) if x != i and x not in adj[i]]
            if not candidates:
                continue
            nxt = rng.choice(candidates)
            adj[i].discard(j)
            adj[j].discard(i)
            adj[i].add(nxt)
            adj[nxt].add(i)
    return adj


def hop_coverage(adj: list[set[int]], start: int = 0, hops: int = 2) -> dict[int, int]:
    """Nodes reached in exactly d hops, d=1..hops. start itself is excluded."""
    seen = {start}
    frontier = {start}
    out: dict[int, int] = {}
    for dist in range(1, hops + 1):
        nxt: set[int] = set()
        for nid in frontier:
            for other in adj[nid]:
                if other not in seen:
                    seen.add(other)
                    nxt.add(other)
        out[dist] = len(seen) - 1
        frontier = nxt
    return out
