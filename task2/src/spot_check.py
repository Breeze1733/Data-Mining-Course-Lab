"""Experiment 2: manual entity QC sampling (stratified random, fixed seed).

Usage:
  python src/spot_check.py --sample          # generate the sample and print contexts
  python src/spot_check.py --score           # compute sample accuracy from manual verdicts
Verdicts go into VERDICTS (correct/incorrect/ambiguous + note), committed with the output.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/exp2"
TASK1 = ROOT.parent / "task1"
N_PER_CELL = 6
SEED = 42

# Manual verdicts (filled in item by item after spot_check.py --sample generates them)
VERDICTS: dict[str, dict] = {}


def load() -> tuple[dict[str, dict], list[dict]]:
    texts = {}
    for line in (TASK1 / "data/processed/dataset_clean.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        texts[r["record_id"]] = r
    ents = [json.loads(line) for line in (OUT / "entities_refined.jsonl").open(encoding="utf-8")]
    return texts, ents


def sample() -> None:
    texts, ents = load()
    cells: dict[tuple[str, str], list] = defaultdict(list)
    for rec in ents:
        for e in rec["entities"]:
            cells[(e["type"], rec["scenic_area"])].append((rec["record_id"], e))
    rng = random.Random(SEED)
    samples = []
    for cell in sorted(cells):
        pool = cells[cell]
        picks = rng.sample(pool, min(N_PER_CELL, len(pool)))
        for rid, e in picks:
            text = texts[rid]["clean_content"]
            s, t = max(0, e["start"] - 28), min(len(text), e["end"] + 28)
            samples.append({
                "type": e["type"], "subtype": e["subtype"], "scenic_area": cell[1],
                "record_id": rid, "text": e["text"], "start": e["start"], "end": e["end"],
                "context": text[s:t].replace("\n", "⏎"),
            })
    (OUT / "spot_checks.json").write_text(
        json.dumps({"seed": SEED, "n_per_cell": N_PER_CELL, "samples": samples},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    for i, s in enumerate(samples):
        print(f"{i:2d} [{s['type']}/{s['subtype']}|{s['scenic_area']}] {s['text']!r} @{s['record_id']}")
        print(f"    …{s['context']}…")


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
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--reconcile", action="store_true")
    args = parser.parse_args()
    if args.sample:
        sample()
    elif args.score:
        score()
    elif args.reconcile:
        reconcile()
