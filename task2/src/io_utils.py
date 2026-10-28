"""task2 的输入适配与序列化工具。

输入来源与字段映射由 `config.json` 决定（见 `config.py`）。默认快照位于
`task2/inputs/`，缺失时可回退到 `task1/data/processed/`。记录条数、景区集合
都从实际数据读取，不在代码中假设。

输出:
    JSON 使用 UTF-8、ensure_ascii=False；CSV 使用 UTF-8 BOM，方便 Excel 打开。
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from paths import repo_relative

DEFAULT_SOURCE_SPECS: dict[str, dict[str, Any]] = {
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
}

DEFAULT_FIELD_MAP: dict[str, list[str]] = {
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
}

# 兼容旧调用：实际来源由 config 决定。
SOURCE_SPECS = DEFAULT_SOURCE_SPECS

_WINDOWS_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_DEVICE_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class SourceRecord:
    """一篇待识别文本，保留 task1 的来源信息。"""

    source_kind: str
    source_file: str
    source_line: int
    source_record_id: str
    source_id_field: str
    parent_record_id: str
    scenic_area: str
    source_platform: str
    source_url: str
    title: str
    cleaned_text: str
    task1_text_sha256: str
    ordered_route: bool | None = None
    published_at: str = ""
    scope_note: str = ""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def write_json_compact(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temp.replace(path)


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
    temp.replace(path)


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key, "")) for key in fieldnames})
    temp.replace(path)


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, ensure_ascii=False)
    text = str(value)
    # 防止 Excel 把文本当公式执行
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _first_present(row: Mapping[str, Any], candidates: Iterable[str] | None) -> Any:
    for key in candidates or ():
        if key and key in row and row[key] is not None:
            return row[key]
    return None


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def safe_filename(value: str, max_len: int = 80) -> str:
    """把任意景区名转成安全的单层文件名（保留中文）。"""
    text = _WINDOWS_BAD_CHARS.sub("_", str(value)).strip().rstrip(". ")
    if not text:
        text = "area_" + sha256_text(str(value))[:8]
    if text.split(".")[0].lower() in _DEVICE_NAMES:
        text = "_" + text
    return text[:max_len]


def merged_specs(specs: Mapping[str, Mapping[str, Any]] | None) -> dict[str, dict[str, Any]]:
    base = {kind: dict(spec) for kind, spec in DEFAULT_SOURCE_SPECS.items()}
    for kind, spec in (specs or {}).items():
        merged = dict(base.get(kind, {}))
        merged.update(dict(spec))
        base[kind] = merged
    return base


def load_source_records(
    input_dir: Path,
    sources: Sequence[str] | None = None,
    areas: Sequence[str] | None = None,
    specs: Mapping[str, Mapping[str, Any]] | None = None,
    field_map: Mapping[str, Sequence[str]] | None = None,
    require_area: bool = False,
) -> tuple[list[SourceRecord], list[dict[str, Any]]]:
    """读取配置中的 JSONL 来源，返回 (records, input_summaries)。

    缺失的 `required=false` 来源会返回 `status="missing_optional"` 的摘要，
    而不是抛错；记录级问题计入摘要，由调用方决定是否告警。
    """
    input_dir = input_dir.resolve()
    all_specs = merged_specs(specs)
    kinds = list(sources) if sources is not None else list(all_specs)
    mapping = {**DEFAULT_FIELD_MAP, **dict(field_map or {})}
    records: list[SourceRecord] = []
    summaries: list[dict[str, Any]] = []
    first_missing: Path | None = None

    for source_kind in kinds:
        spec = all_specs.get(source_kind)
        if spec is None:
            raise ValueError(f"未知来源: {source_kind}")
        path = input_dir / str(spec["file"])
        summary: dict[str, Any] = {
            "source_kind": source_kind,
            "id_field": str(spec.get("id_field") or ""),
            "path": repo_relative(path),
            "status": "ok",
            "records": 0,
            "raw_records": 0,
            "skipped_accepted": 0,
            "skipped_missing_area": 0,
            "skipped_missing_id": 0,
            "skipped_empty_text": 0,
        }
        if not path.exists():
            if _as_bool(spec.get("required")):
                raise FileNotFoundError(path)
            if first_missing is None:
                first_missing = path
            summary["status"] = "missing_optional"
            summaries.append(summary)
            continue

        rows = read_jsonl(path)
        summary["raw_records"] = len(rows)
        summary["sha256"] = sha256_file(path)
        accept_field = spec.get("accept_field")
        platform_field = spec.get("platform_field")

        for line_number, row in enumerate(rows, start=1):
            if accept_field and accept_field in row and not _as_bool(row.get(accept_field)):
                summary["skipped_accepted"] += 1
                continue
            area = _text(_first_present(row, mapping["area"]))
            if areas and area not in areas:
                continue
            if require_area and not area:
                summary["skipped_missing_area"] += 1
                continue
            record_id = _text(_first_present(row, [str(spec["id_field"])]))
            if not record_id:
                summary["skipped_missing_id"] += 1
                continue
            text = _text(_first_present(row, mapping["text"]))
            if not text:
                summary["skipped_empty_text"] += 1
                continue

            platform = _text(_first_present(row, mapping["platform"]))
            if not platform and platform_field:
                platform = _text(row.get(str(platform_field)))
            if not platform:
                platform = "官方" if source_kind != "tourist" else ""

            ordered_raw = _first_present(row, mapping["ordered_route"])
            records.append(
                SourceRecord(
                    source_kind=source_kind,
                    source_file=repo_relative(path),
                    source_line=line_number,
                    source_record_id=record_id,
                    source_id_field=str(spec["id_field"]),
                    parent_record_id=_text(
                        _first_present(row, mapping["parent_record_id"])
                    ),
                    scenic_area=area,
                    source_platform=platform,
                    source_url=_text(_first_present(row, mapping["url"])),
                    title=_text(_first_present(row, mapping["title"])),
                    cleaned_text=text,
                    task1_text_sha256=_text(
                        _first_present(row, mapping["text_sha256"])
                    ),
                    ordered_route=None if ordered_raw is None else _as_bool(ordered_raw),
                    published_at=_text(_first_present(row, mapping["published_at"])),
                    scope_note=_text(_first_present(row, mapping["scope_note"])),
                )
            )
            summary["records"] += 1
        summaries.append(summary)
    if not records and first_missing is not None and len(summaries) == len(kinds):
        # 本次请求的来源文件一个都不存在：按“缺少输入”处理，而不是“没有匹配记录”。
        if all(item.get("status") == "missing_optional" for item in summaries):
            raise FileNotFoundError(first_missing)
    return records, summaries


def load_manifest(input_dir: Path, manifest_name: str = "manifest.json") -> dict[str, Any] | None:
    manifest = input_dir.resolve() / manifest_name
    if not manifest.exists():
        return None
    return json.loads(manifest.read_text(encoding="utf-8"))


def verify_input_manifest(
    input_dir: Path,
    sources: Sequence[str] | None = None,
    specs: Mapping[str, Mapping[str, Any]] | None = None,
    manifest_name: str = "manifest.json",
) -> list[dict[str, Any]]:
    """若存在 manifest.json，校验本次使用来源的 SHA-256。"""
    input_dir = input_dir.resolve()
    all_specs = merged_specs(specs)
    kinds = list(sources) if sources is not None else list(all_specs)
    manifest = load_manifest(input_dir, manifest_name)
    expected: dict[str, str] = {}
    if manifest:
        for item in manifest.get("files", []):
            name = str(item.get("name") or "")
            digest = str(item.get("sha256") or "")
            if name and digest:
                expected[name] = digest

    summaries: list[dict[str, Any]] = []
    for source_kind in kinds:
        spec = all_specs[source_kind]
        name = str(spec["file"])
        path = input_dir / name
        if not path.exists():
            if _as_bool(spec.get("required")):
                raise FileNotFoundError(path)
            summaries.append(
                {
                    "source_kind": source_kind,
                    "path": repo_relative(path),
                    "status": "missing_optional",
                    "records": 0,
                }
            )
            continue
        actual = sha256_file(path)
        if name in expected and expected[name] != actual:
            raise ValueError(
                f"输入快照 SHA-256 不匹配: {path}\n"
                f"manifest={expected[name]}\nactual  ={actual}\n"
                "请重新运行 prepare_inputs.ps1 更新快照。"
            )
        summaries.append(
            {
                "source_kind": source_kind,
                "path": repo_relative(path),
                "status": "ok",
                "sha256": actual,
                "records": sum(1 for _ in read_jsonl(path)),
            }
        )
    return summaries


def ensure_input_dir(
    explicit: str | Path | None,
    config: Mapping[str, Any] | None = None,
) -> Path:
    """解析输入目录：显式参数 > init 配置 > 回退目录。"""
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()

    from paths import DEFAULT_INPUT_DIR, TASK1_PROCESSED

    if config is not None:
        from config import resolve_path

        specs = merged_specs(config.get("input", {}).get("sources"))
        candidates = [resolve_path(config, config["input"]["dir"])]
        candidates.extend(
            resolve_path(config, item)
            for item in config["input"].get("fallback_dirs", [])
        )
        for candidate in candidates:
            if any((candidate / spec["file"]).exists() for spec in specs.values()):
                if candidate != candidates[0]:
                    print(
                        f"[提示] 默认输入目录不可用，改为读取 {candidate}；"
                        "建议先运行 prepare_inputs.ps1 冻结输入。",
                        flush=True,
                    )
                return candidate.resolve()
        return candidates[0].resolve()

    if any((DEFAULT_INPUT_DIR / spec["file"]).exists() for spec in DEFAULT_SOURCE_SPECS.values()):
        return DEFAULT_INPUT_DIR.resolve()
    if any((TASK1_PROCESSED / spec["file"]).exists() for spec in DEFAULT_SOURCE_SPECS.values()):
        print(
            "[提示] task2/inputs 快照不存在，直接读取 task1/data/processed；"
            "建议先运行 prepare_inputs.ps1 冻结输入。",
            flush=True,
        )
        return TASK1_PROCESSED.resolve()
    return DEFAULT_INPUT_DIR.resolve()
