"""Share the configurable rules with the record-oriented task3–7 interface.

The seed preserves curated aliases and out-of-area POIs. Root scenic names are
excluded from the downstream POI layer. Offsets always address clean_content.
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

from dictionary import Gazetteer, POIEntry, TransportEntry, load_poi_gazetteer, load_transport_lexicon
from time_rules import TimeRules
from entity_identity import canonical_name

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "resources"


def refined_dictionary():
    data = json.loads((RES / "domain_seed.json").read_text(encoding="utf-8"))
    pois = {e["name"]: {**e, "canonical": canonical_name(e["canonical"])} for e in data["poi"]}
    for entry in load_poi_gazetteer(RES / "poi_gazetteer.csv"):
        if entry.subtype == "景区":
            continue
        if entry.surface not in pois:
            pois[entry.surface] = {
                "name": entry.surface, "entity_type": "景点POI",
                "subtype": "景点", "fine_subtype": entry.subtype, "scenic_areas": [entry.area],
                "canonical": entry.canonical, "source": "merged_gazetteer",
            }
    transport = {e["name"]: dict(e) for e in data["transport"]}
    # Unspecified actions remain actions, rather than inventing a vehicle.
    for entry in load_transport_lexicon(RES / "transport_lexicon.csv"):
        if entry.surface in {"乘车", "坐车"}:
            continue
        transport.setdefault(entry.surface, {
            "name": entry.surface, "entity_type": "交通方式", "subtype": entry.subtype,
            "scenic_areas": ["通用"], "canonical": entry.normalized, "source": "merged_lexicon",
        })
    return list(pois.values()) + list(transport.values()), set(data["domain_stopwords"]), True


class DictMatcher:
    def __init__(self, entries: list[dict], stopwords: set[str]):
        self.entries = entries
        self.stopwords = stopwords
        self.by_name = {e["name"]: e for e in entries}
        cloud = {(e.area, e.surface): e for e in load_poi_gazetteer(RES / "poi_gazetteer.csv")}
        pois = []
        for item in entries:
            if item["entity_type"] != "景点POI":
                continue
            for area in item["scenic_areas"]:
                template = cloud.get((area, item["name"]))
                if template:
                    entry = replace(template, canonical=item["canonical"])
                else:
                    entry = POIEntry("DOMAIN-" + item["name"], area, item["name"],
                                     item["canonical"], "其他", "", "domain_seed", 10, "")
                pois.append(entry)
        transports = []
        cloud_transport = {e.surface: e for e in load_transport_lexicon(RES / "transport_lexicon.csv")}
        for item in entries:
            if item["entity_type"] != "交通方式":
                continue
            entry = cloud_transport.get(item["name"])
            if entry is None:
                entry = TransportEntry("DOMAIN-" + item["name"], item["name"],
                                       item["canonical"], "其他", 8, False, "", "", "", "domain_seed")
            # Keep the local compound-word guards, including words the cloud missed.
            guards = {"步行": "街", "登山": "杖|鞋|口|服|包|靴", "地铁": "站|口"}
            extra = guards.get(entry.surface, "")
            if extra:
                entry = replace(entry, negative_after="|".join(filter(None, [entry.negative_after, extra])))
            transports.append(entry)
        self.gazetteer = Gazetteer(pois, transports)
        self.areas = sorted({e.area for e in pois})

    def find(self, text: str, scenic: str | None = None) -> list[dict]:
        areas = ([scenic] if scenic in self.areas else []) + [a for a in self.areas if a != scenic]
        candidates = []
        for area in areas:
            candidates.extend(self.gazetteer.iter_poi_matches(text, area))
        candidates.extend(self.gazetteer.iter_transport_matches(text))
        candidates = [e for e in candidates if not any(
            word.startswith(e.surface) and text.startswith(word, e.start)
            for word in self.stopwords
        )]
        selected, _ = self.gazetteer.resolve_overlaps(candidates)
        found = []
        for candidate in selected:
            entry = self.by_name[candidate.surface]
            in_scenic = scenic is None or scenic in entry.get("scenic_areas", [])
            if entry["entity_type"] == "交通方式":
                in_scenic = True
            found.append({
                "text": candidate.surface, "type": candidate.type,
                "subtype": entry["subtype"], "canonical": entry["canonical"],
                "start": candidate.start, "end": candidate.end, "in_scenic": in_scenic,
                "method": candidate.method, "rule_id": candidate.rule_id,
                "counts_as_time_node": candidate.counts_as_time_node,
            })
        return found


_time_rules = None


def contextual_facility_places(text: str, scenic: str) -> list[dict]:
    """Recover a location antecedent from explicit named-facility proximity.

    A hotel alone is not a scenic POI. A clause such as 北海宾馆附近 explicitly
    locates the narration, so coreference may use the associated named place.
    This inference is kept out of entity frequency and route extraction.
    """
    data = json.loads((RES / "domain_seed.json").read_text(encoding="utf-8"))
    found = []
    for entry in data["poi"]:
        if scenic not in entry["scenic_areas"] or entry["subtype"] != "景点":
            continue
        pattern = re.escape(entry["name"]) + r"(?:宾馆|饭店|酒店)(?:的)?(?:附近|周边|旁边)"
        for match in re.finditer(pattern, text):
            found.append({"text": entry["name"], "type": "景点POI", "subtype": "景点",
                          "canonical": entry["canonical"], "start": match.start(),
                          "end": match.start() + len(entry["name"]),
                          "method": "explicit_facility_proximity"})
    return found


def time_entities(text: str) -> list[dict]:
    global _time_rules
    if _time_rules is None:
        _time_rules = TimeRules.load(RES / "time_rules.json")
    candidates, _ = Gazetteer([], []).resolve_overlaps(_time_rules.extract(text))
    return [{"text": c.surface, "type": c.type, "subtype": c.subtype,
             "start": c.start, "end": c.end, "canonical": c.surface,
             "normalized": c.normalized, "in_scenic": True,
             "counts_as_time_node": c.counts_as_time_node,
             "method": c.method, "rule_id": c.rule_id} for c in candidates]


def resolve_record_entities(entities: list[dict]) -> list[dict]:
    """A duration regex must not consume the first character of a known POI."""
    pois = [e for e in entities if e["type"] == "景点POI"]
    return [e for e in entities if not (
        e["type"] == "时间节点" and e["subtype"] == "时长" and any(
            e["start"] < poi["end"] and e["end"] > poi["start"] for poi in pois
        )
    )]
