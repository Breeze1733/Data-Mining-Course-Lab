"""Experiment 7: knowledge graph query tool layer (called by the Agent).

Every tool has a name, description, parameter schema and structured return, and logs its calls.
Data sources: task6/output/knowledge_graph.graphml + task3/output/parsed_routes.jsonl.
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


_GRAPH_CACHE: dict = {}


class GraphTools:
    def __init__(self):
        # Cache the graphml parse result by file mtime -- the eval chain builds a new Agent instance each time;
        # the cache avoids re-parsing the same graph, which is read-only within the process
        mtime = (OUT6 / "knowledge_graph.graphml").stat().st_mtime
        if _GRAPH_CACHE.get("mtime") != mtime:
            try:
                _GRAPH_CACHE["G"] = nx.read_graphml(OUT6 / "knowledge_graph.graphml")
            except Exception as exc:
                # Corrupted graph file -> structured error instead of a constructor crash (the Agent can fall back stably)
                _GRAPH_CACHE["G"] = None
                _GRAPH_CACHE["load_error"] = f"图谱文件解析失败：{exc}"
            _GRAPH_CACHE["mtime"] = mtime
        self.G = _GRAPH_CACHE["G"]
        if self.G is None:
            self.load_error = _GRAPH_CACHE.get("load_error", "图谱加载失败")
        else:
            self.load_error = None
        self.routes = [json.loads(l) for l in (TASK3 / "parsed_routes.jsonl").open(encoding="utf-8")]
        self.trace: list[dict] = []
        self._qcache: dict = {}


    def poi_nodes(self, scenic: str) -> list[str]:
        return [n for n, d in self.G.nodes(data=True)
                if d.get("kind") in ("景点", "周边景点") and f":{scenic}:" in n]

    def poi_label(self, node: str) -> str:
        return self.G.nodes[node].get("label", node.split(":")[-1])

    def _match_visitor(self, text: str, visitor_type: str | None) -> bool:
        if not visitor_type:
            return True
        for v in (visitor_type if isinstance(visitor_type, (list, tuple)) else [visitor_type]):
            kws = VISITOR_KEYWORDS.get(v, [v])
            if any(k in text for k in kws):
                return True
        return False


    def query_pois(self, scenic: str, visitor_type: str | None = None, limit: int = 8) -> dict:
        if scenic not in AREAS:
            return {"error": f"不支持的景区：{scenic}（仅支持 {'/'.join(AREAS)}）"}
        # limit type/range validation (a negative slice once cut off the tail of results instead of raising)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return {"error": f"limit 须为整数，收到：{limit!r}"}
        if limit <= 0:
            return {"error": f"limit 须为正整数，收到：{limit}"}
        limit = min(limit, 50)
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
                            # negative visitor-group advice (e.g. “老人千万别走中轴线爬山”) is not positive fit --
                            # downweight it and record it as a caveat, not as a bonus
                            fit -= float(e.get("weight", 1))
                            caveats.append(self.G.nodes[v].get("suggestion", "")[:40])
                        else:
                            fit += float(e.get("weight", 1))
            cand.append({"poi": d.get("label", n), "degree": self.G.degree(n),
                         "mention_freq": int(float(d.get("mention_freq", 0) or 0)),
                         "periods": periods, "transports": transports, "visitor_fit": fit,
                         "visitor_caveats": caveats[:2]})
        # POIs with visitor-type fit come first (higher fit first), then graph degree and mention frequency
        cand.sort(key=lambda x: (x["visitor_fit"] > 0, x["visitor_fit"], x["degree"], x["mention_freq"]),
                  reverse=True)
        return {"scenic": scenic, "visitor_type": visitor_type, "pois": cand[:limit]}


    def query_route(self, scenic: str, days: int = 1) -> dict:
        if scenic not in AREAS:
            return {"error": f"不支持的景区：{scenic}"}
        cands = [r for r in self.routes
                 if r["scenic_area"] == scenic and r["ordered_route"] and r["step_count"] >= 2]
        # prefer day-count matches (max day appearing in the steps), then step count
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


    def query_conditions(self, scenic: str, visitor_type: str | None = None, limit: int = 6) -> dict:
        if scenic not in AREAS:
            return {"error": f"不支持的景区：{scenic}"}
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return {"error": f"limit 须为整数，收到：{limit!r}"}
        if limit <= 0:
            return {"error": f"limit 须为正整数，收到：{limit}"}
        limit = min(limit, 60)
        conds = []
        for n, d in self.G.nodes(data=True):
            if d.get("kind") != "条件" or f":{scenic}:" not in n:
                continue
            all_sugg = []
            try:
                all_sugg = json.loads(d.get("suggestions", "[]"))
            except (json.JSONDecodeError, TypeError):
                pass
            if not all_sugg:
                all_sugg = [d.get("suggestion", "")]
            text = d.get("name", "") + " " + " ".join(all_sugg)
            if visitor_type and d.get("cond_type") == "人群" and not self._match_visitor(text, visitor_type):
                continue
            conds.append({"cond_type": d.get("cond_type"), "condition": d.get("name"),
                          "suggestion": d.get("suggestion"),
                          "all_suggestions": all_sugg[:5],
                          "frequency": int(float(d.get("frequency", 1) or 1))})
        # visitor-group conditions matching the visitor type come first; the rest sort by type relevance
        type_rank = {"人群": 0, "装备": 1, "体力安全": 2, "住宿": 3, "天气": 4, "时间": 5,
                     "预约票务": 6, "交通": 7, "美食": 8, "拍照": 9, "一般": 10, "其他": 11}
        conds.sort(key=lambda c: (type_rank.get(c["cond_type"], 9), -c["frequency"]))
        return {"scenic": scenic, "visitor_type": visitor_type, "conditions": conds[:limit]}


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
                          "cond_type": d.get("cond_type"), "frequency": int(float(e.get("weight", 1) or 1)),
                          "source_years": d.get("source_years", "[]")})
        conds.sort(key=lambda c: -c["frequency"])
        return {"poi": poi, "scenic": scenic, "conditions": conds}


    def _resolve_poi(self, scenic: str, name: str):
        """POI name resolution: exact -> mutual prefix -> substring."""
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
        # Paths are restricted to same-scenic-area POIs -- cross-area precedence edges (e.g. surrounding landmark -> on-mountain) do not imply walkability
        same_scenic = {n for n in self.G.nodes
                       if f":{scenic}:" in n and self.G.nodes[n].get("kind") in ("景点", "周边景点")}
        try:
            path = nx.shortest_path(self.G.subgraph(same_scenic), src, dst, weight=None)
        except nx.NetworkXNoPath:
            return {"from": from_poi, "to": to_poi, "path": [], "hops": None,
                    "note": "先后顺序图中无有向路径（可反向查询或分段游览）"}
        labels = [self.poi_label(n) for n in path]
        return {"from": from_poi, "to": to_poi, "path": labels, "hops": len(labels) - 1}


    def call(self, tool: str, args: dict, trace: list | None = None) -> dict:
        if self.G is None:
            return {"error": f"图谱不可用：{getattr(self, 'load_error', '加载失败')}"}
        if tool not in {t["name"] for t in TOOL_SCHEMAS}:
            result = {"error": f"未知工具：{tool}"}
        else:
            # Deterministic same-args query cache within one instance (the trace still records every step)
            key = (tool, json.dumps(args, ensure_ascii=False, sort_keys=True, default=str))
            if key not in self._qcache:
                self._qcache[key] = getattr(self, tool)(**args)
            result = self._qcache[key]
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
