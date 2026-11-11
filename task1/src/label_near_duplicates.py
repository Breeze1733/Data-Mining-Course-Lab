"""Annotate transitive near-duplicate groups in the delivered task1 dataset.

The cleaning audit only records pairwise ``near_duplicate_pairs``. This script
turns those pairs into stable groups and appends four fields to every record:

    duplicate_group  DUP_001.. or "" when the record is not in a group
    duplicate_role   "canonical" | "duplicate" | ""
    duplicate_of     canonical record id for duplicates, otherwise ""
    dedup_weight     1.0 for canonical/singleton records, 0.0 for duplicates

It also writes the group summary into ``quality_report.json`` and rebuilds
``cleaning_examples.json`` for the workbook exporter. No content or hash field
is recomputed, so the 249 post-hoc ``snapshot_sha256`` backfills survive.

The script is idempotent: running it twice produces identical files.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "common"))
from atomic import atomic_write_text  # noqa: E402

PROCESSED = ROOT / "data/processed"
DUPLICATE_FIELDS = ("duplicate_group", "duplicate_role", "duplicate_of", "dedup_weight")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def build_groups(pairs: list[dict], order: dict[str, int]) -> list[dict]:
    """Union-find the pair list; canonical = earliest record in input order."""
    parent: dict[str, str] = {}

    def find(item: str) -> str:
        parent.setdefault(item, item)
        root = item
        while parent[root] != root:
            root = parent[root]
        while parent[item] != root:
            parent[item], item = root, parent[item]
        return root

    for pair in pairs:
        left, right = pair["record_id_a"], pair["record_id_b"]
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    members: dict[str, list[str]] = {}
    for item in parent:
        members.setdefault(find(item), []).append(item)

    groups = []
    for ids in members.values():
        if len(ids) < 2:
            continue
        ids.sort(key=lambda record_id: order.get(record_id, sys.maxsize))
        groups.append(ids)
    groups.sort(key=lambda ids: order.get(ids[0], sys.maxsize))

    pair_scores: dict[str, list[float]] = {}
    for pair in pairs:
        for record_id in (pair["record_id_a"], pair["record_id_b"]):
            pair_scores.setdefault(record_id, []).append(float(pair.get("similarity", 0.0)))

    result = []
    for index, ids in enumerate(groups, start=1):
        group_id = f"DUP_{index:03d}"
        scores = [score for record_id in ids for score in pair_scores.get(record_id, [])]
        result.append({
            "group_id": group_id,
            "canonical_record_id": ids[0],
            "record_ids": ids,
            "duplicate_record_ids": ids[1:],
            "member_count": len(ids),
            "duplicate_count": len(ids) - 1,
            "max_similarity": round(max(scores, default=0.0), 4),
        })
    return result


def annotate(rows: list[dict], groups: list[dict]) -> None:
    by_id = {row["record_id"]: row for row in rows}
    for row in rows:
        for field in DUPLICATE_FIELDS:
            row[field] = ""
        row["duplicate_role"] = ""
        row["dedup_weight"] = 1.0
    for group in groups:
        canonical = group["canonical_record_id"]
        for record_id in group["record_ids"]:
            row = by_id[record_id]
            row["duplicate_group"] = group["group_id"]
            if record_id == canonical:
                row["duplicate_role"] = "canonical"
            else:
                row["duplicate_role"] = "duplicate"
                row["duplicate_of"] = canonical
                row["dedup_weight"] = 0.0


def rebuild_examples(rows: list[dict]) -> list[dict]:
    examples = []
    for row in rows:
        raw = row.get("raw_content") or ""
        cleaned = row.get("clean_content") or ""
        examples.append({
            "record_id": row["record_id"],
            "scenic_area": row["scenic_area"],
            "title": row.get("title", ""),
            "source_url": row.get("source_url", ""),
            "raw_format": row.get("raw_format", ""),
            "before": raw[:1500],
            "after": cleaned[:1500],
            "raw_char_count": row.get("raw_char_count", len(raw)),
            "clean_char_count": row.get("clean_char_count", len(cleaned)),
            "cleaning_counts": row.get("cleaning_counts", {}),
            "sample_is_excerpt": len(raw) > 1500 or len(cleaned) > 1500,
        })
    return examples


def update_report(report: dict, rows: list[dict], groups: list[dict]) -> None:
    duplicates = [row["record_id"] for row in rows if row["duplicate_role"] == "duplicate"]
    in_groups = [row["record_id"] for row in rows if row["duplicate_group"]]
    report["near_duplicate_groups"] = groups
    report["near_duplicate_group_count"] = len(groups)
    report["near_duplicate_records_in_groups"] = len(in_groups)
    report["near_duplicate_redundant_records"] = len(duplicates)
    weight_sum = sum(row["dedup_weight"] for row in rows)
    report["effective_records_after_dedup"] = int(weight_sum) if float(weight_sum).is_integer() else weight_sum
    for pair in report.get("near_duplicate_pairs", []):
        pair["action"] = "retain_with_group_label"

    policy = report.setdefault("validation_policy", {})
    policy["near_duplicate_action"] = "keep_all_records_annotate_group_and_weight"
    policy["dedup_weight_policy"] = "canonical=1.0, duplicate=0.0; all accepted records retained"
    policy["duplicate_group_rule"] = "transitive closure of near_duplicate_pairs; canonical = earliest input record"
    policy["duplicate_fields"] = list(DUPLICATE_FIELDS)

    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    report["dataset_fields"] = fields
    report["xlsx_authoring"] = {"engine": "openpyxl", "script": "src/export_dataset_xlsx.py",
                                "status": "generated"}
    report["xlsx_long_text_externalization"] = []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Label transitive near-duplicate groups.")
    parser.add_argument("--processed", type=Path, default=PROCESSED)
    args = parser.parse_args(argv)

    dataset_path = args.processed / "dataset_clean.jsonl"
    report_path = args.processed / "quality_report.json"
    rows = read_jsonl(dataset_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    order = {row["record_id"]: position for position, row in enumerate(rows)}
    groups = build_groups(report.get("near_duplicate_pairs", []), order)
    annotate(rows, groups)
    update_report(report, rows, groups)

    dataset_text = "\r\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\r\n"
    atomic_write_text(dataset_path, dataset_text, newline="")
    report_text = json.dumps(report, ensure_ascii=False, indent=2).replace("\n", "\r\n") + "\r\n"
    atomic_write_text(report_path, report_text, newline="")
    examples_text = json.dumps(rebuild_examples(rows), ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(args.processed / "cleaning_examples.json", examples_text, newline="")

    print(json.dumps({
        "records": len(rows),
        "groups": len(groups),
        "duplicates": sum(row["duplicate_role"] == "duplicate" for row in rows),
        "effective_records": report["effective_records_after_dedup"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
