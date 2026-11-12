"""Publish contextual facility-proximity POIs for task4.

The rule stays owned by task2; task4 reads this artifact instead of importing
task2 entity code.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK1 = ROOT.parent / "task1"
OUT = ROOT / "output/exp2"
sys.path.insert(0, str(ROOT / "src"))
from entity_rules import contextual_facility_places  # noqa: E402


def main() -> int:
    rows = [json.loads(line) for line in
            (TASK1 / "data/processed/dataset_clean.jsonl").open(encoding="utf-8") if line.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    n_records = n_entities = 0
    with (OUT / "contextual_facility_entities.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            if row["text_type"] != "travelogue":
                continue
            text = row["clean_content"]
            ents = contextual_facility_places(text, row["scenic_area"])
            if not ents:
                continue
            assert all(text[e["start"]:e["end"]] == e["text"] for e in ents), row["record_id"]
            record = {
                "record_id": row["record_id"],
                "scenic_area": row["scenic_area"],
                "text_type": row["text_type"],
                "clean_char_count": len(text),
                "entities": ents,
            }
            n_records += 1
            n_entities += len(ents)
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({"records": n_records, "entities": n_entities}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
