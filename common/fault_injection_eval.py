""" 扩展：评测器故障注入——验证评测环节真的能发现退化。

对三个评测环节各注入一种确定性故障（作用在输入副本上；评测输出重定向到临时
目录，真实产物不改动）：
- task2 实体抽检评测：gold 实体表每 5 句替换 1 个错误实体 → overall F1 必须下降
- task4 指代消解评测：每 5 例把当前预测改成错误先行词（kind 同改 POI）→ 准确率必须下降
- task5 条件复核评测：每 5 条 verdict 由 correct 改为 wrong → 正确率必须下降

判据：注入后指标 − 基线（同 harness 用干净副本复算）≤ −0.05，即指标对退化敏感。
任何一项不敏感即退出码 1。输出 metrics/fault_injection_eval.json。
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

THRESHOLD = 0.05


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def check_task2_entity_eval(tmp: Path) -> dict:
    """task2 实体句级评测：污染 gold 副本，F1 应显著下降。"""
    sys.path.insert(0, str(ROOT / "task2/src"))
    import entity_sentence_eval as esv

    exp2_real = ROOT / "task2/output/exp2"
    base = tmp / "t2_base/exp2"
    fault = tmp / "t2_fault/exp2"
    t1_base = tmp / "t2_base/task1"
    t1_fault = tmp / "t2_fault/task1"
    for d in (base, fault, t1_base, t1_fault):
        d.mkdir(parents=True, exist_ok=True)
    for f in ("entity_sentence_sample.json", "entities_refined.jsonl", "entity_sentence_gold.json"):
        _copy(exp2_real / f, base / f)
    _copy(ROOT / "task1/data/processed/dataset_clean.jsonl", t1_base / "data/processed/dataset_clean.jsonl")
    _copy(base / "entity_sentence_sample.json", fault / "entity_sentence_sample.json")
    _copy(base / "entities_refined.jsonl", fault / "entities_refined.jsonl")
    _copy(t1_base / "data/processed/dataset_clean.jsonl", t1_fault / "data/processed/dataset_clean.jsonl")

    # 故障：每 5 个 gold 句子替换第一个实体为不存在的占位文本（必成 FN，且不属设计排除口径）
    gold_doc = json.loads((base / "entity_sentence_gold.json").read_text(encoding="utf-8"))
    n_corrupt = 0
    for i, g in enumerate(gold_doc["gold"]):
        if i % 5 == 0 and g["entities"]:
            g["entities"][0] = ["〔注入占位无此实体〕", g["entities"][0][1]]
            n_corrupt += 1
    (fault / "entity_sentence_gold.json").write_text(
        json.dumps(gold_doc, ensure_ascii=False, indent=1), encoding="utf-8")

    out = {}
    for tag, d_exp2, d_t1 in (("baseline", base, t1_base), ("fault", fault, t1_fault)):
        esv.EXP2 = d_exp2
        esv.TASK1 = d_t1
        esv.main()
        r = json.loads((d_exp2 / "entity_sentence_eval.json").read_text(encoding="utf-8"))
        out[tag] = {"f1": r["overall"]["f1"], "recall": r["overall"]["recall"]}
    return {"metric": "overall.f1", "baseline": out["baseline"]["f1"],
            "fault": out["fault"]["f1"], "fault_recall": out["fault"]["recall"],
            "baseline_recall": out["baseline"]["recall"],
            "drop": round(out["baseline"]["f1"] - out["fault"]["f1"], 3),
            "n_corrupted_gold": n_corrupt,
            "sensitive": out["baseline"]["f1"] - out["fault"]["f1"] >= THRESHOLD}


def check_task4_coref_eval(tmp: Path) -> dict:
    """task4 指代消解评测：污染当前预测副本，准确率应显著下降。"""
    sys.path.insert(0, str(ROOT / "task4/src"))
    import annotate_sample as ann

    out_real = ROOT / "task4/output"
    base = tmp / "t4_base"
    base.mkdir(parents=True, exist_ok=True)
    _copy(out_real / "annotation_gold.json", base / "annotation_gold.json")
    _copy(out_real / "pronoun_cases.jsonl", base / "pronoun_cases.jsonl")

    orig_out, orig_figs = ann.OUT, ann.FIGS
    ann.OUT = base
    ann.FIGS = tmp / "t4_figs"
    try:
        cases = ann.load_cases()
        # 故障：每 5 例把预测改成错误先行词并把 kind 改为 POI（POI/景区类身份判错，
        # 非实体类则类别判错——两类正确判定都会被击穿）
        n_corrupt = 0
        for i, c in enumerate(cases):
            if i % 5 == 0:
                c["resolution"] = "〔注入错误先行词〕"
                c["resolution_kind"] = "POI"
                n_corrupt += 1
        ann.score(cases)
        r = json.loads((base / "evaluation.json").read_text(encoding="utf-8"))
    finally:
        ann.OUT, ann.FIGS = orig_out, orig_figs
    baseline = json.loads((out_real / "evaluation.json").read_text(encoding="utf-8"))
    return {"metric": "accuracy_overall", "baseline": baseline["accuracy_overall"],
            "fault": r["accuracy_overall"],
            "drop": round(baseline["accuracy_overall"] - r["accuracy_overall"], 3),
            "n_corrupted_cases": n_corrupt,
            "sensitive": baseline["accuracy_overall"] - r["accuracy_overall"] >= THRESHOLD}


def check_task5_review_eval(tmp: Path) -> dict:
    """task5 条件复核评测：污染 verdict 副本，正确率应显著下降。"""
    sys.path.insert(0, str(ROOT / "task5/src"))
    import review_and_charts as rc

    out_real = ROOT / "task5/output"
    base = tmp / "t5_base"
    fault = tmp / "t5_fault"
    for d in (base, fault):
        d.mkdir(parents=True, exist_ok=True)
    for f in ("review_dev.json", "mapping_table.json"):
        _copy(out_real / f, base / f)
        _copy(out_real / f, fault / f)

    reviews = json.loads((fault / "review_dev.json").read_text(encoding="utf-8"))
    n_corrupt = 0
    for i, r in enumerate(reviews["reviews"]):
        if i % 5 == 0 and r["verdict"] == "correct":
            r["verdict"] = "wrong"
            n_corrupt += 1
    (fault / "review_dev.json").write_text(
        json.dumps(reviews, ensure_ascii=False, indent=1), encoding="utf-8")

    def correct_rate(d: Path) -> float:
        rc.OUT = d
        rc.score()
        s = json.loads((d / "review_summary.json").read_text(encoding="utf-8"))
        return s["verdicts"].get("correct", 0) / s["n"]

    orig_out = rc.OUT
    try:
        b = correct_rate(base)
        f = correct_rate(fault)
    finally:
        rc.OUT = orig_out
    return {"metric": "verdict correct rate", "baseline": round(b, 3), "fault": round(f, 3),
            "drop": round(b - f, 3), "n_corrupted_reviews": n_corrupt,
            "sensitive": b - f >= THRESHOLD}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="h06_fault_"))
    results = []
    try:
        for name, fn in (("task2_实体抽评测", check_task2_entity_eval),
                         ("task4_指代消解评测", check_task4_coref_eval),
                         ("task5_条件复核评测", check_task5_review_eval)):
            r = fn(tmp)
            results.append({"target": name, **r})
            print(f'{"PASS" if r["sensitive"] else "FAIL"} {name}: '
                  f'baseline={r["baseline"]} fault={r["fault"]} drop={r["drop"]}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    report = {
        "title": "扩展：评测器故障注入（评测环节对退化的敏感性）",
        "method": "在输入副本上注入确定性故障（每5例1处），评测输出重定向临时目录；"
                  "判据 drop ≥ 0.05；基线为同 harness 用干净副本复算",
        "threshold": THRESHOLD,
        "results": results,
    }
    out = ROOT / "metrics/fault_injection_eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    n_fail = sum(1 for r in results if not r["sensitive"])
    print(json.dumps({"n_targets": len(results), "n_insensitive": n_fail}, ensure_ascii=False))
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
