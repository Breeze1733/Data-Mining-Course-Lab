"""实验3：游客实际路线提取 + 官方/游客路线对比（高阶任务）。

游客路线：从实验2实体输出中按阅读顺序取景区内 POI 序列（连续去重，≥4 个不同 POI）。
对比维度：①景点覆盖度（游客路线对官方 POI 集合的覆盖、Jaccard）；②顺序一致性（公共 POI ≥5 时
         计算 Kendall tau）；③时间分配（官方时段-时长分布 vs 游客文本时段词分布）。
输出：task3/output/tourist_routes.jsonl、official_vs_tourist.json、figs/
"""
from __future__ import annotations

import io
import json
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
TASK1 = ROOT.parent / "task1"
TASK2 = ROOT.parent / "task2"
OUT = ROOT / "output"
FIGS = OUT / "figs"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

PERIODS = ("上午", "中午", "下午", "晚上")


def kendall_tau(a: list, b: list) -> float:
    """两个序列（同一集合的不同排序）的 Kendall tau。"""
    pairs = list(combinations(range(len(a)), 2))
    if not pairs:
        return float("nan")
    concordant = discordant = 0
    for i, j in pairs:
        sign_a = (a.index(a[i]), a.index(a[j]))
        sign_b = (b.index(a[i]), b.index(a[j]))
        da = sign_a[0] - sign_a[1]
        db = sign_b[0] - sign_b[1]
        if da * db > 0:
            concordant += 1
        elif da * db < 0:
            discordant += 1
    return (concordant - discordant) / (concordant + discordant) if (concordant + discordant) else float("nan")


def extract_tourist_routes() -> list[dict]:
    ents = [json.loads(l) for l in (TASK2 / "output/exp2/entities_refined.jsonl").open(encoding="utf-8")]
    routes = []
    for rec in ents:
        if rec["text_type"] != "travelogue":
            continue
        pois = []
        for e in rec["entities"]:
            # 只取主景区内 POI（in_scenic 标记），排除多景点游记的跨景区实体
            if e["type"] == "景点POI" and e["subtype"] == "景点" and e.get("in_scenic", True):
                if not pois or pois[-1] != e["canonical"]:
                    pois.append(e["canonical"])
        distinct = list(dict.fromkeys(pois))
        if len(distinct) >= 4:
            routes.append({
                "record_id": rec["record_id"], "scenic_area": rec["scenic_area"],
                "source_platform": rec["source_platform"],
                "poi_sequence": pois, "distinct_pois": distinct,
                "n_distinct": len(distinct),
            })
    return routes


def official_routes_by_scenic() -> dict[str, list[dict]]:
    parsed = [json.loads(l) for l in (OUT / "parsed_routes.jsonl").open(encoding="utf-8")]
    by_scenic: dict[str, list[dict]] = defaultdict(list)
    for p in parsed:
        if p["ordered_route"] and p["pois_in_order"]:
            # 连续去重后的官方 POI 序列
            seq = []
            for poi in p["pois_in_order"]:
                if not seq or seq[-1] != poi:
                    seq.append(poi)
            p["norm_sequence"] = seq
            by_scenic[p["scenic_area"]].append(p)
    return by_scenic


def duration_minutes(dur: str) -> int | None:
    if not dur:
        return None
    if "半小时" in dur:
        return 30
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:个)?(小时|钟头|分钟)", dur)
    if not m:
        return None
    val = float(m.group(1))
    return int(val * 60 if m.group(2) in ("小时", "钟头") else val)


def official_period_allocation(parsed: list[dict]) -> Counter:
    """官方路线的时段-时长分配（有时长用时长，否则计步数）。"""
    alloc = Counter()
    for p in parsed:
        for s in p["steps"]:
            period = s["period"] or "未标注"
            minutes = duration_minutes(s["duration"])
            if s["time_range"]:
                m = re.match(r"(\d{1,2})[:：点](\d{1,2})", s["time_range"])
                m2 = re.search(r"[-—~～至]\s*(\d{1,2})[:：点](\d{1,2})", s["time_range"])
                if m and m2:
                    start = int(m.group(1)) * 60 + int(m.group(2))
                    end = int(m2.group(1)) * 60 + int(m2.group(2))
                    minutes = max(0, end - start)
            alloc[period] += minutes if minutes else 1  # 无时长信息计 1 份“步数权重”
    return alloc


def tourist_period_allocation() -> dict[str, Counter]:
    """游客文本的时段分布：时段词出现次数（叙述型）+ 时钟时刻落点。"""
    ents = [json.loads(l) for l in (TASK2 / "output/exp2/entities_refined.jsonl").open(encoding="utf-8")]
    alloc: dict[str, Counter] = defaultdict(Counter)
    for rec in ents:
        if rec["text_type"] != "travelogue":
            continue
        for e in rec["entities"]:
            if e["type"] != "时间节点":
                continue
            if e["subtype"] == "时段":
                alloc[rec["scenic_area"]][e["text"]] += 1
            elif e["subtype"] == "时刻":
                m = re.match(r"(?:清晨|早上|上午|中午|下午|傍晚|晚上|夜里|深夜|凌晨)?(\d{1,2})[点:：]", e["text"])
                if m:
                    hour = int(m.group(1))
                    bucket = ("清晨" if 5 <= hour < 8 else "上午" if 8 <= hour < 12 else
                              "中午" if 12 <= hour < 14 else "下午" if 14 <= hour < 18 else
                              "傍晚" if 18 <= hour < 19 else "晚上" if 19 <= hour < 23 else "深夜")
                    alloc[rec["scenic_area"]][bucket] += 1
    # 归并到四大时段（清晨→上午、傍晚→下午、深夜→晚上）
    merged: dict[str, Counter] = {}
    for scenic, c in alloc.items():
        m = Counter()
        for k, v in c.items():
            key = ("上午" if k in ("清晨", "早上", "上午") else "中午" if k == "中午" else
                   "下午" if k in ("下午", "傍晚") else "晚上" if k in ("晚上", "夜里", "深夜") else k)
            m[key] += v
        merged[scenic] = m
    return merged


def main() -> int:
    FIGS.mkdir(parents=True, exist_ok=True)
    tourists = extract_tourist_routes()
    with (OUT / "tourist_routes.jsonl").open("w", encoding="utf-8") as fh:
        for t in tourists:
            fh.write(json.dumps(t, ensure_ascii=False) + "\n")

    official = official_routes_by_scenic()
    t_period = tourist_period_allocation()

    comparison = {}
    for scenic, officials in official.items():
        official_pois = list(dict.fromkeys(poi for o in officials for poi in o["norm_sequence"]))
        tourists_here = [t for t in tourists if t["scenic_area"] == scenic]
        coverages, jaccards, taus = [], [], []
        for t in tourists_here:
            tset = set(t["distinct_pois"])
            oset = set(official_pois)
            common = tset & oset
            coverages.append(len(common) / len(oset))
            jaccards.append(len(common) / len(tset | oset))
            best_tau = None
            for o in officials:
                o_set = set(o["norm_sequence"])
                common = [p for p in o["norm_sequence"] if p in tset]  # 官方顺序
                t_common = [p for p in t["distinct_pois"] if p in o_set]  # 游客顺序
                if len(common) >= 5:
                    tau = kendall_tau(t_common, common)
                    if tau == tau and (best_tau is None or tau > best_tau):
                        best_tau = tau
            if best_tau is not None:
                taus.append(best_tau)

        off_alloc = official_period_allocation(officials)
        tour_alloc = t_period.get(scenic, Counter())
        has_official_time = sum(off_alloc[k] for k in PERIODS) > 0

        def pct(c: Counter) -> dict:
            total = sum(c[k] for k in PERIODS)
            if not total:
                return {k: None for k in PERIODS}
            return {k: round(c[k] / total, 3) for k in PERIODS}

        comparison[scenic] = {
            "n_official_routes": len(officials),
            "n_official_pois": len(official_pois),
            "n_tourist_routes": len(tourists_here),
            "official_pois": official_pois,
            "coverage_mean": round(sum(coverages) / len(coverages), 3) if coverages else None,
            "jaccard_mean": round(sum(jaccards) / len(jaccards), 3) if jaccards else None,
            "order_tau_mean": round(sum(taus) / len(taus), 3) if taus else None,
            "n_order_pairs": len(taus),
            "official_has_time_info": has_official_time,
            "official_time_allocation_pct": pct(off_alloc),
            "tourist_time_allocation_pct": pct(tour_alloc),
            "tourist_time_counts": dict(tour_alloc),
        }

    result = {
        "metrics_definition": {
            "coverage": "游客路线与官方 POI 全集的交集 / 官方全集（均值）",
            "jaccard": "交集 / 并集（均值）",
            "order_tau": "公共 POI≥5 时，游客序列与最佳匹配官方序列的 Kendall tau（取各官方路线中的最大值，均值）",
            "time_allocation": "官方按时段累计时长占比；游客按文本时段词+时刻落点计数占比",
        },
        "by_scenic_area": comparison,
    }
    (OUT / "official_vs_tourist.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── 图 1：覆盖度与顺序一致性 ──
    areas = list(comparison)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), dpi=150)
    cov = [comparison[a]["coverage_mean"] for a in areas]
    jac = [comparison[a]["jaccard_mean"] for a in areas]
    x = range(len(areas))
    axes[0].bar([i - 0.18 for i in x], cov, 0.36, label="覆盖度", color="#2E7D32", alpha=0.85)
    axes[0].bar([i + 0.18 for i in x], jac, 0.36, label="Jaccard", color="#66BB6A", alpha=0.85)
    axes[0].set_xticks(x, areas)
    axes[0].set_title("游客路线对官方景点的覆盖")
    axes[0].legend()
    axes[0].spines[["top", "right"]].set_visible(False)
    taus = [comparison[a]["order_tau_mean"] or 0 for a in areas]
    npairs = [comparison[a]["n_order_pairs"] for a in areas]
    bars = axes[1].bar(areas, taus, 0.5, color="#1565C0", alpha=0.85)
    for b, n in zip(bars, npairs):
        axes[1].text(b.get_x() + b.get_width() / 2, b.get_height() + 0.02, f"n={n}", ha="center", fontsize=9)
    axes[1].set_ylim(0, 1)
    axes[1].set_title("顺序一致性（Kendall tau，公共POI≥5）")
    axes[1].spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIGS / "compare_coverage_order.png")
    plt.close(fig)

    # ── 图 2：时间分配对比（分景区双子图）──
    fig, axes = plt.subplots(1, len(areas), figsize=(12, 4.2), dpi=150, sharey=True)
    for ax, scenic in zip(axes, areas):
        tour = [comparison[scenic]["tourist_time_allocation_pct"][k] or 0 for k in PERIODS]
        xx = range(len(PERIODS))
        if comparison[scenic]["official_has_time_info"]:
            off = [comparison[scenic]["official_time_allocation_pct"][k] or 0 for k in PERIODS]
            ax.bar([i - 0.18 for i in xx], off, 0.36, label="官方路线", color="#C62828", alpha=0.85)
            ax.bar([i + 0.18 for i in xx], tour, 0.36, label="游客文本", color="#EF9A9A", alpha=0.9)
        else:
            ax.bar(xx, tour, 0.5, label="游客文本", color="#EF9A9A", alpha=0.9)
            ax.text(0.5, 0.92, "官方路线无时段信息", transform=ax.transAxes,
                    ha="center", fontsize=9, color="#777777")
        ax.set_xticks(xx, PERIODS)
        ax.set_title(scenic)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("占比")
    axes[0].legend()
    fig.suptitle("官方路线 vs 游客文本的时间分配（上午/中午/下午/晚上）", y=1.02)
    fig.tight_layout()
    fig.savefig(FIGS / "compare_time_allocation.png", bbox_inches="tight")
    plt.close(fig)

    print(json.dumps({a: {k: v for k, v in comparison[a].items()
                          if k in ("n_tourist_routes", "coverage_mean", "jaccard_mean",
                                   "order_tau_mean", "n_order_pairs",
                                   "official_time_allocation_pct", "tourist_time_allocation_pct")}
                      for a in comparison}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
