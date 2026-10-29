"""实体词频统计、分景区/分来源对比与跨景区归纳。

来源集合、scope、top-N 和输出目录由 `config.json` 决定；所有景区名都从本次
实体数据动态取得，不假设固定景区或固定条数。

用法:
    python src/stats_entities.py --entities outputs/entities.json --output-dir outputs

输出:
    frequency_by_type.csv
    frequency_detail.csv
    frequency_by_area_type.csv
    stats_summary.json
    top_terms.json
    type_system_induction.md
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from config import add_config_argument, load_config, scope_sources, source_kinds
from io_utils import write_csv, write_json
from schema import TYPE_POI, TYPE_TIME, TYPE_TRANSPORT, TYPES

# 兼容旧调用；实际 scope 由 config 决定。
SCOPES = {
    "analysis": {"tourist", "official_route"},
    "all": {"tourist", "official_route", "official_document"},
    "tourist": {"tourist"},
    "official_route": {"official_route"},
    "official_document": {"official_document"},
}


def load_entities(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def filter_entities(
    entities: Iterable[dict[str, Any]],
    scope: str,
    exclude_root_area: bool,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    allowed = scope_sources(config, scope) if config is not None else SCOPES[scope]
    rows = [entity for entity in entities if entity["source_kind"] in allowed]
    if exclude_root_area:
        rows = [
            entity
            for entity in rows
            if not (entity["type"] == TYPE_POI and entity.get("is_root_area"))
        ]
    return rows


def count_by_type(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals = Counter(entity["type"] for entity in entities)
    total = len(entities)
    rows = []
    for entity_type in TYPES:
        count = totals.get(entity_type, 0)
        rows.append(
            {
                "type": entity_type,
                "mention_count": count,
                "doc_count": len(
                    {
                        (entity["source_kind"], entity["source_record_id"])
                        for entity in entities
                        if entity["type"] == entity_type
                    }
                ),
                "unique_frequency_keys": len(
                    {entity["frequency_key"] for entity in entities if entity["type"] == entity_type}
                ),
                "share": round(count / total, 4) if total else 0.0,
            }
        )
    return rows


def count_detail(
    entities: list[dict[str, Any]],
    source_order: Iterable[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """按来源动态生成 `<kind>_count` 列，不假设固定来源集合。"""
    present = {entity["source_kind"] for entity in entities}
    ordered = [kind for kind in (source_order or []) if kind in present]
    ordered.extend(sorted(present - set(ordered)))

    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for entity in entities:
        key = (
            entity["type"],
            entity["subtype"],
            entity["frequency_key"],
            entity["scenic_area"],
        )
        row = groups.setdefault(
            key,
            {
                "type": entity["type"],
                "subtype": entity["subtype"],
                "normalized": entity["frequency_key"],
                "frequency_key": entity["frequency_key"],
                "scenic_area": entity["scenic_area"],
                "mention_count": 0,
                "docs": set(),
                "source_counts": defaultdict(int),
            },
        )
        row["mention_count"] += 1
        row["docs"].add((entity["source_kind"], entity["source_record_id"]))
        row["source_counts"][entity["source_kind"]] += 1

    rows = []
    for row in groups.values():
        docs = row.pop("docs")
        source_counts = row.pop("source_counts")
        row["doc_count"] = len(docs)
        for kind in ordered:
            row[f"{kind}_count"] = source_counts.get(kind, 0)
        rows.append(row)
    rows.sort(key=lambda item: (item["type"], -item["mention_count"], item["frequency_key"]))
    return rows, ordered


def count_by_area_type(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for entity in entities:
        key = (entity["scenic_area"], entity["type"])
        row = groups.setdefault(
            key,
            {
                "scenic_area": entity["scenic_area"],
                "type": entity["type"],
                "mention_count": 0,
                "docs": set(),
                "keys": set(),
            },
        )
        row["mention_count"] += 1
        row["docs"].add((entity["source_kind"], entity["source_record_id"]))
        row["keys"].add(entity["frequency_key"])
    rows = []
    for row in groups.values():
        rows.append(
            {
                "scenic_area": row["scenic_area"],
                "type": row["type"],
                "mention_count": row["mention_count"],
                "doc_count": len(row["docs"]),
                "unique_frequency_keys": len(row["keys"]),
            }
        )
    rows.sort(key=lambda item: (item["scenic_area"], item["type"]))
    return rows


def top_terms(entities: list[dict[str, Any]], type_name: str, limit: int = 10) -> list[dict[str, Any]]:
    counter = Counter(
        entity["frequency_key"] for entity in entities if entity["type"] == type_name
    )
    docs: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for entity in entities:
        if entity["type"] == type_name:
            docs[entity["frequency_key"]].add(
                (entity["source_kind"], entity["source_record_id"])
            )
    return [
        {"key": key, "count": count, "doc_count": len(docs[key])}
        for key, count in counter.most_common(limit)
    ]


def without_root_area(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        entity
        for entity in entities
        if not (entity["type"] == TYPE_POI and entity.get("is_root_area"))
    ]


def _common_keys(
    entities: list[dict[str, Any]],
    areas: list[str],
    type_name: str,
    field: str = "frequency_key",
) -> set[str]:
    sets = []
    for area in areas:
        sets.append(
            {
                entity[field]
                for entity in entities
                if entity["scenic_area"] == area and entity["type"] == type_name
            }
        )
    if not sets:
        return set()
    common = sets[0]
    for item in sets[1:]:
        common &= item
    return common


def build_induction(entities: list[dict[str, Any]], config: dict[str, Any] | None = None) -> str:
    config = config or {}
    top_n = config.get("top_n", {})
    entities = without_root_area(entities)
    areas = sorted({entity["scenic_area"] for entity in entities})
    lines = ["# 跨景区实体类型归纳", ""]
    if len(areas) == 1:
        lines[-1] = "# 实体类型归纳"
        lines.append(
            "本文件由 `stats_entities.py` 自动生成；当前数据只有一个景区，"
            "因此不进行跨景区比较，仅给出该景区的分布。"
        )
    else:
        lines.append(
            "本文件由 `stats_entities.py` 自动生成，按本次实际出现的景区分组；"
            "统计口径由运行参数 `--scope` 决定。"
        )
    lines.append("")

    lines.append("## 1. 各景区 POI top 10")
    lines.append("")
    lines.append("| 景区 | POI top 10 |")
    lines.append("|---|---|")
    for area in areas:
        rows = [
            entity
            for entity in entities
            if entity["scenic_area"] == area and entity["type"] == TYPE_POI
        ]
        top = "、".join(
            f"{item['key']}({item['count']})"
            for item in top_terms(rows, TYPE_POI, int(top_n.get("per_area", 10)))
        )
        lines.append(f"| {area} | {top} |")
    lines.append("")

    lines.append("## 2. 各景区交通方式 top 8")
    lines.append("")
    lines.append("| 景区 | 交通方式 top 8 |")
    lines.append("|---|---|")
    for area in areas:
        rows = [
            entity
            for entity in entities
            if entity["scenic_area"] == area and entity["type"] == TYPE_TRANSPORT
        ]
        top = "、".join(
            f"{item['key']}({item['count']})"
            for item in top_terms(rows, TYPE_TRANSPORT, 8)
        )
        lines.append(f"| {area} | {top} |")
    lines.append("")

    lines.append("## 3. 各景区时间子类型分布")
    lines.append("")
    lines.append("| 景区 | 子类型计数 |")
    lines.append("|---|---|")
    for area in areas:
        counter = Counter(
            entity["subtype"]
            for entity in entities
            if entity["scenic_area"] == area and entity["type"] == TYPE_TIME
        )
        detail = "、".join(f"{key}:{value}" for key, value in sorted(counter.items()))
        lines.append(f"| {area} | {detail} |")
    lines.append("")

    lines.append("## 4. 归纳结论")
    lines.append("")
    if len(areas) <= 1:
        lines.append("- 当前只有一个景区，跨景区共性与差异不适用；上表给出该景区的实体分布。")
    else:
        common_transport = _common_keys(entities, areas, TYPE_TRANSPORT)
        if common_transport:
            ranked = ", ".join(
                f"{key}({count})"
                for key, count in Counter(
                    entity["frequency_key"]
                    for entity in entities
                    if entity["type"] == TYPE_TRANSPORT
                    and entity["frequency_key"] in common_transport
                ).most_common(5)
            )
            lines.append(f"- **共性交通**：所有景区都出现的交通方式为 {ranked}。")
        else:
            lines.append("- **共性交通**：各景区的交通方式没有完全重合的项，说明交通组织差异较大。")

        common_time = _common_keys(entities, areas, TYPE_TIME, field="subtype")
        if common_time:
            lines.append(
                "- **共性时间**：所有景区都出现的时间子类型/表达为 "
                + "、".join(sorted(common_time)[:10])
                + "。"
            )
        else:
            lines.append("- **共性时间**：各景区的时间子类型没有完全重合的项。")

        dominant = []
        for area in areas:
            counter = Counter(
                entity["subtype"]
                for entity in entities
                if entity["scenic_area"] == area and entity["type"] == TYPE_POI
            )
            if counter:
                subtype, count = counter.most_common(1)[0]
                dominant.append(f"{area}→{subtype}({count})")
        if dominant:
            lines.append("- **各景区主导 POI 子类**：" + "；".join(dominant) + "。")
    lines.append("- **边界口径**：时长保留为时间节点子类但 `counts_as_time_node=false`；"
                 "具名交通设施归交通方式并记录 `linked_poi`；根景区名保留但默认从 POI 图排除；"
                 "词典未覆盖景区使用低置信后缀兜底并标 `fallback=true`。")
    lines.append("")
    qc_dir = (
        Path(config["outputs"]["dir"]) / config["outputs"]["qc_subdir"]
        if config
        else Path("outputs") / "qc"
    )
    lines.append(
        f"> 结论需结合 `{(qc_dir / 'qc_report.md').as_posix()}` 与人工抽查阅读；"
        "自动生成的统计不能替代人工判断。"
    )
    lines.append("")
    return "\n".join(lines)


def run(
    entities_path: Path,
    output_dir: Path,
    scope: str | None = None,
    exclude_root_area: bool = False,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = load_config() if config is None else config
    scope = scope or str(config["scope"].get("default") or "analysis")
    payload = load_entities(entities_path)
    entities = filter_entities(payload["entities"], scope, exclude_root_area, config)
    if not entities:
        raise ValueError(f"scope={scope} 过滤后没有实体")

    top_n = config.get("top_n", {})
    by_type = count_by_type(entities)
    detail, source_columns = count_detail(
        entities, source_order=source_kinds(config)
    )
    by_area_type = count_by_area_type(entities)
    output_dir.mkdir(parents=True, exist_ok=True)

    write_csv(
        output_dir / "frequency_by_type.csv",
        by_type,
        ["type", "mention_count", "doc_count", "unique_frequency_keys", "share"],
    )
    write_csv(
        output_dir / "frequency_detail.csv",
        detail,
        [
            "type",
            "subtype",
            "normalized",
            "frequency_key",
            "scenic_area",
            "mention_count",
            "doc_count",
            *(f"{kind}_count" for kind in source_columns),
        ],
    )
    write_csv(
        output_dir / "frequency_by_area_type.csv",
        by_area_type,
        [
            "scenic_area",
            "type",
            "mention_count",
            "doc_count",
            "unique_frequency_keys",
        ],
    )

    poi_limit = int(top_n.get("poi", 20))
    transport_limit = int(top_n.get("transport", 20))
    time_limit = int(top_n.get("time", 20))
    duration_limit = int(top_n.get("duration", 20))
    duration_mentions = sum(1 for entity in entities if entity["subtype"] == "时长")
    time_nodes = sum(
        1
        for entity in entities
        if entity["type"] == TYPE_TIME and entity.get("counts_as_time_node", True)
    )
    areas = sorted({entity["scenic_area"] for entity in entities})
    area_top_terms = {
        area: {
            TYPE_POI: top_terms(
                without_root_area(
                    [entity for entity in entities if entity["scenic_area"] == area]
                ),
                TYPE_POI,
                int(top_n.get("per_area", 10)),
            ),
            TYPE_TRANSPORT: top_terms(
                [entity for entity in entities if entity["scenic_area"] == area],
                TYPE_TRANSPORT,
                8,
            ),
            TYPE_TIME: top_terms(
                [
                    entity
                    for entity in entities
                    if entity["scenic_area"] == area and entity["subtype"] != "时长"
                ],
                TYPE_TIME,
                int(top_n.get("per_area", 10)),
            ),
        }
        for area in areas
    }
    summary = {
        "scope": scope,
        "exclude_root_area": exclude_root_area,
        "entities_used": len(entities),
        "documents_used": len(
            {(entity["source_kind"], entity["source_record_id"]) for entity in entities}
        ),
        "areas": areas,
        "source_kinds": source_columns,
        "by_type": {row["type"]: row["mention_count"] for row in by_type},
        "duration_mentions": duration_mentions,
        "time_nodes_excluding_duration": time_nodes,
        "root_area_mentions": sum(
            1
            for entity in payload["entities"]
            if entity["type"] == TYPE_POI and entity.get("is_root_area")
        ),
        "top_terms": {
            TYPE_POI: top_terms(without_root_area(entities), TYPE_POI, poi_limit),
            TYPE_TRANSPORT: top_terms(entities, TYPE_TRANSPORT, transport_limit),
            TYPE_TIME: top_terms(
                [entity for entity in entities if entity["subtype"] != "时长"],
                TYPE_TIME,
                time_limit,
            ),
            "时长": top_terms(
                [entity for entity in entities if entity["subtype"] == "时长"],
                TYPE_TIME,
                duration_limit,
            ),
        },
        "area_top_terms": area_top_terms,
        "source_scope": sorted({entity["source_kind"] for entity in entities}),
        "warnings": payload.get("warnings") or payload.get("counts", {}).get("warnings", []),
    }
    write_json(output_dir / "stats_summary.json", summary)
    write_json(output_dir / "top_terms.json", summary["top_terms"])
    (output_dir / "type_system_induction.md").write_text(
        build_induction(entities, config), encoding="utf-8"
    )
    print(
        f"[stats] {len(entities)} entities, scope={scope}, "
        f"duration={duration_mentions}, time_nodes={time_nodes} -> {output_dir}",
        flush=True,
    )
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="task2 实体词频统计")
    add_config_argument(parser)
    parser.add_argument("--entities", required=True, help="entities.json 路径")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--scope",
        default=None,
        help="scope 名（见配置）或逗号分隔的来源名；默认取配置",
    )
    parser.add_argument("--exclude-root-area", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    run(
        Path(args.entities),
        Path(args.output_dir),
        scope=args.scope,
        exclude_root_area=args.exclude_root_area,
        config=config,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
