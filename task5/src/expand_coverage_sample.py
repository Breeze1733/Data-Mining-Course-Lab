# -*- coding: utf-8 -*-
""" 扩充：条件建议覆盖评测的新鲜开发样本抽取（第一轮 dev 40 句 → 追抽 60 句）。

抽样口径：travelogue 正文句（与任务口径一致），排除 entity_sentence_sample*.json 已抽句子；
按 scenic × 抽样格分层，每记录最多 2 句，seed=77 确定性。抽出的句子写入
task2/output/exp2/coverage_sample_expanded.json（ai_advice 字段由开发 agent 逐句判读后回填，
来源声明：AI 辅助判读，非独立人工标注）。
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
TASK1 = REPO / "task1/data/processed/dataset_clean.jsonl"
EXP2 = REPO / "task2/output/exp2"

SENT_SPLIT = re.compile(r"[。！？；!?\n]+")


def split_sentences(text: str) -> list[tuple[int, str]]:
    out = []
    pos = 0
    for chunk in SENT_SPLIT.split(text):
        s = chunk.strip()
        if not s:
            pos += len(chunk) + 1
            continue
        start = text.find(s, pos)
        out.append((start, s))
        pos = start + len(s)
    return out


def main() -> int:
    seen_records = set()
    seen_sentences = set()
    for name in ("entity_sentence_sample.json", "entity_sentence_sample_dev.json"):
        doc = json.loads((EXP2 / name).read_text(encoding="utf-8"))
        for o in doc["sentences"]:
            seen_records.add(o["record_id"])
            seen_sentences.add(o["sentence"])

    pool: dict[tuple, list] = {}
    with TASK1.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("text_type") != "travelogue" or r["record_id"] in seen_records:
                continue
            for start, s in split_sentences(r["clean_content"]):
                if len(s) < 12 or s in seen_sentences:
                    continue
                pool.setdefault((r["scenic_area"], r["source_platform"]), []).append(
                    {"record_id": r["record_id"], "scenic": r["scenic_area"],
                     "platform": r["source_platform"], "start": start, "sentence": s})

    cells = sorted(pool)
    rng = random.Random(77)
    per_cell = max(1, 60 // len(cells) + (1 if 60 % len(cells) else 0))
    picked: dict[str, dict] = {}
    per_record: dict[str, int] = {}
    for cell in cells:
        cand = pool[cell][:]
        rng.shuffle(cand)
        took = 0
        for o in cand:
            if took >= per_cell or len(picked) >= 60:
                break
            if per_record.get(o["record_id"], 0) >= 2:
                continue
            key = o["record_id"] + "|" + o["sentence"][:20]
            if key in picked:
                continue
            picked[key] = {**o, "sid": None, "ai_advice": None, "gist": ""}
            per_record[o["record_id"]] = per_record.get(o["record_id"], 0) + 1
            took += 1
        if len(picked) >= 60:
            break
    sentences = list(picked.values())
    for i, o in enumerate(sentences):
        o["sid"] = 1000 + i  # 与既有 40/66 句 sid 空间错开
    doc = {"draw_seed": 77, "sampling": "travelogue 正文句，排除既有抽样记录；scenic×platform 分层，每记录≤2句",
           "annotated_by": "开发 agent 逐句判读（AI 辅助判读，非独立人工标注）——判读后回填 ai_advice/gist",
           "n": len(sentences), "sentences": sentences}
    (EXP2 / "coverage_sample_expanded.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n": len(sentences),
                      "by_scenic": {a: sum(1 for o in sentences if o["scenic"] == a)
                                    for a in ("黄山", "九寨沟", "颐和园")}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
