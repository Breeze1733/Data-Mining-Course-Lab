# -*- coding: utf-8 -*-
"""B10：词典扩充消融——把 B01 冻结测试的召回增益按扩充批次归因。

配置（在冻结测试 40 句上以 DictMatcher 直接打分，金标准与正式评测同源）：
  full            当前 refined 全量
  minus_b03       去掉 b03_recall_eval 批次（POI 25 + 交通 2 + 时间规则 3）
  minus_p2        再去掉 p2_peripheral_expansion 批次（56 条）
  seed_only       仅保留 seed/manual/merged 主干
输出：各配置的 P/R/F1 与每批次边际贡献（ΔR）。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP2 = ROOT / "output/exp2"
RES = ROOT / "resources"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT.parent / "common"))

from extract_entities import DictMatcher, load_dictionary  # noqa: E402
from entity_rules import time_entities  # noqa: E402


def wilson(k, n, z=1.96):
    if n == 0:
        return {"lo": None, "hi": None}
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    spread = (z / denom) * (p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5
    return {"lo": round(max(0.0, center - spread), 3), "hi": round(min(1.0, center + spread), 3)}


def score_with(entries, stopwords, time_patterns, sample, gold):
    matcher = DictMatcher(entries, stopwords)
    tmap = {"POI": "景点POI", "交通": "交通方式", "时间": "时间节点"}
    stats = {"POI": [0, 0, 0], "交通": [0, 0, 0], "时间": [0, 0, 0]}
    for o in sample:
        sent, sid = o["sentence"], o["sid"]
        preds = [{"text": m["text"], "type": m["type"],
                  "p_start": m["start"], "p_end": m["end"]} for m in matcher.find(sent)]
        preds += [{"text": t["text"], "type": "时间节点",
                   "p_start": t["start"], "p_end": t["end"]} for t in time_entities(sent)]
        used = [False] * len(preds)
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
            stats[gtype][0 if hit else 2] += 1
        for i, pp in enumerate(preds):
            if not used[i]:
                stats[{"景点POI": "POI", "交通方式": "交通", "时间节点": "时间"}[pp["type"]]][1] += 1
    tot = lambda i: sum(v[i] for v in stats.values())
    tp, fp, fn = tot(0), tot(1), tot(2)
    return {"precision": round(tp / max(1, tp + fp), 3), "recall": round(tp / max(1, tp + fn), 3),
            "f1": round(2 * tp / max(1, 2 * tp + fp + fn), 3), "tp": tp, "fp": fp, "fn": fn,
            "recall_ci95": wilson(tp, tp + fn)}


def main() -> int:
    sample = json.loads((EXP2 / "entity_sentence_sample.json").read_text(encoding="utf-8"))["sentences"]
    gold_doc = json.loads((EXP2 / "entity_sentence_gold.json").read_text(encoding="utf-8"))
    gold = {g["sid"]: g["entities"] for g in gold_doc["gold"]}

    entries, stopwords, _ = load_dictionary("refined")
    trule = json.loads((RES / "time_rules.json").read_text(encoding="utf-8"))
    SRC_B03 = "b03_recall_eval_2026-11-05"
    SRC_P2 = "p2_peripheral_expansion_2026-10-30"

    import entity_rules as ER
    orig_load = ER.TimeRules

    def time_with(patterns):
        class _C:
            __slots__ = ("surface", "type", "subtype", "start", "end", "normalized",
                         "counts_as_time_node", "method", "rule_id", "priority")

            def __init__(self, p, m):
                self.surface = m.group(0)
                self.type = "时间节点"
                self.subtype = p.get("subtype", "时段")
                self.start, self.end = m.start(), m.end()
                self.normalized = m.group(0)
                self.counts_as_time_node = p.get("counts_as_time_node", True)
                self.method = "rule"
                self.rule_id = p["id"]
                self.priority = p.get("priority", 50)

            @property
            def length(self):
                return self.end - self.start

            @property
            def rank(self):
                return self.priority

        class _TR:
            @staticmethod
            def extract(text):
                import re as _re
                out = []
                for p in patterns:
                    for m in _re.finditer(p["regex"], text):
                        out.append(_C(p, m))
                return out
        return _TR

    configs = {
        "full": ([e for e in entries], trule["patterns"]),
        "minus_b03": ([e for e in entries if e.get("source") != SRC_B03],
                      [p for p in trule["patterns"] if p.get("source") != SRC_B03]),
        "minus_b03_p2": ([e for e in entries if e.get("source") not in (SRC_B03, SRC_P2)],
                         [p for p in trule["patterns"] if p.get("source") != SRC_B03]),
    }
    results = {}
    import contextlib
    import io as _io
    for name, (es, pats) in configs.items():
        m = DictMatcher(es, stopwords)
        # 时间实体：临时切换全局规则集（entity_rules.time_entities 读取模块级 _time_rules）
        saved = ER._time_rules
        ER._time_rules = time_with(pats)
        with contextlib.redirect_stdout(_io.StringIO()):
            r = score_with(es, stopwords, pats, sample, gold)
        ER._time_rules = saved
        results[name] = r
        print(f"{name:14s} P={r['precision']:.3f} R={r['recall']:.3f} F1={r['f1']:.3f} "
              f"(TP {r['tp']} FP {r['fp']} FN {r['fn']}) R_CI95={r['recall_ci95']}")

    d_b03 = round(results["full"]["recall"] - results["minus_b03"]["recall"], 3)
    d_p2 = round(results["minus_b03"]["recall"] - results["minus_b03_p2"]["recall"], 3)
    out = {"n_sentences": len(sample), "configs": results,
           "marginal_recall": {"b03批次": d_b03, "p2批次": d_p2}}
    (EXP2 / "entity_ablation_b10.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("边际召回贡献:", json.dumps(out["marginal_recall"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
