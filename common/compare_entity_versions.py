"""Run a frozen entity-boundary fixture in isolated local/cloud/merged modules.

Usage: python common/compare_entity_versions.py --mode merged --source task2/src
Old versions can be extracted with git archive <ref> into a temporary directory.
The fixture is a regression benchmark, not a corpus accuracy estimate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--mode", choices=["local", "cloud", "merged"], required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=Path(__file__).resolve().parents[1] / "review/merge_20261029/entity_cases.json")
    args = parser.parse_args()
    source = args.source.resolve()
    sys.path.insert(0, str(source))
    cases = json.loads(args.fixture.read_text(encoding="utf-8"))["cases"]
    if args.mode in {"local", "merged"}:
        from extract_entities import DictMatcher, load_dictionary
        if args.mode == "local":
            from extract_entities import time_entities
        else:
            from compatibility import time_entities
        entries, stopwords, _ = load_dictionary("refined")
        matcher = DictMatcher(entries, stopwords)

        def predict(text, area):
            return [(e["type"], e["start"], e["end"]) for e in matcher.find(text, scenic=area) + time_entities(text)]
    else:
        from dictionary import Gazetteer, load_poi_gazetteer, load_transport_lexicon
        from time_rules import TimeRules
        resources = source.parent / "resources"
        gazetteer = Gazetteer(load_poi_gazetteer(resources / "poi_gazetteer.csv"),
                              load_transport_lexicon(resources / "transport_lexicon.csv"))
        timer = TimeRules.load(resources / "time_rules.json")

        def predict(text, area):
            candidates = gazetteer.iter_poi_matches(text, area) + gazetteer.iter_transport_matches(text) + timer.extract(text)
            # Both systems are compared on the downstream core-entity layer.
            candidates = [c for c in candidates if c.subtype != "景区"]
            selected, _ = gazetteer.resolve_overlaps(candidates)
            return [(c.type, c.start, c.end) for c in selected]
    tp = fp = fn = passed = 0
    details = []
    for case in cases:
        gold = {(e["type"], e["start"], e["end"]) for e in case["expected"]}
        predicted = set(predict(case["text"], case["area"]))
        tp += len(gold & predicted)
        fp += len(predicted - gold)
        fn += len(gold - predicted)
        passed += gold == predicted
        details.append({"id": case["id"], "text": case["text"], "passed": gold == predicted,
                        "false_positive": sorted(predicted - gold), "false_negative": sorted(gold - predicted)})
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    summary = {"mode": args.mode, "cases": len(cases), "passed": passed, "tp": tp, "fp": fp, "fn": fn,
               "precision": round(precision, 4), "recall": round(recall, 4),
               "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0,
               "evaluation_scope": "curated boundary regression; not population accuracy"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"summary": summary, "details": details}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
