# -*- coding: utf-8 -*-
"""B01：实体识别的句级完整评测（查全率首次可测）。

此前评测为"命中样本查准抽检"（spot_check 53/53+46/46），无法度量漏检。
本评测在 40 句原始句子上以人工判读金标准（entity_sentence_gold.json，AI 逐句判读并声明来源）
对当前抽取器打分：POI/交通严格跨度（含包含式变体命中），时间用重叠口径。
口径说明：根景区名（黄山/九寨沟/颐和园）与城市名（北京/成都）按设计不作为 POI 抽取，
分母中单列（entity_sentence_eval.json 的 scope_note）。

用法：python src/entity_sentence_eval.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP2 = ROOT / "output/exp2"
TASK1 = ROOT.parent / "task1"

ROOT_SCENIC = {"黄山", "九寨沟", "颐和园"}
CITY_NAMES = {"北京", "成都"}
OUT_OF_SCOPE = ROOT_SCENIC | CITY_NAMES


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))



def wilson_ci(k: int, n: int, z: float = 1.96) -> dict:
    """H07：Wilson 95% 置信区间（小样本比例的稳健区间）。"""
    if n == 0:
        return {"lo": None, "hi": None}
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    spread = (z / denom) * (p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5
    return {"lo": round(max(0.0, center - spread), 3), "hi": round(min(1.0, center + spread), 3)}


def main() -> int:
    sample = load_json(EXP2 / "entity_sentence_sample.json")["sentences"]
    gold_doc = load_json(EXP2 / "entity_sentence_gold.json")
    gold = {g["sid"]: g["entities"] for g in gold_doc["gold"]}
    records = {}
    with (TASK1 / "data/processed/dataset_clean.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            records[r["record_id"]] = r["clean_content"]
    ents = {}
    with (EXP2 / "entities_refined.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            ents[r["record_id"]] = r["entities"]

    stats = {"POI": [0, 0, 0], "交通": [0, 0, 0], "时间": [0, 0, 0]}
    stats_oos = {"POI": [0, 0, 0]}  # 设计排除口径（根景区名/城市名）：tp/fn 单独计数
    missed, false_pos = [], []
    for o in sample:
        sid, sent = o["sid"], o["sentence"]
        rid, start = o["record_id"], o["start"]
        preds = []
        for e in ents.get(rid, []):
            p_lo, p_hi = e["start"] - start, e["end"] - start
            if 0 <= p_lo < p_hi <= len(sent):
                preds.append({"text": sent[p_lo:p_hi], "type": e["type"],
                              "p_start": p_lo, "p_end": p_hi})
        used = [False] * len(preds)
        tmap = {"POI": "景点POI", "交通": "交通方式", "时间": "时间节点"}
        for gtext, gtype in gold.get(sid, []):
            gpos = sent.find(gtext)
            hit = False
            if gpos >= 0:
                g_lo, g_hi = gpos, gpos + len(gtext)
                for i, pp in enumerate(preds):
                    if used[i] or pp["type"] != tmap[gtype]:
                        continue
                    if gtype == "时间":
                        if pp["p_start"] < g_hi and pp["p_end"] > g_lo:
                            used[i] = True
                            hit = True
                            break
                    else:
                        if pp["text"] and (pp["text"] in gtext or gtext in pp["text"]):
                            used[i] = True
                            hit = True
                            break
            if hit:
                stats[gtype][0] += 1
            else:
                stats[gtype][2] += 1
                missed.append({"sid": sid, "text": gtext, "type": gtype,
                               "out_of_scope_design": gtext in OUT_OF_SCOPE,
                               "sentence": sent[:60]})
        for i, pp in enumerate(preds):
            if not used[i]:
                stats[{"景点POI": "POI", "交通方式": "交通", "时间节点": "时间"}[pp["type"]]][1] += 1
                false_pos.append({"sid": sid, "text": pp["text"], "type": pp["type"],
                                  "sentence": sent[:60]})
        # 设计排除口径：根景区名/城市名的提及单独计数（判 missed 即计入该口径 FN）
        for gtext, gtype in gold.get(sid, []):
            if gtype == "POI" and gtext in OUT_OF_SCOPE and gpos_found(sent, gtext):
                stats_oos["POI"][2] += 1

    def prf(tp, fp, fn):
        return {"tp": tp, "fp": fp, "fn": fn,
                "precision": round(tp / max(1, tp + fp), 3),
                "recall": round(tp / max(1, tp + fn), 3),
                "f1": round(2 * tp / max(1, 2 * tp + fp + fn), 3)}

    result = {
        "n_sentences": len(sample),
        "annotated_by": gold_doc["annotated_by"],
        "match_policy": gold_doc.get("out_of_scope_note", "根景区名与城市名按设计不作为 POI 实体抽取"),
        "per_type": {t: prf(*v) for t, v in stats.items()},
        "missed": missed,
        "false_positives": false_pos,
        "scope_note": {},
    }
    tot = lambda i: sum(v[i] for v in stats.values())
    result["overall"] = prf(tot(0), tot(1), tot(2))
    result["overall"]["precision_ci95"] = wilson_ci(tot(0), tot(0) + tot(1))
    result["overall"]["recall_ci95"] = wilson_ci(tot(0), tot(0) + tot(2))
    # 双口径：把设计排除项（根景区名/城市）从 FN 分母移除后的查全率
    oos_fn = sum(1 for m in missed if m.get("out_of_scope_design"))
    in_scope_fn = result["overall"]["fn"] - oos_fn
    tp = result["overall"]["tp"]
    result["scope_note"] = {
        "excluded_by_design": sorted(OUT_OF_SCOPE),
        "oos_misses": oos_fn,
        "recall_in_scope_only": round(tp / max(1, tp + in_scope_fn), 3),
        "note": "根景区名与城市名按设计不作为 POI 抽取；in_scope_only 口径将其从分母移除",
    }
    (EXP2 / "entity_sentence_eval.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"overall": result["overall"], "scope_note": result["scope_note"],
                      "per_type": {k: {kk: v[kk] for kk in ("precision", "recall", "f1")}
                                   for k, v in result["per_type"].items()}}, ensure_ascii=False))
    return 0


def gpos_found(sent: str, gtext: str) -> bool:
    return sent.find(gtext) >= 0


if __name__ == "__main__":
    sys.exit(main())
