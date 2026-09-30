"""Resolve explicit catalogue terms in a request, without broadening it.

The resolver is a guardrail, not a decision model. It reports facts of four kinds:

- named: pollutants and pollutant groups the request names in catalogue terms;
- levels and filters: breakdown levels, and named places, sectors and dates;
- catalogue checks: what the catalogue cannot hold (years outside 2015 to 2025, cities, days,
  hours, weeks, pollutants it does not hold), places or sectors it does not know, and two
  breakdowns for one dimension, which one query cannot express;
- unknown: words it cannot place. The resolver then claims less (a request it cannot fully read
  is not taken as "all pollutants"), and the pipeline lists them for review, since one of them
  may name something the result would otherwise leave out.

The pipeline uses these facts to check the decision model where the request is explicit, never
to replace the model where it is not. CatalogueBackend answers from the resolver alone and is
deliberately conservative: it also rejects forecasts and other kinds of pollution, and any
unknown word makes it ask for clarification.
"""
from __future__ import annotations

import re
import unicodedata

from . import domain as d

# Pollutants people ask for that the catalogue does not hold. Named so the pipeline can say so,
# instead of dropping them silently or treating them as unknown words.
UNHELD = {"NO2": ("no2", "nitrogen dioxide"), "O3": ("ozone", "o3"),
          "SF6": ("sf6", "sulphur hexafluoride")}

_CONTRACTION = re.compile(r"(?<=[a-z])['’](?:d|ll|re|ve|m|s)(?![a-z])")


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = _CONTRACTION.sub("", text)
    return re.sub(r"pm\s*2[.,]?\s*5", "pm2.5", text.replace("sulfur", "sulphur"))


def _find(term: str, text: str):
    return re.finditer(r"(?<![a-z0-9])" + re.escape(norm(term)) + r"(?![a-z0-9])", text)


def contains(text: str, term: str) -> bool:
    return next(_find(term, norm(text)), None) is not None


def named_pollutants(request: str) -> list[str]:
    text, spans, found = norm(request), [], set()
    terms = []
    for p in d.POLLUTANTS:
        names = (p.label, p.id, *p.aliases)
        if len(p.label) <= 2 and p.id not in {"CO", "BC", "OC"}:
            # Element symbols (As, Cd, Pb...) only count with their capitals, so "as" is not arsenic.
            names = tuple(n for n in names if len(n) > 2)
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(p.label) + r"(?![A-Za-z0-9])", request):
                found.add(p.id)
        terms.extend((norm(n), p.id) for n in names)
    # Longest matches first, so 'methane' inside 'non-methane ...' does not become CH4.
    for term, pid in sorted(terms, key=lambda x: -len(x[0])):
        for match in re.finditer(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text):
            if not any(a <= match.start() and match.end() <= b for a, b in spans):
                found.add(pid)
                spans.append(match.span())
    return [p.id for p in d.POLLUTANTS if p.id in found]


def unheld_pollutants(request: str) -> list[str]:
    text = norm(request)
    return [pid for pid, names in UNHELD.items() if any(contains(text, n) for n in names)]


def named_groups(request: str) -> list[str]:
    """Groups the request names as groups. 'all' only when it says so ('all pollutants')."""
    text = norm(request)
    groups = []
    if re.search(r"\b(all|every) (the )?pollutants?\b", text):
        groups.append("all")
    if re.search(r"\b(greenhouse gas(?:es)?|ghg)\b", text):
        groups.append("ghg")
    if contains(text, "particulate matter") and not re.search(r"\b(fine|coarse) particulate", text):
        groups.append("pm")
    if re.search(r"\bheavy metals?\b", text):
        groups.append("metal")
    return groups


def requested_groups(request: str) -> list[str]:
    """Named groups, plus 'all' for a general request the resolver reads completely."""
    return resolve(request)["groups"]


_ALIASES = {"UK": "United Kingdom", "USA": "United States", "Italia": "Italy", "Deutschland": "Germany",
            "Lombardia": "Lombardy", "Bayern": "Bavaria", "Asian": "Asia", "European": "Europe",
            "African": "Africa", "Italian": "Italy", "Australian": "Australia"}
_LEVEL_TERMS = {"region": ("region", "regions", "regional"), "country": ("country", "countries"),
                "continent": ("continent", "continents"), "month": ("month", "months", "monthly"),
                "year": ("year", "years", "yearly", "annual", "annually"),
                "subsector": ("subsector", "subsectors"),
                "macrosector": ("macrosector", "macrosectors", "macro-sector", "macro sectors")}
_GENERAL = re.compile(r"\b(pollution|pollutants|emissions?|data|everything)\b")
_GRANULARITY = re.compile(r"\b(cities|city|streets?|stations?|daily|days?|hourly|hours?|weekly|weeks?)\b")
_FORECAST = re.compile(r"\b(forecasts?|projections?|predictions?)\b")
_OTHER_KIND = re.compile(r"\b(water|noise|radon|soil)\b")
_FILLER = {
    "i", "we", "you", "me", "us", "my", "our", "it", "them", "would", "like", "wish", "want", "need", "to", "can",
    "could", "please", "thanks", "give", "gimme", "gather", "collect", "find", "show", "compare", "analyse",
    "analyze", "obtain", "join", "pull", "together", "get", "break", "down", "breakdown", "what", "about", "how",
    "much", "many", "did", "do", "does", "emit", "emitted", "measure", "measures", "measured", "containing",
    "contain", "contains", "which", "where", "with", "also", "information", "are", "is", "was", "were", "of",
    "the", "a", "an", "and", "or", "in", "on", "for", "across", "from", "by", "per", "all", "each", "every",
    "last", "past", "one", "two", "three", "four", "five", "to", "through", "until", "between", "over",
    "time", "trend", "trends", "total", "totals", "amount", "amounts", "data", "dataset", "datasets", "source",
    "sources", "pollution", "pollutant", "pollutants", "emission", "emissions", "air", "aggregated",
    "aggregate", "aggregation", "level", "levels", "value", "values", "indicator", "indicators", "figures",
    "numbers", "results", "everything", "have", "has", "geography", "geographic", "temporal", "dimensions",
    "official", "only", "most", "recent", "latest", "newest", "available", "updated", "prefer",
}


def _mask_catalogue_terms(text: str) -> str:
    known = list(_ALIASES)
    known += [m for dim in ("GEO", "SECTOR") for lvl in d.DIMENSIONS[dim] for m in d.members(dim, lvl)]
    known += [n for p in d.POLLUTANTS for n in (p.label, p.id, *p.aliases)]
    known += [n for names in UNHELD.values() for n in names]
    known += [term for terms in _LEVEL_TERMS.values() for term in terms]
    known += ["greenhouse gas", "greenhouse gases", "particulate matter", "heavy metals", "heavy metal",
              "sector", "sectors", "industry"]
    text = norm(text)
    for term in sorted(known, key=len, reverse=True):
        text = re.sub(r"(?<![a-z0-9])" + re.escape(norm(term)) + r"(?![a-z0-9])", " ", text)
    return text


def unresolved_constraints(text: str) -> list[str]:
    """Qualifiers after 'in', 'for', 'across' or 'from' that name nothing in the catalogue, such as
    'for Paris'. They must not disappear from the query, so they need clarification."""
    text = _mask_catalogue_terms(text)
    unknown = []
    for clause in re.findall(r"\b(?:in|for|across|from)\s+?(.*?)(?=\b(?:by|per|with|where|aggregated)\b|[;.!?]|$)", text):
        remaining = [w for w in re.findall(r"[a-z]+", clause) if w not in _FILLER]
        if remaining:
            unknown.append(" ".join(remaining))
    return list(dict.fromkeys(unknown))


def unresolved_request_terms(text: str) -> list[str]:
    """Words the resolver cannot place. They never block a request in the pipeline."""
    words = re.findall(r"[a-z][a-z0-9]*", _mask_catalogue_terms(text))
    return list(dict.fromkeys(w for w in words if w not in _FILLER))


def resolve(request: str) -> dict:
    text, levels, filters, issues = norm(request), {}, {}, []
    named = named_pollutants(request)
    groups = named_groups(request)
    unheld = unheld_pollutants(request)
    unknown = unresolved_request_terms(request)

    for dim, choices in d.DIMENSIONS.items():
        explicit = [lvl for lvl in choices if any(contains(text, t) for t in _LEVEL_TERMS[lvl])]
        if dim == "TIME" and "month" in explicit:
            explicit = ["month"]
        if len(explicit) > 1:
            issues.append(f"Choose one {dim.lower()} breakdown: {' or '.join(explicit)}.")
        if explicit:
            levels[dim] = explicit[0]
        elif dim == "GEO" and re.search(r"\b(geography|geographic)\b", text):
            levels[dim] = "country"
        elif dim == "TIME" and re.search(r"\b(temporal|time)\b", text):
            levels[dim] = "year"
        elif dim == "SECTOR" and re.search(r"\b(sectors?|industry)\b", text):
            levels[dim] = "macrosector"

    for dim in ("GEO", "SECTOR"):
        matches, occupied = [], []
        terms = [(m, lvl, m) for lvl in d.DIMENSIONS[dim] for m in d.members(dim, lvl)]
        if dim == "GEO":
            for alias, member in _ALIASES.items():
                lvl = next(l for l in d.DIMENSIONS[dim] if member in d.members(dim, l))
                terms.append((alias, lvl, member))
        for term, lvl, member in sorted(terms, key=lambda x: -len(x[0])):
            for match in _find(term, text):
                if not any(a <= match.start() and match.end() <= b for a, b in occupied):
                    occupied.append(match.span())
                    matches.append((lvl, member))
        if matches:
            if len({d.DIMENSIONS[dim].index(l) for l, _ in matches}) > 1:
                issues.append(f"The request names {dim.lower()} members at different levels; name one level.")
            lvl = min(matches, key=lambda x: d.DIMENSIONS[dim].index(x[0]))[0]
            filters[dim] = {"level": lvl, "members": list(dict.fromkeys(m for l, m in matches if l == lvl))}
            levels.setdefault(dim, lvl)

    year_tokens = [int(y) for y in re.findall(r"(?<![0-9])(?:18|19|20|21)[0-9]{2}(?![0-9])", text)]
    relative = re.search(r"\b(?:last|past) (\d+|one|two|three|four|five) years?\b", text)
    if relative:
        number = relative[1]
        count = int(number) if number.isdigit() else {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}[number]
        year_tokens = [max(d.YEARS) - count + 1, max(d.YEARS)]
    if year_tokens:
        levels.setdefault("TIME", "year")
        start, end = min(year_tokens), max(year_tokens)
        date = r"\d{4}(?:-\d{2})?"
        continuous = bool(relative or re.search(r"\bbetween\s+" + date + r"\s+and\s+" + date
                                               + r"|" + date + r"\s*(?:-|–|to|through|until)\s*" + date, text))
        selected = list(range(start, end + 1)) if continuous else sorted(set(year_tokens))
        iso_months = re.findall(r"\b(\d{4}-(?:0[1-9]|1[0-2]))\b", text)
        if iso_months:
            selected_months = d.months(min(iso_months), max(iso_months)) if continuous else sorted(set(iso_months))
            filters["TIME"] = {"level": "month", "members": selected_months}
            levels.setdefault("TIME", "month")
            if not any(contains(text, t) for t in _LEVEL_TERMS["year"]):
                levels["TIME"] = "month"
        else:
            filters["TIME"] = {"level": "year", "members": [str(y) for y in selected]}
    for qualifier in unresolved_constraints(request):
        issues.append(f"'{qualifier}' is not a place, sector or period in the catalogue.")

    general = bool(_GENERAL.search(text))
    # A general request ("air emissions by country") means every pollutant, but only when the
    # resolver has read the whole request: "benzene emissions" is not a request for everything.
    if not groups and not named and not unheld and general and not unknown:
        groups = ["all"]
    pollutants = list(dict.fromkeys(named + [p for g in groups for p in d.group_members(g)]))
    pollutants = [p.id for p in d.POLLUTANTS if p.id in pollutants]

    # Facts about the catalogue: these stop a request whatever the model says.
    reasons = []
    outside = sorted({y for y in year_tokens if y not in d.YEARS})
    if outside:
        reasons.append(f"The catalogue holds years {min(d.YEARS)} to {max(d.YEARS)}, not {', '.join(map(str, outside))}.")
    if m := _GRANULARITY.search(text):
        reasons.append(f"The catalogue has no data by {m[1]}.")
    if unheld and not pollutants:
        reasons.append(f"{' and '.join(unheld)} {'is' if len(unheld) == 1 else 'are'} not held in the catalogue.")
    hard_reject = " ".join(reasons) or None
    # Judgements the rules backend makes for itself; in the pipeline the model makes them.
    rules_reject = bool(hard_reject or _FORECAST.search(text) or _OTHER_KIND.search(text))
    off_topic = not pollutants and not unheld and not levels and not general
    gate = ("reject" if rules_reject or off_topic else
            "clarify" if issues or unknown or not pollutants or not levels else "answer")
    return {"gate": gate, "pollutants": pollutants, "named": named, "groups": groups, "levels": levels,
            "filters": filters, "issues": issues, "unknown": unknown, "unheld": unheld,
            "hard_reject": hard_reject, "covered": not unknown,
            "time_anchor": max(d.YEARS) if relative else None}


def preference_score(preference: str, solution: dict) -> int | None:
    """Small explicit rubric; unknown preferences are not silently assigned a score."""
    text, scores = norm(preference), []
    if "as many" in text or "coverage" in text:
        return None
    allowed = {"official", "sources", "source", "only", "the", "most", "recent", "latest", "newest", "data",
               "available", "updated", "prefer", "please", "in", "for", "across", "from", "and", "with", "by",
               "per", "all", "each", "every", "last", "past", "one", "two", "three", "four", "five",
               "to", "through", "until", "between", "countries", "regions", "continents"}
    if any(word not in allowed for word in re.findall(r"[a-z]+", _mask_catalogue_terms(preference))):
        return None
    if contains(text, "official"):
        official = [s["publisher"] == "official" for s in solution["sources"]]
        scores.append(3 if all(official) else 1 if any(official) else 0)
    if re.search(r"\b(recent|latest|newest)\b", text):
        latest = min(s["updated"] for s in solution["sources"])
        scores.append(max(0, 3 - (max(d.YEARS) - latest)))
    parsed = resolve(preference)
    if parsed["issues"] or named_pollutants(preference) or any(g != "all" for g in parsed["groups"]):
        return None
    constraints = parsed["filters"]
    for dim, constraint in constraints.items():
        keys = [k for k in solution["profiles"] if k.startswith(dim + ".")]
        if keys:
            key = keys[0]
            native = key.split(".")[1]
            covered = {d.roll_up(dim, native, m, constraint["level"]) for m in solution["profiles"][key]}
            share = len(covered & set(constraint["members"])) / len(constraint["members"])
            scores.append(int(3 * share))
        else:
            scores.append(0)
    return min(scores) if scores else None
