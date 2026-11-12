"""Experiment 5: conditional sightseeing-advice extraction.


Patterns (highest to lowest priority; each trigger site in a sentence becomes its own case):

  P1 explicit conditional conjunctions: 如果/假如/若是/要是/万一/一旦/只要/除非 + condition clause + (则/就/最好/建议…) advice clause

  P2 “…的话”: condition clause + 的话 + advice clause

  P3 “当/遇到…时”: time/situation condition + advice clause

  P4 建议/推荐/适合 + clause: condition inferred from crowd/situation words in the clause, defaulting to “一般建议”

  P5 crowd subject + 可以: 老人/孩子/情侣…可以… -> condition=人群

  P6 negative advice: 不要/别/避免/慎 + VP -> condition inferred from in-clause weather/equipment/time words

Multi-advice sentences: advice clauses split on ； ； splitting on ， requires the second half to start with an advice verb (to avoid cutting verb-object phrases).

“可以” appears only in P5 (crowd subject) or the negative form; bare “可以” is usually a capability statement and is not extracted — boundary rules in the report.

Output: output/conditional_pairs.jsonl (per pair), mapping_table.json (deduplicated mapping table), extraction_stats.json

"""

from __future__ import annotations


import hashlib

import io

import json

import re

import sys

from collections import Counter, defaultdict

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

TASK1 = ROOT.parent / "task1"

OUT = ROOT / "output"


if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


SENT_SPLIT = re.compile(r"[。！？\n]+")


COND_MARKERS = ("如果", "假如", "假若", "若是", "若", "要是", "万一", "一旦", "只要", "除非")

# Supplement action verbs — split into separate advice when an action verb follows a comma (common travel-advice verbs such as 穿/带/吃/住)

SUGG_VERB = re.compile(r"^(则|就|那|然后|最好|建议|推荐|记得|千万|尽量|务必|一定要|可以|不妨|选择|改|换|提前|避开|放弃|考虑|穿|带|买|吃|住|坐|乘|走|游览|参观|步行|前往|返回|入住|预定|预约|排队|自驾|徒步|登|第[一二三四五六七八九十]+天)")

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

    if re.search(r"时间(?:充足|允许)", text):
        return "时间"

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

        # Split only when the post-comma half starts with an advice verb (to avoid cutting verb-object/noun phrases)

        for m in re.finditer(r"[，,]", sugg):

            tail = sugg[m.end():]

            if SUGG_VERB.match(tail):

                parts = [sugg[:m.start()], tail]

                break

    return [p.strip(" ，,。；;") for p in parts if p.strip(" ，,。；;")]


# Polarity/boundary guards:

# 1) platform boilerplate is not travel advice; 2) appeal/comment sentences are not advice for tourists;

# 3) condition pairs in joint-tour city paragraphs carry little attribution value (苏州街 is a sight inside 颐和园 and must be excluded).

PLATFORM_PHRASE_RE = re.compile(r"点赞|收藏|一键三连|评论区|私信|关注我们|转发|推荐阅读")

# Guards for non-advice sentences:

LYRICAL_RE = re.compile(r"人生|岁月|初心|青春|梦想|心态|老得太快|明白得太迟|否定了自己|自己的想法")

COGNITIVE_RE = re.compile(r"^(不要|别)(认为|觉得|以为|担心)")

RHETORIC_IFSAY_RE = re.compile(r"^如果说")

APPEAL_RE = re.compile(r"管理部门|引起重视|呼吁")

CITY_SKIP_RE = re.compile(r"青岛|南京|苏州(?!街)|无锡|厦门|天津|杭州|大连|哈尔滨|洛阳|西安")


def skip_sentence(sent: str) -> bool:

    return bool(PLATFORM_PHRASE_RE.search(sent) or APPEAL_RE.search(sent)

                or CITY_SKIP_RE.search(sent) or LYRICAL_RE.search(sent))


_PHOTO_HINT = re.compile(r"拍照|出片|机位|镜头|拍摄|摄影|合影|角度|光线|构图")
_TICKET_HINT = re.compile(r"门票|联票|买票|票价|预约|免费|半价|优惠|一卡通|票")
_LODGING_HINT = re.compile(r"住|酒店|民宿|宾馆|客栈|床位|帐篷|标间|多人间|入住|过夜|夜宿")
_FOOD_HINT = re.compile(r"吃|餐|食|饭|菜|小吃|美食|特产|零食|面包|泡面|自热")


def refine_condition_type(cond_text: str, sugg_text: str, current: str) -> str:
    """Refine "其他/一般" (other/general) types by keyword. Existing specific types are left unchanged."""
    if current not in ("其他", "一般"):
        return current
    text = cond_text + " " + sugg_text
    if _PHOTO_HINT.search(text):
        return "拍照"
    if _LODGING_HINT.search(text):
        return "住宿"
    if _TICKET_HINT.search(text):
        return "预约票务"
    if _FOOD_HINT.search(text):
        return "美食"
    return current


CLAUSE_DELIM = re.compile(r"[，,；;。！？!?\n]")

LEGACY_LABELS = {
    "一般建议", "一般建议（避雷）", "时间条件（句内）", "天气条件（句内）",
    "装备条件（句内）", "入园/通行规定（句内）", "开放时间规定（句内）",
}

INFER_RE = {"人群": CROWD_RE, "天气": WEATHER_RE, "时间": TIME_RE, "装备": EQUIP_RE}


def _span_in(sent: str, text: str, lo: int = 0):
    """Return ([a,b], ambiguous) for the first exact occurrence of text at/after lo."""
    if not text:
        return None, False
    a = sent.find(text, lo)
    if a < 0:
        return None, False
    b = a + len(text)
    return [a, b], sent.find(text, b) >= 0


def _group_span(sent: str, m, group: int, suffix: str = ""):
    """Exact (text, span) for a regex group, trimming whitespace and an optional suffix."""
    raw = m.group(group)
    text = raw.strip()
    if suffix and text.endswith(suffix):
        text = text[: -len(suffix)].rstrip()
    if not text:
        return "", None
    lead = raw.find(text)
    a = m.start(group) + (lead if lead >= 0 else 0)
    b = a + len(text)
    if sent[a:b] != text:
        span, _ = _span_in(sent, text, m.start(group))
        if span is None:
            return text, None
        return text, span
    return text, [a, b]


def _clause_span(sent: str, a: int, b: int, max_len: int = 40):
    """Expand [a,b) to clause boundaries, falling back to the keyword span when too long."""
    left = 0
    for cm in CLAUSE_DELIM.finditer(sent, 0, a):
        left = cm.end()
    right = len(sent)
    cm = CLAUSE_DELIM.search(sent, b)
    if cm:
        right = cm.start()
    text = sent[left:right].strip()
    if not text:
        return "", None
    lead = sent[left:right].find(text)
    left = left + lead
    if len(text) > max_len:
        return sent[a:b], [a, b]
    return text, [left, left + len(text)]


def infer_condition(sent: str, advice_start: int, types: list[str], max_len: int = 40):
    """Find a verbatim condition in the sentence.

    Crowd words count anywhere in the sentence (they name the audience); weather/time/equipment
    only count before the advice, otherwise the condition is not separable from the advice.
    Returns (text, span, matched_type, absent_reason).
    """
    keyword_only_in_advice = False
    for kind in types:
        pat = INFER_RE.get(kind)
        if pat is None:
            continue
        if kind == "人群":
            m = pat.search(sent)
            if m:
                return m.group(0).strip(), [m.start(), m.end()], kind, None
            continue
        prefix = sent[:advice_start]
        best = None
        for m in pat.finditer(prefix):
            best = m
        if best is not None:
            text, span = _clause_span(prefix, best.start(), best.end(), max_len)
            if text and span:
                return text, span, kind, None
        if pat.search(sent, advice_start):
            keyword_only_in_advice = True
    return "", None, None, ("keyword_only_in_advice" if keyword_only_in_advice else "no_keyword")


def _cond(text: str, span, kind: str, label: str = "", reason=None, negated: bool = False) -> dict:
    """Build the condition-related fields; empty text is always an explicit 'absent' marker."""
    return {
        "condition_text": text or "",
        "condition_span": span if text else None,
        "condition_kind": kind if text else "absent",
        "condition_label": label,
        "condition_absent_reason": None if text else reason,
        "condition_negated": negated,
    }


def _infer_fields(sent: str, advice_start: int, types: list[str], label: str) -> dict:
    text, span, _, reason = infer_condition(sent, advice_start, types)
    if not text and types == ["人群"] and reason == "no_keyword":
        reason = "no_crowd_span"
    return _cond(text, span, "inferred", label, reason)


def _assign_pair_id(p: dict, counter: list) -> str:
    """Assign a deterministic sequential id p0001, p0002, ... in encounter order.

    Replaces the previous content-hash id, which served no integrity purpose for
    this identifier: the payload lives in the same record, dedup uses tuple
    comparison, and downstream task6 only reads the ``pair_ids`` list (not values).
    Sequential ids are human-readable and stable in encounter order within a run.
    """
    counter[0] += 1
    p["pair_id"] = f"p{counter[0]:04d}"
    return p["pair_id"]


def validate_pairs(pairs: list[dict]) -> None:
    """Fail before writing when a condition is not verifiable or an absent row is not marked."""
    errors = []
    for p in pairs:
        text = p.get("condition_text", "")
        span = p.get("condition_span")
        sent = p.get("sentence", "")
        if text:
            ok = (isinstance(span, list) and len(span) == 2
                  and all(isinstance(i, int) for i in span)
                  and 0 <= span[0] <= span[1] <= len(sent)
                  and sent[span[0]:span[1]] == text)
            if not ok:
                errors.append(f"bad condition span {p.get('pair_id')}: {text!r}")
        elif span is not None or p.get("condition_kind") != "absent":
            errors.append(f"empty condition not marked absent {p.get('pair_id')}")
        if len(sent) > 160:
            errors.append(f"sentence longer than 160 {p.get('pair_id')}: {len(sent)}")
    ids = [p.get("pair_id") for p in pairs]
    if any(not pid for pid in ids):
        errors.append("missing pair_id")
    if len(ids) != len(set(ids)):
        errors.append("duplicate pair_id")
    if errors:
        raise SystemExit("condition validation failed:\n" + "\n".join(errors[:20]))


def refine(row: dict) -> tuple[dict, list[str]]:
    row = dict(row)
    row['condition_refinement'] = []
    original_kind = row.get('condition_kind')
    text = row.get('condition_text', '')
    span = row.get('condition_span')
    if not text or not span:
        return row, []

    sent = row['sentence']
    start, end = span
    changes = []
    if (row.get('pattern') == '显式条件' and row.get('trigger') == '…的话(裸)'
            and text.startswith('果') and start > 0 and sent[start - 1:start + 1] == '如果'):
        row.update(condition_text=text[1:], condition_span=[start + 1, end],
                   original_condition_text=text, original_condition_span=span, original_condition_kind=row['condition_kind'],
                   condition_refinement=['remove_partial_conjunction'])
        return row, row['condition_refinement']
    # “若干” and “若隐若现” are words, not the conditional conjunction “若”.
    if (row.get('pattern') == '显式条件' and row.get('trigger') == '若'
            and (text.startswith('干') or text.startswith('隐若现'))):
        row.update(condition_text='', condition_span=None, condition_kind='absent',
                   condition_absent_reason='nonconditional_homograph',
                   original_condition_type_verified=row.get('condition_type_verified'), condition_type_verified='无',
                   original_condition_text=text, original_condition_span=span, original_condition_kind=row['condition_kind'],
                   condition_refinement=['remove_nonconditional_homograph'])
        return row, row['condition_refinement']
    if row.get('condition_kind') != 'inferred':
        return row, []
    # A preceding instruction is another recommendation, not a situation.
    if re.match(r'^(?:\d+[.、]\s*)?(?:一定要|务必|记得|注意(?:看|查看|关注))', text):
        row.update(condition_text='', condition_span=None, condition_kind='absent',
                   condition_absent_reason='instruction_not_condition',
                   original_condition_type_verified=row.get('condition_type_verified'), condition_type_verified='无',
                   original_condition_text=text, original_condition_span=span, original_condition_kind=row['condition_kind'],
                   condition_refinement=['remove_instruction_as_condition'])
        return row, row['condition_refinement']
    # A clothing-section heading and a place described as suitable are not conditions.
    if (re.fullmatch(r'\s*\d*[.、]?\s*穿搭\s*[:：]?\s*建议\s*', text)
            or re.fullmatch(r'.{0,20}(?:台阶|桥|广场|景点|景区|位置|区域|地方|路线)'
                            r'(?:很|比较|非常|最)?适合', text)):
        row.update(condition_text='', condition_span=None, condition_kind='absent',
                   condition_absent_reason='description_not_condition',
                   original_condition_type_verified=row.get('condition_type_verified'), condition_type_verified='无',
                   original_condition_text=text, original_condition_span=span, original_condition_kind=row['condition_kind'],
                   condition_refinement=['remove_heading_or_place_description'])
        return row, row['condition_refinement']
    # The crowd expression may start immediately after a negator: 没体力的 / 无体力的.
    if row['pattern'] == '人群可以' and text.startswith('体力'):
        prefix = sent[max(0, start - 2):start]
        match = re.search(r'(没有|没|无|缺乏)$', prefix)
        if match:
            start -= len(match.group())
            changes.append('restore_condition_negation')
        crowd = sent[start:end]
        adverb = re.search(r'(完全|都|也)$', crowd)
        if adverb and len(crowd) > len(adverb.group()):
            end -= len(adverb.group())
            changes.append('remove_advice_adverb_from_condition')

    if sent[start:end].startswith('备注:') or sent[start:end].startswith('备注：'):
        start += 3
        changes.append('remove_note_heading')
    if (sent[start:end].endswith('需') and
            re.search(r'(?:老人|小朋友|孩子|儿童|孕妇|游客)需$', sent[start:end])):
        end -= 1
        changes.append('remove_action_marker_from_crowd')

    # An extraction marker ending the condition belongs to the advice, not the condition.
    trigger = row.get('trigger', '')
    if row['pattern'] in ('建议推断', '否定建议') and trigger:
        cond = sent[start:end]
        before_trigger = cond[:-len(trigger)] if cond.endswith(trigger) else ''
        # Only trim where the remaining phrase itself names a concrete situation.
        clear_situation = re.search(
            r'(?:旺季|淡季|周末|节假日|国庆|春季|夏季|秋季|冬季|时间紧张|时间充足|时间充裕|'
            r'体力好|体力不好|体力不足)(?:的|来)?$', before_trigger)
        if before_trigger and clear_situation:
            end -= len(trigger)
            changes.append('remove_trigger_from_condition')

    # A later clause with its own condition and action is a separate statement.
    # Mere mention after advice is insufficient: “不要从东门进，新手避雷” applies to beginners.
    advice_start = sent.find(row.get('suggestion_text', ''))
    after_advice_clause = (advice_start >= 0 and start > advice_start and
                           bool(re.search(r'[，,；;。！？!?)）]', sent[advice_start:start])) and
                           bool(re.match(r'(?:的|朋友|游客|者|旅客|人|小孩|孩子|家长){0,3}'
                                         r'(?:也|都)?(?:可|要|需|建议)', sent[end:end + 12])))
    incomplete_choice = (row['pattern'] == '人群可以' and
                         bool(re.fullmatch(r'可以选择\s*[:：]', row.get('suggestion_text', ''))))
    if after_advice_clause or incomplete_choice:
        row.update(condition_text='', condition_span=None, condition_kind='absent',
                   condition_absent_reason='condition_after_advice' if after_advice_clause else 'incomplete_choice')
        changes.append('remove_condition_after_advice' if after_advice_clause else 'remove_incomplete_choice')
    else:
        while end > start and sent[end - 1] in ' ，,；;：:':
            end -= 1
        if end > start:
            row['condition_text'] = sent[start:end]
            row['condition_span'] = [start, end]
        else:
            row.update(condition_text='', condition_span=None, condition_kind='absent',
                       condition_absent_reason='empty_after_boundary_repair')
            changes.append('empty_after_boundary_repair')

    if row['condition_text'] != text and not changes:
        changes.append('trim_condition_boundary')
    if changes:
        if not row['condition_text']:
            row['original_condition_type_verified'] = row.get('condition_type_verified')
            row['condition_type_verified'] = '无'
        row['original_condition_kind'] = original_kind
        row['original_condition_text'] = text
        row['original_condition_span'] = span
        row['condition_refinement'] = changes
    return row, changes



def extract_from_sentence(sent: str) -> list[dict]:

    pairs = []

    seen_spans = set()


    # Priority: otherwise-branch splitting (a better parse than the explicit-condition branch — store the mutually exclusive branches separately, no merging)

    for m in re.finditer(r"(如果|要是|若)([^。！？；]{1,40}?)就([^，。！？；]{1,30})[，,]?否则([^。！？；]{1,40})", sent):

        branch_a_cond, branch_a_span = _group_span(sent, m, 2)

        branch_a_sugg = "就" + m.group(3).strip()

        branch_b_sugg = m.group(4).strip()

        pairs.append({"pattern": "显式条件", "trigger": m.group(1),

                      "suggestions": [branch_a_sugg], "sentence": sent,

                      **_cond(branch_a_cond, branch_a_span, "explicit")})

        pairs.append({"pattern": "显式条件", "trigger": m.group(1) + "(否则)",

                      "suggestions": [branch_b_sugg], "sentence": sent,

                      **_cond(branch_a_cond, branch_a_span, "explicit",

                             label="非" + branch_a_cond, negated=True)})

        seen_spans.add(m.start())

    if pairs:

        return pairs


    # Explicit conditions (including the no-comma adjacent variants ”…的话就/可以/建议Y”, +4 real advice cases)

    # Reported-speech guard — the advice target of "导游说/司机说…如果…" is the narrator, not tourists
    if re.search(r"(?:导游|司机|师傅|工作人员|店员|讲解员)说[^。！？；]{0,8}(?:如果|要是|若)", sent):
        return pairs

    for m in re.finditer(r"(如果|假如|假若|若是|(?<![宛仿相如自普兰沉聊日的])若|要是|万一|一旦|只要|除非)([^。！？；]{1,40}?)(的话)?[，,]", sent):

        cond, cond_span = _group_span(sent, m, 2)

        rest = sent[m.end():].strip()

        if not rest:

            continue

        trigger = m.group(1) + ("…的话" if m.group(3) else "")

        # Rhetorical guard on two fronts — "如果说" lands in the condition text (the conjunction group captures only 2 chars); reported speech
        # (导游说/司机说…+如果) targets the narrator, not tourist advice
        if (RHETORIC_IFSAY_RE.match(trigger) or cond.startswith("说")) and rest.startswith(("那么", "那 ")):

            continue  # "如果说X,那么Y" is parallel rhetoric, not conditional advice

        for sugg in split_multi_suggestions(rest):

            pairs.append({"pattern": "显式条件", "trigger": trigger,

                          "suggestions": [sugg], "sentence": sent,

                          **_cond(cond, cond_span, "explicit")})

        seen_spans.add(m.start())

    for m in re.finditer(r"(如果|要是|若|假如)([^。！？；，]{1,40}?的话)(?=[就才可以建议最好也])", sent):

        if m.start() in seen_spans:

            continue

        trigger = m.group(1) + "…的话(紧邻)"

        rest = sent[m.start(2) + len(m.group(2)):]

        if not rest or RHETORIC_IFSAY_RE.match(trigger):

            continue

        cond_text, cond_span = _group_span(sent, m, 2, suffix="的话")

        for sugg in split_multi_suggestions(rest):

            pairs.append({"pattern": "显式条件", "trigger": trigger,

                          "suggestions": [sugg], "sentence": sent,

                          **_cond(cond_text, cond_span, "explicit")})

        seen_spans.add(m.start())


    # Extension A: bare "X的话，Y" (no 如果/要是 prefix) — "玩黄龙的话住松潘古城" (miss confirmed on the expanded sample)
    for m in re.finditer(r"([一-龥A-Za-z0-9]{2,12})的话[，,]?\s*", sent):
        if m.start() in seen_spans:
            continue
        cond, cond_span = _group_span(sent, m, 1)
        if cond.startswith(("如果", "要是", "若", "假如", "既然", "就是说")):
            continue  # conjunction forms are handled by P1
        rest = sent[m.end():].strip()
        if not rest or not (SUGG_VERB.match(rest)
                            or re.match(r"(?:建议|最好|推荐|记得|不妨|务必|要|选|住|坐|乘|带|穿|备|订|避)", rest)):
            continue
        for sugg in split_multi_suggestions(rest[:40]):
            pairs.append({"pattern": "显式条件", "trigger": "…的话(裸)",
                          "suggestions": [sugg], "sentence": sent,
                          **_cond(cond, cond_span, "explicit")})
        seen_spans.add(m.start())

    # Extension B: space-separated "condition occurrence + imperative" — "高反情况出现 路上随时休息补氧"
    for m in re.finditer(r"([一-龥A-Za-z0-9]{2,14}(?:出现|的时候?))[ 　]+([一-龥][^。！？；]{1,28})", sent):
        cond, cond_span = _group_span(sent, m, 1)
        rest = m.group(2).strip()
        if not re.search(r"(?:休息|补氧|带上?|备|穿|涂|错峰|排队|慢行|提前)", rest[:10]):
            continue
        pairs.append({"pattern": "句内条件", "trigger": "空格条件",
                      "suggestions": [rest], "sentence": sent,
                      "condition_type": "体力安全" if ("高反" in cond or "体力" in cond) else "一般",
                      **_cond(cond, cond_span, "explicit")})

    # Extension C: must-do/no-entry regulations ("你需要乘坐新国线登山车"/"私家车不允许进入")
    for m in re.finditer(r"(需要?|须)(乘坐?|购买|预订|预约)[^。！？；，]{1,26}", sent):
        pairs.append({"pattern": "依据规定", "trigger": m.group(1) + m.group(2),
                      "suggestions": [m.group(0)], "sentence": sent,
                      "condition_type": "预约票务" if ("订" in m.group(2) or "预约" in m.group(2)) else "交通",
                      **_cond("", None, "absent", label="入园/通行规定（句内）",
                             reason="regulation_not_conditional")})
    for m in re.finditer(r"(不允许|禁止|不得)[^。！？；，]{1,26}", sent):
        back = sent[max(0, m.start() - 12):m.start()]
        if re.search(r"(估计|可能|将|恐怕|也许|说不定)", back):
            continue  # predictive context ("估计不久将禁止"), not a current regulation
        pairs.append({"pattern": "否定建议", "trigger": m.group(1),
                      "suggestions": [m.group(0)], "sentence": sent, "condition_type": "一般",
                      **_cond("", None, "absent", label="入园/通行规定（句内）",
                             reason="regulation_not_conditional")})
    # Extension D: note + closure/not-open regulations ("需要注意的是北京很多景点周一都不开放")
    for m in re.finditer(r"(需要注意的是?|注意)[^。！？；]{0,18}(不开放|闭馆|关闭|停运|暂停开放)[^。！？；]{0,20}", sent):
        pairs.append({"pattern": "依据规定", "trigger": m.group(1),
                      "suggestions": [m.group(0)[:40]], "sentence": sent,
                      "condition_type": "时间",
                      **_cond("", None, "absent", label="开放时间规定（句内）",
                             reason="regulation_not_conditional")})

    # P7 by-regulation: conditional rule information from 按照/根据+要求/规定/政策/须知 (no explicit conditional conjunction)

    for m in re.finditer(r"((?:按照|根据|依据)[^。！？；]{0,16}?(?:要求|规定|政策|须知|提示))[^。！？；]{0,12}?[，,]\s*([^。！？；]{1,60})", sent):

        cond, cond_span = _group_span(sent, m, 1)

        rest = m.group(2).strip()

        if not rest:

            continue

        emitted = False

        for sugg in split_multi_suggestions(rest):

            if re.match(r"^[第其][一二三四五六七八九十]", sugg.strip()):

                continue

            pairs.append({"pattern": "依据规定", "trigger": m.group(1),

                          "suggestions": [sugg], "sentence": sent,

                          "condition_type": "一般",

                          **_cond(cond, cond_span, "explicit")})

            emitted = True

        if emitted:

            seen_spans.add(m.start())

    # 当/遇到…时 (time-point conditions)

    for m in re.finditer(r"(?:当(?!时|初|年|地|下|然)|遇到|遇上|碰到)([^。！？；，]{1,24}?)(的时候|时)[，,]?", sent):

        if m.start() in seen_spans:

            continue

        cond, cond_span = _group_span(sent, m, 1)

        rest = sent[m.end():].strip()

        if not rest or not SUGG_VERB.search(rest[:12]):

            continue

        for sugg in split_multi_suggestions(rest):

            pairs.append({"pattern": "时点条件", "trigger": "当…时/遇到…时",

                          "suggestions": [sugg], "sentence": sent,

                          **_cond(cond, cond_span, "explicit")})

        seen_spans.add(m.start())


    if pairs:

        return pairs


    # Advice class (with crowd/situation inference)

    for m in re.finditer(r"((?<![不])建议(?!的话)|推荐|(?<![的])最好|尽量|务必|记得|千万|不妨|(?<![不合舒])适合|(?<![舒])适宜)([^。！？；]{1,60})", sent):

        clause = m.group(2).strip()

        if m.group(1) == "最好" and clause.startswith("的"):

            continue  # "最好的天气,就是…" is adjectival usage, not advice ("最好是+advice" kept)

        crowd = crowd_subtype(clause) or crowd_subtype(sent)

        advice_start = m.end(1)

        if crowd:

            cond_label, cond_type = f"游客为{crowd}", "人群"

            cond_fields = _infer_fields(sent, advice_start, ["人群"], cond_label)

        elif WEATHER_RE.search(sent):

            cond_label, cond_type = "天气条件（句内）", "天气"

            cond_fields = _infer_fields(sent, advice_start, ["天气"], cond_label)

        elif TIME_RE.search(sent):

            cond_label, cond_type = "时间条件（句内）", "时间"

            cond_fields = _infer_fields(sent, advice_start, ["时间"], cond_label)

        else:

            cond_label, cond_type = "一般建议", "一般"

            cond_fields = _infer_fields(sent, advice_start, ["装备"], cond_label)

        emitted = False

        for sugg in split_multi_suggestions(clause):

            if re.match(r"^[第其][一二三四五六七八九十]", sugg.strip()):

                continue  # enumeration items ("第二,房卡") are not advice

            pairs.append({"pattern": "建议推断", "trigger": m.group(1),

                          "suggestions": [sugg], "sentence": sent,

                          "condition_type": cond_type, **cond_fields})

            emitted = True

        if emitted:

            return pairs


    # Crowd subject + 可以

    for m in re.finditer(

            r"(老人|老人小孩|带孩子[^。！？；，]{0,6}|带娃|小孩|儿童|婴儿|亲子[^。！？；，]{0,4}|情侣|夫妻|"

            r"孕妇|腿脚[^。！？；，]{0,4}|体力[^。！？；，]{0,4}|新手|第一次[^。！？；，]{0,6}|学生|恐高|晕车)可以([^。！？；]{1,50})", sent):

        crowd, crowd_span = _group_span(sent, m, 1)

        segs = split_multi_suggestions(m.group(2))

        # Extension: re-attach the leading "可以" verb cue to the first segment — advice starts from the verb
        # (without it "可以不下了" would be cut to "不下了" and the 3-char advice dropped by the minimum-length filter)

        if segs:

            segs[0] = "可以" + segs[0]

        for sugg in segs:

            pairs.append({"pattern": "人群可以", "trigger": "可以",

                          "suggestions": [sugg], "sentence": sent,

                          "condition_type": "人群",

                          **_cond(crowd, crowd_span, "inferred", f"游客为{crowd}")})

        return pairs


    # Negative advice

    for m in re.finditer(r"((?<!要)不要(?![要不要门票钱票])|不建议|不宜|(?<![特级区差分别参离告])别(?=[去走买坐赶忘信贪乱省图踩拒绝玩用管抢急费听折腾改])|避免|(?<![不])慎|切勿|(?<![禁])忌|(?<![要])不用(?=[去走买带])|不必(?=[去走买带])|无需|没必要)([^。！？；]{1,50})", sent):

        clause = m.group(0).strip()

        if re.match(r"不要(太多|要好|要太好|不要的)", clause):

            continue  # colloquial exaggerated comparison ("好了不要太多"), not advice

        if COGNITIVE_RE.match(clause):

            continue  # "不要认为/觉得/以为" polarity-reversing rhetoric, not pitfall-avoidance advice

        # Extension: re-extend the verb phrase — the "带/穿/买/选…" phrase before the negative word belongs to the same advice
        # (without it "带老人、小孩慎选" would keep only "慎选", dropping the 3-char advice "带老人、小孩")
        back = sent[max(0, m.start(1) - 8):m.start(1)]
        back_m = re.search(r"(带|穿|买|选|点|准备|记得)([^，。！？；；]{0,6})$", back)
        advice_start = m.start(1)
        if back_m:
            advice_start = max(0, m.start(1) - 8) + back_m.start()
            clause = back_m.group(0) + clause
        clause = clause.rstrip(")）]】")

        if WEATHER_RE.search(sent):

            cond_label, cond_type = "天气条件（句内）", "天气"

            cond_fields = _infer_fields(sent, advice_start, ["天气"], cond_label)

        elif TIME_RE.search(sent):

            cond_label, cond_type = "时间条件（句内）", "时间"

            cond_fields = _infer_fields(sent, advice_start, ["时间"], cond_label)

        elif EQUIP_RE.search(sent):

            cond_label, cond_type = "装备条件（句内）", "装备"

            cond_fields = _infer_fields(sent, advice_start, ["装备"], cond_label)

        else:

            cond_label, cond_type = "一般建议（避雷）", "一般"

            cond_fields = _infer_fields(sent, advice_start, ["人群", "装备"], cond_label)
        for sugg in split_multi_suggestions(clause):

            pairs.append({"pattern": "否定建议", "trigger": m.group(1),

                          "suggestions": [sugg], "sentence": sent,

                          "condition_type": cond_type, **cond_fields})

        return pairs


    return pairs


# Opposing-advice auto-marking: within the same scenic area, negative vs affirmative advice sharing the same core coexist and cite each other's sources.

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

                    continue  # the counterpart must be affirmative

                core_b = AFF_HEDGE_RE.sub("", nb)

                if len(core_b) < 3:

                    continue

                # Longest common prefix serves as the aligned term

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

    return re.sub(r"[\s，,。；;、！？!?\[\]()【】]+", "", s)


def needs_semantic_roles(pair: dict) -> bool:
    """Reserve LTP for inferred conditions and structurally complicated explicit clauses."""
    kind = pair.get('condition_kind')
    condition = pair.get('condition_text', '')
    if kind == 'inferred':
        return True
    if kind != 'explicit' or not condition:
        return False
    trigger = pair.get('trigger', '')
    return (trigger == '若' or '裸' in trigger or len(condition) > 30 or
            bool(re.search(r'建议|推荐|最好|不要|不建议|可以', condition)))


def link_semantic_roles(row: dict) -> list[dict]:
    """Find LTP arguments matching this condition and a predicate in this advice."""
    semantic = row.get('semantic_roles')
    condition = re.sub(r'\s+', '', row.get('condition_text', ''))
    sentence = row.get('sentence', '')
    advice = row.get('suggestion_text', '')
    advice_start = sentence.find(advice) if advice else -1
    condition_span = row.get('condition_span')
    if not semantic or not condition or advice_start < 0 or not condition_span:
        return []
    offsets = []
    cursor = 0
    for token in semantic['tokens']:
        start = sentence.find(token, cursor)
        if start < 0:
            return []
        offsets.append(start)
        cursor = start + len(token)
    links = []
    for pred in semantic['predicates']:
        index = pred['index']
        if not 0 <= index < len(offsets) or not advice_start <= offsets[index] < advice_start + len(advice):
            continue
        for role, text, start, end in pred['arguments']:
            if role not in {'A0', 'ARGM-CND', 'ARGM-TMP', 'ARGM-ADV'} or not (0 <= start <= end < len(offsets)):
                continue
            arg = re.sub(r'\s+', '', text)
            overlap = max(offsets[start], condition_span[0]) < min(offsets[end] + len(semantic['tokens'][end]), condition_span[1])
            similar = ((condition in arg and len(condition) / max(1, len(arg)) >= 0.5) or
                       (arg in condition and len(arg) / max(1, len(condition)) >= 0.65))
            if len(arg) >= 2 and overlap and similar:
                links.append({'predicate': pred['predicate'], 'role': role, 'argument': text,
                              'token_start': start, 'token_end': end})
    return links


def annotate_semantic_roles(pairs: list[dict], model_path: str) -> dict:
    """Annotate selected difficult sentences; rules handle straightforward conditions."""
    from importlib.metadata import version
    import torch
    from ltp import LTP

    torch.set_num_threads(min(4, torch.get_num_threads()))
    model = LTP(model_path)
    selected = [p for p in pairs if needs_semantic_roles(p)]
    sentences = list(dict.fromkeys(p['sentence'] for p in selected))
    cache = {}
    batch_size = 12
    for pos in range(0, len(sentences), batch_size):
        batch = sentences[pos:pos + batch_size]
        output = model.pipeline(batch, tasks=['cws', 'srl'])
        if len(output.cws) != len(batch) or len(output.srl) != len(batch):
            raise ValueError('LTP returned a different number of results than input sentences')
        for sentence, tokens, roles in zip(batch, output.cws, output.srl):
            cache[sentence] = {'tokens': tokens, 'predicates': roles}
        if (pos // batch_size + 1) % 10 == 0 or pos + batch_size >= len(sentences):
            print(f'LTP semantic roles: {min(pos + batch_size, len(sentences))}/{len(sentences)} sentences', flush=True)
    def has_condition(semantic):
        return any(arg[0] == 'ARGM-CND' for pred in semantic['predicates'] for arg in pred['arguments'])
    for pair in selected:
        pair['semantic_roles'] = cache[pair['sentence']]
    model_file = Path(model_path) / 'pytorch_model.bin'
    model_sha256 = None
    if model_file.is_file():
        with model_file.open('rb') as fh:
            model_sha256 = hashlib.file_digest(fh, 'sha256').hexdigest()
    return {'tool': 'LTP', 'package_version': version('ltp'), 'model': model_path,
            'model_file_sha256': model_sha256,
            'tasks': ['cws', 'srl'], 'selection': 'inferred_or_complex_explicit',
            'unique_sentences': len(sentences), 'annotated_pairs': len(selected),
            'sentences_with_predicates': sum(bool(x['predicates']) for x in cache.values()),
            'sentences_with_conditional_role': sum(has_condition(x) for x in cache.values()),
            'pairs_with_conditional_role': sum(has_condition(p['semantic_roles']) for p in selected)}


def main(argv=None) -> int:

    import argparse

    ap = argparse.ArgumentParser()

    ap.add_argument("--no-attribution-filter", action="store_true",

                    help="关闭 P1 句级归属过滤（默认开启：景区外句子不产出条件建议对）")

    ap.add_argument('--ltp-model', default=None,
                    help='使用 LTP 模型目录或模型名执行分词和语义角色标注')

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

                continue  # P1 attribution filter: outside-area sentences produce no conditional-advice pairs

            if not (8 <= len(sent) <= 160):

                continue

            if skip_sentence(sent):

                continue  # platform boilerplate / appeal sentence / joint-tour city paragraph guard

            for p in extract_from_sentence(sent):

                ctype = p.get("condition_type") or classify_condition(p.get("condition_text", ""))

                cfields = {key: p.get(key) for key in (
                    "condition_text", "condition_span", "condition_kind",
                    "condition_label", "condition_absent_reason", "condition_negated")}

                # Safety net: any pair that did not go through a condition-aware emit site
                # must still satisfy the verbatim-or-absent invariant.
                if not cfields["condition_kind"]:

                    if cfields["condition_text"]:

                        span, _ = _span_in(sent, cfields["condition_text"])

                        if span:

                            cfields.update(condition_span=span, condition_kind="explicit")

                        else:

                            cfields.update(condition_label=cfields["condition_text"],

                                           condition_text="", condition_span=None,

                                           condition_kind="absent",

                                           condition_absent_reason="label_unmapped")

                    else:

                        cfields.update(condition_kind="absent", condition_span=None,

                                       condition_absent_reason="no_keyword")

                for sugg in p["suggestions"]:

                    if len(norm(sugg)) < 4:

                        continue

                    polarity = "NEG" if p["pattern"] == "否定建议" else "POS"
                    all_pairs.append({"polarity": polarity,

                        "record_id": row["record_id"], "scenic_area": row["scenic_area"],

                        "source_platform": row["source_platform"], "text_type": row["text_type"],

                        "pattern": p["pattern"], "trigger": p["trigger"],

                        "condition_text": cfields["condition_text"],

                        "condition_span": cfields["condition_span"],

                        "condition_kind": cfields["condition_kind"],

                        "condition_label": cfields["condition_label"] or "",

                        "condition_absent_reason": cfields["condition_absent_reason"],

                        "condition_negated": bool(cfields["condition_negated"]),

                        "suggestion_text": sugg,

                        "condition_type": ctype, "sentence": p["sentence"],

                    })


    # Condition-type refinement (batch)
    for p in all_pairs:
        p["condition_type"] = refine_condition_type(
            p.get("condition_text", ""), p.get("suggestion_text", ""),
            p.get("condition_type", "其他"))
        p["condition_type_verified"] = (classify_condition(p["condition_text"])
                                        if p["condition_text"] else "无")

    # Sequential ids (assigned before dedup so every merged row keeps its member ids)
    counter = [0]
    for p in all_pairs:
        _assign_pair_id(p, counter)

    validate_pairs(all_pairs)

    srl_stats = annotate_semantic_roles(all_pairs, args.ltp_model) if args.ltp_model else None

    # Dedup: same scenic area + condition provenance/label + normalized condition/advice text

    merged: dict[tuple, dict] = {}

    near_dup = 0

    for p in all_pairs:

        key = (p["scenic_area"], p["condition_kind"], norm(p["condition_label"])[:24],
               norm(p["condition_text"])[:24], norm(p["suggestion_text"])[:40])

        if key in merged:

            merged[key]["sources"].append(p["record_id"])

            merged[key]["pair_ids"].append(p["pair_id"])

            near_dup += 1

            continue

        merged[key] = {**p, "sources": [p["record_id"]], "pair_ids": [p["pair_id"]]}

    mapping = list(merged.values())

    mapping = mark_opposing(mapping)

    _opp = [r for r in mapping if r.get("opposing")]

    (OUT / "opposing_pairs.json").write_text(json.dumps({

        "n_marked_rows": len(_opp),

        "pairs": [{"scenic_area": r["scenic_area"], "term": r["opposing"]["term"],

                   "suggestion": r["suggestion_text"][:60],

                   "opposing_with": r["opposing"]["with"], "sources": r.get("sources", [])[:3]}

                  for r in _opp]}, ensure_ascii=False, indent=1), encoding="utf-8")

    for m in mapping:

        m["frequency"] = len(m["sources"])

        m["sources"] = list(dict.fromkeys(m["sources"]))

        m["pair_ids"] = list(dict.fromkeys(m["pair_ids"]))

    nonempty_before_refinement = sum(bool(m["condition_text"]) for m in mapping)
    refined_mapping = []
    refinement_counts = Counter()
    for item in mapping:
        corrected, changes = refine(item)
        if corrected.get('semantic_roles'):
            corrected['semantic_role_links'] = link_semantic_roles(corrected)
        if changes:
            refinement_counts["changed_rows"] += 1
            refinement_counts.update(changes)
        refined_mapping.append(corrected)
    mapping = refined_mapping
    if srl_stats is not None:
        srl_stats['mapping_rows_with_linked_roles'] = sum(bool(m.get('semantic_role_links')) for m in mapping)


    OUT.mkdir(parents=True, exist_ok=True)

    with (OUT / "conditional_pairs.jsonl").open("w", encoding="utf-8") as fh:

        for p in all_pairs:

            fh.write(json.dumps(p, ensure_ascii=False) + "\n")

    (OUT / "mapping_table.json").write_text(

        json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")


    kind_raw = Counter(p["condition_kind"] for p in all_pairs)
    kind_dedup = Counter()
    for m in mapping:
        kind_dedup[m["condition_kind"]] += m["frequency"]
    nonempty_raw = sum(1 for p in all_pairs if p["condition_text"])
    nonempty_dedup = sum(m["frequency"] for m in mapping if m["condition_text"])
    pattern_kind = defaultdict(Counter)
    for p in all_pairs:
        pattern_kind[p["pattern"]][p["condition_kind"]] += 1

    stats = {

        "semantic_roles": srl_stats,

        "condition_refinement": {
            "input_rows": len(mapping),
            "nonempty_before": nonempty_before_refinement,
            "nonempty_after": sum(bool(m["condition_text"]) for m in mapping),
            "changes": dict(refinement_counts),
        },

        "raw_pairs": len(all_pairs),

        "after_dedup": len(mapping),

        "duplicates_merged": near_dup,

        "by_pattern": dict(Counter(p["pattern"] for p in all_pairs)),
        "by_polarity": dict(Counter(p.get("polarity", "POS") for p in all_pairs)),

        "by_condition_type": dict(Counter(p["condition_type"] for p in all_pairs)),

        "by_condition_type_verified": dict(Counter(p["condition_type_verified"] for p in all_pairs)),

        "by_condition_kind": dict(kind_raw),

        "by_condition_kind_dedup": dict(kind_dedup),

        "by_pattern_condition_kind": {k: dict(v) for k, v in pattern_kind.items()},

        "by_condition_label": dict(Counter(
            p["condition_label"] for p in all_pairs if p["condition_label"])),

        "by_absent_reason": dict(Counter(
            p["condition_absent_reason"] for p in all_pairs if p["condition_absent_reason"])),

        "nonempty_condition_pairs": nonempty_raw,

        "absent_condition_pairs": len(all_pairs) - nonempty_raw,

        "nonempty_condition_rate": round(nonempty_raw / max(1, len(all_pairs)), 3),

        "nonempty_condition_rows": sum(1 for m in mapping if m["condition_text"]),

        "nonempty_condition_row_rate": round(
            sum(1 for m in mapping if m["condition_text"]) / max(1, len(mapping)), 3),

        "nonempty_condition_rate_dedup": round(nonempty_dedup / max(1, len(all_pairs)), 3),

        "condition_type_mismatch": sum(
            1 for p in all_pairs
            if p["condition_text"] and p["condition_type_verified"] != p["condition_type"]),

        "label_like_nonempty": sum(
            1 for p in all_pairs
            if p["condition_text"] in LEGACY_LABELS or p["condition_text"].startswith("游客为")),

        "condition_span_invalid": 0,

        "sentence_max_len": max((len(p["sentence"]) for p in all_pairs), default=0),

        "sentence_truncated_pairs": sum(1 for p in all_pairs if len(p["sentence"]) > 160),

        "dedup_key_version": "v2:scenic|kind|label|condition|suggestion",

        "by_scenic": dict(Counter(p["scenic_area"] for p in all_pairs)),

        "by_text_type": dict(Counter(p["text_type"] for p in all_pairs)),

        "crowd_breakdown": dict(Counter(

            crowd_subtype(p["condition_text"] or p.get("condition_label", "")) or "未细分"

            for p in all_pairs if p["condition_type"] == "人群")),

    }

    (OUT / "extraction_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps(stats, ensure_ascii=False, indent=1))

    return 0


if __name__ == "__main__":

    raise SystemExit(main())
