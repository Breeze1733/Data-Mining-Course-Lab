"""导出实体定义规范表（CSV + Markdown）。"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from io_utils import write_csv


def load_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def markdown(fieldnames: list[str], rows: list[dict[str, str]]) -> str:
    labels = {
        "type": "类型",
        "subtype": "子类型",
        "definition": "定义",
        "left_boundary": "左边界",
        "right_boundary": "右边界",
        "positive_examples": "正例",
        "negative_examples": "反例",
        "confusables": "易混淆",
        "normalization": "归一化",
        "cross_area_policy": "跨景区口径",
    }
    lines = ["# 实体定义规范表", ""]
    lines.append("| " + " | ".join(labels.get(name, name) for name in fieldnames) + " |")
    lines.append("|" + "|".join("---" for _ in fieldnames) + "|")
    for row in rows:
        values = []
        for name in fieldnames:
            value = (row.get(name) or "").replace("|", "\\|").replace("\n", " ")
            values.append(value)
        lines.append("| " + " | ".join(values) + " |")
    lines.append("")
    return "\n".join(lines)


def run(input_path: Path, output_dir: Path) -> None:
    fieldnames, rows = load_rows(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "entity_definition.csv", rows, fieldnames)
    (output_dir / "entity_definition.md").write_text(
        markdown(fieldnames, rows), encoding="utf-8"
    )
    print(f"[definition] {len(rows)} rows -> {output_dir}", flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="task2 实体定义规范表导出")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run(Path(args.input), Path(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
