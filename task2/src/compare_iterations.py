"""Compare the two dictionary iterations using their published statistics."""

import json
from pathlib import Path

EXP2 = Path(__file__).resolve().parents[1] / "output/exp2"


def run_iter_compare() -> None:
    base = json.loads((EXP2 / "entity_stats_baseline.json").read_text(encoding="utf-8"))
    ref = json.loads((EXP2 / "entity_stats_refined.json").read_text(encoding="utf-8"))
    spot_file = Path(__file__).resolve().parents[1] / "resources/eval/spot_checks.json"
    spot = json.loads(spot_file.read_text(encoding="utf-8")) if spot_file.exists() else {}

    compare = {
        "rounds": [
            {
                "iteration": "baseline",
                "dictionary": base["dictionary_size"],
                "total_entities": base["total_entities"],
                "by_type": {t: sum(v.get(t, 0) for v in base["by_scenic_area"].values())
                            for t in ("景点POI", "交通方式", "时间节点")},
            },
            {
                "iteration": "refined",
                "dictionary": ref["dictionary_size"],
                "total_entities": ref["total_entities"],
                "by_type": {t: sum(v.get(t, 0) for v in ref["by_scenic_area"].values())
                            for t in ("景点POI", "交通方式", "时间节点")},
            },
        ],
        "spot_check": spot.get("review_summary", {}),
    }
    (EXP2 / "iter_compare.json").write_text(json.dumps(compare, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in compare["rounds"]:
        print(r["iteration"], r["dictionary"], r["total_entities"], r["by_type"])
    if spot:
        print("spot:", spot.get("review_summary", {}))


if __name__ == "__main__":
    run_iter_compare()
