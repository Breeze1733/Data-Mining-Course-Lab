"""通用 POI 后缀兜底。

当目标景区在 `poi_gazetteer.csv` 中没有条目时，用后缀规则在原文中发现候选，
输出低置信实体（`method=generic_suffix` / `area_name_match`），并保留
`fallback=True` 供下游过滤。规则与防误报词表都在 `resources/poi_suffix_rules.csv`。
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from dictionary import Candidate
from schema import SUBTYPES, TYPE_POI, TYPE_TRANSPORT

BOUNDARY_CHARS = set(
    "，。；：！？、（）()【】[]{}<>《》〈〉「」『』\"'“”‘’ \t\n\r|/-—…·*#@&+=~^$%"
)
STOP_CHARS = set(
    "的了在到去从往向是有和与及或然后再就都也很最这那坐乘走看游经过把被给让对为以于其之"
)
ROOT_BLOCKED_AFTER = re.compile(
    r"市|区|县|镇|村|乡|站|机场|高铁|火车站|汽车站|酒店|宾馆|餐厅|学院|大学|医院|公司|大道|路"
)
WORD_CHAR = re.compile(r"[㐀-鿿A-Za-z0-9·]")


@dataclass(frozen=True)
class SuffixRule:
    rule_id: str
    target_type: str
    subtype: str
    suffix: str
    priority: int
    confidence: float
    min_prefix_chars: int
    requires_context: bool
    context_regex: re.Pattern[str] | None
    blocked_prefix: re.Pattern[str] | None
    blocked_after: re.Pattern[str] | None
    blocked_surface: re.Pattern[str] | None
    notes: str = ""


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _pattern(value: Any) -> re.Pattern[str] | None:
    text = str(value or "").strip()
    return re.compile(text) if text else None


def load_suffix_rules(path: Path) -> list[SuffixRule]:
    rules: list[SuffixRule] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            suffix = str(row.get("suffix") or "").strip()
            if not suffix:
                continue
            target_type = str(row.get("target_type") or TYPE_POI).strip()
            subtype = str(row.get("subtype") or "其他").strip()
            if target_type not in {TYPE_POI, TYPE_TRANSPORT}:
                raise ValueError(f"suffix rule {row.get('rule_id')}: 未知 target_type {target_type}")
            if subtype not in SUBTYPES[target_type]:
                raise ValueError(f"suffix rule {row.get('rule_id')}: 未知 subtype {subtype}")
            rules.append(
                SuffixRule(
                    rule_id=str(row.get("rule_id") or suffix),
                    target_type=target_type,
                    subtype=subtype,
                    suffix=suffix,
                    priority=_int(row.get("priority"), 5),
                    confidence=_float(row.get("confidence"), 0.5),
                    min_prefix_chars=_int(row.get("min_prefix_chars"), 2),
                    requires_context=_bool(row.get("requires_context")),
                    context_regex=_pattern(row.get("context_regex")),
                    blocked_prefix=_pattern(row.get("blocked_prefix")),
                    blocked_after=_pattern(row.get("blocked_after")),
                    blocked_surface=_pattern(row.get("blocked_surface")),
                    notes=str(row.get("notes") or ""),
                )
            )
    return rules


def build_root_aliases(area: str, area_config: dict[str, Any] | None = None) -> list[str]:
    """由景区名和配置后缀生成根景区别名，不再假设固定后缀。"""
    area = str(area or "").strip()
    if not area:
        return []
    config = area_config or {}
    suffixes = [str(item) for item in config.get("root_suffixes", []) if str(item)]
    aliases: list[str] = [area]
    already_suffixed = any(area.endswith(suffix) and len(area) > len(suffix) for suffix in suffixes)
    for suffix in suffixes:
        if not already_suffixed:
            candidate = area + suffix
            if candidate not in aliases:
                aliases.append(candidate)
        if area.endswith(suffix) and len(area) > len(suffix):
            base = area[: -len(suffix)]
            if base not in aliases:
                aliases.append(base)
    for alias in config.get("aliases", {}).get(area, []) or []:
        alias = str(alias).strip()
        if alias and alias not in aliases:
            aliases.append(alias)
    ordered = sorted(set(aliases), key=lambda item: (-len(item), item))
    return ordered


class GenericPOIFallback:
    """在无词典景区上生成低置信 POI / 交通候选。"""

    def __init__(
        self,
        rules: Iterable[SuffixRule],
        config: dict[str, Any] | None = None,
        area_config: dict[str, Any] | None = None,
    ) -> None:
        self.rules = list(rules)
        self.config = dict(config or {})
        self.area_config = dict(area_config or {})
        self.rank_base = _int(self.config.get("rank_base"), 20)
        self.default_confidence = _float(self.config.get("confidence"), 0.55)
        self.min_prefix = _int(self.config.get("min_prefix_chars"), 2)
        self.max_prefix = _int(self.config.get("max_prefix_chars"), 8)
        self.use_jieba_boundary = _bool(self.config.get("use_jieba_boundary", True))

    def extract(
        self,
        text: str,
        area: str,
        token_spans: Iterable[tuple[str, int, int]] | None = None,
    ) -> list[Candidate]:
        spans = list(token_spans or [])
        candidates: list[Candidate] = []
        for rule in self.rules:
            for start in self._occurrences(text, rule.suffix):
                candidate = self._build(text, area, rule, start, spans)
                if candidate is not None:
                    candidates.append(candidate)
        return self._dedupe(candidates)

    def _occurrences(self, text: str, suffix: str):
        start = text.find(suffix)
        while start != -1:
            yield start
            start = text.find(suffix, start + 1)

    def _build(
        self,
        text: str,
        area: str,
        rule: SuffixRule,
        suffix_start: int,
        spans: list[tuple[str, int, int]],
    ) -> Candidate | None:
        end = suffix_start + len(rule.suffix)
        min_prefix = rule.min_prefix_chars
        start, prefix_len = self._extend_left(text, suffix_start, self.max_prefix)
        if self.use_jieba_boundary and spans:
            start = self._trim_with_jieba(start, suffix_start, spans)
            prefix_len = suffix_start - start
        if prefix_len < min_prefix:
            return None
        surface = text[start:end]
        if rule.blocked_surface and rule.blocked_surface.fullmatch(surface):
            return None
        prefix_window = text[max(0, start - 2) : suffix_start]
        if rule.blocked_prefix and rule.blocked_prefix.search(prefix_window):
            return None
        after_window = text[end : min(len(text), end + 6)]
        if rule.blocked_after and rule.blocked_after.search(after_window):
            return None
        if rule.requires_context:
            if rule.context_regex is None:
                return None
            context = text[max(0, start - 8) : min(len(text), end + 8)]
            if not rule.context_regex.search(context):
                return None

        confidence = rule.confidence or self.default_confidence
        if rule.target_type == TYPE_TRANSPORT:
            return Candidate(
                start=start,
                end=end,
                surface=surface,
                type=TYPE_TRANSPORT,
                subtype=rule.subtype,
                normalized=surface,
                frequency_key=surface,
                method="generic_suffix",
                rule_id=rule.rule_id,
                confidence=confidence,
                rank=self.rank_base + rule.priority,
                notes="generic_suffix;gazetteer_missing",
                extra={"fallback": True, "fallback_reason": "missing_gazetteer", "suffix": rule.suffix},
            )
        return Candidate(
            start=start,
            end=end,
            surface=surface,
            type=TYPE_POI,
            subtype=rule.subtype,
            normalized=surface,
            frequency_key=surface,
            method="generic_suffix",
            rule_id=rule.rule_id,
            confidence=confidence,
            rank=self.rank_base + rule.priority,
            notes="generic_suffix;gazetteer_missing",
            extra={
                "fallback": True,
                "fallback_reason": "missing_gazetteer",
                "parent_poi": surface,
                "suffix": rule.suffix,
            },
        )

    def _extend_left(self, text: str, suffix_start: int, max_chars: int) -> tuple[int, int]:
        index = suffix_start
        count = 0
        while index > 0 and count < max_chars:
            char = text[index - 1]
            if char in STOP_CHARS or not WORD_CHAR.match(char):
                break
            index -= 1
            count += 1
        return index, count

    def _trim_with_jieba(
        self, start: int, suffix_start: int, spans: list[tuple[str, int, int]]
    ) -> int:
        best = start
        best_len = 1
        for _, token_start, token_end in spans:
            if token_end == suffix_start and start <= token_start < suffix_start:
                length = token_end - token_start
                if length >= 2 and length > best_len:
                    best = token_start
                    best_len = length
        return best

    def _dedupe(self, candidates: list[Candidate]) -> list[Candidate]:
        # 同一结束位置只保留后缀最长的规则（如 观景台 优先于 台）。
        by_end: dict[int, list[Candidate]] = {}
        for candidate in candidates:
            by_end.setdefault(candidate.end, []).append(candidate)
        kept: list[Candidate] = []
        for rows in by_end.values():
            longest_suffix = max(len(str(row.extra.get("suffix", ""))) for row in rows)
            kept.extend(
                row
                for row in rows
                if len(str(row.extra.get("suffix", ""))) == longest_suffix
            )
        unique: dict[tuple[int, int, str], Candidate] = {}
        for candidate in kept:
            key = (candidate.start, candidate.end, candidate.type)
            old = unique.get(key)
            if old is None or candidate.confidence > old.confidence:
                unique[key] = candidate
        ordered = sorted(unique.values(), key=lambda item: (item.start, -item.length, -item.rank))
        selected: list[Candidate] = []
        for candidate in ordered:
            if any(candidate.start < other.end and candidate.end > other.start for other in selected):
                continue
            selected.append(candidate)
        selected.sort(key=lambda item: (item.start, item.end, item.type))
        return selected

    def root_area_candidates(self, text: str, area: str) -> list[Candidate]:
        aliases = build_root_aliases(area, self.area_config)
        if not aliases:
            return []
        pattern = re.compile("|".join(re.escape(alias) for alias in aliases))
        results: list[Candidate] = []
        for match in pattern.finditer(text):
            surface = match.group(0)
            after = text[match.end() : min(len(text), match.end() + 5)]
            if ROOT_BLOCKED_AFTER.search(after):
                continue
            results.append(
                Candidate(
                    start=match.start(),
                    end=match.end(),
                    surface=surface,
                    type=TYPE_POI,
                    subtype="景区",
                    normalized=area,
                    frequency_key=area,
                    method="area_name_match",
                    rule_id="ROOT_AREA_ALIAS",
                    confidence=0.90,
                    rank=60,
                    notes="root_area_alias",
                    extra={"root_area": True, "fallback": True, "parent_poi": area},
                )
            )
        # 同一位置只保留最长别名
        chosen: list[Candidate] = []
        for candidate in sorted(results, key=lambda item: (item.start, -item.length)):
            if any(candidate.start < other.end and candidate.end > other.start for other in chosen):
                continue
            chosen.append(candidate)
        return chosen


__all__ = [
    "GenericPOIFallback",
    "SuffixRule",
    "build_root_aliases",
    "load_suffix_rules",
]
