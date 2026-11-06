"""实验7 F06：官方/游客证据权重对下游编排的敏感性。

先后顺序边为"官方路线 + 游客序列"双源加权（build_graph），边级来源已保留
（official_routes / tourist_support 列）。本分析构造三种权重方案：
- mixed（现行）：官方次数 + 去重游客支持数
- official_only：仅官方边（权重=官方路线次数）
- tourist_only：仅游客边（权重=去重游客支持数）

对全部 15 个验收场景在每种方案下重跑（运行期替换 GraphTools.G 的先后顺序边），
对比行程站点序列（Kendall tau）与场景通过数——量化证据权重选择对下游的传导。
输出 metrics/f06_weight_sensitivity.json。
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

import networkx as nx

from agent_cli import ReActAgent
from run_tests import SCENARIOS, evaluate_scenario

OUT = REPO / "metrics"


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


def main() -> int:
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
        "title": "F06 权重方案敏感性：官方/游客证据分离对下游编排的传导（实验7）",
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
    (OUT / "f06_weight_sensitivity.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(passes, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
