"""Score coreference predictions against the frozen human annotations."""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
FIGS = OUT / "figs"
sys.stdout.reconfigure(encoding="utf-8")
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False


def load_cases() -> list[dict]:
    return [json.loads(l) for l in (OUT / "pronoun_cases.jsonl").open(encoding="utf-8")]


def doc_grouped_split(gold_rows: list[dict], target_test: int = 60) -> dict:
    """Doc-grouped dev/test split — sentence-level random splits leak within-document info (the two original rounds share 25 documents).

    Deterministic: sort the document list, shuffle with rng(42), assign whole documents to test until the sample quota is met, the rest go to dev.
    Near-duplicate constraint: near-duplicate pairs are forced to the same side (A05 fix — 2 pairs previously leaked across splits).
    Returns {record_id: "dev"|"test"}.
    """
    doc_ids = sorted({g["record_id"] for g in gold_rows})
    rng = random.Random(42)
    rng.shuffle(doc_ids)
    sizes = {d: sum(1 for g in gold_rows if g["record_id"] == d) for d in doc_ids}
    # A05: near-duplicate pairs -> transitive-closure grouping -> one side per group
    quality_path = ROOT.parent / "task1/data/processed/quality_report.json"
    near_dup_groups = []
    if quality_path.exists():
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        for _d in quality.get("near_duplicate_pairs", []):
            _a, _b = _d["record_id_a"], _d["record_id_b"]
            for _grp in near_dup_groups:
                if _a in _grp or _b in _grp:
                    _grp.add(_b)
                    _grp.add(_a)
                    break
            else:
                near_dup_groups.append({_a, _b})
    rec2grp = {}
    for _gi, _grp in enumerate(near_dup_groups):
        for _r in _grp:
            rec2grp[_r] = _gi
    # Split by group rather than by document (the first document of a group encountered decides the whole group's side)
    assigned = set()
    split, n_test = {}, 0
    for d in doc_ids:
        if d in assigned:
            continue
        grp = near_dup_groups[rec2grp[d]] if d in rec2grp else {d}
        target = "test" if n_test < target_test else "dev"
        for member in sorted(grp):
            if member in sizes:
                split[member] = target
                assigned.add(member)
                if target == "test":
                    n_test += sizes[member]
    return split


sys.path.insert(0, str(ROOT.parent))
from common.fingerprints import data_fingerprints as _data_fingerprints


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


def score(cases: list[dict]) -> None:
    gold = json.loads((OUT / "annotation_gold.json").read_text(encoding="utf-8"))["annotations"]
    FIGS.mkdir(parents=True, exist_ok=True)
    rows = []
    for g in gold:
        case = cases[g["case_index"]]
        for field in ("record_id", "pronoun", "doc_start", "doc_end"):
            if field not in g or case[field] != g[field]:
                raise ValueError(f"Stale coreference annotation at {g['case_index']}: {field}; re-align the gold set before scoring")
        pred, truth = case["resolution"], g["gold_antecedent"]
        # Correctness: kind must match and identity must match (person/set/none compared by their special kinds; scenic-name fallback counts as “POI/景区” granularity)
        # Add the "其他" mapping — single-noun antecedents (non-entity concepts) are judged "其他" per the gold lineage, distinguished from "名词集合" (multi-element sets)
        canon = {"POI": "POI", "交通": "交通", "景区名": "景区", "他人": "他人", "同行者": "同行者",
                 "名词集合": "集合-其他", "其他": "其他", "前文POI集合": "集合-POI", "人称集合": "集合-人", "路线": "路线", "设施": "设施", "无明确先行词": "无"}
        kind_match = canon.get(case["resolution_kind"]) == g["gold_kind"]
        if g["gold_kind"] in ("POI", "景区"):
            name_match = pred == truth or (case["resolution_kind"] == "景区名" and truth == case["scenic_area"])
        else:
            name_match = True
        rows.append({**g, "correct": bool(kind_match and name_match),
                     "kind_match": bool(kind_match), "name_match": bool(name_match),
                     "cur_pred": pred, "cur_kind": case["resolution_kind"]})
    acc_overall = sum(r["correct"] for r in rows) / len(rows)
    by_class = defaultdict(lambda: [0, 0])
    for r in rows:
        by_class[r["pronoun_class"]][1] += 1
        by_class[r["pronoun_class"]][0] += r["correct"]
    # Split metric (doc-grouped): whole documents go into dev/test, eliminating within-document leakage
    doc_split = doc_grouped_split(gold)
    by_split = defaultdict(lambda: [0, 0])
    for r in rows:
        sp = doc_split[r["record_id"]]
        by_split[sp][1] += 1
        by_split[sp][0] += r["correct"]
    # D04: abstention metric — "无明确先行词" is an interpretable abstention; coverage and accuracy are reported separately
    by_scenic_acc = defaultdict(lambda: [0, 0])
    by_platform_acc = defaultdict(lambda: [0, 0])
    for r in rows:
        by_scenic_acc[r["scenic_area"]][1] += 1
        by_scenic_acc[r["scenic_area"]][0] += r["correct"]
        by_platform_acc[r.get("source_platform") or r["record_id"].split("_")[0]][1] += 1
        by_platform_acc[r.get("source_platform") or r["record_id"].split("_")[0]][0] += r["correct"]
    abstain_by_class = defaultdict(lambda: [0, 0])
    for r in rows:
        abstain_by_class[r["pronoun_class"]][1] += 1
        abstain_by_class[r["pronoun_class"]][0] += (r["cur_pred"] == "NONE")
    abstain_overall = [sum(v[0] for v in abstain_by_class.values()), len(rows)]
    result = {
        "n": len(rows),
        "accuracy_overall": round(acc_overall, 3),
        "abstention": {
            "note": "弃权=解析为 NONE（可解释的不定位）；覆盖率=1−弃权率，与准确率分开解读",
            "overall": {"n": abstain_overall[1],
                        "abstained": abstain_overall[0],
                        "coverage": round(1 - abstain_overall[0] / max(1, abstain_overall[1]), 3)},
            "by_class": {k: {"n": v[1], "abstained": v[0],
                             "coverage": round(1 - v[0] / max(1, v[1]), 3)}
                         for k, v in sorted(abstain_by_class.items())},
        },
        "accuracy_by_class": {k: {"n": v[1], "accuracy": round(v[0] / v[1], 3)} for k, v in sorted(by_class.items())},
        "accuracy_by_split": {k: {"n": v[1], "accuracy": round(v[0] / v[1], 3)} for k, v in sorted(by_split.items())},
        "accuracy_by_scenic": {k: {"n": v[1], "accuracy": round(v[0] / v[1], 3),
                                   "ci95": wilson_ci(v[0], v[1])}
                               for k, v in sorted(by_scenic_acc.items())},
        # Stratified by platform (XHS vs 携程), with CI
        "accuracy_by_platform": {k: {"n": v[1], "accuracy": round(v[0] / v[1], 3),
                                     "ci95": wilson_ci(v[0], v[1])}
                                 for k, v in sorted(by_platform_acc.items())},
        "errors_by_split": {k: v[1] - v[0] for k, v in sorted(by_split.items())},
        "split_method": "文档分组：整文档划入 dev/test（rng42 确定性），无同文档泄漏",
        # Error list cites the current predictions (historical rule_resolution snapshots remain only in the gold file for reference)
        "errors": [
            {"pronoun": r["pronoun"], "class": r["pronoun_class"], "scenic": r["scenic_area"],
             "pred": r["cur_pred"], "pred_kind": r["cur_kind"],
             "gold": r["gold_antecedent"], "gold_kind": r["gold_kind"], "note": r["note"]}
            for r in rows if not r["correct"]],
        # Kind metrics and antecedent-identity metrics are reported separately — non-entity kinds are judged on kind only, never counted as identity-correct
        "kind_only_accuracy": round(sum(r["kind_match"] for r in rows) / len(rows), 3) if rows else None,
        # D07: auxiliary "specific member hit" metric for set kinds — counted when the resolved name contains one of the gold set members,
        # read separately from the coarse kind accuracy (distinguishing "kind-correct" from "member-correct")
        "set_member_hit": None,
        "accuracy_ci95": wilson_ci(round(acc_overall * len(rows)), len(rows)),
        "data_fingerprints": _data_fingerprints(),
        "identity_ci95": wilson_ci(
            sum(1 for r in rows if r["gold_kind"] in ("POI", "景区") and r["correct"]),
            sum(1 for r in rows if r["gold_kind"] in ("POI", "景区"))),
        "identity_scope": {
            "n_identity_checked": sum(1 for r in rows if r["gold_kind"] in ("POI", "景区")),
            "identity_accuracy": round(
                sum(1 for r in rows if r["gold_kind"] in ("POI", "景区") and r["correct"])
                / max(1, sum(1 for r in rows if r["gold_kind"] in ("POI", "景区"))), 3),
        },
    }
    set_rows = [r for r in rows if r["gold_kind"].startswith("集合") or r["pronoun_class"] == "set"]
    member_hits = 0
    member_detail = []
    for r in set_rows:
        gold_members = [m for m in re.split(r"[、/／,，;；]|和|与", r["gold_antecedent"]) if len(m) >= 2]
        hit = any((m in r["cur_pred"]) or (r["cur_pred"] in m) for m in gold_members
                  if m not in ("无",)) if gold_members else False
        member_hits += hit
        member_detail.append({"pronoun": r["pronoun"], "gold": r["gold_antecedent"],
                              "pred": r["cur_pred"], "member_hit": hit})
    result["set_member_hit"] = {
        "n_set_cases": len(set_rows), "member_hits": member_hits,
        "member_hit_rate": round(member_hits / max(1, len(set_rows)), 3),
        "detail": member_detail,
    }
    (OUT / "evaluation.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    # Charts: per-class accuracy + pronoun distribution
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), dpi=150)
    cls = sorted(by_class)
    accs = [by_class[c][0] / by_class[c][1] for c in cls]
    ns = [by_class[c][1] for c in cls]
    bars = axes[0].bar(cls, accs, 0.5, color="#1565C0", alpha=0.85)
    for b, n in zip(bars, ns):
        axes[0].text(b.get_x() + b.get_width() / 2, b.get_height() + 0.02, f"n={n}", ha="center", fontsize=9)
    axes[0].set_ylim(0, 1.1)
    axes[0].set_title("规则消解准确率（按代词类别）")
    axes[0].spines[["top", "right"]].set_visible(False)
    pron_counter = Counter(g["pronoun"] for g in gold)
    axes[1].bar(list(pron_counter), list(pron_counter.values()), 0.6, color="#2E7D32", alpha=0.85)
    axes[1].set_title("标注样本的代词分布")
    axes[1].spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIGS / "coref_evaluation.png")
    plt.close(fig)
    print(json.dumps({k: result[k] for k in ("n", "accuracy_overall", "accuracy_by_class")}, ensure_ascii=False, indent=1))
    print("errors:", len(result["errors"]))
    for e in result["errors"][:15]:
        print(" ", e)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score", action="store_true", help="使用冻结人工标注评估规则消解")
    parser.parse_args()
    score(load_cases())
