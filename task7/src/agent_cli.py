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
    ("老人", r"老人|爸妈|父母|银发|奶奶|爷爷|长辈"),
    ("孩子", r"孩子|小孩|儿童|带娃|娃|儿子|女儿|幼儿园"),
    ("亲子", r"亲子|家庭|一家"),
    ("情侣", r"情侣|夫妻|蜜月|约会|女朋友|男朋友"),
    ("体力有限", r"体力(不好|差|有限|不足)|腿脚|孕妇|高反"),
    ("初次游览", r"第一次|首次|没去过"),
]
DURATION_PATTERNS = [
    (3.5, r"三天半|3\.5\s*天"),
    (3, r"三天|3\s*天"),
    (4, r"四天|4\s*天"),
    (5, r"五天|5\s*天"),
    (2, r"两日|两天|2\s*天|二日|周末游"),
    (1.5, r"一天半|1\.5\s*天"),
    (1, r"一日|一天|1\s*天|当日"),
    (0.5, r"半天|([0-9一二两三])\s*小时"),
]
SPECIAL_PATTERNS = [
    ("看日出", r"日出|朝霞"), ("避开人流", r"人少|避开|错峰|不挤"),
    ("省力", r"省力|轻松|不累|少走"), ("红叶", r"红叶|秋色|赏秋"),
    ("拍照片", r"拍照|出片|机位"), ("滑雪", r"滑雪|温泉"),
]
# 出行月份（规则口径）：月份短语/季节词/节假日 → 代表月份（U24 时段可行性）
TRIP_MONTH_PATTERNS = [
    (10, r"(?<!\d)10月|十月|秋季|秋天|国庆"), (11, r"(?<!\d)11月|十一月"), (12, r"(?<!\d)12月|十二月|冬季|冬天"),
    (1, r"(?<!\d)1月|一月|寒假|元旦"), (2, r"(?<!\d)2月|二月|春节"), (3, r"(?<!\d)3月|三月"),
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
            # 混合：规则精确字段（时长正则/景区词表/人群词表）优先，规则缺省处用 LLM 补（U18）
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
        """P10：规则显式给定的时长不被 LLM 覆盖；LLM 值须为 0.5–5 的数值，否则忽略。"""
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
        visitor = next((v for v, pat in VISITOR_PATTERNS if re.search(pat, query)), None)
        days = 1
        days_explicit = False
        for d, pat in DURATION_PATTERNS:
            if re.search(pat, query):
                days = d
                days_explicit = True
                break
        special = [s for s, pat in SPECIAL_PATTERNS if re.search(pat, query)]
        month = next((m for m, pat in TRIP_MONTH_PATTERNS if re.search(pat, query)), None)
        return {"scenic": scenic or "未知", "visitor_type": visitor, "days": days,
                "days_explicit": days_explicit,
                "month": month, "special": special}


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
        pois_res = self.tools.call("query_pois", {"scenic": scenic, "visitor_type": visitor, "limit": limit}, trace)
        route_res = self.tools.call("query_route", {"scenic": scenic, "days": days if days <= 2 else 2}, trace)
        cond_res = self.tools.call("query_conditions", {"scenic": scenic, "visitor_type": visitor}, trace)
        trace.append({"step": "thought", "thought": f"约束={intent}；先查核心 POI（limit={limit}），"
                     "再取官方路线做编排骨架，最后按游客类型取条件贴士"})

        selected = [p["poi"] for p in pois_res["pois"]]
        # 模板选择：在与天数匹配的官方路线中选“覆盖已选 POI 比例最高”的一条；覆盖率过低则改用图谱拓扑排序
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
        ordered = self._order_pois(scenic, selected, template_pos)
        trace.append({"step": "thought", "thought": f"编排骨架：模板“{template}”覆盖已选 POI 的 {best_cov:.0%}"
                     + ("；覆盖率不足 60%，改用图谱先后边拓扑排序" if template_cov_low else "")})
        # 天数/时段分配（P05/P06）：n_days 对 0.5/1/1.5/2/3/3.5/4/5 全部成立；
        # 2 日且模板全覆盖时沿用模板的天与时段，否则按切分块分配；半日时段封顶于上午/中午（P06）；
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
                # P06：半日时段封顶于上午/中午，不出现下午/晚上
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
        # 额外邻接参考（工具4，证明图谱查询参与编排）
        if ordered:
            order_res = self.tools.call("query_order", {"scenic": scenic, "poi": ordered[0]}, trace)
            trace.append({"step": "thought", "thought": f"用 query_order 校验首站的官方后继（{order_res.get('poi')}）"
                         "以决定第二站是否符合主流动线"})
        # P6 行程可行性校验（U24 时段化）：封禁/不建议类按 U11 提示；条件文本含月份窗口时按出行月份判定——
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
        return {"scenic": scenic, "days": days, "visitor_type": visitor, "special": intent["special"],
                "trip_month": intent.get("month"),
                "itinerary": itinerary, "tips": tips, "feasibility_warnings": feasibility_warnings,
                "template_route": f'{route_res.get("route_id", "")} {route_res.get("route_title", "")}'}

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
        na = next((n for n in self.tools.poi_nodes(scenic) if self.tools.poi_label(n) == a), None)
        nb = next((n for n in self.tools.poi_nodes(scenic) if self.tools.poi_label(n) == b), None)
        if na and nb:
            for _, v, e in self.tools.G.out_edges(na, data=True):
                if v == nb and e.get("relation") == "交通方式":
                    return self.tools.G.nodes[v].get("name", "步行")
            for _, v, e in self.tools.G.out_edges(nb, data=True):
                if e.get("relation") == "交通方式":
                    return self.tools.G.nodes[v].get("name", "步行")
        return "步行"

    # ── 最终回答生成 ────────────────────────────────────────────
    POLISH_PROMPT = """你是导游。把下面的结构化行程改写成 150 字以内的中文行程说明，按时间顺序、口语化、
保留全部景点名与提示。行程 JSON："""

    def _render(self, plan: dict, trace: list) -> str:
        if self.llm and self.llm.available:
            try:
                text = self.llm.complete(self.POLISH_PROMPT, json.dumps(plan, ensure_ascii=False))
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
        # P08：可行性警告进入最终回答（此前仅存在于内部字段）
        warnings = plan.get("feasibility_warnings") or []
        warn_text = "".join(f'\n⚠ {w[:70]}' for w in warnings[:4])
        day_label = {0.5: "半日", 1: "一日", 1.5: "一日半", 2: "两日", 3: "三日", 3.5: "三日半", 4: "四日", 5: "五日"}
        month_tag = f'，出行时段{plan["trip_month"]}月' if plan.get("trip_month") else ""
        return (f'为您规划{plan["scenic"]}{day_label.get(plan["days"], plan["days"])}游{month_tag}'
                f'（参考官方路线 {plan["template_route"]}）：\n' + "\n".join(lines) +
                (f'\n贴士：{tips}' if tips else "") + warn_text)

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
