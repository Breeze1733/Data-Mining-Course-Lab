"""Experiment 3: structured parsing of official routes and time-hierarchy construction.

Input: task1/data/raw/official_routes.jsonl (46 official route branches)
       task2/output/exp2/{entity_dictionary.json, entities_refined.jsonl} (dictionary and entities)
Output: task3/output/
       route_format_analysis.json   format-pattern analysis
       name_normalization.json      name-normalization rules and application statistics
       parsed_routes.jsonl          structured route per entry (steps/narrative segments/periods/POIs/transport/time)
Usage: python src/parse_routes.py (inside the task1 venv, -X utf8)
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK2 = ROOT.parent / "task2"
OUT = ROOT / "output"

if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


# Rule 1: dictionary canonical (清晏舫→石舫, 诺日朗游客中心→诺日朗中心, etc.)
# Rule 2: geographic-qualifier stripping (黄山南大门/黄山风景区→南大门; strip the “XX景区” suffix)
# Rule 3: same name, different places (五彩池) keep the scenic-area qualifier and are not forcibly merged
# Rules are published by task2 in entity_dictionary.json; task3 never imports task2 code.
_DICT_PATH = TASK2 / "output/exp2/entity_dictionary.json"
if not _DICT_PATH.exists():
    raise SystemExit("缺少 entity_dictionary.json；请先运行 task2/src/export_dictionary.py")
_DICT = json.loads(_DICT_PATH.read_text(encoding="utf-8"))
for _key in ("aliases", "normalization", "poi_lookup"):
    if _key not in _DICT:
        raise SystemExit(f"entity_dictionary.json 缺少 {_key}；请先运行 task2/src/export_dictionary.py")
_UNSCOPED: dict[str, set[str]] = {}
for _row in _DICT["aliases"]:
    _UNSCOPED.setdefault(_row["alias"], set()).add(_row["canonical"])
_NORMALIZATION = _DICT["normalization"]
_SUFFIX_RE = re.compile("(?:" + "|".join(map(re.escape, _NORMALIZATION["suffixes"])) + ")$")


def normalize(name: str) -> str:
    targets = _UNSCOPED.get(name, set())
    if len(targets) == 1:
        name = next(iter(targets))
    for prefix, short in _NORMALIZATION["prefix_map"].items():
        if name.startswith(prefix) and name != prefix:
            return normalize(short + name[len(prefix):])
    return _SUFFIX_RE.sub("", name)


CHAIN_SEP = re.compile(r"→|➝|➞|⇒|➤|─+|—+|–+")
PAREN_RE = re.compile(r"[（(]([^()]*)[）)]")
TIME_RANGE_RE = re.compile(
    r"(?:清晨|早上|上午|中午|下午|傍晚|晚上|夜里|深夜|凌晨)?\d{1,2}[点:：]\d{1,2}(?:分)?\s*[-—~～至]\s*\d{1,2}[点:：]\d{1,2}(?:分)?")
DUR_RE = re.compile(r"(?:约|大概|将近|近)?\d+(?:\.\d+)?\s*(?:个)?(?:小时|钟头|分钟)|半小时")
PERIOD_WORDS = ("清晨", "早上", "上午", "中午", "下午", "傍晚", "晚上", "夜里", "深夜", "凌晨", "全天")
DAY_MARK = re.compile(r"[【\[]\s*(第[一二三四五六七八九十\d]+[日天]|Day\s*\d+)\s*[】\]]|第([一二三四五六七八九十\d]+)天|Day\s*(\d+)")
PERIOD_MARK = re.compile(r"[【\[]\s*(上午|中午|下午|晚上|清晨|傍晚|全天)\s*[】\]]|(上午|中午|下午|晚上|清晨|傍晚)[:：]")
# Composite day+period marker ("【第一天·晚上】") -- matched as a whole so both the day and the period are captured
# Non-route-context clause guard -- POIs of 未去/放弃 (not visited / given up), others' itineraries, or background listings are not steps
NON_ROUTE_CLAUSE_RE = re.compile(
    r"未(?:去|能前往|能成行|开放)|没有?去|没能(?:前往|到达|成行)|放弃|取消了?|原计划"
    r"|本来(?:想|打算|计划)|计划去"
    r"|(?:很多人|大家|游客们?|不少人|其他游客)都?(?:去|前往|选择)"
    r"|有[^，。；]{1,18}等")

DAY_PERIOD_MARK = re.compile(
    r"[【\[]\s*(第[一二三四五六七八九十\d]+[日天])\s*[·.、]\s*(上午|中午|下午|晚上|清晨|傍晚)\s*[】\]]")
STATION_MARK = re.compile(r"第([一二三四五六七八九十\d]+)站[:：]")
STOP_TOKEN = re.compile(r"^(?:反之也可|以此类推|等等|依此类推)$")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def hour_of(time_range: str):
    match = re.match(r"(\d{1,2})[:：点](\d{1,2})", time_range or "")
    return int(match.group(1)) if match else None


def period_from_hour(hour: int) -> str:
    return ("上午" if 5 <= hour < 11 else "中午" if 11 <= hour < 13 else
            "下午" if 13 <= hour < 18 else "晚上" if 18 <= hour < 24 else "未标注时段")


def infer_periods(steps: list[dict]) -> None:
    """Fill a missing period from the clock start; later steps inherit the last known period."""
    current = None
    for step in steps:
        if not step["period"] and step["time_range"] and (hour := hour_of(step["time_range"])) is not None:
            step["period"] = period_from_hour(hour)
        current = step["period"] or current
        step["period"] = step["period"] or current


def repair_spans(entries: list[dict], raw_text: str) -> None:
    """Recompute every span from the step text itself.

    The parser normalizes labels/arrows and sometimes joins clauses, so its
    incremental offsets can drift. Exact text search is authoritative: a unique
    occurrence wins, multiple occurrences pick the one nearest the old offset
    (or the previous entry), and non-contiguous synthesized text is marked
    ``not_contiguous`` with ``span=None`` instead of pointing at the wrong place.
    """
    last_end = 0
    for entry in entries:
        text = entry.get("text") or ""
        if not text:
            entry["span"], entry["span_status"] = None, "empty_text"
            continue
        positions = [match.start() for match in re.finditer(re.escape(text), raw_text)]
        if not positions:
            entry["span"], entry["span_status"] = None, "not_contiguous"
            continue
        anchor = entry.get("span")[0] if entry.get("span") else last_end
        start = min(positions, key=lambda position: abs(position - anchor))
        entry["span"] = [start, start + len(text)]
        entry["span_status"] = "exact"
        last_end = start + len(text)


def split_with_spans(text: str, pattern: re.Pattern) -> list[tuple[str, int, int]]:
    """pattern.split(text) with each part's offsets, preserving empty parts."""
    parts = []
    last = 0
    for match in pattern.finditer(text):
        parts.append((text[last:match.start()], last, match.start()))
        last = match.end()
    parts.append((text[last:], last, len(text)))
    return parts


def _strip_offsets(text: str, offsets: list[int | None], chars: str | None = None):
    """Reproduce str.strip(chars) while keeping each surviving character's raw offset."""
    left, right = 0, len(text)
    if chars is None:
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
    else:
        while left < right and text[left] in chars:
            left += 1
        while right > left and text[right - 1] in chars:
            right -= 1
    return text[left:right], offsets[left:right]


def _remove_patterns(text: str, offsets: list[int | None], patterns) -> tuple[str, list[int | None]]:
    """Remove every regex match, keeping surviving characters' offsets."""
    keep = [True] * len(text)
    for pattern in patterns:
        for match in pattern.finditer(text):
            for i in range(match.start(), match.end()):
                keep[i] = False
    return ("".join(text[i] for i in range(len(text)) if keep[i]),
            [offsets[i] for i in range(len(text)) if keep[i]])


def _clause_filter(text: str, offsets: list[int | None]) -> tuple[str, list[int | None]]:
    """Apply NON_ROUTE_CLAUSE_RE clause filtering while carrying offsets."""
    parts = split_with_spans(text, re.compile(r"[，,]"))
    kept = [(part, start, end) for part, start, end in parts
            if part.strip() and not NON_ROUTE_CLAUSE_RE.search(part)]
    if not kept:
        return "", []
    new_offsets: list[int | None] = []
    for index, (_, start, end) in enumerate(kept):
        if index:
            new_offsets.append(None)  # synthesized "，"
        new_offsets.extend(offsets[start:end])
    return "，".join(part for part, _, _ in kept), new_offsets


def _compress_offsets(offsets: list[int | None]) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    start = prev = None
    for offset in offsets:
        if offset is None:
            if start is not None:
                intervals.append((start, prev + 1))
            start = prev = None
            continue
        if start is None:
            start = offset
        elif offset != prev + 1:
            intervals.append((start, prev + 1))
            start = offset
        prev = offset
    if start is not None:
        intervals.append((start, prev + 1))
    return intervals


def _core_intervals(token: str, offsets: list[int | None]) -> list[tuple[int, int]]:
    """Raw intervals of PAREN_RE.sub('', token).strip(' 　,，。;；')."""
    keep = [True] * len(token)
    for match in PAREN_RE.finditer(token):
        for i in range(match.start(), match.end()):
            keep[i] = False
    core = "".join(token[i] for i in range(len(token)) if keep[i])
    core_offsets = [offsets[i] for i in range(len(token)) if keep[i]]
    _, stripped_offsets = _strip_offsets(core, core_offsets, " 　,，。;；")
    return _compress_offsets(stripped_offsets)


def _paren_intervals(token: str, offsets: list[int | None]) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    for match in PAREN_RE.finditer(token):
        intervals.extend(_compress_offsets(offsets[match.start(1):match.end(1)]))
    return intervals


def _inside(entity: dict, intervals: list[tuple[int, int]]) -> bool:
    return any(start <= entity["start"] and entity["end"] <= end for start, end in intervals)


def step_kind(step: dict) -> str:
    """A step label derived from its actual signals, not from a default."""
    if not step["pois"] and step["transport"]:
        return "移动事件"
    if step["lodging"]:
        return "住宿停留"
    if step["pois"] or step.get("station_tag"):
        return "景点停留"
    return "说明"


def classify_format(text: str, ordered: bool) -> str:
    if not ordered:
        return "theme_prose"
    arrows = len(CHAIN_SEP.findall(text))
    has_kv_route = bool(re.search(r"活动路线[:：]", text))
    has_station = bool(STATION_MARK.search(text))
    has_number = bool(re.search(r"^\s*\d+[.、）)]", text, re.M))
    if has_kv_route:
        return "kv_route_line"
    if has_station:
        return "numbered_stops"
    if arrows >= 3:
        return "arrow_chain"
    if has_number:
        return "numbered_list"
    return "prose"


class RouteParser:
    def __init__(self, annotations: dict[str, list[dict]]):
        self.annotations = annotations
        self._branch_entities: list[dict] = []
        self._raw = ""
        self._cursor = 0

    def _locate_offsets(self, token: str) -> list[int | None]:
        """Fallback raw offsets for tokens whose span was not tracked."""
        index = self._raw.find(token, self._cursor)
        if index < 0:
            index = self._raw.find(token)
        if index < 0:
            return [None] * len(token)
        self._cursor = index + len(token)
        return list(range(index, index + len(token)))

    def annotate(self, token: str, scenic: str | None = None,
                 offsets: list[int | None] | None = None) -> dict:
        """Parse a single chain node: POIs, transport, time, and notes."""
        note_parts = PAREN_RE.findall(token)
        core = PAREN_RE.sub("", token).strip(" 　,，。;；")
        if offsets is None:
            offsets = self._locate_offsets(token)
        core_spans = _core_intervals(token, offsets)
        paren_spans = _paren_intervals(token, offsets)
        pois, transports = [], []
        for e in self._branch_entities:
            if not _inside(e, core_spans):
                continue
            if e["type"] == "景点POI":
                if scenic is not None and not e.get("in_scenic", True):
                    continue  # peripheral landmarks (logistics mentions such as 汤口镇/黄龙) are not route steps
                pois.append({"name": e["canonical"], "mention": e["text"],
                             "normalized": normalize(e["canonical"])})
            elif e["type"] == "交通方式":
                transports.append(e["canonical"])
        # Transport/time information inside parentheses
        paren_text = " ".join(note_parts)
        for e in self._branch_entities:
            if (e["type"] == "交通方式" and e["canonical"] not in transports
                    and _inside(e, paren_spans)):
                transports.append(e["canonical"])
        tr = TIME_RANGE_RE.search(paren_text) or TIME_RANGE_RE.search(core)
        dur = DUR_RE.search(paren_text) or DUR_RE.search(core)
        period = next((w for w in PERIOD_WORDS if w in paren_text), None)
        return {
            "text": token.strip(), "pois": pois, "transport": transports,
            "time_range": tr.group() if tr else None,
            "duration": dur.group() if dur else None,
            "period_hint": period,
            "note": "；".join(n for n in note_parts if not TIME_RANGE_RE.search(n) and not DUR_RE.search(n)),
        }

    def parse_line(self, line: str, scenic: str | None = None,
                   offsets: list[int | None] | None = None) -> list[dict]:
        if not CJK_RE.search(line):
            return []
        if offsets is None:
            offsets = self._locate_offsets(line)
        parts = [(part, start, end) for part, start, end in split_with_spans(line, CHAIN_SEP)
                 if part.strip()]
        if len(parts) == 1:
            return [self.annotate(line, scenic, offsets)] if len(line) <= 60 else []
        return [self.annotate(part, scenic, offsets[start:end])
                for part, start, end in parts if not STOP_TOKEN.match(part.strip())]

    def parse(self, route: dict) -> dict:
        text = route["raw_content"]
        scenic = route.get("scenic_area")
        self._branch_entities = self.annotations[route["route_id"]]
        self._raw = text
        self._cursor = 0
        fmt = classify_format(text, route.get("ordered_route", True))
        steps: list[dict] = []
        day, period = 1, None
        step_no = 0
        # Keep character spans of lines/segments within raw_content (step source sentences are traceable)
        lines = []
        pos = 0
        for ln in text.split("\n"):
            stripped = ln.strip()
            if stripped:
                start = text.find(stripped, pos)
                lines.append((stripped, start, start + len(stripped)))
            pos += len(ln) + 1
        # Prose-style routes have whole paragraphs without newlines: split into sentences first, then parse sentence by sentence
        if fmt in ("prose", "theme_prose"):
            sents_with_span: list[tuple[str, int, int]] = []
            for ln, ln_start, ln_end in lines:
                cursor = 0
                for s in re.split(r"(?<=[。！？；])", ln):
                    s = s.strip()
                    if not s:
                        continue
                    _i = ln.find(s, cursor)
                    if _i < 0:
                        _i = cursor
                    sents_with_span.append((s, ln_start + _i, ln_start + _i + len(s)))
                    cursor = _i + len(s)
            lines = sents_with_span
        for line, line_start, line_end in lines:
            # Segment-level handling: day/period markers may appear at line start or mid-chain (e.g. “…—【第二日】丹霞峰…”)
            for seg_text, seg_start_in_line, seg_end_in_line in split_with_spans(line, CHAIN_SEP):
                seg_offsets = list(range(line_start + seg_start_in_line,
                                         line_start + seg_end_in_line))
                seg, seg_offsets = _strip_offsets(seg_text, seg_offsets)
                if not seg:
                    continue
                mdp = DAY_PERIOD_MARK.search(seg)
                if mdp:
                    # A composite marker sets both day and period; a day change still resets the period (the first stop
                    # of the next day does not inherit the previous day's 晚上—— required; the cross-day reset also holds for composite markers)
                    day = self._cn_day(mdp.group(1))
                    period = mdp.group(2)
                elif m := DAY_MARK.search(seg):
                    day = self._day_num(m)
                    period = None
                if m := PERIOD_MARK.search(seg):
                    period = (m.group(1) or m.group(2))
                seg_content, seg_offsets = _remove_patterns(seg, seg_offsets, (PERIOD_MARK, DAY_MARK))
                seg_content, seg_offsets = _strip_offsets(seg_content, seg_offsets)
                # Clause-level context guard -- strip clauses of "未去/放弃/他人行程/背景罗列" (not visited / given up / others' itineraries / background lists) before parsing,
                # so unvisited attractions and introductory listings are not taken as actual route passes (probes constructed to evidence the three mis-inclusion types)
                if NON_ROUTE_CLAUSE_RE.search(seg_content):
                    seg_content, seg_offsets = _clause_filter(seg_content, seg_offsets)
                    if not seg_content.strip():
                        continue
                if not seg_content:
                    continue
                # Compute the span after the clause guard: the final text may be shorter than the raw segment.
                seg_span = None
                _i = line.find(seg_content)
                if _i >= 0:
                    seg_span = [line_start + _i, line_start + _i + len(seg_content)]
                # Station-list line (第一站：…)
                if m := STATION_MARK.search(seg_content):
                    step_no += 1
                    ann = self.annotate(seg_content, offsets=seg_offsets)
                    ann.update({"step_no": step_no, "day": day, "period": period,
                                "station_tag": f"第{m.group(1)}站", "span": seg_span})
                    steps.append(ann)
                    continue
                # KV field lines (活动路线：… / 活动时长：约2小时)
                if fmt == "kv_route_line" and re.match(r"^[A-Za-z\u4e00-\u9fff]+[:：]", seg_content):
                    if "：" in seg_content:
                        label_raw, sep, val = seg_content.partition("：")
                    else:
                        label_raw, sep, val = seg_content.partition(":")
                    label = label_raw.rstrip(":：")
                    if label == "活动路线":
                        for sub in self.parse_line(val, scenic, seg_offsets[len(label_raw) + len(sep):]):
                            step_no += 1
                            sub.update({"step_no": step_no, "day": day, "period": period,
                                        "span": seg_span})
                            steps.append(sub)
                    elif label == "活动时长" and steps and not steps[-1]["duration"]:
                        dur = DUR_RE.search(seg_content)
                        if dur:
                            steps[-1]["duration"] = dur.group()
                    continue
                segs = self.parse_line(seg_content, scenic, seg_offsets)
                if not segs:
                    # Default handling for narrative sentences: keep the whole sentence as one potential step (retained when it contains a POI)
                    if fmt in ("prose", "theme_prose") and CJK_RE.search(seg_content):
                        ann = self.annotate(seg_content, offsets=seg_offsets)
                        if ann["pois"] and len(seg_content) <= 140:
                            step_no += 1
                            ann.update({"step_no": step_no, "day": day, "period": period,
                                        "span": seg_span})
                            steps.append(ann)
                    continue
                for sub in segs:
                    # Chain-connector dedup: drop segments with only a single POI, identical to the previous step's last POI, and carrying no other information
                    if (sub["pois"] and len(sub["pois"]) == 1 and not sub["transport"]
                            and not sub["time_range"] and not sub["duration"] and not sub["note"]
                            and steps and steps[-1]["pois"]
                            and sub["pois"][0]["normalized"] == steps[-1]["pois"][-1]["normalized"]):
                        continue
                    step_no += 1
                    sub.update({"step_no": step_no, "day": day, "period": period,
                                "span": seg_span})
                    steps.append(sub)
        # arrow_chain pure openings with neither POI nor time are not route steps (kept out of the audited population)
        if fmt == "arrow_chain":
            steps = [s for s in steps
                     if s["pois"] or s["time_range"] or s.get("station_tag") or s["transport"]]
            for i, s in enumerate(steps, 1):
                s["step_no"] = i
        # Lodging markers (宾馆/饭店/酒店/民宿)
        for s in steps:
            s["lodging"] = bool(re.search(r"宾馆|饭店|酒店|民宿", s["text"]))
        # Period forward-fill, then clock inference, so parsed_routes and the hierarchy agree.
        self._fill_periods(steps)
        infer_periods(steps)
        # Partition route steps from narrative segments. A route step needs at least
        # one route signal; narration is kept in its own list for traceability.
        route_steps: list[dict] = []
        narrative: list[dict] = []
        for segment_no, s in enumerate(steps, 1):
            has_signal = bool(s["pois"] or s["transport"] or s["time_range"]
                              or s["duration"] or s.get("station_tag") or s["lodging"])
            if has_signal:
                s["step_kind"] = step_kind(s)
                route_steps.append(s)
            else:
                narrative.append({
                    "segment_no": segment_no, "text": s["text"], "span": s.get("span"),
                    "span_status": s.get("span_status"), "day": s["day"],
                    "period": s["period"], "step_kind": "叙述",
                })
        for i, s in enumerate(route_steps, 1):
            s["step_no"] = i
        repair_spans(route_steps, text)
        repair_spans(narrative, text)
        return {
            "route_id": route["route_id"], "scenic_area": route["scenic_area"],
            "route_title": route["title"], "source_record_id": route["source_record_id"],
            "source_url": route["source_url"], "ordered_route": route.get("ordered_route", True),
            "format": fmt, "step_count": len(route_steps),
            "segment_count": len(route_steps) + len(narrative),
            "narrative_step_count": len(narrative),
            "pois_in_order": [p["name"] for s in route_steps for p in s["pois"]],
            "steps": route_steps, "narrative_segments": narrative,
        }

    @staticmethod
    def _cn_day(text: str) -> int:
        cn = "一二三四五六七八九十"
        body = text[1:-1] if text.endswith(("天", "日")) else text
        if body.isdigit():
            return int(body)
        for i, c in enumerate(cn, 1):
            if c in body:
                return 10 if c == "十" and len(body) == 1 else i
        return 1

    @staticmethod
    def _day_num(m: re.Match) -> int:
        text = m.group(1) or m.group(2) or m.group(3)
        if text and text.isdigit():
            return int(text)
        if text and text.startswith("Day"):
            return int(text[3:].strip())
        cn = "一二三四五六七八九十"
        for i, c in enumerate(cn, 1):
            if text and c in text:
                return 10 if c == "十" and len(text) == 1 else i
        return 1

    @staticmethod
    def _fill_periods(steps: list[dict]) -> None:
        """Period-marker lines themselves contain no POI (e.g. “【上午】”); a marker only takes effect on subsequent steps.
        If steps exist before the first marker, fall back to the step's period_hint.
        ：cross-day reset -- the first stop of a new day must not inherit the previous day's period (e.g. the previous evening "晚上")."""
        current = None
        prev_day = None
        for s in steps:
            if prev_day is not None and s["day"] != prev_day:
                current = None
            prev_day = s["day"]
            if s["period"]:
                current = s["period"]
            elif s["period_hint"]:
                current = s["period_hint"]
                s["period"] = current
            else:
                s["period"] = current


def main() -> int:
    routes = [json.loads(l) for l in (ROOT.parent / "task1/data/raw/official_routes.jsonl").open(encoding="utf-8")]
    ann_path = TASK2 / "output/exp2/official_route_entities.jsonl"
    if not ann_path.exists():
        raise SystemExit("缺少 official_route_entities.jsonl；请先运行 task2/src/extract_official_routes.py")
    ann_records = {}
    with ann_path.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            ann_records[rec["route_id"]] = rec
    if set(ann_records) != {r["route_id"] for r in routes}:
        raise SystemExit("official_route_entities.jsonl 的 route_id 与官方路线不一致；请重新运行 task2/src/extract_official_routes.py")
    for route in routes:
        expected = hashlib.sha256(route["raw_content"].encode("utf-8")).hexdigest()
        if ann_records[route["route_id"]]["raw_content_sha256"] != expected:
            raise SystemExit(f"官方路线标注已过期：{route['route_id']}；请重新运行 task2/src/extract_official_routes.py")
    parser = RouteParser({route_id: rec["entities"] for route_id, rec in ann_records.items()})

    parsed_routes = []
    raw_by_id = {}
    fmt_counter = Counter()
    for route in routes:
        p = parser.parse(route)
        fmt_counter[(route["scenic_area"], p["format"])] += 1
        parsed_routes.append(p)
        raw_by_id[route["route_id"]] = route["raw_content"]

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "parsed_routes.jsonl").open("w", encoding="utf-8") as fh:
        for p in parsed_routes:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")

    # Format analysis
    format_analysis = {
        "total_routes": len(routes),
        "ordered_routes": sum(1 for r in routes if r.get("ordered_route")),
        "format_counts": {f"{a}/{b}": c for (a, b), c in sorted(fmt_counter.items())},
        "format_rules": {
            "arrow_chain": "以 →/—/─ 分隔的链式表达（九寨沟时段+链、颐和园短链、黄山冬游链、黄山FAQ破折号链）",
            "numbered_stops": "“第一站：…”编号站点列表（颐和园清明遛弯线）",
            "numbered_list": "阿拉伯数字编号列表",
            "kv_route_line": "活动路线：…键值字段（九寨沟自然科学行旅）",
            "prose": "叙述式，无分隔符，含“由…至…”类路线句",
            "theme_prose": "无固定顺序的主题方案（九寨沟生态/季节主题游）",
        },
        "period_marker_styles": ["【上午】式方括号标记", "上午：式冒号标记", "无标记（由时间范围推断）"],
    }
    all_steps = [s for p in parsed_routes for s in p["steps"]]
    all_narrative = [s for p in parsed_routes for s in p["narrative_segments"]]
    span_missing = 0
    for p in parsed_routes:
        source = raw_by_id[p["route_id"]]
        for entry in p["steps"] + p["narrative_segments"]:
            if "span" not in entry:
                span_missing += 1
            elif entry.get("span_status") == "exact":
                start, end = entry["span"]
                assert source[start:end] == entry["text"], (p["route_id"], entry["text"])
    poi_mismatch = sum(
        1 for p in parsed_routes
        if p["pois_in_order"] != [poi["name"] for s in p["steps"] for poi in s["pois"]]
    )
    format_analysis["validation"] = {
        "segments": len(all_steps) + len(all_narrative),
        "route_steps": len(all_steps),
        "narrative_segments": len(all_narrative),
        "span_exact": sum(1 for s in all_steps + all_narrative if s.get("span_status") == "exact"),
        "span_not_contiguous": sum(1 for s in all_steps + all_narrative if s.get("span_status") == "not_contiguous"),
        "span_missing": span_missing,
        "pois_in_order_mismatch": poi_mismatch,
        "station_steps_without_poi": sum(1 for s in all_steps if s.get("station_tag") and not s["pois"]),
    }
    assert span_missing == 0
    assert poi_mismatch == 0
    (OUT / "route_format_analysis.json").write_text(json.dumps(format_analysis, ensure_ascii=False, indent=1), encoding="utf-8")

    # Name-normalization statistics
    norm_stats = {
        "rules": [
            "词典 canonical 映射（清晏舫→石舫、诺日朗游客中心→诺日朗中心、玉屏→玉屏景区、云谷→云谷景区）",
            "地理限定语剥离：黄山南大门→南大门、黄山风景区→黄山、XX景区→XX",
            "同名异点保护：五彩池（九寨沟/黄龙各一）不跨景区合并；北海（黄山）与北海公园（北京）由停用词守卫区分",
        ],
        "normalized_examples": {},
        "limitation": "简称/俗称（如“大峡谷”指西海大峡谷）依赖上下文，本版不做跨指代合并，留待共指消解实验处理",
    }
    for p in parsed_routes:
        for s in p["steps"]:
            for poi in s["pois"]:
                if poi["mention"] != poi["normalized"]:
                    norm_stats["normalized_examples"].setdefault(poi["mention"], poi["normalized"])
    (OUT / "name_normalization.json").write_text(json.dumps(norm_stats, ensure_ascii=False, indent=1), encoding="utf-8")

    # Parsing-quality summary
    ok = [p for p in parsed_routes if p["ordered_route"] and p["step_count"] >= 2]
    print(json.dumps({
        "routes": len(parsed_routes),
        "ordered_parsed_with_steps": len(ok),
        "format_counts": format_analysis["format_counts"],
        "avg_steps_ordered": round(sum(p["step_count"] for p in ok) / max(1, len(ok)), 1),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
