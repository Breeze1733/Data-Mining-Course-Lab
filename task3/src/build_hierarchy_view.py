"""Experiment 3: time-dimension hierarchy view and visualization.

1. Official routes: when no period marker exists, infer the period from the start of the clock range (5-11 上午 / 11-13 中午 / 13-18 下午 / 18-23 晚上);
2. Draw “day → period → step” hierarchy tree charts for representative routes (one per scenic area);
3. Tourist side: assign the current period to POIs in entity reading order to build the tourist time hierarchy, aggregated per scenic area;
Output: time_hierarchy_summary.json, figs/tree_*.png, tourist_time_hierarchy.jsonl
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
    """Day → period → step text tree (row spacing normalized by total row count)."""
    rows: list[tuple[int, str, str, str]] = []  # (indent level, text, color, font weight)
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


def entity_period(entity: dict) -> str | None:
    """Normalized clock/period word → the four report periods (same origin as the inlined version in compare_routes)."""
    import re as _re
    groups = {"上午": ("清晨", "早晨", "早上", "上午"), "中午": ("正午", "中午"),
              "下午": ("下午", "傍晚"), "晚上": ("晚上", "夜间", "夜里", "深夜", "凌晨", "半夜")}
    if entity.get("subtype") == "时段":
        word = entity.get("normalized") or entity["text"]
        return next((k for k, vs in groups.items() if word in vs), None)
    if entity.get("subtype") not in {"时刻", "时刻区间"}:
        return None
    value = entity.get("normalized") or entity["text"]
    for k, vs in groups.items():
        if value.startswith(vs):
            return k
    m = _re.match(r"(\d{1,2}):", value)
    if not m:
        return None
    hour = int(m.group(1))
    return "上午" if 5 <= hour < 12 else "中午" if 12 <= hour < 14 else "下午" if 14 <= hour < 19 else "晚上"


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

    # Period inference (fill from the clock start when official routes lack markers)
    by_id = {p["route_id"]: p for p in parsed}
    for p in parsed:
        infer_periods(p)
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

    reps = {"九寨沟": "JZG-EXP01-R1", "黄山": "HS-O1-R8", "颐和园": "YHY-EXP10-R1"}
    tree_meta = {}
    for scenic, rid in reps.items():
        h = hier_map[rid]
        path = FIGS / f"tree_{rid}.png"
        draw_tree(h, f"{scenic}官方路线时间层级：{h['route_title']}", path)
        tree_meta[scenic] = {"route_id": rid, "fig": path.name,
                             "days": {str(d): {p: len(steps) for p, steps in day.items()}
                                      for d, day in h["days"].items()}}

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
    }
    (OUT / "time_hierarchy_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"trees": list(tree_meta), "official": {k: dict(v) for k, v in official_period_pois.items()},
                      "tourist": tourist_stats}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
