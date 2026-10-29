"""task2 运行配置：加载、合并、路径解析与来源规格。

优先级：CLI 参数 > config.json > 内置默认值。
未提供 --config 且 task2/config.json 不存在时，使用内置默认值（与当前数据一致）。
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Iterable

from paths import CONFIG_FILE, TASK2_ROOT

DEFAULTS: dict[str, Any] = {
    "schema_version": "task2-config-1.0",
    "input": {
        "dir": "inputs",
        "fallback_dirs": ["../task1/data/processed"],
        "manifest": "manifest.json",
        "quality_report": "quality_report.json",
        "sources": {
            "tourist": {
                "file": "tourist_routes_clean.jsonl",
                "id_field": "record_id",
                "platform_field": "source_platform",
                "accept_field": None,
                "label": "游客游记",
                "required": False,
            },
            "official_route": {
                "file": "official_routes_clean.jsonl",
                "id_field": "route_id",
                "platform_field": None,
                "accept_field": None,
                "label": "官方线路",
                "required": False,
            },
            "official_document": {
                "file": "official_documents_clean.jsonl",
                "id_field": "evidence_id",
                "platform_field": None,
                "accept_field": "accepted",
                "label": "官方文档",
                "required": False,
            },
        },
        "field_map": {
            "area": ["scenic_area"],
            "text": ["cleaned_text"],
            "text_sha256": ["text_sha256"],
            "platform": ["source_platform"],
            "url": ["source_url"],
            "title": ["title", "page_title"],
            "parent_record_id": ["source_record_id"],
            "ordered_route": ["ordered_route"],
            "published_at": ["published_at"],
            "scope_note": ["scope_note"],
            "matched_pois": ["matched_pois"],
        },
    },
    "resources": {
        "dir": "resources",
        "poi_gazetteer": "poi_gazetteer.csv",
        "transport_lexicon": "transport_lexicon.csv",
        "time_rules": "time_rules.json",
        "stopwords": "stopwords_extraction.txt",
        "entity_definition": "entity_definition.csv",
        "poi_suffix_rules": "poi_suffix_rules.csv",
        "iter1_baseline_dir": "iter1_baseline",
    },
    "outputs": {
        "dir": "outputs",
        "data_dir": "data",
        "logs_dir": "logs",
        "iter1_dir": "data/iterations/iter1",
        "charts_subdir": "charts",
        "qc_subdir": "qc",
        "manifest": "outputs/run_manifest.json",
    },
    "scope": {
        "default": "analysis",
        "scopes": {
            "analysis": ["tourist", "official_route"],
            "all": ["tourist", "official_route", "official_document"],
            "tourist": ["tourist"],
            "official_route": ["official_route"],
            "official_document": ["official_document"],
        },
    },
    "top_n": {
        "poi": 20,
        "transport": 20,
        "time": 20,
        "duration": 15,
        "per_area": 10,
        "max_area_panels": 12,
    },
    "sampling": {
        "seed": 42,
        "quotas": {"tourist": 8, "official_route": 6, "official_document": 6},
        "boundary_limit": 12,
    },
    "poi_fallback": {
        "enabled": True,
        "mode": "missing_area_only",
        "confidence": 0.55,
        "rank_base": 20,
        "min_prefix_chars": 2,
        "max_prefix_chars": 8,
        "use_jieba_boundary": True,
    },
    "area": {
        "root_suffixes": ["风景区", "景区", "旅游区", "名胜区", "国家公园", "公园"],
        "aliases": {},
        "require_nonempty": True,
    },
    "visualization": {
        "font_candidates": [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/simsun.ttc",
        ],
        "font_env_var": "TASK2_FONT",
        "dpi": 180,
        "wordcloud_max_words": 120,
        "wordcloud_random_state": 42,
    },
    "comparison": {
        "coarse_subtypes": ["景区片区"],
        "ticket_words": ["票", "票价", "购票", "买票"],
        "ticket_context_radius": 3,
        "noise_rules": [
            {
                "id": "standalone_huanzheng",
                "label": "裸换乘",
                "type": "交通方式",
                "surface_regex": "^换乘$",
            },
            {
                "id": "video_00_entities",
                "label": "00:00 噪声",
                "type": "时间节点",
                "surface_regex": "^00:00$",
            },
        ],
    },
    "qc": {
        "seed": 42,
        "quotas": {"tourist": 8, "official_route": 6, "official_document": 6},
        "boundary_limit": 12,
        "type_confusion": {
            "transport_heads": "索道|缆车|观光车|大巴|步行|徒步|游船|轮渡",
            "ticket_words": "票|票价|购票|买票",
        },
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """加载配置；不存在时返回内置默认值。"""
    if path:
        config_path = Path(path)
        if not config_path.is_absolute():
            config_path = (Path.cwd() / config_path).resolve()
    else:
        config_path = CONFIG_FILE

    raw: dict[str, Any] = {}
    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"配置文件必须是 JSON 对象: {config_path}")

    config = _deep_merge(DEFAULTS, raw)
    base_dir = config_path.parent if config_path.exists() else TASK2_ROOT
    config["_meta"] = {
        "path": str(config_path) if config_path.exists() else "",
        "dir": str(base_dir.resolve()),
    }
    errors = validate_config(config)
    if errors:
        raise ValueError("配置错误: " + "; ".join(errors))
    return config


def resolve_path(config: dict[str, Any], value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    base = Path(config.get("_meta", {}).get("dir") or TASK2_ROOT)
    return (base / path).resolve()


def source_specs(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return config["input"]["sources"]


def source_kinds(config: dict[str, Any]) -> list[str]:
    return list(config["input"]["sources"])


def source_labels(config: dict[str, Any]) -> dict[str, str]:
    return {
        kind: str(spec.get("label") or kind)
        for kind, spec in config["input"]["sources"].items()
    }


def scope_sources(config: dict[str, Any], scope: str) -> set[str]:
    """把 scope 名或逗号分隔的来源名解析成 source_kind 集合。"""
    scopes = config["scope"]["scopes"]
    if scope in scopes:
        return set(scopes[scope])
    return {part.strip() for part in scope.split(",") if part.strip()}


def validate_config(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    sources = config.get("input", {}).get("sources", {})
    if not sources:
        errors.append("input.sources 不能为空")
    for kind, spec in sources.items():
        if not kind or not kind.replace("_", "").isalnum():
            errors.append(f"非法 source_kind: {kind!r}")
        if not spec.get("file"):
            errors.append(f"{kind}.file 不能为空")
        if not spec.get("id_field"):
            errors.append(f"{kind}.id_field 不能为空")
    mode = config.get("poi_fallback", {}).get("mode")
    if mode not in {"never", "missing_area_only", "always"}:
        errors.append(f"poi_fallback.mode 非法: {mode!r}")
    return errors


def add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None, help="配置文件路径；默认 task2/config.json")


def resolved_paths(
    config: dict[str, Any], input_dir: str | Path | None = None
) -> dict[str, str]:
    """供 PowerShell/其他脚本复用的解析后路径。"""
    resources_dir = resolve_path(config, config["resources"]["dir"])
    outputs_dir = resolve_path(config, config["outputs"]["dir"])
    data_dir = resolve_path(config, config["outputs"]["data_dir"])
    if input_dir:
        chosen = Path(input_dir)
        if not chosen.is_absolute():
            chosen = (Path.cwd() / chosen).resolve()
    else:
        chosen = resolve_path(config, config["input"]["dir"])
        if not _has_any_source(chosen, config):
            for fallback in config["input"].get("fallback_dirs", []):
                candidate = resolve_path(config, fallback)
                if _has_any_source(candidate, config):
                    chosen = candidate
                    break
    return {
        "config": config.get("_meta", {}).get("path", ""),
        "input_dir": chosen.resolve().as_posix(),
        "resources_dir": resources_dir.as_posix(),
        "outputs_dir": outputs_dir.as_posix(),
        "data_dir": data_dir.as_posix(),
        "logs_dir": resolve_path(config, config["outputs"]["logs_dir"]).as_posix(),
        "iter1_dir": resolve_path(config, config["outputs"]["iter1_dir"]).as_posix(),
        "charts_dir": (outputs_dir / config["outputs"]["charts_subdir"]).as_posix(),
        "qc_dir": (outputs_dir / config["outputs"]["qc_subdir"]).as_posix(),
        "manifest": resolve_path(config, config["outputs"]["manifest"]).as_posix(),
        "iter1_baseline_dir": (
            resources_dir / config["resources"]["iter1_baseline_dir"]
        ).as_posix(),
    }


def _has_any_source(directory: Path, config: dict[str, Any]) -> bool:
    return any((directory / spec["file"]).exists() for spec in source_specs(config).values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="task2 配置工具")
    add_config_argument(parser)
    parser.add_argument("--input-dir", default=None)
    parser.add_argument("--print-paths", action="store_true")
    parser.add_argument("--print-sources", action="store_true")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.print_sources:
        payload = source_specs(config)
    else:
        payload = resolved_paths(config, args.input_dir)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
