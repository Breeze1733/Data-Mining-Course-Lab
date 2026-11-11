"""Score frozen reviews, plot extraction results and export the Excel mapping."""
from __future__ import annotations

import argparse
import io
import json
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

def load() -> list[dict]:
    return [json.loads(l) for l in (OUT / "conditional_pairs.jsonl").open(encoding="utf-8")]


def _norm5(t: str) -> str:
    return re.sub(r"[\s，,。；;、！？!?\[\]()【】的了吗呢啊呀的]", "", t or "")


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


def score() -> None:
    data = json.loads((OUT / "review_dev.json").read_text(encoding="utf-8"))["reviews"]
    # Align with the current extraction — check whether reviewed rows are still extracted by the current rules (identical/changed/missing),
    # so extractor regressions (misextraction/missed extraction) are no longer invisible to the metrics
    mapping = json.loads((OUT / "mapping_table.json").read_text(encoding="utf-8"))
    mrows = mapping["rows"] if isinstance(mapping, dict) else mapping
    pair_index = {(r["scenic_area"], _norm5(r["condition_text"]), _norm5(r["suggestion_text"]))
                  for r in mrows}
    sentence_index = {_norm5(r["sentence"]) for r in mrows}
    align = Counter()
    for r in data:
        key = (r["scenic_area"], _norm5(r["condition"]), _norm5(r["suggestion"]))
        if key in pair_index:
            align["retained_identical"] += 1
        elif _norm5(r["sentence"]) in sentence_index:
            align["changed_same_sentence"] += 1
        else:
            align["missing"] += 1
    c = Counter(r["verdict"] for r in data)
    by_pattern = defaultdict(lambda: Counter())
    for r in data:
        by_pattern[r["pattern"].split("_")[0]][r["verdict"]] += 1
    result = {"n": len(data), "verdicts": dict(c),
              "correct_ci95": wilson_ci(c.get("correct", 0), len(data)),
              "data_fingerprints": _data_fingerprints(),
              "alignment_with_current_extraction": dict(align),
              "by_pattern": {k: dict(v) for k, v in by_pattern.items()}}
    (OUT / "review_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


def charts() -> None:
    mapping = json.loads((OUT / "mapping_table.json").read_text(encoding="utf-8"))
    FIGS.mkdir(parents=True, exist_ok=True)

    # Chart 1: condition type × scenic area (weighted by frequency)
    totals = Counter()
    areas = ["黄山", "九寨沟", "颐和园"]
    weighted = {a: Counter() for a in areas}
    for m in mapping:
        weighted[m["scenic_area"]][m["condition_type"]] += m["frequency"]
        totals[m["condition_type"]] += m["frequency"]
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
    ax.set_title("条件性建议的类型 × 景区分布")
    ax.legend()
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIGS / "cond_type_by_scenic.png")
    plt.close(fig)

    # Chart 2: crowd-class breakdown (visitor types)
    crowd = Counter()
    for m in mapping:
        if m["condition_type"] == "人群":
            for w, label in (("老人", "老人"), ("孩子", "孩子"), ("小孩", "孩子"), ("儿童", "孩子"),
                             ("婴儿", "孩子"), ("亲子", "亲子"), ("带娃", "亲子"), ("情侣", "情侣"),
                             ("夫妻", "情侣"), ("孕妇", "孕妇"), ("腿脚", "行动不便"), ("体力", "体力有限"),
                             ("新手", "新手"), ("第一次", "初次游览"), ("学生", "学生"), ("家庭", "家庭"),
                             ("恐高", "恐高"), ("晕车", "晕车")):
                if w in m["condition_text"]:
                    crowd[label] += m["frequency"]
                    break
            else:
                crowd["未细分"] += m["frequency"]
    fig, ax = plt.subplots(figsize=(8.5, 4.2), dpi=150)
    items = crowd.most_common()
    ax.bar([k for k, _ in items], [v for _, v in items], 0.55, color="#C62828", alpha=0.85)
    ax.set_title("人群类条件建议的游客类型分布")
    ax.set_ylabel("对数（含频次）")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIGS / "crowd_breakdown.png")
    plt.close(fig)
    print(json.dumps({"figs": ["cond_type_by_scenic.png", "crowd_breakdown.png"],
                      "crowd": dict(crowd)}, ensure_ascii=False))


def export_xlsx():
    mapping = json.loads((OUT / "mapping_table.json").read_text(encoding="utf-8"))
    stats = json.loads((OUT / "extraction_stats.json").read_text(encoding="utf-8"))
    review = json.loads((OUT / "review_summary.json").read_text(encoding="utf-8"))

    wb = Workbook()
    # Fixed docProps timestamps: identical content yields identical bytes, keeping rebuilt artifacts deterministic
    wb.properties.created = wb.properties.modified = datetime(2026, 1, 1)
    ws = wb.active
    ws.title = "条件-建议映射表"
    headers = ["条件类型", "条件描述", "建议内容", "触发词", "抽取模式", "景区", "频次", "来源记录（前5）"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    order = {"人群": 0, "天气": 1, "时间": 2, "装备": 3, "预约票务": 4, "交通": 5,
             "体力安全": 6, "一般": 7, "其他": 8}
    for m in sorted(mapping, key=lambda x: (order.get(x["condition_type"], 9), -x["frequency"])):
        ws.append([m["condition_type"], m["condition_text"][:120], m["suggestion_text"][:200],
                   m["trigger"], m["pattern"], m["scenic_area"], m["frequency"],
                   "；".join(m["sources"][:5])])
    for col, w in zip("ABCDEFGH", (10, 34, 44, 8, 14, 9, 7, 30)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"

    ws2 = wb.create_sheet("统计与抽检")
    ws2.append(["指标", "值"])
    for c in ws2[1]:
        c.font = Font(bold=True)
    for k in ("raw_pairs", "after_dedup", "duplicates_merged"):
        ws2.append([k, stats[k]])
    ws2.append(["by_pattern", json.dumps(stats["by_pattern"], ensure_ascii=False)])
    ws2.append(["by_condition_type", json.dumps(stats["by_condition_type"], ensure_ascii=False)])
    ws2.append(["by_scenic", json.dumps(stats["by_scenic"], ensure_ascii=False)])
    ws2.append(["人工抽检", json.dumps(review["verdicts"], ensure_ascii=False) +
                f"（n={review['n']}，严格正确 {review['verdicts'].get('correct',0)/review['n']:.0%}）"])
    ws2.column_dimensions["A"].width = 22
    ws2.column_dimensions["B"].width = 90

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
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--charts", action="store_true")
    parser.add_argument("--xlsx", action="store_true")
    args = parser.parse_args()
    if args.score:
        score()
    elif args.xlsx:
        export_xlsx()
    if args.charts:
        charts()
