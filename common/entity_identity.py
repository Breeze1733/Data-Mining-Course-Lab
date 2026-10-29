"""One reviewed alias source shared by entity extraction, routes and the graph.

Names are scoped by scenic area. Ambiguous unscoped names are left unchanged;
there is deliberately no fuzzy matching or automatic hotel/region merging.
"""
import csv
import re
from functools import lru_cache
from pathlib import Path

ALIAS_PATH = Path(__file__).resolve().parents[1] / "task2/resources/poi_aliases.csv"


def read_aliases(path: Path) -> dict[tuple[str, str], str]:
    aliases = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            area, alias, target = (row[key].strip() for key in ("area", "alias", "canonical"))
            if not area or not alias or not target:
                raise ValueError("Alias rows require area, alias and canonical")
            key = (area, alias)
            if key in aliases and aliases[key] != target:
                raise ValueError(f"Conflicting alias: {key}")
            if alias != target:
                aliases[key] = target
    for area, alias in aliases:
        visited = set()
        current = alias
        while (area, current) in aliases:
            if current in visited:
                raise ValueError(f"Alias cycle in {area}: {alias}")
            visited.add(current)
            current = aliases[(area, current)]
    return aliases


@lru_cache(maxsize=1)
def aliases():
    return read_aliases(ALIAS_PATH)


def canonical_name(name: str, scenic_area: str | None = None) -> str:
    table = aliases()
    if scenic_area is None:
        areas = {area for area, alias in table if alias == name}
        targets = {canonical_name(name, area) for area in areas}
        return next(iter(targets)) if len(targets) == 1 else name
    while (scenic_area, name) in table:
        name = table[(scenic_area, name)]
    return name


_SUFFIX = re.compile(r"(?:风景区|景区|入口|出口)$")
_PREFIX = {"黄山南大门": "南大门", "黄山北大门": "北大门", "黄山西门": "西门",
           "九寨沟沟口": "沟口", "九寨沟景区": "九寨沟"}


def normalize(name: str) -> str:
    """Legacy route display normalization; identity remains area-scoped canonical."""
    name = canonical_name(name)
    for prefix, short in _PREFIX.items():
        if name.startswith(prefix) and name != prefix:
            return normalize(short + name[len(prefix):])
    return _SUFFIX.sub("", name)


def build_poi_lookup(entries: list[dict]) -> dict[tuple[str, str], str]:
    """Map route display names back to the same canonical names as NER.

    Display shortening is accepted only when it identifies a single known POI
    in that area. This prevents two distinct objects being silently collapsed.
    """
    lookup = {}
    for entry in entries:
        for area in entry["scenic_areas"]:
            target = canonical_name(entry["canonical"], area)
            for variant in (entry["canonical"], normalize(entry["canonical"]), target, normalize(target), entry.get("name", "")):
                if not variant:
                    continue
                key = (area, variant)
                if key in lookup and lookup[key] != target:
                    raise ValueError(f"Ambiguous route name {key}: {lookup[key]} / {target}")
                lookup[key] = target
    for (area, alias), _ in aliases().items():
        target = canonical_name(alias, area)
        if (area, target) in lookup:
            for variant in (alias, normalize(alias)):
                key = (area, variant)
                if key in lookup and lookup[key] != target:
                    raise ValueError(f"Conflicting route alias {key}")
                lookup[key] = target
    return lookup
