"""实验5：条件性游览建议抽取。

模式（优先级从高到低，同一句内每个触发点独立成案）：
  P1 显式条件连词：如果/假如/若是/要是/万一/一旦/只要/除非 + 条件子句 + （则/就/最好/建议…）建议子句
  P2 “…的话”：条件子句+的话 + 建议子句
  P3 “当/遇到…时”：时间/情境条件 + 建议子句
  P4 建议/推荐/适合 + 子句：条件从子句内人群/情境词推断，缺省为“一般建议”
  P5 人群主语 + 可以：老人/孩子/情侣…可以… → 条件=人群
  P6 否定建议：不要/别/避免/慎 + VP → 条件从句内天气/装备/时间词推断
多建议句：建议子句按 ； 切分；按 ， 切分需后半以建议动词开头（避免误切动宾）。
“可以”仅在 P5（人群主语）或否定式出现，裸“可以”多为叙述能力句，不抽——边界规则见报告。
输出：output/conditional_pairs.jsonl（逐条）、mapping_table.json（去重后映射表）、extraction_stats.json
"""
from __future__ import annotations

import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.atomic import atomic_write_text

ROOT = Path(__file__).resolve().parents[1]
TASK1 = ROOT.parent / "task1"
OUT = ROOT / "output"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SENT_SPLIT = re.compile(r"[。！？\n]+")

COND_MARKERS = ("如果", "假如", "假若", "若是", "若", "要是", "万一", "一旦", "只要", "除非")
SUGG_VERB = re.compile(r"^(则|就|那|最好|建议|推荐|记得|千万|尽量|务必|一定要|可以|不妨|选择|改|换|提前|避开|放弃|考虑)")
CROWD_RE = re.compile(
    r"老人|老人小孩|带孩子|带娃|小孩|儿童|婴儿|亲子|情侣|夫妻|带老人|孕妇|腿脚|体力(不好|差|一般|有限)|新手|"
    r"第一次|学生|家庭|带娃|老人孩子|带小孩|恐高|晕车")
WEATHER_RE = re.compile(r"下雨|下雨天|雨天|雨后|下雪|雪后|大雪|降雪|雨雪|云雾|大雾|结冰|冰面|雷雨|台风|大风|降温|天冷|天热|暴晒|高温|严寒|天气|气候")
EQUIP_RE = re.compile(r"带[上好]?|穿[上好]?|准备|备[用好]?|雨衣|雨伞|防晒|冲锋衣|羽绒服|登山杖|手套|水|食物|干粮|现金|充电宝")
TIME_RE = re.compile(r"旺季|淡季|周末|节假日|黄金周|国庆|五一|寒暑假|季节|早上|清晨|上午|中午|下午|晚上|傍晚|夜晚|一天|两天|三天|"
                     r"时间紧|时间充裕|时间有限|春季|夏季|秋季|冬季|春天|夏天|秋天|冬天|红叶|花期|杜鹃|雪期|开园|闭园|淡季")
TICKET_RE = re.compile(r"提前|预约|预订|门票|身份证|优惠|免票|抢票|放票")
TRANSPORT_RE = re.compile(r"自驾|包车|班车|高铁|飞机|动车|停车|堵车|拼车|黑车")
SAFETY_RE = re.compile(r"高反|高原反应|缺氧|体力|悬崖|安全|危险|摔|滑倒|失温|迷路|封山|封闭|关闭")
NEG_RE = re.compile(r"^(不要|别|避免|慎|切勿|忌)")

CONDITION_TYPES = [
    ("天气", WEATHER_RE), ("人群", CROWD_RE), ("装备", EQUIP_RE), ("预约票务", TICKET_RE),
    ("交通", TRANSPORT_RE), ("体力安全", SAFETY_RE), ("时间", TIME_RE),
]


def classify_condition(text: str) -> str:
    for name, pat in CONDITION_TYPES:
        if pat.search(text):
            return name
    return "其他"


def crowd_subtype(text: str) -> str | None:
    for w, label in (("老人", "老人"), ("孩子", "孩子"), ("小孩", "孩子"), ("儿童", "孩子"), ("婴儿", "孩子"),
                     ("亲子", "亲子"), ("带娃", "亲子"), ("情侣", "情侣"), ("夫妻", "情侣"),
                     ("孕妇", "孕妇"), ("腿脚", "行动不便"), ("体力不好", "体力有限"), ("体力差", "体力有限"),
                     ("体力一般", "体力有限"), ("体力有限", "体力有限"), ("体力不足", "体力有限"),
                     ("体力不济", "体力有限"), ("新手", "新手"),
                     ("第一次", "初次游览"), ("学生", "学生"), ("家庭", "家庭"), ("恐高", "恐高"),
                     ("晕车", "晕车")):
        if w in text:
            return label
    return None


def split_multi_suggestions(sugg: str) -> list[str]:
    parts = [s for s in re.split(r"[；;]", sugg) if s.strip()]
    if len(parts) == 1:
        parts = [sugg]
        # 仅当逗号后半以建议动词开头才切（避免切断动宾/名词短语）
        for m in re.finditer(r"[，,]", sugg):
            tail = sugg[m.end():]
            if SUGG_VERB.match(tail):
                parts = [sugg[:m.start()], tail]
                break
    return [p.strip(" ，,。；;") for p in parts if p.strip(" ，,。；;")]


# P4 极性/边界守卫（2026-10-30，依据 review_dev wrong 样例回归）：
# 1) 平台话术不是旅游建议；2) 呼吁/评论句不是给游客的建议；
# 3) 联游城市段落的条件对归属价值低（苏州街为颐和园内景点，需排除）。
PLATFORM_PHRASE_RE = re.compile(r"点赞|收藏|一键三连|评论区|私信|关注我们|转发|推荐阅读")
# U20 守卫（依据 review_test 新鲜抽检 8 wrong 归因）：
LYRICAL_RE = re.compile(r"人生|岁月|初心|青春|梦想|心态|老得太快|明白得太迟|否定了自己|自己的想法")
COGNITIVE_RE = re.compile(r"^(不要|别)(认为|觉得|以为|担心)")
RHETORIC_P1_RE = re.compile(r"^如果说")
APPEAL_RE = re.compile(r"管理部门|引起重视|呼吁")
CITY_SKIP_RE = re.compile(r"青岛|南京|苏州(?!街)|无锡|厦门|天津|杭州|大连|哈尔滨|洛阳|西安")


def skip_sentence(sent: str) -> bool:
    return bool(PLATFORM_PHRASE_RE.search(sent) or APPEAL_RE.search(sent)
                or CITY_SKIP_RE.search(sent) or LYRICAL_RE.search(sent))


def extract_from_sentence(sent: str) -> list[dict]:
    pairs = []
    seen_spans = set()

    # P1/P2/P3：显式条件（含“…的话就/可以/建议Y”无逗号紧邻变体，U25：+4 例真实建议）
    for m in re.finditer(r"(如果|假如|假若|若是|(?<![宛仿相如自普兰沉聊日的])若|要是|万一|一旦|只要|除非)([^。！？；]{1,40}?)(的话)?[，,]", sent):
        cond = (m.group(2) or "").strip()
        rest = sent[m.end():].strip()
        if not rest:
            continue
        trigger = m.group(1) + ("…的话" if m.group(3) else "")
        if RHETORIC_P1_RE.match(trigger) and rest.startswith(("那么", "那 ")):
            continue  # "如果说X,那么Y"为对仗修辞，非条件建议
        for sugg in split_multi_suggestions(rest):
            pairs.append({"pattern": "P1_显式条件", "trigger": trigger,
                          "condition_text": cond, "suggestions": [sugg], "sentence": sent})
        seen_spans.add(m.start())
    for m in re.finditer(r"(如果|要是|若|假如)([^。！？；，]{1,40}?的话)(?=[就才可以建议最好也])", sent):
        if m.start() in seen_spans:
            continue
        trigger = m.group(1) + "…的话(紧邻)"
        rest = sent[m.start(2) + len(m.group(2)):]
        if not rest or RHETORIC_P1_RE.match(trigger):
            continue
        for sugg in split_multi_suggestions(rest):
            pairs.append({"pattern": "P1_显式条件", "trigger": trigger,
                          "condition_text": m.group(2).rstrip("的话").strip(),
                          "suggestions": [sugg], "sentence": sent})
        seen_spans.add(m.start())

    # P7 依据规定（E03）：按照/根据+要求/规定/政策/须知 的条件性规则信息（无显式条件连词）
    for m in re.finditer(r"((?:按照|根据|依据)[^。！？；]{0,16}?(?:要求|规定|政策|须知|提示))[^。！？；]{0,12}?[，,]\s*([^。！？；]{1,60})", sent):
        cond = m.group(1).strip()
        rest = m.group(2).strip()
        if not rest:
            continue
        emitted = False
        for sugg in split_multi_suggestions(rest):
            if re.match(r"^[第其][一二三四五六七八九十]", sugg.strip()):
                continue
            pairs.append({"pattern": "P7_依据规定", "trigger": m.group(1),
                          "condition_text": cond, "suggestions": [sugg], "sentence": sent,
                          "condition_type": "一般"})
            emitted = True
        if emitted:
            seen_spans.add(m.start())

    # P3 当/遇到…时
    for m in re.finditer(r"(?:当(?!时|初|年|地|下|然)|遇到|遇上|碰到)([^。！？；，]{1,24}?)(的时候|时)[，,]?", sent):
        if m.start() in seen_spans:
            continue
        cond = m.group(1).strip()
        rest = sent[m.end():].strip()
        if not rest or not SUGG_VERB.search(rest[:12]):
            continue
        for sugg in split_multi_suggestions(rest):
            pairs.append({"pattern": "P3_时点条件", "trigger": "当…时/遇到…时",
                          "condition_text": cond, "suggestions": [sugg], "sentence": sent})
        seen_spans.add(m.start())

    if pairs:
        return pairs

    # P4 建议类（带人群/情境推断）
    for m in re.finditer(r"((?<![不])建议(?!的话)|推荐|(?<![的])最好|尽量|务必|记得|千万|不妨|(?<![不合舒])适合|(?<![舒])适宜)([^。！？；]{1,60})", sent):
        clause = m.group(2).strip()
        if m.group(1) == "最好" and clause.startswith("的"):
            continue  # "最好的天气,就是…"为形容词用法，非建议（"最好是+建议"保留）
        crowd = crowd_subtype(clause) or crowd_subtype(sent)
        if crowd:
            cond_text, cond_type = f"游客为{crowd}", "人群"
        elif WEATHER_RE.search(sent):
            cond_text, cond_type = "天气条件（句内）", "天气"
        elif TIME_RE.search(sent):
            cond_text, cond_type = "时间条件（句内）", "时间"
        else:
            cond_text, cond_type = "一般建议", "一般"
        emitted = False
        for sugg in split_multi_suggestions(clause):
            if re.match(r"^[第其][一二三四五六七八九十]", sugg.strip()):
                continue  # 列举项（"第二,房卡"）非建议
            pairs.append({"pattern": "P4_建议推断", "trigger": m.group(1),
                          "condition_text": cond_text, "suggestions": [sugg], "sentence": sent,
                          "condition_type": cond_type})
            emitted = True
        if emitted:
            return pairs

    # P5 人群主语 + 可以
    for m in re.finditer(
            r"(老人|老人小孩|带孩子[^。！？；，]{0,6}|带娃|小孩|儿童|婴儿|亲子[^。！？；，]{0,4}|情侣|夫妻|"
            r"孕妇|腿脚[^。！？；，]{0,4}|体力[^。！？；，]{0,4}|新手|第一次[^。！？；，]{0,6}|学生|恐高|晕车)可以([^。！？；]{1,50})", sent):
        crowd = m.group(1).strip()
        for sugg in split_multi_suggestions(m.group(2)):
            pairs.append({"pattern": "P5_人群可以", "trigger": "可以",
                          "condition_text": f"游客为{crowd}", "suggestions": [sugg], "sentence": sent,
                          "condition_type": "人群"})
        return pairs

    # P6 否定建议
    for m in re.finditer(r"((?<!要)不要(?![要不要门票钱票])|不建议|不宜|(?<![特级区差分别参离告])别(?=[去走买坐赶忘信贪乱省图踩拒绝玩用管抢急费听折腾改])|避免|(?<![不])慎|切勿|(?<![禁])忌)([^。！？；]{1,50})", sent):
        clause = m.group(0).strip()
        if re.match(r"不要(太多|要好|要太好|不要的)", clause):
            continue  # 口语夸张比较（"好了不要太多"），非建议
        if COGNITIVE_RE.match(clause):
            continue  # "不要认为/觉得/以为"极性反转的修辞，非避雷建议
        if WEATHER_RE.search(sent):
            cond_text, cond_type = "天气条件（句内）", "天气"
        elif TIME_RE.search(sent):
            cond_text, cond_type = "时间条件（句内）", "时间"
        elif EQUIP_RE.search(sent):
            cond_text, cond_type = "装备条件（句内）", "装备"
        else:
            cond_text, cond_type = "一般建议（避雷）", "一般"
        for sugg in split_multi_suggestions(clause):
            pairs.append({"pattern": "P6_否定建议", "trigger": m.group(1),
                          "condition_text": cond_text, "suggestions": [sugg], "sentence": sent,
                          "condition_type": cond_type})
        return pairs

    return pairs


# P4 对立建议自动标记（U15）：同景区内"否定式 vs 肯定式"同核建议共存并互带来源引用。
NEG_PREFIX_RE = re.compile(r"^(不要|不宜|不建议|别|切勿|避免|慎|忌|最好不|无法|不能)")
AFF_HEDGE_RE = re.compile(r"^(最好|建议|推荐|可以|记得|务必|千万|尽量|不妨|适合|适宜)")


def _norm_sugg(s: str) -> str:
    return re.sub(r"[\s，,。；;、！？!?]+", "", s)


def mark_opposing(mapping: list[dict]) -> list[dict]:
    for idx, row in enumerate(mapping):
        row["row_id"] = idx
    by_scenic: dict[str, list[dict]] = {}
    for row in mapping:
        by_scenic.setdefault(row["scenic_area"], []).append(row)
    marked = 0
    seen_pairs: set[tuple[int, int]] = set()
    for scenic, rows in by_scenic.items():
        for a in rows:
            na = _norm_sugg(a["suggestion_text"])
            ma = NEG_PREFIX_RE.match(na)
            if not ma or len(na) - ma.end() < 3:
                continue
            core_a = na[ma.end():]
            for b in rows:
                if b["row_id"] == a["row_id"]:
                    continue
                nb = _norm_sugg(b["suggestion_text"])
                mb = NEG_PREFIX_RE.match(nb)
                if mb:
                    continue  # 对面必须是肯定式
                core_b = AFF_HEDGE_RE.sub("", nb)
                if len(core_b) < 3:
                    continue
                # 最长公共前缀作为对齐词项
                lcp = 0
                for ca, cb in zip(core_a, core_b):
                    if ca != cb:
                        break
                    lcp += 1
                if lcp < 3:
                    continue
                key = tuple(sorted((a["row_id"], b["row_id"])))
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                term = core_a[:lcp]
                a.setdefault("opposing", {"term": term, "with": []})["with"].append(
                    {"row_id": b["row_id"], "suggestion": b["suggestion_text"][:40],
                     "sources": b.get("sources", [b.get("record_id", [])])[:2]})
                b.setdefault("opposing", {"term": term, "with": []})["with"].append(
                    {"row_id": a["row_id"], "suggestion": a["suggestion_text"][:40],
                     "sources": a.get("sources", [a.get("record_id", [])])[:2]})
                marked += 1
    return mapping


def norm(s: str) -> str:
    return re.sub(r"[\s，,。；;、！？!?\[\]（）()【】]+", "", s)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-attribution-filter", action="store_true",
                    help="关闭 P1 句级归属过滤（默认开启：景区外句子不产出条件建议对）")
    args = ap.parse_args(argv)

    attr = None
    if not args.no_attribution_filter:
        import sys as _sys
        _sys.path.insert(0, str(ROOT.parent / "task4/src"))
        from attribute_sentences import Attributor, SENT_SPLIT as ATTR_SPLIT
        attr = Attributor()

    rows = [json.loads(l) for l in (TASK1 / "data/processed/dataset_clean.jsonl").open(encoding="utf-8")]
    all_pairs = []
    for row in rows:
        text = row["clean_content"]
        raw_sents = [s.strip() for s in SENT_SPLIT.split(text)]
        sent_labels = None
        if attr is not None:
            sent_labels = attr.attribute_record(row["scenic_area"], raw_sents,
                                                text_type=row.get("text_type", "travelogue"))
        for sent, sent_lab in zip(raw_sents, sent_labels or [None] * len(raw_sents)):
            if sent_lab == "景区外":
                continue  # P1 归属过滤：景区外句子不产出条件建议对
            if not (8 <= len(sent) <= 160):
                continue
            if skip_sentence(sent):
                continue  # 平台话术/呼吁句/联游城市段落守卫
            for p in extract_from_sentence(sent):
                ctype = p.get("condition_type") or classify_condition(p["condition_text"])
                for sugg in p["suggestions"]:
                    if len(norm(sugg)) < 4:
                        continue
                    all_pairs.append({
                        "record_id": row["record_id"], "scenic_area": row["scenic_area"],
                        "source_platform": row["source_platform"], "text_type": row["text_type"],
                        "pattern": p["pattern"], "trigger": p["trigger"],
                        "condition_text": p["condition_text"], "suggestion_text": sugg,
                        "condition_type": ctype, "sentence": p["sentence"][:150],
                    })

    # 去重：同景区 + 条件/建议归一文本相同 → 合并来源；另产出全局跨景区重复合并视图
    merged: dict[tuple, dict] = {}
    near_dup = 0
    for p in all_pairs:
        key = (p["scenic_area"], norm(p["condition_text"])[:24], norm(p["suggestion_text"])[:40])
        if key in merged:
            merged[key]["sources"].append(p["record_id"])
            near_dup += 1
            continue
        merged[key] = {**p, "sources": [p["record_id"]]}
    mapping = list(merged.values())
    mapping = mark_opposing(mapping)
    _opp = [r for r in mapping if r.get("opposing")]
    atomic_write_text(OUT / "opposing_pairs.json", json.dumps({
        "note": "P4 对立建议自动标记：同景区内否定式与肯定式同核建议共存（互带 row_id 与来源）",
        "n_marked_rows": len(_opp),
        "pairs": [{"scenic_area": r["scenic_area"], "term": r["opposing"]["term"],
                   "suggestion": r["suggestion_text"][:60],
                   "opposing_with": r["opposing"]["with"], "sources": r.get("sources", [])[:3]}
                  for r in _opp]}, ensure_ascii=False, indent=1), encoding="utf-8")
    for m in mapping:
        m["frequency"] = len(m["sources"])
        m["sources"] = list(dict.fromkeys(m["sources"]))[:10]

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "conditional_pairs.jsonl").open("w", encoding="utf-8") as fh:
        for p in all_pairs:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    atomic_write_text(OUT / "mapping_table.json",
        json.dumps(mapping, ensure_ascii=False, indent=1))

    stats = {
        "raw_pairs": len(all_pairs),
        "after_dedup": len(mapping),
        "duplicates_merged": near_dup,
        "by_pattern": dict(Counter(p["pattern"] for p in all_pairs)),
        "by_condition_type": dict(Counter(p["condition_type"] for p in all_pairs)),
        "by_scenic": dict(Counter(p["scenic_area"] for p in all_pairs)),
        "by_text_type": dict(Counter(p["text_type"] for p in all_pairs)),
        "crowd_breakdown": dict(Counter(
            crowd_subtype(p["condition_text"]) or "未细分"
            for p in all_pairs if p["condition_type"] == "人群")),
    }
    atomic_write_text(OUT / "extraction_stats.json", json.dumps(stats, ensure_ascii=False, indent=1))
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
