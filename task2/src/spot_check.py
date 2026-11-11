"""Score or reconcile the frozen manual entity spot checks."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/exp2"
def score() -> None:
    data = json.loads((OUT / "spot_checks.json").read_text(encoding="utf-8"))
    filled = [s for s in data["samples"] if s.get("verdict")]
    by_type: dict[str, list] = defaultdict(list)
    for s in filled:
        by_type[s["type"]].append(s["verdict"])
    summary = {t: {"n": len(v), "correct": v.count("correct"),
                   "precision": round(v.count("correct") / len(v), 3)} for t, v in by_type.items()}
    overall = {"n": len(filled), "correct": sum(1 for s in filled if s["verdict"] == "correct"),
               "ambiguous": sum(1 for s in filled if s["verdict"] == "ambiguous"),
               "incorrect": sum(1 for s in filled if s["verdict"] == "incorrect")}
    print(json.dumps({"overall": overall, "by_type": summary}, ensure_ascii=False, indent=1))


def reconcile():
    path = OUT / "spot_checks.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("historical_review_summary", data["review_summary"])
    current = {}
    for line in (OUT / "entities_refined.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        for e in row["entities"]:
            current[(row["record_id"], e["type"], e["text"], e["start"], e["end"])] = e
    retained = []
    for sample in data["samples"]:
        key = (sample["record_id"], sample["type"], sample["text"], sample["start"], sample["end"])
        sample["present_in_current_output"] = key in current
        sample["review_provenance"] = "historical label; exact document/type/surface/span alignment"
        if key in current:
            retained.append(sample)
    summary = {"n": len(retained), **{kind: sum(s.get("verdict") == kind for s in retained)
                                     for kind in ("correct", "ambiguous", "incorrect")}}
    summary["historical_sample_count"] = len(data["samples"])
    summary["removed_or_changed"] = len(data["samples"]) - len(retained)
    summary["note"] = "仅对本轮仍存在的相同实体继承历史判定；非新一轮随机抽检，不估计总体准确率。新增实体尚待独立人工抽检。"
    data["review_summary"] = summary
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--reconcile", action="store_true")
    args = parser.parse_args()
    if args.score:
        score()
    elif args.reconcile:
        reconcile()
