"""实验7：知识图谱查询工具层（供 Agent 调用）。

每个工具都有名称、描述、参数 Schema 与结构化返回，并记录调用日志。
数据源：task6/output/knowledge_graph.graphml + task3/output/parsed_routes.jsonl。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
OUT6 = ROOT.parent / "task6/output"
TASK3 = ROOT.parent / "task3/output"

AREAS = ("黄山", "九寨沟", "颐和园")
PERIOD_ORDER = {"上午": 0, "中午": 1, "下午": 2, "晚上": 3, "未标注时段": 4}
VISITOR_KEYWORDS = {
    "老人": ["老人", "银发", "腿脚", "老年"],
    "孩子": ["孩子", "儿童", "带娃", "小孩", "亲子"],
    "亲子": ["亲子", "孩子", "儿童", "带娃", "小孩", "家庭"],
    "情侣": ["情侣", "夫妻", "蜜月", "约会"],
    "体力有限": ["体力", "腿脚", "高反", "不济", "不足"],
    "初次游览": ["第一次", "首次", "初游"],
}

TOOL_SCHEMAS = [
    {"name": "query_pois", "description": "查询景区内景点 POI 及其热度、时段、交通属性，可按游客类型筛选",
     "params": {"scenic": "str", "visitor_type": "str(可选)", "limit": "int(可选,默认8)"}},
    {"name": "query_route", "description": "查询景区官方推荐路线（结构化步骤：POI/时段/交通/天数）",
     "params": {"scenic": "str", "days": "int(可选,默认1)"}},
    {"name": "query_conditions", "description": "查询景区的条件性建议，可按游客类型过滤（人群/装备/天气/体力安全等）",
     "params": {"scenic": "str", "visitor_type": "str(可选)", "limit": "int(可选,默认6)"}},
    {"name": "query_order", "description": "查询某 POI 在图谱中的先后顺序邻接（官方+游客加权）",
     "params": {"scenic": "str", "poi": "str"}},
    {"name": "query_poi_conditions", "description": "查询某 POI 挂接的条件建议节点（用于行程可行性校验：封山/轮休/不建议类提示）",
     "params": {"scenic": "str", "poi": "str"}},
    {"name": "query_path", "description": "多跳查询：两 POI 之间沿官方+游客先后顺序边的最短动线（途经节点序列）",
     "params": {"scenic": "str", "from_poi": "str", "to_poi": "str"}},
]


NEG_ADVICE_RE = re.compile(r"不要|别去|千万别|不宜|不适合|避免|慎|忌|禁止|不建议|别走|别爬")


class GraphTools:
    def __init__(self):
        self.G = nx.read_graphml(OUT6 / "knowledge_graph.graphml")
        self.routes = [json.loads(l) for l in (TASK3 / "parsed_routes.jsonl").open(encoding="utf-8")]
        self.trace: list[dict] = []

    # ── 基础查询 ────────────────────────────────────────────────
    def poi_nodes(self, scenic: str) -> list[str]:
        return [n for n, d in self.G.nodes(data=True)
                if d.get("kind") in ("景点", "周边景点") and f":{scenic}:" in n]

    def poi_label(self, node: str) -> str:
        return self.G.nodes[node].get("label", node.split(":")[-1])

    def _match_visitor(self, text: str, visitor_type: str | None) -> bool:
        if not visitor_type:
            return True
        kws = VISITOR_KEYWORDS.get(visitor_type, [visitor_type])
        return any(k in text for k in kws)

    # ── 工具1：query_pois ───────────────────────────────────────
    def query_pois(self, scenic: str, visitor_type: str | None = None, limit: int = 8) -> dict:
        if scenic not in AREAS:
            return {"error": f"不支持的景区：{scenic}（仅支持 {'/'.join(AREAS)}）"}
        cand = []
        for n in self.poi_nodes(scenic):
            d = self.G.nodes[n]
            periods = sorted({self.G.nodes[v].get("name", "") for _, v, e in self.G.out_edges(n, data=True)
                              if e.get("relation") == "时段归属"}, key=lambda p: PERIOD_ORDER.get(p, 9))
            transports = sorted({self.G.nodes[v].get("name", "") for _, v, e in self.G.out_edges(n, data=True)
                                 if e.get("relation") == "交通方式"})
            fit = 0
            caveats = []
            if visitor_type:
                for _, v, e in self.G.out_edges(n, data=True):
                    if e.get("relation") == "条件建议" and self.G.nodes[v].get("cond_type") == "人群":
                        text = self.G.nodes[v].get("name", "") + self.G.nodes[v].get("suggestion", "")
                        if not self._match_visitor(text, visitor_type):
                            continue
                        if NEG_ADVICE_RE.search(text):
                            # P09：负向人群建议（如“老人千万别走中轴线爬山”）不是正向适配——
                            # 降权并记入站点提示，而不是当加分项
                            fit -= float(e.get("weight", 1))
                            caveats.append(self.G.nodes[v].get("suggestion", "")[:40])
                        else:
                            fit += float(e.get("weight", 1))
            cand.append({"poi": d.get("label", n), "degree": self.G.degree(n),
                         "mention_freq": int(float(d.get("mention_freq", 0) or 0)),
                         "periods": periods, "transports": transports, "visitor_fit": fit,
                         "visitor_caveats": caveats[:2]})
        # 有游客类型适配的优先（适配度高者在前），其次图谱度数、提及词频
        cand.sort(key=lambda x: (x["visitor_fit"] > 0, x["visitor_fit"], x["degree"], x["mention_freq"]),
                  reverse=True)
        return {"scenic": scenic, "visitor_type": visitor_type, "pois": cand[:limit]}

    # ── 工具2：query_route ──────────────────────────────────────
    def query_route(self, scenic: str, days: int = 1) -> dict:
        if scenic not in AREAS:
            return {"error": f"不支持的景区：{scenic}"}
        cands = [r for r in self.routes
                 if r["scenic_area"] == scenic and r["ordered_route"] and r["step_count"] >= 2]
        # 优先天数匹配（步骤里出现的最大天数），其次步骤数
        def route_days(r):
            return max((s["day"] for s in r["steps"]), default=1)

        exact = [r for r in cands if route_days(r) == days] or cands
        best = max(exact, key=lambda r: (route_days(r) == days, r["step_count"]))
        return {"route_id": best["route_id"], "route_title": best["route_title"],
                "scenic_area": scenic,
                "steps": [{"step_no": s["step_no"], "day": s["day"], "period": s["period"],
                           "pois": [p["normalized"] for p in s["pois"]], "transport": s["transport"],
                           "time_range": s["time_range"], "duration": s["duration"],
                           "lodging": s.get("lodging", False)} for s in best["steps"]]}

    def routes_by_scenic(self, scenic: str, days: int) -> list[dict]:
        cands = [r for r in self.routes
                 if r["scenic_area"] == scenic and r["ordered_route"] and r["step_count"] >= 2]
        exact = [r for r in cands if max((st["day"] for st in r["steps"]), default=1) == days] or cands
        return exact

    # ── 工具3：query_conditions ─────────────────────────────────
    def query_conditions(self, scenic: str, visitor_type: str | None = None, limit: int = 6) -> dict:
        if scenic not in AREAS:
            return {"error": f"不支持的景区：{scenic}"}
        conds = []
        for n, d in self.G.nodes(data=True):
            if d.get("kind") != "条件" or f":{scenic}:" not in n:
                continue
            text = d.get("name", "") + " " + d.get("suggestion", "")
            if visitor_type and d.get("cond_type") == "人群" and not self._match_visitor(text, visitor_type):
                continue
            conds.append({"cond_type": d.get("cond_type"), "condition": d.get("name"),
                          "suggestion": d.get("suggestion"), "frequency": int(float(d.get("frequency", 1) or 1))})
        # 人群类匹配游客类型的优先；其余按类型相关性排序
        type_rank = {"人群": 0, "装备": 1, "体力安全": 2, "天气": 3, "时间": 4, "预约票务": 5, "交通": 6, "一般": 7, "其他": 8}
        conds.sort(key=lambda c: (type_rank.get(c["cond_type"], 9), -c["frequency"]))
        return {"scenic": scenic, "visitor_type": visitor_type, "conditions": conds[:limit]}

    # ── 工具4：query_order ──────────────────────────────────────
    def query_order(self, scenic: str, poi: str) -> dict:
        node = next((n for n in self.poi_nodes(scenic) if self.poi_label(n) == poi), None)
        if node is None:
            return {"error": f"{scenic} 中未找到景点：{poi}"}
        successors, predecessors = [], []
        for _, v, e in self.G.out_edges(node, data=True):
            if e.get("relation") == "先后顺序":
                successors.append({"poi": self.poi_label(v), "weight": float(e.get("weight", 0))})
        for u, _, e in self.G.in_edges(node, data=True):
            if e.get("relation") == "先后顺序":
                predecessors.append({"poi": self.poi_label(u), "weight": float(e.get("weight", 0))})
        successors.sort(key=lambda x: -x["weight"])
        predecessors.sort(key=lambda x: -x["weight"])
        return {"poi": poi, "next": successors[:6], "prev": predecessors[:6]}

    # ── 工具5：query_poi_conditions（P6 行程可行性）──────────────
    def query_poi_conditions(self, scenic: str, poi: str) -> dict:
        node = next((n for n in self.poi_nodes(scenic) if self.poi_label(n) == poi), None)
        if node is None:
            return {"error": f"{scenic} 中未找到景点：{poi}"}
        conds = []
        for u, v, e in self.G.out_edges(node, data=True):
            if e.get("relation") != "条件建议" or not self.G.has_node(v):
                continue
            d = self.G.nodes[v]
            conds.append({"condition": d.get("name", ""), "suggestion": d.get("suggestion", ""),
                          "cond_type": d.get("cond_type"), "frequency": int(float(e.get("weight", 1) or 1))})
        conds.sort(key=lambda c: -c["frequency"])
        return {"poi": poi, "scenic": scenic, "conditions": conds}

    # ── 工具6：query_path（P5 多跳动线）──────────────────────────
    def _resolve_poi(self, scenic: str, name: str):
        """POI 名解析：精确 → 前缀互含 → 子串。"""
        labels = {self.poi_label(n): n for n in self.poi_nodes(scenic)}
        if name in labels:
            return labels[name]
        for label, node in labels.items():
            if label.startswith(name) or name.startswith(label):
                return node
        for label, node in labels.items():
            if name in label or label in name:
                return node
        return None

    def query_path(self, scenic: str, from_poi: str, to_poi: str) -> dict:
        src = self._resolve_poi(scenic, from_poi)
        dst = self._resolve_poi(scenic, to_poi)
        if src is None or dst is None:
            return {"error": f"{scenic} 中未找到景点：{from_poi if src is None else to_poi}"}
        if src == dst:
            return {"from": from_poi, "to": to_poi, "path": [from_poi], "hops": 0}
        try:
            path = nx.shortest_path(self.G, src, dst, weight=None)
        except nx.NetworkXNoPath:
            return {"from": from_poi, "to": to_poi, "path": [], "hops": None,
                    "note": "先后顺序图中无有向路径（可反向查询或分段游览）"}
        labels = [self.poi_label(n) for n in path]
        return {"from": from_poi, "to": to_poi, "path": labels, "hops": len(labels) - 1}

    # ── 统一调用入口（记录 trace；trace 传入时同步 action/observation 两步）──
    def call(self, tool: str, args: dict, trace: list | None = None) -> dict:
        if tool not in {t["name"] for t in TOOL_SCHEMAS}:
            result = {"error": f"未知工具：{tool}"}
        else:
            result = getattr(self, tool)(**args)
        summary = self._summarize(result)
        self.trace.append({"tool": tool, "args": args, "summary": summary})
        if trace is not None:
            trace.append({"step": "action", "thought": f"调用工具 {tool}，参数 {args}", "tool": tool, "args": args})
            trace.append({"step": "observation", "tool": tool, "summary": summary})
        return result

    @staticmethod
    def _summarize(result: dict) -> str:
        if "error" in result:
            return f"错误：{result['error']}"
        if "pois" in result:
            return f"返回 {len(result['pois'])} 个 POI：" + "、".join(p["poi"] for p in result["pois"][:6])
        if "steps" in result:
            return f"路线 {result['route_title']}，共 {len(result['steps'])} 步"
        if "conditions" in result:
            return f"返回 {len(result['conditions'])} 条条件建议"
        if "next" in result:
            return f"后继：{'、'.join(x['poi'] for x in result['next'][:4]) or '无'}"
        return "ok"
