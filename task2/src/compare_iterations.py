"""比较 iter1 基线与 iter2 最终结果，输出前后变化证据。

噪声指标、粗粒度子类和票务词由 `config.json` 决定；不再写死具体地名或固定噪声词。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from config import add_config_argument, load_config  # noqa: E402
from io_utils import write_json  # noqa: E402
from schema import TYPE_POI, TYPE_TIME, TYPE_TRANSPORT  # noqa: E402

FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path(r"C:\Windows\Fonts\simsun.ttc"),
]
METRIC_LABELS = {
    "documents": "文档数",
    "total_entities": "实体总数",
    "poi_entities_excluding_root": "POI（不含根景区）",
    "poi_all_entities": "POI（含根景区）",
    "transport_entities": "交通",
    "time_entities": "时间",
    "duration_entities": "时长",
    "time_nodes_excluding_duration": "时间节点（不含时长）",
    "poi_unique_keys": "POI 唯一词",
    "coarse_poi_share": "粗粒度 POI 占比",
    "ticket_adjacent_transport": "票务相邻交通",
    "root_area_entities": "根景区名",
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_font() -> Path | None:
    for path in FONT_CANDIDATES:
        if path.exists():
            return path
    return None


def summary(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    comparison_config = config.get("comparison", {})
    coarse_subtypes = set(comparison_config.get("coarse_subtypes", ["景区片区"]))
    ticket_words = comparison_config.get("ticket_words", ["票", "票价", "购票", "买票"])
    ticket_pattern = re.compile("|".join(re.escape(word) for word in ticket_words))
    radius = int(comparison_config.get("ticket_context_radius", 3))

    def ticket_adjacent(entity: dict[str, Any]) -> bool:
        if entity["type"] != TYPE_TRANSPORT:
            return False
        offset = int(entity["end"]) - int(entity.get("context_start", 0))
        following = (entity.get("context") or "")[offset : offset + radius]
        return bool(ticket_pattern.search(following))

    entities = payload["entities"]
    by_type = Counter(entity["type"] for entity in entities)
    poi_all = [entity for entity in entities if entity["type"] == TYPE_POI]
    poi = [entity for entity in poi_all if not entity.get("is_root_area")]
    coarse = [entity for entity in poi if entity["subtype"] in coarse_subtypes]
    result: dict[str, Any] = {
        "iteration": payload.get("iteration"),
        "documents": payload.get("counts", {}).get("documents", 0),
        "total_entities": len(entities),
        "poi_entities_excluding_root": len(poi),
        "poi_all_entities": len(poi_all),
        "transport_entities": by_type.get(TYPE_TRANSPORT, 0),
        "time_entities": by_type.get(TYPE_TIME, 0),
        "duration_entities": sum(1 for entity in entities if entity["subtype"] == "时长"),
        "time_nodes_excluding_duration": sum(
            1
            for entity in entities
            if entity["type"] == TYPE_TIME and entity.get("counts_as_time_node", True)
        ),
        "poi_unique_keys": len({entity["frequency_key"] for entity in poi}),
        "coarse_poi_share": round(len(coarse) / len(poi), 4) if poi else 0.0,
        "ticket_adjacent_transport": sum(1 for entity in entities if ticket_adjacent(entity)),
        "root_area_entities": sum(1 for entity in poi_all if entity.get("is_root_area")),
        "areas": sorted({entity["scenic_area"] for entity in entities}),
    }
    labels = dict(METRIC_LABELS)
    for rule in comparison_config.get("noise_rules", []):
        rule_id = str(rule.get("id") or "")
        if not rule_id:
            continue
        labels[rule_id] = str(rule.get("label") or rule_id)
        rule_type = str(rule.get("type") or "")
        pattern = re.compile(str(rule.get("surface_regex") or "."))
        result[rule_id] = sum(
            1
            for entity in entities
            if (not rule_type or entity["type"] == rule_type)
            and pattern.search(entity["surface"])
        )
    result["_labels"] = labels
    return result


def compare(iter1: dict[str, Any], iter2: dict[str, Any]) -> dict[str, Any]:
    metric_keys = [
        key
        for key, value in iter1.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    labels = dict(iter1.get("_labels") or {})
    rows = []
    for metric in metric_keys:
        before = iter1.get(metric, 0)
        after = iter2.get(metric, 0)
        rows.append(
            {
                "metric": metric,
                "label": labels.get(metric, METRIC_LABELS.get(metric, metric)),
                "iter1": before,
                "iter2": after,
                "delta": round(after - before, 4),
            }
        )
    areas1 = set(iter1.get("areas", []))
    areas2 = set(iter2.get("areas", []))
    return {
        "iter1": iter1,
        "iter2": iter2,
        "rows": rows,
        "areas_iter1": sorted(areas1),
        "areas_iter2": sorted(areas2),
        "areas_only_iter1": sorted(areas1 - areas2),
        "areas_only_iter2": sorted(areas2 - areas1),
    }


def markdown(comparison: dict[str, Any]) -> str:
    lines = ["# 迭代前后对比", ""]
    lines.append("| 指标 | iter1 基线 | iter2 最终 | 变化 |")
    lines.append("|---|---:|---:|---:|")
    for row in comparison["rows"]:
        delta = row["delta"]
        delta_text = f"{delta:+d}" if isinstance(delta, int) else f"{delta:+.4f}"
        lines.append(
            f"| {row['label']} | {row['iter1']} | {row['iter2']} | {delta_text} |"
        )
    lines.append("")

    up = [row["label"] for row in comparison["rows"] if row["delta"] > 0]
    down = [row["label"] for row in comparison["rows"] if row["delta"] < 0]
    flat = [row["label"] for row in comparison["rows"] if row["delta"] == 0]
    if up:
        lines.append("- 上升项：" + "、".join(up))
    if down:
        lines.append("- 下降项：" + "、".join(down))
    if flat:
        lines.append("- 持平项：" + "、".join(flat))
    lines.append("")

    if comparison.get("areas_only_iter1"):
        lines.append(
            "- 注意：iter1 出现而 iter2 缺失的景区："
            + "、".join(comparison["areas_only_iter1"])
        )
    if comparison.get("areas_only_iter2"):
        lines.append(
            "- 注意：iter2 新增的景区："
            + "、".join(comparison["areas_only_iter2"])
        )
    lines.append(
        "- 表中的变化只反映当前输入与规则配置；具体原因请对照两侧资源文件的差异，"
        "不要仅凭数值方向推断。"
    )
    lines.append("")
    return "\n".join(lines)


def chart(
    comparison: dict[str, Any],
    path: Path,
    config: dict[str, Any],
    limit: int = 8,
) -> bool:
    preferred = [
        "total_entities",
        "poi_entities_excluding_root",
        "transport_entities",
        "time_entities",
        "coarse_poi_share",
    ]
    noise_ids = [
        str(rule.get("id"))
        for rule in config.get("comparison", {}).get("noise_rules", [])
        if rule.get("id")
    ]
    keys = [
        key
        for key in preferred + noise_ids
        if any(row["metric"] == key and (row["iter1"] or row["iter2"]) for row in comparison["rows"])
    ][:limit]
    if not keys:
        return False

    font = find_font()
    if font:
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun"]
    plt.rcParams["axes.unicode_minus"] = False
    by_key = {row["metric"]: row for row in comparison["rows"]}
    labels = [by_key[key]["label"] for key in keys]
    before = [by_key[key]["iter1"] for key in keys]
    after = [by_key[key]["iter2"] for key in keys]
    width = 0.38
    positions = list(range(len(labels)))
    fig, ax = plt.subplots(figsize=(max(9, 1.3 * len(labels)), 5))
    ax.bar([p - width / 2 for p in positions], before, width=width, label="iter1 基线", color="#B0B0B0")
    ax.bar([p + width / 2 for p in positions], after, width=width, label="iter2 最终", color="#4C78A8")
    ax.set_xticks(positions)
    ax.set_xticklabels(labels, rotation=20 if len(labels) > 5 else 0, ha="right" if len(labels) > 5 else "center")
    ax.set_ylabel("数值")
    ax.set_title("迭代前后指标变化")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return True


def run(
    iter1_path: Path,
    iter2_path: Path,
    output_dir: Path,
    charts_dir: Path,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = load_config() if config is None else config
    iter1 = summary(load(iter1_path), config)
    iter2 = summary(load(iter2_path), config)
    comparison = compare(iter1, iter2)
    output_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "iteration_comparison.json", comparison)
    (output_dir / "iteration_comparison.md").write_text(markdown(comparison), encoding="utf-8")
    (output_dir / "iterations").mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "iterations" / "iter1_summary.json", iter1)
    write_json(output_dir / "iterations" / "iter2_summary.json", iter2)
    chart_path = charts_dir / "iter1_vs_iter2.png"
    if not chart(comparison, chart_path, config):
        note = charts_dir / "iteration_chart_unavailable.txt"
        note.write_text("iter1/iter2 指标全为 0，未生成对比图。\n", encoding="utf-8")
        if chart_path.exists():
            chart_path.unlink()
    print(f"[compare] written to {output_dir}", flush=True)
    return comparison


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="task2 迭代对比")
    add_config_argument(parser)
    parser.add_argument("--iter1", required=True)
    parser.add_argument("--iter2", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--charts-dir", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    run(
        Path(args.iter1),
        Path(args.iter2),
        Path(args.output_dir),
        Path(args.charts_dir),
        config=config,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
