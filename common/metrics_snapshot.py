# -*- coding: utf-8 -*-
"""指标快照工具：读取各任务 output 的关键指标文件，生成 JSON+Markdown 摘要。

用法（在仓库任意目录）：
    python common/metrics_snapshot.py --label "基线"        # 快照并追加到 METRICS.md
    python common/metrics_snapshot.py --print-only          # 只打印，不落盘

每运行一次，向根目录 METRICS.md 的账本表追加一行（一行一个时点），
并把完整指标 JSON 存到 metrics/snapshots/<时间戳>.json 与 snapshot_latest.json。
后续优化一律以 METRICS.md 中的记录为对照基线。
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# JSON 中的中文景区名 -> 稳定英文键
SCENIC_KEYS = {"九寨沟": "jiuzhaigou", "颐和园": "yiheyuan", "黄山": "huangshan"}

ENTITY_TYPE_PREFIXES = {"poi": "景点POI", "transport": "交通方式", "time": "时间节点"}


def _load(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as e:
        print(f"[warn] 读取失败 {path}: {e}", file=sys.stderr)
        return None


def _count_lines(path: Path) -> int | None:
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return None


def _git_short_hash() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except OSError:
        pass
    return "unknown"


def _dirty_files() -> int:
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT,
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return len([ln for ln in out.stdout.splitlines() if ln.strip()])
    except OSError:
        pass
    return -1


def collect_metrics() -> dict:
    """汇总全部关键指标为扁平 dict；缺文件时对应键记 None。"""
    m: dict = {}

    # task1 主数据集规模（守护指标：271）
    m["dataset.count"] = _count_lines(ROOT / "task1/data/processed/dataset_clean.jsonl")

    # task2 实体统计
    st = _load(ROOT / "task2/output/exp2/entity_stats_refined.json")
    if st:
        m["entities.total"] = st.get("total_entities")
        by_subtype = st.get("by_subtype", {})
        for key, prefix in ENTITY_TYPE_PREFIXES.items():
            m[f"entities.{key}"] = sum(
                v for k, v in by_subtype.items() if k.startswith(prefix)
            )
        m["entities.dict_poi"] = st.get("dictionary_size", {}).get("poi")
        m["entities.dict_transport"] = st.get("dictionary_size", {}).get("transport")
    else:
        for key in ("total", "poi", "transport", "time", "dict_poi", "dict_transport"):
            m[f"entities.{key}"] = None

    # task2 实体抽检
    sp = _load(ROOT / "task2/output/exp2/spot_checks.json")
    if sp:
        rs = sp.get("review_summary", {})
        m["entity_spot.n"] = rs.get("n")
        m["entity_spot.correct"] = rs.get("correct")
        m["entity_spot.ambiguous"] = rs.get("ambiguous")
        m["entity_spot.incorrect"] = rs.get("incorrect")
    else:
        m["entity_spot.n"] = m["entity_spot.correct"] = None

    # task3 路线覆盖度与顺序一致性
    ov = _load(ROOT / "task3/output/official_vs_tourist.json")
    if ov:
        total_official = total_tourist = 0
        for scenic, data in ov.get("by_scenic_area", {}).items():
            key = SCENIC_KEYS.get(scenic, scenic)
            m[f"coverage.{key}"] = data.get("coverage_mean")
            m[f"tau.{key}"] = data.get("order_tau_mean")
            total_official += data.get("n_official_routes", 0) or 0
            total_tourist += data.get("n_tourist_routes", 0) or 0
        m["routes.official_total"] = total_official
        m["routes.tourist_total"] = total_tourist
    else:
        for key in SCENIC_KEYS.values():
            m[f"coverage.{key}"] = m[f"tau.{key}"] = None
        m["routes.official_total"] = m["routes.tourist_total"] = None

    # task4 共指消解
    ev = _load(ROOT / "task4/output/evaluation.json")
    m["coref.n"] = ev.get("n") if ev else None
    m["coref.accuracy"] = ev.get("accuracy_overall") if ev else None

    # task5 条件建议
    ex = _load(ROOT / "task5/output/extraction_stats.json")
    m["cond.pairs"] = ex.get("after_dedup") if ex else None
    rv = _load(ROOT / "task5/output/review_summary.json")
    if rv:
        m["cond.review_n"] = rv.get("n")
        verdicts = rv.get("verdicts", {})
        m["cond.correct"] = verdicts.get("correct")
        m["cond.boundary"] = verdicts.get("boundary")
        m["cond.wrong"] = verdicts.get("wrong")
    else:
        m["cond.review_n"] = m["cond.correct"] = None

    # task6 知识图谱
    gs = _load(ROOT / "task6/output/graph_stats.json")
    m["graph.nodes"] = gs.get("total_nodes") if gs else None
    m["graph.edges"] = gs.get("total_edges") if gs else None
    gv = _load(ROOT / "task6/output/graph_validation.json")
    if gv:
        checks = gv.get("fact_checks", [])
        m["graph.fact_checks_passed"] = sum(1 for c in checks if c.get("found"))
        m["graph.fact_checks_total"] = len(checks)
        m["graph.name_alignment_passed"] = gv.get("name_alignment", {}).get("passed")
    else:
        m["graph.fact_checks_passed"] = m["graph.fact_checks_total"] = None

    # task7 Agent
    tr = _load(ROOT / "task7/output/test_report.json")
    m["agent.passed"] = tr.get("n_passed") if tr else None
    m["agent.total"] = tr.get("n_scenarios") if tr else None
    m["agent.mode"] = tr.get("mode") if tr else None

    return m


def fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".")
    return str(v)


# 占位符用下划线键（str.format 会把 {a.b} 解析为属性访问）
LEDGER_COLUMNS = [
    ("时点", "{time}"),
    ("git", "{git}"),
    ("说明", "{label}"),
    ("数据集", "{dataset_count}"),
    ("实体", "{entities_total}"),
    ("POI", "{entities_poi}"),
    ("交通", "{entities_transport}"),
    ("时间", "{entities_time}"),
    ("抽检", "{entity_spot_correct}/{entity_spot_n}"),
    ("覆盖 九/颐/黄", "{coverage_row}"),
    ("tau 九/颐/黄", "{tau_row}"),
    ("消解", "{coref_accuracy}"),
    ("条件对", "{cond_pairs}"),
    ("条件抽检 正/界/误", "{cond_row}"),
    ("图节点", "{graph_nodes}"),
    ("图边", "{graph_edges}"),
    ("核验", "{graph_row}"),
    ("Agent", "{agent_row}"),
]


def _row_cells(m: dict, meta: dict) -> list[str]:
    slash = lambda a, b: "—" if a is None or b is None else f"{fmt(a)}/{fmt(b)}"
    trio = lambda *vals: "/".join(fmt(v) for v in vals)
    cells = {
        "time": meta["time"],
        "git": meta["git"],
        "label": meta["label"],
        "dataset_count": fmt(m["dataset.count"]),
        "entities_total": fmt(m["entities.total"]),
        "entities_poi": fmt(m["entities.poi"]),
        "entities_transport": fmt(m["entities.transport"]),
        "entities_time": fmt(m["entities.time"]),
        "entity_spot_correct": fmt(m["entity_spot.correct"]),
        "entity_spot_n": fmt(m["entity_spot.n"]),
        "coverage_row": trio(m["coverage.jiuzhaigou"], m["coverage.yiheyuan"], m["coverage.huangshan"]),
        "tau_row": trio(m["tau.jiuzhaigou"], m["tau.yiheyuan"], m["tau.huangshan"]),
        "coref_accuracy": fmt(m["coref.accuracy"]),
        "cond_pairs": fmt(m["cond.pairs"]),
        "cond_row": trio(m["cond.correct"], m["cond.boundary"], m["cond.wrong"]),
        "graph_nodes": fmt(m["graph.nodes"]),
        "graph_edges": fmt(m["graph.edges"]),
        "graph_row": f"{fmt(m['graph.fact_checks_passed'])}/{fmt(m['graph.fact_checks_total'])}",
        "agent_row": f"{fmt(m['agent.passed'])}/{fmt(m['agent.total'])}",
    }
    return [col.format(**cells) for _, col in LEDGER_COLUMNS]


LEDGER_HEADER = [name for name, _ in LEDGER_COLUMNS]


def append_to_metrics_md(m: dict, meta: dict) -> Path:
    path = ROOT / "METRICS.md"
    cells = _row_cells(m, meta)
    lines = []
    if not path.exists():
        lines.append("# METRICS — 指标账本\n")
        lines.append(
            "由 `common/metrics_snapshot.py` 自动追加，一行一个时点；"
            "完整 JSON 见 `metrics/snapshots/`。优化改动一律对照本账本评估。\n"
        )
        lines.append("| " + " | ".join(LEDGER_HEADER) + " |")
        lines.append("|" + "|".join(["---"] * len(LEDGER_HEADER)) + "|")
    text = path.read_text(encoding="utf-8") if path.exists() else "\n".join(lines) + "\n"
    row = "| " + " | ".join(cells) + " |"
    if "| " + " | ".join(LEDGER_HEADER) + " |" not in text:
        # 已有文件但缺表头（不应发生）：补一段新表
        text += "\n| " + " | ".join(LEDGER_HEADER) + " |\n"
        text += "|" + "|".join(["---"] * len(LEDGER_HEADER)) + "|\n"
    text += row + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def save_snapshot_json(m: dict, meta: dict) -> Path:
    snap_dir = ROOT / "metrics" / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    stamp = meta["time"].replace(":", "").replace("-", "").replace(" ", "_")
    payload = {"meta": meta, "metrics": m}
    latest = snap_dir / "snapshot_latest.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    dated = snap_dir / f"snapshot_{stamp}.json"
    if not dated.exists():
        dated.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return latest


def main() -> int:
    ap = argparse.ArgumentParser(description="关键指标快照")
    ap.add_argument("--label", default="未命名时点", help="本时点说明，如：基线 / P2词典扩充后")
    ap.add_argument("--print-only", action="store_true", help="只打印不落盘")
    args = ap.parse_args()

    m = collect_metrics()
    meta = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "git": _git_short_hash(),
        "label": args.label,
        "dirty_files": _dirty_files(),
    }

    print(json.dumps({"meta": meta, "metrics": m}, ensure_ascii=False, indent=1))
    if args.print_only:
        return 0

    json_path = save_snapshot_json(m, meta)
    md_path = append_to_metrics_md(m, meta)
    print(f"[snapshot] JSON -> {json_path.relative_to(ROOT)}")
    print(f"[snapshot] 账本追加 -> {md_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
