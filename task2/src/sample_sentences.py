# -*- coding: utf-8 -*-
"""P1 句子级叙述焦点：分层抽样器。

从 task1/data/processed/dataset_clean.jsonl 分句，按 景区 × 文本类型 分层随机抽样，
输出句子池 task2/output/exp2/sentence_pool.jsonl（含 doc 级字符偏移），供人工（LLM）预标注。

分层设计：官方路线句是结构化清单，"景区外漂移"问题主要发生在游记（携程/小红书），
因此游记层加大权重：每景区 official 10 句 + travelogue 155 句 ≈ 495 句。
分句规则与 task4 detect_and_resolve.py 保持一致（。！？；!?\n）。
"""
import argparse
import io
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK1 = ROOT.parent / "task1"
OUT = ROOT / "output/exp2"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
SENT_SPLIT = re.compile(r"[。！？；!?\n]+")

N_OFFICIAL_PER_SCENIC = 10
N_TRAVELOGUE_PER_SCENIC = 155
MIN_LEN = 6          # 过短句（纯表情/标题碎片）直接跳过，标不出焦点
MAX_LEN = 220        # 超长句截断风险大，跳过（分句规则下的罕见残留）
SEED = 42


def split_sentences(text: str) -> list[tuple[int, int, str]]:
    out = []
    start = 0
    for m in SENT_SPLIT.finditer(text):
        if m.start() > start:
            out.append((start, m.start(), text[start:m.start()]))
        start = m.end()
    if start < len(text):
        out.append((start, len(text), text[start:]))
    return [(s, e, t) for s, e, t in out if t.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--official-per-scenic", type=int, default=N_OFFICIAL_PER_SCENIC)
    ap.add_argument("--travelogue-per-scenic", type=int, default=N_TRAVELOGUE_PER_SCENIC)
    args = ap.parse_args()

    rows = [json.loads(l) for l in
            (TASK1 / "data/processed/dataset_clean.jsonl").open(encoding="utf-8")]

    cells: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        text = row["clean_content"]
        for s, e, sent in split_sentences(text):
            if not (MIN_LEN <= len(sent.strip()) <= MAX_LEN):
                continue
            cells.setdefault((row["scenic_area"], row["text_type"]), []).append({
                "record_id": row["record_id"],
                "scenic_area": row["scenic_area"],       # 记录级主景区标签（基线A的特征，非真值）
                "text_type": row["text_type"],
                "source": row.get("source_platform", row.get("source", "")),
                "start": s, "end": e,
                "sentence": sent.strip(),
            })

    rng = random.Random(SEED)
    picked = []
    for scenic in ("黄山", "九寨沟", "颐和园"):
        for tt, n in (("official_route", args.official_per_scenic),
                      ("travelogue", args.travelogue_per_scenic)):
            pool = cells.get((scenic, tt), [])
            take = min(n, len(pool))
            picked += rng.sample(pool, take)

    rng.shuffle(picked)
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "sentence_pool.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for i, item in enumerate(picked):
            item["sid"] = i
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"句子池: {len(picked)} 句 -> {out_path.relative_to(ROOT.parent)}")
    print("分层:", dict(Counter((p['scenic_area'], p['text_type']) for p in picked)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
