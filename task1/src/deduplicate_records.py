"""Apply near-duplicate dedup to the delivered task1 dataset.

The cleaning policy is: within one scenic area, the earliest accepted record is
the canonical copy; later records with clean-text similarity >= 0.9 are removed.
This script applies that policy to ``data/processed/dataset_clean.jsonl`` without
re-cleaning the text.

Removed rows are appended to ``rejected_records.jsonl`` with rejection reason
``near_duplicate_of:<canonical>`` (audit trail), not silently dropped. Retained
canonical rows keep the four group fields:

    duplicate_group  DUP_001.. or "" when the record is not in a group
    duplicate_role   "canonical" | "duplicate" | ""
    duplicate_of     canonical record id for removed duplicates
    dedup_weight     1.0 for retained records, 0.0 for removed duplicates

The script is idempotent: running it twice produces identical files.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT.parent / "common"))
from atomic import atomic_write_text  # noqa: E402
from preprocess import find_near_duplicate, summarize_dataset  # noqa: E402

PROCESSED = ROOT / "data/processed"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def mark_duplicate(row: dict, canonical: str, similarity: float) -> None:
    reason = f"near_duplicate_of:{canonical}"
    row["deduplication_reason"] = reason
    row["near_duplicate_of"] = canonical
    row["near_duplicate_similarity"] = round(similarity, 4)
    row["rejection_reasons"] = [reason]
    row["quality_flags"] = [flag for flag in row.get("quality_flags", [])
                            if not flag.startswith("near_duplicate")]


def is_near_duplicate_rejection(row: dict) -> bool:
    return (any(str(reason).startswith("near_duplicate_of:") for reason in row.get("rejection_reasons", []))
            or str(row.get("deduplication_reason", "")).startswith("near_duplicate_of:")
            or bool(row.get("near_duplicate_of")))


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove near-duplicate records from the delivered task1 dataset.")
    parser.add_argument("--processed", type=Path, default=PROCESSED)
    args = parser.parse_args(argv)

    dataset_path = args.processed / "dataset_clean.jsonl"
    report_path = args.processed / "quality_report.json"
    rejected_path = args.processed / "rejected_records.jsonl"
    legacy_removed_path = args.processed / "deduplicated_records.jsonl"
    rows = read_jsonl(dataset_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rejected = read_jsonl(rejected_path)
    pairs = [dict(pair, action="removed_as_duplicate") for pair in report.get("near_duplicate_pairs", [])]
    pair_similarity = {(pair["record_id_a"], pair["record_id_b"]): float(pair.get("similarity", 0.0))
                       for pair in pairs}

    accepted: list[dict] = []
    removed: list[dict] = []
    for row in rows:
        match = find_near_duplicate(row, accepted)
        if match is None:
            accepted.append(row)
            continue
        canonical, similarity = match
        mark_duplicate(row, canonical, similarity)
        pairs.append({"record_id_a": canonical, "record_id_b": row["record_id"],
                      "similarity": round(similarity, 4), "action": "removed_as_duplicate"})
        removed.append(row)

    # Idempotence: previously removed copies already live in rejected_records.jsonl
    # (or, for a pre-change delivery, in the legacy deduplicated_records.jsonl).
    removed_ids = {row["record_id"] for row in removed}
    for row in read_jsonl(legacy_removed_path) + rejected:
        if row["record_id"] in removed_ids or not is_near_duplicate_rejection(row):
            continue
        reason = next((str(item) for item in row.get("rejection_reasons", [])
                       if str(item).startswith("near_duplicate_of:")), "")
        canonical = row.get("near_duplicate_of") or reason.removeprefix("near_duplicate_of:")
        similarity = float(row.get("near_duplicate_similarity")
                           or pair_similarity.get((canonical, row["record_id"]), 0.0))
        mark_duplicate(row, canonical, similarity)
        removed.append(row)
        removed_ids.add(row["record_id"])
    if not pairs:
        pairs = [dict(pair, action="removed_as_duplicate") for pair in report.get("near_duplicate_pairs", [])]

    # Rejected file = quality rejections + near-duplicate removals, in input order.
    record_checks = report.get("record_checks", [])
    positions = {check["record_id"]: check["input_position"] for check in record_checks}
    for row in rejected + removed:
        if row.get("input_position") is None:
            row["input_position"] = positions.get(row["record_id"])
    merged_rejected = {row["record_id"]: row for row in rejected}
    merged_rejected.update({row["record_id"]: row for row in removed})
    rejected = sorted(merged_rejected.values(), key=lambda row: row.get("input_position") or 0)

    accepted_ids = {row["record_id"] for row in accepted}
    removed_ids = {row["record_id"] for row in removed}
    rejected_by_id = {row["record_id"]: row for row in rejected}
    reasons = {row["record_id"]: row["deduplication_reason"] for row in removed}
    for check in record_checks:
        record_id = check["record_id"]
        if record_id in accepted_ids:
            check["accepted"] = True
            check["errors"] = []
        elif record_id in removed_ids:
            check["accepted"] = False
            check["errors"] = [reasons[record_id]]
            check["warnings"] = [flag for flag in check.get("warnings", [])
                                 if not flag.startswith("near_duplicate")]
        elif record_id in rejected_by_id:
            check["accepted"] = False
            check["errors"] = rejected_by_id[record_id].get("rejection_reasons", [])
            check["warnings"] = rejected_by_id[record_id].get("quality_flags", [])

    new_report = summarize_dataset(
        accepted, rejected, removed, pairs, record_checks,
        report.get("cleaning_rule_totals_all_inputs", {}),
        report.get("missing_required_fields_in_input", {}),
        report.get("input_records", len(accepted) + len(rejected)),
        positions, 80, 30,
    )
    for key in ("input_path",):
        if key in report:
            new_report[key] = report[key]

    dataset_text = "\n".join(json.dumps(row, ensure_ascii=False) for row in accepted) + "\n"
    rejected_text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rejected) + "\n"
    report_text = json.dumps(new_report, ensure_ascii=False, indent=2).replace("\n", "\r\n") + "\r\n"
    examples_text = json.dumps(rebuild_examples(accepted), ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(dataset_path, dataset_text, newline="")
    atomic_write_text(rejected_path, rejected_text, newline="")
    atomic_write_text(report_path, report_text, newline="")
    atomic_write_text(args.processed / "cleaning_examples.json", examples_text, newline="")
    if legacy_removed_path.exists():
        legacy_removed_path.unlink()

    print(json.dumps({
        "records": len(accepted),
        "rejected_records": len(rejected),
        "removed_duplicates": len(removed),
        "groups": new_report["near_duplicate_group_count"],
        "effective_records": new_report["effective_records_after_dedup"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
