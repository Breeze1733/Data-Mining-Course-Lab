# -*- coding: utf-8 -*-
"""条件建议抽取的原句级覆盖评测（查全/过抽首次可测）。

此前评测只在"系统已抽出的对"上测准确率，无法度量漏抽。本评测复用  的 40 句原始抽样
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
import re
import sys
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
          23: (True, "玩黄龙的话住松潘古城（海拔低、配套全）【设计排除：他景区建议，归属过滤不产出】"),
          24: (True, "14天内有相关旅居史的游客暂缓接待（防疫条件规定）"),
          31: (False, "昆明湖边坐一会儿（松弛感，无触发词）"),
          33: (False, "北如意门-画中游-…-新宫门（路线罗列）"),
          37: (False, "北宫门进➡…➡东宫门出（路线罗列）")}


def _load_batches() -> list[dict]:
    """ 扩充：第一轮 dev 40 句（ADVICE 字典判读）+ 追抽 60 句（coverage_sample_expanded.json，
    ai_advice 字段随样本存储）。两批口径一致，分批与合并同时报告。"""
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
        # 精神：按 record + 句子包含匹配（task5 分句与抽样分句的规则不同，精确等值会漏配）
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






# 覆盖样本追抽（原独立脚本，内联；先抽样后评测可一次完成）
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


def expand_sample() -> int:
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
    import sys
    if "--expand" in sys.argv:
        sys.exit(expand_sample())
    sys.exit(main())
