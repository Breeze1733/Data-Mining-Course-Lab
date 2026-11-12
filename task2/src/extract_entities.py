"""Entity recognizer for Experiment 2. Reads the Experiment 1 main corpus; results feed downstream experiments.

baseline and refined are dictionary-iteration parameters of the recognizer.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from entity_rules import DictMatcher, time_entities, refined_dictionary, resolve_record_entities

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/exp2"
TASK1 = ROOT.parent / "task1"


def load_dictionary(iteration: str):
    if iteration == "refined":
        return refined_dictionary()
    if iteration != "baseline":
        raise ValueError(f"未知迭代: {iteration}")
    sys.path.insert(0, str(TASK1 / "scripts"))
    from expand_ctrip import NODES
    entries = [{"name": poi, "entity_type": "景点POI", "subtype": "景点",
                "scenic_areas": [area], "canonical": poi, "source": "seed"}
               for area, pois in NODES.items() for poi in pois]
    basic = ["观光车", "索道", "缆车", "步行", "徒步", "游船", "电瓶车", "摆渡车", "环保车"]
    entries += [{"name": word, "entity_type": "交通方式", "subtype": "通用",
                 "scenic_areas": ["通用"], "canonical": word, "source": "basic"} for word in basic]
    return entries, set(), False


def _number(value):
    return int(value) if float(value).is_integer() else round(float(value), 4)


def _counter(counter: Counter) -> dict:
    return {key: _number(value) for key, value in counter.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", choices=["baseline", "refined"], default="refined")
    parser.add_argument("--input", type=Path, default=TASK1 / "data/processed/dataset_clean.jsonl")
    parser.add_argument("--output-dir", type=Path, default=OUT)
    args = parser.parse_args(argv)
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    entries, stopwords, _ = load_dictionary(args.iteration)
    matcher = DictMatcher(entries, stopwords)

    with args.input.open(encoding="utf-8") as source:
        rows = [json.loads(line) for line in source if line.strip()]

    if not rows:
        raise ValueError("输入数据集为空")

    out_path = out / f"entities_{args.iteration}.jsonl"
    type_scenic = defaultdict(Counter)
    type_scenic_in_scenic = defaultdict(Counter)
    subtype_counter = Counter()
    canonical_freq: dict[str, Counter] = defaultdict(Counter)
    canonical_in_scenic: dict[str, Counter] = defaultdict(Counter)
    canonical_by_scenic: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    per_record_counts = []
    per_record_weights = []
    total_characters = 0
    canonical_whitespace = 0
    weighted_entity_total = 0

    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            text = row["clean_content"]
            total_characters += len(text)
            weight = int(float(row.get("dedup_weight", 1.0)))
            duplicate_group = row.get("duplicate_group") or ""
            ents = resolve_record_entities(matcher.find(text, scenic=row["scenic_area"]) + time_entities(text))
            assert all(text[e["start"]:e["end"]] == e["text"] for e in ents)
            ents.sort(key=lambda e: (e["start"], e["end"]))
            assert all(a["end"] <= b["start"] for a, b in zip(ents, ents[1:]))

            for e in ents:
                if any(ch.isspace() for ch in e["canonical"]):
                    canonical_whitespace += 1
                if not weight:
                    continue
                area = row["scenic_area"]
                type_scenic[area][e["type"]] += weight
                subtype_counter[e["type"] + "/" + e["subtype"]] += weight
                canonical_freq[e["type"]][e["canonical"]] += weight
                if e.get("in_scenic", True):
                    type_scenic_in_scenic[area][e["type"]] += weight
                    canonical_in_scenic[e["type"]][e["canonical"]] += weight
                    canonical_by_scenic[area][e["type"]][e["canonical"]] += weight

            weighted_entity_total += len(ents) * weight
            rec = {
                "record_id": row["record_id"],
                "scenic_area": row["scenic_area"],
                "source_platform": row["source_platform"],
                "text_type": row["text_type"],
                "clean_char_count": row["clean_char_count"],
                "duplicate_group": duplicate_group,
                "duplicate_role": row.get("duplicate_role") or "",
                "duplicate_of": row.get("duplicate_of") or "",
                "dedup_weight": weight,
                "entities": ents,
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            per_record_counts.append(len(ents))
            per_record_weights.append(weight)

    records_after_dedup = _number(sum(per_record_weights))
    duplicate_records = len(rows) - records_after_dedup
    stats = {
        "iteration": args.iteration,
        "dictionary_size": {
            "poi": sum(1 for e in entries if e["entity_type"] == "景点POI"),
            "transport": sum(1 for e in entries if e["entity_type"] == "交通方式"),
            "stopwords": len(stopwords),
        },
        "records": len(rows),
        "records_after_dedup": records_after_dedup,
        "duplicate_records": duplicate_records,
        "records_in_duplicate_groups": sum(1 for row in rows if row.get("duplicate_group")),
        "total_entities": weighted_entity_total,
        "total_entities_raw": sum(per_record_counts),
        "entities_per_record_mean": round(weighted_entity_total / records_after_dedup, 2) if records_after_dedup else 0,
        "entities_per_record_mean_raw": round(sum(per_record_counts) / len(rows), 2),
        "total_characters": total_characters,
        "by_scenic_area": {k: _counter(v) for k, v in type_scenic.items()},
        "by_scenic_area_in_scenic": {k: _counter(v) for k, v in type_scenic_in_scenic.items()},
        "by_subtype": _counter(subtype_counter),
        "top_canonical": {t: {k: _number(v) for k, v in c.most_common(40)}
                          for t, c in canonical_freq.items()},
        "top_canonical_in_scenic": {t: {k: _number(v) for k, v in c.most_common(40)}
                                    for t, c in canonical_in_scenic.items()},
        "top_canonical_by_scenic": {
            area: {t: {k: _number(v) for k, v in c.most_common(20)} for t, c in types.items()}
            for area, types in canonical_by_scenic.items()
        },
        "qc": {
            "canonical_with_whitespace": canonical_whitespace,
            "input_records_with_dedup_weight": sum(1 for row in rows if "dedup_weight" in row),
        },
    }
    (out / f"entity_stats_{args.iteration}.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: stats[k] for k in ("iteration", "total_entities", "entities_per_record_mean")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
