"""运行结果回归校验（只读）。

检查偏移、结构、景区覆盖、兜底告警、与改造前快照的计数差异、运行清单完整性，
并扫描文档/源码中是否残留固定结果数字或固定景区名。

用法:
    python src/verify_outputs.py --baseline data/regression_baseline_xxx \
        --current outputs --inputs inputs --config config.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from config import add_config_argument, load_config, resolve_path, source_kinds
from dictionary import Gazetteer, load_poi_gazetteer, load_transport_lexicon
from io_utils import (
    load_source_records,
    merged_specs,
    safe_filename,
    sha256_file,
)
from qc_entities import (
    check_cross_type_overlaps,
    check_duplicates,
    check_schema_and_offsets,
)

BANNED_NUMBERS = re.compile(
    r"(?<!\d)(145|208|14188|8085|1981|4122|11850|13124|5472|3827|4889)(?!\d)"
    r"|41/42|0\.(?:3873|0482|9471|8544)"
)
AREA_NAMES = ("黄山", "九寨沟", "颐和园")


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _flat_counts(summary: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {
        "documents": summary.get("documents"),
        "entities": summary.get("entities"),
        "time_nodes_excluding_duration": summary.get("time_nodes_excluding_duration"),
    }
    for group in ("by_type", "by_source_kind", "by_area"):
        for key, value in (summary.get(group) or {}).items():
            values[f"{group}.{key}"] = value
    return values


def compare_to_baseline(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    problems = []
    before = _flat_counts(baseline)
    after = _flat_counts(current)
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            problems.append(f"回归差异 {key}: baseline={before.get(key)} current={after.get(key)}")
    return problems


def check_coverage(
    entities_payload: dict[str, Any],
    current_dir: Path,
    input_dir: Path,
    config: dict[str, Any],
) -> list[str]:
    problems = []
    records, _ = load_source_records(
        input_dir,
        source_kinds(config),
        specs=merged_specs(config["input"]["sources"]),
        field_map=config["input"]["field_map"],
        require_area=False,
    )
    areas = sorted({record.scenic_area for record in records if record.scenic_area})
    entity_areas = {entity["scenic_area"] for entity in entities_payload["entities"]}
    expected = {
        f"{safe_filename(area)}.json" for area in areas if area in entity_areas
    }
    area_dir = current_dir / "by_area"
    present = {path.name for path in area_dir.glob("*.json")} if area_dir.exists() else set()
    missing = expected - present
    stale = present - expected
    if missing:
        problems.append(f"缺少 by_area 文件: {sorted(missing)}")
    if stale:
        problems.append(f"by_area 存在本次输入之外的残留文件: {sorted(stale)}")
    return problems


def check_fallback(
    entities_payload: dict[str, Any],
    resources_dir: Path,
    config: dict[str, Any],
) -> list[str]:
    problems = []
    names = config["resources"]
    gazetteer = Gazetteer(
        load_poi_gazetteer(resources_dir / str(names["poi_gazetteer"])),
        load_transport_lexicon(resources_dir / str(names["transport_lexicon"])),
    )
    warnings = entities_payload.get("counts", {}).get("warnings", [])
    warned_areas = {
        item.get("area") for item in warnings if item.get("code") == "missing_gazetteer_area"
    }
    areas = {
        entity["scenic_area"]
        for entity in entities_payload["entities"]
        if entity.get("scenic_area")
    }
    for area in sorted(areas):
        if not gazetteer.has_area(area) and area not in warned_areas:
            problems.append(f"景区 {area} 无词典但缺少 missing_gazetteer_area 警告")
    for entity in entities_payload["entities"]:
        if entity.get("method") == "generic_suffix" and not entity.get("fallback"):
            problems.append(f"兜底实体缺少 fallback 标记: {entity['surface']}")
    return problems


def check_manifest(current_dir: Path, manifest_path: Path) -> list[str]:
    problems = []
    manifest = load_json(manifest_path)
    if manifest is None:
        return [f"缺少运行清单: {manifest_path}"]
    listed = {item["path"]: item["sha256"] for item in manifest.get("outputs", [])}
    exclude = {manifest_path.name}
    for path in sorted(current_dir.rglob("*")):
        if not path.is_file() or path.name in exclude or path.name.endswith(".tmp"):
            continue
        relative = path.relative_to(current_dir).as_posix()
        if relative not in listed:
            problems.append(f"清单未收录输出: {relative}")
        elif listed[relative] != sha256_file(path):
            problems.append(f"清单哈希不一致: {relative}")
    return problems


def check_docs_and_sources(task2_root: Path) -> list[str]:
    problems = []
    docs = [
        task2_root / "readme.md",
        task2_root / "inputs" / "README.md",
    ]
    for path in docs:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for match in BANNED_NUMBERS.finditer(text):
            problems.append(f"{path.name} 残留固定结果数字: {match.group(0)}")
        for area in AREA_NAMES:
            if area in text:
                problems.append(f"{path.name} 残留固定景区名: {area}")
    for path in sorted((task2_root / "src").glob("*.py")):
        if path.name.startswith("test_") or path.name == "verify_outputs.py":
            continue
        text = path.read_text(encoding="utf-8")
        for area in AREA_NAMES:
            if area in text:
                problems.append(f"{path.name} 残留固定景区名: {area}")
    return problems


def run(
    baseline_dir: Path | None,
    current_dir: Path,
    input_dir: Path,
    config: dict[str, Any],
) -> tuple[bool, list[str], list[str]]:
    hard: list[str] = []
    warnings: list[str] = []
    payload = load_json(current_dir / "entities.json")
    if payload is None:
        return False, [f"缺少 entities.json: {current_dir}"], warnings

    texts, _ = load_source_records(
        input_dir,
        source_kinds(config),
        specs=merged_specs(config["input"]["sources"]),
        field_map=config["input"]["field_map"],
        require_area=False,
    )
    text_map = {
        (record.source_kind, record.source_record_id): record.cleaned_text
        for record in texts
    }
    allowed = set(source_kinds(config))
    schema_errors, missing = check_schema_and_offsets(payload["entities"], text_map, allowed)
    offset_invalid = sum(
        1 for error in schema_errors if error.startswith("offset_") or error == "offset_surface_mismatch"
    )
    if offset_invalid:
        hard.append(f"偏移错误: {offset_invalid}")
    if missing:
        hard.append(f"找不到原文的记录: {len(missing)}")
    duplicates = check_duplicates(payload["entities"])
    overlaps = check_cross_type_overlaps(payload["entities"])
    if duplicates:
        hard.append(f"重复 span: {len(duplicates)}")
    if overlaps:
        hard.append(f"跨类型重叠: {len(overlaps)}")

    hard.extend(check_coverage(payload, current_dir, input_dir, config))
    resources_dir = resolve_path(config, config["resources"]["dir"])
    hard.extend(check_fallback(payload, resources_dir, config))

    manifest_path = resolve_path(config, config["outputs"]["manifest"])
    if manifest_path.exists():
        hard.extend(check_manifest(current_dir, manifest_path))
    else:
        warnings.append(f"未找到运行清单: {manifest_path}")

    if baseline_dir is not None:
        baseline_summary = load_json(baseline_dir / "extract_summary.json")
        current_summary = load_json(current_dir / "extract_summary.json")
        if baseline_summary and current_summary:
            hard.extend(compare_to_baseline(baseline_summary, current_summary))
        else:
            warnings.append("缺少 baseline/current extract_summary.json，跳过计数回归比较")

    iter1 = load_json(current_dir / "iterations" / "iter1_summary.json")
    iter2 = load_json(current_dir / "iterations" / "iter2_summary.json")
    if iter1 and iter2:
        if iter2.get("total_entities", 0) < iter1.get("total_entities", 0):
            warnings.append("iter2 实体总数低于 iter1，请检查词典/规则变化")
        if iter2.get("coarse_poi_share", 0) > iter1.get("coarse_poi_share", 0):
            warnings.append("iter2 粗粒度 POI 占比高于 iter1")

    hard.extend(check_docs_and_sources(current_dir.parent))
    return (not hard), hard, warnings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="task2 运行结果回归校验")
    add_config_argument(parser)
    parser.add_argument("--baseline", default=None, help="改造前 outputs 快照目录")
    parser.add_argument("--current", required=True)
    parser.add_argument("--inputs", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    ok, hard, warnings = run(
        Path(args.baseline).resolve() if args.baseline else None,
        Path(args.current).resolve(),
        Path(args.inputs).resolve(),
        config,
    )
    for item in hard:
        print(f"[FAIL] {item}")
    for item in warnings:
        print(f"[WARN] {item}")
    if ok:
        print("[verify] OK")
        return 0
    print(f"[verify] {len(hard)} 个问题")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
