"""生成运行清单：输入/输出的 SHA-256、大小、时间与配置。

输入与输出文件通过目录扫描发现，不依赖固定文件名或固定景区数量。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import add_config_argument, load_config
from io_utils import sha256_file, write_json


def collect_files(root: Path, exclude: set[str] | None = None) -> list[dict]:
    excluded = exclude or set()
    items = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in excluded or path.name.endswith(".tmp"):
            continue
        items.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    items.sort(key=lambda item: item["path"])
    return items


def run(
    outputs_dir: Path,
    inputs_dir: Path,
    output_path: Path,
    config: dict | None = None,
    config_path: str | None = None,
) -> dict:
    config = load_config() if config is None else config
    manifest_name = str(config["input"].get("manifest") or "manifest.json")
    outputs_manifest = output_path.resolve()
    if outputs_dir.resolve() == outputs_manifest.parent:
        exclude_outputs = {outputs_manifest.name}
    else:
        exclude_outputs = set()

    manifest = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(
            timespec="seconds"
        ),
        "inputs_dir": inputs_dir.as_posix(),
        "outputs_dir": outputs_dir.as_posix(),
        "config_path": config_path or config.get("_meta", {}).get("path", ""),
        "config_sha256": (
            sha256_file(Path(config_path or config.get("_meta", {}).get("path")))
            if (config_path or config.get("_meta", {}).get("path"))
            else ""
        ),
        "inputs_manifest": None,
        "inputs": [],
        "outputs": [],
    }
    input_manifest = inputs_dir / manifest_name
    if input_manifest.exists():
        manifest["inputs_manifest"] = json.loads(
            input_manifest.read_text(encoding="utf-8")
        )
    manifest["inputs"] = collect_files(inputs_dir, exclude={manifest_name})

    manifest["outputs"] = collect_files(outputs_dir, exclude=exclude_outputs)

    summary_path = outputs_dir / "extract_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        manifest["warnings"] = summary.get("warnings", [])
        manifest["poi_fallback"] = summary.get("poi_fallback", {})

    write_json(output_path, manifest)
    print(f"[manifest] {len(manifest['outputs'])} outputs -> {output_path}", flush=True)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="task2 运行清单")
    add_config_argument(parser)
    parser.add_argument("--outputs", required=True)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    run(
        Path(args.outputs),
        Path(args.inputs),
        Path(args.output),
        config=config,
        config_path=args.config,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
