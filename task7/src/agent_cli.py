"""实验7：旅游规划 Agent（ReAct 模式）。

组成：
  - LLMClient：任意 OpenAI 兼容接口（config.json 配置 base_url/api_key/model）；
    未配置时 llm_available=False，Agent 使用内置规则规划器（意图解析、路线编排、文案生成全部离线可复现）。
  - IntentParser：提取 景区/游客类型/时长/特殊需求/起点 约束（LLM 模式走 Prompt，规则模式走关键词表）。
  - ReActAgent：思考→行动（调用 GraphTools）→观察→…→最终回答 的显式循环，
    每一步记录 trace（thought/action/observation），工具调用结果实际参与行程编排。
运行：python src/agent_cli.py            （交互命令行）
      python src/run_tests.py            （6 个场景批量测试并落盘证据）
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from graph_tools import AREAS, GraphTools  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

VISITOR_PATTERNS = [
    ("老人", r"老人|爸妈|父母|银发|奶奶|爷爷|长辈|岳父|岳母|外婆|外公"),
    ("孩子", r"孩子|小孩|儿童|带娃|娃|儿子|女儿|幼儿园|闺女|小朋友|宝贝"),
    ("亲子", r"亲子|家庭|一家"),
    ("情侣", r"情侣|夫妻|蜜月|约会|女朋友|男朋友|对象|另一半|爱人"),
    ("体力有限", r"体力(不好|差|有限|不足)|腿脚|孕妇|高反"),
    ("初次游览", r"第一次|首次|没去过"),
]
DURATION_PATTERNS = [
    (3.5, r"三天半|三日半|3\.5\s*天"),
    (3, r"(?<![\d.])3\s*天|三天|三日"),
    (4, r"(?<![\d.])4\s*天|四天|四日"),
    (5, r"(?<![\d.])5\s*天|五天|五日"),
    (2, r"两日|两天|(?<![\d.])2\s*天|二日|周末游"),
    (1.5, r"一天半|一日半|(?<![\d.])1\.5\s*天"),
    (1, r"一日|一天|(?<![\d.])1\s*天(?!夜)|当日"),
    (0.5, r"半天|半日|([0-9一二两三])\s*小时"),
]
SPECIAL_PATTERNS = [
    ("看日出", r"日出|朝霞"), ("避开人流", r"人少|避开|错峰|不挤"),
    ("省力", r"省力|轻松|不累|少走|不想太累|不要太累|不想走太多|走路要少|少走路"), ("红叶", r"红叶|秋色|赏秋"),
    ("拍照片", r"拍照|出片|机位"), ("滑雪", r"滑雪|温泉"),
]
# 出行月份（规则口径）：月份短语/季节词/节假日 → 代表月份（时段可行性）
TRIP_MONTH_PATTERNS = [
    (10, r"(?<!\d)10月|十月|秋季|秋天|国庆"), (11, r"(?<!\d)11月|十一月"), (12, r"(?<!\d)12月|十二月|冬季|冬天"),
    (1, r"(?<!\d)1月|一月|寒假|元旦"), (2, r"(?<!\d)2月|二月|春节|过年"), (3, r"(?<!\d)3月|三月"),
    (4, r"(?<!\d)4月|四月|春季|春天"), (5, r"(?<!\d)5月|五月|五一"), (6, r"(?<!\d)6月|六月"),
    (7, r"(?<!\d)7月|七月|暑假|夏季|夏天"), (8, r"(?<!\d)8月|八月"), (9, r"(?<!\d)9月|九月"),
]
SEASON_MONTHS = {"冬季": {12, 1, 2}, "冬天": {12, 1, 2}, "夏季": {6, 7, 8}, "夏天": {6, 7, 8},
                 "春季": {3, 4, 5}, "春天": {3, 4, 5}, "秋季": {9, 10, 11}, "秋天": {9, 10, 11}}


def extract_condition_months(text: str) -> set:
    """条件文本中的月份集合：单月/月份区间（4-11月份、10月中旬-11月中旬）/季节词。"""
    months = set()
    for m in re.finditer(r"(1[0-2]|[1-9])\s*月?[^，。；、！？]{0,3}?[-—~到至]\s*(1[0-2]|[1-9])\s*月", text):
        a, b = int(m.group(1)), int(m.group(2))
        if a <= b:
            months.update(range(a, b + 1))
    for m in re.finditer(r"(1[0-2]|[1-9])\s*月(?:份|底|初|中旬|上旬|下旬)?", text):
        months.add(int(m.group(1)))
    for w, ms in SEASON_MONTHS.items():
        if w in text:
            months.update(ms)
    return months


class LLMClient:
    """OpenAI 兼容 ChatCompletion 客户端；未配置时不可用，Agent 走规则模式。"""

    def __init__(self, config_path: Path | None = None):
        cfg = {}
        cfg_path = Path(config_path) if config_path else ROOT / "config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.base_url = str(cfg.get("base_url", "")).rstrip("/")
        self.api_key = str(cfg.get("api_key", ""))
        self.model = str(cfg.get("model", ""))
        # 占位模板（config.example.json）不算已配置
        placeholder = any(k in self.api_key for k in ("填入", "你的", "placeholder", "xxx"))
        self.available = bool(self.base_url and self.api_key and self.model) and not placeholder

    def complete(self, system: str, user: str, temperature: float = 0.4) -> str:
        if not self.available:
            raise RuntimeError("LLM 未配置")
        body = json.dumps({"model": self.model,
                           "messages": [{"role": "system", "content": system},
                                        {"role": "user", "content": user}],
                           "temperature": temperature}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}",
                     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) scenic-guide-agent/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


INTENT_PROMPT = """你是旅游规划助手。从用户输入中提取约束，输出 JSON：
{"scenic": "黄山|九寨沟|颐和园|未知", "visitor_type": "老人|孩子|亲子|情侣|体力有限|初次游览|null",
 "days": 1, "month": 出行月份数字(1-12)或null,
 "special": ["看日出|避开人流|省力|红叶|拍照片" 中的若干或空数组]}
只输出 JSON，不要解释。用户输入："""


class IntentParser:
    def __init__(self, llm: LLMClient | None):
        self.llm = llm

    def parse(self, query: str, trace: list) -> dict:
        llm_intent = None
        if self.llm and self.llm.available:
            try:
                raw = self.llm.complete(INTENT_PROMPT, query, temperature=0)
                llm_intent = json.loads(re.search(r"\{.*\}", raw, re.S).group())
            except Exception as exc:  # 网络失败回退规则
                trace.append({"step": "intent", "thought": f"LLM 解析失败（{exc}），回退规则解析", "via": "fallback"})
        if llm_intent is not None:
            rule_intent = self._parse_rules(query)
            # 混合：规则精确字段（时长正则/景区词表/人群词表）优先，规则缺省处用 LLM 补
            merged = dict(rule_intent)
            if merged.get("scenic") in (None, "未知") and llm_intent.get("scenic"):
                merged["scenic"] = llm_intent["scenic"]
            if not merged.get("visitor_type") and llm_intent.get("visitor_type"):
                merged["visitor_type"] = llm_intent["visitor_type"]
            merged_days = self._merge_days(merged.get("days"), merged.get("days_explicit", False),
                                            llm_intent.get("days"))
            if merged_days is not None:
                merged["days"] = merged_days
            if not merged.get("special") and llm_intent.get("special"):
                merged["special"] = llm_intent["special"]
            if merged.get("month") is None and llm_intent.get("month"):
                try:
                    merged["month"] = int(llm_intent["month"])
                except (TypeError, ValueError):
                    pass
            trace.append({"step": "intent", "thought": "混合解析：规则精确字段优先，LLM 补缺省", "via": "hybrid",
                          "rule": rule_intent, "llm": llm_intent, "result": merged})
            return merged
        return self._parse_rules(query)

    @staticmethod
    def _merge_days(rule_days, rule_explicit: bool, llm_days):
        """规则显式给定的时长不被 LLM 覆盖；LLM 值须为 0.5–5 的数值，否则忽略。"""
        if isinstance(llm_days, bool) or not isinstance(llm_days, (int, float)):
            return rule_days
        v = float(llm_days)
        if not (0 < v <= 5):
            return rule_days
        if rule_explicit:
            return rule_days
        return v if v != rule_days else rule_days

    def _parse_rules(self, query: str) -> dict:
        scenic = next((a for a in AREAS if a in query), None)
        if scenic is None:
            # 景区别名映射（“九寨”→“九寨沟”等常见简称）
            for _alias, _target in (("九寨", "九寨沟"), ("黄山市", "黄山"), ("黄龙九寨", "九寨沟")):
                if _alias in query:
                    scenic = _target
                    break
        visitor_hits = [v for v, pat in VISITOR_PATTERNS if re.search(pat, query)]
        visitor = visitor_hits[0] if visitor_hits else None
        days = 1
        days_explicit = False
        for d, pat in DURATION_PATTERNS:
            if re.search(pat, query):
                days = d
                days_explicit = True
                break
        special = [s for s, pat in SPECIAL_PATTERNS if re.search(pat, query)]
        # 不去地点——前缀否定（不要去/不想去/不去/避开/别安排/别去/不想逛）
        # 与后置否定（“X就不去了”）；必去地点——前缀（一定要去/一定要逛/必去/必须去）
        # 与后置（“X是必去的”）。后置模式收紧锚点（就不去/是必去），避免误捕。
        avoid = [m.group(1).strip() for m in
                 re.finditer(r"(?:不要去|不想去|不去|避开|别安排|别去|不想逛)\s*([一-龥A-Za-z0-9]{2,10})", query)]
        avoid += [m.group(1).strip() for m in
                  re.finditer(r"([一-龥A-Za-z0-9]{2,10})\s*就不去了?", query)]
        # 否定表达变体：POI前置否定（“原始森林不要去”）、“除了X都行”、
        # “X就别安排了”（千万/切记等副词不入捕获）
        avoid += [m.group(1).strip() for m in
                  re.finditer(r"([一-龥A-Za-z0-9]{2,10})(?<!千万)(?<!切记)\s*(?:不要去|别去)", query)]
        avoid += [m.group(1).strip() for m in
                  re.finditer(r"除了\s*([一-龥A-Za-z0-9]{2,10})\s*(?:都|以外|之外)", query)]
        avoid += [m.group(1).strip() for m in
                  re.finditer(r"([一-龥A-Za-z0-9]{2,10})\s*就别(?:安排|去|考虑)", query)]
        must = [m.group(1).strip() for m in
                re.finditer(r"(?:一定要去|一定要逛|必须去|必去)\s*([一-龥A-Za-z0-9]{2,10})", query)]
        must += [m.group(1).strip() for m in
                 re.finditer(r"([一-龥A-Za-z0-9]{2,10})是必去", query)]
        avoid, must = list(dict.fromkeys(avoid)), list(dict.fromkeys(must))
        month = next((m for m, pat in TRIP_MONTH_PATTERNS if re.search(pat, query)), None)
        return {"scenic": scenic or "未知", "visitor_type": visitor, "visitor_types": visitor_hits,
                "days": days, "days_explicit": days_explicit,
                "month": month, "special": special, "avoid": avoid, "must": must}


class ReActAgent:
    """思考→行动→观察循环；规划器在规则模式下同样按“意图→选点→排序→时段→贴士”五步走。"""

    def __init__(self, llm: LLMClient | None = None):
        self.tools = GraphTools()
        self.llm = llm
        self.parser = IntentParser(llm)

    # ── 规则模式规划 ────────────────────────────────────────────
    def _plan_rule(self, intent: dict, trace: list) -> dict:
        scenic, days, visitor = intent["scenic"], intent["days"], intent["visitor_type"]
        limit = {0.5: 5, 1: 8, 1.5: 9, 2: 11, 3: 12, 3.5: 13, 4: 14, 5: 15}.get(days, 11)
        # 特殊需求参与选点——“省力”映射到体力有限的人群证据（负向建议已降权）
        # 多人群（如“带老人和孩子”）→ 条件查询与贴士按人群列表匹配
        visitor_types = intent.get("visitor_types") or ([visitor] if visitor else [])
        visitor_eff = ("体力有限" if ("省力" in (intent.get("special") or []) and not visitor)
                       else (visitor_types if visitor_types else visitor))
        pois_res = self.tools.call("query_pois", {"scenic": scenic, "visitor_type": visitor_eff, "limit": limit}, trace)
        route_res = self.tools.call("query_route", {"scenic": scenic, "days": days if days <= 2 else 2}, trace)
        cond_res = self.tools.call("query_conditions", {"scenic": scenic, "visitor_type": visitor_eff}, trace)
        trace.append({"step": "thought", "thought": f"约束={intent}；先查核心 POI（limit={limit}），"
                     "再取官方路线做编排骨架，最后按游客类型取条件贴士"})

        selected = [p["poi"] for p in pois_res["pois"]]
        # 软偏好参与选点排序——"拍照片"把挂有拍照类条件的已选 POI 前置
        # （稳定排序只提位不新增；此前该特殊需求仅被解析、从未作用于规划）
        photo_pois: set = set()
        if "拍照片" in (intent.get("special") or []):
            for poi in list(selected):
                pc = self.tools.call("query_poi_conditions", {"scenic": scenic, "poi": poi}, trace)
                if any(c.get("cond_type") == "拍照" for c in pc.get("conditions", [])):
                    photo_pois.add(poi)
            if photo_pois:
                trace.append({"step": "thought",
                              "thought": f"软偏好「拍照片」：{sorted(photo_pois)} 挂有拍照点位条件（编排后前置）"})
        # 不去地点从行程剔除并说明；必去地点优先保留
        avoid = [a for a in (intent.get("avoid") or []) if a]
        must = [m0 for m0 in (intent.get("must") or []) if m0]
        special_notes: list[str] = []
        removed_by_avoid = []
        # 多日行程自动注入住宿 POI
        if days and days >= 2:
            has_lodging = any(any(k in p for k in ("宾馆", "酒店", "民宿", "饭店")) for p in selected)
            if not has_lodging:
                lodging = self._find_lodging_poi(scenic)
                if lodging and lodging not in selected:
                    selected.append(lodging)
        if avoid:
            kept = []
            for poi in selected:
                if any(a in poi or poi in a for a in avoid):
                    removed_by_avoid.append(poi)
                else:
                    kept.append(poi)
            selected = kept
            trace.append({"step": "thought", "thought": f"不去地点过滤：移除 {removed_by_avoid or '无'}"})
            # 最小放宽建议：避开较多导致行程明显精简时，给出可放宽方向（不替用户放宽）
            if len(removed_by_avoid) >= 2 and len(selected) <= 3:
                special_notes.append("您避开的景点较多，行程较精简；"
                                     "如需更丰富的安排，可放宽部分\"不去\"地点后再试")
        # 必去地点落实（ 后半——此前 must 仅抽取、从未作用于规划）。
        # 已选/解析到的必去项一律进入豁免名单（must_keep），豁免时段预算裁剪（硬约束优先，）；
        # 解析失败如实说明。
        must_keep: list[str] = []
        for m0 in must:
            hit = next((p for p in selected if m0 in p or p in m0), None)
            if hit:
                must_keep.append(hit)
                special_notes.append(f"必去：{hit} 已在行程中")
                continue
            node = self.tools._resolve_poi(scenic, m0)
            if node is not None:
                label = self.tools.poi_label(node)
                if label not in selected:
                    selected.append(label)
                    must_keep.append(label)
                    special_notes.append(f"必去：{label} 已加入行程")
                else:
                    must_keep.append(label)
                    special_notes.append(f"必去：{label} 已在行程中")
            else:
                special_notes.append(f"必去：{m0} 未在{scenic}景点库中找到，请确认名称或咨询景区")
        if must:
            trace.append({"step": "thought",
                          "thought": f"必去地点处理：{len(must_keep)} 个进入豁免名单"
                                     f"（含新加入），未找到项见贴士"})
        # 模板选择：query_route 返回的路线作为首选候选参与覆盖率竞争——
        # 工具结果真实进入决策；未入选时 trace 如实说明原因
        cands = self.tools.routes_by_scenic(scenic, days if days <= 2 else 2)
        best_route, best_pos, best_cov = None, {}, 0.0
        for r in cands:
            pos = {}
            for st in r["steps"]:
                for poi in [x["normalized"] for x in st["pois"]]:
                    pos.setdefault(poi, (st["day"], st["step_no"], st["period"], st["transport"]))
            cov = sum(1 for poi in selected if poi in pos) / max(1, len(selected))
            if cov > best_cov:
                best_route, best_pos, best_cov = r, pos, cov
        template_cov_low = best_cov < 0.6
        template_pos = best_pos if not template_cov_low else {}
        template = best_route["route_title"] if best_route else ""
        _sunrise_poi = None
        ordered = self._order_pois(scenic, selected, template_pos)
        # 软偏好提升在编排序之后生效（此前置于 selected 上会被 _order_pois 覆盖）
        if photo_pois:
            ordered.sort(key=lambda x: x not in photo_pois)
            trace.append({"step": "thought",
                          "thought": f"软偏好「拍照片」提升：{sorted(photo_pois)} 前置于行程"})
        if removed_by_avoid:
            special_notes.append("已按您的要求避开：" + "、".join(removed_by_avoid))
        lodging_in_plan = [p for p in selected if any(k in p for k in ("宾馆", "酒店", "民宿"))]
        if lodging_in_plan and days and days >= 2:
            special_notes.append(f"住宿：{lodging_in_plan[0]} 已纳入行程（多日游建议山上住宿）")
        if "看日出" in (intent.get("special") or []) and days and days >= 2:
            _sunrise_poi = self._find_sunrise_poi(scenic, ordered)
            if _sunrise_poi:
                special_notes.append(f"看日出：{_sunrise_poi} 已安排在最后一日首位（清晨前往），需前晚住宿山上或山顶酒店")
            else:
                special_notes.append("看日出：已选景点中无日出观景点（如光明顶），如需看日出请将其加入需求")
            trace.append({"step": "thought", "thought": f"特殊需求「看日出」编排：{special_notes[-1]}"})
        qr_selected = bool(best_route) and best_route.get("route_id") == route_res.get("route_id")
        trace.append({"step": "thought", "thought": f"编排骨架：模板“{template}”覆盖已选 POI 的 {best_cov:.0%}"
                     + ("；query_route 返回的路线入选" if qr_selected else
                        "；query_route 返回的路线覆盖率不足，另选覆盖最高者")
                     + ("；覆盖率不足 60%，改用图谱先后边拓扑排序" if template_cov_low else "")})
        # 工具4：官方后继校验（/§4.1-3）——结果真实作用于决策：
        # 在 itinerary 构建前调用，后继调序直接影响行程内容
        if len(ordered) >= 2:
            order_res = self.tools.call("query_order", {"scenic": scenic, "poi": ordered[0]}, trace)
            succ = (order_res.get("successors") or [])
            succ_labels = [x.get("name") if isinstance(x, dict) else str(x) for x in succ]
            official_next = next((x for x in succ_labels if x in ordered[1:]), None)
            if official_next and ordered[1] != official_next:
                j = ordered.index(official_next)
                ordered[1], ordered[j] = ordered[j], ordered[1]
                trace.append({"step": "thought",
                              "thought": f"query_order 后继校验：官方后继 {official_next} 原在 第{j + 1} 位，"
                                         f"已调整至第 2 位以符合主流动线"})
            else:
                trace.append({"step": "thought",
                              "thought": f"query_order 后继校验：{'无已选后继，维持现有顺序' if not official_next else '第二站已是官方后继，无需调整'}"})
        # 时段预算——限制每日 POI 数量（半日≤3、一日≤5、多日≤每日4）
        n_days = max(1, int(days) if days and days >= 1 else 1)
        ordered = self._apply_time_budget(ordered, days, n_days, _sunrise_poi, special_notes, trace)
        # 必去地点豁免时段预算裁剪（硬约束优先，）——被裁剪则回填
        if must_keep:
            missing = [p for p in dict.fromkeys(must_keep) if p not in ordered]
            if missing:
                ordered.extend(missing)
                trace.append({"step": "thought",
                              "thought": f"必去地点豁免预算裁剪：{missing} 已回填行程"})

        # 天数/时段分配（/）：n_days 对 0.5/1/1.5/2/3/3.5/4/5 全部成立；
        # 2 日且模板全覆盖时沿用模板的天与时段，否则按切分块分配；半日时段封顶于上午/中午；
        # 住宿节点固定晚上。天号一律写入行程，不再出现“1.5/3 天全部落第 1 天”。
        period_cycle = ["上午", "上午", "中午", "下午", "下午", "晚上"]
        n_days = max(1, int(days) if days and days >= 1 else 1)
        split = (len(ordered) + n_days - 1) // n_days
        per_day = [ordered[i * split:(i + 1) * split] for i in range(n_days)
                   if ordered[i * split:(i + 1) * split]]
        template_ok = not template_cov_low and days == 2
        itinerary = []
        for i, poi in enumerate(ordered):
            day, step, period, transport = template_pos.get(poi, (None, None, "", []))
            if not (template_ok and day is not None and period):
                for d, chunk in enumerate(per_day):
                    if poi in chunk:
                        day = d + 1
                        idx = chunk.index(poi)
                        period = period_cycle[min(idx, len(period_cycle) - 1)]
                        break
                else:
                    day = day or 1
            is_lodging = any(k in poi for k in ("宾馆", "饭店", "酒店", "民宿"))
            if is_lodging:
                period = "晚上"
            if days == 0.5:
                # 半日时段封顶于上午/中午，不出现下午/晚上
                period = {"下午": "中午", "晚上": "中午"}.get(period, period)
            itinerary.append({
                "order": len(itinerary) + 1, "day": min(day or 1, n_days),
                "period": period,
                "poi": poi,
                "transport_from_prev": (transport[0] if transport else
                                        (self._transport_between(ordered[i - 1], poi, scenic) if i else "入园")),
                "note": ("与游客类型适配" if any(
                    x["poi"] == poi and x["visitor_fit"] > 0 for x in pois_res["pois"]) else "")
                + ("，建议宿此" if is_lodging else ""),
            })
        # §4.1-2：住宿/日出 天号与时段覆盖——保证"前晚住宿→次日清晨观景"的时间先后
        if days and days >= 2:
            PERIOD_ORD = {"上午": 0, "中午": 1, "下午": 2, "晚上": 3}
            # 住宿 → 第 n_days-1 天晚上（前晚住宿）
            for it in itinerary:
                if any(k in it["poi"] for k in ("宾馆", "酒店", "民宿")):
                    it["day"] = max(1, n_days - 1)
                    it["period"] = "晚上"
            # 日出 → 第 n_days 天上午，且排在该日首位
            if _sunrise_poi:
                for it in itinerary:
                    if it["poi"] == _sunrise_poi:
                        it["day"] = n_days
                        it["period"] = "上午"
            # 日内按时段排序（保证单调性），日出 POI 排该日首位
            itinerary.sort(key=lambda x: (x["day"],
                                          PERIOD_ORD.get(x["period"], 9),
                                          0 if x["poi"] == _sunrise_poi else 1))
            for i, it in enumerate(itinerary):
                it["order"] = i + 1

        # P6 行程可行性校验（时段化）：封禁/不建议类按 提示；条件文本含月份窗口时按出行月份判定——
        # 封禁类月份命中 → 升级为时段冲突；正类窗口（开放/适合/精华）且出行月不在窗口 → 出行时段提示
        feasibility_warnings = []
        seen_warn = set()
        import re as _re
        CLOSURE_RE = _re.compile(r"封山|封闭|轮休|停运|关闭|不开放|暂停|停止接待|限流|不建议|不宜|不去|不适合|慎入|谨慎")
        WINDOW_RE = _re.compile(r"开放|适合|最美|精华|推荐|值得|绝佳")
        trip_month = intent.get("month")
        for poi in ordered[:10]:
            pc = self.tools.call("query_poi_conditions", {"scenic": scenic, "poi": poi}, trace)
            for c in pc.get("conditions", []):
                text = c["condition"] + c["suggestion"]
                months = extract_condition_months(text)
                if CLOSURE_RE.search(text):
                    w = f'{poi}：{c["condition"][:26]}——{c["suggestion"][:40]}'
                    if months and trip_month and trip_month in months:
                        w = f'{poi}（时段冲突，您出行的{trip_month}月适逢条件所述月份）：{c["condition"][:26]}——{c["suggestion"][:40]}'
                    if w not in seen_warn:
                        seen_warn.add(w)
                        feasibility_warnings.append(w)
                elif (months and trip_month and trip_month not in months
                      and WINDOW_RE.search(text)):
                    span = "/".join(str(m) for m in sorted(months))
                    w = (f'{poi}（时段提示）：条件建议集中于{span}月，您计划的{trip_month}月'
                         f'不在其中——{c["condition"][:24]}，请先确认当期开放情况')
                    if w not in seen_warn:
                        seen_warn.add(w)
                        feasibility_warnings.append(w)
        # 景区级时段窗口：直查图谱全部条件节点（query_conditions 按 visitor/limit 截断，会漏一般类）
        if trip_month:
            n_win = 0
            for n, d in self.tools.G.nodes(data=True):
                if d.get("kind") != "条件" or f":{scenic}:" not in n:
                    continue
                text = (d.get("name") or "") + (d.get("suggestion") or "")
                months = extract_condition_months(text)
                if (months and trip_month not in months
                        and WINDOW_RE.search(text) and not CLOSURE_RE.search(text)):
                    span = "/".join(str(m) for m in sorted(months))
                    w = (f'{scenic}（时段提示）：条件建议集中于{span}月，您计划的{trip_month}月'
                         f'不在其中——{(d.get("name") or "")[:24]}，请确认当期景点开放情况')
                    n_win += 1
                    if w not in seen_warn:
                        seen_warn.add(w)
                        feasibility_warnings.append(w)
            if n_win:
                trace.append({"step": "thought", "thought": f"时段窗口扫描：{n_win} 条条件节点含月份窗口"
                              f"且与出行月 {trip_month} 不符，已生成时段提示"})
        trace.append({"step": "thought", "thought": f"可行性校验：{len(feasibility_warnings)} 条封禁/不建议提示"
                     + ("；已附加到对应站点" if feasibility_warnings else "")})
        for it in itinerary:
            hit = [w for w in feasibility_warnings if w.startswith(f'{it["poi"]}：')]
            if hit:
                it["note"] = (it["note"] + "；" if it["note"] else "") + "⚠ " + hit[0][len(it["poi"]) + 1:52]
        other_area_kw = ("慕田峪", "长城", "故宫", "天坛", "香山", "圆明园", "乌镇", "西塘", "三清山",
                         "庐山", "峨眉", "泰山", "华山", "武夷山", "丽江", "张家界", "八达岭", "十三陵",
                         "北海公园", "景山", "雍和宫", "恭王府", "什刹海", "南锣鼓巷")
        suggest_cue = ("建议", "最好", "记得", "不要", "别", "避免", "推荐", "可以", "适合",
                       "务必", "千万", "小心", "注意", "提前", "预约", "必备", "慎", "尽量")
        tips = [c for c in cond_res.get("conditions", [])
                if not any(k in c["condition"] + c["suggestion"] for k in other_area_kw)
                and (c["cond_type"] == "人群" or any(k in c["suggestion"] for k in suggest_cue))][:6]
        # 编排来源如实标注——模板覆盖不足 60% 时未采用官方路线，不得冒充官方来源
        if template and not template_cov_low:
            template_src = f'（参考官方路线 {route_res.get("route_id", "")} {template}）'
        else:
            template_src = "（编排依据：图谱游客动线拓扑排序，未匹配到合适的官方路线）"
        return {"scenic": scenic, "days": days, "visitor_type": visitor, "special": intent["special"],
                "special_notes": special_notes, "trip_month": intent.get("month"),
                "itinerary": itinerary, "tips": tips, "feasibility_warnings": feasibility_warnings,
                "template_used": bool(template and not template_cov_low),
                "template_route": f'{route_res.get("route_id", "")} {route_res.get("route_title", "")}',
                "template_src": template_src}

    def _apply_time_budget(self, ordered: list[str], days, n_days: int, _sunrise_poi,
                           special_notes: list, trace: list) -> list[str]:
        """时段预算——限制每日 POI 数量（半日≤3、一日≤5、多日≤每日4）。

        日出/住宿 POI 不受裁剪（它们是多日行程的结构性锚点）。
        独立成方法以便  消融整体禁用。
        """
        daily_budget = {0.5: 3, 1: 5, 1.5: 4, 2: 4, 3: 4, 3.5: 4, 4: 4, 5: 4}.get(days, 4)
        _anchored = set()
        if _sunrise_poi:
            _anchored.add(_sunrise_poi)
        _anchored.update(p for p in ordered if any(k in p for k in ("宾馆", "酒店", "民宿")))
        max_pois = daily_budget * n_days + len(_anchored)
        if len(ordered) > max_pois:
            dropped = [p for p in ordered[max_pois:] if p not in _anchored]
            kept_tail = [p for p in ordered[max_pois:] if p in _anchored]
            ordered = ordered[:max_pois] + kept_tail
            special_notes.append(f"时间预算限制：已裁剪 {len(dropped)} 个景点（{', '.join(dropped[:3])}等），建议根据体力取舍")
            trace.append({"step": "thought",
                          "thought": f"时段预算：每日上限 {daily_budget}，总 {n_days} 天，裁剪 {len(dropped)} 个 POI"})
        return ordered

    def _find_lodging_poi(self, scenic: str) -> str | None:
        """找景区内住宿 POI（名称含宾馆/酒店/民宿/饭店，度数最高者）。"""
        best, best_deg = None, 0
        for n in self.tools.poi_nodes(scenic):
            label = self.tools.G.nodes[n].get("label", "")
            if any(k in label for k in ("宾馆", "酒店", "民宿", "饭店")):
                deg = self.tools.G.degree(n)
                if deg > best_deg:
                    best, best_deg = label, deg
        return best

    def _find_sunrise_poi(self, scenic: str, ordered: list[str]) -> str | None:
        """在已选 POI 中找日出观景点。

        评分制：名称/标签直含“日出”记 2 分（如曙光亭类），挂接条件含“日出”记 1 分；
        同分取图谱度数最高者——避免把挂接条件碰巧含“日出”的次要景点排在经典观测点之前。
        """
        best, best_key = None, None
        for poi in ordered:
            n = next((x for x in self.tools.poi_nodes(scenic) if self.tools.poi_label(x) == poi), None)
            if not n:
                continue
            name_txt = self.tools.G.nodes[n].get("name", "") + self.tools.G.nodes[n].get("label", "")
            cond_txts = []
            for _, v, e in self.tools.G.out_edges(n, data=True):
                if e.get("relation") == "条件建议":
                    cond_txts.append(self.tools.G.nodes[v].get("name", ""))
                    cond_txts.append(self.tools.G.nodes[v].get("suggestion", ""))
            score = 2 if "日出" in name_txt else (1 if any("日出" in t for t in cond_txts) else 0)
            if score:
                key = (score, self.tools.G.degree(n))
                if best_key is None or key > best_key:
                    best, best_key = poi, key
        return best

    def _order_pois(self, scenic: str, selected: list[str], template_pos: dict) -> list[str]:
        """模板全覆盖时按模板排；否则官方先后边拓扑排序（不可达时按入度+度数贪心），剩余按热度补。"""
        covered = [poi for poi in selected if poi in template_pos]
        if len(covered) == len(selected) and template_pos:
            return sorted(selected, key=lambda poi: (template_pos[poi][0], template_pos[poi][1]))
        G = self.tools.G
        sub = nx.DiGraph()
        nodes = [n for n in self.tools.poi_nodes(scenic) if self.tools.poi_label(n) in selected]
        label_of = {n: self.tools.poi_label(n) for n in nodes}
        if G.is_multigraph():
            edge_iter = ((u, v, d) for u, v, _k, d in G.edges(data=True, keys=True))
        else:
            edge_iter = G.edges(data=True)
        for u, v, e in edge_iter:
            rel = e.get("relation") if isinstance(e, dict) else ""
            if rel == "先后顺序" and u in label_of and v in label_of and u != v:
                src = str(e.get("source", "")) + str(e.get("official_routes", ""))
                if "官方" in src or e.get("official_routes"):
                    w = float(e.get("weight", 1))
                    if sub.has_edge(label_of[u], label_of[v]):
                        sub[label_of[u]][label_of[v]]["w"] += w
                    else:
                        sub.add_edge(label_of[u], label_of[v], w=w)
        ordered_known: list[str] = []
        if sub.number_of_nodes():
            try:
                ordered_known = list(nx.topological_sort(sub))
            except nx.NetworkXUnfeasible:
                # 环形路线（如环湖线）会成环：按“流出权重-流入权重”最大者先走，保持主流动线方向
                temp = sub.copy()
                out_w = {n: sum(d.get("w", 1) for _, _, d in temp.out_edges(n, data=True)) for n in temp.nodes}
                in_w = {n: sum(d.get("w", 1) for _, _, d in temp.in_edges(n, data=True)) for n in temp.nodes}
                while temp.number_of_nodes():
                    ready = [n for n in temp.nodes if temp.in_degree(n) == 0]
                    if ready:
                        n = max(ready, key=lambda x: out_w.get(x, 0))
                    else:
                        n = max(temp.nodes, key=lambda x: (out_w.get(x, 0) - in_w.get(x, 0), int(temp.degree(x))))
                    ordered_known.append(n)
                    for succ in list(temp.successors(n)):
                        if temp.has_edge(n, succ):
                            out_w[succ] = out_w.get(succ, 0) - temp[n][succ].get("w", 1)
                    temp.remove_node(n)
        rest = [poi for poi in selected if poi not in ordered_known]
        deg_of = {x["poi"]: x["degree"] for x in self.tools.query_pois(scenic, limit=30)["pois"]}
        rest.sort(key=lambda poi: -deg_of.get(poi, 0))
        return ordered_known + rest

    def _transport_between(self, a: str, b: str, scenic: str) -> str:
        """仅当两个 POI 挂接同一交通操作时才声称该交通方式，否则如实回退步行。"""
        na = next((n for n in self.tools.poi_nodes(scenic) if self.tools.poi_label(n) == a), None)
        nb = next((n for n in self.tools.poi_nodes(scenic) if self.tools.poi_label(n) == b), None)
        if na and nb:
            trans = lambda n: {self.tools.G.nodes[v].get("name", "") for _, v, e in self.tools.G.out_edges(n, data=True)
                               if e.get("relation") == "交通方式"}
            shared = trans(na) & trans(nb) - {"步行"}
            if shared:
                return f'乘坐{sorted(shared)[0]}'
        return "步行"

    # ── 最终回答生成 ────────────────────────────────────────────
    POLISH_PROMPT = """你是导游。把下面的结构化行程改写成 150 字以内的中文行程说明，按时间顺序、口语化、
保留全部景点名与提示。行程 JSON："""

    def _render(self, plan: dict, trace: list) -> str:
        if self.llm and self.llm.available:
            try:
                text = self.llm.complete(self.POLISH_PROMPT, json.dumps(plan, ensure_ascii=False))
                # 空/纯空白响应与异常同视为润色失败——直接透传会产生空回答
                if not text or not text.strip():
                    raise ValueError("LLM 返回空响应")
                trace.append({"step": "render", "thought": "调用 LLM 润色行程文案", "via": "llm"})
                return text
            except Exception as exc:
                trace.append({"step": "render", "thought": f"LLM 润色失败（{exc}），使用模板文案", "via": "fallback"})
        cn_day = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}
        multi = bool(plan["days"] and plan["days"] > 1)
        lines = []
        for it in plan["itinerary"]:
            head = f'第{cn_day.get(it["day"], it["day"])}天·{it["period"]}' if multi else it["period"]
            trans = f'（{it["transport_from_prev"]}前往）' if it["order"] > 1 else ""
            lines.append(f'{head}：{it["poi"]}{trans}')
        tips = "；".join(f'[{t["cond_type"]}] {t["suggestion"][:30]}' for t in plan["tips"][:4])
        # 可行性警告进入最终回答（此前仅存在于内部字段）
        warnings = plan.get("feasibility_warnings") or []
        # F07：可行性提示来自历史游记语料——标注时效属性，不冒充实时开放状态
        warn_text = "".join(f"\n⚠ {w[:70]}（语料经验，出行前请核实）" for w in warnings[:4])
        day_label = {0.5: "半日", 1: "一日", 1.5: "一日半", 2: "两日", 3: "三日", 3.5: "三日半", 4: "四日", 5: "五日"}
        month_tag = f'，出行时段{plan["trip_month"]}月' if plan.get("trip_month") else ""
        sp_notes = "".join(f'{chr(10)}说明：{n}' for n in (plan.get("special_notes") or []))
        # 来源区分——编排依据（官方/图谱动线）如实标注；贴士注明游记经验来源
        return (f'为您规划{plan["scenic"]}{day_label.get(plan["days"], plan["days"])}游{month_tag}'
                f'{plan.get("template_src", "")}：\n' + "\n".join(lines) +
                (f'\n贴士（来自游记经验）：{tips}' if tips else "") + warn_text + sp_notes)

    # ── ReAct 主循环 ────────────────────────────────────────────
    def run(self, query: str) -> dict:
        started = time.time()
        trace: list[dict] = [{"step": "start", "thought": f"接收请求：{query}", "mode":
                              "llm" if (self.llm and self.llm.available) else "rules"}]
        intent = self.parser.parse(query, trace)
        if intent["scenic"] not in AREAS:
            trace.append({"step": "thought", "thought": "未识别到支持景区，走回退：说明能力边界并列出支持景区"})
            answer = (f'抱歉，当前仅支持 {"/".join(AREAS)} 三个景区的规划。'
                      "您可以试试：“带老人颐和园半日游”“九寨沟亲子一日游”“黄山两日看日出”。")
            trace.append({"step": "final", "thought": "返回能力说明"})
            return {"query": query, "intent": intent, "trace": trace, "answer": answer, "plan": None,
                    "elapsed": round(time.time() - started, 2)}

        if intent["days"] == 0.5 and intent["special"]:
            trace.append({"step": "thought", "thought": "半天+特殊需求（如看日出）存在冲突，提示取舍"})
        plan = self._plan_rule(intent, trace)
        answer = self._render(plan, trace)
        # 多跳动线问句（"从A…走/回到B"）：调用 query_path 追加动线参考
        import re as _re2
        pm = _re2.search(r"从([一-龥A-Za-z0-9]{2,10}?)(?:出来|出发|下来|[，,、\s])[^。！？]{0,12}?(?:走|回|到|去|返回)(?:到|回|去|往)?([^。！？，,]{2,12}?)(?:[？?！！。]|$)", query)
        if pm:
            fp, tp = pm.group(1), pm.group(2)
            fp, tp = fp.strip("的从往回到去"), tp.strip("的从往回到去")
            trace.append({"step": "thought", "thought": f"检测到动线问句：从{fp}到{tp}，调用 query_path 做多跳查询"})
            path_res = self.tools.call("query_path", {"scenic": intent["scenic"], "from_poi": fp, "to_poi": tp}, trace)
            if path_res.get("path"):
                seq = " → ".join(path_res["path"])
                answer += f'\n动线参考（图谱先后顺序边，{path_res["hops"]} 跳）：{seq}'
            elif path_res.get("hops", 1) is None:
                answer += f'\n动线参考：图谱先后顺序图中 {fp} 与 {tp} 之间没有有向路径（可反向查询或分段游览）。'
        if intent["days"] == 0.5 and "看日出" in intent["special"]:
            answer = ("提示：半日游难以兼顾看日出——日出需要清晨身处山顶，通常要求前晚住宿山上。"
                      "建议改为两日行程（首日上山宿山顶，次日看日出后下山），或舍弃看日出安排。\n\n") + answer
        trace.append({"step": "final", "thought": "综合 POI 查询、官方路线模板与条件贴士，生成最终行程"})
        return {"query": query, "intent": intent, "trace": trace, "answer": answer, "plan": plan,
                "elapsed": round(time.time() - started, 2)}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    llm = LLMClient()
    agent = ReActAgent(llm)
    print(f"旅游规划 Agent（LLM: {'已配置 ' + llm.model if llm.available else '未配置，规则模式'}）")
    print(f"支持景区：{'/'.join(AREAS)}；输入 q 退出。")
    while True:
        try:
            query = input("\n您想去哪儿玩？> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query or query.lower() in ("q", "quit", "exit"):
            break
        result = agent.run(query)
        print(result["answer"])
        print(f"\n[trace] {len(result['trace'])} 步，工具调用 {sum(1 for t in result['trace'] if 'tool' in t)} 次，"
              f"耗时 {result['elapsed']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
