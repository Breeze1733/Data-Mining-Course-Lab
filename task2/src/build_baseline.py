"""生成 iter1 基线词典/规则。

基线来源按景区逐级选择：当前游客记录的 `matched_pois` → task1 `NODES`
→ iter2 词典 → 通用后缀兜底。这样任意景区集合都能得到一份粗粒度基线。

输出:
    <resources>/iter1_baseline/poi_gazetteer.csv
    <resources>/iter1_baseline/transport_lexicon.csv
    <resources>/iter1_baseline/time_rules.json
    <resources>/iter1_baseline/stopwords_extraction.txt
    <resources>/iter1_baseline/metadata.json

基线故意保留粗粒度节点、裸“换乘”、无票务否定语境、无 00:00 排除，
用于第二轮展示可量化的改进。
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import add_config_argument, load_config, resolve_path, source_kinds
from dictionary import load_poi_gazetteer
from io_utils import (
    ensure_input_dir,
    load_source_records,
    merged_specs,
    read_jsonl,
    write_csv,
)
from paths import REPO_ROOT
from poi_fallback import GenericPOIFallback, load_suffix_rules
from schema import TYPE_POI

TRANSPORT = [
    ("索道", "索道", "索道缆车"),
    ("缆车", "索道", "索道缆车"),
    ("观光车", "观光车", "景区车摆渡车"),
    ("环保车", "观光车", "景区车摆渡车"),
    ("大巴", "大巴", "公路客运"),
    ("公交", "公交", "城市公交"),
    ("高铁", "高铁", "铁路"),
    ("火车", "火车", "铁路"),
    ("地铁", "地铁", "城市公交"),
    ("飞机", "飞机", "航空"),
    ("出租车", "出租车", "自驾出租"),
    ("包车", "包车", "自驾出租"),
    ("自驾", "自驾", "自驾出租"),
    ("步行", "步行", "步行徒步"),
    ("徒步", "徒步", "步行徒步"),
    ("爬山", "爬山", "步行徒步"),
    ("换乘", "换乘", "其他"),
    ("游船", "游船", "水运"),
    ("船", "游船", "水运"),
]

TIME_BASELINE = {
    "version": "time-iter1",
    "patterns": [
        {
            "id": "TIME_CLOCK_COLON",
            "subtype": "时刻",
            "priority": 94,
            "regex": "(?<![\\d:：])(?:[01]?\\d|2[0-3])\\s*[:：]\\s*[0-5]\\d(?!\\d)",
        },
        {
            "id": "TIME_CLOCK_DIAN",
            "subtype": "时刻",
            "priority": 93,
            "regex": "(?<![\\d.])(?:[01]?\\d|2[0-3])\\s*点(?:半|[0-5]?\\d\\s*分|多)?",
        },
        {
            "id": "TIME_DATE_CN",
            "subtype": "日期",
            "priority": 96,
            "regex": "(?:(?:19|20)\\d{2}\\s*年\\s*)?(?:1[0-2]|0?[1-9])\\s*月\\s*(?:3[01]|[12]\\d|0?[1-9])\\s*[日号]",
        },
        {
            "id": "TIME_DATE_ISO",
            "subtype": "日期",
            "priority": 95,
            "regex": "(?<!\\d)(?:19|20)\\d{2}[-/]\\d{1,2}[-/]\\d{1,2}(?!\\d)",
        },
        {
            "id": "TIME_REL_DAY",
            "subtype": "相对日",
            "priority": 91,
            "regex": "(?:第\\s*[一二三四五六七八九十百\\d]{1,3}\\s*[天日]|(?:次|当|第二|第三|最后)\\s*天|Day\\s*0?\\d{1,2}|D\\s*\\d{1,2}|前一天)",
        },
        {
            "id": "TIME_SEASON",
            "subtype": "季节",
            "priority": 89,
            "regex": "(?:[春夏秋冬]\\s*季|春天|夏天|秋天|冬天)",
        },
        {
            "id": "TIME_HOLIDAY",
            "subtype": "节日",
            "priority": 88,
            "regex": "(?:春节|元宵节?|清明节?|劳动节|五一|十一|国庆节?|中秋节?|元旦|端午|暑假|寒假)",
        },
        {
            "id": "TIME_PERIOD",
            "subtype": "时段",
            "priority": 70,
            "regex": "(?:凌晨|清晨|早晨|早上|上午|中午|正午|下午|傍晚|晚上|夜里|夜间)",
        },
        {
            "id": "TIME_DURATION",
            "subtype": "时长",
            "priority": 60,
            "regex": "(?:\\d+(?:\\.\\d+)?\\s*(?:个)?\\s*(?:小时|钟头|分钟|天|晚|个月)|[一二两三四五六七八九十百半]+(?:个)?\\s*(?:半小时|小时|钟头|分钟|天|晚|个月)|个来小时|个把小时|[一1]个多小时|两个半小时)",
        },
    ],
    "exclusions": [],
}


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def load_task1_nodes() -> dict[str, list[str]]:
    source = REPO_ROOT / "task1" / "src" / "expand_ctrip.py"
    if not source.exists():
        return {}
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "NODES" for target in node.targets
        ):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                return {}
            if isinstance(value, dict):
                return {
                    str(area): [str(item) for item in surfaces]
                    for area, surfaces in value.items()
                }
    return {}


def _first_present(row: dict[str, Any], candidates) -> Any:
    for key in candidates or ():
        if key and key in row and row[key] is not None:
            return row[key]
    return None


def _dedupe(items) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def infer_subtype(surface: str, suffix_rules) -> str:
    matches = [
        rule for rule in suffix_rules if rule.target_type == TYPE_POI and surface.endswith(rule.suffix)
    ]
    if matches:
        return max(matches, key=lambda rule: len(rule.suffix)).subtype
    return "景区片区"


def _matched_pois_by_area(
    input_dir: Path, config: dict[str, Any], stopwords: set[str]
) -> dict[str, list[str]]:
    specs = merged_specs(config["input"]["sources"])
    tourist = specs.get("tourist")
    if not tourist:
        return {}
    path = input_dir / str(tourist["file"])
    if not path.exists():
        return {}
    mapping = config["input"]["field_map"]
    area_fields = mapping.get("area", ["scenic_area"])
    poi_fields = mapping.get("matched_pois", ["matched_pois"])
    result: dict[str, list[str]] = {}
    for row in read_jsonl(path):
        area = str(_first_present(row, area_fields) or "")
        if not area:
            continue
        values = _first_present(row, poi_fields) or []
        bucket = result.setdefault(area, [])
        for item in values:
            text = str(item).strip()
            if len(text) >= 2 and text not in stopwords:
                bucket.append(text)
    return {area: _dedupe(values) for area, values in result.items()}


def _gazetteer_by_area(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    result: dict[str, list[str]] = {}
    for entry in load_poi_gazetteer(path):
        result.setdefault(entry.area, []).append(entry.surface)
    return {area: _dedupe(values) for area, values in result.items()}


def _generic_by_area(
    records, config: dict[str, Any], suffix_rules, missing_areas: set[str]
) -> dict[str, list[str]]:
    if not missing_areas or not suffix_rules:
        return {}
    fallback = GenericPOIFallback(suffix_rules, config.get("poi_fallback"), config.get("area"))
    result: dict[str, Counter] = {}
    for record in records:
        if record.scenic_area not in missing_areas:
            continue
        counter = result.setdefault(record.scenic_area, Counter())
        for candidate in fallback.extract(record.cleaned_text, record.scenic_area):
            if candidate.type == TYPE_POI:
                counter[candidate.surface] += 1
    return {
        area: [surface for surface, count in counter.most_common(50) if count >= 2]
        for area, counter in result.items()
    }


def run(
    config: dict[str, Any] | None = None,
    input_dir: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    config = load_config() if config is None else config
    input_dir = input_dir or ensure_input_dir(None, config)
    resources_dir = resolve_path(config, config["resources"]["dir"])
    baseline_dir = output_dir or (
        resources_dir / str(config["resources"]["iter1_baseline_dir"])
    )
    baseline_dir.mkdir(parents=True, exist_ok=True)

    records, _ = load_source_records(
        input_dir,
        source_kinds(config),
        specs=merged_specs(config["input"]["sources"]),
        field_map=config["input"]["field_map"],
        require_area=True,
    )
    areas = sorted({record.scenic_area for record in records if record.scenic_area})
    if not areas:
        raise ValueError("输入中没有可用景区，无法生成 iter1 基线")

    stopwords_path = resources_dir / str(config["resources"]["stopwords"])
    stopwords = (
        {
            line.strip()
            for line in stopwords_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        if stopwords_path.exists()
        else set()
    )
    suffix_rules_path = resources_dir / str(config["resources"]["poi_suffix_rules"])
    suffix_rules = load_suffix_rules(suffix_rules_path) if suffix_rules_path.exists() else []

    sources: dict[str, dict[str, list[str]]] = {
        "matched_pois": _matched_pois_by_area(input_dir, config, stopwords),
        "task1_NODES": {
            area: values
            for area, values in load_task1_nodes().items()
            if area in areas
        },
        "gazetteer": _gazetteer_by_area(resources_dir / str(config["resources"]["poi_gazetteer"])),
    }
    missing_for_generic = {
        area
        for area in areas
        if not any(sources[name].get(area) for name in ("matched_pois", "task1_NODES", "gazetteer"))
    }
    sources["generic"] = _generic_by_area(records, config, suffix_rules, missing_for_generic)

    area_surfaces: dict[str, list[str]] = {}
    area_sources: dict[str, str] = {}
    for area in areas:
        for name in ("matched_pois", "task1_NODES", "gazetteer", "generic"):
            values = sources[name].get(area) or []
            if values:
                area_surfaces[area] = values
                area_sources[area] = name
                break
        else:
            area_surfaces[area] = []
            area_sources[area] = "empty"

    poi_rows = []
    index = 0
    for area in areas:
        for surface in area_surfaces[area]:
            index += 1
            poi_rows.append(
                {
                    "poi_id": f"BASE-POI-{index:03d}",
                    "area": area,
                    "surface": surface,
                    "canonical": surface,
                    "subtype": infer_subtype(surface, suffix_rules),
                    "parent_poi": surface,
                    "source": area_sources[area],
                    "priority": 5,
                    "negative_after": "",
                    "notes": "iter1 baseline",
                }
            )
    write_csv(
        baseline_dir / "poi_gazetteer.csv",
        poi_rows,
        [
            "poi_id",
            "area",
            "surface",
            "canonical",
            "subtype",
            "parent_poi",
            "source",
            "priority",
            "negative_after",
            "notes",
        ],
    )

    transport_rows = []
    for index, (surface, normalized, subtype) in enumerate(TRANSPORT, start=1):
        transport_rows.append(
            {
                "transport_id": f"BASE-TR-{index:03d}",
                "surface": surface,
                "normalized": normalized,
                "subtype": subtype,
                "priority": 5,
                "requires_verb": "false",
                "negative_before": "",
                "negative_after": "",
                "linked_poi": "",
                "notes": "iter1 baseline",
            }
        )
    write_csv(
        baseline_dir / "transport_lexicon.csv",
        transport_rows,
        [
            "transport_id",
            "surface",
            "normalized",
            "subtype",
            "priority",
            "requires_verb",
            "negative_before",
            "negative_after",
            "linked_poi",
            "notes",
        ],
    )

    (baseline_dir / "time_rules.json").write_text(
        json.dumps(TIME_BASELINE, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (baseline_dir / "stopwords_extraction.txt").write_text("", encoding="utf-8")
    for stale in baseline_dir.glob("stopwords_viz.txt"):
        stale.unlink()

    used_sources = sorted(set(area_sources.values()))
    metadata = {
        "derivation": used_sources[0] if len(used_sources) == 1 else "mixed",
        "area_sources": area_sources,
        "areas": areas,
        "nodes": {area: len(values) for area, values in area_surfaces.items()},
        "generated_at": now_iso(),
        "input_dir": input_dir.as_posix(),
    }
    (baseline_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"iter1 baseline written to {baseline_dir} "
        f"(areas={len(areas)}, derivation={metadata['derivation']})",
        flush=True,
    )
    return metadata


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 iter1 基线词典/规则")
    add_config_argument(parser)
    parser.add_argument("--input-dir", default=None)
    parser.add_argument("--output-dir", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    input_dir = ensure_input_dir(args.input_dir, config) if args.input_dir else None
    output_dir = Path(args.output_dir).resolve() if args.output_dir else None
    run(config, input_dir, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
