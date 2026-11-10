# -*- coding: utf-8 -*-
"""Cross-task data contract checks -- basic field consistency of each task's boundary
artifacts + anti-tampering fingerprints for the human-annotated eval set.

Checks (read-only, never repairs data):
- every artifact that carries record_id must reference ids present in the task1 dataset;
- scenic_area ∈ {黄山, 九寨沟, 颐和园} (or the same values as the official route documents);
- offset fields start<end≥0; itinerary day≥1; entity type within the enum;
- graph CSV and jsonl row counts are conserved (complementary to the graph_stats
  three-way check; this checks the field layer);
- the human-annotated eval set (task2 spot check / task4 annotation / task5 review)
  SHA256 fingerprints match the last accepted state; task2/task5 summaries are
  self-consistent with recomputation from samples; the dataset row count does not drift.
Any violation exits with code 1. Writes metrics/contract_check.json.

Fingerprint baselines live in metrics/regression_state.json; when a gold file genuinely
must change, state the reason first, then run
    python common/contract_check.py --update-state
to freeze the new baseline.
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
# human-annotated eval set: verdicts may only be extended by additional review, never re-judged for cosmetics -- fingerprint changes must be explicitly documented
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
    """Collect anti-tampering guard metrics: dataset row count, gold fingerprints,
    task2/task5 summary-vs-sample self-consistency."""
    g: dict = {}
    ds = REPO / "task1/data/processed/dataset_clean.jsonl"
    g["dataset.count"] = sum(1 for ln in ds.open(encoding="utf-8") if ln.strip()) if ds.exists() else None

    # task2 spot-check summary vs recomputation from samples
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

    # task5 review summary vs recomputation from the human-annotated eval set
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
    """Compare fingerprints/counts against the last accepted baseline; self-consistency
    checks are baseline-independent and always run.
    Returns the metrics measured this run (including gold.sha256)."""
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

    # task2 entities
    n = check_jsonl(REPO / "task2/output/exp2/entities_refined.jsonl", fields=("entities",))
    with (REPO / "task2/output/exp2/entities_refined.jsonl").open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            r = json.loads(line)
            for e in r["entities"]:
                if e["type"] not in ENT_TYPES:
                    violations.append(f"entities_refined:{i} 非法实体类型 {e['type']}")
                if not (0 <= e["start"] < e["end"] <= len(r["clean_content"]) if "clean_content" in e else 0 <= e["start"] < e["end"]):
                    violations.append(f"entities_refined:{i} 偏移异常 {e.get('text')}")

    # task3 routes / visitor routes
    check_jsonl(REPO / "task3/output/parsed_routes.jsonl", fields=("steps",))
    check_jsonl(REPO / "task3/output/tourist_routes.jsonl", fields=("poi_sequence",))

    # task4 cases / task5 conditional pairs
    check_jsonl(REPO / "task4/output/pronoun_cases.jsonl", fields=("pronoun", "sentence"))
    check_jsonl(REPO / "task5/output/conditional_pairs.jsonl",
                fields=("condition_text", "suggestion_text"))

    # task7 itinerary traces: day≥1, period enum
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

    # task6 CSV field layer: node_id non-empty, kind enum, row count matches stats
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

    # Count conservation -- the conditional-pairs JSONL row count matches the mapping table (export truncation is display-only, no fact rows lost)
    def jsonl_count(path: Path) -> int:
        return sum(1 for _ in path.open(encoding="utf-8")) if path.exists() else -1

    pairs_n = jsonl_count(REPO / "task5/output/conditional_pairs.jsonl")
    mapping = json.loads((REPO / "task5/output/mapping_table.json").read_text(encoding="utf-8"))
    mapping_n = len(mapping["rows"] if isinstance(mapping, dict) else mapping)
    stats5 = json.loads((REPO / "task5/output/extraction_stats.json").read_text(encoding="utf-8"))
    # invariant: JSONL=raw pairs before dedup; mapping table=published pairs after dedup + attribution filtering
    if pairs_n != stats5.get("raw_pairs"):
        violations.append(f"条件对 JSONL({pairs_n}) != 抽取统计 raw_pairs({stats5.get('raw_pairs')})")
    if mapping_n != stats5.get("after_dedup"):
        violations.append(f"映射表({mapping_n}) != 抽取统计 after_dedup({stats5.get('after_dedup')})")

    # A10: missing-field statistics (not violations; used for the data-quality profile)
    field_nulls = {}
    for line in (REPO / "task1/data/processed/dataset_clean.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        for f in ("source_url", "collected_at", "published_at", "author", "content_sha256"):
            if not r.get(f):
                field_nulls[f] = field_nulls.get(f, 0) + 1
    # human-annotated eval set anti-tampering guard (the former regression_check merged in; re-scoring is covered by the full-chain rebuild)
    now = check_guards(violations)
    if args.update_state:
        write_state(now)
        # after freezing, guard-type violations are cleared; contract violations (record_id/fields/enums) are still reported honestly
        violations = [v for v in violations if not v.startswith(("dataset.count", "gold "))]
        guards = {k: v for k, v in now.items() if k != "gold.sha256"} | {"gold.fingerprints_match": True}
    else:
        state = load_json(STATE_PATH)
        guards = {k: v for k, v in now.items() if k != "gold.sha256"} | {"gold.fingerprints_match":
            not state or all(v == state.get("gold.sha256", {}).get(k) for k, v in now["gold.sha256"].items())}
    # D01: documented sentence-split rule difference -- task4 includes semicolons/half-width exclamation, task5 does not; cross-task matching tolerates it via containment
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
