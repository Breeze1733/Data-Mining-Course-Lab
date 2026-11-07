"""实验3：官方路线的结构化解析与时间层级构建。

输入：task1/data/raw/official_routes.jsonl（46 条官方路线分支）
     task2/output/exp2/{entity_dictionary.json, entities_refined.jsonl}（词典与实体）
输出：task3/output/
     route_format_analysis.json   格式规律分析
     name_normalization.json      名称归一化规则与应用统计
     parsed_routes.jsonl          逐条结构化路线（步骤/时段/天数/POI/交通/时间）
     time_hierarchy.jsonl         上午/中午/下午/晚上 时间层级视图
用法：python src/parse_routes.py（在 task1 venv 内，-X utf8）
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

# ── 名称归一化 ────────────────────────────────────────────────
# 规则1：词典 canonical（清晏舫→石舫、诺日朗游客中心→诺日朗中心等，见 entity_dictionary.json）
# 规则2：地理限定语剥离（黄山南大门/黄山风景区→南大门；“XX景区”后缀剥离）
# 规则3：等同名异点（五彩池）保留景区限定，不强行合并
from normalize_name import normalize  # noqa: E402

# ── 分隔符与括号 ──────────────────────────────────────────────
CHAIN_SEP = re.compile(r"→|➝|➞|⇒|➤|─+|—+|–+")
PAREN_RE = re.compile(r"[（(]([^()]*)[）)]")
TIME_RANGE_RE = re.compile(
    r"(?:清晨|早上|上午|中午|下午|傍晚|晚上|夜里|深夜|凌晨)?\d{1,2}[点:：]\d{1,2}(?:分)?\s*[-—~～至]\s*\d{1,2}[点:：]\d{1,2}(?:分)?")
DUR_RE = re.compile(r"(?:约|大概|将近|近)?\d+(?:\.\d+)?\s*(?:个)?(?:小时|钟头|分钟)|半小时")
PERIOD_WORDS = ("清晨", "早上", "上午", "中午", "下午", "傍晚", "晚上", "夜里", "深夜", "凌晨", "全天")
DAY_MARK = re.compile(r"[【\[]\s*(第[一二三四五六七八九十\d]+[日天]|Day\s*\d+)\s*[】\]]|第([一二三四五六七八九十\d]+)天|Day\s*(\d+)")
PERIOD_MARK = re.compile(r"[【\[]\s*(上午|中午|下午|晚上|清晨|傍晚|全天)\s*[】\]]|(上午|中午|下午|晚上|清晨|傍晚)[:：]")
# C03：复合天+时段标记（"【第一天·晚上】"）——此前 DAY/PERIOD 各自都不命中复合形，
# 天与时段双双丢失
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
        """解析单个链节点：POI、交通、时间、备注。"""
        note_parts = PAREN_RE.findall(token)
        core = PAREN_RE.sub("", token).strip(" 　,，。;；")
        pois, transports = [], []
        for e in self.matcher.find(core, scenic):
            if e["type"] == "景点POI":
                if not e.get("in_scenic", True):
                    continue  # 周边地标（汤口镇/黄龙等后勤提及）不作为路线步骤
                pois.append({"name": e["canonical"], "mention": e["text"],
                             "normalized": normalize(e["canonical"])})
            elif e["type"] == "交通方式":
                transports.append(e["canonical"])
        # 括号里的交通/时间信息
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
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        # 散文式路线整段无换行，先分句再逐句解析
        if fmt in ("prose", "theme_prose"):
            sentences: list[str] = []
            for ln in lines:
                sentences.extend(s.strip() for s in re.split(r"(?<=[。！？；])", ln) if s.strip())
            lines = sentences
        for line in lines:
            # 段级处理：一天/时段标记可能出现在行首或链中间（如“…—【第二日】丹霞峰…”）
            for seg in CHAIN_SEP.split(line):
                seg = seg.strip()
                if not seg:
                    continue
                mdp = DAY_PERIOD_MARK.search(seg)
                if mdp:
                    # C03：复合标记同时设定天与时段；天变更仍重置时段（次日第一站
                    # 不继承前一日晚上——C03 要求，跨日重置在复合标记同样成立）
                    day = self._cn_day(mdp.group(1))
                    period = mdp.group(2)
                elif m := DAY_MARK.search(seg):
                    day = self._day_num(m)
                    period = None
                if m := PERIOD_MARK.search(seg):
                    period = (m.group(1) or m.group(2))
                seg_content = DAY_MARK.sub("", PERIOD_MARK.sub("", seg)).strip()
                if not seg_content:
                    continue
                # 站点列表行（第一站：…）
                if m := STATION_MARK.search(seg_content):
                    step_no += 1
                    ann = self.annotate(seg_content)
                    ann.update({"step_no": step_no, "day": day, "period": period,
                                "station_tag": f"第{m.group(1)}站"})
                    steps.append(ann)
                    continue
                # KV 字段行（活动路线：… / 活动时长：约2小时）
                if fmt == "kv_route_line" and re.match(r"^[A-Za-z\u4e00-\u9fff]+[:：]", seg_content):
                    label, _, val = seg_content.partition("：") if "：" in seg_content else seg_content.partition(":")
                    label = label.rstrip(":：")
                    if label == "活动路线":
                        for sub in self.parse_line(val, scenic):
                            step_no += 1
                            sub.update({"step_no": step_no, "day": day, "period": period})
                            steps.append(sub)
                    elif label == "活动时长" and steps and not steps[-1]["duration"]:
                        dur = DUR_RE.search(seg_content)
                        if dur:
                            steps[-1]["duration"] = dur.group()
                    continue
                segs = self.parse_line(seg_content, scenic)
                if not segs:
                    # 叙述句兜底：整句作为一个潜在步骤（含POI时保留）
                    if fmt in ("prose", "theme_prose") and CJK_RE.search(seg_content):
                        ann = self.annotate(seg_content)
                        if ann["pois"] and len(seg_content) <= 140:
                            step_no += 1
                            ann.update({"step_no": step_no, "day": day, "period": period})
                            steps.append(ann)
                    continue
                for sub in segs:
                    # 链式连接点去重：仅有单个POI且与上一步末尾POI相同、无其他信息的段
                    if (sub["pois"] and len(sub["pois"]) == 1 and not sub["transport"]
                            and not sub["time_range"] and not sub["duration"] and not sub["note"]
                            and steps and steps[-1]["pois"]
                            and sub["pois"][0]["normalized"] == steps[-1]["pois"][-1]["normalized"]):
                        continue
                    step_no += 1
                    sub.update({"step_no": step_no, "day": day, "period": period})
                    steps.append(sub)
        # 纯前置句过滤：arrow_chain 格式下无 POI 且无时间的开场白不算步骤
        if fmt == "arrow_chain":
            steps = [s for s in steps if s["pois"] or s["time_range"] or s.get("station_tag")]
            for i, s in enumerate(steps, 1):
                s["step_no"] = i
        # 住宿点标记（宾馆/饭店/酒店/民宿）
        for s in steps:
            s["lodging"] = bool(re.search(r"宾馆|饭店|酒店|民宿", s["text"]))
        # 时段前向填充：带时段标记的行只设置后续步骤的 period
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
        """时段标记行本身不含 POI（如“【上午】”），标记只对后续步骤生效；
        首个标记前若已有步骤，沿用 step 里的 period_hint。
        C03：跨日重置——次日第一站不得继承前一日时段（如前一晚"晚上"）。"""
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
    """天数 → 时段 → 步骤 三层视图。"""
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

    # 格式分析
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

    # 名称归一化统计
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

    # 解析质量摘要
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
