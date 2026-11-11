# -*- coding: utf-8 -*-
"""Sentence-level coverage evaluation of conditional-advice extraction (recall/over-extraction measurable for the first time).

Previous evaluation measured accuracy only on "pairs the system already extracted" and could not measure misses. This evaluation reuses the 60-sentence expanded
sample (task5/resources/eval/coverage_sample_expanded.json, seed=77, drawn to exclude earlier sampling records), judges each sentence for "whether it contains advice for tourists"
(AI sentence-by-sentence judging, ai_advice stored alongside the sample), then reports against the current mapping table (mapping_table.json):
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
EVAL = ROOT / "resources/eval"

def _load_batches() -> list[dict]:
    """Expanded evaluation sample: 60 sentences (coverage_sample_expanded.json, with the AI advice judging stored in the ai_advice field)."""
    expanded_path = EVAL / "coverage_sample_expanded.json"
    exp = json.loads(expanded_path.read_text(encoding="utf-8"))["sentences"]
    return [{"batch": "expanded_seed77", "sentences": exp}]


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
        "sample_note": "coverage_sample_expanded.json（60 句，seed=77，排除既有抽样记录）",
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
        in_scope = o.get("ai_advice", False)
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
