"""实验2：两轮迭代对比（baseline 种子词典 vs refined 语料挖掘整理词典）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/exp2"
sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    base = json.loads((OUT / "entity_stats_baseline.json").read_text(encoding="utf-8"))
    ref = json.loads((OUT / "entity_stats_refined.json").read_text(encoding="utf-8"))
    spot = json.loads((OUT / "spot_checks.json").read_text(encoding="utf-8"))

    compare = {
        "rounds": [
            {
                "iteration": "baseline",
                "dictionary": base["dictionary_size"],
                "total_entities": base["total_entities"],
                "by_type": {t: sum(v.get(t, 0) for v in base["by_scenic_area"].values())
                            for t in ("景点POI", "交通方式", "时间节点")},
                "findings": [
                    "九寨沟高频POI大面积漏识别：诺日朗(358次)、犀牛海、芦苇海、双龙海、中查沟等不在种子词典",
                    "无停用词：其他景区名（庐山/泰山）与北京同城公园（北海公园）混入",
                    "无子类：索道站名与普通车辆混在一起，周边景点（黄龙/宏村）与景区内POI混算",
                ],
            },
            {
                "iteration": "refined",
                "dictionary": ref["dictionary_size"],
                "total_entities": ref["total_entities"],
                "by_type": {t: sum(v.get(t, 0) for v in ref["by_scenic_area"].values())
                            for t in ("景点POI", "交通方式", "时间节点")},
                "findings": [
                    "POI 词典 72→117（挖掘+人工复核），交通词表补充 37 条并分 8 个子类",
                    "领域停用词 28 条；停用词守卫拒绝“北海公园”整词",
                    "复合词守卫三轮修复：步行街/火车站→登山杖/登山鞋→地铁站/地铁口（共拦截约90处设施名误报）",
                    "时间正则修复：Day\\d+ 完整匹配；时钟范围（7:00-8:10）合并为一条时刻实体；移除口语“半天”",
                    f"人工抽检 54 例（分层随机 seed=42）：{spot['review_summary']['correct']} 正确 / "
                    f"{spot['review_summary']['ambiguous']} 歧义 / {spot['review_summary']['incorrect']} 错误",
                ],
            },
        ],
        "spot_check": spot["review_summary"],
    }
    (OUT / "iter_compare.json").write_text(json.dumps(compare, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in compare["rounds"]:
        print(r["iteration"], r["dictionary"], r["total_entities"], r["by_type"])
    print("spot:", spot["review_summary"])


if __name__ == "__main__":
    main()
