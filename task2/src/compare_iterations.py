"""Compare the two dictionary iterations using their published statistics."""

import json
from pathlib import Path


EXP2 = Path(__file__).resolve().parents[1] / "output/exp2"


def run_iter_compare() -> None:
    base = json.loads((EXP2 / "entity_stats_baseline.json").read_text(encoding="utf-8"))
    ref = json.loads((EXP2 / "entity_stats_refined.json").read_text(encoding="utf-8"))
    spot = json.loads((EXP2 / "spot_checks.json").read_text(encoding="utf-8"))

    compare = {
        "rounds": [
            {
                "iteration": "baseline",
                "dictionary": base["dictionary_size"],
                "total_entities": base["total_entities"],
                "by_type": {t: sum(v.get(t, 0) for v in base["by_scenic_area"].values())
                            for t in ("景点POI", "交通方式", "时间节点")},
                "findings": ["采集阶段种子词典；使用与refined相同的共享时间和交通规则；词典覆盖变化与规则替换分开比较。"],
            },
            {
                "iteration": "refined",
                "dictionary": ref["dictionary_size"],
                "total_entities": ref["total_entities"],
                "by_type": {t: sum(v.get(t, 0) for v in ref["by_scenic_area"].values())
                            for t in ("景点POI", "交通方式", "时间节点")},
                "findings": [
                    f"整合词表：POI {ref['dictionary_size']['poi']} 项、交通 {ref['dictionary_size']['transport']} 项、停用词 {ref['dictionary_size']['stopwords']} 项。",
                    "紧邻语境过滤、复合词守卫、最长区间消解与公共别名映射。",
                    "历史标签仅按文档、类型、原文及位置完全一致时继承；不是新一轮随机抽检。",
                ],
            },
        ],
        "spot_check": spot["review_summary"],
    }
    (EXP2 / "iter_compare.json").write_text(json.dumps(compare, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in compare["rounds"]:
        print(r["iteration"], r["dictionary"], r["total_entities"], r["by_type"])
    print("spot:", spot["review_summary"])


if __name__ == "__main__":
    run_iter_compare()
