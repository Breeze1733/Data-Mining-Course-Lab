"""Experiment 6: multi-source procedural knowledge fusion and knowledge graph construction (NetworkX).

Schema:
  Nodes: scenic area / sight POI (with surrounding-sight subtype) / transport operation (sightseeing bus, cableway…)/ time period (上午…晚上)/ condition (人群/天气/时间/装备…)
  Edges:  包含 (scenic area->POI), 周边关联 (scenic area->surrounding sight), 先后顺序 (POI->POI, weighted from official + tourist sources),
        时段归属 (POI->time period), 交通方式 (POI->transport operation), 条件建议 (POI->condition node)

Fusion policy:
  1. Entity alignment: the experiment-2 dictionary canonical is the unique key, with per-scenic-area namespaces (五彩池 isolated by area, 北海 restricted to 黄山);
  2. Source merging: order edges record the official_routes / tourist_records source groups with separate weights (official 1.0 per route, tourist 0.5 per record);
  3. Frequency weighting: period-membership and transport-mode edges accumulate per step occurrence;
  4. Noise filtering: only dictionary POIs are included; condition-advice edges attach only to POIs appearing in the sentence, otherwise attach to the scenic-area node and are flagged.
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


def _norm_cond_m(t: str) -> str:
    return re.sub(r"[\s，,。；;、！？!?\[\]()【】的了吗呢啊呀]", "", t)


def _contrast_blocked(ta: str, tb: str) -> bool:
    if len(ta) != len(tb):
        return False
    diffs = [i for i, (x, y) in enumerate(zip(ta, tb)) if x != y]
    if len(diffs) != 1:
        return False
    i = diffs[0]
    return any({ta[i], tb[i]} == {x, y} for x, y in _CONTRAST)


def dedup_groups_from_quality(quality: dict) -> tuple[list[set], dict[str, int]]:
    """F05: near-duplicate pairs -> transitive-closure grouping and record->group-id mapping (key names match the preprocess output)."""
    groups: list[set] = []
    for _d in quality.get("near_duplicate_pairs", []):
        _a, _b = _d["record_id_a"], _d["record_id_b"]
        for _grp in groups:
            if _a in _grp or _b in _grp:
                _grp.add(_b)
                _grp.add(_a)
                break
        else:
            groups.append({_a, _b})
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
            if G.has_edge(u, v, key="先后顺序"):
                G[u][v]["先后顺序"]["weight"] += 1.0
            else:
                G.add_edge(u, v, key="先后顺序", relation="先后顺序", weight=1.0, source="官方路线")
            official_support[(u, v)].append(p["route_id"])
    # Near-duplicate travelogue dedup — records in the same group contribute at most 1 support per edge
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
        # Graph edges use the full poi_sequence (preserving backtracking and repeated visits); accumulated weights carry visit intensity
        for a, b in zip(t["poi_sequence"], t["poi_sequence"][1:]):
            u, v = node_id("POI", scenic, resolve(scenic, a)), node_id("POI", scenic, resolve(scenic, b))
            # Skip cross-region pairs (one end a surrounding landmark, the other an in-area POI)
            if (resolve(scenic, a) in _nearby) != (resolve(scenic, b) in _nearby):
                continue
            if not (G.has_node(u) and G.has_node(v)):
                continue
            if G.has_edge(u, v, key="先后顺序"):
                G[u][v]["先后顺序"]["weight"] += 0.5
            else:
                G.add_edge(u, v, key="先后顺序", relation="先后顺序", weight=0.5, source="游客序列")
            # Records in the same near-duplicate group contribute at most 1 support per edge
            grp_id = _rec2grp.get(rid, rid)
            if grp_id in tourist_group_seen[(u, v)]:
                continue
            tourist_group_seen[(u, v)].add(grp_id)
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

    _stats: dict = {}

    # Cluster normalization: conditions with the same scenic area + same type + normalized-text char-bigram Jaccard>=0.4 merge into one node,
    # keeping the representative text (highest frequency), all variants, and the summed frequency; edges attach per member with accumulated weights.
    def _norm_cond(t: str) -> str:
        return re.sub(r"[\s，,。；;、！？!?\[\]()【】的了吗呢啊呀]", "", t)

    def _bigrams(t: str) -> set:
        return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t}

    def _polarity(m) -> str:
        t = _norm_cond(m["condition_text"])[:4]
        return "NEG" if re.search(r"^(不要|不去|别|切勿|避免|慎|忌|没带|没有带|没有|不宜|不建议)", t) else "POS"

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
    # Contrast-word guard: see module-level _contrast_blocked (0 pairs affected in the real graph; hardening against a latent risk)
    reps: list[tuple[str, str, str, str, set]] = []
    for m in mapping:
        key_text = _norm_cond(m["condition_text"])
        bg = _bigrams(key_text)
        hit = None
        for scenic0, ctype0, pat0, pol0, bg0, cluster0 in reps:
            # Different polarity is never merged (P4 advice/P6 pitfall-avoidance, plus negation prefixes in the condition text itself)
            if (scenic0 == m["scenic_area"] and ctype0 == m["condition_type"]
                    and pat0 == m["pattern"] and pol0 == _polarity(m)):
                inter, union = len(bg0 & bg), len(bg0 | bg)
                if union and inter / union >= 0.4:
                    if _contrast_blocked(_norm_cond(m["condition_text"]),
                                         _norm_cond(cluster0["members"][0]["condition_text"])):
                        continue
                    hit = cluster0
                    break
        if hit is not None:
            hit["members"].append(m)
        else:
            cluster = {"scenic_area": m["scenic_area"], "condition_type": m["condition_type"],
                       "members": [m]}
            reps.append((m["scenic_area"], m["condition_type"], m["pattern"], _polarity(m), bg, cluster))
            clusters.append(cluster)
    _stats["cond_raw"] = len(mapping)
    _stats["cond_clusters"] = len(clusters)

    cond_edges = 0
    cond_to_scenic = 0
    for cluster in clusters:
        members = cluster["members"]
        rep = sorted(members, key=lambda x: (-x["frequency"], x["condition_text"]))[0]
        scenic = rep["scenic_area"]
        # Include the extraction pattern in the ID — P4 advice and P6 pitfall-avoidance with inferred labels (“时间条件（句内）”) are
        # different semantic nodes; clustering already separates them by pattern, so node identity must carry it too or they collide
        cn = node_id("条件", scenic,
                     f'{rep["pattern"]}:{rep["condition_type"]}:{_norm_cond(rep["condition_text"])}')
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
                if x.get("record_id") and x["record_id"] not in seen_src:
                    seen_src.append(x["record_id"])
                evidence.append({"row_id": x.get("row_id"), "record_id": x.get("record_id"),
                                 "pattern": x.get("pattern"), "frequency": x.get("frequency", 1),
                                 "condition": ct[:60], "suggestion": sg[:60]})
            src_years = sorted({m[:4] for rid in seen_src
                                for m in [str(rec_year.get(rid, ""))]
                                if re.match(r"^(?:19|20)\d{2}", m)})
            G.add_node(cn, kind="条件", name=rep["condition_text"][:30],
                       label=f'[{rep["condition_type"]}|{rep["pattern"].split("_")[0]}] {rep["condition_text"][:24]}',
                       cond_type=rep["condition_type"], suggestion=_best_suggestion(members)[:100],
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

    print(json.dumps({"cond_raw_pairs": _stats.get("cond_raw"), "cond_cluster_nodes": _stats.get("cond_clusters")}, ensure_ascii=False))

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
    w.writerow(["node_id", "kind", "name", "label", "mention_freq", "cond_type", "suggestion", "frequency",
                "variants", "suggestions", "sources", "evidence"])
    for n, d in G.nodes(data=True):
        w.writerow([n, d.get("kind", ""), d.get("name", ""), d.get("label", ""),
                    d.get("mention_freq", ""), d.get("cond_type", ""), d.get("suggestion", ""),
                    d.get("frequency", ""), d.get("variants", ""), d.get("suggestions", ""),
                    d.get("sources", ""), d.get("evidence", "")])
    atomic_write_text(OUT / "graph_nodes.csv", _buf.getvalue(), encoding="utf-8-sig", newline="")

    _buf2 = io.StringIO()
    w2 = csv.writer(_buf2, lineterminator=chr(13) + chr(10))
    w2.writerow(["src", "dst", "relation", "weight", "source", "official_routes", "tourist_support", "tourist_records"])
    for u, v, d in G.edges(data=True):
        w2.writerow([u, v, d.get("relation", ""), round(d.get("weight", 1), 2),
                     d.get("source", ""), d.get("official_routes", ""), d.get("tourist_support", ""),
                     d.get("tourist_records", "")])
    atomic_write_text(OUT / "graph_edges.csv", _buf2.getvalue(), encoding="utf-8-sig", newline="")

    _tmp_gml = OUT / "knowledge_graph.graphml.tmp"
    nx.write_graphml(G, _tmp_gml)
    _tmp_gml.replace(OUT / "knowledge_graph.graphml")

    from fingerprints import data_fingerprints as _fp
    _graph_fingerprints = _fp

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
        # Version binding between the graph and its inputs (dictionary/corpus fingerprints, preventing an old graph paired with a new dictionary)
        "input_fingerprints": _graph_fingerprints(),
        "fusion_policy": {
            "entity_alignment": "实验2词典 canonical 为唯一键，景区命名空间隔离（五彩池/北海不跨景区合并）",
            "source_merge": "先后边=官方1.0/条+游客0.5/条；条件边挂句中POI，无POI挂景区并计数",
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
