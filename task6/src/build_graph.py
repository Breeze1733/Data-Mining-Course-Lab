"""实验6：多源程序性知识融合与知识图谱构建（NetworkX）。

Schema：
  节点：景区 / 景点POI（含周边景点子类）/ 交通操作（观光车、索道…）/ 时段（上午…晚上）/ 条件（人群/天气/时间/装备…）
  边：  包含（景区→POI）、周边关联（景区→周边景点）、先后顺序（POI→POI，官方+游客双源加权）、
        时段归属（POI→时段）、交通方式（POI→交通操作）、条件建议（POI→条件节点）

融合策略：
  1. 实体对齐：以实验2词典 canonical 为唯一键，景区内命名空间（五彩池按景区隔离，北海限定黄山）；
  2. 来源合并：先后边记录 official_routes / tourist_records 两组来源并分权重（官方 1.0/条，游客 0.5/条）；
  3. 频次加权：时段归属、交通方式边按步骤出现次数累计；
  4. 噪声过滤：仅收录词典内 POI；条件建议边只挂到句中出现的 POI，无 POI 挂景区节点并标记。
输出：graph_nodes.csv、graph_edges.csv、knowledge_graph.graphml、graph_stats.json
"""
from __future__ import annotations

import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize_name import normalize  # noqa: E402  与实验3相同的归一化

ROOT = Path(__file__).resolve().parents[1]
TASK2 = ROOT.parent / "task2"
TASK3 = ROOT.parent / "task3"
TASK5 = ROOT.parent / "task5"
OUT = ROOT / "output"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

AREAS = ("黄山", "九寨沟", "颐和园")
PERIODS = ("上午", "中午", "下午", "晚上")


def main() -> int:
    sys.path.insert(0, str(TASK2 / "src"))
    from extract_entities import DictMatcher, load_dictionary

    entries, stopwords, _ = load_dictionary("refined")
    matcher = DictMatcher(entries, stopwords)
    poi_of = {e["name"]: e for e in entries if e["entity_type"] == "景点POI"}
    transport_of = {e["name"]: e for e in entries if e["entity_type"] == "交通方式"}
    # 名称解析：实验3步骤名经过 normalize（剥离“景区”后缀），与词典 canonical 对齐
    from entity_identity import build_poi_lookup
    name2canon = build_poi_lookup(list(poi_of.values()))
    canonical_areas = defaultdict(set)
    for entry in poi_of.values():
        canonical_areas[entry["canonical"]].update(entry["scenic_areas"])

    def resolve(scenic: str, name: str) -> str:
        return name2canon.get((scenic, name), name)

    parsed = [json.loads(l) for l in (TASK3 / "output/parsed_routes.jsonl").open(encoding="utf-8")]
    tourists = [json.loads(l) for l in (TASK3 / "output/tourist_routes.jsonl").open(encoding="utf-8")]
    mapping = json.loads((TASK5 / "output/mapping_table.json").read_text(encoding="utf-8"))
    stats2 = json.loads((TASK2 / "output/exp2/entity_stats_refined.json").read_text(encoding="utf-8"))
    mention_freq = stats2["top_canonical"]

    G = nx.MultiDiGraph()

    def node_id(kind: str, scenic: str, name: str) -> str:
        return f"{kind}:{scenic}:{name}"

    # ── 景区与 POI 节点 ─────────────────────────────────────────
    for scenic in AREAS:
        G.add_node(node_id("景区", scenic, scenic), kind="景区", name=scenic, label=scenic)
    for e in poi_of.values():
        for scenic in e["scenic_areas"]:
            if scenic == "通用":
                continue
            freq = mention_freq.get("景点POI", {}).get(e["canonical"], 0)
            G.add_node(node_id("POI", scenic, e["canonical"]), kind=e["subtype"], name=e["canonical"],
                       label=e["canonical"], mention_freq=freq, aliases=e["name"])
            rel = "周边关联" if e["subtype"] == "周边景点" else "包含"
            G.add_edge(node_id("景区", scenic, scenic), node_id("POI", scenic, e["canonical"]),
                       key=rel, relation=rel, weight=1)

    # ── 先后顺序边（官方路线 + 游客序列，双源加权）───────────────
    official_support: dict[tuple, list[str]] = defaultdict(list)
    for p in parsed:
        if not p["ordered_route"]:
            continue
        scenic = p["scenic_area"]
        seq = p["pois_in_order"]
        for a, b in zip(seq, seq[1:]):
            if a == b:
                continue
            u, v = node_id("POI", scenic, resolve(scenic, a)), node_id("POI", scenic, resolve(scenic, b))
            if G.has_edge(u, v, key="先后顺序"):
                G[u][v]["先后顺序"]["weight"] += 1.0
            else:
                G.add_edge(u, v, key="先后顺序", relation="先后顺序", weight=1.0, source="官方路线")
            official_support[(u, v)].append(p["route_id"])
    tourist_support: dict[tuple, int] = Counter()
    for t in tourists:
        scenic = t["scenic_area"]
        for a, b in zip(t["distinct_pois"], t["distinct_pois"][1:]):
            u, v = node_id("POI", scenic, resolve(scenic, a)), node_id("POI", scenic, resolve(scenic, b))
            if not (G.has_node(u) and G.has_node(v)):
                continue
            if G.has_edge(u, v, key="先后顺序"):
                G[u][v]["先后顺序"]["weight"] += 0.5
            else:
                G.add_edge(u, v, key="先后顺序", relation="先后顺序", weight=0.5, source="游客序列")
            tourist_support[(u, v)] += 1
    for (u, v), route_ids in official_support.items():
        if G.has_edge(u, v, key="先后顺序"):
            G[u][v]["先后顺序"]["official_routes"] = "；".join(dict.fromkeys(route_ids))[:200]
            G[u][v]["先后顺序"]["tourist_support"] = tourist_support.get((u, v), 0)

    # ── 时段与交通（来自官方路线步骤）────────────────────────────
    period_freq: dict[str, Counter] = defaultdict(Counter)
    transport_freq: dict[str, Counter] = defaultdict(Counter)
    for p in parsed:
        if not p["ordered_route"]:
            continue
        scenic = p["scenic_area"]
        for s in p["steps"]:
            period = s["period"] or "未标注时段"
            for poi in {resolve(scenic, x["normalized"]) for x in s["pois"]}:
                period_freq[scenic][period] += 1
                u, v = node_id("POI", scenic, poi), node_id("时段", scenic, period)
                if not G.has_node(v):
                    G.add_node(v, kind="时段", name=period, label=period)
                if G.has_edge(u, v, key="时段归属"):
                    G[u][v]["时段归属"]["weight"] += 1
                else:
                    G.add_edge(u, v, key="时段归属", relation="时段归属", weight=1)
            for tr in s["transport"]:
                if tr not in transport_of:
                    continue
                tn = node_id("交通操作", scenic, tr)
                if not G.has_node(tn):
                    G.add_node(tn, kind="交通操作", name=tr, label=tr)
                for poi in {resolve(scenic, x["normalized"]) for x in s["pois"]}:
                    u = node_id("POI", scenic, poi)
                    transport_freq[scenic][tr] += 1
                    if G.has_edge(u, tn, key="交通方式"):
                        G[u][tn]["交通方式"]["weight"] += 1
                    else:
                        G.add_edge(u, tn, key="交通方式", relation="交通方式", weight=1)

    # ── 条件建议边（实验5映射表 → 句中 POI）──────────────────────
    cond_edges = 0
    cond_to_scenic = 0
    for m in mapping:
        scenic = m["scenic_area"]
        cn = node_id("条件", scenic, f'{m["condition_type"]}:{m["condition_text"][:18]}')
        if not G.has_node(cn):
            G.add_node(cn, kind="条件", name=m["condition_text"][:30], label=f'[{m["condition_type"]}] {m["condition_text"][:24]}',
                       cond_type=m["condition_type"], suggestion=m["suggestion_text"][:100],
                       frequency=m["frequency"])
        text = m["condition_text"] + " " + m["suggestion_text"]
        pois_in_text = [resolve(scenic, e["canonical"]) for e in matcher.find(text)
                        if e["type"] == "景点POI"
                        and scenic in canonical_areas.get(e["canonical"], set())
                        and node_id("POI", scenic, resolve(scenic, e["canonical"])) in G]
        if pois_in_text:
            for poi in dict.fromkeys(pois_in_text):
                u = node_id("POI", scenic, poi)
                if G.has_edge(u, cn, key="条件建议"):
                    G[u][cn]["条件建议"]["weight"] += m["frequency"]
                else:
                    G.add_edge(u, cn, key="条件建议", relation="条件建议", weight=m["frequency"])
                cond_edges += 1
        else:
            u = node_id("景区", scenic, scenic)
            G.add_edge(u, cn, key="条件建议", relation="条件建议", weight=m["frequency"])
            cond_to_scenic += 1

    # ── 导出与统计 ──────────────────────────────────────────────
    OUT.mkdir(parents=True, exist_ok=True)
    import csv
    with (OUT / "graph_nodes.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["node_id", "kind", "name", "label", "mention_freq", "cond_type", "suggestion", "frequency"])
        for n, d in G.nodes(data=True):
            w.writerow([n, d.get("kind", ""), d.get("name", ""), d.get("label", ""),
                        d.get("mention_freq", ""), d.get("cond_type", ""), d.get("suggestion", ""),
                        d.get("frequency", "")])
    with (OUT / "graph_edges.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["src", "dst", "relation", "weight", "source", "official_routes", "tourist_support"])
        for u, v, d in G.edges(data=True):
            w.writerow([u, v, d.get("relation", ""), round(d.get("weight", 1), 2),
                        d.get("source", ""), d.get("official_routes", ""), d.get("tourist_support", "")])
    nx.write_graphml(G, OUT / "knowledge_graph.graphml")

    per_scenic = {}
    for scenic in AREAS:
        sub = G.subgraph([n for n in G.nodes if f":{scenic}:" in n])
        degrees = Counter(dict(sub.degree()))
        isolated = [n for n in sub.nodes if sub.degree(n) == 0]
        per_scenic[scenic] = {
            "nodes": sub.number_of_nodes(), "edges": sub.number_of_edges(),
            "by_kind": dict(Counter(d.get("kind", "?") for _, d in sub.nodes(data=True))),
            "by_relation": dict(Counter(d.get("relation", "?") for _, _, d in sub.edges(data=True))),
            "top_degree": [(sub.nodes[n].get("label", n), deg) for n, deg in degrees.most_common(8)],
            "isolated_nodes": len(isolated),
        }
    graph_stats = {
        "total_nodes": G.number_of_nodes(), "total_edges": G.number_of_edges(),
        "by_kind": dict(Counter(d.get("kind", "?") for _, d in G.nodes(data=True))),
        "by_relation": dict(Counter(d.get("relation", "?") for _, _, d in G.edges(data=True))),
        "cond_edges_to_poi": cond_edges, "cond_edges_to_scenic": cond_to_scenic,
        "per_scenic": per_scenic,
        "fusion_policy": {
            "entity_alignment": "实验2词典 canonical 为唯一键，景区命名空间隔离（五彩池/北海不跨景区合并）",
            "source_merge": "先后边=官方1.0/条+游客0.5/条；条件边挂句中POI，无POI挂景区并计数",
            "noise_filter": "仅词典内POI；游客序列需两端节点已存在；周边景点单列子类",
        },
    }
    (OUT / "graph_stats.json").write_text(json.dumps(graph_stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: graph_stats[k] for k in ("total_nodes", "total_edges", "by_kind", "by_relation")},
                     ensure_ascii=False, indent=1))
    for a in AREAS:
        print(a, {k: per_scenic[a][k] for k in ("nodes", "edges", "isolated_nodes")},
              "top:", per_scenic[a]["top_degree"][:4])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
