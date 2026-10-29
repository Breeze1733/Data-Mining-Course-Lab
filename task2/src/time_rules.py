"""时间节点识别：正则、区间合并与归一化。

口径（用户已确认）:
    - 时刻/时刻区间/时段/日期/日期区间/月份区间/相对日/季节/节日/重复 属于时间节点；
    - 时长（2小时/半小时/个来小时）保留为 TIME 子类，但 counts_as_time_node=False，
      词频与图表单独分列，供项目 3 的停留时长复用；
    - 距离、价格、一日游、单独一行的 00:00 视频时间戳不进入 TIME。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from dictionary import Candidate
from offsets import trim_span
from schema import TYPE_TIME

PERIODS = ("凌晨", "清晨", "早晨", "早上", "上午", "中午", "正午", "下午", "傍晚", "晚上", "夜里", "夜间")
PERIOD_RE = re.compile("|".join(PERIODS))
CLOCK_COLON_RE = re.compile(r"^(\d{1,2})\s*[:：]\s*(\d{1,2})$")
CLOCK_DIAN_RE = re.compile(r"^([一二两三四五六七八九十\d]{1,3})\s*点\s*(半|[0-5]?\d\s*分|多)?$")
DATE_RE = re.compile(
    r"(?:(?P<year>(?:19|20)\d{2})\s*年\s*)?(?P<month>1[0-2]|0?[1-9])\s*月\s*"
    r"(?P<day>3[01]|[12]\d|0?[1-9])\s*[日号]"
)
DATE_ISO_RE = re.compile(r"^(?P<year>(?:19|20)\d{2})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})$")
RANGE_SEP_RE = re.compile(r"\s*(?:-|—|–|~|～|至|到)\s*")

CN_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def cn_to_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if value == "半":
        return 0
    if "百" in value:
        left, _, right = value.partition("百")
        hundreds = CN_DIGITS.get(left, 1) if left else 1
        rest = cn_to_int(right) if right else 0
        return hundreds * 100 + (rest or 0)
    if "十" in value:
        left, _, right = value.partition("十")
        tens = CN_DIGITS.get(left, 1) if left else 1
        ones = CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    if len(value) == 1 and value in CN_DIGITS:
        return CN_DIGITS[value]
    return None


def _split_period(surface: str) -> tuple[str, str]:
    surface = surface.strip()
    match = PERIOD_RE.match(surface)
    if not match:
        return "", surface
    return match.group(0), surface[match.end() :].strip()


def _apply_period(hour: int, period: str) -> tuple[int, bool, str]:
    """返回 (24h hour, ambiguous, note)。"""
    if not period:
        return hour, hour <= 12, ""
    note = ""
    if period in {"凌晨"}:
        if hour == 12:
            hour = 0
            note = "凌晨12点按00:00处理"
    elif period in {"清晨", "早晨", "早上", "上午"}:
        pass
    elif period in {"中午", "正午"}:
        if 1 <= hour <= 3:
            hour += 12
    elif period in {"下午", "傍晚"}:
        if hour < 12:
            hour += 12
    elif period in {"晚上", "夜里", "夜间"}:
        if hour < 12:
            hour += 12
        elif hour == 12:
            hour = 0
            note = "晚上12点按次日00:00处理"
    return hour % 24, False, note


def normalize_clock(surface: str) -> tuple[str, bool, str]:
    period, rest = _split_period(surface)
    rest = rest.replace(" ", "")

    colon = CLOCK_COLON_RE.match(rest)
    if colon:
        hour, minute = int(colon.group(1)), int(colon.group(2))
        hour, ambiguous, note = _apply_period(hour, period)
        return f"{hour:02d}:{minute:02d}", ambiguous, note

    dian = CLOCK_DIAN_RE.match(rest)
    if dian:
        hour = cn_to_int(dian.group(1))
        if hour is None:
            return surface.strip(), True, ""
        minute = 0
        tail = (dian.group(2) or "").strip()
        if tail == "半":
            minute = 30
        elif tail and tail != "多":
            digits = re.sub(r"\D", "", tail)
            if digits:
                minute = int(digits)
        note = "约" if tail == "多" else ""
        hour, ambiguous, period_note = _apply_period(hour, period)
        if period_note:
            note = f"{note};{period_note}".strip(";")
        return f"{hour:02d}:{minute:02d}", ambiguous, note

    return surface.strip(), True, ""


def _inherit_period(left: str, right: str) -> str:
    left_period, _ = _split_period(left)
    right_period, right_rest = _split_period(right)
    if left_period and not right_period:
        return left_period + right_rest
    return right


def normalize_clock_range(surface: str) -> tuple[str, bool, str]:
    parts = RANGE_SEP_RE.split(surface, maxsplit=1)
    if len(parts) != 2:
        value, ambiguous, note = normalize_clock(surface)
        return value, ambiguous, note
    left, right = parts
    right = _inherit_period(left, right)
    left_value, left_ambiguous, left_note = normalize_clock(left)
    right_value, right_ambiguous, right_note = normalize_clock(right)
    notes = ";".join(item for item in (left_note, right_note) if item)
    return f"{left_value}-{right_value}", left_ambiguous or right_ambiguous, notes


def normalize_date(surface: str) -> str:
    text = surface.replace(" ", "")
    iso = DATE_ISO_RE.match(text)
    if iso:
        return f"{int(iso.group('year')):04d}-{int(iso.group('month')):02d}-{int(iso.group('day')):02d}"
    match = DATE_RE.search(text)
    if match:
        year = match.group("year")
        month = int(match.group("month"))
        day = int(match.group("day"))
        if year:
            return f"{int(year):04d}-{month:02d}-{day:02d}"
        return f"{month:02d}-{day:02d}"
    return text


def normalize_date_range(surface: str) -> str:
    parts = RANGE_SEP_RE.split(surface, maxsplit=1)
    if len(parts) != 2:
        return normalize_date(surface)
    left = normalize_date(parts[0])
    right = normalize_date(parts[1])
    # “5月6日-9日”：右端只有日，沿用左端月份
    left_match = re.match(r"(?P<month>\d{2})-(?P<day>\d{2})$", left)
    right_day = re.search(r"(?P<day>3[01]|[12]\d|0?[1-9])\s*[日号]", parts[1])
    if left_match and right_day and re.fullmatch(r"\d{1,2}\s*[日号]", parts[1].strip()):
        right = f"{left_match.group('month')}-{int(right_day.group('day')):02d}"
    return f"{left}~{right}"


def normalize_month_range(surface: str) -> str:
    text = surface.replace(" ", "")
    if "-" in text or "~" in text or "～" in text or "至" in text:
        parts = RANGE_SEP_RE.split(text, maxsplit=1)
        if len(parts) == 2:
            left = re.sub(r"[月]", "", parts[0])
            right = re.sub(r"[月]", "", parts[1])
            return f"{int(cn_to_int(left) or left):02d}-{int(cn_to_int(right) or right):02d}月"
    months: list[int] = []
    for token in re.split(r"[、,，]", text.replace("月", "")):
        value = cn_to_int(token)
        if value is not None:
            months.append(value)
    if months:
        if len(months) == 1:
            return f"{months[0]:02d}月"
        return "-".join(f"{month:02d}" for month in months) + "月"
    return text


def normalize_relative_day(surface: str) -> str:
    text = surface.replace(" ", "")
    match = re.match(r"^第([一二三四五六七八九十百\d]{1,3})[天日]$", text)
    if match:
        value = cn_to_int(match.group(1))
        return f"第{value}天" if value is not None else text
    match = re.match(r"^(?:Day|D)(\d{1,2})$", text, re.IGNORECASE)
    if match:
        return f"第{int(match.group(1))}天"
    if text in {"当天", "当日"}:
        return "当天"
    return text


def normalize_period(surface: str) -> str:
    text = surface.strip()
    mapping = {"早上": "上午", "早晨": "上午", "正午": "中午"}
    return mapping.get(text, text)


def normalize_duration(surface: str) -> str:
    text = surface.replace(" ", "")
    if text in {"个来小时", "个把小时"}:
        return "约1小时"
    if text in {"一个多小时", "1个多小时"}:
        return ">1小时"
    if text == "两个半小时":
        return "2.5小时"
    match = re.match(
        r"^(?P<num>[一二两三四五六七八九十百半\d.]+)(?P<ge>个)?(?P<unit>半小时|小时|钟头|分钟|天|晚|个月)$",
        text,
    )
    if not match:
        return text
    num_text = match.group("num")
    unit = match.group("unit")
    if num_text == "半":
        mapping = {"小时": "0.5小时", "钟头": "0.5小时", "天": "0.5天", "晚": "0.5晚", "个月": "0.5个月"}
        return mapping.get(unit, text)
    if unit == "半小时":
        value = cn_to_int(num_text)
        if value is None:
            return text
        return f"{value + 0.5:g}小时"
    value = cn_to_int(num_text)
    if value is None:
        return text
    unit = "小时" if unit == "钟头" else unit
    return f"{value}{unit}"


def _normalize(surface: str, subtype: str, rule_id: str) -> tuple[str, bool, str, bool]:
    """返回 (normalized, ambiguous, notes, counts_as_time_node)。"""
    if subtype == "时刻":
        value, ambiguous, notes = normalize_clock(surface)
        return value, ambiguous, notes, True
    if subtype == "时刻区间":
        value, ambiguous, notes = normalize_clock_range(surface)
        return value, ambiguous, notes, True
    if subtype == "日期":
        return normalize_date(surface), False, "", True
    if subtype == "日期区间":
        return normalize_date_range(surface), False, "", True
    if subtype == "月份区间":
        return normalize_month_range(surface), False, "", True
    if subtype == "相对日":
        return normalize_relative_day(surface), False, "", True
    if subtype == "时段":
        return normalize_period(surface), False, "", True
    if subtype == "时长":
        return normalize_duration(surface), False, "", False
    return surface.strip(), False, "", True


@dataclass
class TimeRules:
    version: str
    patterns: list[dict]
    exclusions: list[dict]

    @classmethod
    def load(cls, path: Path) -> "TimeRules":
        config = json.loads(path.read_text(encoding="utf-8"))
        patterns = []
        for item in config.get("patterns", []):
            patterns.append(
                {
                    "id": item["id"],
                    "subtype": item["subtype"],
                    "priority": int(item.get("priority", 50)),
                    "regex": re.compile(item["regex"], re.IGNORECASE),
                }
            )
        exclusions = []
        for item in config.get("exclusions", []):
            exclusions.append(
                {
                    "id": item["id"],
                    "reason": item.get("reason", ""),
                    "regex": re.compile(item["regex"], re.IGNORECASE),
                }
            )
        return cls(str(config.get("version", "time")), patterns, exclusions)

    def _exclusion_spans(self, text: str) -> list[tuple[int, int, str]]:
        spans: list[tuple[int, int, str]] = []
        for item in self.exclusions:
            for match in item["regex"].finditer(text):
                spans.append((match.start(), match.end(), item["reason"]))
        return spans

    def extract(self, text: str) -> list[Candidate]:
        exclusion_spans = self._exclusion_spans(text)
        candidates: list[Candidate] = []
        for pattern in self.patterns:
            for match in pattern["regex"].finditer(text):
                start, end = trim_span(text, match.start(), match.end())
                if start >= end:
                    continue
                if any(ex_start <= start and end <= ex_end for ex_start, ex_end, _ in exclusion_spans):
                    continue
                surface = text[start:end]
                # “一点/半点”常是副词（一点也不、半点办法），裸用时按非时间处理；
                # 带时段前缀的“下午一点”仍保留。
                if pattern["id"] == "TIME_CLOCK_CN" and surface.replace(" ", "") in {"一点", "半点"}:
                    continue
                normalized, ambiguous, notes, counts_as_time_node = _normalize(
                    surface, pattern["subtype"], pattern["id"]
                )
                if not normalized:
                    continue
                confidence = 0.99
                if pattern["subtype"] == "时段":
                    confidence = 0.9
                elif pattern["subtype"] in {"季节", "节日", "重复"}:
                    confidence = 0.92
                elif pattern["subtype"] == "时长":
                    confidence = 0.95
                candidates.append(
                    Candidate(
                        start=start,
                        end=end,
                        surface=surface,
                        type=TYPE_TIME,
                        subtype=pattern["subtype"],
                        normalized=normalized,
                        frequency_key=normalized,
                        method="regex_range"
                        if pattern["subtype"] in {"时刻区间", "日期区间", "月份区间"}
                        else "regex",
                        rule_id=pattern["id"],
                        confidence=confidence,
                        rank=60 + min(pattern["priority"], 100) // 10,
                        ambiguous_meridiem=ambiguous,
                        counts_as_time_node=counts_as_time_node,
                        notes=notes,
                    )
                )

        # 同一 span 去重；再做时间内部的区间/嵌套消解
        unique: dict[tuple[int, int, str], Candidate] = {}
        for candidate in candidates:
            key = (candidate.start, candidate.end, candidate.subtype)
            old = unique.get(key)
            if old is None or candidate.confidence > old.confidence:
                unique[key] = candidate
        ordered = sorted(
            unique.values(), key=lambda item: (item.start, -item.length, -item.rank)
        )
        selected: list[Candidate] = []
        for candidate in ordered:
            if any(
                candidate.start < other.end and candidate.end > other.start
                for other in selected
            ):
                continue
            selected.append(candidate)
        selected.sort(key=lambda item: (item.start, item.end))
        return selected


__all__ = [
    "TimeRules",
    "cn_to_int",
    "normalize_clock",
    "normalize_clock_range",
    "normalize_date",
    "normalize_date_range",
    "normalize_duration",
    "normalize_month_range",
    "normalize_period",
    "normalize_relative_day",
]
