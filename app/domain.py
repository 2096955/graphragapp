"""The catalogue domain: air pollution datasets, modelled on the paper's running example.

Diamantini et al., "A Graph RAG Approach to Enhance Explainability in Dataset Discovery",
Data Science and Engineering 11:30-52 (2026), doi:10.1007/s41019-025-00313-x.

Two layers, as in the paper:
  * background knowledge (BKG): pollutants, dimensions, levels, members and their hierarchies
  * source knowledge (SKG): datasets, their columns and what each column maps to

The sources are invented. They are modelled on the kinds of sources the paper used (a global
facility inventory, a national statistics compendium, an EU reporting dataset and so on), but
their names, columns and coverage are synthetic and describe no real publication.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

# --------------------------------------------------------------------------------------------
# Pollutants (the paper's 24 indicators) and the groups the graph expands
# --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Pollutant:
    id: str            # stable id used everywhere, e.g. "PM2_5"
    label: str         # display label, e.g. "PM2.5"
    name: str          # plain name
    unit: str
    groups: tuple[str, ...]
    aliases: tuple[str, ...] = ()

    @property
    def describe(self) -> str:
        return f"{self.label}: {self.name}"


POLLUTANTS: list[Pollutant] = [
    Pollutant("CO2", "CO2", "carbon dioxide", "Mt", ("ghg",), ("carbon dioxide", "co2", "carbon emissions")),
    Pollutant("CO2e100", "CO2e (100-year)", "CO2-equivalent, 100-year global warming potential", "Mt", ("ghg",),
              ("co2e100", "co2-equivalent", "co2 equivalent", "gwp100")),
    Pollutant("CO2e20", "CO2e (20-year)", "CO2-equivalent, 20-year global warming potential", "Mt", ("ghg",),
              ("co2e20", "gwp20")),
    Pollutant("CH4", "CH4", "methane", "kt", ("ghg",), ("methane", "ch4")),
    Pollutant("N2O", "N2O", "nitrous oxide", "kt", ("ghg",), ("nitrous oxide", "n2o")),
    Pollutant("PM2_5", "PM2.5", "fine particulate matter, particles smaller than 2.5 micrometres", "ug/m3", ("pm",),
              ("pm2.5", "pm25", "pm 2.5", "fine particulate")),
    Pollutant("PM10", "PM10", "particulate matter, particles smaller than 10 micrometres", "ug/m3", ("pm",),
              ("pm10", "pm 10", "coarse particulate")),
    Pollutant("NOx", "NOx", "nitrogen oxides", "kt", ("air",), ("nox", "nitrogen oxides", "nitrogen oxide")),
    Pollutant("SO2", "SO2", "sulphur dioxide", "kt", ("air",), ("so2", "sulphur dioxide", "sulfur dioxide")),
    Pollutant("SOx", "SOx", "sulphur oxides", "kt", ("air",), ("sox", "sulphur oxides", "sulfur oxides")),
    Pollutant("NH3", "NH3", "ammonia", "kt", ("air",), ("nh3", "ammonia")),
    Pollutant("CO", "CO", "carbon monoxide", "kt", ("air",), ("carbon monoxide",)),
    Pollutant("NMVOCs", "NMVOCs", "non-methane volatile organic compounds", "kt", ("air",),
              ("nmvoc", "nmvocs", "volatile organic compounds")),
    Pollutant("BC", "BC", "black carbon", "kt", ("air",), ("black carbon",)),
    Pollutant("OC", "OC", "organic carbon", "kt", ("air",), ("organic carbon",)),
    Pollutant("AS", "As", "arsenic", "t", ("metal",), ("arsenic",)),
    Pollutant("CD", "Cd", "cadmium", "t", ("metal",), ("cadmium",)),
    Pollutant("CR", "Cr", "chromium", "t", ("metal",), ("chromium",)),
    Pollutant("CU", "Cu", "copper", "t", ("metal",), ("copper",)),
    Pollutant("HG", "Hg", "mercury", "t", ("metal",), ("mercury",)),
    Pollutant("NI", "Ni", "nickel", "t", ("metal",), ("nickel",)),
    Pollutant("PB", "Pb", "lead", "t", ("metal",), ("lead",)),
    Pollutant("SE", "Se", "selenium", "t", ("metal",), ("selenium",)),
    Pollutant("ZN", "Zn", "zinc", "t", ("metal",), ("zinc",)),
]
POLLUTANT = {p.id: p for p in POLLUTANTS}

# Groups are graph nodes too. Choosing a group expands to its members through the graph.
GROUPS: dict[str, dict] = {
    "all": {"label": "All pollutants",
            "describe": "all pollutants, as in a request for pollution, emissions or data in general that names no specific pollutant or group"},
    "ghg": {"label": "Greenhouse gases",
            "describe": "greenhouse gases as a group (CO2, CO2-equivalents, methane and nitrous oxide), asked for by that name"},
    "pm": {"label": "Particulate matter",
           "describe": "particulate matter as a group (PM2.5 and PM10), asked for by that name"},
    "metal": {"label": "Heavy metals",
              "describe": "heavy metals as a group (arsenic, cadmium, chromium, copper, mercury, nickel, lead, selenium, zinc), asked for by that name"},
}


def group_members(group: str) -> list[str]:
    if group == "all":
        return [p.id for p in POLLUTANTS]
    return [p.id for p in POLLUTANTS if group in p.groups]


# --------------------------------------------------------------------------------------------
# Dimensions, levels and members
# --------------------------------------------------------------------------------------------

# Finest to coarsest. Only these levels are held; cities, days, stations and so on are not.
DIMENSIONS: dict[str, list[str]] = {
    "GEO": ["region", "country", "continent"],
    "TIME": ["month", "year"],
    "SECTOR": ["subsector", "macrosector"],
}
DEFAULT_LEVEL = {"GEO": "country", "TIME": "year", "SECTOR": "macrosector"}
YEARS = list(range(2015, 2026))

CONTINENTS = ["Europe", "Americas", "Asia", "Africa", "Oceania"]
COUNTRIES = {
    "Italy": "Europe", "France": "Europe", "Germany": "Europe", "Spain": "Europe", "Portugal": "Europe",
    "Poland": "Europe", "United Kingdom": "Europe", "United States": "Americas", "Brazil": "Americas",
    "China": "Asia", "India": "Asia", "Japan": "Asia", "Australia": "Oceania", "South Africa": "Africa",
    "Nigeria": "Africa",
}
EUROPE = [c for c, k in COUNTRIES.items() if k == "Europe"]
REGIONS = {
    "Veneto": "Italy", "Lazio": "Italy", "Lombardy": "Italy", "Ile-de-France": "France",
    "Auvergne-Rhone-Alpes": "France", "Brandenburg": "Germany", "Bavaria": "Germany", "Andalusia": "Spain",
}
MACROSECTORS = ["Agriculture", "Buildings", "Fossil Fuel Operations", "Forestry and Land Use", "Manufacturing",
                "Power", "Transportation", "Waste"]
SUBSECTORS = {
    "Coal mining": "Fossil Fuel Operations", "Oil and gas extraction": "Fossil Fuel Operations",
    "Road transport": "Transportation", "Aviation": "Transportation", "Shipping": "Transportation",
    "Electricity generation": "Power", "Crop residue burning": "Agriculture", "Livestock": "Agriculture",
    "Residential heating": "Buildings", "Cement": "Manufacturing", "Steel": "Manufacturing",
    "Landfill": "Waste", "Deforestation": "Forestry and Land Use",
}


def months(start: str, end: str) -> list[str]:
    y, m = map(int, start.split("-"))
    ye, me = map(int, end.split("-"))
    out = []
    while (y, m) <= (ye, me):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def members(dim: str, level: str) -> list[str]:
    if dim == "GEO":
        return {"region": list(REGIONS), "country": list(COUNTRIES), "continent": CONTINENTS}[level]
    if dim == "TIME":
        return months("2015-01", "2025-12") if level == "month" else [str(y) for y in YEARS]
    return list(SUBSECTORS) if level == "subsector" else MACROSECTORS


def parent(dim: str, level: str, member: str) -> str | None:
    """The member one level up, or None at the top."""
    if dim == "GEO":
        return {"region": REGIONS, "country": COUNTRIES}.get(level, {}).get(member)
    if dim == "TIME":
        return member[:4] if level == "month" else None
    return SUBSECTORS.get(member) if level == "subsector" else None


def roll_up(dim: str, level: str, member: str, target: str) -> str | None:
    lv = DIMENSIONS[dim]
    i, j = lv.index(level), lv.index(target)
    if i > j:
        return None
    m: str | None = member
    for k in range(i, j):
        m = parent(dim, lv[k], m) if m is not None else None
    return m


def plural(level: str, n: int) -> str:
    """'1 country', '7 countries', '12 months'."""
    word = level if n == 1 else (level[:-1] + "ies" if level.endswith("y") else level + "s")
    return f"{n} {word}"


def level_rolls_up(dim: str, source_level: str, target_level: str) -> bool:
    lv = DIMENSIONS[dim]
    return lv.index(source_level) <= lv.index(target_level)


CATALOGUE_SUMMARY = (
    "Holds 24 air pollutants and greenhouse gases: CO2, CO2-equivalents, CH4, N2O, PM2.5, PM10, NOx, "
    "SO2, SOx, NH3, CO, NMVOCs, black carbon, organic carbon and nine heavy metals. Breakdowns: region, "
    "country or continent; month or year, 2015 to 2025; subsector or macrosector."
)

# --------------------------------------------------------------------------------------------
# Sources (synthetic)
# --------------------------------------------------------------------------------------------

@dataclass
class Column:
    name: str
    maps_to: str | None      # "pollutant:PM2_5", "level:GEO.country" or None
    samples: list[str]


@dataclass
class Source:
    id: str
    name: str
    description: str
    publisher: str           # "official", "research" or "commercial"
    updated: int
    levels: dict[str, str]   # dimension -> native level; a missing dimension is not held
    coverage: dict[str, list[str]]  # dimension -> members at the native level
    columns: list[Column]
    rows: dict[str, dict[str, int]] = field(default_factory=dict)  # dimension -> member -> rows

    @property
    def pollutants(self) -> list[str]:
        return [c.maps_to.split(":")[1] for c in self.columns if c.maps_to and c.maps_to.startswith("pollutant:")]


def _col(name, maps_to, *samples):
    return Column(name, maps_to, list(samples))


ALL_COUNTRIES = list(COUNTRIES)
ASIA_PACIFIC = ["China", "India", "Japan", "Australia"]

SOURCES: list[Source] = [
    Source(
        "S1", "Global Facility Emissions Inventory",
        "Facility-level greenhouse gas estimates aggregated to country, month and subsector.",
        "research", 2025,
        {"GEO": "country", "TIME": "month", "SECTOR": "subsector"},
        {"GEO": ALL_COUNTRIES, "TIME": months("2021-01", "2025-06"), "SECTOR": [s for s in SUBSECTORS if s != "Deforestation"]},
        [_col("iso3_country", "level:GEO.country", "ITA", "FRA", "BRA"),
         _col("start_time", "level:TIME.month", "2021-03-01", "2024-11-01"),
         _col("sector_subtype", "level:SECTOR.subsector", "road-transportation", "cement"),
         _col("co2_t", "pollutant:CO2", "18234.5", "902.1"),
         _col("ch4_t", "pollutant:CH4", "12.4", "0.8"),
         _col("n2o_t", "pollutant:N2O", "0.61", "0.02"),
         _col("co2e_100yr", "pollutant:CO2e100", "19120.3", "955.7"),
         _col("co2e_20yr", "pollutant:CO2e20", "19788.0", "990.2"),
         _col("facility_id", None, "F-00321", "F-19877"),
         _col("lat", None, "45.43", "-23.55"),
         _col("lon", None, "12.33", "-46.63")],
    ),
    Source(
        "S2", "National Emissions Compendium",
        "Country-year totals compiled from national inventories, without a sector breakdown.",
        "official", 2024,
        {"GEO": "country", "TIME": "year"},
        {"GEO": ALL_COUNTRIES, "TIME": [str(y) for y in range(2015, 2024)]},
        [_col("country", "level:GEO.country", "Italy", "Japan"),
         _col("iso_code", "level:GEO.country", "ITA", "JPN"),
         _col("year", "level:TIME.year", "2016", "2022"),
         _col("co2", "pollutant:CO2", "317.2", "1064.4"),
         _col("methane", "pollutant:CH4", "1580.3", "1204.9"),
         _col("nitrous_oxide", "pollutant:N2O", "52.1", "40.7"),
         _col("nox_emissions", "pollutant:NOx", "612.0", "1405.8"),
         _col("so2_emissions", "pollutant:SO2", "98.4", "503.2"),
         _col("co_emissions", "pollutant:CO", "2211.9", "3920.3"),
         _col("bc_emissions", "pollutant:BC", "21.7", "18.0"),
         _col("oc_emissions", "pollutant:OC", "48.2", "30.6"),
         _col("nh3_emissions", "pollutant:NH3", "360.8", "440.1"),
         _col("nmvoc_emissions", "pollutant:NMVOCs", "802.4", "915.0"),
         _col("population", None, "59110000", "125700000")],
    ),
    Source(
        "S3", "European Air Emissions Reporting",
        "Air pollutant emissions reported by European countries, by year and reporting subsector.",
        "official", 2025,
        {"GEO": "country", "TIME": "year", "SECTOR": "subsector"},
        {"GEO": EUROPE, "TIME": [str(y) for y in range(2015, 2025)],
         "SECTOR": ["Road transport", "Aviation", "Shipping", "Electricity generation", "Residential heating",
                    "Livestock", "Cement", "Steel", "Landfill"]},
        [_col("country_code", "level:GEO.country", "IT", "PL"),
         _col("reporting_year", "level:TIME.year", "2019", "2023"),
         _col("nfr_sector", "level:SECTOR.subsector", "1A3bi", "3B1a"),
         _col("pm25_kt", "pollutant:PM2_5", "141.2", "98.7"),
         _col("pm10_kt", "pollutant:PM10", "171.9", "140.2"),
         _col("nox_kt", "pollutant:NOx", "630.4", "512.0"),
         _col("sox_kt", "pollutant:SOx", "101.3", "402.8"),
         _col("nh3_kt", "pollutant:NH3", "344.1", "301.9"),
         _col("nmvoc_kt", "pollutant:NMVOCs", "780.2", "560.4"),
         _col("co_kt", "pollutant:CO", "1804.6", "2210.3"),
         _col("as_t", "pollutant:AS", "6.2", "11.8"),
         _col("cd_t", "pollutant:CD", "4.1", "9.7"),
         _col("cr_t", "pollutant:CR", "18.3", "29.5"),
         _col("cu_t", "pollutant:CU", "210.4", "160.2"),
         _col("hg_t", "pollutant:HG", "3.1", "9.9"),
         _col("ni_t", "pollutant:NI", "40.2", "55.1"),
         _col("pb_t", "pollutant:PB", "120.8", "188.4"),
         _col("se_t", "pollutant:SE", "5.6", "7.3"),
         _col("zn_t", "pollutant:ZN", "410.5", "620.1"),
         _col("notation_key", None, "NE", "IE")],
    ),
    Source(
        "S4", "Regional Air Monitoring Network",
        "Monthly mean concentrations from regional monitoring networks in four European countries.",
        "official", 2025,
        {"GEO": "region", "TIME": "month"},
        {"GEO": list(REGIONS), "TIME": months("2019-01", "2025-08")},
        [_col("nuts2_region", "level:GEO.region", "ITH3", "FR10"),
         _col("date_month", "level:TIME.month", "2023-01", "2025-07"),
         _col("pm25_ugm3", "pollutant:PM2_5", "18.2", "11.4"),
         _col("pm10_ugm3", "pollutant:PM10", "31.0", "22.8"),
         _col("nox_ugm3", "pollutant:NOx", "44.9", "29.3"),
         _col("so2_ugm3", "pollutant:SO2", "2.1", "1.4"),
         _col("co_mgm3", "pollutant:CO", "0.5", "0.3"),
         _col("station_count", None, "38", "12")],
    ),
    Source(
        "S5", "Continental Climate Summary",
        "Greenhouse gas totals by continent, year and macrosector.",
        "research", 2024,
        {"GEO": "continent", "TIME": "year", "SECTOR": "macrosector"},
        {"GEO": CONTINENTS, "TIME": [str(y) for y in range(2015, 2025)], "SECTOR": MACROSECTORS},
        [_col("continent", "level:GEO.continent", "Europe", "Asia"),
         _col("year", "level:TIME.year", "2018", "2024"),
         _col("sector_group", "level:SECTOR.macrosector", "Power", "Agriculture"),
         _col("co2_mt", "pollutant:CO2", "3120.4", "18204.9"),
         _col("ch4_mt", "pollutant:CH4", "18.2", "120.6"),
         _col("n2o_mt", "pollutant:N2O", "1.1", "4.9"),
         _col("ghg_co2e_100", "pollutant:CO2e100", "4012.8", "25630.2")],
    ),
    Source(
        "S6", "Asia-Pacific Particulate Survey",
        "Particulate matter and black carbon estimates for four Asia-Pacific countries.",
        "research", 2023,
        {"GEO": "country", "TIME": "year", "SECTOR": "macrosector"},
        {"GEO": ASIA_PACIFIC, "TIME": [str(y) for y in range(2016, 2023)],
         "SECTOR": ["Power", "Transportation", "Manufacturing", "Buildings", "Agriculture"]},
        [_col("nation", "level:GEO.country", "India", "Australia"),
         _col("survey_year", "level:TIME.year", "2017", "2021"),
         _col("sector", "level:SECTOR.macrosector", "Transportation", "Power"),
         _col("pm2_5", "pollutant:PM2_5", "52.3", "7.9"),
         _col("pm_10", "pollutant:PM10", "98.1", "16.2"),
         _col("black_carbon", "pollutant:BC", "0.9", "0.2")],
    ),
    Source(
        "S7", "Transport Emissions Tracker",
        "Monthly emissions from road, air and sea transport for 15 countries.",
        "commercial", 2025,
        {"GEO": "country", "TIME": "month", "SECTOR": "subsector"},
        {"GEO": ALL_COUNTRIES, "TIME": months("2018-01", "2025-06"), "SECTOR": ["Road transport", "Aviation", "Shipping"]},
        [_col("country_iso", "level:GEO.country", "DEU", "AUS"),
         _col("month", "level:TIME.month", "2020-04", "2025-02"),
         _col("transport_mode", "level:SECTOR.subsector", "road", "aviation"),
         _col("co2_tonnes", "pollutant:CO2", "8812345", "403221"),
         _col("nox_tonnes", "pollutant:NOx", "20431", "3210"),
         _col("so2_tonnes", "pollutant:SO2", "1230", "8830"),
         _col("pm25_tonnes", "pollutant:PM2_5", "812", "140")],
    ),
    Source(
        "S8", "Agricultural Emissions Database",
        "Emissions from livestock and crop residue burning by country and year.",
        "official", 2025,
        {"GEO": "country", "TIME": "year", "SECTOR": "subsector"},
        {"GEO": ALL_COUNTRIES, "TIME": [str(y) for y in range(2015, 2026)], "SECTOR": ["Livestock", "Crop residue burning"]},
        [_col("area", "level:GEO.country", "Brazil", "Nigeria"),
         _col("year", "level:TIME.year", "2015", "2025"),
         _col("item", "level:SECTOR.subsector", "Enteric fermentation", "Burning crop residues"),
         _col("ch4_kt", "pollutant:CH4", "13020.5", "812.9"),
         _col("n2o_kt", "pollutant:N2O", "402.2", "31.8"),
         _col("nh3_kt", "pollutant:NH3", "2010.4", "120.3"),
         _col("element_code", None, "7225", "7230")],
    ),
]
SOURCE = {s.id: s for s in SOURCES}


def _fill_rows(seed: int = 20260930) -> None:
    """Deterministic synthetic row counts per member, with some gaps, for the join estimator."""
    r = random.Random(seed)
    for s in SOURCES:
        s.rows = {}
        for dim, mems in s.coverage.items():
            counts = {}
            for m in mems:
                if r.random() < 0.08:          # occasional gaps in coverage
                    continue
                base = {"GEO": 40, "TIME": 25, "SECTOR": 30}[dim]
                counts[m] = int(base * (0.4 + r.random() * 1.2))
            s.rows[dim] = counts


_fill_rows()


def source_covers_query(s: Source, levels: dict[str, str]) -> bool:
    """A source can serve a query if it holds every requested dimension at the same or a finer level."""
    for dim, lvl in levels.items():
        native = s.levels.get(dim)
        if native is None or not level_rolls_up(dim, native, lvl):
            return False
    return True
