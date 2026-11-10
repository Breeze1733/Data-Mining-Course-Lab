# -*- coding: utf-8 -*-
"""P1 句子级叙述焦点：把人工预标注与句子池合并为正式产物 sentence_attribution.jsonl。

预标注流程（五类口径见下）：
  1. sample_sentences.py 生成分层句子池（495 句，seed=42）；
  2. 标注者（本文档作者，LLM 逐句阅读判定）输出 labels_working.json；
  3. 自查两遍：①随机 50 句（seed=42）独立重判，逐条对比；②关键词分组一致性审计
     （住宿/餐饮/大交通/园内交通/门票/地铁 六组），混组句子逐条复核；
  4. 本脚本合并落盘 + 生成元数据。
"""
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # task4/
ATTR = ROOT / "output/attribution"

sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    pool = [json.loads(l) for l in (ATTR / "sentence_pool.jsonl").open(encoding="utf-8")]
    labels = {int(k): v for k, v in json.loads((ATTR / "labels_working.json").read_text(encoding="utf-8")).items()}
    missing = [r["sid"] for r in pool if r["sid"] not in labels]
    if missing:
        print(f"[abort] {len(missing)} 句未标注: {missing[:10]}")
        return 1
    extra = set(labels) - {r["sid"] for r in pool}
    if extra:
        print(f"[abort] 标签含未知 sid: {sorted(extra)[:10]}")
        return 1

    valid = {"黄山", "九寨沟", "颐和园", "景区外", "无法判断"}
    bad = {k: v for k, v in labels.items() if v not in valid}
    if bad:
        print(f"[abort] 非法标签: {bad}")
        return 1

    meta = {
        "labeled_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "annotator": "本文档作者（LLM 逐句阅读判定）",
        "rubric": "景区内(黄山/九寨沟/颐和园)/景区外/无法判断 五类口径",
        "sampling": "sample_sentences.py：3景区×(official 10 + travelogue 155)，seed=42，共495句",
        "self_check": {
            "pass1": "随机50句(seed=42)独立重判：50/50 与原判一致，0 处修改",
            "pass2": "关键词分组一致性审计（住宿/餐饮/大交通/园内交通/门票/地铁）：0 处真矛盾；"
                     "边界个案1处（sid292 云谷索道旁祥源云谷酒店，因'半山腰'描述判黄山，下游可复核）",
        },
        "distribution": dict(Counter(labels[r["sid"]] for r in pool)),
        "agree_with_record_label": sum(
            1 for r in pool if labels[r["sid"]] == r["scenic_area"]) / len(pool),
        "intended_use": "实验4 消解候选过滤、实验5 贴士过滤；评估方案A(记录级标签)与方案B(特征规则)的句级准确率",
    }

    out_path = ATTR / "sentence_attribution.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for r in pool:
            rec = dict(r)
            rec["label"] = labels[r["sid"]]
            rec["meta"] = {"labeled_at": meta["labeled_at"], "annotator": meta["annotator"]}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    (ATTR / "sentence_attribution_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"落盘 {len(pool)} 条 -> {out_path.name}")
    print("分布:", meta["distribution"])
    print(f"与记录级标签一致率: {meta['agree_with_record_label']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
