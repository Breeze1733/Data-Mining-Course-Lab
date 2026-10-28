"""实体质量检查：结构、偏移、重复、类型混淆、银标准与人工抽查。

银标准、抽样配额、类型混淆词和人工边界案例都由配置与当前数据动态生成，
不假设固定景区、固定来源或固定案例。

用法:
    python src/qc_entities.py --input-dir inputs --entities outputs/entities.json \
        --output-dir outputs/qc
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from config import add_config_argument, load_config, resolve_path, source_kinds
from dictionary import Gazetteer, load_poi_gazetteer, load_transport_lexicon
from io_utils import (
    load_source_records,
    merged_specs,
    read_jsonl,
    write_csv,
    write_json,
)
from schema import TYPE_POI, TYPE_TIME, TYPE_TRANSPORT, validate_entity

SAMPLE_SEED = 42
TYPE_ORDER = (TYPE_POI, TYPE_TRANSPORT, TYPE_TIME)
TRANSPORT_HEADS = re.compile(r"索道|缆车|观光车|大巴|步行|徒步|游船|轮渡")
TICKET_WORDS = re.compile(r"票|票价|购票|买票")


def _first_present(row: dict[str, Any], candidates: Iterable[str] | None) -> Any:
    for key in candidates or ():
        if key and key in row and row[key] is not None:
            return row[key]
    return None


def load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_record_texts(
    input_dir: Path, config: dict[str, Any] | None = None
) -> dict[tuple[str, str], str]:
    config = load_config() if config is None else config
    records, _ = load_source_records(
        input_dir,
        source_kinds(config),
        specs=merged_specs(config["input"]["sources"]),
        field_map=config["input"]["field_map"],
        require_area=False,
    )
    return {(record.source_kind, record.source_record_id): record.cleaned_text for record in records}


def build_gold(input_dir: Path, config: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """从游客文本的 matched_pois 构造粗粒度银标准；字段缺失时返回空。"""
    config = load_config() if config is None else config
    specs = merged_specs(config["input"]["sources"])
    tourist = specs.get("tourist")
    mapping = config["input"]["field_map"]
    if not tourist:
        return {}
    path = input_dir / str(tourist["file"])
    if not path.exists():
        return {}
    id_fields = [str(tourist.get("id_field") or "record_id")]
    poi_fields = mapping.get("matched_pois", ["matched_pois"])
    gold: dict[str, list[str]] = {}
    for row in read_jsonl(path):
        record_id = str(_first_present(row, id_fields) or "")
        if not record_id:
            continue
        values = _first_present(row, poi_fields) or []
        gold[record_id] = [str(item) for item in values]
    return gold


def check_schema_and_offsets(
    entities: Iterable[dict[str, Any]],
    texts: dict[tuple[str, str], str],
    allowed_kinds: set[str] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    missing_records: list[dict[str, Any]] = []
    for entity in entities:
        key = (entity["source_kind"], entity["source_record_id"])
        text = texts.get(key)
        if text is None:
            missing_records.append(
                {
                    "source_kind": entity["source_kind"],
                    "source_record_id": entity["source_record_id"],
                    "surface": entity["surface"],
                }
            )
            errors.append("missing_record")
            continue
        errors.extend(validate_entity(entity, text, allowed_kinds))
    return errors, missing_records


def check_duplicates(entities: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[tuple[str, str, int, int, str]] = Counter(
        (
            entity["source_kind"],
            entity["source_record_id"],
            int(entity["start"]),
            int(entity["end"]),
            entity["type"],
        )
        for entity in entities
    )
    rows = []
    for (source_kind, record_id, start, end, type_name), count in counter.items():
        if count > 1:
            rows.append(
                {
                    "source_kind": source_kind,
                    "source_record_id": record_id,
                    "start": start,
                    "end": end,
                    "type": type_name,
                    "count": count,
                }
            )
    return rows


def check_entity_id_collisions(entities: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, set[tuple[str, str, int, int, str]]] = defaultdict(set)
    for entity in entities:
        groups[entity["entity_id"]].add(
            (
                entity["source_kind"],
                entity["source_record_id"],
                int(entity["start"]),
                int(entity["end"]),
                entity["type"],
            )
        )
    return [
        {
            "entity_id": entity_id,
            "variants": len(values),
            "detail": " | ".join(
                f"{kind}:{record}:{start}-{end}:{type_name}"
                for kind, record, start, end, type_name in sorted(values)
            ),
        }
        for entity_id, values in sorted(groups.items())
        if len(values) > 1
    ]


def check_cross_type_overlaps(entities: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for entity in entities:
        grouped[(entity["source_kind"], entity["source_record_id"])].append(entity)
    overlaps = []
    for (source_kind, record_id), rows in grouped.items():
        rows = sorted(rows, key=lambda item: (int(item["start"]), int(item["end"])))
        for previous, current in zip(rows, rows[1:]):
            if int(current["start"]) < int(previous["end"]):
                overlaps.append(
                    {
                        "source_kind": source_kind,
                        "source_record_id": record_id,
                        "left": previous["surface"],
                        "right": current["surface"],
                        "left_span": f"{previous['start']}-{previous['end']}",
                        "right_span": f"{current['start']}-{current['end']}",
                    }
                )
    return overlaps


def _patterns(config: dict[str, Any]) -> tuple[re.Pattern[str], re.Pattern[str]]:
    qc_config = config.get("qc", {})
    confusion = qc_config.get("type_confusion", {})
    heads = re.compile(str(confusion.get("transport_heads") or TRANSPORT_HEADS.pattern))
    tickets = re.compile(str(confusion.get("ticket_words") or TICKET_WORDS.pattern))
    return heads, tickets


def check_type_confusions(
    entities: Iterable[dict[str, Any]], config: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    config = load_config() if config is None else config
    transport_heads, ticket_words = _patterns(config)
    rows = []
    for entity in entities:
        surface = entity["surface"]
        type_name = entity["type"]
        subtype = entity["subtype"]
        if type_name == TYPE_POI and transport_heads.search(surface):
            rows.append(
                {
                    "source_record_id": entity["source_record_id"],
                    "surface": surface,
                    "types": f"{type_name}|{TYPE_TRANSPORT}",
                    "reason": "poi_surface_contains_transport_head",
                    "suggested_type": TYPE_TRANSPORT,
                }
            )
        if type_name == TYPE_TRANSPORT and ticket_words.search(surface):
            rows.append(
                {
                    "source_record_id": entity["source_record_id"],
                    "surface": surface,
                    "types": type_name,
                    "reason": "transport_ticket_surface",
                    "suggested_type": "非实体",
                }
            )
        if (
            type_name == TYPE_TIME
            and subtype not in {"时长", "日期", "日期区间", "相对日"}
            and re.search(r"小时|分钟", surface)
        ):
            rows.append(
                {
                    "source_record_id": entity["source_record_id"],
                    "surface": surface,
                    "types": f"{type_name}/{subtype}",
                    "reason": "time_surface_contains_duration_unit",
                    "suggested_type": "时长",
                }
            )
        if type_name == TYPE_TIME and subtype == "时长" and entity.get("counts_as_time_node"):
            rows.append(
                {
                    "source_record_id": entity["source_record_id"],
                    "surface": surface,
                    "types": f"{type_name}/时长",
                    "reason": "duration_counted_as_time_node",
                    "suggested_type": "时长(counts_as_time_node=false)",
                }
            )
    return rows


def silver_poi(
    entities: Iterable[dict[str, Any]], gold: dict[str, list[str]]
) -> dict[str, Any]:
    by_record: dict[str, set[str]] = defaultdict(set)
    root_ids = set()
    for entity in entities:
        if entity["type"] != TYPE_POI:
            continue
        if entity.get("is_root_area"):
            root_ids.add(entity["source_record_id"])
            continue
        key = entity.get("parent_poi") or entity["normalized"]
        by_record[entity["source_record_id"]].add(key)

    records = []
    for record_id, gold_values in gold.items():
        gold_set = set(gold_values)
        if not gold_set:
            continue
        predicted = by_record.get(record_id, set())
        intersection = predicted & gold_set
        records.append(
            {
                "record_id": record_id,
                "gold": len(gold_set),
                "predicted": len(predicted),
                "hit": len(intersection),
                "recall": len(intersection) / len(gold_set),
                "agreement_precision": len(intersection) / len(predicted) if predicted else 0.0,
            }
        )
    if not records:
        return {
            "available": False,
            "scope": "tourist_matched_pois",
            "records": 0,
            "micro": {},
            "macro": {},
            "caveat": "输入中没有可用的 matched_pois；银标准指标不可用。",
        }

    gold_total = sum(row["gold"] for row in records)
    pred_total = sum(row["predicted"] for row in records)
    hit_total = sum(row["hit"] for row in records)
    return {
        "available": True,
        "scope": "tourist_matched_pois",
        "records": len(records),
        "records_with_root_area": len(root_ids),
        "micro": {
            "recall": round(hit_total / gold_total, 4) if gold_total else 0.0,
            "agreement_precision": round(hit_total / pred_total, 4) if pred_total else 0.0,
            "gold_mentions": gold_total,
            "predicted_mentions": pred_total,
            "hits": hit_total,
        },
        "macro": {
            "recall": round(sum(row["recall"] for row in records) / len(records), 4),
            "agreement_precision": round(
                sum(row["agreement_precision"] for row in records) / len(records), 4
            ),
        },
        "caveat": "matched_pois 是粗粒度存在性列表，不是 gold span/类型标注；该指标只作召回代理，精确率以人工抽查为准。",
    }


def _find_entity(
    entities: list[dict[str, Any]], surface: str, type_name: str | None = None
) -> dict[str, Any] | None:
    return next(
        (
            entity
            for entity in entities
            if entity["surface"] == surface
            and (type_name is None or entity["type"] == type_name)
        ),
        None,
    )


def derive_boundary_cases(
    entities: list[dict[str, Any]],
    gazetteer: Gazetteer,
    transport_entries: list[Any],
    config: dict[str, Any],
) -> list[dict[str, str]]:
    """从词典、规则和本次输出动态生成人工复核的边界案例。"""
    cases: list[dict[str, str]] = []
    current_areas = {entity["scenic_area"] for entity in entities}

    # 1) 词典内短名被长名包含：考最长匹配（只看本次出现的景区）
    for area in sorted(current_areas & set(gazetteer.areas))[:4]:
        surfaces = sorted(gazetteer.area_surfaces(area), key=len)
        found = False
        for index, short in enumerate(surfaces):
            for long in surfaces[index + 1 :]:
                if short != long and short in long:
                    cases.append(
                        {
                            "surface": long,
                            "type": TYPE_POI,
                            "stratum": "boundary",
                            "evidence": f"最长匹配：{short} ⊂ {long}（{area}）",
                        }
                    )
                    found = True
                    break
            if found:
                break

    # 2) 带否定语境的词典条目
    for entry in gazetteer.poi_entries:
        if (
            entry.area in current_areas
            and entry.negative_after
            and _find_entity(entities, entry.surface, TYPE_POI)
        ):
            cases.append(
                {
                    "surface": entry.surface,
                    "type": TYPE_POI,
                    "stratum": "boundary",
                    "evidence": f"否定语境：{entry.negative_after}",
                }
            )
            break

    # 3) 具名交通设施
    for entry in transport_entries:
        if entry.linked_poi and _find_entity(entities, entry.surface, TYPE_TRANSPORT):
            cases.append(
                {
                    "surface": entry.surface,
                    "type": TYPE_TRANSPORT,
                    "stratum": "boundary",
                    "evidence": f"具名交通：linked_poi={entry.linked_poi}",
                }
            )
            break

    # 4) 本次实际出现的时间规则各取一条代表
    time_rules: dict[str, dict[str, Any]] = {}
    for entity in entities:
        if entity["type"] == TYPE_TIME:
            time_rules.setdefault(entity["rule_id"], entity)
    for rule_id, entity in sorted(time_rules.items())[:3]:
        cases.append(
            {
                "surface": entity["surface"],
                "type": TYPE_TIME,
                "stratum": "boundary",
                "evidence": f"时间规则：{rule_id}",
            }
        )

    # 5) 本次实际出现的通用后缀规则各取一条代表
    fallback_rules: dict[str, dict[str, Any]] = {}
    for entity in entities:
        if entity.get("method") == "generic_suffix":
            fallback_rules.setdefault(entity["rule_id"], entity)
    for rule_id, entity in sorted(fallback_rules.items())[:3]:
        cases.append(
            {
                "surface": entity["surface"],
                "type": entity["type"],
                "stratum": "boundary",
                "evidence": f"通用后缀兜底：{rule_id}",
            }
        )

    # 6) 配置中的人工追加项
    for item in config.get("qc", {}).get("boundary_cases", []):
        if isinstance(item, str):
            cases.append(
                {"surface": item, "type": "", "stratum": "boundary", "evidence": "配置追加"}
            )
        elif isinstance(item, dict) and item.get("surface"):
            cases.append(
                {
                    "surface": str(item["surface"]),
                    "type": str(item.get("type") or ""),
                    "stratum": "boundary",
                    "evidence": str(item.get("reason") or "配置追加"),
                }
            )

    limit = int(config.get("qc", {}).get("boundary_limit", 12))
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for case in cases:
        key = (case["surface"], case["type"])
        if key in seen:
            continue
        seen.add(key)
        result.append(case)
        if len(result) >= limit:
            break
    return result


def sample_manual(
    entities: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
    gazetteer: Gazetteer | None = None,
    transport_entries: list[Any] | None = None,
) -> list[dict[str, Any]]:
    config = load_config() if config is None else config
    qc_config = config.get("qc", {})
    seed = int(qc_config.get("seed", SAMPLE_SEED))
    quotas = qc_config.get("quotas", {})
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    used: set[str] = set()
    index = 0
    present_kinds = {entity["source_kind"] for entity in entities}
    for type_name in TYPE_ORDER:
        for source_kind, quota in quotas.items():
            if source_kind not in present_kinds:
                continue
            pool = [
                entity
                for entity in entities
                if entity["type"] == type_name and entity["source_kind"] == source_kind
            ]
            for entity in rng.sample(pool, min(int(quota), len(pool))):
                index += 1
                used.add(entity["entity_id"])
                rows.append(
                    {
                        "sample_id": f"S{index:03d}",
                        "stratum": f"{type_name}/{source_kind}",
                        "source_kind": entity["source_kind"],
                        "source_record_id": entity["source_record_id"],
                        "scenic_area": entity["scenic_area"],
                        "entity_id": entity["entity_id"],
                        "type": entity["type"],
                        "subtype": entity["subtype"],
                        "surface": entity["surface"],
                        "start": entity["start"],
                        "end": entity["end"],
                        "context": entity["context"],
                        "auto_confidence": entity["confidence"],
                        "evidence": "分层随机抽样",
                        "label": "",
                        "error_type": "",
                        "corrected_type": "",
                        "corrected_span": "",
                        "suggested_fix": "",
                        "notes": "",
                    }
                )

    if gazetteer is None:
        return rows
    for case in derive_boundary_cases(
        entities, gazetteer, transport_entries or [], config
    ):
        match = _find_entity(
            entities, case["surface"], case["type"] or None
        )
        index += 1
        if match and match["entity_id"] not in used:
            used.add(match["entity_id"])
            rows.append(
                {
                    "sample_id": f"S{index:03d}",
                    "stratum": case["stratum"],
                    "source_kind": match["source_kind"],
                    "source_record_id": match["source_record_id"],
                    "scenic_area": match["scenic_area"],
                    "entity_id": match["entity_id"],
                    "type": match["type"],
                    "subtype": match["subtype"],
                    "surface": match["surface"],
                    "start": match["start"],
                    "end": match["end"],
                    "context": match["context"],
                    "auto_confidence": match["confidence"],
                    "evidence": case["evidence"],
                    "label": "",
                    "error_type": "",
                    "corrected_type": "",
                    "corrected_span": "",
                    "suggested_fix": "",
                    "notes": "",
                }
            )
        elif match is None:
            rows.append(
                {
                    "sample_id": f"S{index:03d}",
                    "stratum": "boundary_missing",
                    "source_kind": "",
                    "source_record_id": "",
                    "scenic_area": "",
                    "entity_id": "",
                    "type": case["type"],
                    "subtype": "",
                    "surface": case["surface"],
                    "start": "",
                    "end": "",
                    "context": "",
                    "auto_confidence": "",
                    "evidence": case["evidence"],
                    "label": "",
                    "error_type": "",
                    "corrected_type": "",
                    "corrected_span": "",
                    "suggested_fix": "",
                    "notes": "预期边界案例未在输出中找到（可能是漏识别或规则有意排除）。",
                }
            )
    return rows


def aggregate_reviewed(
    path: Path, current_ids: set[str] | None = None
) -> dict[str, Any]:
    if not path.exists():
        return {"reviewed": 0, "status": "template_only"}
    rows = read_jsonl(path) if path.suffix == ".jsonl" else []
    if not rows:
        import csv

        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    labels = Counter((row.get("label") or "").strip() for row in rows)
    reviewed = sum(
        labels.get(label, 0) for label in ("TP", "FP", "FN", "ambiguous", "skip")
    )
    ids = {str(row.get("entity_id") or "") for row in rows if row.get("entity_id")}
    matched = len(ids & current_ids) if current_ids is not None else len(ids)
    stale_rows = len(ids - current_ids) if current_ids is not None else 0
    if reviewed and ids and current_ids is not None and matched == 0:
        status = "stale_reviewed"
    else:
        status = "reviewed" if reviewed else "template_only"
    return {
        "reviewed": reviewed,
        "labels": dict(labels),
        "status": status,
        "reviewed_entity_ids": len(ids),
        "matched_current_ids": matched,
        "stale_rows": stale_rows,
    }


def report_markdown(
    counts: dict[str, int],
    schema_errors: list[str],
    duplicates: list[dict[str, Any]],
    overlaps: list[dict[str, Any]],
    confusions: list[dict[str, Any]],
    silver: dict[str, Any],
    manual: dict[str, Any],
    warnings: list[dict[str, Any]] | None = None,
    fallback_entities: int = 0,
) -> str:
    lines = ["# task2 实体质量检查报告", ""]
    lines.append("## 1. 硬校验")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---:|")
    for key, value in counts.items():
        lines.append(f"| {key} | {value} |")
    lines.append(f"| schema_errors | {len(schema_errors)} |")
    lines.append(f"| duplicate_spans | {len(duplicates)} |")
    lines.append(f"| cross_type_overlaps | {len(overlaps)} |")
    lines.append(f"| generic_suffix_entities | {fallback_entities} |")
    lines.append("")
    lines.append("## 2. 银标准（仅游客文本）")
    lines.append("")
    if silver.get("available") and silver.get("micro"):
        lines.append(f"- 记录数：{silver['records']}")
        lines.append(f"- micro recall：{silver['micro']['recall']}")
        lines.append(
            f"- agreement precision：{silver['micro']['agreement_precision']}"
        )
        lines.append(f"- {silver['caveat']}")
    else:
        lines.append("未找到可用的 matched_pois，银标准指标不可用。")
    lines.append("")
    lines.append("## 3. 类型混淆候选")
    lines.append("")
    lines.append(f"共 {len(confusions)} 条，详见 `type_confusions.csv`。")
    lines.append("")
    lines.append("## 4. 人工抽查")
    lines.append("")
    lines.append(f"- 状态：{manual.get('status')}")
    lines.append(f"- 已复核：{manual.get('reviewed')} 条")
    if manual.get("labels"):
        lines.append(f"- 标签分布：{manual['labels']}")
    if manual.get("status") == "stale_reviewed":
        lines.append("- 警告：复核表中的 entity_id 与本次输出完全不匹配，请重新复核。")
    lines.append("")
    lines.append("## 5. 告警")
    lines.append("")
    if warnings:
        for warning in warnings:
            lines.append(f"- `{warning.get('code')}`：{warning.get('detail', '')}")
    else:
        lines.append("无。")
    lines.append("")
    lines.append("## 6. 说明")
    lines.append("")
    lines.append(
        "`matched_pois`（如存在）只提供粗粒度召回代理；`agreement_precision` 会惩罚"
        "词典中更具体的 POI，因此不能当作真实精确率。精确率与歧义判断以 "
        "`manual_spotcheck_reviewed.csv` 为准。"
    )
    lines.append("")
    return "\n".join(lines)


def run(
    input_dir: Path,
    entities_path: Path,
    output_dir: Path,
    resources_dir: Path | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = load_config() if config is None else config
    if resources_dir is None:
        resources_dir = resolve_path(config, config["resources"]["dir"])
    payload = load_payload(entities_path)
    entities = payload["entities"]
    allowed_kinds = set(source_kinds(config))
    texts = build_record_texts(input_dir, config)
    schema_errors, missing_records = check_schema_and_offsets(entities, texts, allowed_kinds)
    offset_invalid = sum(
        1
        for error in schema_errors
        if error.startswith("offset_") or error == "offset_surface_mismatch"
    )
    duplicate_rows = check_duplicates(entities)
    overlap_rows = check_cross_type_overlaps(entities)
    collisions = check_entity_id_collisions(entities)
    confusions = check_type_confusions(entities, config)
    gold = build_gold(input_dir, config)
    silver = silver_poi(entities, gold)

    resource_names = config["resources"]
    poi_entries = load_poi_gazetteer(resources_dir / resource_names["poi_gazetteer"])
    transport_entries = load_transport_lexicon(resources_dir / resource_names["transport_lexicon"])
    gazetteer = Gazetteer(poi_entries, transport_entries)

    output_dir.mkdir(parents=True, exist_ok=True)
    sample = sample_manual(entities, config, gazetteer, transport_entries)
    write_csv(
        output_dir / "manual_spotcheck.csv",
        sample,
        [
            "sample_id",
            "stratum",
            "source_kind",
            "source_record_id",
            "scenic_area",
            "entity_id",
            "type",
            "subtype",
            "surface",
            "start",
            "end",
            "context",
            "auto_confidence",
            "evidence",
            "label",
            "error_type",
            "corrected_type",
            "corrected_span",
            "suggested_fix",
            "notes",
        ],
    )
    write_csv(
        output_dir / "duplicates.csv",
        duplicate_rows,
        ["source_kind", "source_record_id", "start", "end", "type", "count"],
    )
    write_csv(
        output_dir / "type_confusions.csv",
        confusions,
        ["source_record_id", "surface", "types", "reason", "suggested_type"],
    )
    write_csv(
        output_dir / "entity_id_collisions.csv",
        collisions,
        ["entity_id", "variants", "detail"],
    )
    current_ids = {entity["entity_id"] for entity in entities}
    manual = aggregate_reviewed(output_dir / "manual_spotcheck_reviewed.csv", current_ids)

    fallback_entities = sum(1 for entity in entities if entity.get("method") == "generic_suffix")
    warnings = list(
        payload.get("warnings") or payload.get("counts", {}).get("warnings", [])
    )
    if not silver.get("available"):
        warnings.append(
            {
                "code": "silver_standard_unavailable",
                "severity": "info",
                "detail": "输入中没有 matched_pois，QC 跳过银标准召回指标。",
            }
        )
    if manual.get("status") == "stale_reviewed":
        warnings.append(
            {
                "code": "stale_reviewed",
                "severity": "warning",
                "detail": "人工复核表的 entity_id 与本次输出完全不匹配，已忽略其标签含义。",
            }
        )
    elif manual.get("stale_rows"):
        warnings.append(
            {
                "code": "partially_stale_reviewed",
                "severity": "warning",
                "count": manual["stale_rows"],
                "detail": "部分人工复核行已不对应本次输出。",
            }
        )

    if collisions:
        warnings.append(
            {
                "code": "entity_id_collision",
                "severity": "warning",
                "count": len(collisions),
                "detail": "不同来源/记录复用了相同 ID，实体 ID 出现冲突；请检查各来源的 ID 唯一性。",
            }
        )

    counts = {
        "entities": len(entities),
        "documents": len(
            {(entity["source_kind"], entity["source_record_id"]) for entity in entities}
        ),
        "areas": len({entity["scenic_area"] for entity in entities}),
        "source_kinds": len({entity["source_kind"] for entity in entities}),
        "offset_valid": len(entities) - offset_invalid,
        "offset_invalid": offset_invalid,
        "missing_records": len(missing_records),
        "entity_id_collisions": len(collisions),
        "duration_entities": sum(1 for entity in entities if entity["subtype"] == "时长"),
        "time_nodes_excluding_duration": sum(
            1
            for entity in entities
            if entity["type"] == TYPE_TIME and entity.get("counts_as_time_node", True)
        ),
    }
    metrics = {
        "counts": counts,
        "schema_errors": schema_errors[:100],
        "schema_error_total": len(schema_errors),
        "duplicate_spans": len(duplicate_rows),
        "cross_type_overlaps": len(overlap_rows),
        "entity_id_collisions": len(collisions),
        "type_confusions": len(confusions),
        "generic_suffix_entities": fallback_entities,
        "silver_poi": silver,
        "manual_review": manual,
        "warnings": warnings,
        "areas": sorted({entity["scenic_area"] for entity in entities}),
        "source_kinds": sorted({entity["source_kind"] for entity in entities}),
        "hard_checks_passed": not (
            offset_invalid
            or duplicate_rows
            or overlap_rows
            or any(not error.startswith(("missing_record",)) for error in schema_errors)
        ),
    }
    write_json(output_dir / "qc_metrics.json", metrics)
    (output_dir / "qc_report.md").write_text(
        report_markdown(
            counts,
            schema_errors,
            duplicate_rows,
            overlap_rows,
            confusions,
            silver,
            manual,
            warnings,
            fallback_entities,
        ),
        encoding="utf-8",
    )
    print(
        f"[qc] entities={len(entities)} offset_invalid={offset_invalid} "
        f"duplicates={len(duplicate_rows)} overlaps={len(overlap_rows)} "
        f"confusions={len(confusions)} reviewed={manual.get('reviewed')}",
        flush=True,
    )
    return metrics


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="task2 实体质量检查")
    add_config_argument(parser)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--entities", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--resources", default=None, help="默认取自配置")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    resources_dir = (
        Path(args.resources).resolve()
        if args.resources
        else resolve_path(config, config["resources"]["dir"])
    )
    metrics = run(
        Path(args.input_dir),
        Path(args.entities),
        Path(args.output_dir),
        resources_dir,
        config,
    )
    return 0 if metrics["hard_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
