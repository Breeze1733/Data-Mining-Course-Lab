"""Experiment 6: graph quality verification (queries and statistics; results written to graph_validation.json).

Checks:
  1. Known-fact verification: classic ordering facts — official routes place a before b, and the graph preserves
     that ordering as a directed path over official-backed order edges (adjacency may legitimately change when
     route parsing inserts intermediate stops; ordering, not adjacency, is the fact);
  2. Key-node analysis: degree-centrality top per scenic area (POI core after excluding scenic-area/condition nodes);
  3. Structural integrity: isolated nodes, POI connected components, edge-type distribution, direction-resolution integrity;
  4. Fusion correctness: same-name-different-place isolation check (五彩池/北海 split into per-area nodes).
"""
from __future__ import annotations

import io
import json
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
if not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def verify_names(graph):
    data = json.loads((ROOT.parent / "task2/output/exp2/entity_dictionary.json").read_text(encoding="utf-8"))
    entries = data["poi"]
    names = {(area, e["canonical"]) for e in entries for area in e["scenic_areas"]}
    lookup = {(r["scenic_area"], r["variant"]): r["canonical"] for r in data["poi_lookup"]}
    alias_rows = data["aliases"]
    unresolved = [(r["area"], r["alias"]) for r in alias_rows
                  if (r["area"], r["canonical"]) not in names]
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
    return {"alias_rows": len(alias_rows), "route_poi_references_checked": references,
            "unresolved_alias_targets": unresolved, "graph_nodes_without_identity": missing,
            "route_references_missing_from_graph": absent, "passed": not (unresolved or missing or absent)}


def main(out_dir: Path | None = None) -> int:
    """out_dir may point at an artifact copy — fault-injection tests run the real checks against the damaged copy."""
    out_dir = Path(out_dir) if out_dir else OUT
    G = nx.read_graphml(out_dir / "knowledge_graph.graphml")

    known_pairs = [
        ("长廊", "佛香阁", "颐和园"), ("长廊", "石舫", "颐和园"),
        ("迎客松", "光明顶", "黄山"), ("光明顶", "飞来石", "黄山"),
        ("诺日朗", "长海", "九寨沟"), ("长海", "五彩池", "九寨沟"),
    ]
    # Official-route ordering evidence, straight from task3 (route ids where a precedes b)
    official_orders: dict[tuple, set] = defaultdict(set)
    for line in (ROOT.parent / "task3/output/parsed_routes.jsonl").open(encoding="utf-8"):
        route = json.loads(line)
        if not route.get("ordered_route"):
            continue
        seq = route["pois_in_order"]
        for i, a in enumerate(seq):
            for b in seq[i + 1:]:
                official_orders[(route["scenic_area"], a, b)].add(route["route_id"])

    def official_directed_path(scenic: str, a: str, b: str, route_id: str):
        """BFS over edges supported by the same route, returning the path."""
        start, goal = f"POI:{scenic}:{a}", f"POI:{scenic}:{b}"
        if start not in G or goal not in G:
            return []
        q, parents = deque([start]), {start: None}
        while q:
            x = q.popleft()
            if x == goal:
                path = []
                while x is not None:
                    path.append(x.split(":", 2)[-1])
                    x = parents[x]
                return list(reversed(path))
            for _, y, d in G.out_edges(x, data=True):
                routes = d.get("official_routes", "").split("；")
                if d.get("relation") == "先后顺序" and route_id in routes and y not in parents:
                    parents[y] = x
                    q.append(y)
        return []

    fact_checks = []
    for a, b, scenic in known_pairs:
        route_ids = sorted(official_orders.get((scenic, a, b), set()))
        paths = {rid: path for rid in route_ids
                 if (path := official_directed_path(scenic, a, b, rid))}
        fact_checks.append({"pair": f"{scenic}:{a}→{b}",
                            "official_route_ids": route_ids,
                            "official_route_count": len(route_ids),
                            "graph_official_path": bool(paths),
                            "same_route_paths": paths,
                            "found": bool(paths)})

    key_nodes = {}
    for scenic in ("黄山", "九寨沟", "颐和园"):
        sub = G.subgraph([n for n in G if f":{scenic}:" in n])
        poi_sub = sub.subgraph([n for n, d in sub.nodes(data=True) if d.get("kind") in ("景点", "周边景点")])
        degs = sorted(poi_sub.degree(), key=lambda x: (-x[1], x[0]))[:8]
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
    }
    # Three-way consistency — graphml / nodes.csv / edges.csv / stats row counts cross-check each other
    import csv as _csv
    import json as _json
    try:
        with (out_dir / "graph_nodes.csv").open(encoding="utf-8-sig") as _fh:
            _n_nodes = sum(1 for _ in _csv.DictReader(_fh))
        with (out_dir / "graph_edges.csv").open(encoding="utf-8-sig") as _fh:
            _n_edges = sum(1 for _ in _csv.DictReader(_fh))
        _stats = _json.loads((out_dir / "graph_stats.json").read_text(encoding="utf-8"))
        _rt_ok = (_n_nodes == _stats.get("total_nodes") == G.number_of_nodes()
                  and _n_edges == _stats.get("total_edges") == G.number_of_edges())
        validation["roundtrip"] = {"csv_nodes": _n_nodes, "csv_edges": _n_edges,
                                   "graphml_nodes": G.number_of_nodes(),
                                   "graphml_edges": G.number_of_edges(),
                                   "ok": _rt_ok}
    except Exception as _exc:
        validation["roundtrip"] = {"ok": False, "error": str(_exc)}

    # Provenance spot-check: per-item evidence of condition nodes and tourist order edges must be complete and parseable.
    # Condition nodes must be named by their original fragment — the old generic placeholder labels are regression-guarded.
    import json as _json
    _PLACEHOLDER_LABELS = {"一般建议", "一般建议（避雷）", "时间条件（句内）", "入园/通行规定（句内）",
                           "天气条件（句内）", "装备条件（句内）", "入园/通行规定"}
    prov = {"cond_nodes_checked": 0, "cond_nodes_with_evidence": 0, "cond_nodes_placeholder_named": 0,
            "order_edges_checked": 0, "order_edges_with_records": 0, "parse_failures": 0}
    for _, d in G.nodes(data=True):
        if d.get("kind") == "条件":
            prov["cond_nodes_checked"] += 1
            if d.get("name") in _PLACEHOLDER_LABELS:
                prov["cond_nodes_placeholder_named"] += 1
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

    # Evidence and direction metadata must agree with the retained reverse edge.
    direction = {"order_edges": 0, "unopposed_edges": 0, "opposed_edges": 0,
                 "tied_edges": 0, "invalid_edges": 0}
    for u, v, d in G.edges(data=True):
        if d.get("relation") != "先后顺序":
            continue
        direction["order_edges"] += 1
        reverse_data = G.get_edge_data(v, u, default={})
        reverse = (next((x for x in reverse_data.values() if x.get("relation") == "先后顺序"), None)
                   if G.is_multigraph() else reverse_data if reverse_data.get("relation") == "先后顺序" else None)
        if reverse and u != v:
            direction["opposed_edges"] += 1
            if d.get("direction") == "tied":
                direction["tied_edges"] += 1
                if d["weight"] != reverse["weight"] or reverse.get("direction") != "tied":
                    direction["invalid_edges"] += 1
            if float(d.get("reverse_weight", -1)) != float(reverse["weight"]):
                direction["invalid_edges"] += 1
        else:
            direction["unopposed_edges"] += 1
    validation["direction_resolution"] = direction
    validation["direction_ok"] = direction["invalid_edges"] == 0
    (out_dir / "graph_validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=1), encoding="utf-8")
    # Field-by-field spot-check of graphml node attributes against graph_nodes.csv (5 nodes)
    import csv as _csv
    _csv_attrs = {}
    with (out_dir / "graph_nodes.csv").open(encoding="utf-8-sig") as _fh:
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
                      "same_name": same_name_check,
                      "direction": direction,
                      "placeholder_named": prov["cond_nodes_placeholder_named"]}, ensure_ascii=False))
    for f in fact_checks:
        print(" ", f["pair"], "OK" if f["found"] else "MISS",
              f'官方路线={len(f["official_route_ids"])}条 图内官方路径={f["graph_official_path"]}')
    return 0 if (ok == len(fact_checks) and all(n == 1 for n in components.values())
                 and not validation["isolated_nodes"] and alignment["passed"]
                 and validation["direction_ok"] and validation["roundtrip"]["ok"] and validation["provenance_ok"]
                 and prov["cond_nodes_placeholder_named"] == 0
                 and not _attr_mismatch) else 1


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--out-dir", default=None, help="验证目标产物目录（默认正式 output/；故障注入测试指向副本）")
    _args = _ap.parse_args()
    raise SystemExit(main(out_dir=Path(_args.out_dir) if _args.out_dir else None))
