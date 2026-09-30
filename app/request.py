"""Resolve explicit catalogue terms without broadening a user's request."""
from __future__ import annotations

import re
import unicodedata

from . import domain as d


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"pm\s*2[.,]?\s*5", "pm2.5", text.replace("sulfur", "sulphur"))


def contains(text: str, term: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(norm(term)) + r"(?![a-z0-9])", norm(text)))


def named_pollutants(request: str) -> list[str]:
    text, spans, found = norm(request), [], set()
    terms = []
    for p in d.POLLUTANTS:
        names = (p.label, p.id, *p.aliases)
        if len(p.label) <= 2 and p.id not in {"CO", "BC", "OC"}:
            names = tuple(n for n in names if len(n) > 2)
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(p.label) + r"(?![A-Za-z0-9])", request):
                found.add(p.id)
        terms.extend((norm(n), p.id) for n in names)
    # Longest matches prevent 'methane' inside 'non-methane ...' becoming CH4.
    for term, pid in sorted(terms, key=lambda x: -len(x[0])):
        for match in re.finditer(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text):
            if not any(a <= match.start() and match.end() <= b for a, b in spans):
                found.add(pid)
                spans.append(match.span())
    return [p.id for p in d.POLLUTANTS if p.id in found]


def requested_groups(request: str) -> list[str]:
    text = norm(request)
    groups = []
    if re.search(r"\b(greenhouse gas(?:es)?|ghg)\b", text):
        groups.append("ghg")
    if contains(text, "particulate matter") and not re.search(r"\b(fine|coarse) particulate", text):
        groups.append("pm")
    if re.search(r"\bheavy metals?\b", text):
        groups.append("metal")
    specific = named_pollutants(request)
    if contains(text, "all pollutants") or (not groups and not specific and re.search(r"\b(pollution|emissions?|data|everything)\b", text)):
        groups.insert(0, "all")
    return groups


_ALIASES = {"UK": "United Kingdom", "USA": "United States", "Italia": "Italy", "Deutschland": "Germany",
            "Lombardia": "Lombardy", "Bayern": "Bavaria", "Asian": "Asia", "European": "Europe",
            "African": "Africa", "Italian": "Italy", "Australian": "Australia"}
_LEVEL_TERMS = {"region": ("region", "regions", "regional"), "country": ("country", "countries", "contry"),
                "continent": ("continent", "continents"), "month": ("month", "months", "monthly"),
                "year": ("year", "years", "yearly", "annual", "annually", "yeer"),
                "subsector": ("subsector", "subsectors"),
                "macrosector": ("macrosector", "macrosectors", "macro-sector", "macro sectors")}


def _mask_catalogue_terms(text: str) -> str:
    known = list(_ALIASES)
    known += [m for dim in ("GEO", "SECTOR") for lvl in d.DIMENSIONS[dim] for m in d.members(dim, lvl)]
    known += [n for p in d.POLLUTANTS for n in (p.label, p.id, *p.aliases)]
    known += [term for terms in _LEVEL_TERMS.values() for term in terms]
    known += ["greenhouse gas", "greenhouse gases", "particulate matter", "heavy metals", "heavy metal",
              "sector", "sectors", "industry"]
    text = norm(text)
    for term in sorted(known, key=len, reverse=True):
        text = re.sub(r"(?<![a-z0-9])" + re.escape(norm(term)) + r"(?![a-z0-9])", " ", text)
    return text


def unresolved_constraints(text: str) -> list[str]:
    """Keep unrecognised qualifiers from disappearing from a catalogue query."""
    text = _mask_catalogue_terms(text)
    ignored = {"all", "the", "a", "an", "and", "or", "each", "every", "last", "past", "one", "two", "three",
               "four", "five", "data", "dataset", "datasets", "source", "sources", "emission", "emissions",
               "pollution", "pollutants", "air", "countries", "continents", "geography", "temporal", "dimensions",
               "to", "through", "until", "between"}
    unknown = []
    for clause in re.findall(r"\b(?:in|for|across|from)\s+?(.*?)(?=\b(?:by|per|with|where|aggregated)\b|[;.!?]|$)", text):
        words = re.findall(r"[a-z]+", clause)
        remaining = [w for w in words if w not in ignored and w not in {"in", "for", "across", "from"}]
        if remaining:
            unknown.append(" ".join(remaining))
    return list(dict.fromkeys(unknown))


def unresolved_request_terms(text: str) -> list[str]:
    # The rules backend supports catalogue wording, not arbitrary free-form intent.
    allowed = {"i", "we", "you", "would", "like", "wish", "want", "to", "can", "could", "please", "me",
               "gimme", "give", "gather", "collect", "find", "show", "compare", "analyse", "analyze", "aanlyse",
               "obtain", "join", "pull", "get", "break", "it", "down", "what", "about", "how", "much", "did",
               "emit", "emitted", "measure", "measures", "measured", "containing", "contain", "contains", "which",
               "where", "with", "also", "information", "are", "is", "of", "the", "a", "an", "and", "or", "in",
               "for", "across", "from", "by", "per", "all", "each", "every", "last", "past", "one", "two", "three",
               "four", "five", "to", "through", "until", "between", "data", "dataset", "datasets", "source", "sources",
               "pollution", "pollutant", "pollutants", "emission", "emissions", "air", "aggregated", "aggregate",
               "aggregation", "level", "levels", "value", "values", "indicator", "indicators", "figures", "numbers",
               "results", "everything", "have", "ghg", "geography", "geographic", "temporal", "time", "dimensions",
               "official", "only", "most", "recent", "latest", "newest", "available", "updated", "prefer"}
    words = re.findall(r"[a-z][a-z0-9]*", _mask_catalogue_terms(text))
    return list(dict.fromkeys(w for w in words if w not in allowed))


def resolve(request: str) -> dict:
    text, levels, filters, issues = norm(request), {}, {}, []
    pollutants = named_pollutants(request)
    groups = requested_groups(request)
    for g in groups:
        pollutants = list(dict.fromkeys(pollutants + d.group_members(g)))
    pollutants = [p.id for p in d.POLLUTANTS if p.id in pollutants]

    for dim, choices in d.DIMENSIONS.items():
        explicit = [lvl for lvl in choices if any(contains(text, t) for t in _LEVEL_TERMS[lvl])]
        if dim == "TIME" and "month" in explicit:
            explicit = ["month"]
        if len(explicit) > 1:
            issues.append(f"Choose one {dim.lower()} aggregation level.")
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
            for match in re.finditer(r"(?<![a-z0-9])" + re.escape(norm(term)) + r"(?![a-z0-9])", text):
                if not any(a <= match.start() and match.end() <= b for a, b in occupied):
                    occupied.append(match.span())
                    matches.append((lvl, member))
        if matches:
            ranks = {d.DIMENSIONS[dim].index(l) for l, _ in matches}
            if len(ranks) > 1:
                issues.append(f"Mixed {dim.lower()} member levels need clarification.")
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
                                               + r"|" + date + r"\s*(?:-|\u2013|to|through|until)\s*" + date, text))
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
        issues.append(f"Unrecognised constraint '{qualifier}'; use catalogue members or clarify the request.")
    unknown = unresolved_request_terms(request)
    if unknown and not issues:
        issues.append("Unrecognised request terms: " + ", ".join(unknown) + ". Use catalogue terms or clarify the request.")
    unsupported = bool(re.search(r"\b(cities|city|streets?|stations?|daily|days?|hourly|hours?|weeks?|forecasts?|water|noise|radon|poem|world cup)\b", text))
    outside = any(y not in d.YEARS for y in year_tokens)
    unheld = bool(re.search(r"\b(ozone|no2|sf6|sulphur hexafluoride)\b", text))
    if unheld and not named_pollutants(request):
        unsupported = True
        pollutants = []
    off_topic = not pollutants and not levels and not re.search(r"\b(pollution|emissions?|data|everything)\b", text)
    gate = "reject" if unsupported or outside or off_topic else "clarify" if issues or not pollutants or not levels else "answer"
    return {"gate": gate, "pollutants": pollutants, "groups": groups, "levels": levels,
            "filters": filters, "issues": issues, "time_anchor": max(d.YEARS) if relative else None}


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
