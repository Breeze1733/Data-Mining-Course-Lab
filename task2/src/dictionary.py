"""词典加载、最长匹配与跨类型重叠消解。

词典文件:
    resources/poi_gazetteer.csv
    resources/transport_lexicon.csv

匹配规则:
    - 同一位置按 (surface 长度降序, priority 降序) 选最长；
    - POI 严格按景区隔离；
    - 具名交通设施（带 linked_poi 的索道/缆车等）优先于其内部的 POI 名；
    - 同一字符区间只保留一个实体，被抑制项写入审计。
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from schema import TYPE_POI, TYPE_TIME, TYPE_TRANSPORT


@dataclass(frozen=True)
class POIEntry:
    poi_id: str
    area: str
    surface: str
    canonical: str
    subtype: str
    parent_poi: str
    source: str
    priority: int
    negative_after: str
    notes: str = ""

    @property
    def pattern(self) -> re.Pattern[str] | None:
        return re.compile(self.negative_after) if self.negative_after else None


@dataclass(frozen=True)
class TransportEntry:
    transport_id: str
    surface: str
    normalized: str
    subtype: str
    priority: int
    requires_verb: bool
    negative_before: str
    negative_after: str
    linked_poi: str
    notes: str = ""

    @property
    def before_pattern(self) -> re.Pattern[str] | None:
        return re.compile(self.negative_before) if self.negative_before else None

    @property
    def after_pattern(self) -> re.Pattern[str] | None:
        return re.compile(self.negative_after) if self.negative_after else None


@dataclass
class Candidate:
    start: int
    end: int
    surface: str
    type: str
    subtype: str
    normalized: str
    frequency_key: str
    method: str
    rule_id: str
    dictionary_id: str = ""
    confidence: float = 0.9
    rank: int = 40
    linked_poi: str = ""
    linked_poi_start: int | None = None
    linked_poi_end: int | None = None
    ambiguous_meridiem: bool = False
    counts_as_time_node: bool = True
    notes: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def length(self) -> int:
        return self.end - self.start


def _int(value: str, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def load_poi_gazetteer(path: Path) -> list[POIEntry]:
    entries: list[POIEntry] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("surface"):
                continue
            entries.append(
                POIEntry(
                    poi_id=str(row.get("poi_id") or ""),
                    area=str(row.get("area") or ""),
                    surface=str(row["surface"]),
                    canonical=str(row.get("canonical") or row["surface"]),
                    subtype=str(row.get("subtype") or "其他"),
                    parent_poi=str(row.get("parent_poi") or row.get("canonical") or row["surface"]),
                    source=str(row.get("source") or ""),
                    priority=_int(row.get("priority", ""), 5),
                    negative_after=str(row.get("negative_after") or ""),
                    notes=str(row.get("notes") or ""),
                )
            )
    return entries


def load_transport_lexicon(path: Path) -> list[TransportEntry]:
    entries: list[TransportEntry] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("surface"):
                continue
            entries.append(
                TransportEntry(
                    transport_id=str(row.get("transport_id") or ""),
                    surface=str(row["surface"]),
                    normalized=str(row.get("normalized") or row["surface"]),
                    subtype=str(row.get("subtype") or "其他"),
                    priority=_int(row.get("priority", ""), 5),
                    requires_verb=_bool(row.get("requires_verb", "")),
                    negative_before=str(row.get("negative_before") or ""),
                    negative_after=str(row.get("negative_after") or ""),
                    linked_poi=str(row.get("linked_poi") or ""),
                    notes=str(row.get("notes") or ""),
                )
            )
    return entries


class Gazetteer:
    def __init__(self, poi_entries: Iterable[POIEntry], transport_entries: Iterable[TransportEntry]):
        self.poi_entries = list(poi_entries)
        self.transport_entries = list(transport_entries)

        self._poi_by_area: dict[str, dict[str, list[POIEntry]]] = {}
        for entry in self.poi_entries:
            self._poi_by_area.setdefault(entry.area, {}).setdefault(entry.surface[0], []).append(entry)
        for area in self._poi_by_area:
            for bucket in self._poi_by_area[area].values():
                bucket.sort(key=lambda item: (-len(item.surface), -item.priority))

        self._transport_by_first: dict[str, list[TransportEntry]] = {}
        for entry in self.transport_entries:
            self._transport_by_first.setdefault(entry.surface[0], []).append(entry)
        for bucket in self._transport_by_first.values():
            bucket.sort(key=lambda item: (-len(item.surface), -item.priority))

    @property
    def areas(self) -> tuple[str, ...]:
        return tuple(sorted(self._poi_by_area))

    def poi_entries_for_area(self, area: str) -> list[POIEntry]:
        return [entry for bucket in self._poi_by_area.get(area, {}).values() for entry in bucket]

    def has_area(self, area: str) -> bool:
        return bool(self._poi_by_area.get(area))

    def area_entry_count(self, area: str) -> int:
        return sum(len(bucket) for bucket in self._poi_by_area.get(area, {}).values())

    def area_surfaces(self, area: str) -> set[str]:
        return {entry.surface for entry in self.poi_entries_for_area(area)}

    def _blocked(self, text: str, start: int, end: int, after: re.Pattern[str] | None) -> bool:
        if after is None:
            return False
        following = text[end : min(len(text), end + 8)]
        return bool(after.search(following))

    def iter_poi_matches(self, text: str, area: str) -> list[Candidate]:
        buckets = self._poi_by_area.get(area, {})
        results: list[Candidate] = []
        position = 0
        while position < len(text):
            matched: POIEntry | None = None
            for entry in buckets.get(text[position], ()):
                if not text.startswith(entry.surface, position):
                    continue
                if self._blocked(text, position, position + len(entry.surface), entry.pattern):
                    continue
                matched = entry
                break
            if matched is None:
                position += 1
                continue
            end = position + len(matched.surface)
            is_coarse = matched.subtype in {"景区", "景区片区"}
            rank = (50 if is_coarse else 55) + matched.priority
            results.append(
                Candidate(
                    start=position,
                    end=end,
                    surface=text[position:end],
                    type=TYPE_POI,
                    subtype=matched.subtype,
                    normalized=matched.canonical,
                    frequency_key=matched.canonical,
                    method="dictionary_longest_match",
                    rule_id="POI_GAZETTEER",
                    dictionary_id=matched.poi_id,
                    confidence=0.98 if not is_coarse else 0.94,
                    rank=rank,
                    notes=matched.source,
                    extra={"parent_poi": matched.parent_poi, "canonical": matched.canonical},
                )
            )
            position = end
        return results

    def iter_transport_matches(self, text: str) -> list[Candidate]:
        results: list[Candidate] = []
        position = 0
        while position < len(text):
            matched: TransportEntry | None = None
            for entry in self._transport_by_first.get(text[position], ()):
                if not text.startswith(entry.surface, position):
                    continue
                end = position + len(entry.surface)
                before = text[max(0, position - 4) : position]
                if entry.before_pattern and entry.before_pattern.search(before):
                    continue
                if self._blocked(text, position, end, entry.after_pattern):
                    continue
                matched = entry
                break
            if matched is None:
                position += 1
                continue
            end = position + len(matched.surface)
            is_named = bool(matched.linked_poi)
            results.append(
                Candidate(
                    start=position,
                    end=end,
                    surface=text[position:end],
                    type=TYPE_TRANSPORT,
                    subtype=matched.subtype,
                    normalized=matched.normalized,
                    frequency_key=matched.normalized,
                    method="dictionary_longest_match",
                    rule_id="TRANSPORT_FACILITY" if is_named else "TRANSPORT_LEXICON",
                    dictionary_id=matched.transport_id,
                    confidence=0.96 if is_named else 0.92,
                    rank=(58 if is_named else 45) + matched.priority,
                    linked_poi=matched.linked_poi,
                    notes=matched.notes,
                )
            )
            position = end
        return results

    def resolve_overlaps(
        self, candidates: Iterable[Candidate]
    ) -> tuple[list[Candidate], list[Candidate]]:
        """按起点、长度、rank 贪心选取互不重叠的实体。"""
        unique: dict[tuple[int, int, str], Candidate] = {}
        for candidate in candidates:
            key = (candidate.start, candidate.end, candidate.type)
            old = unique.get(key)
            if old is None or candidate.confidence > old.confidence:
                unique[key] = candidate
        ordered = sorted(
            unique.values(),
            key=lambda item: (item.start, -item.length, -item.rank),
        )
        selected: list[Candidate] = []
        suppressed: list[Candidate] = []
        for candidate in ordered:
            if any(
                candidate.start < other.end and candidate.end > other.start for other in selected
            ):
                suppressed.append(candidate)
            else:
                selected.append(candidate)
        selected.sort(key=lambda item: (item.start, item.end, item.type))
        return selected, suppressed


def jieba_boundary_report(gazetteer: Gazetteer, text: str, limit: int = 0) -> list[str]:
    """用 jieba 自定义词典做边界校验（不改变最终实体边界）。

    返回 jieba.search 分词中包含词典词的 token 列表，供报告说明 jieba 的用途。
    """
    try:
        import jieba
    except ImportError:
        return []
    words = {entry.surface for entry in gazetteer.poi_entries}
    words.update(entry.surface for entry in gazetteer.transport_entries)
    for word in words:
        jieba.add_word(word, freq=100000, tag="ns")
    tokens = [
        token
        for token, start, end in jieba.tokenize(text, mode="search", HMM=False)
        if token in words
    ]
    return tokens[:limit] if limit else tokens


__all__ = [
    "Candidate",
    "Gazetteer",
    "POIEntry",
    "TransportEntry",
    "TYPE_POI",
    "TYPE_TRANSPORT",
    "TYPE_TIME",
    "jieba_boundary_report",
    "load_poi_gazetteer",
    "load_transport_lexicon",
]
