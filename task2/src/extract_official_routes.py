"""Publish task2 entity annotations for official route branches.

task3 reads this artifact instead of importing task2 NER code. Only 景点POI and
交通方式 are emitted; task3 computes time nodes with its own local rules.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK1 = ROOT.parent / "task1"
OUT = ROOT / "output/exp2"
sys.path.insert(0, str(ROOT / "src"))
from entity_rules import DictMatcher, refined_dictionary  # noqa: E402

KEEP_KEYS = ("text", "type", "subtype", "canonical", "start", "end", "in_scenic", "method", "rule_id")


def main() -> int:
    entries, stopwords, _ = refined_dictionary()
    matcher = DictMatcher(entries, stopwords)
    routes = [json.loads(line) for line in
              (TASK1 / "data/raw/official_routes.jsonl").open(encoding="utf-8") if line.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    with (OUT / "official_route_entities.jsonl").open("w", encoding="utf-8") as fh:
        for route in routes:
            raw = route["raw_content"]
            ents = [e for e in matcher.find(raw, scenic=route["scenic_area"])
                    if e["type"] in ("景点POI", "交通方式")]
            ents.sort(key=lambda e: (e["start"], e["end"]))
            assert all(raw[e["start"]:e["end"]] == e["text"] for e in ents), route["route_id"]
            assert all(a["end"] <= b["start"] for a, b in zip(ents, ents[1:])), route["route_id"]
            payload = [{k: (e.get(k, True) if k == "in_scenic" else e.get(k)) for k in KEEP_KEYS}
                       for e in ents]
            record = {
                "route_id": route["route_id"],
                "source_record_id": route["source_record_id"],
                "scenic_area": route["scenic_area"],
                "raw_char_count": len(raw),
                "entity_count": len(payload),
                "entities": payload,
            }
            total += len(payload)
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({"routes": len(routes), "entities": total}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
