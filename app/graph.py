"""The two-layer knowledge graph in Kuzu, and the discovery queries that run on it.

Kuzu is embedded, so the graph needs no server. Upstream Kuzu is archived at 0.11.3; for a
graph you keep, move to a maintained fork or swap this module for another engine. Nothing
outside this module talks to the database.
"""
from __future__ import annotations

import itertools
import shutil
import tempfile
import threading
from pathlib import Path

import kuzu

from . import domain as d

SCHEMA = [
    "CREATE NODE TABLE Pollutant(id STRING PRIMARY KEY, label STRING, name STRING, unit STRING)",
    "CREATE NODE TABLE PollutantGroup(id STRING PRIMARY KEY, label STRING, describe STRING)",
    "CREATE NODE TABLE Level(id STRING PRIMARY KEY, dim STRING, name STRING, rank INT64)",
    "CREATE NODE TABLE Member(id STRING PRIMARY KEY, dim STRING, level STRING, name STRING)",
    "CREATE NODE TABLE Source(id STRING PRIMARY KEY, name STRING, description STRING, publisher STRING, updated INT64)",
    "CREATE NODE TABLE SourceColumn(id STRING PRIMARY KEY, name STRING, samples STRING)",
    "CREATE REL TABLE IN_GROUP(FROM Pollutant TO PollutantGroup)",
    "CREATE REL TABLE ROLLS_UP_TO(FROM Level TO Level)",
    "CREATE REL TABLE IN_LEVEL(FROM Member TO Level)",
    "CREATE REL TABLE PARENT(FROM Member TO Member)",
    "CREATE REL TABLE PROVIDES(FROM Source TO Pollutant)",
    "CREATE REL TABLE AT_LEVEL(FROM Source TO Level)",
    "CREATE REL TABLE COVERS(FROM Source TO Member, rows INT64)",
    "CREATE REL TABLE HAS_COLUMN(FROM Source TO SourceColumn)",
    "CREATE REL TABLE MAPS_TO_POLLUTANT(FROM SourceColumn TO Pollutant)",
    "CREATE REL TABLE MAPS_TO_LEVEL(FROM SourceColumn TO Level)",
]


def build(path: str | Path) -> None:
    path = Path(path)
    if path.exists():
        shutil.rmtree(path) if path.is_dir() else path.unlink()
    db = kuzu.Database(str(path))
    c = kuzu.Connection(db)
    for ddl in SCHEMA:
        c.execute(ddl)

    for g, meta in d.GROUPS.items():
        c.execute("CREATE (:PollutantGroup {id: $id, label: $l, describe: $d})", {"id": g, "l": meta["label"], "d": meta["describe"]})
    for p in d.POLLUTANTS:
        c.execute("CREATE (:Pollutant {id: $id, label: $l, name: $n, unit: $u})", {"id": p.id, "l": p.label, "n": p.name, "u": p.unit})
        for g in ("all",) + p.groups:
            c.execute("MATCH (p:Pollutant {id: $p}), (g:PollutantGroup {id: $g}) CREATE (p)-[:IN_GROUP]->(g)", {"p": p.id, "g": g})

    for dim, levels in d.DIMENSIONS.items():
        for rank, lvl in enumerate(levels):
            c.execute("CREATE (:Level {id: $id, dim: $dim, name: $n, rank: $r})", {"id": f"{dim}.{lvl}", "dim": dim, "n": lvl, "r": rank})
        for a, b in zip(levels, levels[1:]):
            c.execute("MATCH (a:Level {id: $a}), (b:Level {id: $b}) CREATE (a)-[:ROLLS_UP_TO]->(b)", {"a": f"{dim}.{a}", "b": f"{dim}.{b}"})
        for lvl in levels:
            for m in d.members(dim, lvl):
                mid = f"{dim}.{lvl}:{m}"
                c.execute("CREATE (:Member {id: $id, dim: $dim, level: $lvl, name: $n})", {"id": mid, "dim": dim, "lvl": lvl, "n": m})
                c.execute("MATCH (m:Member {id: $m}), (l:Level {id: $l}) CREATE (m)-[:IN_LEVEL]->(l)", {"m": mid, "l": f"{dim}.{lvl}"})
        for i, lvl in enumerate(levels[:-1]):
            for m in d.members(dim, lvl):
                up = d.parent(dim, lvl, m)
                if up is not None:
                    c.execute("MATCH (a:Member {id: $a}), (b:Member {id: $b}) CREATE (a)-[:PARENT]->(b)",
                              {"a": f"{dim}.{lvl}:{m}", "b": f"{dim}.{levels[i + 1]}:{up}"})

    for s in d.SOURCES:
        c.execute("CREATE (:Source {id: $id, name: $n, description: $ds, publisher: $pub, updated: $u})",
                  {"id": s.id, "n": s.name, "ds": s.description, "pub": s.publisher, "u": s.updated})
        for p in s.pollutants:
            c.execute("MATCH (s:Source {id: $s}), (p:Pollutant {id: $p}) CREATE (s)-[:PROVIDES]->(p)", {"s": s.id, "p": p})
        for dim, lvl in s.levels.items():
            c.execute("MATCH (s:Source {id: $s}), (l:Level {id: $l}) CREATE (s)-[:AT_LEVEL]->(l)", {"s": s.id, "l": f"{dim}.{lvl}"})
            for m, rows in s.rows[dim].items():
                c.execute("MATCH (s:Source {id: $s}), (m:Member {id: $m}) CREATE (s)-[:COVERS {rows: $r}]->(m)",
                          {"s": s.id, "m": f"{dim}.{lvl}:{m}", "r": rows})
        for col in s.columns:
            cid = f"{s.id}.{col.name}"
            c.execute("CREATE (:SourceColumn {id: $id, name: $n, samples: $sm})", {"id": cid, "n": col.name, "sm": ", ".join(col.samples)})
            c.execute("MATCH (s:Source {id: $s}), (k:SourceColumn {id: $k}) CREATE (s)-[:HAS_COLUMN]->(k)", {"s": s.id, "k": cid})
            if col.maps_to and col.maps_to.startswith("pollutant:"):
                c.execute("MATCH (k:SourceColumn {id: $k}), (p:Pollutant {id: $p}) CREATE (k)-[:MAPS_TO_POLLUTANT]->(p)",
                          {"k": cid, "p": col.maps_to.split(":")[1]})
            elif col.maps_to and col.maps_to.startswith("level:"):
                c.execute("MATCH (k:SourceColumn {id: $k}), (l:Level {id: $l}) CREATE (k)-[:MAPS_TO_LEVEL]->(l)",
                          {"k": cid, "l": col.maps_to.split(":")[1]})
    c.close()
    db.close()


class Graph:
    """Read-only access to the catalogue graph. Thread-safe through one lock."""

    def __init__(self, path: str | Path | None = None):
        if path is None:
            self._tmp = tempfile.mkdtemp(prefix="catalogue-")
            path = Path(self._tmp) / "catalogue.kuzu"
        self.path = Path(path)
        build(self.path)
        self._db = kuzu.Database(str(self.path), read_only=True)
        self._conn = kuzu.Connection(self._db)
        self._conn.set_query_timeout(5000)
        self._lock = threading.Lock()

    def q(self, cypher: str, params: dict | None = None) -> list[tuple]:
        with self._lock:
            res = self._conn.execute(cypher, params or {})
            rows = []
            while res.has_next():
                rows.append(tuple(res.get_next()))
            return rows

    # ---------------------------------------------------------------- lookups
    def expand_groups(self, groups: list[str]) -> list[str]:
        if not groups:
            return []
        rows = self.q("MATCH (p:Pollutant)-[:IN_GROUP]->(g:PollutantGroup) WHERE g.id IN $g RETURN DISTINCT p.id", {"g": groups})
        order = [p.id for p in d.POLLUTANTS]
        return sorted((r[0] for r in rows), key=order.index)

    def counts(self) -> dict:
        out = {}
        for label in ("Pollutant", "PollutantGroup", "Level", "Member", "Source", "SourceColumn"):
            out[label] = self.q(f"MATCH (n:{label}) RETURN count(n)")[0][0]
        out["edges"] = self.q("MATCH ()-[r]->() RETURN count(r)")[0][0]
        return out

    # ---------------------------------------------------------------- discovery
    def sources_for(self, pollutants: list[str], levels: dict[str, str], filters: dict | None = None) -> dict[str, set[str]]:
        """Sources that hold at least one requested pollutant at levels that roll up to the query's."""
        rows = self.q("MATCH (s:Source)-[:PROVIDES]->(p:Pollutant) WHERE p.id IN $p RETURN s.id, collect(p.id)", {"p": pollutants})
        provides = {sid: set(ps) for sid, ps in rows}
        if not levels:
            return provides
        ok = {}
        for sid, ps in provides.items():
            fine = True
            for dim, lvl in levels.items():
                # Same level, or a finer one that rolls up through ROLLS_UP_TO.
                same = self.q("MATCH (s:Source {id: $s})-[:AT_LEVEL]->(l:Level {id: $l}) RETURN count(l)", {"s": sid, "l": f"{dim}.{lvl}"})[0][0]
                finer = self.q("MATCH (s:Source {id: $s})-[:AT_LEVEL]->(:Level)-[:ROLLS_UP_TO*1..3]->(t:Level {id: $l}) RETURN count(t)",
                               {"s": sid, "l": f"{dim}.{lvl}"})[0][0]
                if not (same or finer):
                    fine = False
                    break
            if fine:
                for dim, constraint in (filters or {}).items():
                    native = d.SOURCE[sid].levels.get(dim)
                    if native is None or not d.level_rolls_up(dim, native, constraint["level"]):
                        fine = False
                        break
                    if not self.profile(sid, dim, levels.get(dim, constraint["level"]), constraint):
                        fine = False
                        break
            if fine:
                ok[sid] = ps
        return ok

    def profile(self, source_id: str, dim: str, level: str, constraint: dict | None = None) -> dict[str, int]:
        """Rows per member at the requested level, rolled up from the source's native level."""
        native = d.SOURCE[source_id].levels[dim]
        if constraint:
            if not d.level_rolls_up(dim, native, constraint["level"]):
                return {}
            rows = self.q("MATCH (s:Source {id: $s})-[c:COVERS]->(m:Member {dim: $dim}) RETURN m.name, c.rows",
                          {"s": source_id, "dim": dim})
            filtered = {}
            for member, count in rows:
                if d.roll_up(dim, native, member, constraint["level"]) in constraint["members"]:
                    target = d.roll_up(dim, native, member, level)
                    if target is not None:
                        filtered[target] = filtered.get(target, 0) + int(count)
            return filtered
        if native == level:
            rows = self.q("MATCH (s:Source {id: $s})-[c:COVERS]->(m:Member {dim: $dim}) RETURN m.name, c.rows", {"s": source_id, "dim": dim})
        else:
            rows = self.q(
                "MATCH (s:Source {id: $s})-[c:COVERS]->(m:Member {dim: $dim})-[:PARENT*1..3]->(t:Member {level: $lvl}) "
                "RETURN t.name, sum(c.rows)", {"s": source_id, "dim": dim, "lvl": level})
        return {name: int(n) for name, n in rows}

    def discover(self, pollutants: list[str], levels: dict[str, str], max_sources: int = 3, max_solutions: int = 8,
                 filters: dict | None = None) -> list[dict]:
        """Minimal sets of sources that together hold every requested pollutant (Algorithm 2)."""
        candidates = self.sources_for(pollutants, levels, filters)
        need = set(pollutants)
        solutions: list[tuple[str, ...]] = []
        for k in range(1, max_sources + 1):
            for combo in itertools.combinations(sorted(candidates), k):
                covered = set().union(*(candidates[s] for s in combo))
                if not need <= covered:
                    continue
                if any(set(prev) <= set(combo) for prev in solutions):
                    continue  # not minimal
                solutions.append(combo)
        out = []
        for combo in solutions:
            sol = self._solution(combo, pollutants, levels, candidates, filters)
            if sol["cells"] <= 0:
                continue
            complete = True
            for dim, constraint in (filters or {}).items():
                profiles = [self.profile(s, dim, constraint["level"], constraint) for s in combo]
                shared = set(profiles[0]).intersection(*profiles[1:])
                if not set(constraint["members"]) <= shared:
                    complete = False
                    break
            if not complete:
                continue
            out.append(sol)
            if len(out) >= max_solutions:
                break
        return out

    def _solution(self, combo: tuple[str, ...], pollutants: list[str], levels: dict[str, str], candidates: dict,
                  filters: dict | None = None) -> dict:
        profiles = {}
        for dim, lvl in levels.items():
            per_source = [self.profile(s, dim, lvl, (filters or {}).get(dim)) for s in combo]
            shared = set(per_source[0]).intersection(*per_source[1:]) if per_source else set()
            order = d.members(dim, lvl)
            # Histogram intersection (Definition 7): the join can hold at most the smallest count.
            profiles[f"{dim}.{lvl}"] = {m: min(p[m] for p in per_source) for m in sorted(shared, key=order.index)}
        cells = 1
        for prof in profiles.values():
            cells *= len(prof)
        notes = []
        for s in combo:
            src = d.SOURCE[s]
            for dim in src.levels:
                if dim not in levels:
                    held = src.coverage[dim]
                    total = d.members(dim, src.levels[dim])
                    if len(held) < len(total):
                        what = (" and ".join(held) if len(held) <= 2 else
                                f"{len(held)} of {len(total)} {d.plural(src.levels[dim], len(total)).split(' ', 1)[1]}")
                        notes.append(f"{src.name} is summed over {dim.lower()} but covers only {what}")
        return {
            "sources": [{"id": s, "name": d.SOURCE[s].name, "publisher": d.SOURCE[s].publisher,
                         "updated": d.SOURCE[s].updated, "provides": sorted(candidates[s] & set(pollutants))} for s in combo],
            "profiles": profiles,
            "cells": cells if levels else 0,
            "notes": notes,
        }

    # ---------------------------------------------------------------- for the page
    def subgraph(self, pollutants: list[str], levels: dict[str, str], source_ids: list[str]) -> dict:
        """Nodes and edges the page draws for one query."""
        nodes, edges = [], []
        for p in d.POLLUTANTS:
            if p.id in pollutants:
                nodes.append({"id": f"P:{p.id}", "kind": "pollutant", "label": p.label})
        for dim, lvls in d.DIMENSIONS.items():
            for lvl in lvls:
                nodes.append({"id": f"L:{dim}.{lvl}", "kind": "level", "label": lvl, "dim": dim,
                              "selected": levels.get(dim) == lvl})
            for a, b in zip(lvls, lvls[1:]):
                edges.append({"from": f"L:{dim}.{a}", "to": f"L:{dim}.{b}", "kind": "rolls_up"})
        for sid in source_ids:
            s = d.SOURCE[sid]
            nodes.append({"id": f"S:{sid}", "kind": "source", "label": s.name})
            for p in s.pollutants:
                if p in pollutants:
                    edges.append({"from": f"S:{sid}", "to": f"P:{p}", "kind": "provides"})
            for dim, lvl in s.levels.items():
                edges.append({"from": f"S:{sid}", "to": f"L:{dim}.{lvl}", "kind": "at_level"})
        return {"nodes": nodes, "edges": edges}
