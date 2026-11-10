# -*- coding: utf-8 -*-
"""实验7 评估套件：模块消融 + 权重方案敏感性（规则模式，离线）。

- 模块消融：10 个模块逐一运行期禁用 × 15 个验收场景，量化各模块对最终规划的贡献
- 权重敏感性：先后顺序边 mixed/official_only/tourist_only 三方案 × 15 场景的行程序列对比

运行：python src/evaluations.py [--modules|--weights]（默认两个都跑）。
输出 task7/output/ablation_modules.json 与 metrics/weight_sensitivity.json。
"""
from __future__ import annotations

import io
import json
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

METRICS = REPO / "metrics"
OUT = ROOT / "output"

from agent_cli import GraphTools, IntentParser, ReActAgent  # noqa: E402
from run_tests import SCENARIOS, evaluate_scenario  # noqa: E402


_ORIG = {}  # 原方法引用，_make_patches 时填充


def _err(**_kw):
    return {"error": "消融：该工具已禁用"}


def _make_patches() -> dict[str, tuple[str, callable, callable]]:
    """名称 → (说明, 打补丁, 恢复)。恢复一律 setattr 回原引用，不用 delattr。"""
    _ORIG.update({
        "query_conditions": GraphTools.query_conditions,
        "query_order": GraphTools.query_order,
        "query_path": GraphTools.query_path,
        "routes_by_scenic": GraphTools.routes_by_scenic,
        "query_poi_conditions": GraphTools.query_poi_conditions,
        "query_pois": GraphTools.query_pois,
        "_find_lodging_poi": ReActAgent._find_lodging_poi,
        "_find_sunrise_poi": ReActAgent._find_sunrise_poi,
        "_apply_time_budget": ReActAgent._apply_time_budget,
        "parse": IntentParser.parse,
    })
    patches: dict[str, tuple[str, callable, callable]] = {}

    def add(name, desc, apply, undo):
        patches[name] = (desc, apply, undo)


    add("no_tips", "禁用 query_conditions（条件贴士消失）",
        lambda: setattr(GraphTools, "query_conditions",
                        lambda self, scenic, visitor_type=None, limit=6: _err()),
        lambda: setattr(GraphTools, "query_conditions", _ORIG["query_conditions"]))
    add("no_order_check", "禁用 query_order（官方后继校验消失）",
        lambda: setattr(GraphTools, "query_order", lambda self, scenic, poi: _err()),
        lambda: setattr(GraphTools, "query_order", _ORIG["query_order"]))
    add("no_path", "禁用 query_path（多跳动线查询消失）",
        lambda: setattr(GraphTools, "query_path", lambda self, scenic, from_poi, to_poi: _err()),
        lambda: setattr(GraphTools, "query_path", _ORIG["query_path"]))
    add("no_template", "禁用官方路线模板（编排退化为图谱拓扑排序）",
        lambda: setattr(GraphTools, "routes_by_scenic", lambda self, scenic, days: []),
        lambda: setattr(GraphTools, "routes_by_scenic", _ORIG["routes_by_scenic"]))
    add("no_poi_cond", "禁用 query_poi_conditions（站点级可行性校验失去数据源）",
        lambda: setattr(GraphTools, "query_poi_conditions", lambda self, scenic, poi: _err()),
        lambda: setattr(GraphTools, "query_poi_conditions", _ORIG["query_poi_conditions"]))
    add("no_visitormatch", "query_pois/query_conditions 的 visitor_type 恒为 None（人群适配消失）",
        lambda: (setattr(GraphTools, "query_pois",
                        lambda self, scenic, visitor_type=None, limit=8:
                        _ORIG["query_pois"](self, scenic, None, limit)),
                 setattr(GraphTools, "query_conditions",
                         lambda self, scenic, visitor_type=None, limit=6:
                         _ORIG["query_conditions"](self, scenic, None, limit))),
        lambda: (setattr(GraphTools, "query_pois", _ORIG["query_pois"]),
                 setattr(GraphTools, "query_conditions", _ORIG["query_conditions"])))


    add("no_lodging", "禁用住宿注入（多日行程无住宿 POI）",
        lambda: setattr(ReActAgent, "_find_lodging_poi", lambda self, scenic: None),
        lambda: setattr(ReActAgent, "_find_lodging_poi", _ORIG["_find_lodging_poi"]))
    add("no_sunrise", "禁用日出重定位（看日出特殊需求失效）",
        lambda: setattr(ReActAgent, "_find_sunrise_poi", lambda self, scenic, ordered: None),
        lambda: setattr(ReActAgent, "_find_sunrise_poi", _ORIG["_find_sunrise_poi"]))
    add("no_budget", "禁用时段预算（POI 不裁剪，行程可能超载）",
        lambda: setattr(ReActAgent, "_apply_time_budget",
                        lambda self, ordered, days, n_days, sp, notes, trace: ordered),
        lambda: setattr(ReActAgent, "_apply_time_budget", _ORIG["_apply_time_budget"]))


    def _parse_no_avoid(self, query, trace):
        intent = _ORIG["parse"](self, query, trace)
        intent["avoid"] = []
        intent["must"] = []
        return intent

    add("no_avoid_must", "意图解析丢弃 avoid/must（不去/必去约束失效）",
        lambda: setattr(IntentParser, "parse", _parse_no_avoid),
        lambda: setattr(IntentParser, "parse", _ORIG["parse"]))
    return patches


def _run_all_scenarios() -> tuple[list, int, int]:
    """跑全部场景（规则模式），返回 (失败列表, 工具调用总数, 回答总字数)。"""
    fails, n_tools, n_chars = [], 0, 0
    for sc in SCENARIOS:
        agent = ReActAgent(None)
        result = agent.run(sc["query"])
        checks = evaluate_scenario(sc, result, rules=True)
        n_tools += len([t for t in result["trace"] if t.get("step") == "action"])
        n_chars += len(result["answer"])
        if not all(checks.values()):
            fails.append({"scenario": sc["id"],
                          "failed_checks": [k for k, v in checks.items() if not v]})
    return fails, n_tools, n_chars


def run_module_ablation() -> int:
    fails, n_tools, n_chars = _run_all_scenarios()
    baseline = {"ablation": "baseline（无禁用）", "description": "完整管线基线",
                "n_passed": len(SCENARIOS) - len(fails), "n_failed": len(fails),
                "failed_scenarios": fails,
                "avg_tool_calls": round(n_tools / len(SCENARIOS), 1),
                "avg_answer_chars": round(n_chars / len(SCENARIOS))}
    print(f'baseline         pass={baseline["n_passed"]:2d}/{len(SCENARIOS)}')
    rows = []
    base_pass = baseline["n_passed"]
    for name, (desc, apply, undo) in _make_patches().items():
        apply()
        try:
            fails, n_tools, n_chars = _run_all_scenarios()
        finally:
            undo()
        rows.append({"ablation": name, "description": desc,
                     "n_passed": len(SCENARIOS) - len(fails), "n_failed": len(fails),
                     "failed_scenarios": fails,
                     "avg_tool_calls": round(n_tools / len(SCENARIOS), 1),
                     "avg_answer_chars": round(n_chars / len(SCENARIOS)),
                     "contribution_n_scenarios": base_pass - (len(SCENARIOS) - len(fails))})
        print(f'{name:16s} pass={rows[-1]["n_passed"]:2d}/{len(SCENARIOS)} '
              f'fail={len(fails)} avg_tools={rows[-1]["avg_tool_calls"]}')
    report = {
        "title": "模块消融：各模块对最终规划的贡献（实验7，规则模式）",
        "method": "对 14 个验收场景逐一禁用单个模块后重跑；口径与 run_tests.evaluate_scenario 一致；"
                  "contribution = 基线通过数 − 消融后通过数（受该模块影响的场景数）",
        "n_scenarios": len(SCENARIOS),
        "baseline": baseline,
        "ablations": sorted(rows, key=lambda r: -r["contribution_n_scenarios"]),
        "notes": [
            "contribution=0 不代表模块无用：验收断言未覆盖的行为（如排序质量、贴士排序）不受场景断言约束",
            "消融仅运行期补丁，生产代码路径未改动；基线与消融均为确定性规则模式（任务1-6离线，任务7 rules）",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ablation_modules.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({r["ablation"]: r["contribution_n_scenarios"] for r in rows},
                     ensure_ascii=False, indent=1))
    return 0


def kendall_tau(a: list, b: list) -> float | None:
    common = [x for x in a if x in b]
    b_common = [x for x in b if x in a]
    if len(common) < 2:
        return None
    pairs = list(combinations(range(len(common)), 2))
    conc = disc = 0
    for i, j in pairs:
        da = common.index(common[i]) - common.index(common[j])
        db = b_common.index(common[i]) - b_common.index(common[j])
        conc += da * db > 0
        disc += da * db < 0
    total = conc + disc
    return round((conc - disc) / total, 3) if total else None


def build_variant_graph(G: nx.DiGraph, scheme: str) -> nx.DiGraph:
    H = G.copy()
    for u, v, d in list(G.edges(data=True)):
        if d.get("relation") != "先后顺序":
            continue
        official_n = len(d.get("official_routes") or [])
        tourist_n = int(float(d.get("tourist_support") or 0))
        if scheme == "official_only":
            if official_n:
                H[u][v]["weight"] = float(official_n)
            else:
                H.remove_edge(u, v)
        elif scheme == "tourist_only":
            if tourist_n:
                H[u][v]["weight"] = float(tourist_n)
            else:
                H.remove_edge(u, v)
    return H


def run_all(G_variant: nx.MultiDiGraph) -> tuple[dict[str, list], int, list]:
    seqs, n_pass, fails = {}, 0, []
    agent = ReActAgent(None)
    agent.tools.G = G_variant
    for sc in SCENARIOS:
        r = agent.run(sc["query"])
        checks = evaluate_scenario(sc, r, rules=True)
        if all(checks.values()):
            n_pass += 1
        else:
            fails.append(sc["id"])
        plan = r.get("plan") or {}
        seqs[sc["id"]] = [it["poi"] for it in plan.get("itinerary", [])]
    return seqs, n_pass, fails


def run_weight_sensitivity() -> int:
    base = ReActAgent(None)
    G = base.tools.G
    results, passes, seqs_by = {}, {}, {}
    for scheme in ("mixed", "official_only", "tourist_only"):
        seqs, n_pass, fails = run_all(build_variant_graph(G, scheme))
        seqs_by[scheme] = seqs
        passes[scheme] = {"n_passed": n_pass, "failed": fails}
        print(f"{scheme:14s} pass={n_pass}/15")
    # 方案间行程序列 tau（逐场景，mixed 为参照）
    sens = {}
    for sc in SCENARIOS:
        sid = sc["id"]
        row = {}
        for scheme in ("official_only", "tourist_only"):
            row[scheme] = kendall_tau(seqs_by["mixed"][sid], seqs_by[scheme][sid])
        sens[sid] = row
    report = {
        "title": "权重方案敏感性：官方/游客证据分离对下游编排的传导（实验7）",
        "method": "三种先后顺序边权重方案（mixed=现行官方+游客、official_only、tourist_only）下重跑 15 场景；"
                  "行程站点序列与 mixed 方案做 Kendall tau（公共站点<2 记 None）",
        "n_scenarios": len(SCENARIOS),
        "passes_by_scheme": passes,
        "sequence_tau_vs_mixed": sens,
        "notes": [
            "official_only 可能因官方边稀疏产生更多拓扑序回退；tau=None 表示两方案行程公共站点过少",
            "本分析只读图并运行期替换，不改动生产图谱",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "weight_sensitivity.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(passes, ensure_ascii=False))
    return 0


def main() -> int:
    if "--modules" not in sys.argv:
        run_module_ablation()
    if "--weights" not in sys.argv:
        run_weight_sensitivity()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
