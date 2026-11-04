# -*- coding: utf-8 -*-
"""E01：条件建议抽取的原句级覆盖评测（查全/过抽首次可测）。

此前评测只在"系统已抽出的对"上测准确率，无法度量漏抽。本评测复用 B01 的 40 句原始抽样
（task2/output/exp2/entity_sentence_sample.json），对每句判读"是否含给游客的建议"
（AI 逐句判读，来源如实声明），再对照当前映射表（mapping_table.json）报告：
  - advice_recall：含建议句中被抽出≥1 对的比例；
  - over_extraction：无建议句中被抽出的对数（过抽）；
  - 逐句明细（含未覆盖建议的 gist）。
判读口径：给游客的建议（条件性或建议性），个人计划/纯描述/官方规定陈述不计（防疫通告类
条件性规则信息按 boundary 计入）。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
TASK2 = ROOT.parent / "task2"

# 逐句判读（AI）。in_scope=True 表示句内含**条件性建议或带触发词的建议**（实验5 任务口径：
# 如果/若/建议/推荐/最好/适合/不要 等触发结构）；一般性路线罗列与无触发词的泛建议为任务外。
ADVICE = {4: (False, "中午12点上山、下午4点前下山（攻略式时间安排，无触发词）"),
          5: (False, "手机购票免现场排队（无触发词）"),
          6: (True, "建议后山上前山下、早点下山、坐索道避开人流"),
          7: (True, "如果背包有空间，可带面包香蕉香肠逗猴"),
          8: (True, "视野不佳时建议多等5-10分钟"),
          12: (True, "推荐坐火车下谷底再从一环二环爬上来"),
          21: (False, "光线好则人多，自己取舍（无触发词）"),
          23: (True, "玩黄龙的话住松潘古城（海拔低、配套全）"),
          24: (True, "14天内有相关旅居史的游客暂缓接待（防疫条件规定）"),
          31: (False, "昆明湖边坐一会儿（松弛感，无触发词）"),
          33: (False, "北如意门-画中游-…-新宫门（路线罗列）"),
          37: (False, "北宫门进➡…➡东宫门出（路线罗列）")}


def main() -> int:
    sample = json.loads((TASK2 / "output/exp2/entity_sentence_sample.json").read_text(encoding="utf-8"))["sentences"]
    mapping = json.loads((OUT / "mapping_table.json").read_text(encoding="utf-8"))
    mrows = mapping["rows"] if isinstance(mapping, dict) else mapping
    by_sentence = {}
    for r in mrows:
        by_sentence.setdefault((r.get("record_id"), r.get("sentence")), []).append(r)

    advice_n = matched_n = 0
    unmatched_advice = []
    over_pairs = 0
    detail = []
    for o in sample:
        sid, rid, sent = o["sid"], o["record_id"], o["sentence"]
        in_scope, gist = ADVICE.get(sid, (False, ""))
        # P16 精神：按 record + 句子包含匹配（task5 分句与抽样分句的规则不同，精确等值会漏配）
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

    result = {
        "n_sentences": len(sample),
        "annotated_by": "开发 agent 逐句判读（AI 辅助判读，非独立人工标注）",
        "scope_note": "in_scope=句内含条件性建议或带触发词的建议（实验5 任务口径）；无触发词的泛建议/路线罗列为任务外",
        "n_advice_sentences": advice_n,
        "advice_recall": round(matched_n / max(1, advice_n), 3),
        "unmatched_advice": unmatched_advice,
        "over_extraction_pairs_in_non_advice": over_pairs,
        "detail": detail,
    }
    (OUT / "extraction_coverage_eval.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n_advice": advice_n, "advice_recall": result["advice_recall"],
                      "unmatched": [u["sid"] for u in unmatched_advice],
                      "over_pairs": over_pairs}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
