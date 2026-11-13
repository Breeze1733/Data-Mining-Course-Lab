"""Human-audit tool for the conditional-advice extraction (任务书考核项：人工抽查误抽/漏抽/边界切分).

Modes (repo root):
  python task5/src/spot_check.py --sample [N]      Stratified sample of mapping rows -> resources/eval/conditional_spot_checks.json
  python task5/src/spot_check.py --miss-sample [N] Sample marker-bearing sentences that produced no pair (漏抽排查)
  python task5/src/spot_check.py --score           Score filled verdicts and write review_summary back

Verdicts (human-filled): correct / boundary / incorrect；issue tags: 误抽 | 边界切分 | 条件不匹配 | 非游览主题；
miss verdicts: missed (真漏抽) / correctly_skipped (无建议，跳过正确)。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
EVAL = ROOT / "resources" / "eval"
TASK1 = ROOT.parent / "task1"
EVAL.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "src"))
from extract_conditionals import SENT_SPLIT, extract_from_sentence, norm, skip_sentence  # noqa: E402

AUDIT_PATH = EVAL / "conditional_spot_checks.json"


def load_mapping() -> list[dict]:
    return json.loads((OUT / "mapping_table.json").read_text(encoding="utf-8"))


def sample(n: int) -> None:
    mapping = load_mapping()
    rng = random.Random(42)
    by_pattern: dict[str, list[dict]] = {}
    for r in mapping:
        by_pattern.setdefault(r["pattern"], []).append(r)
    patterns = sorted(by_pattern)
    # Proportional per pattern with a floor of 2 rows per pattern (small patterns stay auditable).
    quota = {p: max(2, round(n * len(rows) / len(mapping))) for p, rows in by_pattern.items()}
    samples = []
    for p in patterns:
        rows = sorted(by_pattern[p], key=lambda r: r["row_id"])
        rng.shuffle(rows)
        for r in rows[:quota[p]]:
            samples.append({
                "row_id": r["row_id"], "pattern": p, "scenic_area": r["scenic_area"],
                "condition_text": r["condition_text"], "suggestion_text": r["suggestion_text"],
                "sentence": r["sentence"], "verdict": "", "issue": "", "note": ""})
    data = {"seed": 42, "n_requested": n, "samples": samples}
    AUDIT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"file": AUDIT_PATH.as_posix(), "sampled": len(samples),
                      "by_pattern": dict(Counter(s["pattern"] for s in samples))}, ensure_ascii=False))


def miss_sample(n: int) -> None:
    """Sentences carrying a conditional/advice marker but yielding no extracted pair.

    The candidate pool replays the main pipeline's per-sentence filters (attribution, length,
    boilerplate) so every listed sentence is one the extractor actually saw and skipped.
    """
    import sys as _sys
    _sys.path.insert(0, str(ROOT.parent / "task4/src"))
    from attribute_sentences import Attributor

    data = json.loads(AUDIT_PATH.read_text(encoding="utf-8")) if AUDIT_PATH.exists() else {}
    attr = Attributor()
    rows = [json.loads(l) for l in (TASK1 / "data/processed/dataset_clean.jsonl").open(encoding="utf-8") if l.strip()]
    candidates = []
    for row in rows:
        sents = [s.strip() for s in SENT_SPLIT.split(row["clean_content"])]
        labels = attr.attribute_record(row["scenic_area"], sents,
                                       text_type=row.get("text_type", "travelogue"))
        for sent, lab in zip(sents, labels):
            if lab == "景区外" or not (8 <= len(sent) <= 160) or skip_sentence(sent):
                continue
            if not any(m in sent for m in ("如果", "要是", "假如", "建议", "推荐", "最好", "记得", "千万", "不要", "别", "避免", "慎", "可以")):
                continue
            if extract_from_sentence(sent):
                continue
            # Bare “可以” capability statements are excluded by design — do not list them as misses.
            if "可以" in sent and not any(m in sent for m in ("如果", "要是", "假如", "建议", "推荐", "最好", "记得", "千万", "不要", "避免", "慎")):
                continue
            candidates.append({"record_id": row["record_id"], "scenic_area": row["scenic_area"],
                               "sentence": sent, "verdict": "", "note": ""})
    rng = random.Random(42)
    rng.shuffle(candidates)
    data["miss_samples"] = candidates[:n]
    AUDIT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"miss_pool": len(candidates), "miss_sampled": len(data["miss_samples"])},
                     ensure_ascii=False))


def score() -> None:
    data = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    samples = data["samples"]
    filled = [s for s in samples if s.get("verdict")]
    verdicts = Counter(s["verdict"] for s in filled)
    issues = Counter(i for s in filled for i in (s.get("issue") or "").split("、") if i)
    misses = data.get("miss_samples", [])
    miss_filled = [m for m in misses if m.get("verdict")]
    miss_verdicts = Counter(m["verdict"] for m in miss_filled)
    n = len(filled)
    summary = {
        "n": n,
        "total_sampled": len(samples),
        "verdicts": {"correct": verdicts.get("correct", 0), "boundary": verdicts.get("boundary", 0),
                     "incorrect": verdicts.get("incorrect", 0)},
        "strict_precision": round(verdicts.get("correct", 0) / n, 3) if n else None,
        "lenient_precision": round((verdicts.get("correct", 0) + verdicts.get("boundary", 0)) / n, 3) if n else None,
        "issues": dict(issues),
        "miss_check": {"n": len(miss_filled), "pool_listed": len(misses),
                       "missed": miss_verdicts.get("missed", 0),
                       "correctly_skipped": miss_verdicts.get("correctly_skipped", 0)},
    }
    data["review_summary"] = summary
    AUDIT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="按模式分层抽取映射行进入工审计文件")
    ap.add_argument("--miss-sample", type=int, default=0, help="抽取含触发词但未产出的句子供漏抽排查")
    ap.add_argument("--score", action="store_true", help="汇总已填写的判定并写回 review_summary")
    args = ap.parse_args()
    if args.sample:
        sample(args.sample)
    if args.miss_sample:
        miss_sample(args.miss_sample)
    if args.score:
        score()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
