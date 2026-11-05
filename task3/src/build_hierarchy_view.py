"""实验3：时间维度层级视图与可视化。

1. 官方路线：无时段标记时按时钟范围起点推断时段（5-11上午 / 11-13中午 / 13-18下午 / 18-23晚上）；
2. 代表路线绘制“天 → 时段 → 步骤”层级树图（每景区一张）；
3. 游客侧：按实体阅读顺序为 POI 赋当前时段，得到游客时间层级，按景区聚合统计；
输出：time_hierarchy_summary.json、figs/tree_*.png、tourist_time_hierarchy.jsonl
"""
from __future__ import annotations

import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
TASK2 = ROOT.parent / "task2"
OUT = ROOT / "output"
FIGS = OUT / "figs"

if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

PERIOD_ORDER = ("上午", "中午", "下午", "晚上", "未标注时段")


def hour_of(time_range: str):
    m = re.match(r"(\d{1,2})[:：点](\d{1,2})", time_range or "")
    return int(m.group(1)) if m else None


def period_from_hour(hour: int) -> str:
    return ("上午" if 5 <= hour < 11 else "中午" if 11 <= hour < 13 else
            "下午" if 13 <= hour < 18 else "晚上" if 18 <= hour < 24 else "未标注时段")


def infer_periods(parsed: dict) -> None:
    current = None
    for s in parsed["steps"]:
        if not s["period"]:
            if s["time_range"] and (h := hour_of(s["time_range"])) is not None:
                s["period"] = period_from_hour(h)
        current = s["period"] or current
        s["period"] = s["period"] or current


def draw_tree(hierarchy: dict, title: str, path: Path):
    """天 → 时段 → 步骤 文本树（行距按总行数归一）。"""
    rows: list[tuple[int, str, str, str]] = []  # (缩进级别, 文本, 颜色, 字重)
    for day in sorted(hierarchy["days"]):
        rows.append((0, f"第{day}天", "#1565C0", "bold"))
        day_map = hierarchy["days"][day]
        periods = [p for p in PERIOD_ORDER if p in day_map] +                   [p for p in day_map if p not in PERIOD_ORDER]
        for period in periods:
            steps = day_map[period]
            rows.append((1, f"{period}（{len(steps)} 步）", "#C62828", "normal"))
            for st in steps:
                label = " → ".join(st["pois"]) if st["pois"] else st["text"][:22]
                extra = f'  [{st["time_range"]}]' if st["time_range"] else ""
                extra += f'  ({st["duration"]})' if st["duration"] else ""
                rows.append((2, f"· {label}{extra}", "#333333", "normal"))
    n = len(rows)
    fig_h = max(3.0, 0.30 * n + 0.8)
    fig, ax = plt.subplots(figsize=(10.5, fig_h), dpi=150)
    ax.axis("off")
    ax.set_ylim(0, 1)
    ax.set_xlim(0, 1)
    step = 1.0 / (n + 1.2)
    y = 1.0 - 0.4 * step
    for level, text, color, weight in rows:
        ax.text(0.02 + 0.055 * level, y, text, fontsize=9.5 if level < 2 else 8.5,
                color=color, fontweight=weight, family="SimHei")
        y -= step
    ax.set_title(title, fontsize=11, family="SimHei")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


from time_periods import entity_period


def tourist_time_hierarchy() -> dict:
    ents = [json.loads(l) for l in (TASK2 / "output/exp2/entities_refined.jsonl").open(encoding="utf-8")]
    per_scenic: dict[str, Counter] = defaultdict(Counter)
    records = []
    for rec in ents:
        if rec["text_type"] != "travelogue":
            continue
        current = None
        period_pois = defaultdict(list)
        for e in rec["entities"]:
            if e["type"] == "时间节点":
                period = entity_period(e)
                if period:
                    current = period
            elif e["type"] == "景点POI" and e["subtype"] == "景点" and e.get("in_scenic", True) and current:
                bucket = ("上午" if current in ("清晨", "早上", "上午") else "中午" if current == "中午" else
                          "下午" if current in ("下午", "傍晚") else "晚上" if current in ("晚上", "夜里", "深夜") else
                          "全天" if current == "全天" else "未标注时段")
                period_pois[bucket].append(e["canonical"])
        if period_pois:
            records.append({"record_id": rec["record_id"], "scenic_area": rec["scenic_area"],
                            "period_pois": {k: v for k, v in period_pois.items()}})
            for period, pois in period_pois.items():
                per_scenic[rec["scenic_area"]][period] += len(set(pois))
    with (OUT / "tourist_time_hierarchy.jsonl").open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {scenic: dict(c) for scenic, c in per_scenic.items()}


def main() -> int:
    FIGS.mkdir(parents=True, exist_ok=True)
    parsed = [json.loads(l) for l in (OUT / "parsed_routes.jsonl").open(encoding="utf-8")]
    hierarchies = [json.loads(l) for l in (OUT / "time_hierarchy.jsonl").open(encoding="utf-8")]

    # 时段推断（官方路线缺标记时按时钟起点补）
    by_id = {p["route_id"]: p for p in parsed}
    for p in parsed:
        infer_periods(p)
    # 重写 time_hierarchy.jsonl（含推断结果）
    hier_map = {}
    for p in parsed:
        h = {"route_id": p["route_id"], "scenic_area": p["scenic_area"], "route_title": p["route_title"],
             "days": {}, "periods_present": []}
        for s in p["steps"]:
            day = h["days"].setdefault(s["day"], {})
            day.setdefault(s["period"] or "未标注时段", []).append({
                "step_no": s["step_no"], "text": s["text"],
                "pois": [x["normalized"] for x in s["pois"]],
                "transport": s["transport"], "time_range": s["time_range"], "duration": s["duration"],
                "lodging": s.get("lodging", False)})
        h["periods_present"] = sorted({period for d in h["days"].values() for period in d})
        hier_map[p["route_id"]] = h
    with (OUT / "time_hierarchy.jsonl").open("w", encoding="utf-8") as fh:
        for h in hier_map.values():
            fh.write(json.dumps(h, ensure_ascii=False) + "\n")

    # 代表路线树图
    reps = {"九寨沟": "JZG-EXP01-R1", "黄山": "HS-O1-R8", "颐和园": "YHY-EXP10-R1"}
    tree_meta = {}
    for scenic, rid in reps.items():
        h = hier_map[rid]
        path = FIGS / f"tree_{rid}.png"
        draw_tree(h, f"{scenic}官方路线时间层级：{h['route_title']}", path)
        tree_meta[scenic] = {"route_id": rid, "fig": path.name,
                             "days": {str(d): {p: len(steps) for p, steps in day.items()}
                                      for d, day in h["days"].items()}}

    # 官方层级聚合：各景区时段覆盖的 POI 数
    official_period_pois: dict[str, Counter] = defaultdict(Counter)
    for p in parsed:
        if not p["ordered_route"]:
            continue
        for s in p["steps"]:
            for poi in s["pois"]:
                official_period_pois[p["scenic_area"]][s["period"] or "未标注时段"] += 1

    tourist_stats = tourist_time_hierarchy()

    summary = {
        "representative_trees": tree_meta,
        "official_period_poi_counts": {k: dict(v) for k, v in official_period_pois.items()},
        "tourist_period_poi_counts": tourist_stats,
        "note": "颐和园/黄山官方路线大多不携带时段信息（节点链式指南），时段结构主要来自九寨沟官方文本与游客自述的时间轴",
    }
    (OUT / "time_hierarchy_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"trees": list(tree_meta), "official": {k: dict(v) for k, v in official_period_pois.items()},
                      "tourist": tourist_stats}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
