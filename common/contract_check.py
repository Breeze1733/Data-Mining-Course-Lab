# -*- coding: utf-8 -*-
"""跨任务数据契约校验——各任务边界产物的基础字段一致性 + 人工标注评测集防篡改指纹。

校验（只读，不修数据）：
- 所有出现 record_id 的产物，其 id 必须存在于 task1 数据集；
- scenic_area ∈ {黄山, 九寨沟, 颐和园}（或官方路线文档同值）；
- 偏移字段 start<end≥0；行程 day≥1；实体 type ∈ 枚举；
- 图谱 CSV 与 jsonl 行数守恒（与 graph_stats 三方校验互补，此处校验字段层）；
- 人工标注评测集（task2 抽检 / task4 标注 / task5 复核）SHA256 指纹与上次认可状态一致，
  task2/task5 汇总数与样本重算自洽，数据集行数不漂移。
任何违例即退出码 1。输出 metrics/contract_check.json。

指纹基准存 metrics/regression_state.json；确需变更 gold 文件时先说明，再运行
    python common/contract_check.py --update-state
固化新基准。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SCENICS = {"黄山", "九寨沟", "颐和园"}
ENT_TYPES = {"景点POI", "交通方式", "时间节点"}
STATE_PATH = REPO / "metrics" / "regression_state.json"
# 人工标注评测集：判定只允许追加复核，不允许为好看而改判——指纹变化必须显式备案
GOLD_FILES = {
    "task2_spot_checks": REPO / "task2/output/exp2/spot_checks.json",
    "task4_annotation_gold": REPO / "task4/output/annotation_gold.json",
    "task5_review_dev": REPO / "task5/output/review_dev.json",
}


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[warn] 读取失败 {path}: {e}", file=sys.stderr)
        return None


def collect_guards() -> dict:
    """收集防篡改守护指标：数据集行数、gold 指纹、task2/task5 汇总与样本重算自洽。"""
    g: dict = {}
    ds = REPO / "task1/data/processed/dataset_clean.jsonl"
    g["dataset.count"] = sum(1 for ln in ds.open(encoding="utf-8") if ln.strip()) if ds.exists() else None

    # task2 抽检汇总 vs 样本重算
    sp = load_json(GOLD_FILES["task2_spot_checks"])
    if sp:
        present = [s for s in sp.get("samples", []) if s.get("present_in_current_output")]
        verdicts: dict = {}
        for s in present:
            verdicts[s.get("verdict")] = verdicts.get(s.get("verdict"), 0) + 1
        rs = sp.get("review_summary", {})
        g["task2.spot_n"] = rs.get("n")
        g["task2.spot_self_consistent"] = (
            rs.get("n") == len(present) and rs.get("correct") == verdicts.get("correct")
        )
    else:
        g["task2.spot_self_consistent"] = False

    # task5 复核汇总 vs 人工标注评测集重算
    rg = load_json(GOLD_FILES["task5_review_dev"])
    rs5 = load_json(REPO / "task5/output/review_summary.json")
    if rg and rs5:
        counts: dict = {}
        for r in rg.get("reviews", []):
            counts[r.get("verdict")] = counts.get(r.get("verdict"), 0) + 1
        v = rs5.get("verdicts", {})
        g["task5.review_n"] = rs5.get("n")
        g["task5.verdicts"] = f"{counts.get('correct', 0)}/{counts.get('boundary', 0)}/{counts.get('wrong', 0)}"
        g["task5.review_self_consistent"] = (
            rs5.get("n") == rg.get("n")
            and v.get("correct") == counts.get("correct")
            and v.get("boundary") == counts.get("boundary")
            and v.get("wrong") == counts.get("wrong")
        )
    else:
        g["task5.review_self_consistent"] = False

    g["gold.sha256"] = {k: sha256(p) for k, p in GOLD_FILES.items()}
    return g


def check_guards(violations: list[str]) -> dict:
    """指纹/计数与上次认可基准比对；自洽性检查与基准无关，始终执行。
    返回本次实测指标（含 gold.sha256）。"""
    now = collect_guards()
    state = load_json(STATE_PATH)
    if state:
        last = state.get("guards", {})
        if last.get("dataset.count") not in (None, now.get("dataset.count")):
            violations.append(f"dataset.count {now.get('dataset.count')} != 认可基准 {last.get('dataset.count')}")
        changed = [k for k, v in now["gold.sha256"].items() if v != state.get("gold.sha256", {}).get(k)]
        for k in changed:
            violations.append(f"gold 指纹变化（人工标注评测集不得改判；确认合理后 --update-state）: {k}")
    for name in ("task2.spot_self_consistent", "task5.review_self_consistent"):
        if now.get(name) is False:
            violations.append(f"{name} 为 False：汇总与样本重算不一致")
    return now


def write_state(g: dict) -> None:
    payload = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "guards": {k: v for k, v in g.items() if k != "gold.sha256"},
        "gold.sha256": g["gold.sha256"],
        "notes": "人工标注判定只允许追加复核；指纹变化必须在变更说明后固化新基准。",
    }
    STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[state] 已更新基准 -> {STATE_PATH.relative_to(REPO)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="跨任务数据契约校验")
    ap.add_argument("--update-state", action="store_true",
                    help="把当前指纹/计数固化为新基准（须先人工确认变更合理）")
    args = ap.parse_args()
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

    # E14：条数守恒——条件对 JSONL 与映射表行数一致（导出截断仅用于显示，不丢事实行）
    def jsonl_count(path: Path) -> int:
        return sum(1 for _ in path.open(encoding="utf-8")) if path.exists() else -1

    pairs_n = jsonl_count(REPO / "task5/output/conditional_pairs.jsonl")
    mapping = json.loads((REPO / "task5/output/mapping_table.json").read_text(encoding="utf-8"))
    mapping_n = len(mapping["rows"] if isinstance(mapping, dict) else mapping)
    stats5 = json.loads((REPO / "task5/output/extraction_stats.json").read_text(encoding="utf-8"))
    # 不变量：JSONL=去重前原始对；映射表=去重+归属过滤后的发布对
    if pairs_n != stats5.get("raw_pairs"):
        violations.append(f"条件对 JSONL({pairs_n}) != 抽取统计 raw_pairs({stats5.get('raw_pairs')})")
    if mapping_n != stats5.get("after_dedup"):
        violations.append(f"映射表({mapping_n}) != 抽取统计 after_dedup({stats5.get('after_dedup')})")

    # A10：缺失字段统计（非违例，供数据质量画像）
    field_nulls = {}
    for line in (REPO / "task1/data/processed/dataset_clean.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        for f in ("source_url", "collected_at", "published_at", "author", "content_sha256"):
            if not r.get(f):
                field_nulls[f] = field_nulls.get(f, 0) + 1
    # 人工标注评测集防篡改守护（原 regression_check 并入；重打分由全链 rebuild 覆盖）
    now = check_guards(violations)
    if args.update_state:
        write_state(now)
        # 固化后守护类违例清零；契约类违例（record_id/字段/枚举）仍如实保留
        violations = [v for v in violations if not v.startswith(("dataset.count", "gold "))]
        guards = {k: v for k, v in now.items() if k != "gold.sha256"} | {"gold.fingerprints_match": True}
    else:
        state = load_json(STATE_PATH)
        guards = {k: v for k, v in now.items() if k != "gold.sha256"} | {"gold.fingerprints_match":
            not state or all(v == state.get("gold.sha256", {}).get(k) for k, v in now["gold.sha256"].items())}
    # D01：分句规则差异备案——task4 含分号/半角感叹，task5 不含；跨任务匹配用包含式容忍
    report = {
        "title": "跨任务数据契约校验",
        "sentence_split_difference": {
            "task4": "按 。！？；!?与换行分句（含分号与半角）",
            "task5": "按 。！？与换行分句（分号并入句内）",
            "mitigation": "实验4↔5 交叉匹配采用 record+包含式比对（对齐口径），分句差异不产生错位打分",
        },
        "missing_field_counts": field_nulls,
        "checked": ["entities_refined", "parsed_routes", "tourist_routes", "pronoun_cases",
                    "conditional_pairs", "mapping_table", "task7 itineraries", "graph_nodes"],
        "guards": guards,
        "n_violations": len(violations),
        "violations": violations[:50],
    }
    out = REPO / "metrics/contract_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n_violations": len(violations),
                      "gold.fingerprints_match": guards["gold.fingerprints_match"],
                      "sample": violations[:5]}, ensure_ascii=False))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
