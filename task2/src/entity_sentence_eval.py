# -*- coding: utf-8 -*-
"""Sentence-level recall evaluation for entity recognition.

Prior evaluation was precision-only spot checks (53/53 + 46/46 hits) and could not
measure misses. This evaluation scores the current extractor on 40 raw sentences
against a sentence-level gold standard (entity_sentence_gold.json): strict span
matching for POI/transport (with containment variants), overlap-based matching for
time. Root scenic-area names (黄山/九寨沟/颐和园) and city names (北京/成都) are by
design not extracted as POI and are listed separately in the denominator
(scope_note of entity_sentence_eval.json).

Usage: python src/entity_sentence_eval.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXP2 = ROOT / "output/exp2"
EVAL = ROOT / "resources/eval"
TASK1 = ROOT.parent / "task1"

ROOT_SCENIC = {"黄山", "九寨沟", "颐和园"}
CITY_NAMES = {"北京", "成都"}
OUT_OF_SCOPE = ROOT_SCENIC | CITY_NAMES


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def wilson_ci(k: int, n: int, z: float = 1.96) -> dict:
    """Wilson 95% confidence interval (robust interval for small-sample proportions)."""
    if n == 0:
        return {"lo": None, "hi": None}
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    spread = (z / denom) * (p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5
    return {"lo": round(max(0.0, center - spread), 3), "hi": round(min(1.0, center + spread), 3)}


def prf(tp: int, fp: int, fn: int) -> dict:
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / max(1, tp + fp), 3),
            "recall": round(tp / max(1, tp + fn), 3),
            "f1": round(2 * tp / max(1, 2 * tp + fp + fn), 3)}


def gpos_found(sent: str, gtext: str) -> bool:
    return sent.find(gtext) >= 0


def main() -> int:
    sample = load_json(EVAL / "entity_sentence_sample.json")["sentences"]
    gold_doc = load_json(EVAL / "entity_sentence_gold.json")
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

    # Task 1 now removes near-duplicate documents physically. If a frozen sample
    # sentence came from a removed copy, remap it to the group's canonical record
    # when the exact sentence still exists there; otherwise skip it explicitly.
    quality = load_json(TASK1 / "data/processed/quality_report.json")
    canonical_of = {record_id: group["canonical_record_id"]
                    for group in quality.get("near_duplicate_groups", [])
                    for record_id in group["duplicate_record_ids"]}
    remapped, skipped = [], []
    for o in sample:
        if o["record_id"] in records:
            continue
        canonical = canonical_of.get(o["record_id"])
        pos = records[canonical].find(o["sentence"]) if canonical in records else -1
        if pos >= 0:
            o["remapped_from"] = o["record_id"]
            o["record_id"] = canonical
            o["start"] = pos
            remapped.append(o["sid"])
        else:
            skipped.append(o["sid"])
    sample = [o for o in sample if o["record_id"] in records]

    stats = {"POI": [0, 0, 0], "交通": [0, 0, 0], "时间": [0, 0, 0]}
    strict_hit = {"POI": 0, "交通": 0, "时间": 0}  # strict criterion (a hit must be exactly equal text)
    strict_by_span = {}  # stratified by span length {length bucket: [strict hits, total hits]}
    stats_oos = {"POI": [0, 0, 0]}  # out-of-scope-by-design criterion (root scenic names / city names): tp/fn counted separately
    missed, false_pos = [], []
    sentence_stats = []  # per-sentence local (tp, fp, fn), for stratified reporting
    for o in sample:
        sent_stats = {"POI": [0, 0, 0], "交通": [0, 0, 0], "时间": [0, 0, 0]}
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
                            if pp["text"] == gtext:
                                strict_hit[gtype] += 1
                            _bucket = "2字" if len(gtext) <= 2 else "3-4字" if len(gtext) <= 4 else "5字+"
                            _sb = strict_by_span.setdefault(_bucket, [0, 0])
                            _sb[1] += 1
                            if pp["text"] == gtext:
                                _sb[0] += 1
                            break
            if hit:
                stats[gtype][0] += 1
                sent_stats[gtype][0] += 1
            else:
                stats[gtype][2] += 1
                sent_stats[gtype][2] += 1
                missed.append({"sid": sid, "text": gtext, "type": gtype,
                               "out_of_scope_design": gtext in OUT_OF_SCOPE,
                               "sentence": sent[:60]})
        for i, pp in enumerate(preds):
            if not used[i]:
                _t = {"景点POI": "POI", "交通方式": "交通", "时间节点": "时间"}[pp["type"]]
                stats[_t][1] += 1
                sent_stats[_t][1] += 1
                false_pos.append({"sid": sid, "text": pp["text"], "type": pp["type"],
                                  "sentence": sent[:60]})
        # Out-of-scope-by-design criterion: mentions of root scenic names / city names are counted separately (counted as FN in that criterion when marked missed)
        for gtext, gtype in gold.get(sid, []):
            if gtype == "POI" and gtext in OUT_OF_SCOPE and gpos_found(sent, gtext):
                stats_oos["POI"][2] += 1
        sentence_stats.append((o, sent_stats))

    result = {
        "n_sentences": len(sample),
        "sample_remap": {
            "n_remapped": len(remapped),
            "remapped_sids": remapped,
            "already_remapped_sids": [o["sid"] for o in sample if o.get("remapped_from")],
            "n_skipped_absent_records": len(skipped),
            "skipped_sids": skipped,
            "note": "task1 物理去重后，原抽样文档若已移除，则映射到同组 canonical 记录；找不到原句时才跳过。",
        },
        "annotated_by": "开发 agent 逐句判读（AI 辅助判读，非独立人工标注；POI/交通严格跨度含包含式变体，时间重叠口径）",
        "match_policy": gold_doc.get("out_of_scope_note", "根景区名与城市名按设计不作为 POI 实体抽取"),
        "per_type": {t: prf(*v) for t, v in stats.items()},
        # Dual criteria: lenient (containment-variant hits, primary) vs strict (hit text exactly equal)
        "strict_ratio": {t: round(strict_hit[t] / max(1, v[0]), 3)
                         for t, v in stats.items() if v[0]},
        # Strict ratio stratified by matched-entity span length (2字/3-4字/5字+)
        "strict_by_span_len": strict_by_span,
        "missed": missed,
        "false_positives": false_pos,
        "scope_note": {},
    }
    # Stratified reporting (frozen sample: measure only, no rule changes) -- by platform / scenic area / source span length
    def _strata(keyfn, name):
        agg = {}
        for o, sent_stats in sentence_stats:
            k = keyfn(o, sent_stats)
            slot = agg.setdefault(k, {"POI": [0, 0, 0], "交通": [0, 0, 0], "时间": [0, 0, 0]})
            for typ, tri in sent_stats.items():
                for i in range(3):
                    slot[typ][i] += tri[i]
        return {"layer": name,
                "buckets": {str(k): {"overall": prf(sum(v[0] for v in s.values()),
                                                     sum(v[1] for v in s.values()),
                                                     sum(v[2] for v in s.values()))}
                            for k, s in sorted(agg.items(), key=lambda kv: str(kv[0]))}}
    result["stratified"] = [
        _strata(lambda o, ss: o.get("platform", "?"), "平台"),
        _strata(lambda o, ss: o.get("scenic", o.get("scenic_area", "?")), "景区"),
        _strata(lambda o, ss: "长句≥30" if len(o["sentence"]) >= 30 else "短句<30", "句长"),
    ]
    tot = lambda i: sum(v[i] for v in stats.values())
    result["overall"] = prf(tot(0), tot(1), tot(2))
    result["overall"]["precision_ci95"] = wilson_ci(tot(0), tot(0) + tot(1))
    result["overall"]["recall_ci95"] = wilson_ci(tot(0), tot(0) + tot(2))
    # Dual criterion: recall after removing by-design exclusions (root scenic names / cities) from the FN denominator
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


if __name__ == "__main__":
    sys.exit(main())
