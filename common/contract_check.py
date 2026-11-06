# -*- coding: utf-8 -*-
"""H01：跨任务数据契约校验——各任务边界产物的基础字段一致性。

校验（只读，不修数据）：
- 所有出现 record_id 的产物，其 id 必须存在于 task1 数据集；
- scenic_area ∈ {黄山, 九寨沟, 颐和园}（或官方路线文档同值）；
- 偏移字段 start<end≥0；行程 day≥1；实体 type ∈ 枚举；
- 图谱 CSV 与 jsonl 行数守恒（与 graph_stats 三方校验互补，此处校验字段层）。
任何违例即退出码 1。输出 metrics/contract_check.json。
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SCENICS = {"黄山", "九寨沟", "颐和园"}
ENT_TYPES = {"景点POI", "交通方式", "时间节点"}


def main() -> int:
    violations: list[str] = []
    ds_ids = set()
    with (REPO / "task1/data/processed/dataset_clean.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            ds_ids.add(json.loads(line)["record_id"])

    def check_jsonl(path: Path, record_field: str = "record_id", fields: tuple = ()):
        if not path.exists():
            return 0
        n = 0
        with path.open(encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                r = json.loads(line)
                n += 1
                rid = r.get(record_field)
                if rid is not None and rid not in ds_ids:
                    violations.append(f"{path.name}:{i} record_id 不在数据集: {rid}")
                sa = r.get("scenic_area") or r.get("scenic")
                if sa is not None and sa not in SCENICS:
                    violations.append(f"{path.name}:{i} scenic 非法: {sa}")
                for f in fields:
                    if f not in r or r[f] in (None, ""):
                        violations.append(f"{path.name}:{i} 缺字段 {f}")
        return n

    # task2 实体
    n = check_jsonl(REPO / "task2/output/exp2/entities_refined.jsonl", fields=("entities",))
    with (REPO / "task2/output/exp2/entities_refined.jsonl").open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            r = json.loads(line)
            for e in r["entities"]:
                if e["type"] not in ENT_TYPES:
                    violations.append(f"entities_refined:{i} 非法实体类型 {e['type']}")
                if not (0 <= e["start"] < e["end"] <= len(r["clean_content"]) if "clean_content" in e else 0 <= e["start"] < e["end"]):
                    violations.append(f"entities_refined:{i} 偏移异常 {e.get('text')}")

    # task3 路线 / 游客动线
    check_jsonl(REPO / "task3/output/parsed_routes.jsonl", fields=("steps",))
    check_jsonl(REPO / "task3/output/tourist_routes.jsonl", fields=("poi_sequence",))

    # task4 案例 / task5 条件对
    check_jsonl(REPO / "task4/output/pronoun_cases.jsonl", fields=("pronoun", "sentence"))
    check_jsonl(REPO / "task5/output/conditional_pairs.jsonl",
                fields=("condition_text", "suggestion_text"))

    # task7 行程 trace：day≥1、period 枚举
    traces = REPO / "task7/output/traces"
    n_tr = 0
    for f in sorted(traces.glob("trace_*.json")):
        t = json.loads(f.read_text(encoding="utf-8"))
        plan = t.get("plan")
        if not plan:
            continue
        n_tr += 1
        for it in plan.get("itinerary", []):
            if not (isinstance(it.get("day"), int) and it["day"] >= 1):
                violations.append(f"{f.name} day 非法: {it.get('day')}")
            if it.get("period") not in ("上午", "中午", "下午", "晚上", "未标注时段"):
                violations.append(f"{f.name} period 非法: {it.get('period')}")

    # task6 CSV 字段层：node_id 非空、kind 枚举、行数与 stats 一致
    gstats = json.loads((REPO / "task6/output/graph_stats.json").read_text(encoding="utf-8"))
    kinds = {"景区", "景点", "周边景点", "时段", "交通操作", "条件"}
    n_nodes = 0
    with (REPO / "task6/output/graph_nodes.csv").open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            n_nodes += 1
            if row.get("kind") not in kinds:
                violations.append(f"graph_nodes.csv kind 非法: {row.get('kind')}")
            if not row.get("node_id"):
                violations.append("graph_nodes.csv 空 node_id")
    if n_nodes != gstats.get("total_nodes"):
        violations.append(f"graph_nodes 行数 {n_nodes} != stats {gstats.get('total_nodes')}")

    report = {
        "title": "H01 跨任务数据契约校验",
        "checked": ["entities_refined", "parsed_routes", "tourist_routes", "pronoun_cases",
                    "conditional_pairs", "task7 itineraries", "graph_nodes"],
        "n_violations": len(violations),
        "violations": violations[:50],
    }
    out = REPO / "metrics/contract_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n_violations": len(violations),
                      "sample": violations[:5]}, ensure_ascii=False))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
