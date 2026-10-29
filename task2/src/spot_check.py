"""实验2：实体人工质检抽样（分层随机，固定种子）。

用法：
  python src/spot_check.py --sample          # 生成抽样并打印上下文
  python src/spot_check.py --score           # 依据人工判定计算样例正确率
判定写在 VERDICTS 中（correct/incorrect/ambiguous + note），随 output 提交。
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

# 人工判定（spot_check.py --sample 生成后逐条复核填写）
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


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--score", action="store_true")
    args = parser.parse_args()
    if args.sample:
        sample()
    elif args.score:
        score()
