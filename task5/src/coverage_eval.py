# -*- coding: utf-8 -*-
"""Sentence-level coverage evaluation of conditional-advice extraction (recall/over-extraction measurable for the first time).

Previous evaluation measured accuracy only on "pairs the system already extracted" and could not measure misses. This evaluation reuses the  original 40-sentence sample
(task2/output/exp2/entity_sentence_sample.json), judges each sentence for "whether it contains advice for tourists"
(AI sentence-by-sentence judging, source declared as-is), then reports against the current mapping table (mapping_table.json):
  - advice_recall: fraction of advice-containing sentences with >=1 extracted pair;
  - over_extraction: number of pairs extracted from non-advice sentences (over-extraction);
  - per-sentence detail (including the gist of uncovered advice).
Judging scope: advice for tourists (conditional or suggestive); personal plans / pure description / official regulation statements excluded (epidemic-prevention
conditional rule information is counted as boundary).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
TASK2 = ROOT.parent / "task2"

# Sentence-by-sentence judging (AI). in_scope=True means the sentence contains **conditional advice or advice with trigger words** (experiment 5 task scope:
# trigger structures such as 如果/若/建议/推荐/最好/适合/不要); generic route listings and triggerless blanket advice are out of scope.
ADVICE = {4: (False, "中午12点上山、下午4点前下山（攻略式时间安排，无触发词）"),
          5: (False, "手机购票免现场排队（无触发词）"),
          6: (True, "建议后山上前山下、早点下山、坐索道避开人流"),
          7: (True, "如果背包有空间，可带面包香蕉香肠逗猴"),
          8: (True, "视野不佳时建议多等5-10分钟"),
          12: (True, "推荐坐火车下谷底再从一环二环爬上来"),
          21: (False, "光线好则人多，自己取舍（无触发词）"),
          23: (True, "玩黄龙的话住松潘古城（海拔低、配套全）【设计排除：他景区建议，归属过滤不产出】"),
          24: (True, "14天内有相关旅居史的游客暂缓接待（防疫条件规定）"),
          31: (False, "昆明湖边坐一会儿（松弛感，无触发词）"),
          33: (False, "北如意门-画中游-…-新宫门（路线罗列）"),
          37: (False, "北宫门进➡…➡东宫门出（路线罗列）")}


def _load_batches() -> list[dict]:
    """ Expansion: round-1 dev 40 sentences (judged via the ADVICE dict) + 60 additional sentences (coverage_sample_expanded.json,
    with the ai_advice field stored alongside the sample). Both batches share the same criteria; report per-batch and merged. """
    batches = []
    dev = json.loads((TASK2 / "output/exp2/entity_sentence_sample_dev.json").read_text(encoding="utf-8"))["sentences"]
    batches.append({"batch": "round1_dev", "sentences": [
        {**o, "ai_advice": ADVICE.get(o["sid"], (False, ""))[0],
         "gist": ADVICE.get(o["sid"], (False, ""))[1]} for o in dev]})
    expanded_path = TASK2 / "output/exp2/coverage_sample_expanded.json"
    if expanded_path.exists():
        exp = json.loads(expanded_path.read_text(encoding="utf-8"))["sentences"]
        batches.append({"batch": "expanded_seed77", "sentences": exp})
    return batches


def main() -> int:
    batches = _load_batches()
    all_rows = []
    batch_stats = {}
    for b in batches:
        b_rows = _eval_batch(b["batch"], b["sentences"])
        batch_stats[b["batch"]] = {k: b_rows[k] for k in
                                   ("n_sentences", "n_advice_sentences", "advice_recall",
                                    "over_extraction_pairs_in_non_advice")}
        all_rows.extend(b_rows["detail"])
    advice_n = sum(s["n_advice_sentences"] for s in batch_stats.values())
    design_excluded_n = sum(s.get("n_design_excluded", 0) for s in batch_stats.values())
    matched_total = sum(1 for r in all_rows if r["in_scope"] and r["n_pairs"] > 0)
    over_pairs = sum(r["n_pairs"] for r in all_rows if not r["in_scope"])
    result = {
        "n_sentences": len(all_rows),
        "annotated_by": "开发 agent 逐句判读（AI 辅助判读，非独立人工标注）",
        "sample_note": "第一轮 dev 40 句（entity_sentence_sample_dev.json）+ 追抽 60 句"
                       "（coverage_sample_expanded.json，seed=77，排除既有抽样记录）；"
                       " 第二轮冻结样本仅用于实体评测",
        "scope_note": "in_scope=句内含条件性建议或带触发词的建议（实验5 任务口径）；无触发词的泛建议/路线罗列为任务外",
        "n_advice_sentences": advice_n,
        "n_design_excluded": design_excluded_n,
        "advice_recall": round(matched_total / max(1, advice_n), 3),
        "by_batch": batch_stats,
        "over_extraction_pairs_in_non_advice": over_pairs,
        "detail": all_rows,
    }
    (OUT / "extraction_coverage_eval.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n_advice": advice_n, "advice_recall": result["advice_recall"],
                      "by_batch": {k: v["advice_recall"] for k, v in batch_stats.items()},
                      "over_pairs": over_pairs}, ensure_ascii=False))
    return 0


def _eval_batch(batch: str, sample: list[dict]) -> dict:
    """单批评测：句级判读 × 当前映射表匹配（record+包含匹配口径）。"""
    mapping = json.loads((OUT / "mapping_table.json").read_text(encoding="utf-8"))
    mrows = mapping["rows"] if isinstance(mapping, dict) else mapping
    by_sentence = {}
    for r in mrows:
        by_sentence.setdefault((r.get("record_id"), r.get("sentence")), []).append(r)

    advice_n = matched_n = 0
    unmatched_advice = []
    over_pairs = 0
    detail = []
    design_excluded = 0
    for o in sample:
        sid, rid, sent = o["sid"], o["record_id"], o["sentence"]
        in_scope = o.get("ai_advice")
        if in_scope is None:
            in_scope, gist = ADVICE.get(sid, (False, ""))
        else:
            gist = o.get("gist", "")
        if in_scope and "设计排除" in gist:
            design_excluded += 1
            detail.append({"sid": sid, "in_scope": True, "design_excluded": True,
                           "n_pairs": 0, "gist": gist})
            continue
        # Spirit: match by record + sentence containment (task5's splitter differs from the sampling splitter; exact equality would miss pairs)
        pairs = [r for (rr, ss), rs in by_sentence.items() if rr == rid and (ss in sent or sent in ss)
                 for r in rs]
        if in_scope:
            advice_n += 1
            if pairs:
                matched_n += 1
            else:
                unmatched_advice.append({"sid": sid, "gist": gist, "sentence": sent[:60]})
        if pairs and not in_scope:
            over_pairs += len(pairs)
        detail.append({"sid": sid, "in_scope": in_scope, "n_pairs": len(pairs), "gist": gist})

    return {
        "n_sentences": len(sample),
        "n_design_excluded": design_excluded,
        "n_advice_sentences": advice_n,
        "advice_recall": round(matched_n / max(1, advice_n), 3),
        "unmatched_advice": unmatched_advice,
        "over_extraction_pairs_in_non_advice": over_pairs,
        "detail": detail,
    }


if __name__ == "__main__":
    sys.exit(main())
