"""Experiment 3: structured parsing of official routes and time-hierarchy construction.

Input: task1/data/raw/official_routes.jsonl (46 official route branches)
       task2/output/exp2/{entity_dictionary.json, entities_refined.jsonl} (dictionary and entities)
Output: task3/output/
       route_format_analysis.json   format-pattern analysis
       name_normalization.json      name-normalization rules and application statistics
       parsed_routes.jsonl          structured route per entry (steps/periods/days/POIs/transport/time)
       time_hierarchy.jsonl         上午/中午/下午/晚上 (morning/noon/afternoon/evening) time-hierarchy view
Usage: python src/parse_routes.py (inside the task1 venv, -X utf8)
"""
from __future__ import annotations

import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK2 = ROOT.parent / "task2"
OUT = ROOT / "output"
sys.path.insert(0, str(TASK2 / "src"))
from extract_entities import DictMatcher, load_dictionary  # noqa: E402

if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


# Rule 1: dictionary canonical (清晏舫→石舫, 诺日朗游客中心→诺日朗中心, etc.)
# Rule 2: geographic-qualifier stripping (黄山南大门/黄山风景区→南大门; strip the “XX景区” suffix)
# Rule 3: same name, different places (五彩池) keep the scenic-area qualifier and are not forcibly merged
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
from entity_identity import normalize  # noqa: E402


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
    def __init__(self, matcher: DictMatcher):
        self.matcher = matcher

    def annotate(self, token: str, scenic: str | None = None) -> dict:
        """Parse a single chain node: POIs, transport, time, and notes."""
        note_parts = PAREN_RE.findall(token)
        core = PAREN_RE.sub("", token).strip(" 　,，。;；")
        pois, transports = [], []
        for e in self.matcher.find(core, scenic):
            if e["type"] == "景点POI":
                if not e.get("in_scenic", True):
                    continue  # peripheral landmarks (logistics mentions such as 汤口镇/黄龙) are not route steps
                pois.append({"name": e["canonical"], "mention": e["text"],
                             "normalized": normalize(e["canonical"])})
            elif e["type"] == "交通方式":
                transports.append(e["canonical"])
        # Transport/time information inside parentheses
        paren_text = " ".join(note_parts)
        for e in self.matcher.find(paren_text):
            if e["type"] == "交通方式" and e["canonical"] not in transports:
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

    def parse_line(self, line: str, scenic: str | None = None) -> list[dict]:
        if not CJK_RE.search(line):
            return []
        parts = [p for p in CHAIN_SEP.split(line) if p.strip()]
        if len(parts) == 1:
            return [self.annotate(line, scenic)] if len(line) <= 60 else []
        return [self.annotate(p, scenic) for p in parts if p.strip() and not STOP_TOKEN.match(p.strip())]

    def parse(self, route: dict) -> dict:
        text = route["raw_content"]
        scenic = route.get("scenic_area")
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
                offset = ln_start
                for s in re.split(r"(?<=[。！？；])", ln):
                    s = s.strip()
                    if not s:
                        continue
                    _i = ln.find(s, offset - ln_start)
                    if _i < 0:
                        _i = offset - ln_start
                    sents_with_span.append((s, ln_start + _i, ln_start + _i + len(s)))
                    offset = _i + len(s)
            lines = sents_with_span
        for line, line_start, line_end in lines:
            # Segment-level handling: day/period markers may appear at line start or mid-chain (e.g. “…—【第二日】丹霞峰…”)
            for seg in CHAIN_SEP.split(line):
                seg = seg.strip()
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
                seg_content = DAY_MARK.sub("", PERIOD_MARK.sub("", seg)).strip()
                seg_span = None
                if seg_content:
                    _i = line.find(seg_content)
                    if _i >= 0:
                        seg_span = [line_start + _i, line_start + _i + len(seg_content)]
                # Clause-level context guard -- strip clauses of "未去/放弃/他人行程/背景罗列" (not visited / given up / others' itineraries / background lists) before parsing,
                # so unvisited attractions and introductory listings are not taken as actual route passes (probes constructed to evidence the three mis-inclusion types)
                if NON_ROUTE_CLAUSE_RE.search(seg_content):
                    clauses = re.split(r"([，,])", seg_content)
                    kept = [c for i, c in enumerate(clauses)
                            if i % 2 == 0 and not NON_ROUTE_CLAUSE_RE.search(c)]
                    seg_content = "，".join(c for c in kept if c.strip())
                    if not seg_content.strip():
                        continue
                if not seg_content:
                    continue
                # Station-list line (第一站：…)
                if m := STATION_MARK.search(seg_content):
                    step_no += 1
                    ann = self.annotate(seg_content)
                    ann.update({"step_no": step_no, "day": day, "period": period,
                                "station_tag": f"第{m.group(1)}站", "span": seg_span})
                    steps.append(ann)
                    continue
                # KV field lines (活动路线：… / 活动时长：约2小时)
                if fmt == "kv_route_line" and re.match(r"^[A-Za-z\u4e00-\u9fff]+[:：]", seg_content):
                    label, _, val = seg_content.partition("：") if "：" in seg_content else seg_content.partition(":")
                    label = label.rstrip(":：")
                    if label == "活动路线":
                        for sub in self.parse_line(val, scenic):
                            step_no += 1
                            sub.update({"step_no": step_no, "day": day, "period": period,
                                        "span": seg_span})
                            steps.append(sub)
                    elif label == "活动时长" and steps and not steps[-1]["duration"]:
                        dur = DUR_RE.search(seg_content)
                        if dur:
                            steps[-1]["duration"] = dur.group()
                    continue
                segs = self.parse_line(seg_content, scenic)
                if not segs:
                    # Default handling for narrative sentences: keep the whole sentence as one potential step (retained when it contains a POI)
                    if fmt in ("prose", "theme_prose") and CJK_RE.search(seg_content):
                        ann = self.annotate(seg_content)
                        if ann["pois"] and len(seg_content) <= 140:
                            step_no += 1
                            ann.update({"step_no": step_no, "day": day, "period": period})
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
        # Pure-opening filter: in arrow_chain format, openings with neither POI nor time do not count as steps
        if fmt == "arrow_chain":
            # Pure movement events ("乘索道下山", transport without POI) are also route steps, no longer dropped
            steps = [s for s in steps
                     if s["pois"] or s["time_range"] or s.get("station_tag") or s["transport"]]
            for i, s in enumerate(steps, 1):
                s["step_no"] = i
        # Lodging markers (宾馆/饭店/酒店/民宿) and step kinds (stay vs movement event)
        for s in steps:
            s["lodging"] = bool(re.search(r"宾馆|饭店|酒店|民宿", s["text"]))
            if not s["pois"] and s["transport"]:
                s["step_kind"] = "移动事件"
            elif s["lodging"]:
                s["step_kind"] = "住宿停留"
            else:
                s["step_kind"] = "景点停留"
        # Period forward-fill: lines with a period marker only set the period of subsequent steps
        self._fill_periods(steps)
        return {
            "route_id": route["route_id"], "scenic_area": route["scenic_area"],
            "route_title": route["title"], "source_record_id": route["source_record_id"],
            "source_url": route["source_url"], "ordered_route": route.get("ordered_route", True),
            "format": fmt, "step_count": len(steps),
            "pois_in_order": [p["normalized"] for s in steps for p in s["pois"]],
            "steps": steps,
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


def build_hierarchy(parsed: dict) -> dict:
    """Three-level view: day → period → step."""
    hierarchy: dict[int, dict] = {}
    for s in parsed["steps"]:
        day = hierarchy.setdefault(s["day"], {})
        period = s["period"] or "未标注时段"
        day.setdefault(period, []).append({
            "step_no": s["step_no"], "text": s["text"], "pois": [p["normalized"] for p in s["pois"]],
            "transport": s["transport"], "time_range": s["time_range"], "duration": s["duration"],
        })
    return {"route_id": parsed["route_id"], "scenic_area": parsed["scenic_area"],
            "route_title": parsed["route_title"], "days": hierarchy,
            "periods_present": sorted({p for d in hierarchy.values() for p in d})}


def main() -> int:
    entries, stopwords, _ = load_dictionary("refined")
    matcher = DictMatcher(entries, stopwords)
    routes = [json.loads(l) for l in (ROOT.parent / "task1/data/raw/official_routes.jsonl").open(encoding="utf-8")]
    parser = RouteParser(matcher)

    parsed_routes, hierarchies = [], []
    fmt_counter = Counter()
    for route in routes:
        p = parser.parse(route)
        fmt_counter[(route["scenic_area"], p["format"])] += 1
        parsed_routes.append(p)
        hierarchies.append(build_hierarchy(p))

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "parsed_routes.jsonl").open("w", encoding="utf-8") as fh:
        for p in parsed_routes:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    with (OUT / "time_hierarchy.jsonl").open("w", encoding="utf-8") as fh:
        for h in hierarchies:
            fh.write(json.dumps(h, ensure_ascii=False) + "\n")

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
