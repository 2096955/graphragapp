"""The typed questions the pipeline asks. The benchmark asks exactly these, so its numbers
describe the pipeline's own decisions.

Stage     Task          Type    Question
build     entity        noul    Do these two names refer to the same thing?
build     mapping       choice  Which catalogue property does this source column hold?
query     gate          choice  Answer, ask for clarification, or reject?
query     relevance     noul    Does the request ask for this pollutant (or group)?
query     level         choice  Which breakdown does the request ask for, per dimension?
rank      fit           score   How well does this solution match the user's preference?
"""
from __future__ import annotations

from . import domain as d

GATE = {
    "type": "choice",
    "instructions": "Can the data catalogue answer this request as written?",
    "criteria": {
        "answer": ("It names at least one pollutant, or asks for pollution, emissions or data in general, and at least "
                   "one breakdown the catalogue holds: region, country or continent; month or year from 2015 to 2025; "
                   "subsector or macrosector. A named place, period or sector counts as a breakdown."),
        "clarify": ("It is about air pollution data but names no pollutant and no general term such as pollution or "
                    "emissions, or it gives no breakdown at all."),
        "reject": ("It is off-topic, or it needs something the catalogue does not hold: cities, streets, stations, days, "
                   "hours, weeks, years outside 2015 to 2025, forecasts, pollutants such as ozone, or other kinds of "
                   "pollution such as water or noise."),
    },
}

RELEVANCE_TRUE = ("The request names this pollutant, or a group it belongs to (greenhouse gases, particulate matter, "
                  "heavy metals), or asks for pollution, emissions or data in general without naming any pollutant.")
RELEVANCE_FALSE = "The request names other pollutants but not this one, and not a group it belongs to."


def relevance_question(candidate: str) -> dict:
    return {"type": "noul", "instructions": f"Does the request ask for data on {candidate}?",
            "criteria": {"true": RELEVANCE_TRUE, "false": RELEVANCE_FALSE}}


def group_question(group: str) -> dict:
    """Whole-group selection. The criteria must agree with LABELLING.md section 6: a general request
    ("air emissions", "data by region") selects every pollutant; a named group selects only itself."""
    if group == "all":
        return {"type": "noul", "instructions": "Does the request ask for all pollutants?",
                "criteria": {"true": ("It asks for pollution, emissions or data in general and names no specific "
                                      "pollutant or pollutant group, or it asks for all pollutants."),
                             "false": "It names at least one specific pollutant or pollutant group."}}
    name = d.GROUPS[group]["label"].lower()
    return {"type": "noul", "instructions": f"Does the request ask for {d.GROUPS[group]['describe']}?",
            "criteria": {"true": f"It names {name} as a group, not only some of its members.",
                         "false": ("It names only specific pollutants, another group, or asks for pollution, "
                                   "emissions or data in general.")}}


LEVEL = {
    "GEO": {
        "type": "choice",
        "instructions": "Which geographic breakdown does the request ask for?",
        "criteria": {
            "region": "Sub-national regions, or a named region such as Lombardy or Bavaria.",
            "country": "Countries, or a named country. Also the default when geography is mentioned without a level.",
            "continent": "Continents as the unit of analysis.",
            "none": "No geographic breakdown is mentioned.",
        },
    },
    "TIME": {
        "type": "choice",
        "instructions": "Which time breakdown does the request ask for?",
        "criteria": {
            "month": "Monthly figures.",
            "year": "Yearly figures, or a named year or range of years. Also the default when time is mentioned without a level.",
            "none": "No time breakdown is mentioned.",
        },
    },
    "SECTOR": {
        "type": "choice",
        "instructions": "Which sector breakdown does the request ask for?",
        "criteria": {
            "subsector": "Specific activities such as road transport, aviation, shipping, cement or livestock.",
            "macrosector": ("Broad sectors such as agriculture, power or transportation. Also the default for 'sector' "
                            "or 'industry' without a level."),
            "none": "No sector breakdown is mentioned.",
        },
    },
}

ENTITY = {
    "type": "noul",
    "instructions": "Do the two names refer to the same real-world thing?",
    "criteria": {
        "true": "The same thing under another name, spelling, language, abbreviation or code.",
        "false": "Different things, even if the names look alike, or one is only part of the other.",
    },
}

FIT = {
    "type": "score",
    "instructions": "How well does this dataset solution match the user's preference?",
    "criteria": ["It does not match the preference.", "It partly matches the preference.",
                 "It mostly matches the preference.", "It fully matches the preference."],
}

# Mapping targets: every pollutant, every level, and "none".
TARGETS: dict[str, tuple[str, str]] = {}
for _p in d.POLLUTANTS:
    TARGETS[f"pollutant:{_p.id}"] = (_p.label, _p.name)
_LEVEL_TEXT = {
    "GEO.region": ("region", "sub-national region names or codes"),
    "GEO.country": ("country", "country names or country codes"),
    "GEO.continent": ("continent", "continent names"),
    "TIME.month": ("month", "calendar months or month start dates"),
    "TIME.year": ("year", "calendar years"),
    "SECTOR.subsector": ("subsector", "specific activities or detailed sector codes"),
    "SECTOR.macrosector": ("macrosector", "broad economic sectors"),
}
for _k, _v in _LEVEL_TEXT.items():
    TARGETS[f"level:{_k}"] = _v
NONE_OPTION = ("none of these", "Something else, such as an identifier, a coordinate, a population or a count.")


def gate(request: str) -> tuple[dict, dict]:
    return {"request": request, "catalogue": d.CATALOGUE_SUMMARY}, {"gate": GATE}


def relevance(request: str, candidate: str) -> tuple[dict, dict]:
    return {"request": request}, {"relevant": relevance_question(candidate)}


def relevance_many(request: str, candidates: dict[str, str]) -> tuple[dict, dict]:
    """All candidates in one call: the state is shared, one question per candidate."""
    return {"request": request}, {name: group_question(name.split(":")[1]) if name.startswith("group:") else relevance_question(text)
                                 for name, text in candidates.items()}


def levels(request: str) -> tuple[dict, dict]:
    return {"request": request}, {dim: LEVEL[dim] for dim in d.DIMENSIONS}


def entity(kind: str, a: str, b: str) -> tuple[dict, dict]:
    return {"kind": kind, "name A": a, "name B": b}, {"same": ENTITY}


def mapping(source_id: str, column: str, samples: list[str], targets: list[str]) -> tuple[dict, dict]:
    """targets: mapping keys (e.g. 'pollutant:PM2_5'), shown in this order, 'none' added last."""
    s = d.SOURCE[source_id]
    crit = {}
    for t in targets:
        lab, desc = TARGETS[t]
        crit[lab] = desc
    crit[NONE_OPTION[0]] = NONE_OPTION[1]
    q = {"type": "choice", "instructions": "Which catalogue property does this column hold?", "criteria": crit}
    return {"source": f"{s.name}: {s.description}", "column": column, "sample values": samples}, {"maps_to": q}


def target_label(target: str | None) -> str:
    return NONE_OPTION[0] if target is None else TARGETS[target][0]


def fit(preference: str, summary: str, solution: dict | None = None) -> tuple[dict, dict]:
    state = {"preference": preference, "summary": summary}
    if solution is not None:
        state["solution"] = {k: solution[k] for k in ("sources", "profiles", "cells")}
    return state, {"fit": FIT}
