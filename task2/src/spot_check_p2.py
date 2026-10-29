# -*- coding: utf-8 -*-
"""P2 新增实体的独立抽检：从 refined 抽取结果中抽新增词条命中的实例，人工复核。

与历史 spot_checks 相互独立（历史判定不动），结果落盘 spot_checks_p2.json：
  samples: [{type,subtype,name,scenic_area,record_id,start,end,context,verdict,note}]
  review_summary: {n, correct, ambiguous, incorrect}
用法：python src/spot_check_p2.py --sample   # 采样并打印上下文供标注
      python src/spot_check_p2.py --write    # 标注完成后落盘（读取 labels_working_p2.json）
"""
from __future__ import annotations

import argparse
import io
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP2 = ROOT / "output/exp2"
TASK1 = ROOT.parent / "task1"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

N_PER_SCENIC = 12
SEED = 42


def new_names() -> set[str]:
    names = set()
    for e in json.loads((ROOT / "resources/domain_seed.json").read_text(encoding="utf-8"))["poi"]:
        if str(e.get("source", "")).startswith("p2_peripheral_expansion"):
            names.add(e["name"])
    return names


def sample() -> list[dict]:
    targets = new_names()
    ents = [json.loads(l) for l in (EXP2 / "entities_refined.jsonl").open(encoding="utf-8")]
    texts = {json.loads(l)["record_id"]: json.loads(l)["clean_content"]
             for l in (TASK1 / "data/processed/dataset_clean.jsonl").open(encoding="utf-8")}
    by_scenic: dict[str, list[dict]] = defaultdict(list)
    for rec in ents:
        for e in rec["entities"]:
            if e["type"] == "景点POI" and (e.get("canonical") in targets or e.get("text") in targets):
                by_scenic[rec["scenic_area"]].append({
                    "name": e["text"], "canonical": e["canonical"],
                    "scenic_area": rec["scenic_area"], "record_id": rec["record_id"],
                    "start": e["start"], "end": e["end"],
                    "in_scenic": e.get("in_scenic"),
                })
    rng = random.Random(SEED)
    samples = []
    for scenic in ("黄山", "九寨沟", "颐和园"):
        pool = by_scenic.get(scenic, [])
        rng.shuffle(pool)
        picked, name_counts = [], {}
        # 先保证名字多样性：每个名字最多取3例
        for s in pool:
            if len(picked) >= N_PER_SCENIC:
                break
            if name_counts.get(s["name"], 0) >= 3:
                continue
            picked.append(s)
            name_counts[s["name"]] = name_counts.get(s["name"], 0) + 1
        samples += picked
    for s in samples:
        text = texts[s["record_id"]]
        a, b = max(0, s["start"] - 32), min(len(text), s["end"] + 32)
        s["context"] = text[a:b].replace("\n", " ")
        s["verdict"] = None
        s["note"] = ""
    return samples


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    if args.sample:
        samples = sample()
        for i, s in enumerate(samples):
            print(f"{i}|{s['scenic_area']}|{s['name']}({s['canonical']})|in_scenic={s['in_scenic']}| {s['context']}")
        (EXP2 / "spot_checks_p2_draft.json").write_text(
            json.dumps(samples, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n共 {len(samples)} 例 -> spot_checks_p2_draft.json")
        return 0

    if args.write:
        samples = json.loads((EXP2 / "spot_checks_p2_draft.json").read_text(encoding="utf-8"))
        labels = json.loads((EXP2 / "labels_working_p2.json").read_text(encoding="utf-8"))
        verdicts = {"correct": 0, "ambiguous": 0, "incorrect": 0}
        for i, s in enumerate(samples):
            s["verdict"] = labels[str(i)]
            verdicts[s["verdict"]] += 1
        payload = {
            "round": "p2_peripheral_expansion_2026-10-30",
            "annotator": "本文档作者（LLM 逐条阅读上下文判定）",
            "note": "对 P2 新增词条命中的实体做独立抽检（与历史 spot_checks 相互独立，历史判定未改动）",
            "n_sampled_pools": {sc: N_PER_SCENIC for sc in ("黄山", "九寨沟", "颐和园")},
            "seed": SEED,
            "samples": samples,
            "review_summary": {"n": len(samples), **verdicts},
        }
        (EXP2 / "spot_checks_p2.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"落盘 {len(samples)} 例，判定 {verdicts} -> spot_checks_p2.json")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
