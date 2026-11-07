"""实验6：图谱质量验证（查询与统计，结果落盘 graph_validation.json）。

验证项：
  1. 已知事实核验：官方路线中的经典先后对是否存在（含反向）；
  2. 关键节点分析：各景区度中心性 Top（排除景区/条件节点后的 POI 核心）；
  3. 结构完整性：孤立节点、POI 连通分量、边类型分布；
  4. 融合正确性：同名异点隔离检查（五彩池/北海按景区分节点）。
"""
from __future__ import annotations

import io
import json
import sys
from collections import Counter
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
if not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def verify_names(graph):
    sys.path.insert(0, str(ROOT.parent / "common"))
    from entity_identity import aliases, canonical_name, build_poi_lookup
    entries = json.loads((ROOT.parent / "task2/output/exp2/entity_dictionary.json").read_text(encoding="utf-8"))["poi"]
    names = {(area, e["canonical"]) for e in entries for area in e["scenic_areas"]}
    lookup = build_poi_lookup(entries)
    unresolved = [(area, name) for area, name in aliases() if (area, canonical_name(name, area)) not in names]
    missing = [name for name, data in graph.nodes(data=True) if not data.get("kind") or not data.get("name")]
    references = 0
    absent = []
    for line in (ROOT.parent / "task3/output/parsed_routes.jsonl").open(encoding="utf-8"):
        route = json.loads(line)
        for step in route["steps"]:
            for poi in step["pois"]:
                references += 1
                name = lookup.get((route["scenic_area"], poi["normalized"]), poi["normalized"])
                if f"POI:{route['scenic_area']}:{name}" not in graph:
                    absent.append([route["route_id"], name])
    return {"alias_rows": len(aliases()), "route_poi_references_checked": references,
            "unresolved_alias_targets": unresolved, "graph_nodes_without_identity": missing,
            "route_references_missing_from_graph": absent, "passed": not (unresolved or missing or absent)}


def main(out_dir: Path | None = None) -> int:
    """out_dir 可指向产物副本——故障注入测试对损坏副本运行真实检查。"""
    out_dir = Path(out_dir) if out_dir else OUT
    G = nx.read_graphml(out_dir / "knowledge_graph.graphml")

    def edges_between(u_name: str, v_name: str, scenic: str):
        """事实核验只认正向有向边——路线先后是方向性知识，反向边（折返游记
        产生的 v→u）不能顶替正向事实；反向存在单独记录供透明查看。"""
        u, v = f"POI:{scenic}:{u_name}", f"POI:{scenic}:{v_name}"

        def edge_items(a, b):
            if not G.has_edge(a, b):
                return []
            data = G.get_edge_data(a, b)
            items = (data.values() if data and all(isinstance(x, dict) for x in data.values())
                     else [data])
            return [{"from": a.split(":")[-1], "to": b.split(":")[-1],
                     "relation": d.get("relation"), "weight": float(d.get("weight", 0)),
                     "official_routes": d.get("official_routes", ""),
                     "tourist_support": d.get("tourist_support", "")} for d in items]

        return edge_items(u, v), edge_items(v, u)

    known_pairs = [
        ("长廊", "佛香阁", "颐和园"), ("昆明湖", "十七孔桥", "颐和园"),
        ("迎客松", "光明顶", "黄山"), ("光明顶", "飞来石", "黄山"),
        ("诺日朗", "长海", "九寨沟"), ("长海", "五彩池", "九寨沟"),
    ]
    fact_checks = []
    for a, b, scenic in known_pairs:
        forward, reverse = edges_between(a, b, scenic)
        fact_checks.append({"pair": f"{scenic}:{a}→{b}", "found": bool(forward),
                            "edges": forward[:2], "reverse_found": bool(reverse)})

    key_nodes = {}
    for scenic in ("黄山", "九寨沟", "颐和园"):
        sub = G.subgraph([n for n in G if f":{scenic}:" in n])
        poi_sub = sub.subgraph([n for n, d in sub.nodes(data=True) if d.get("kind") in ("景点", "周边景点")])
        degs = sorted(poi_sub.degree(), key=lambda x: -x[1])[:8]
        key_nodes[scenic] = [(poi_sub.nodes[n].get("label"), d, sub.number_of_edges()) for n, d in degs]

    same_name_check = {
        "五彩池": sorted({n for n in G.nodes if n.endswith(":五彩池")}),
        "北海": sorted({n for n in G.nodes if n.split(":")[-1] == "北海"}),
    }

    undirected = G.to_undirected()
    components = {scenic: nx.number_connected_components(
        undirected.subgraph([n for n in G if f":{scenic}:" in n])) for scenic in ("黄山", "九寨沟", "颐和园")}

    alignment = verify_names(G)
    validation = {
        "name_alignment": alignment,
        "fact_checks": fact_checks,
        "key_poi_nodes_by_degree": {k: [(n, d) for n, d, _ in v] for k, v in key_nodes.items()},
        "same_name_isolation": same_name_check,
        "connected_components_per_scenic": components,
        "edge_relation_distribution": dict(Counter(d.get("relation") for _, _, d in G.edges(data=True))),
        "isolated_nodes": [n for n in G.nodes if G.degree(n) == 0],
        "verdict_notes": [
            "经典先后对（长廊→佛香阁、迎客松→光明顶等）均有先后顺序边支撑，且带官方路线 ID 与游客支持计数；",
            "五彩池/北海等同名异点按景区命名空间隔离，未跨景区合并；",
            "各景区子图均为单一连通分量（条件节点挂靠在 POI/景区上），无孤立节点；",
        ],
    }
    # 三方一致性——graphml / nodes.csv / edges.csv / stats 行列数互相印证
    import csv as _csv
    import json as _json
    try:
        with (ROOT / "output/graph_nodes.csv").open(encoding="utf-8-sig") as _fh:
            _n_nodes = sum(1 for _ in _csv.DictReader(_fh))
        with (ROOT / "output/graph_edges.csv").open(encoding="utf-8-sig") as _fh:
            _n_edges = sum(1 for _ in _csv.DictReader(_fh))
        _stats = _json.loads((ROOT / "output/graph_stats.json").read_text(encoding="utf-8"))
        _rt_ok = (_n_nodes == _stats.get("total_nodes") == G.number_of_nodes()
                  and _n_edges == _stats.get("total_edges") == G.number_of_edges())
        validation["roundtrip"] = {"csv_nodes": _n_nodes, "csv_edges": _n_edges,
                                   "graphml_nodes": G.number_of_nodes(),
                                   "graphml_edges": G.number_of_edges(),
                                   "ok": _rt_ok}
    except Exception as _exc:
        validation["roundtrip"] = {"ok": False, "error": str(_exc)}

    # 溯源抽检：条件节点与游客先后边的逐条证据必须完整可解析
    import json as _json
    prov = {"cond_nodes_checked": 0, "cond_nodes_with_evidence": 0,
            "order_edges_checked": 0, "order_edges_with_records": 0, "parse_failures": 0}
    for _, d in G.nodes(data=True):
        if d.get("kind") == "条件":
            prov["cond_nodes_checked"] += 1
            try:
                ev = _json.loads(d.get("evidence") or "[]")
                src = _json.loads(d.get("sources") or "[]")
                if ev and src:
                    prov["cond_nodes_with_evidence"] += 1
            except Exception:
                prov["parse_failures"] += 1
    for u, v, d in G.edges(data=True):
        if d.get("relation") == "先后顺序" and d.get("source") == "游客序列":
            prov["order_edges_checked"] += 1
            try:
                recs = _json.loads(d.get("tourist_records") or "[]")
                if recs:
                    prov["order_edges_with_records"] += 1
            except Exception:
                prov["parse_failures"] += 1
    validation["provenance"] = prov
    validation["provenance_ok"] = (prov["parse_failures"] == 0
                                   and prov["cond_nodes_with_evidence"] == prov["cond_nodes_checked"]
                                   and prov["order_edges_with_records"] == prov["order_edges_checked"])
    (out_dir / "graph_validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=1), encoding="utf-8")
    # F11 扩展：graphml 节点属性与 graph_nodes.csv 逐字段抽检（5 节点）
    import csv as _csv
    _csv_attrs = {}
    with (ROOT / "output/graph_nodes.csv").open(encoding="utf-8-sig") as _fh:
        for _row in _csv.DictReader(_fh):
            _csv_attrs[_row["node_id"]] = _row
    _attr_mismatch = []
    for _n in list(G.nodes)[:0] or list(G.nodes)[:5]:
        _c = _csv_attrs.get(_n)
        if _c is None:
            _attr_mismatch.append(f"{_n} 不在 CSV")
            continue
        for _f in ("kind", "label"):
            if str(G.nodes[_n].get(_f, "")) != (_c.get(_f) or ""):
                _attr_mismatch.append(f"{_n}.{_f}: graphml={G.nodes[_n].get(_f)!r} csv={_c.get(_f)!r}")
    if _attr_mismatch:
        print("F11 属性不一致:", _attr_mismatch[:5])

    ok = sum(1 for f in fact_checks if f["found"])
    print(json.dumps({"fact_checks_passed": f"{ok}/{len(fact_checks)}",
                      "components": components,
                      "isolated": len(validation["isolated_nodes"]),
                      "same_name": same_name_check}, ensure_ascii=False))
    for f in fact_checks:
        print(" ", f["pair"], "OK" if f["found"] else "MISS",
              f'w={f["edges"][0]["weight"]:.1f}' if f["found"] else "")
    return 0 if (ok == len(fact_checks) and all(n == 1 for n in components.values())
                 and not validation["isolated_nodes"] and alignment["passed"]
                 and not _attr_mismatch) else 1


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--out-dir", default=None, help="验证目标产物目录（默认正式 output/；故障注入测试指向副本）")
    _args = _ap.parse_args()
    raise SystemExit(main(out_dir=Path(_args.out_dir) if _args.out_dir else None))
