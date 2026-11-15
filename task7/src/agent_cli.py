"""Experiment 7: travel planning Agent (LangGraph ReAct mode).

Components:
  - LLM via LangChain ChatOpenAI (base_url/api_key/model configured in config.json);
    when unconfigured llm_available=False and the Agent uses the built-in rule planner
    (intent parsing, itinerary composition and text rendering are fully offline-reproducible).
  - IntentParser: extracts scenic area/visitor type/duration/special needs/entrance constraints
    (hybrid: rule-exact fields take priority, the LLM fills rule gaps; rules-only when LLM unavailable).
  - ReActAgent: the evidence-gathering phase is a genuine ReAct loop built on LangGraph
    create_react_agent — the model decides which graph tools to call (query_pois / query_route /
    query_conditions / query_order / query_poi_conditions / query_path), reads the observations
    and decides when the evidence is enough, finishing with a JSON planning basis. The itinerary
    assembly (ordering, time budget, periods, feasibility warnings) stays deterministic so every
    POI in the plan is graph-verified; the LLM polishes the final text under a coverage check.
Run: python src/agent_cli.py            (interactive CLI)
      python src/run_tests.py --llm      (batch tests 14 scenarios and write evidence to disk)
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
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
TRIP_MONTH_PATTERNS = [
    (10, r"(?<!\d)10月|十月|秋季|秋天|国庆"), (11, r"(?<!\d)11月|十一月"), (12, r"(?<!\d)12月|十二月|冬季|冬天"),
    (1, r"(?<!\d)1月|一月|寒假|元旦"), (2, r"(?<!\d)2月|二月|春节|过年"), (3, r"(?<!\d)3月|三月"),
    (4, r"(?<!\d)4月|四月|春季|春天"), (5, r"(?<!\d)5月|五月|五一"), (6, r"(?<!\d)6月|六月"),
    (7, r"(?<!\d)7月|七月|暑假|夏季|夏天"), (8, r"(?<!\d)8月|八月"), (9, r"(?<!\d)9月|九月"),
]
SEASON_MONTHS = {"冬季": {12, 1, 2}, "冬天": {12, 1, 2}, "夏季": {6, 7, 8}, "夏天": {6, 7, 8},
                 "春季": {3, 4, 5}, "春天": {3, 4, 5}, "秋季": {9, 10, 11}, "秋天": {9, 10, 11}}


def extract_condition_months(text: str) -> set:
    """Set of months in a condition text: single months/month ranges (e.g. 4-11月份)/season words."""
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


def load_config(config_path: Path | None = None) -> dict:
    cfg_path = Path(config_path) if config_path else ROOT / "config.json"
    cfg = {}
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    key = str(cfg.get("api_key", ""))
    placeholder = any(k in key for k in ("填入", "你的", "placeholder", "xxx"))
    configured = bool(cfg.get("base_url") and key and cfg.get("model")) and not placeholder
    return {"base_url": str(cfg.get("base_url", "")).rstrip("/"), "api_key": key,
            "model": str(cfg.get("model", "")), "available": configured}


def build_chat_model(cfg: dict):
    """LangChain ChatOpenAI bound to the configured OpenAI-compatible endpoint."""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=cfg["model"], api_key=cfg["api_key"], base_url=cfg["base_url"],
                      temperature=0.3, timeout=90, max_retries=2)


INTENT_PROMPT = """你是旅游规划助手。从用户输入中提取约束，输出 JSON：
{"scenic": "黄山|九寨沟|颐和园|未知", "visitor_type": "老人|孩子|亲子|情侣|体力有限|初次游览|null",
 "days": 1, "month": 出行月份数字(1-12)或null,
 "special": ["看日出|避开人流|省力|红叶|拍照片" 中的若干或空数组]}
visitor_type 只在用户明确提到人群词（老人/爸妈/孩子/儿童/亲子/家庭/情侣/夫妻/体力差/腿脚/第一次等）时填写对应类别，否则必须为 null。
只输出 JSON，不要解释。用户输入："""


class IntentParser:
    def __init__(self, chat_model=None):
        self.chat_model = chat_model

    def parse(self, query: str, trace: list) -> dict:
        llm_intent = None
        if self.chat_model is not None:
            try:
                raw = self.chat_model.bind(temperature=0).invoke(INTENT_PROMPT + query).content
                llm_intent = json.loads(re.search(r"\{.*\}", raw, re.S).group())
            except Exception as exc:  # fall back to rules on network/parse failure
                trace.append({"step": "intent", "thought": f"LLM 解析失败（{exc}），回退规则解析", "via": "fallback"})
        if llm_intent is not None:
            rule_intent = self._parse_rules(query)
            # hybrid: rule-exact fields (duration regexes/scenic-area lexicon/visitor lexicon) take priority; the LLM fills rule gaps
            merged = dict(rule_intent)
            if merged.get("scenic") in (None, "未知") and llm_intent.get("scenic"):
                merged["scenic"] = llm_intent["scenic"]
            # visitor_type is rule-authoritative: the lexicon table decides. The LLM may not invent
            # a visitor group the query never mentions ("快速逛一遍" is not 体力有限).
            if not merged.get("visitor_type") and llm_intent.get("visitor_type") \
                    and any(re.search(pat, query) for _v, pat in VISITOR_PATTERNS):
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
        """A duration explicitly given by rules is not overridden by the LLM; the LLM value must be numeric in 0.5-5, otherwise ignored."""
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
        avoid = [m.group(1).strip() for m in
                 re.finditer(r"(?:不要去|不想去|不去|避开|别安排|别去|不想逛|不要住|不住|别住)\s*([一-龥A-Za-z0-9]{2,10})", query)]
        avoid += [m.group(1).strip() for m in
                  re.finditer(r"([一-龥A-Za-z0-9]{2,10})\s*就不去了?", query)]
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
        # “想去/想上/想看 X”states a destination wish — capture it as a must-visit so the planner
        # guarantees the POI; special keywords (日出/红叶…) are wishes about scenery, not POIs.
        must += [m.group(1).strip() for m in
                 re.finditer(r"想(?:去|上|逛|看)\s*([一-龥A-Za-z0-9]{2,10})", query)
                 if m.group(1) not in ("日出", "日落", "红叶", "雪景", "温泉", "滑雪", "美景", "风景")]
        avoid, must = list(dict.fromkeys(avoid)), list(dict.fromkeys(must))
        m_en = re.search(r"(?:从|在)?([一-龥]{2,8}?)(?:进园|入园|进入|进)", query)
        m_ex = re.search(r"([一-龥]{2,8}?)(?:出园|(?<!日)出|离开)", query)
        entrance = m_en.group(1).strip() if m_en else None
        exit_gate = m_ex.group(1).strip() if m_ex else None
        if entrance and entrance.endswith(("景区", "园区")):
            entrance = entrance[:-2]
        if entrance in ("进入", "进口"):
            entrance = None
        if exit_gate in ("出发", "发"):
            exit_gate = None
        if entrance and ("进" in entrance or "出" in entrance):
            entrance = None
        if exit_gate and ("进" in exit_gate or "出" in exit_gate):
            exit_gate = None
        month = next((m for m, pat in TRIP_MONTH_PATTERNS if re.search(pat, query)), None)
        return {"scenic": scenic or "未知", "visitor_type": visitor, "visitor_types": visitor_hits,
                "days": days, "days_explicit": days_explicit,
                "month": month, "special": special, "avoid": avoid, "must": must,
                "entrance": entrance, "exit_gate": exit_gate,
                "explicit_fields": sorted(
                    (["days"] if days_explicit else [])
                    + (["visitor_type"] if visitor_hits else [])
                    + (["month"] if month else [])
                    + (["avoid"] if avoid else []) + (["must"] if must else [])
                    + (["entrance"] if entrance else []) + (["exit_gate"] if exit_gate else [])
                    + (["special"] if special else []))}


# ---------------------------------------------------------------- ReAct gathering phase

REACT_SYSTEM = """你是旅游规划 Agent，负责为一次游览收集证据并选出候选景点。用户消息中给出已解析的约束 JSON。

可用的图谱工具（知识图谱来自官方路线+游记语料的 task6 产物）：
- query_pois(scenic, visitor_type, limit): 景点 POI 及热度/时段/交通/游客适配度
- query_route(scenic, days): 官方推荐路线步骤
- query_conditions(scenic, visitor_type, limit): 条件性建议（人群/装备/天气/预约票务…）
- query_order(scenic, poi): 某 POI 的官方+游客先后顺序邻接
- query_poi_conditions(scenic, poi): 某 POI 挂接的条件建议（封山/轮休/慎入类提示）
- query_path(scenic, from_poi, to_poi): 两 POI 间沿先后顺序边的最短动线

要求：
1. 自主决定调用哪些工具、以什么参数、调用几次：先查 POI（结合游客类型与天数取 limit），再取官方路线做参照；
   游客类型不为空时务必查 query_conditions 取贴士；用户问“从A怎么走到B”时调用 query_path；
   需要核实某景点封山/轮休/时段窗口时调用 query_poi_conditions。
2. 观察每一步结果：POI 不存在或工具报错时调整参数重试，不要虚构景点名。
   selected_pois 的数量要与天数匹配：半日 4-5 个、一日 6-8 个、两日 9-12 个、三日以上 10-14 个。
3. 证据足够后停止调用工具，最终回复只输出一个 JSON（不要 markdown 代码块，不要解释文字）：
{{"selected_pois": ["按游览价值挑选的景点名，必须来自工具返回结果"],
  "route_preference": "你倾向参考的官方路线 route_id 或空串",
  "tips": ["从 query_conditions 结果中挑选的最相关贴士原文，至多 6 条"],
  "path": "若用户询问动线，填 query_path 返回的途经序列字符串，否则空串",
  "notes": ["给编排器的说明，如必去/避开/时段注意，至多 4 条"]}}"""


class ReActAgent:
    """LangGraph ReAct loop for evidence gathering + deterministic itinerary assembly."""

    MAX_REACT_TURNS = 8

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or load_config()
        self.tools = GraphTools()
        self.chat_model = build_chat_model(self.cfg) if self.cfg["available"] else None
        self.parser = IntentParser(chat_model=self.chat_model)
        self._react_app = None
        if self.chat_model is not None:
            self._react_app = self._build_react_app()

    # -- LangGraph ReAct app ------------------------------------------------
    def _build_react_app(self):
        from langchain_core.tools import tool
        from langgraph.prebuilt import create_react_agent

        gt = self.tools

        @tool
        def query_pois(scenic: str, visitor_type: str = "", limit: int = 8) -> dict:
            """查询景区内景点 POI 及其热度、时段、交通属性，可按游客类型筛选（体力适配优先）。visitor_type 传空串表示不限。"""
            return gt.query_pois(scenic, visitor_type or None, limit)

        @tool
        def query_route(scenic: str, days: int = 1) -> dict:
            """查询景区官方推荐路线（结构化步骤：POI/时段/交通/天数）。"""
            return gt.query_route(scenic, days)

        @tool
        def query_conditions(scenic: str, visitor_type: str = "", limit: int = 6) -> dict:
            """查询景区的条件性建议（人群/装备/天气/预约票务/体力安全…），可按游客类型过滤。"""
            return gt.query_conditions(scenic, visitor_type or None, limit)

        @tool
        def query_order(scenic: str, poi: str) -> dict:
            """查询某 POI 在图谱中的先后顺序邻接（官方+游客加权，用于编排顺序校验）。"""
            return gt.query_order(scenic, poi)

        @tool
        def query_poi_conditions(scenic: str, poi: str) -> dict:
            """查询某 POI 挂接的条件建议节点（封山/轮休/不建议类提示，用于可行性校验）。"""
            return gt.query_poi_conditions(scenic, poi)

        @tool
        def query_path(scenic: str, from_poi: str, to_poi: str) -> dict:
            """多跳查询：两 POI 之间沿官方+游客先后顺序边的最短动线（途经节点序列）。"""
            return gt.query_path(scenic, from_poi, to_poi)

        return create_react_agent(
            self.chat_model, [query_pois, query_route, query_conditions,
                              query_order, query_poi_conditions, query_path],
            prompt=REACT_SYSTEM, )

    def _gather_react(self, intent: dict, trace: list) -> dict:
        """Run the ReAct loop; returns the model's JSON planning basis (or {} on failure)."""
        from langchain_core.messages import AIMessage, ToolMessage

        user_msg = ("用户约束如下，请开始收集证据并给出 JSON 规划依据。\n"
                    + json.dumps(intent, ensure_ascii=False))
        result = self._react_app.invoke(
            {"messages": [{"role": "user", "content": user_msg}]},
            config={"recursion_limit": self.MAX_REACT_TURNS * 2 + 4})
        for msg in result["messages"]:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    trace.append({"step": "action", "thought": (msg.content or f"决定调用工具 {tc['name']}").strip()[:120],
                                  "tool": tc["name"], "args": dict(tc["args"]), "via": "react"})
            elif isinstance(msg, ToolMessage):
                trace.append({"step": "observation", "tool": msg.name,
                              "summary": str(msg.content)[:180], "via": "react"})
        final = next((m for m in reversed(result["messages"])
                      if isinstance(m, AIMessage) and not m.tool_calls), None)
        trace.append({"step": "thought", "via": "react",
                      "thought": f"ReAct 收束：模型认为证据足够，产出规划依据（{len([t for t in trace if t.get('step')=='action'])} 次工具调用）"})
        if final is None:
            return {}
        try:
            return json.loads(re.search(r"\{.*\}", str(final.content), re.S).group())
        except Exception as exc:
            trace.append({"step": "thought", "via": "fallback",
                          "thought": f"ReAct 终稿 JSON 解析失败（{exc}），回退用已缓存工具结果编排"})
            return {}

    # -- deterministic assembly (ported from the previous fixed pipeline) ----

    def _plan_rule(self, intent: dict, evidence: dict, trace: list) -> dict:
        scenic, days, visitor = intent["scenic"], intent["days"], intent["visitor_type"]
        limit = {0.5: 5, 1: 8, 1.5: 9, 2: 11, 3: 12, 3.5: 13, 4: 14, 5: 15}.get(days, 11)
        visitor_types = intent.get("visitor_types") or ([visitor] if visitor else [])
        visitor_eff = ("体力有限" if ("省力" in (intent.get("special") or []) and not visitor)
                       else (visitor_types if visitor_types else visitor))
        pois_res = self.tools.call("query_pois", {"scenic": scenic, "visitor_type": visitor_eff, "limit": limit}, trace)
        route_res = self.tools.call("query_route", {"scenic": scenic, "days": days if days <= 2 else 2}, trace)
        cond_res = self.tools.call("query_conditions", {"scenic": scenic, "visitor_type": visitor_eff}, trace)
        trace.append({"step": "thought", "thought": f"约束={intent}；以 ReAct 收集的证据为基础，"
                      "核对候选景点后进入确定性编排：官方路线做骨架，时间预算与可行性校验兜底"})

        # Agent-selected POIs are validated against the graph; unknown names are dropped honestly.
        graph_labels = {self.tools.poi_label(n) for n in self.tools.poi_nodes(scenic)}
        selected, rejected = [], []
        for p in (evidence.get("selected_pois") or []):
            if p in graph_labels:
                selected.append(p)
            elif p:
                rejected.append(p)
        if rejected:
            trace.append({"step": "thought", "thought": f"模型候选未在图谱中命中，剔除：{rejected}"})
        if not selected:
            selected = [p["poi"] for p in pois_res["pois"]]
            trace.append({"step": "thought", "via": "fallback",
                          "thought": "模型未给出可用候选，回退默认 POI 选取"})
        # ensure coverage of the must/entrance/exit constraints handled below even if the model missed them
        for extra in (intent.get("must") or []):
            node = self.tools._resolve_poi(scenic, extra)
            if node is not None and self.tools.poi_label(node) not in selected:
                selected.append(self.tools.poi_label(node))

        photo_pois: set = set()
        if "拍照片" in (intent.get("special") or []):
            for poi in list(selected):
                pc = self.tools.call("query_poi_conditions", {"scenic": scenic, "poi": poi}, trace)
                if any(c.get("cond_type") == "拍照" for c in pc.get("conditions", [])):
                    photo_pois.add(poi)
            if photo_pois:
                trace.append({"step": "thought",
                              "thought": f"软偏好「拍照片」：{sorted(photo_pois)} 挂有拍照点位条件（编排后前置）"})
        avoid = [a for a in (intent.get("avoid") or []) if a]
        must = [m0 for m0 in (intent.get("must") or []) if m0]
        special_notes: list[str] = []
        removed_by_avoid = []
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
            if len(removed_by_avoid) >= 2 and len(selected) <= 3:
                special_notes.append("您避开的景点较多，行程较精简；"
                                     "如需更丰富的安排，可放宽部分\"不去\"地点后再试")
        # Itinerary-size floor: a trip whose model selection fell below the time budget is topped
        # up by graph popularity (never by invention), keeping itinerary_size valid.
        _budget_daily = {0.5: 3, 1: 5, 1.5: 4, 2: 4, 3: 4, 3.5: 4, 4: 4, 5: 4}.get(days, 4)
        _size_target = _budget_daily if days == 0.5 else round(_budget_daily * max(1, days or 1))
        if len(selected) < _size_target:
            topup = [p["poi"] for p in pois_res["pois"]
                     if p["poi"] not in selected and not any(a in p["poi"] or p["poi"] in a for a in avoid)]
            for p in topup[:_size_target - len(selected)]:
                selected.append(p)
            trace.append({"step": "thought", "via": "fallback",
                          "thought": f"模型候选不足（{len(selected)}/{_size_target}），按图谱热度补足：{topup[:_size_target - len(selected)]}"})
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
                          "thought": f"必去地点处理：{len(must_keep)} 个进入豁免名单（含新加入），未找到项见贴士"})
        entrance_label = exit_label = None
        for role, raw, kind in (("入口", intent.get("entrance"), "en"),
                                ("出口", intent.get("exit_gate"), "ex")):
            if not raw:
                continue
            hit = next((q for q in selected if raw in q or q in raw), None)
            node = self.tools._resolve_poi(scenic, raw)
            label = self.tools.poi_label(node) if node is not None else None
            if label is None and hit:
                label = hit
            if label is None:
                special_notes.append(f"{role}：{raw} 未在{scenic}景点库中找到，请确认名称")
                continue
            if label not in selected:
                selected.append(label)
                special_notes.append(f"{role}：{label} 已加入行程")
            else:
                special_notes.append(f"{role}：{label} 已在行程中")
            if kind == "en":
                entrance_label = label
            else:
                exit_label = label
            must_keep.append(label)
            trace.append({"step": "thought",
                          "thought": f"出入口处理：{role} {label} 纳入行程并豁免预算"})
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
        # Entrance-first heuristic: a gate POI (name ends with 门) is where visitors physically
        # enter, even when no explicit entrance constraint was parsed — starting anywhere else
        # reads as walking out of the park first.
        gate_first = next((p for p in ordered if p.endswith("门")), None)
        if gate_first and ordered[0] != gate_first:
            ordered.remove(gate_first)
            ordered.insert(0, gate_first)
            trace.append({"step": "thought",
                          "thought": f"入口前置：门类景点 {gate_first} 置于行程首站"})
        if entrance_label and entrance_label in ordered:
            ordered.remove(entrance_label)
            ordered.insert(0, entrance_label)
            trace.append({"step": "thought",
                          "thought": f"出入口编排：入口 {entrance_label} 前置于行程首站"})
        if exit_label and exit_label in ordered:
            ordered.remove(exit_label)
            ordered.append(exit_label)
            trace.append({"step": "thought",
                          "thought": f"出入口编排：出口 {exit_label} 后置于行程末站"})
        if photo_pois:
            ordered.sort(key=lambda x: x not in photo_pois)
            trace.append({"step": "thought",
                          "thought": f"软偏好「拍照片」提升：{sorted(photo_pois)} 前置于行程"})
        if avoid:
            # Acknowledge every avoided item whether or not it had entered the candidate list —
            # the model may already have respected the constraint, which still deserves a statement.
            for a in avoid:
                if not any(a in r or r in a for r in removed_by_avoid):
                    special_notes.append(f"已按您的要求避开：{a}（未纳入行程）")
            if removed_by_avoid:
                special_notes.append("已按您的要求避开：" + "、".join(removed_by_avoid))
        lodging_in_plan = [p for p in selected if any(k in p for k in ("宾馆", "酒店", "民宿"))]
        if lodging_in_plan and days and days >= 2:
            special_notes.append(f"住宿：{lodging_in_plan[0]} 已纳入行程（多日游建议山上住宿）")
        if "看日出" in (intent.get("special") or []) and days and days >= 2:
            _sunrise_poi = self._find_sunrise_poi(scenic, ordered)
            if _sunrise_poi:
                _lodging_now = [q for q in selected if any(k in q for k in ("宾馆", "酒店", "民宿"))]
                if _lodging_now:
                    special_notes.append(f"看日出：{_sunrise_poi} 已安排在最后一日首位（清晨前往），需前晚住宿山上或山顶酒店")
                else:
                    special_notes.append(f"看日出：{_sunrise_poi} 已安排在最后一日首位（清晨前往）；"
                                         "注意：您已避开山上住宿且无替代住宿点，需凌晨自山下出发（班车/夜爬，注意安全），"
                                         "或恢复住宿安排后再看日出")
            else:
                special_notes.append("看日出：已选景点中无日出观景点（如光明顶），如需看日出请将其加入需求")
            trace.append({"step": "thought", "thought": f"特殊需求「看日出」编排：{special_notes[-1]}"})
        qr_selected = bool(best_route) and best_route.get("route_id") == route_res.get("route_id")
        trace.append({"step": "thought", "thought": f"编排骨架：模板“{template}”覆盖已选 POI 的 {best_cov:.0%}"
                      + ("；query_route 返回的路线入选" if qr_selected else
                         "；query_route 返回的路线覆盖率不足，另选覆盖最高者")
                      + ("；覆盖率不足 60%，改用图谱先后边拓扑排序" if template_cov_low else "")})
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
        n_days = max(1, int(math.ceil(days)) if days and days >= 1 else 1)
        ordered = self._apply_time_budget(ordered, days, n_days, _sunrise_poi, special_notes, trace)
        if must_keep:
            missing = [p for p in dict.fromkeys(must_keep) if p not in ordered]
            if missing:
                ordered.extend(missing)
                trace.append({"step": "thought",
                              "thought": f"必去地点豁免预算裁剪：{missing} 已回填行程"})

        period_cycle = ["上午", "上午", "中午", "下午", "下午", "晚上"]
        n_days = max(1, int(math.ceil(days)) if days and days >= 1 else 1)
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
            if days and days % 1 != 0 and day == n_days and period in ("下午", "晚上"):
                period = "中午"
            if days == 0.5:
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
        if days and days >= 2:
            PERIOD_ORD = {"上午": 0, "中午": 1, "下午": 2, "晚上": 3}
            for it in itinerary:
                if any(k in it["poi"] for k in ("宾馆", "酒店", "民宿")):
                    it["day"] = max(1, n_days - 1)
                    it["period"] = "晚上"
            if _sunrise_poi:
                for it in itinerary:
                    if it["poi"] == _sunrise_poi:
                        it["day"] = n_days
                        it["period"] = "上午"
            itinerary.sort(key=lambda x: (x["day"],
                                          PERIOD_ORD.get(x["period"], 9),
                                          0 if x["poi"] == _sunrise_poi else 1))
            for i, it in enumerate(itinerary):
                it["order"] = i + 1

        feasibility_warnings = []
        seen_warn = set()
        CLOSURE_RE = re.compile(r"封山|封闭|轮休|停运|关闭|不开放|暂停|停止接待|限流|不建议|不宜|不去|不适合|慎入|谨慎")
        WINDOW_RE = re.compile(r"开放|适合|最美|精华|推荐|值得|绝佳")
        trip_month = intent.get("month")
        for poi in ordered[:10]:
            pc = self.tools.call("query_poi_conditions", {"scenic": scenic, "poi": poi}, trace)
            for c in pc.get("conditions", []):
                text = c["condition"] + c["suggestion"]
                months = extract_condition_months(text)
                if CLOSURE_RE.search(text):
                    w = f'{poi}：{c["condition"][:26]}——{c["suggestion"][:40]}'
                    years = "/".join(sorted(json.loads(c.get("source_years") or "[]"))[-2:])
                    w = w + (f"（证据年份 {years}）" if years else "")
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
        # tips: the ReAct pass selects candidates first; fall back to the rule filter for gaps
        ev_tips = [t for t in (evidence.get("tips") or []) if isinstance(t, str)]
        cond_by_sugg = {c["suggestion"]: c for c in cond_res.get("conditions", [])}
        tips = [cond_by_sugg[t] for t in ev_tips if t in cond_by_sugg][:6]
        if not tips:
            tips = [c for c in cond_res.get("conditions", [])
                    if not any(k in c["condition"] + c["suggestion"] for k in other_area_kw)
                    and (c["cond_type"] == "人群" or any(k in c["suggestion"] for k in suggest_cue))][:6]
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
        """Time budget -- caps daily POI counts (half-day ≤3, one-day ≤5, multi-day ≤4/day).

        Sunrise/lodging POIs are never trimmed (they are the structural anchors of a
        multi-day itinerary).
        """
        daily_budget = {0.5: 3, 1: 5, 1.5: 4, 2: 4, 3: 4, 3.5: 4, 4: 4, 5: 4}.get(days, 4)
        _anchored = set()
        if _sunrise_poi:
            _anchored.add(_sunrise_poi)
        _anchored.update(p for p in ordered if any(k in p for k in ("宾馆", "酒店", "民宿")))
        effective = days if (days and days >= 1) else 1
        max_pois = (daily_budget if days == 0.5 else round(daily_budget * effective)) + len(_anchored)
        if len(ordered) > max_pois:
            dropped = [p for p in ordered[max_pois:] if p not in _anchored]
            kept_tail = [p for p in ordered[max_pois:] if p in _anchored]
            ordered = ordered[:max_pois] + kept_tail
            special_notes.append(f"时间预算限制：已裁剪 {len(dropped)} 个景点（{', '.join(dropped[:3])}等），建议根据体力取舍")
            trace.append({"step": "thought",
                          "thought": f"时段预算：每日上限 {daily_budget}，总 {n_days} 天，裁剪 {len(dropped)} 个 POI"})
        return ordered

    def _find_lodging_poi(self, scenic: str) -> str | None:
        best, best_deg = None, 0
        for n in self.tools.poi_nodes(scenic):
            label = self.tools.G.nodes[n].get("label", "")
            if any(k in label for k in ("宾馆", "酒店", "民宿", "饭店")):
                deg = self.tools.G.degree(n)
                if deg > best_deg:
                    best, best_deg = label, deg
        return best

    def _find_sunrise_poi(self, scenic: str, ordered: list[str]) -> str | None:
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
        """With full template coverage, order by the template; otherwise topological sort over official
        先后顺序 edges (greedy by out-weight minus in-weight on cycles), remainder filled by popularity."""
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
        na = next((n for n in self.tools.poi_nodes(scenic) if self.tools.poi_label(n) == a), None)
        nb = next((n for n in self.tools.poi_nodes(scenic) if self.tools.poi_label(n) == b), None)
        if na and nb:
            trans = lambda n: {self.tools.G.nodes[v].get("name", "") for _, v, e in self.tools.G.out_edges(n, data=True)
                               if e.get("relation") == "交通方式"}
            shared = trans(na) & trans(nb) - {"步行"}
            if shared:
                return f'乘坐{sorted(shared)[0]}'
        return "步行"

    POLISH_PROMPT = """你是旅游规划助手。把下面的结构化行程改写成 150 字以内的中文行程说明：按时间顺序直接陈述，
不要任何招呼语或开场客套（如“两位好”“叔叔阿姨好”“大家好”之类一律不要），不要与行程无关的铺垫和空话，
保留全部景点名与提示。行程 JSON："""

    def _render(self, plan: dict, trace: list) -> str:
        if self.chat_model is not None:
            try:
                resp = self.chat_model.invoke(self.POLISH_PROMPT + json.dumps(plan, ensure_ascii=False))
                text = resp.content
                _pois = [it["poi"] for it in plan.get("itinerary", [])]
                _hit = sum(1 for q in _pois if q in text)
                if _pois and _hit < max(1, int(0.6 * len(_pois))):
                    raise ValueError(f"润色文本站点覆盖不足（{_hit}/{len(_pois)}）")
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
        warnings = plan.get("feasibility_warnings") or []
        warn_text = "".join(f"\n⚠ {w[:70]}（语料经验，出行前请核实）" for w in warnings[:4])
        day_label = {0.5: "半日", 1: "一日", 1.5: "一日半", 2: "两日", 3: "三日", 3.5: "三日半", 4: "四日", 5: "五日"}
        month_tag = f'，出行时段{plan["trip_month"]}月' if plan.get("trip_month") else ""
        sp_notes = "".join(f'{chr(10)}说明：{n}' for n in (plan.get("special_notes") or []))
        return (f'为您规划{plan["scenic"]}{day_label.get(plan["days"], plan["days"])}游{month_tag}'
                f'{plan.get("template_src", "")}：\n' + "\n".join(lines) +
                (f'\n贴士（来自游记经验）：{tips}' if tips else "") + warn_text + sp_notes)

    def run(self, query: str) -> dict:
        started = time.time()
        trace: list[dict] = [{"step": "start", "thought": f"接收请求：{query}", "mode":
                              "llm" if self.cfg["available"] else "rules"}]
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
        evidence: dict = {}
        if self._react_app is not None:
            try:
                evidence = self._gather_react(intent, trace)
            except Exception as exc:
                trace.append({"step": "thought", "via": "fallback",
                              "thought": f"ReAct 循环失败（{exc}），回退确定性收集"})
        plan = self._plan_rule(intent, evidence if isinstance(evidence, dict) else {}, trace)
        answer = self._render(plan, trace)
        pm = re.search(r"从([一-龥A-Za-z0-9]{2,10}?)(?:出来|出发|下来|[，,、\s])[^。！？]{0,12}?(?:走|回|到|去|返回)(?:到|回|去|往)?([^。！？，,]{2,12}?)(?:[？?！！。]|$)", query)
        if pm and not any(t.get("tool") == "query_path" for t in trace if t.get("step") == "action"):
            fp, tp = pm.group(1), pm.group(2)
            fp, tp = fp.strip("的从往回到去"), tp.strip("的从往回到去")
            trace.append({"step": "thought", "thought": f"检测到动线问句且 ReAct 未覆盖：从{fp}到{tp}，调用 query_path"})
            path_res = self.tools.call("query_path", {"scenic": intent["scenic"], "from_poi": fp, "to_poi": tp}, trace)
            if path_res.get("path"):
                seq = " → ".join(path_res["path"])
                answer += f'\n动线参考（图谱先后顺序边，{path_res["hops"]} 跳）：{seq}'
            elif path_res.get("hops", 1) is None:
                answer += f'\n动线参考：图谱先后顺序图中 {fp} 与 {tp} 之间没有有向路径（可反向查询或分段游览）。'
        if intent["days"] == 0.5 and "看日出" in intent["special"]:
            answer = ("提示：半日游难以兼顾看日出——日出需要清晨身处山顶，通常要求前晚住宿山上。"
                      "建议改为两日行程（首日上山宿山顶，次日看日出后下山），或舍弃看日出安排。\n\n") + answer
        trace.append({"step": "final", "thought": "综合 ReAct 证据、官方路线模板与条件贴士，生成最终行程"})
        return {"query": query, "intent": intent, "trace": trace, "answer": answer, "plan": plan,
                "elapsed": round(time.time() - started, 2)}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    agent = ReActAgent()
    print(f"旅游规划 Agent（LangGraph ReAct · LLM: "
          f"{agent.cfg['model'] + ' @ ' + agent.cfg['base_url'] if agent.cfg['available'] else '未配置，规则模式'}）")
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
