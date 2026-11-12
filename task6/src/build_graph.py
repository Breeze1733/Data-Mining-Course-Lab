"""Experiment 6: multi-source procedural knowledge fusion and knowledge graph construction (NetworkX).

Schema:
  Nodes: scenic area / sight POI (with surrounding-sight subtype) / transport operation (sightseeing bus, cableway…)/ time period (上午…晚上)/ condition (node name = the original condition-text fragment; type/label kept as attributes)
  Edges:  包含 (scenic area->POI), 周边关联 (scenic area->surrounding sight), 先后顺序 (POI->POI, weighted from official + tourist sources, all observed directions retained),
        时段归属 (POI->time period), 交通方式 (POI->transport operation), 条件建议 (POI/景区->condition node)

Fusion policy:
  1. Entity alignment: the experiment-2 dictionary canonical is the unique key, with per-scenic-area namespaces (五彩池 isolated by area, 北海 restricted to 黄山);
  2. Source merging: order edges preserve official_routes / tourist_records and both observed directions; each route contributes 1.0 and each record contributes 0.5 per directed edge; recommendation metadata records official priority;
  3. Frequency weighting: period-membership and transport-mode edges accumulate per step occurrence; condition edges accumulate per member frequency on both POI and scenic-area fallback;
  4. Noise filtering: only dictionary POIs are included; condition-advice edges attach only to POIs appearing in the sentence, otherwise attach to the scenic-area node; condition rows without an explicit condition (absent) never become condition nodes.
Output: graph_nodes.csv, graph_edges.csv, knowledge_graph.graphml, graph_stats.json
"""
from __future__ import annotations

import io
import json
import sys
from collections import Counter, defaultdict
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.atomic import atomic_write_text

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
from entity_identity import normalize  # noqa: E402  same normalization as experiment 3

ROOT = Path(__file__).resolve().parents[1]
TASK1 = ROOT.parent / "task1"
TASK2 = ROOT.parent / "task2"
TASK3 = ROOT.parent / "task3"
TASK5 = ROOT.parent / "task5"
OUT = ROOT / "output"

if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

AREAS = ("黄山", "九寨沟", "颐和园")
PERIODS = ("上午", "中午", "下午", "晚上")


# (module level for unit-test reuse): contrast-word guard — equal-length texts differing at exactly one position where the chars are a contrast pair -> semantically exclusive
_CONTRAST = [("多", "少"), ("雨", "雪"), ("早", "晚"), ("上", "下"), ("有", "无"),
             ("大", "小"), ("开", "关"), ("高", "低"), ("冷", "热"), ("快", "慢"), ("贵", "廉")]


def _contrast_blocked(ta: str, tb: str) -> bool:
    if len(ta) != len(tb):
        return False
    diffs = [i for i, (x, y) in enumerate(zip(ta, tb)) if x != y]
    if len(diffs) != 1:
        return False
    i = diffs[0]
    return any({ta[i], tb[i]} == {x, y} for x, y in _CONTRAST)


def dedup_groups_from_quality(quality: dict) -> tuple[list[set], dict[str, int]]:
    """Use task1's precomputed transitive groups, including removed audit records."""
    groups = [set(g["record_ids"]) for g in quality.get("near_duplicate_groups", [])]
    rec2grp: dict[str, int] = {}
    for _gi, _grp in enumerate(groups):
        for _r in _grp:
            rec2grp[_r] = _gi
    return groups, rec2grp


def main() -> int:
    sys.path.insert(0, str(TASK2 / "src"))
    from extract_entities import DictMatcher, load_dictionary

    entries, stopwords, _ = load_dictionary("refined")
    matcher = DictMatcher(entries, stopwords)
    poi_of = {e["name"]: e for e in entries if e["entity_type"] == "景点POI"}
    transport_of = {e["name"]: e for e in entries if e["entity_type"] == "交通方式"}
    # Name resolution: experiment-3 step names pass through normalize (stripping the “景区” suffix) to align with dictionary canonicals
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
    refinement_stats = json.loads((TASK5 / "output/extraction_stats.json").read_text(encoding="utf-8"))["condition_refinement"]
    if len(mapping) != refinement_stats["input_rows"] or sum(bool(m["condition_text"]) for m in mapping) != refinement_stats["nonempty_after"]:
        raise ValueError("task5 mapping and extraction statistics are inconsistent")
    # Mention frequency taken directly from full entity statistics (the top_canonical table is truncated and misses low-frequency POIs)
    mention_counter: Counter = Counter()
    with (TASK2 / "output/exp2/entities_refined.jsonl").open(encoding="utf-8") as _fh:
        for _line in _fh:
            _rec = json.loads(_line)
            for _e in _rec["entities"]:
                if _e["type"] == "景点POI":
                    mention_counter[_e["canonical"]] += 1

    G = nx.MultiDiGraph()

    def node_id(kind: str, scenic: str, name: str) -> str:
        return f"{kind}:{scenic}:{name}"


    for scenic in AREAS:
        G.add_node(node_id("景区", scenic, scenic), kind="景区", name=scenic, label=scenic)
    for e in poi_of.values():
        for scenic in e["scenic_areas"]:
            if scenic == "通用":
                continue
            freq = mention_counter.get(e["canonical"], 0)
            in_scenic = bool(e["scenic_areas"])  # empty list = surrounding landmark (excluded from walking routes)
            G.add_node(node_id("POI", scenic, e["canonical"]), kind=e["subtype"], name=e["canonical"],
                       label=e["canonical"], mention_freq=freq, aliases=e["name"],
                       in_scenic=in_scenic)
            rel = "周边关联" if e["subtype"] == "周边景点" else "包含"
            G.add_edge(node_id("景区", scenic, scenic), node_id("POI", scenic, e["canonical"]),
                       key=rel, relation=rel, weight=1)


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
            if p["route_id"] in official_support[(u, v)]:
                continue
            if G.has_edge(u, v, key="先后顺序"):
                G[u][v]["先后顺序"]["weight"] += 1.0
            else:
                G.add_edge(u, v, key="先后顺序", relation="先后顺序", weight=1.0, source="官方路线")
            official_support[(u, v)].append(p["route_id"])
    # Task1 already removed near-duplicate records; group identity is retained as an additional guard.
    _quality = json.loads((TASK1 / "data/processed/quality_report.json").read_text(encoding="utf-8"))
    _dup_groups, _rec2grp = dedup_groups_from_quality(_quality)

    # No order edges between surrounding landmarks (scenic_areas=[]) and in-area POIs —
    # cross-region edges (宏村→光明顶, 40km) do not imply walkability
    _nearby = {e["canonical"] for e in poi_of.values() if not e["scenic_areas"]}
    tourist_support: dict[tuple, int] = Counter()
    tourist_records: dict[tuple, list] = defaultdict(list)
    tourist_group_seen: dict[tuple, set] = defaultdict(set)
    for t in tourists:
        scenic = t["scenic_area"]
        rid = t.get("record_id")
        # Keep both directions, counting each record/group once per directed edge.
        for a, b in zip(t["poi_sequence"], t["poi_sequence"][1:]):
            u, v = node_id("POI", scenic, resolve(scenic, a)), node_id("POI", scenic, resolve(scenic, b))
            # Skip cross-region pairs (one end a surrounding landmark, the other an in-area POI)
            if (resolve(scenic, a) in _nearby) != (resolve(scenic, b) in _nearby):
                continue
            if not (G.has_node(u) and G.has_node(v)):
                continue
            grp_id = _rec2grp.get(rid, rid)
            if grp_id in tourist_group_seen[(u, v)]:
                continue
            tourist_group_seen[(u, v)].add(grp_id)
            if G.has_edge(u, v, key="先后顺序"):
                G[u][v]["先后顺序"]["weight"] += 0.5
            else:
                G.add_edge(u, v, key="先后顺序", relation="先后顺序", weight=0.5, source="游客序列")
            # Records in the same near-duplicate group contribute at most 1 support per edge
            tourist_support[(u, v)] += 1
            if rid and rid not in tourist_records[(u, v)]:
                tourist_records[(u, v)].append(rid)
    for (u, v), route_ids in official_support.items():
        if G.has_edge(u, v, key="先后顺序"):
            # Source lists are not truncated (official route IDs + per-record tourist evidence)
            G[u][v]["先后顺序"]["official_routes"] = "；".join(dict.fromkeys(route_ids))
    # Tourist evidence is written back uniformly to both official and tourist-only order edges
    for (u, v), recs in tourist_records.items():
        if G.has_edge(u, v, key="先后顺序") and recs:
            G[u][v]["先后顺序"]["tourist_records"] = json.dumps(recs, ensure_ascii=False)
            G[u][v]["先后顺序"]["tourist_support"] = tourist_support.get((u, v), 0)

    # Preserve every observed direction. Recommendation is metadata, never deletion of evidence.
    _opp: dict[frozenset, list] = defaultdict(list)
    for u, v, d in G.edges(data=True):
        if d.get("relation") == "先后顺序":
            _opp[frozenset((u, v))].append((u, v, d))
    _dir_single = _dir_opposed = _dir_tied = 0
    for items in _opp.values():
        if len(items) == 1:
            (u, v, d), = items
            d["direction"] = "single"
            d["recommended"] = True
            d["direction_basis"] = "observed"
            _dir_single += 1
            continue
        (u1, v1, d1), (u2, v2, d2) = items
        off1, off2 = d1.get("official_routes") or "", d2.get("official_routes") or ""
        _dir_opposed += 1
        for d, reverse in ((d1, d2), (d2, d1)):
            d["reverse_weight"] = reverse["weight"]
            d["evidence_share"] = round(d["weight"] / (d["weight"] + reverse["weight"]), 3)
        if off1 and off2:
            for d in (d1, d2):
                d.update(direction="opposed", recommended=True, direction_basis="official")
        elif bool(off1) != bool(off2):
            for d, official in ((d1, off1), (d2, off2)):
                d.update(direction="opposed", recommended=bool(official), direction_basis="official")
        elif d1["weight"] == d2["weight"]:
            for d in (d1, d2):
                d.update(direction="tied", recommended=True, direction_basis="weight")
            _dir_tied += 1
        else:
            for d, reverse in ((d1, d2), (d2, d1)):
                d.update(direction="opposed", recommended=d["weight"] > reverse["weight"], direction_basis="weight")


    period_freq: dict[str, Counter] = defaultdict(Counter)
    transport_freq: dict[str, Counter] = defaultdict(Counter)
    for p in parsed:
        if not p["ordered_route"]:
            continue
        scenic = p["scenic_area"]
        for s in p["steps"]:
            period = s["period"] or "未标注时段"
            for poi in sorted({resolve(scenic, x["normalized"]) for x in s["pois"]}):
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
                for poi in sorted({resolve(scenic, x["normalized"]) for x in s["pois"]}):
                    u = node_id("POI", scenic, poi)
                    transport_freq[scenic][tr] += 1
                    if G.has_edge(u, tn, key="交通方式"):
                        G[u][tn]["交通方式"]["weight"] += 1
                    else:
                        G.add_edge(u, tn, key="交通方式", relation="交通方式", weight=1)

    _stats: dict = {}

    # Exact condition identity after conservative whitespace and outer punctuation normalization.
    def _norm_cond(t: str) -> str:
        return re.sub(r"\s+", "", t).strip("，,。；;、！？!?")

    # Representative-advice selection: the representative member's advice is not necessarily the most actionable (e.g. “避暑旅游” is weaker than “携带保暖衣物”).
    # Action signal > member frequency > length; pick the representative advice for the graph from the whole group.
    _SUGG_ACT = re.compile(
        r"(?:不要|别去|别走|千万|建议|记得|最好|需要|可以尝试|避开|注意|慎|宜|忌|"
        r"带[上着]?|穿|涂|订|预约|乘|坐|尝|早点|提前|步行|前往|游览|下山|上山|错峰|托运)")

    def _best_suggestion(members) -> str:
        cands = [(x.get("frequency", 1), x["suggestion_text"]) for x in members if x.get("suggestion_text")]
        if not cands:
            return ""
        return max(cands, key=lambda fc: (bool(_SUGG_ACT.search(fc[1])), fc[0], len(fc[1])))[1]

    rec_year = {}
    for line in (TASK1 / "data/processed/dataset_clean.jsonl").open(encoding="utf-8"):
        _r = json.loads(line)
        rec_year[_r["record_id"]] = str(_r.get("published_at") or "")

    clusters: list[dict] = []
    by_condition: dict[tuple[str, str], dict] = {}
    _absent = _unusable = 0
    for m in mapping:
        if not m["condition_text"]:
            _absent += 1
            continue  # absent rows state no condition — there is no "如果X则Y" to graph
        key_text = _norm_cond(m["condition_text"])
        if not key_text:
            _unusable += 1
            continue  # punctuation-only fragments carry no condition semantics
        key = (m["scenic_area"], key_text)
        if key not in by_condition:
            cluster = {"scenic_area": m["scenic_area"], "members": [m]}
            by_condition[key] = cluster
            clusters.append(cluster)
        else:
            by_condition[key]["members"].append(m)
    _stats["cond_pairs_input"] = len(mapping)
    _stats["cond_pairs_with_condition"] = len(mapping) - _absent - _unusable
    _stats["cond_pairs_absent_skipped"] = _absent
    _stats["cond_pairs_unusable_skipped"] = _unusable
    _stats["cond_clusters"] = len(clusters)

    for cluster in clusters:
        members = cluster["members"]
        rep = sorted(members, key=lambda x: (-x["frequency"], x["condition_text"]))[0]
        scenic = rep["scenic_area"]
        # Node identity is the conservatively normalized condition text per scenic area. Extraction pattern and
        # condition type/label are metadata attributes: the same condition reached via different patterns is one
        # node carrying every advice variant, which is what downstream condition queries need.
        cn = node_id("条件", scenic, _norm_cond(rep["condition_text"]))
        if not G.has_node(cn):
            # Full evidence lands in the graph — variants/suggestions are not truncated; per-item sources and extraction methods stay traceable
            seen_cond, seen_sugg, seen_src = [], [], []
            evidence = []
            for x in members:
                ct, sg = x["condition_text"], x["suggestion_text"]
                if ct not in seen_cond:
                    seen_cond.append(ct)
                if sg not in seen_sugg:
                    seen_sugg.append(sg)
                for rid in x.get("sources", [x.get("record_id")]):
                    if rid and rid not in seen_src:
                        seen_src.append(rid)
                evidence.append({"row_id": x.get("row_id"), "record_id": x.get("record_id"),
                                 "sources": x.get("sources", []), "pair_ids": x.get("pair_ids", []),
                                 "pattern": x.get("pattern"), "frequency": x.get("frequency", 1),
                                 "condition_type": x.get("condition_type_verified"),
                                 "original_condition": x.get("original_condition_text", ct),
                                 "condition_refinement": x.get("condition_refinement", []),
                                 "semantic_roles": x.get("semantic_roles", {}),
                                 "semantic_role_links": x.get("semantic_role_links", []),
                                 "condition": ct, "suggestion": sg})
            src_years = sorted({m[:4] for rid in seen_src
                                for m in [str(rec_year.get(rid, ""))]
                                if re.match(r"^(?:19|20)\d{2}", m)})
            G.add_node(cn, kind="条件", name=rep["condition_text"][:30],
                       label=rep["condition_text"][:24],
                       cond_type=rep["condition_type_verified"],
                       cond_types=json.dumps(sorted({x["condition_type_verified"] for x in members}), ensure_ascii=False),
                       condition_label=rep.get("condition_label", ""),
                       suggestion=_best_suggestion(members)[:100],
                       frequency=sum(x["frequency"] for x in members),
                       variants=json.dumps(seen_cond, ensure_ascii=False),
                       suggestions=json.dumps(seen_sugg, ensure_ascii=False),
                       sources=json.dumps(seen_src, ensure_ascii=False),
                       source_years=json.dumps(src_years, ensure_ascii=False),
                       evidence=json.dumps(evidence, ensure_ascii=False))
        for m in members:
            text = m["condition_text"] + " " + m["suggestion_text"]
            pois_in_text = [resolve(scenic, e["canonical"]) for e in matcher.find(text)
                            if e["type"] == "景点POI"
                            and scenic in canonical_areas.get(e["canonical"], set())
                            and node_id("POI", scenic, resolve(scenic, e["canonical"])) in G]
            targets = ([node_id("POI", scenic, poi) for poi in dict.fromkeys(pois_in_text)]
                       if pois_in_text else [node_id("景区", scenic, scenic)])
            for u in targets:
                if G.has_edge(u, cn, key="条件建议"):
                    G[u][cn]["条件建议"]["weight"] += m["frequency"]
                    row_ids = json.loads(G[u][cn]["条件建议"]["row_ids"])
                    row_ids.append(m["row_id"])
                    G[u][cn]["条件建议"]["row_ids"] = json.dumps(row_ids)
                else:
                    G.add_edge(u, cn, key="条件建议", relation="条件建议", weight=m["frequency"],
                               row_ids=json.dumps([m["row_id"]]))

    print(json.dumps({"cond_pairs_input": _stats.get("cond_pairs_input"),
                      "cond_pairs_with_condition": _stats.get("cond_pairs_with_condition"),
                      "cond_cluster_nodes": _stats.get("cond_clusters")}, ensure_ascii=False))

    OUT.mkdir(parents=True, exist_ok=True)
    # Collateral cleanup of the non-route-context guard: transport-operation nodes etc. connected only via removed clauses become orphans — remove them
    # (scenic-area root nodes have 包含 edges and are never orphans)
    orphans = [n for n in G.nodes if G.degree(n) == 0 and G.nodes[n].get("kind") != "景区"]
    for n in orphans:
        G.remove_node(n)
    if orphans:
        print(f"移除孤点 {len(orphans)}: {[G.nodes[n].get('label', n) if n in G else n for n in orphans]}")

    import csv
    _buf = io.StringIO()
    w = csv.writer(_buf, lineterminator=chr(13) + chr(10))
    w.writerow(["node_id", "kind", "name", "label"])
    for n, d in G.nodes(data=True):
        w.writerow([n, d.get("kind", ""), d.get("name", ""), d.get("label", "")])
    atomic_write_text(OUT / "graph_nodes.csv", _buf.getvalue(), encoding="utf-8-sig", newline="")

    _buf2 = io.StringIO()
    w2 = csv.writer(_buf2, lineterminator=chr(13) + chr(10))
    w2.writerow(["src", "dst", "relation", "weight"])
    for u, v, d in G.edges(data=True):
        w2.writerow([u, v, d.get("relation", ""), round(d.get("weight", 1), 2)])
    atomic_write_text(OUT / "graph_edges.csv", _buf2.getvalue(), encoding="utf-8-sig", newline="")

    _tmp_gml = OUT / "knowledge_graph.graphml.tmp"
    nx.write_graphml(G, _tmp_gml)
    _tmp_gml.replace(OUT / "knowledge_graph.graphml")

    per_scenic = {}
    for scenic in AREAS:
        sub = G.subgraph([n for n in G.nodes if f":{scenic}:" in n])
        degrees = Counter(dict(sub.degree()))
        isolated = [n for n in sub.nodes if sub.degree(n) == 0]
        per_scenic[scenic] = {
            "nodes": sub.number_of_nodes(), "edges": sub.number_of_edges(),
            "by_kind": dict(Counter(d.get("kind", "?") for _, d in sub.nodes(data=True))),
            "by_relation": dict(Counter(d.get("relation", "?") for _, _, d in sub.edges(data=True))),
            "top_degree": [(sub.nodes[n].get("label", n), deg)
                           for n, deg in sorted(degrees.items(), key=lambda x: (-x[1], x[0]))[:8]],
            "isolated_nodes": len(isolated),
        }
    cond_edges_to_poi = sum(1 for u, v, d in G.edges(data=True)
                            if d.get("relation") == "条件建议" and u.startswith("POI:"))
    cond_edges_to_scenic = sum(1 for u, v, d in G.edges(data=True)
                               if d.get("relation") == "条件建议" and u.startswith("景区:"))
    graph_stats = {
        "total_nodes": G.number_of_nodes(), "total_edges": G.number_of_edges(),
        "by_kind": dict(Counter(d.get("kind", "?") for _, d in G.nodes(data=True))),
        "by_relation": dict(Counter(d.get("relation", "?") for _, _, d in G.edges(data=True))),
        # Condition-edge counts are read back from the graph itself, so stats and graph_edges.csv recompute each other
        "cond_edges_to_poi": cond_edges_to_poi, "cond_edges_to_scenic": cond_edges_to_scenic,
        "cond_pairs_input": _stats["cond_pairs_input"],
        "cond_pairs_with_condition": _stats["cond_pairs_with_condition"],
        "cond_pairs_absent_skipped": _stats["cond_pairs_absent_skipped"],
        "cond_pairs_absent_input": refinement_stats["input_rows"] - refinement_stats["nonempty_before"],
        "cond_pairs_condition_removed": refinement_stats["nonempty_before"] - refinement_stats["nonempty_after"],
        "cond_pairs_unusable_skipped": _stats["cond_pairs_unusable_skipped"],
        "cond_pairs_refined": refinement_stats["changes"].get("changed_rows", 0),
        "cond_cluster_nodes": _stats["cond_clusters"],
        "order_direction": {"unopposed_edges": _dir_single, "opposed_pairs": _dir_opposed,
                            "tied_pairs": _dir_tied},
        "per_scenic": per_scenic,
        "fusion_policy": {
            "entity_alignment": "实验2词典 canonical 为唯一键，景区命名空间隔离（五彩池/北海不跨景区合并）",
            "source_merge": "先后顺序保留全部方向；每条官方路线每方向1.0，每篇游客记录每方向0.5；官方方向优先推荐，纯游客等权标记 tied",
            "condition_semantics": "同景区条件文本经空白与首尾标点规范化后精确合并；无显式条件（absent）的建议不进入条件层",
            "noise_filter": "仅词典内POI；游客序列需两端节点已存在；周边景点单列子类",
        },
    }
    atomic_write_text(OUT / "graph_stats.json", json.dumps(graph_stats, ensure_ascii=False, indent=1))
    print(json.dumps({k: graph_stats[k] for k in ("total_nodes", "total_edges", "by_kind", "by_relation")},
                     ensure_ascii=False, indent=1))
    for a in AREAS:
        print(a, {k: per_scenic[a][k] for k in ("nodes", "edges", "isolated_nodes")},
              "top:", per_scenic[a]["top_degree"][:4])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
