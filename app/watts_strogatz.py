"""Watts-Strogatz small-world example shown in the lab.

The figures come from one draw of the interactive small-world lab (web/small-world.html):
N=500, K=25, p=0.15, seed 1. They are stored, not recomputed at serve time, so a clone sees
the same numbers without NetworkX, MATLAB or a key.

The lesson: in a small-world graph, hop count does not bound context. Two hops from one node
reach 75% of this graph. An agent that expands k hops from a match floods its context long
before k is interesting, so retrieval has to stop on a token budget or a ranking. These figures
are a synthetic example, not a measurement of the catalogue graph.

Citations:
- D. J. Watts and S. H. Strogatz, Collective dynamics of small-world networks,
  Nature 393, 440–442 (1998), doi:10.1038/30918
- MathWorks, Build Watts-Strogatz Small World Graph Model
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
    "title": "Build Watts-Strogatz Small World Graph Model",
    "publisher": "MathWorks",
    "url": "https://www.mathworks.com/help/matlab/math/build-watts-strogatz-small-world-graph-model.html",
}

# Assumptions for the token figure, stated rather than hidden in a constant.
TOKENS_PER_NODE = 60        # a short node description: name, type and a few properties
CONTEXT_BUDGET = 32_000     # tokens available for retrieved context

# One draw from the lab. Seed 1, 1,912 rewires. Replace all of it together, not piecemeal.
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
    "tokens_per_node": TOKENS_PER_NODE,
    "context_budget": CONTEXT_BUDGET,
    "two_hop_tokens": 373 * TOKENS_PER_NODE,
    "two_hop_budget_pct": round(373 * TOKENS_PER_NODE / CONTEXT_BUDGET, 2),
    "networkx": {"n": 500, "k": 50, "p": 0.15, "note": "NetworkX uses k=2K"},
    "mathworks_check": [
        {"beta": 0.0, "matlab": 5.48, "visual": 5.48},
        {"beta": 0.15, "matlab": 2.0715, "visual": 2.0617},
        {"beta": 0.5, "matlab": 1.9101, "visual": 1.9091},
        {"beta": 1.0, "matlab": 1.9008, "visual": None},
    ],
}

CLAIM = (
    "In a small-world graph, hop count does not bound context: two hops from one node reach 75% "
    "of this 500-node graph. Retrieval has to stop on a token budget or a ranking. These figures "
    "are a synthetic example, not a measurement of the catalogue graph."
)


def example() -> dict[str, Any]:
    """Cited visual plus the claim and sources. Safe to bake into the page."""
    return {
        "claim": CLAIM,
        "example": EXAMPLE,
        "citations": [NATURE, MATHWORKS],
        "why_here": (
            "The discovery pipeline does not expand by hops at all: the graph proposes candidates and "
            "typed decisions keep the relevant ones, which is a ranking. The compliance store can use a "
            "two-hop neighbourhood only because its schema is a small star around each pattern (its "
            "attempts, their decisions and the agent), not because two hops are small in general."
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
    """Nodes within d hops, for d = 1..hops (cumulative). The start node is not counted."""
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
