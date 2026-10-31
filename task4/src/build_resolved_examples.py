# -*- coding: utf-8 -*-
"""实验4：消解后文本改写示例（resolved_examples.json）。

从当前规则消解结果（pronoun_cases.jsonl）与人工标注（annotation_gold.json）中选取判定正确的
实体指代案例，把句中代词替换为【先行词】生成 before/after 对照。选择规则：判定正确、代词在句内
唯一出现（替换无歧义）、按类别均衡取样、同记录不重复。

用法：python src/build_resolved_examples.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"

CANON = {"POI": "POI", "交通": "交通", "景区名": "景区", "他人": "他人", "同行者": "同行者",
         "名词集合": "集合-其他", "前文POI集合": "集合-POI", "人称集合": "集合-人",
         "路线": "路线", "设施": "设施", "无明确先行词": "无"}
MAX_PER_CLASS = 3
N_EXAMPLES = 6


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cases = [json.loads(l) for l in (OUT / "pronoun_cases.jsonl").open(encoding="utf-8")]
    gold = json.loads((OUT / "annotation_gold.json").read_text(encoding="utf-8"))["annotations"]
    records = {}
    for line in (ROOT.parent / "task1/data/processed/dataset_clean.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        records[r["record_id"]] = r["clean_content"]

    rows = []
    for g in gold:
        c = cases[g["case_index"]]
        kind_ok = CANON.get(c["resolution_kind"]) == g["gold_kind"]
        name_ok = (c["resolution"] == g["gold_antecedent"]
                   or (c["resolution_kind"] == "景区名" and g["gold_antecedent"] == c["scenic_area"]))
        if not (kind_ok and name_ok):
            continue
        if g["gold_kind"] not in ("POI", "景区", "路线"):
            continue  # 改写示例只呈现可代入实词的指代
        text = records.get(c["record_id"], "")
        sent_start = text.find(c["sentence"], max(0, c["doc_start"] - 400))
        if sent_start < 0:
            continue
        lo, hi = c["doc_start"] - sent_start, c["doc_end"] - sent_start
        if c["sentence"][lo:hi] != c["pronoun"]:
            continue
        if c["sentence"].count(c["pronoun"]) != 1:
            continue  # 代词在句内多处出现时不做示例，保证替换无歧义
        rows.append({
            "record_id": c["record_id"], "pronoun": c["pronoun"], "class": c["pronoun_class"],
            "antecedent": c["resolution"], "gold": g["gold_antecedent"],
            "before": c["sentence"], "after": c["sentence"][:lo] + f"【{c['resolution']}】" + c["sentence"][hi:],
        })

    picked, class_count, seen_rec = [], Counter(), set()
    for r in rows:
        if class_count[r["class"]] >= MAX_PER_CLASS or r["record_id"] in seen_rec:
            continue
        picked.append(r)
        class_count[r["class"]] += 1
        seen_rec.add(r["record_id"])
        if len(picked) >= N_EXAMPLES:
            break

    (OUT / "resolved_examples.json").write_text(
        json.dumps(picked, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"resolved_examples.json: {len(picked)} 例（按类别 {dict(class_count)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
