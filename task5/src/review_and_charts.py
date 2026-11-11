"""Score frozen reviews, plot extraction results and export the Excel mapping."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
FIGS = OUT / "figs"
sys.stdout.reconfigure(encoding="utf-8")
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

KIND_CN = {"explicit": "显式", "inferred": "推断", "absent": "无显式条件"}


def load() -> list[dict]:
    return [json.loads(l) for l in (OUT / "conditional_pairs.jsonl").open(encoding="utf-8")]


def load_mapping() -> list[dict]:
    return json.loads((OUT / "mapping_table.json").read_text(encoding="utf-8"))


def _norm5(t: str) -> str:
    return re.sub(r"[\s，,。；;、！？!?\[\]()【】的了吗呢啊呀的]", "", t or "")


def _extraction_fingerprints() -> dict:
    out = {}
    for key, name in (("conditional_pairs", "conditional_pairs.jsonl"),
                      ("mapping_table", "mapping_table.json")):
        p = OUT / name
        out[key] = hashlib.sha256(p.read_bytes()).hexdigest()[:12] if p.exists() else None
    return out


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


sys.path.insert(0, str(ROOT.parent))
from common.fingerprints import data_fingerprints as _data_fingerprints


def sample(per_cell: int = 6, seed: int = 20261111, out_path: Path | None = None,
           force: bool = False) -> None:
    """Draw a deterministic stratified review sample from the current mapping table."""
    out_path = out_path or (OUT / "review_dev.json")
    mapping = load_mapping()
    if not mapping or "pair_id" not in mapping[0]:
        raise SystemExit("mapping_table.json has no pair_id; rerun extract_conditionals.py first")

    if out_path.exists() and not force:
        try:
            old = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            old = None
        if (isinstance(old, dict) and old.get("sample_meta")
                and any(r.get("verdict") not in (None, "", "unreviewed")
                        for r in old.get("reviews", []))):
            raise SystemExit(f"{out_path} already holds annotated verdicts; use --force to re-sample")

    cells: dict[tuple, list[dict]] = defaultdict(list)
    for row in mapping:
        cells[(row["pattern"], row["scenic_area"])].append(row)

    rng = random.Random(seed)
    picked = []
    for key in sorted(cells):
        pool = sorted(cells[key], key=lambda r: r["pair_id"])
        rng.shuffle(pool)
        picked.extend(pool[: min(per_cell, len(pool))])
    picked.sort(key=lambda r: (r["pattern"], r["scenic_area"], r["row_id"]))

    doc = {
        "n": len(picked),
        "sample_meta": {
            "source": "output/mapping_table.json",
            "strata": ["pattern", "scenic_area"],
            "per_cell": per_cell,
            "seed": seed,
            "n_cells": len(cells),
            "generated_by": (f"python task5/src/review_and_charts.py --sample "
                             f"--per-cell {per_cell} --seed {seed}"),
            "extraction_fingerprint": _extraction_fingerprints(),
        },
        "annotation": {
            "annotated_by": ("AI-assisted single annotator (Claude Code agent), "
                             "not independent human annotation"),
            "method": "Each row judged against its stored sentence; verdict in correct|boundary|wrong",
            "instructions": (
                "correct=condition span (or a correct 'no explicit condition' judgement) and "
                "advice are both right; boundary=clause boundary imperfect or condition only weakly "
                "inferred but materially usable; wrong=not tourist advice, mismatch between condition "
                "and advice, a real condition was missed, or the advice is wrong"),
            "completed": False,
            "date": None,
        },
        "reviews": [{
            "pair_id": r["pair_id"], "row_id": r["row_id"],
            "record_id": r["record_id"], "pattern": r["pattern"],
            "scenic_area": r["scenic_area"],
            "condition_text": r["condition_text"],
            "condition_span": r["condition_span"],
            "condition_kind": r["condition_kind"],
            "condition_label": r["condition_label"],
            "condition_type_verified": r["condition_type_verified"],
            "suggestion_text": r["suggestion_text"],
            "sentence": r["sentence"],
            "frequency": r["frequency"],
            "verdict": "unreviewed", "note": "",
        } for r in picked],
    }
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"output": str(out_path), "n": len(picked),
                      "per_cell": per_cell, "seed": seed}, ensure_ascii=False))


def score() -> None:
    doc = json.loads((OUT / "review_dev.json").read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or "sample_meta" not in doc:
        raise SystemExit("review_dev.json is legacy (no sample_meta); rerun --sample first")
    reviews = doc["reviews"]
    if not doc.get("annotation", {}).get("completed"):
        raise SystemExit("review_dev.json annotation.completed is false; finish annotation first")

    mapping = load_mapping()
    by_id = {r["pair_id"]: r for r in mapping}
    drift = []
    for r in reviews:
        cur = by_id.get(r["pair_id"])
        if cur is None:
            drift.append((r["pair_id"], "missing"))
            continue
        for field in ("record_id", "pattern", "scenic_area",
                      "condition_text", "suggestion_text", "sentence"):
            if r.get(field) != cur.get(field):
                drift.append((r["pair_id"], field))
    if drift:
        raise SystemExit(f"stale review sample: {len(drift)} drift(s); rerun --sample and re-annotate\n"
                         f"{drift[:5]}")

    fps = _extraction_fingerprints()
    if doc["sample_meta"].get("extraction_fingerprint") != fps:
        raise SystemExit("review sample fingerprint does not match current extraction; rerun --sample")

    bad = [r["pair_id"] for r in reviews if r.get("verdict") not in ("correct", "boundary", "wrong")]
    if bad:
        raise SystemExit(f"unreviewed/invalid verdicts: {len(bad)}; examples {bad[:5]}")

    n = len(reviews)
    verdicts = Counter(r["verdict"] for r in reviews)
    correct_n = verdicts.get("correct", 0)
    boundary_n = verdicts.get("boundary", 0)
    lenient_n = correct_n + boundary_n

    def group(key_fn):
        buckets = defaultdict(Counter)
        for r in reviews:
            buckets[key_fn(r)][r["verdict"]] += 1
        out = {}
        for key, counts in buckets.items():
            total = sum(counts.values())
            out[key] = {
                "n": total,
                "correct": counts.get("correct", 0),
                "boundary": counts.get("boundary", 0),
                "wrong": counts.get("wrong", 0),
                "strict_accuracy": round(counts.get("correct", 0) / total, 3) if total else None,
                "boundary_rate": round(counts.get("boundary", 0) / total, 3) if total else None,
            }
        return out

    result = {
        "n": n,
        "verdicts": dict(verdicts),
        "strict_accuracy": round(correct_n / n, 3) if n else None,
        "strict_ci95": wilson_ci(correct_n, n),
        "boundary_rate": round(boundary_n / n, 3) if n else None,
        "boundary_ci95": wilson_ci(boundary_n, n),
        "lenient_accuracy_correct_or_boundary": round(lenient_n / n, 3) if n else None,
        "lenient_ci95": wilson_ci(lenient_n, n),
        "by_pattern": group(lambda r: r["pattern"]),
        "by_scenic": group(lambda r: r["scenic_area"]),
        "by_condition_kind": group(lambda r: r["condition_kind"]),
        "alignment_with_current_extraction": {
            "reviewed": n, "matched": n, "missing": 0, "content_drift": 0},
        "sample_fingerprint_matches_current": True,
        "sample_meta": doc["sample_meta"],
        "annotated_by": doc["annotation"].get("annotated_by"),
        "data_fingerprints": {**_data_fingerprints(), **fps},
    }
    (OUT / "review_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


def charts() -> None:
    mapping = load_mapping()
    FIGS.mkdir(parents=True, exist_ok=True)

    # Chart 1: verified condition type × scenic area (weighted by frequency)
    totals = Counter()
    areas = ["黄山", "九寨沟", "颐和园"]
    weighted = {a: Counter() for a in areas}
    for m in mapping:
        weighted[m["scenic_area"]][m["condition_type_verified"]] += m["frequency"]
        totals[m["condition_type_verified"]] += m["frequency"]
    types = [kind for kind, _ in totals.most_common()]
    import numpy as np
    x = np.arange(len(types))
    width = 0.26
    fig, ax = plt.subplots(figsize=(10.5, 4.6), dpi=150)
    for i, a in enumerate(areas):
        vals = [weighted[a].get(t, 0) for t in types]
        ax.bar(x + (i - 1) * width, vals, width, label=a, alpha=0.85)
    ax.set_xticks(x, types, rotation=20)
    ax.set_ylabel("条件→建议对数量（含频次）")
    ax.set_title("核验条件类型 × 景区分布（含未给出条件）")
    ax.legend()
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIGS / "cond_type_by_scenic.png")
    plt.close(fig)

    # Chart 2: crowd-class breakdown (rows with no extractable crowd condition kept separate)
    crowd = Counter()
    for m in mapping:
        if m["condition_type_verified"] == "人群":
            text = m["condition_text"] or m["condition_label"]
            for w, label in (("老人", "老人"), ("孩子", "孩子"), ("小孩", "孩子"), ("儿童", "孩子"),
                             ("婴儿", "孩子"), ("亲子", "亲子"), ("带娃", "亲子"), ("情侣", "情侣"),
                             ("夫妻", "情侣"), ("孕妇", "孕妇"), ("腿脚", "行动不便"), ("体力", "体力有限"),
                             ("新手", "新手"), ("第一次", "初次游览"), ("学生", "学生"), ("家庭", "家庭"),
                             ("恐高", "恐高"), ("晕车", "晕车")):
                if w in text:
                    crowd[label] += m["frequency"]
                    break
            else:
                crowd["未细分"] += m["frequency"]
        elif m["condition_kind"] == "absent" and m["condition_type"] == "人群":
            crowd["无显式条件（人群桶）"] += m["frequency"]
    fig, ax = plt.subplots(figsize=(8.5, 4.2), dpi=150)
    items = crowd.most_common()
    ax.bar([k for k, _ in items], [v for _, v in items], 0.55, color="#C62828", alpha=0.85)
    ax.set_title("人群类条件建议的游客类型分布")
    ax.set_ylabel("对数（含频次）")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIGS / "crowd_breakdown.png")
    plt.close(fig)

    # Chart 3: condition provenance × extraction pattern
    provenance = defaultdict(Counter)
    for m in mapping:
        provenance[m["pattern"]][m["condition_kind"]] += m["frequency"]
    patterns = sorted(provenance)
    kinds = ["explicit", "inferred", "absent"]
    colors = {"explicit": "#2E7D32", "inferred": "#F9A825", "absent": "#9E9E9E"}
    fig, ax = plt.subplots(figsize=(9.5, 4.4), dpi=150)
    bottom = np.zeros(len(patterns))
    for kind in kinds:
        vals = np.array([provenance[p].get(kind, 0) for p in patterns])
        ax.bar(patterns, vals, 0.55, bottom=bottom, label=KIND_CN[kind], color=colors[kind], alpha=0.9)
        bottom += vals
    ax.set_ylabel("对数（含频次）")
    ax.set_title("条件片段来源 × 抽取模式")
    ax.legend()
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIGS / "condition_provenance.png")
    plt.close(fig)

    print(json.dumps({"figs": ["cond_type_by_scenic.png", "crowd_breakdown.png",
                               "condition_provenance.png"],
                      "crowd": dict(crowd)}, ensure_ascii=False))


def export_xlsx():
    mapping = load_mapping()
    stats = json.loads((OUT / "extraction_stats.json").read_text(encoding="utf-8"))
    review = json.loads((OUT / "review_summary.json").read_text(encoding="utf-8"))
    if not mapping or "condition_kind" not in mapping[0]:
        raise SystemExit("mapping_table.json lacks condition fields; rerun extract_conditionals.py first")

    wb = Workbook()
    # Fixed docProps timestamps: identical content yields identical bytes, keeping rebuilt artifacts deterministic
    wb.properties.created = wb.properties.modified = datetime(2026, 1, 1)
    ws = wb.active
    ws.title = "条件-建议映射表"
    headers = ["条件类型（核验）", "条件描述（原文）", "条件来源", "条件标签（旧口径）",
               "建议内容", "触发词", "抽取模式", "景区", "频次", "条件位置", "来源记录（前5）"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    order = {"人群": 0, "天气": 1, "时间": 2, "装备": 3, "预约票务": 4, "交通": 5,
             "体力安全": 6, "拍照": 7, "住宿": 8, "美食": 9, "一般": 10, "其他": 11, "无": 12}
    for m in sorted(mapping, key=lambda x: (order.get(x["condition_type_verified"], 13), -x["frequency"])):
        span = f"{m['condition_span'][0]}-{m['condition_span'][1]}" if m.get("condition_span") else ""
        ws.append([m.get("condition_type_verified", ""),
                   m["condition_text"][:120] if m["condition_text"] else "（无显式条件）",
                   KIND_CN.get(m["condition_kind"], m["condition_kind"]),
                   (m.get("condition_label") or "")[:60],
                   m["suggestion_text"][:200], m["trigger"], m["pattern"],
                   m["scenic_area"], m["frequency"], span,
                   "；".join(m["sources"][:5])])
    for col, w in zip("ABCDEFGHIJK", (12, 34, 11, 22, 44, 8, 14, 9, 7, 8, 30)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"

    ws2 = wb.create_sheet("统计与抽检")
    ws2.append(["指标", "值"])
    for c in ws2[1]:
        c.font = Font(bold=True)
    for k in ("raw_pairs", "after_dedup", "duplicates_merged",
              "nonempty_condition_pairs", "nonempty_condition_rate",
              "nonempty_condition_rows", "nonempty_condition_row_rate",
              "condition_span_invalid", "condition_type_mismatch",
              "by_condition_kind", "by_absent_reason", "by_condition_type_verified",
              "by_pattern", "by_scenic"):
        val = stats[k]
        ws2.append([k, json.dumps(val, ensure_ascii=False) if isinstance(val, dict) else val])
    ws2.append(["复核", (
        f"n={review['n']}；strict {review['strict_accuracy']:.0%}"
        f"（95%CI {review['strict_ci95']['lo']:.3f}–{review['strict_ci95']['hi']:.3f}）；"
        f"boundary {review['boundary_rate']:.0%}；"
        f"lenient {review['lenient_accuracy_correct_or_boundary']:.0%}；"
        f"alignment {review['alignment_with_current_extraction']}")])
    ws2.column_dimensions["A"].width = 26
    ws2.column_dimensions["B"].width = 110

    out = OUT / "conditional_mapping_table.xlsx"
    wb.save(out)
    _normalize_xlsx(out)
    print(json.dumps({"output": out.as_posix(), "rows": len(mapping)}, ensure_ascii=False))


def _normalize_xlsx(path: Path) -> None:
    """openpyxl forces zip entry timestamps and core.xml's modified to the current moment; rewrite both to fixed values:
    identical content yields identical bytes (artifact determinism)."""
    stamp = b"2026-01-01T00:00:00Z"
    core_mod = (b'<dcterms:modified xmlns:dcterms="http://purl.org/dc/terms/" '
                b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                b'xsi:type="dcterms:W3CDTF">' + stamp + b"</dcterms:modified>")
    src = zipfile.ZipFile(io.BytesIO(path.read_bytes()))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                data = re.sub(rb"<dcterms:modified[^>]*>.*?</dcterms:modified>", core_mod, data)
            fixed = zipfile.ZipInfo(info.filename, date_time=(1980, 1, 1, 0, 0, 0))
            fixed.compress_type = info.compress_type
            fixed.external_attr = info.external_attr
            dst.writestr(fixed, data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--charts", action="store_true")
    parser.add_argument("--xlsx", action="store_true")
    parser.add_argument("--per-cell", type=int, default=6)
    parser.add_argument("--seed", type=int, default=20261111)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sample-out", type=Path, default=None)
    args = parser.parse_args()
    if args.sample:
        sample(args.per_cell, args.seed, args.sample_out, args.force)
    if args.score:
        score()
    if args.xlsx:
        export_xlsx()
    if args.charts:
        charts()
