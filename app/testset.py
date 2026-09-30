"""The labelled test set: seven tasks, every label written by hand against LABELLING.md.

The 22 requests marked "paper" are the test requests of Table 1 in Diamantini et al. (2026),
as reproduced in Syntran-Labs/paper-rag-graph-4-datasets (MIT). Their labels follow the rules
in LABELLING.md, which agree with the paper's outcome for every case except 18 and 20: the
paper returned "Not sure" for both, and the rules here say "reject" because they need city-level
data the catalogue does not hold. Version 1.1 also clarifies P15 rather than ignoring its unheld
NO2 component; its relevance/level items remain independently labelable.
"""
from __future__ import annotations

import random

from . import domain as d
from . import tasks as t

ALL = "ALL"
GHG = ["CO2", "CO2e100", "CO2e20", "CH4", "N2O"]
PM = ["PM2_5", "PM10"]

# id, request, gate label, pollutants, GEO, TIME, SECTOR, relevance positives, relevance negatives
REQUESTS = [
    ("P01", "I want to analyse pollution (PM2.5 and CO2) by country and year", "answer", ["PM2_5", "CO2"], "country", "year", "none", ["PM2_5", "CO2"], ["PM10", "CO", "CO2e100"]),
    ("P02", "I want data sources which measure CH4 emissions by country, year and macro sectors", "answer", ["CH4"], "country", "year", "macrosector", ["CH4"], ["CO2", "N2O", "NMVOCs"]),
    ("P03", "Gather data about PM2.5 aggregated by region and subsector for all the years", "answer", ["PM2_5"], "region", "year", "subsector", ["PM2_5"], ["PM10", "BC", "OC"]),
    ("P04", "I would like to join data sources containing NH3 and CO2 pollutants where indicators are aggregated by country, year and subsectors", "answer", ["NH3", "CO2"], "country", "year", "subsector", ["NH3", "CO2"], ["N2O", "CO", "NOx"]),
    ("P05", "I wish to analyse CH4, CO and PM10 air pollution indicators measured by country and months, also with information about subsectors", "answer", ["CH4", "CO", "PM10"], "country", "month", "subsector", ["CH4", "CO", "PM10"], ["CO2", "PM2_5", "N2O"]),
    ("P06", "Collect data sources containing PM10 values for all the countries and years", "answer", ["PM10"], "country", "year", "none", ["PM10"], ["PM2_5", "SO2", "BC"]),
    ("P07", "Find all the datasets with regions, months and subsectors, and NOx values", "answer", ["NOx"], "region", "month", "subsector", ["NOx"], ["N2O", "SOx", "NH3"]),
    ("P08", "I want to analyse country data and the emissions of CO2", "answer", ["CO2"], "country", "none", "none", ["CO2"], ["CO", "CO2e100", "CH4"]),
    ("P09", "Gimme data aggregated by region and subsector for all the years", "answer", ALL, "region", "year", "subsector", ["PM10", "CH4", "PB"], []),
    ("P10", "Collect greenhouse gas emissions for country, year and subsector", "answer", GHG, "country", "year", "subsector", ["CO2e20", "N2O", "CH4"], ["PM2_5", "NOx", "SO2"]),
    ("P11", "Find datasets containing CO2 measured by geography and temporal dimensions", "answer", ["CO2"], "country", "year", "none", ["CO2"], ["CO", "CH4", "CO2e20"]),
    ("P12", "I want to aanlyse air pollution aggregated by region, month and sector", "answer", ALL, "region", "month", "macrosector", ["NOx", "SO2", "CO2"], []),
    ("P13", "Find data about PM10 and PM2.5 for sectors", "answer", ["PM10", "PM2_5"], "none", "none", "macrosector", ["PM10", "PM2_5"], ["BC", "OC", "NOx"]),
    ("P14", "Find particulate matter emissions in datasets with continents and years", "answer", PM, "continent", "year", "none", ["PM2_5", "PM10"], ["CO2", "NH3"]),
    ("P15", "I would like to obtain data about CO2, NOx and NO2 for each region, month and subsector", "answer", ["CO2", "NOx"], "region", "month", "subsector", ["CO2", "NOx"], ["N2O", "CO", "SO2"]),
    ("P16", "I want to analyse pollution", "clarify", None, None, None, None, [], []),
    ("P17", "Give me data about air emissions aggregated by industry", "answer", ALL, "none", "none", "macrosector", ["NOx", "PM10", "CO"], []),
    ("P18", "Gather data sources containing SO2, C4H and AS for cities and centuries", "reject", None, None, None, None, [], []),
    ("P19", "Give me results for SO2, Nox and N2O", "clarify", None, None, None, None, [], []),
    ("P20", "I want pollutant indicators for cities", "reject", None, None, None, None, [], []),
    ("P21", "Sector by year and country", "clarify", None, None, None, None, [], []),
    ("P22", "Year by year and sector", "clarify", None, None, None, None, [], []),
    ("A01", "Monthly NOx emissions by region for the last five years", "answer", ["NOx"], "region", "month", "none", ["NOx"], ["N2O", "SOx", "NH3"]),
    ("A02", "Compare methane emissions across continents by year", "answer", ["CH4"], "continent", "year", "none", ["CH4"], ["CO2", "NMVOCs", "N2O"]),
    ("A03", "Ammonia from agriculture by country and year", "answer", ["NH3"], "country", "year", "macrosector", ["NH3"], ["N2O", "CH4", "NOx"]),
    ("A04", "Black carbon and organic carbon for Asian countries, yearly", "answer", ["BC", "OC"], "country", "year", "none", ["BC", "OC"], ["CO2", "PM2_5", "CO"]),
    ("A05", "Show me SO2 by country and subsector", "answer", ["SO2"], "country", "none", "subsector", ["SO2"], ["SOx", "NOx", "CO"]),
    ("A06", "PM10 levels in Lombardy each month", "answer", ["PM10"], "region", "month", "none", ["PM10"], ["PM2_5", "NOx", "BC"]),
    ("A07", "Mercury and lead emissions for European countries per year", "answer", ["HG", "PB"], "country", "year", "none", ["HG", "PB"], ["NI", "CD", "ZN"]),
    ("A08", "Greenhouse gas emissions from road transport by country and month", "answer", GHG, "country", "month", "subsector", ["CO2", "CH4", "CO2e100"], ["NOx", "PM10", "NH3"]),
    ("A09", "carbon monoxide by contry and yeer", "answer", ["CO"], "country", "year", "none", ["CO"], ["CO2", "NOx", "NMVOCs"]),
    ("A10", "Annual CO2 for Australia", "answer", ["CO2"], "country", "year", "none", ["CO2"], ["CO", "CO2e100", "N2O"]),
    ("A11", "NMVOC emissions by macro-sector and year", "answer", ["NMVOCs"], "none", "year", "macrosector", ["NMVOCs"], ["CH4", "CO", "OC"]),
    ("A12", "Particulate matter by region", "answer", PM, "region", "none", "none", ["PM2_5", "PM10"], ["SO2", "CO2"]),
    ("A13", "How much nitrous oxide did each continent emit per year?", "answer", ["N2O"], "continent", "year", "none", ["N2O"], ["NOx", "NH3", "CH4"]),
    ("A14", "Sulphur oxides from shipping per country per month", "answer", ["SOx"], "country", "month", "subsector", ["SOx"], ["NOx", "CO2", "PM10"]),
    ("A15", "Monthly data by region", "answer", ALL, "region", "month", "none", ["SO2", "NH3", "PM2_5"], []),
    ("C01", "Emissions data please", "clarify", None, None, None, None, [], []),
    ("C02", "PM2.5", "clarify", None, None, None, None, [], []),
    ("C03", "Break it down by country and year", "clarify", None, None, None, None, [], []),
    ("C04", "What about methane?", "clarify", None, None, None, None, [], []),
    ("C05", "Emissions of NOx and SO2", "clarify", None, None, None, None, [], []),
    ("C06", "Ammonia figures", "clarify", None, None, None, None, [], []),
    ("C07", "Compare Italy and France", "clarify", None, None, None, None, [], []),
    ("C08", "I want the particulate matter numbers", "clarify", None, None, None, None, [], []),
    ("C09", "Can you pull the heavy metals data?", "clarify", None, None, None, None, [], []),
    ("C10", "I'd like the carbon monoxide data", "clarify", None, None, None, None, [], []),
    ("C11", "Give me everything you have", "clarify", None, None, None, None, [], []),
    ("C12", "By region and month, please", "clarify", None, None, None, None, [], []),
    ("R01", "Daily PM2.5 for Milan", "reject", None, None, None, None, [], []),
    ("R02", "Water pollution in the Po river by year", "reject", None, None, None, None, [], []),
    ("R03", "What will CO2 emissions be in 2040?", "reject", None, None, None, None, [], []),
    ("R04", "Hourly NOx readings by monitoring station", "reject", None, None, None, None, [], []),
    ("R05", "Noise levels near airports by country", "reject", None, None, None, None, [], []),
    ("R06", "Who won the 2022 World Cup?", "reject", None, None, None, None, [], []),
    ("R07", "Ozone concentrations by country and year", "reject", None, None, None, None, [], []),
    ("R08", "Emissions per street in Paris", "reject", None, None, None, None, [], []),
    ("R09", "Radon levels in homes by region", "reject", None, None, None, None, [], []),
    ("R10", "Write me a poem about clean air", "reject", None, None, None, None, [], []),
    ("R11", "Sulfur hexafluoride (SF6) by country and year", "reject", None, None, None, None, [], []),
    ("R12", "CO2 emissions in 1850 by country", "reject", None, None, None, None, [], []),
]

# kind, name A, name B, same?
ENTITIES = [
    ("countries", "United Kingdom", "UK", True), ("countries", "United States", "USA", True),
    ("countries", "Germany", "Deutschland", True), ("countries", "Italy", "Italia", True),
    ("countries", "Poland", "Polska", True), ("countries", "Spain", "España", True),
    ("countries", "Brazil", "Brasil", True), ("countries", "China", "People's Republic of China", True),
    ("countries", "Czechia", "Czech Republic", True), ("countries", "South Korea", "Korea, Rep.", True),
    ("countries", "North Macedonia", "Macedonia, FYR", True), ("countries", "Türkiye", "Turkey", True),
    ("countries", "Eswatini", "Swaziland", True), ("countries", "Myanmar", "Burma", True),
    ("countries", "Côte d'Ivoire", "Ivory Coast", True), ("countries", "Japan", "JPN", True),
    ("countries", "France", "FRA", True), ("countries", "Netherlands", "NLD", True),
    ("countries", "Austria", "Australia", False), ("countries", "Niger", "Nigeria", False),
    ("countries", "India", "Indonesia", False), ("countries", "Slovakia", "Slovenia", False),
    ("countries", "Iran", "Iraq", False), ("countries", "Sweden", "Switzerland", False),
    ("countries", "South Korea", "Korea, Dem. People's Rep.", False), ("countries", "Guinea", "Guinea-Bissau", False),
    ("countries", "Dominica", "Dominican Republic", False), ("countries", "Mali", "Malawi", False),
    ("countries", "Latvia", "Lithuania", False), ("country codes", "AUT", "AUS", False),
    ("regions", "Lombardy", "Lombardia", True), ("regions", "Bavaria", "Bayern", True),
    ("regions", "Andalusia", "Andalucía", True), ("regions", "Lazio", "Latium", True),
    ("regions", "Île-de-France", "Paris Region", True), ("places", "Veneto", "Venice", False),
    ("places", "Brandenburg", "Berlin", False), ("places", "Lombardy", "Milan", False),
    ("regions", "Lazio", "Lombardy", False), ("places", "Auvergne-Rhône-Alpes", "Rhône", False),
    ("pollutants", "PM2.5", "fine particulate matter", True), ("pollutants", "PM10", "PM2.5", False),
    ("pollutants", "CO", "CO2", False), ("pollutants", "CO", "carbon monoxide", True),
    ("pollutants", "NOx", "nitrogen oxides", True), ("pollutants", "NO2", "NOx", False),
    ("pollutants", "SO2", "sulphur dioxide", True), ("pollutants", "SOx", "sulphur oxides", True),
    ("pollutants", "SOx", "SO2", False), ("pollutants", "CH4", "methane", True),
    ("pollutants", "N2O", "nitrous oxide", True), ("pollutants", "N2O", "NO2", False),
    ("pollutants", "NH3", "ammonia", True), ("pollutants", "NMVOC", "non-methane volatile organic compounds", True),
    ("pollutants", "VOC", "NMVOC", False), ("pollutants", "BC", "black carbon", True),
    ("pollutants", "black carbon", "organic carbon", False), ("pollutants", "Hg", "mercury", True),
    ("pollutants", "Pb", "lead", True), ("pollutants", "Cd", "cadmium", True),
    ("pollutants", "As", "arsenic", True), ("pollutants", "Ni", "nickel", True),
    ("pollutants", "Zn", "zinc", True), ("pollutants", "CO2e (100-year GWP)", "CO2e (20-year GWP)", False),
    ("pollutants", "CO2", "CO2e (100-year GWP)", False), ("pollutants", "Se", "selenium", True),
    ("pollutants", "Cr", "chromium", True), ("pollutants", "Cu", "copper", True),
    ("sectors", "Road transport", "On-road vehicles", True), ("sectors", "Aviation", "Air transport", True),
    ("sectors", "Shipping", "Maritime transport", True), ("sectors", "Aviation", "Shipping", False),
    ("sectors", "Electricity generation", "Power generation", True), ("sectors", "Crop residue burning", "Crop burning", True),
    ("sectors", "Coal mining", "Coal mines", True), ("sectors", "Coal mining", "Oil and gas extraction", False),
    ("sectors", "Livestock", "Crop residue burning", False), ("sectors", "Cement", "Steel", False),
    ("sectors", "Landfill", "Solid waste disposal on land", True), ("sectors", "Residential heating", "Road transport", False),
    ("sectors", "Deforestation", "Landfill", False), ("sectors", "Manufacturing", "Transportation", False),
]

# Distractors for the mapping task: the likeliest confusions for each target.
_P = lambda *ids: [f"pollutant:{i}" for i in ids]  # noqa: E731
_L = lambda *ids: [f"level:{i}" for i in ids]  # noqa: E731
HARD = {
    "pollutant:PM2_5": _P("PM10", "BC", "OC", "NOx"), "pollutant:PM10": _P("PM2_5", "BC", "SO2", "NOx"),
    "pollutant:CO2": _P("CO", "CO2e100", "CH4", "N2O"), "pollutant:CO": _P("CO2", "NOx", "NMVOCs", "SO2"),
    "pollutant:CH4": _P("CO2", "N2O", "NMVOCs", "CO2e100"), "pollutant:N2O": _P("NOx", "CH4", "NH3", "CO2"),
    "pollutant:NOx": _P("N2O", "SOx", "NH3", "CO"), "pollutant:SO2": _P("SOx", "NOx", "CO", "NH3"),
    "pollutant:SOx": _P("SO2", "NOx", "CO", "NH3"), "pollutant:NH3": _P("N2O", "NOx", "NMVOCs", "CH4"),
    "pollutant:NMVOCs": _P("CH4", "CO", "NOx", "OC"), "pollutant:BC": _P("OC", "PM2_5", "CO2", "CO"),
    "pollutant:OC": _P("BC", "PM10", "NMVOCs", "CO"), "pollutant:CO2e100": _P("CO2e20", "CO2", "CH4", "N2O"),
    "pollutant:CO2e20": _P("CO2e100", "CO2", "CH4", "N2O"),
    "pollutant:AS": _P("CD", "HG", "PB", "SE"), "pollutant:CD": _P("CU", "CR", "AS", "HG"),
    "pollutant:CR": _P("CU", "CD", "NI", "ZN"), "pollutant:CU": _P("CR", "CD", "ZN", "NI"),
    "pollutant:HG": _P("PB", "AS", "CD", "NI"), "pollutant:NI": _P("ZN", "CR", "CU", "PB"),
    "pollutant:PB": _P("HG", "ZN", "NI", "CD"), "pollutant:SE": _P("AS", "ZN", "CD", "PB"),
    "pollutant:ZN": _P("NI", "CU", "PB", "CR"),
    "level:GEO.country": _L("GEO.region", "GEO.continent", "SECTOR.subsector", "TIME.year"),
    "level:GEO.region": _L("GEO.country", "GEO.continent", "SECTOR.subsector", "TIME.month"),
    "level:GEO.continent": _L("GEO.country", "GEO.region", "SECTOR.macrosector", "TIME.year"),
    "level:TIME.year": _L("TIME.month", "GEO.country", "SECTOR.macrosector", "GEO.region"),
    "level:TIME.month": _L("TIME.year", "GEO.region", "SECTOR.subsector", "GEO.country"),
    "level:SECTOR.subsector": _L("SECTOR.macrosector", "GEO.region", "TIME.month", "GEO.country"),
    "level:SECTOR.macrosector": _L("SECTOR.subsector", "GEO.continent", "TIME.year", "GEO.country"),
}
NONE_DISTRACTORS = {
    "facility_id": _L("GEO.country", "GEO.region", "TIME.year") + _P("CO2"),
    "lat": _L("GEO.region", "GEO.country", "GEO.continent") + _P("PM10"),
    "lon": _L("GEO.region", "GEO.country", "GEO.continent") + _P("NOx"),
    "population": _L("GEO.country", "TIME.year") + _P("CO2", "NOx"),
    "notation_key": _L("SECTOR.subsector", "GEO.country", "TIME.year") + _P("NOx"),
    "station_count": _L("GEO.region", "TIME.month") + _P("PM10", "CO"),
    "element_code": _L("SECTOR.subsector", "SECTOR.macrosector", "TIME.year") + _P("CH4"),
}

TASKS = {
    "gate": {"label": "Answer, clarify or reject", "stage": "query", "type": "choice"},
    "relevance": {"label": "Pollutant relevance", "stage": "query", "type": "noul"},
    "level": {"label": "Breakdown level", "stage": "query", "type": "choice"},
    "mapping": {"label": "Column mapping", "stage": "build", "type": "choice"},
    "entity": {"label": "Entity match", "stage": "build", "type": "noul"},
    "group": {"label": "Whole-group relevance", "stage": "query", "type": "noul"},
    "fit": {"label": "Preference fit", "stage": "rank", "type": "score"},
}

GROUP_GOLD = {"P09": ("all",), "P10": ("ghg",), "P12": ("all",), "P14": ("pm",),
              "P17": ("all",), "A08": ("ghg",), "A12": ("pm",), "A15": ("all",)}


def _item(id_, task, state, questions, question, gold, **meta):
    return {"id": id_, "task": task, "state": state, "questions": questions, "question": question,
            "gold": gold, "meta": meta}


def build() -> list[dict]:
    items = []
    for rid, text, gate, pols, geo, time_, sector, pos, neg in REQUESTS:
        src = "paper" if rid.startswith("P") else "added"
        state, qs = t.gate(text)
        # P15 names unheld NO2; the legacy label silently ignored it.
        gate_gold = "clarify" if rid == "P15" else gate
        items.append(_item(f"gate-{rid}", "gate", state, qs, "gate", gate_gold, request=rid, source=src))
        if gate != "answer":
            continue
        requested = GROUP_GOLD.get(rid, ())
        for group in d.GROUPS:
            qs = {f"group:{group}": t.group_question(group)}
            items.append(_item(f"grp-{rid}-{group}", "group", {"request": text}, qs, f"group:{group}",
                               "yes" if group in requested else "no", request=rid, source=src))
        for pid, label in [(p, "yes") for p in pos] + [(n, "no") for n in neg]:
            state, qs = t.relevance(text, d.POLLUTANT[pid].describe)
            items.append(_item(f"rel-{rid}-{pid}", "relevance", state, qs, "relevant", label, request=rid, pollutant=pid, source=src))
        for dim, gold in (("GEO", geo), ("TIME", time_), ("SECTOR", sector)):
            state, qs = t.levels(text)
            items.append(_item(f"lvl-{rid}-{dim}", "level", state, {dim: qs[dim]}, dim, gold, request=rid, dim=dim, source=src))
    for i, (kind, a, b, same) in enumerate(ENTITIES, 1):
        state, qs = t.entity(kind, a, b)
        items.append(_item(f"ent-{i:02d}", "entity", state, qs, "same", "yes" if same else "no", kind=kind))
    for s in d.SOURCES:
        for col in s.columns:
            distract = NONE_DISTRACTORS[col.name] if col.maps_to is None else HARD[col.maps_to]
            opts = ([col.maps_to] if col.maps_to else []) + distract
            opts = opts[:5] if col.maps_to else opts[:4]
            random.Random(f"{s.id}.{col.name}").shuffle(opts)
            state, qs = t.mapping(s.id, col.name, col.samples, opts)
            items.append(_item(f"map-{s.id}-{col.name}", "mapping", state, qs, "maps_to", t.target_label(col.maps_to),
                               source_id=s.id, column=col.name))
    for group in d.GROUPS:
        qs = {f"group:{group}": t.group_question(group)}
        items.append(_item(f"grp-GX01-{group}", "group", {"request": "Heavy metals by country and year"}, qs,
                           f"group:{group}", "yes" if group == "metal" else "no", request="GX01", source="added"))
    for sid, gold in (("S1", "0"), ("S2", "3"), ("S3", "3"), ("S4", "3"),
                      ("S5", "0"), ("S6", "0"), ("S7", "0"), ("S8", "3")):
        source = d.SOURCE[sid]
        solution = {"sources": [{"id": sid, "name": source.name, "publisher": source.publisher, "updated": source.updated}],
                    "profiles": {}, "cells": 1}
        state, qs = t.fit("Official sources only", source.description, solution)
        items.append(_item(f"fit-{sid}-official", "fit", state, qs, "fit", gold, source_id=sid))
    return items


def gold_query(rid: str) -> dict | None:
    """The labelled structured query for an answerable request, for pipeline checks."""
    for r in REQUESTS:
        if r[0] == rid and r[2] == "answer":
            order = [p.id for p in d.POLLUTANTS]
            pols = order if r[3] == ALL else sorted(r[3], key=order.index)
            levels = {dim: lvl for dim, lvl in zip(("GEO", "TIME", "SECTOR"), r[4:7]) if lvl != "none"}
            return {"pollutants": pols, "levels": levels}
    return None
