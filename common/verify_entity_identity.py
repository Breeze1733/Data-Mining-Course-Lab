"""Audit alias targets and route-to-graph name alignment after rebuilding."""
import json
from pathlib import Path
from entity_identity import aliases, canonical_name, normalize, build_poi_lookup

ROOT = Path(__file__).resolve().parents[1]


def main():
    dictionary = json.loads((ROOT / "task2/output/exp2/entity_dictionary.json").read_text(encoding="utf-8"))["poi"]
    names = {(area, e["canonical"]) for e in dictionary for area in e["scenic_areas"]}
    lookup = build_poi_lookup(dictionary)
    unresolved_aliases = [(area, alias, canonical_name(alias, area)) for area, alias in aliases()
                          if (area, canonical_name(alias, area)) not in names]
    import networkx as nx
    graph = nx.read_graphml(ROOT / "task6/output/knowledge_graph.graphml")
    missing_identity = [node for node, data in graph.nodes(data=True) if not data.get("kind") or not data.get("name")]
    missing_route_nodes = []
    checked = 0
    for line in (ROOT / "task3/output/parsed_routes.jsonl").open(encoding="utf-8"):
        route = json.loads(line)
        for step in route["steps"]:
            for poi in step["pois"]:
                name = lookup.get((route["scenic_area"], poi["normalized"]), poi["normalized"])
                checked += 1
                if f"POI:{route['scenic_area']}:{name}" not in graph:
                    missing_route_nodes.append([route["route_id"], name])
    result = {"alias_rows": len(aliases()), "route_poi_references_checked": checked,
              "unresolved_alias_targets": unresolved_aliases, "graph_nodes_without_identity": missing_identity,
              "route_references_missing_from_graph": missing_route_nodes}
    result["passed"] = not (unresolved_aliases or missing_identity or missing_route_nodes)
    path = ROOT / "review/merge_20261029/naming_validation.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
