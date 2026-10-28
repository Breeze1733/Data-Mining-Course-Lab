"""批量识别景点 POI、交通方式、时间节点并导出带位置的 JSON。

用法:
    python src/extract_entities.py --input-dir inputs --resources resources \
        --iteration iter2 --output-dir outputs

    python src/extract_entities.py --config config.json --limit 5

输入来源、字段映射和资源文件名由 `config.json` 决定；缺失的可选来源会跳过并告警。
没有 POI 词典的景区使用通用后缀兜底（`method=generic_suffix`），不会静默返回 0。

输出:
    <output-dir>/entities.json      顶层元数据 + 全部实体
    <output-dir>/entities.jsonl     一行一个实体
    <output-dir>/by_area/<area>.json
    <output-dir>/extract_summary.json
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import jieba

from config import (
    add_config_argument,
    load_config,
    resolve_path,
    source_kinds,
)
from dictionary import Gazetteer, load_poi_gazetteer, load_transport_lexicon
from io_utils import (
    SourceRecord,
    ensure_input_dir,
    load_source_records,
    merged_specs,
    safe_filename,
    sha256_file,
    sha256_text,
    verify_input_manifest,
    write_json,
    write_json_compact,
    write_jsonl,
)
from offsets import context_window, locate
from poi_fallback import GenericPOIFallback, build_root_aliases, load_suffix_rules
from schema import (
    TYPE_POI,
    TYPE_TIME,
    TYPE_TRANSPORT,
    TYPES,
    make_entity_id,
    validate_entity,
)
from time_rules import TimeRules
from transport_rules import TransportRules

JIEBA_WORDS: set[str] = set()


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def load_stopwords(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def init_jieba(gazetteer: Gazetteer) -> None:
    jieba.setLogLevel(logging.ERROR)
    for entry in gazetteer.poi_entries:
        if entry.surface not in JIEBA_WORDS:
            jieba.add_word(entry.surface, freq=100000, tag="ns")
            JIEBA_WORDS.add(entry.surface)
    for entry in gazetteer.transport_entries:
        if entry.surface not in JIEBA_WORDS:
            jieba.add_word(entry.surface, freq=100000, tag="n")
            JIEBA_WORDS.add(entry.surface)


def jieba_tokens(text: str) -> set[str]:
    return {token for token, _, _ in jieba.tokenize(text, mode="search", HMM=False)}


def jieba_token_spans(text: str) -> list[tuple[str, int, int]]:
    return list(jieba.tokenize(text, mode="search", HMM=False))


def candidate_to_entity(
    candidate,
    record: SourceRecord,
    text: str,
    iteration: str,
    tokens: set[str] | None,
    root_aliases: set[str] | None = None,
) -> dict[str, Any]:
    sentence_index, clause_index, sentence_start, sentence_end, _, _ = locate(
        text, candidate.start, candidate.end
    )
    context, context_start, context_end = context_window(text, candidate.start, candidate.end)
    aliases = root_aliases or set()
    is_root_area = candidate.type == TYPE_POI and (
        bool(candidate.extra.get("root_area"))
        or candidate.normalized in aliases
        or candidate.surface in aliases
        or candidate.frequency_key in aliases
    )
    notes = candidate.notes
    if tokens is not None and candidate.type in {TYPE_POI, TYPE_TRANSPORT}:
        if candidate.surface not in tokens:
            notes = f"{notes};jieba_boundary_unconfirmed".strip(";")

    entity = {
        "entity_id": make_entity_id(record.source_record_id, candidate.start, candidate.end),
        "type": candidate.type,
        "subtype": candidate.subtype,
        "surface": candidate.surface,
        "normalized": candidate.normalized,
        "frequency_key": candidate.frequency_key,
        "source_kind": record.source_kind,
        "source_file": record.source_file,
        "source_record_id": record.source_record_id,
        "source_id_field": record.source_id_field,
        "source_line": record.source_line,
        "source_url": record.source_url,
        "parent_record_id": record.parent_record_id,
        "scenic_area": record.scenic_area,
        "source_platform": record.source_platform,
        "title": record.title,
        "ordered_route": record.ordered_route,
        "start": candidate.start,
        "end": candidate.end,
        "offset_unit": "unicode_codepoint",
        "text_sha256": record.task1_text_sha256 or sha256_text(text),
        "record_char_count": len(text),
        "sentence_index": sentence_index,
        "clause_index": clause_index,
        "sentence_start": sentence_start,
        "sentence_end": sentence_end,
        "context": context,
        "context_start": context_start,
        "context_end": context_end,
        "method": candidate.method,
        "rule_id": candidate.rule_id,
        "dictionary_id": candidate.dictionary_id,
        "confidence": candidate.confidence,
        "iteration": iteration,
        "is_root_area": is_root_area,
        "linked_poi": candidate.linked_poi or None,
        "linked_poi_start": candidate.linked_poi_start,
        "linked_poi_end": candidate.linked_poi_end,
        "ambiguous_meridiem": candidate.ambiguous_meridiem,
        "counts_as_time_node": candidate.counts_as_time_node,
        "parent_poi": candidate.extra.get("parent_poi"),
        "fallback": bool(candidate.extra.get("fallback")),
        "fallback_reason": candidate.extra.get("fallback_reason"),
        "notes": notes,
    }
    return entity


def summarize_entities(
    entities: list[dict[str, Any]],
    records: list[SourceRecord],
    warnings: list[dict[str, Any]] | None = None,
    fallback_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    by_type = Counter(entity["type"] for entity in entities)
    by_source = Counter(entity["source_kind"] for entity in entities)
    by_area = Counter(entity["scenic_area"] for entity in entities)
    by_time_subtype = Counter(
        entity["subtype"] for entity in entities if entity["type"] == TYPE_TIME
    )
    time_nodes = sum(
        1
        for entity in entities
        if entity["type"] == TYPE_TIME and entity["counts_as_time_node"]
    )
    counts: dict[str, Any] = {
        "documents": len(records),
        "entities": len(entities),
        "by_type": {entity_type: by_type.get(entity_type, 0) for entity_type in TYPES},
        "by_source_kind": dict(sorted(by_source.items())),
        "by_area": dict(sorted(by_area.items())),
        "by_time_subtype": dict(sorted(by_time_subtype.items())),
        "time_nodes_excluding_duration": time_nodes,
    }
    if warnings is not None:
        counts["warnings"] = warnings
    if fallback_stats is not None:
        counts["poi_fallback"] = fallback_stats
    return counts


def _input_warnings(input_summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for summary in input_summaries:
        kind = summary.get("source_kind")
        if summary.get("status") == "missing_optional":
            warnings.append(
                {
                    "code": "missing_optional_source",
                    "severity": "warning",
                    "source_kind": kind,
                    "detail": f"可选输入文件不存在，已跳过: {summary.get('path')}",
                }
            )
        for code, key in (
            ("missing_area_value", "skipped_missing_area"),
            ("missing_record_id", "skipped_missing_id"),
            ("empty_text", "skipped_empty_text"),
        ):
            count = int(summary.get(key) or 0)
            if count:
                warnings.append(
                    {
                        "code": code,
                        "severity": "warning",
                        "source_kind": kind,
                        "count": count,
                        "detail": f"{kind} 有 {count} 条记录因 {code} 被跳过。",
                    }
                )
    return warnings


def _fallback_stats(
    entities: list[dict[str, Any]],
    config: dict[str, Any],
    mode: str,
    missing_areas: list[str],
) -> dict[str, Any]:
    fallback_entities = [
        entity for entity in entities if entity.get("method") == "generic_suffix"
    ]
    root_entities = [
        entity for entity in entities if entity.get("method") == "area_name_match"
    ]
    return {
        "enabled": bool(config.get("enabled", True)) and mode != "never",
        "mode": mode,
        "areas_without_gazetteer": missing_areas,
        "areas_with_fallback_entities": sorted(
            {entity["scenic_area"] for entity in fallback_entities}
        ),
        "entities": len(fallback_entities),
        "root_area_entities": len(root_entities),
        "by_rule": dict(Counter(entity["rule_id"] for entity in fallback_entities)),
        "by_subtype": dict(Counter(entity["subtype"] for entity in fallback_entities)),
    }


def extract(
    input_dir: Path,
    resources_dir: Path,
    output_dir: Path,
    iteration: str,
    sources: Iterable[str] | None = None,
    areas: Iterable[str] | None = None,
    limit: int | None = None,
    record_id: str | None = None,
    generated_at: str | None = None,
    use_jieba: bool = True,
    stopwords_path: Path | None = None,
    verify_manifest: bool = True,
    config: dict[str, Any] | None = None,
    generic_fallback: str | None = None,
) -> dict[str, Any]:
    config = load_config() if config is None else config
    allowed_kinds = source_kinds(config)
    sources = list(sources) if sources is not None else allowed_kinds
    unknown = [kind for kind in sources if kind not in allowed_kinds]
    if unknown:
        raise ValueError(f"未知来源: {unknown}；可用来源: {allowed_kinds}")

    specs = merged_specs(config["input"]["sources"])
    field_map = config["input"]["field_map"]
    manifest_name = str(config["input"].get("manifest") or "manifest.json")

    if verify_manifest:
        verify_input_manifest(input_dir, sources, specs=specs, manifest_name=manifest_name)
    records, input_summaries = load_source_records(
        input_dir,
        sources,
        areas,
        specs=specs,
        field_map=field_map,
        require_area=bool(config["area"].get("require_nonempty", True)),
    )

    if record_id:
        records = [record for record in records if record.source_record_id == record_id]
    if limit is not None:
        records = records[:limit]
    if not records:
        raise ValueError("没有匹配的输入记录，请检查 --area / --limit / --record-id 或输入文件")

    resource_names = config["resources"]
    poi_entries = load_poi_gazetteer(resources_dir / resource_names["poi_gazetteer"])
    transport_entries = load_transport_lexicon(resources_dir / resource_names["transport_lexicon"])
    gazetteer = Gazetteer(poi_entries, transport_entries)
    transport_rules = TransportRules(transport_entries)
    time_rules = TimeRules.load(resources_dir / resource_names["time_rules"])
    stopwords = load_stopwords(stopwords_path)

    fallback_config = dict(config["poi_fallback"])
    mode = generic_fallback or str(fallback_config.get("mode") or "missing_area_only")
    mode_map = {"off": "never", "missing": "missing_area_only"}
    mode = mode_map.get(mode, mode)
    if mode not in {"never", "missing_area_only", "always"}:
        raise ValueError(f"未知兜底模式: {mode}")
    suffix_rules_path = resources_dir / str(resource_names["poi_suffix_rules"])
    suffix_rules = load_suffix_rules(suffix_rules_path) if suffix_rules_path.exists() else []
    fallback = GenericPOIFallback(suffix_rules, fallback_config, config["area"])
    fallback_enabled = bool(fallback_config.get("enabled", True)) and mode != "never"

    if use_jieba:
        init_jieba(gazetteer)

    area_documents = Counter(record.scenic_area for record in records)
    missing_areas = sorted(
        area for area in area_documents if area and not gazetteer.has_area(area)
    )

    entities: list[dict[str, Any]] = []
    suppressed_rows: list[dict[str, Any]] = []
    boundary_unconfirmed = 0
    for index, record in enumerate(records, start=1):
        text = record.cleaned_text
        area = record.scenic_area
        aliases = build_root_aliases(area, config["area"])
        candidates = []
        has_gazetteer = gazetteer.has_area(area)
        if has_gazetteer:
            candidates.extend(gazetteer.iter_poi_matches(text, area))
            if fallback_enabled and mode == "always":
                candidates.extend(fallback.extract(text, area, jieba_token_spans(text) if use_jieba else None))
        elif fallback_enabled:
            token_spans = jieba_token_spans(text) if use_jieba else None
            candidates.extend(fallback.root_area_candidates(text, area))
            candidates.extend(fallback.extract(text, area, token_spans))
        candidates.extend(transport_rules.extract(text))
        candidates.extend(time_rules.extract(text))
        if stopwords:
            candidates = [
                candidate
                for candidate in candidates
                if not (
                    candidate.method == "jieba_ns"
                    and candidate.surface in stopwords
                )
            ]
        selected, suppressed = gazetteer.resolve_overlaps(candidates)
        tokens = jieba_tokens(text) if use_jieba else None
        for candidate in selected:
            entity = candidate_to_entity(
                candidate, record, text, iteration, tokens, set(aliases)
            )
            errors = validate_entity(entity, text, set(sources))
            if errors:
                raise ValueError(
                    f"实体校验失败 {record.source_record_id} "
                    f"{candidate.surface!r}: {errors}"
                )
            if "jieba_boundary_unconfirmed" in entity["notes"]:
                boundary_unconfirmed += 1
            entities.append(entity)
        for candidate in suppressed:
            suppressed_rows.append(
                {
                    "source_record_id": record.source_record_id,
                    "start": candidate.start,
                    "end": candidate.end,
                    "surface": candidate.surface,
                    "type": candidate.type,
                    "subtype": candidate.subtype,
                    "rule_id": candidate.rule_id,
                }
            )
        if index % 20 == 0 or index == len(records):
            print(f"[extract] {index}/{len(records)} records", flush=True)

    entities.sort(
        key=lambda item: (
            item["source_file"],
            item["source_record_id"],
            item["start"],
            item["end"],
            item["type"],
        )
    )

    warnings = _input_warnings(input_summaries)
    id_groups: dict[str, set[tuple[str, str, int, int, str]]] = defaultdict(set)
    for entity in entities:
        id_groups[entity["entity_id"]].add(
            (
                entity["source_kind"],
                entity["source_record_id"],
                int(entity["start"]),
                int(entity["end"]),
                entity["type"],
            )
        )
    collisions = {key: value for key, value in id_groups.items() if len(value) > 1}
    if collisions:
        warnings.append(
            {
                "code": "entity_id_collision",
                "severity": "warning",
                "count": len(collisions),
                "detail": (
                    "不同来源/记录复用了相同的 source_record_id，导致实体 ID 冲突；"
                    "建议让各来源的 ID 字段保持全局唯一。"
                ),
            }
        )
    for area in missing_areas:
        warnings.append(
            {
                "code": "missing_gazetteer_area",
                "severity": "warning",
                "area": area,
                "documents": area_documents[area],
                "fallback": "generic_suffix" if fallback_enabled else "disabled",
                "detail": (
                    "该景区在 POI 词典中无条目，已使用低置信后缀规则。"
                    if fallback_enabled
                    else "该景区在 POI 词典中无条目，且兜底已关闭，因此不产生 POI。"
                ),
            }
        )
    fallback_stats = _fallback_stats(entities, fallback_config, mode, missing_areas)
    counts = summarize_entities(entities, records, warnings=warnings, fallback_stats=fallback_stats)

    resource_config = {
        "resources_dir": resources_dir.as_posix(),
        "gazetteer_sha256": sha256_file(resources_dir / resource_names["poi_gazetteer"]),
        "transport_sha256": sha256_file(resources_dir / resource_names["transport_lexicon"]),
        "time_rules_sha256": sha256_file(resources_dir / resource_names["time_rules"]),
        "stopwords_sha256": sha256_file(stopwords_path) if stopwords_path and stopwords_path.exists() else "",
        "suffix_rules_sha256": sha256_file(suffix_rules_path) if suffix_rules_path.exists() else "",
        "jieba_version": getattr(jieba, "__version__", "0.42.1"),
        "use_jieba": use_jieba,
        "jieba_boundary_unconfirmed": boundary_unconfirmed,
        "poi_scope": "area",
        "poi_fallback_mode": mode,
        "area_root_suffixes": config["area"].get("root_suffixes", []),
        "stopwords": sorted(stopwords),
        "config_path": config.get("_meta", {}).get("path", ""),
    }
    payload = {
        "schema_version": "task2-entity-1.0",
        "pipeline_version": "task2-extract-1.1",
        "iteration": iteration,
        "generated_at": generated_at or now_iso(),
        "offset_unit": "unicode_codepoint",
        "span_convention": "start_inclusive_end_exclusive",
        "source_scope": sources,
        "areas": sorted({record.scenic_area for record in records}),
        "area_documents": dict(sorted(area_documents.items())),
        "inputs": input_summaries,
        "config": resource_config,
        "counts": counts,
        "suppressed_overlaps": len(suppressed_rows),
        "entities": entities,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json_compact(output_dir / "entities.json", payload)
    write_jsonl(output_dir / "entities.jsonl", entities)
    by_area: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        by_area.setdefault(entity["scenic_area"], []).append(entity)
    area_dir = output_dir / "by_area"
    area_dir.mkdir(parents=True, exist_ok=True)
    expected_files: set[str] = set()
    for area, rows in by_area.items():
        filename = f"{safe_filename(area)}.json"
        expected_files.add(filename)
        write_json_compact(
            area_dir / filename,
            {
                "area": area,
                "iteration": iteration,
                "generated_at": payload["generated_at"],
                "count": len(rows),
                "entities": rows,
            },
        )
    for stale in area_dir.glob("*.json"):
        if stale.name not in expected_files:
            stale.unlink()

    intermediate = resolve_path(config, config["outputs"]["data_dir"]) / "intermediate"
    intermediate.mkdir(parents=True, exist_ok=True)
    suppressed_path = intermediate / f"suppressed_{iteration}.jsonl"
    if suppressed_rows:
        write_jsonl(suppressed_path, suppressed_rows)
    elif suppressed_path.exists():
        suppressed_path.unlink()
    write_json(output_dir / "extract_summary.json", counts)
    print(
        f"[extract] {counts['entities']} entities from {counts['documents']} docs "
        f"-> {output_dir}",
        flush=True,
    )
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="task2 实体识别（POI/交通/时间）")
    add_config_argument(parser)
    parser.add_argument("--input-dir", default=None, help="默认 task2/inputs，缺失时回退 task1/data/processed")
    parser.add_argument("--resources", default=None, help="词典/规则目录；默认取自配置")
    parser.add_argument("--iteration", default="iter2", help="迭代标签，写入实体")
    parser.add_argument("--output-dir", default=None, help="输出目录；默认取自配置")
    parser.add_argument(
        "--sources",
        nargs="+",
        default=None,
        help="要处理的来源名；默认使用配置中的全部来源",
    )
    parser.add_argument("--area", action="append", default=None, help="只处理指定景区，可重复")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 条，便于冒烟")
    parser.add_argument("--record-id", default=None, help="只处理指定记录 ID")
    parser.add_argument("--generated-at", default=None, help="固定时间戳，便于重跑对比")
    parser.add_argument("--no-jieba", action="store_true", help="跳过 jieba 边界校验")
    parser.add_argument("--stopwords", default=None, help="默认 <resources>/stopwords_extraction.txt")
    parser.add_argument("--skip-manifest-check", action="store_true", help="不校验输入 manifest")
    parser.add_argument(
        "--generic-fallback",
        choices=["off", "missing", "always"],
        default=None,
        help="覆盖配置中的通用后缀兜底模式",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    input_dir = ensure_input_dir(args.input_dir, config)
    resources_dir = (
        Path(args.resources).resolve()
        if args.resources
        else resolve_path(config, config["resources"]["dir"])
    )
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else resolve_path(config, config["outputs"]["dir"])
    )
    stopwords_path = (
        Path(args.stopwords).resolve()
        if args.stopwords
        else resources_dir / str(config["resources"]["stopwords"])
    )

    try:
        extract(
            input_dir=input_dir,
            resources_dir=resources_dir,
            output_dir=output_dir,
            iteration=args.iteration,
            sources=args.sources,
            areas=args.area,
            limit=args.limit,
            record_id=args.record_id,
            generated_at=args.generated_at,
            use_jieba=not args.no_jieba,
            stopwords_path=stopwords_path,
            verify_manifest=not args.skip_manifest_check,
            config=config,
            generic_fallback=args.generic_fallback,
        )
    except FileNotFoundError as exc:
        print(
            "错误：缺少 task1 预处理输出或输入文件：\n"
            f"  {exc}\n\n"
            "请准备 task1 的清洗输出，或用 --input-dir 指向包含 *_clean.jsonl 的目录；\n"
            "也可以先运行 task2 的 prepare_inputs.ps1 冻结输入。",
            file=sys.stderr,
            flush=True,
        )
        return 2
    except (ValueError, AssertionError) as exc:
        print(f"错误：{exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
