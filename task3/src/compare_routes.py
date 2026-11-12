"""Experiment 3: tourist actual-route extraction + official/tourist route comparison (advanced task).


Tourist routes: take the in-scenic POI sequence in reading order from the Experiment 2 entity output (consecutive duplicates merged, >= 4 distinct POIs).

Comparison dimensions: 1. attraction coverage (tourist-route coverage of the official POI set, Jaccard); 2. order consistency (when >= 5 common POIs,

         compute Kendall tau); 3. time allocation (official period-duration distribution vs tourist-text period-word distribution).

Output: task3/output/tourist_routes.jsonl, official_vs_tourist.json, figs/

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


if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]

plt.rcParams["axes.unicode_minus"] = False


PERIODS = ("上午", "中午", "下午", "晚上")

_DICT = json.loads((TASK2 / "output/exp2/entity_dictionary.json").read_text(encoding="utf-8"))
if "poi_lookup" not in _DICT:
    raise SystemExit("entity_dictionary.json 缺少 poi_lookup；请先运行 task2/src/export_dictionary.py")
POI_LOOKUP = {(r["scenic_area"], r["variant"]): r["canonical"] for r in _DICT["poi_lookup"]}


def kendall_tau(a: list, b: list) -> float:

    """Kendall tau between two sequences (different orderings of the same set)."""

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

            # Take only POIs inside the main scenic area (in_scenic flag), excluding cross-scenic entities from multi-attraction travelogues

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

                # po_sequence keeps backtracking and repeated visits (consecutive duplicates already merged); graph edges use the full sequence;

                # distinct_pois is only for the set-based criterion of coverage/tau

            })

    return routes


def official_routes_by_scenic() -> dict[str, list[dict]]:

    parsed = [json.loads(l) for l in (OUT / "parsed_routes.jsonl").open(encoding="utf-8")]

    by_scenic: dict[str, list[dict]] = defaultdict(list)

    for p in parsed:

        if p["ordered_route"] and p["pois_in_order"]:

            # Official POI sequence after consecutive deduplication

            seq = []

            for poi in p["pois_in_order"]:

                poi = POI_LOOKUP.get((p["scenic_area"], poi), poi)

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


def official_period_allocation(parsed: list[dict]) -> dict:

    """§4.1-4: official period allocation separates two measures -- known minutes and steps without durations are counted separately."""

    alloc_minutes = Counter()

    alloc_steps = Counter()

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

            if minutes:

                alloc_minutes[period] += minutes

            else:

                alloc_steps[period] += 1

    return {"minutes": dict(alloc_minutes), "steps": dict(alloc_steps),

            "n_known_minutes": sum(alloc_minutes.values()),

            "n_unknown_steps": sum(alloc_steps.values())}


# Period bucketing (originally a separate module, inlined)
import re

# Word tuples of the four report periods (shared by direct period-word lookup and clock-prefix fallback)
_GROUPS = {
    "上午": {"清晨", "早晨", "早上", "上午"}, "中午": {"正午", "中午"},
    "下午": {"下午", "傍晚"}, "晚上": {"晚上", "夜间", "夜里", "深夜", "凌晨", "半夜"},
}


def entity_period(entity: dict) -> str | None:
    if entity.get("subtype") == "时段":
        word = entity.get("normalized") or entity["text"]
        return next((key for key, values in _GROUPS.items() if word in values), None)
    if entity.get("subtype") not in {"时刻", "时刻区间"}:
        return None
    value = entity.get("normalized") or entity["text"]
    # Approximate/range clock times ("下午四五点") have no exact hour -- bucket by the leading period word
    for key, values in _GROUPS.items():
        if value.startswith(tuple(values)):
            return key
    match = re.match(r"(\d{1,2}):", value)
    if not match:
        return None
    hour = int(match.group(1))
    return "上午" if 5 <= hour < 12 else "中午" if 12 <= hour < 14 else "下午" if 14 <= hour < 19 else "晚上"


def tourist_period_allocation(tourist_ids: set[str] | None = None) -> dict[str, Counter]:

    """Period distribution of tourist text: period-word occurrence counts (narrative) + clock-time placements.

    When ``tourist_ids`` is supplied, only the same routes as tourist_routes.jsonl
    are counted so the allocation shares the coverage/order denominator.
    """

    ents = [json.loads(l) for l in (TASK2 / "output/exp2/entities_refined.jsonl").open(encoding="utf-8")]

    alloc: dict[str, Counter] = defaultdict(Counter)

    for rec in ents:

        if rec["text_type"] != "travelogue":

            continue

        if tourist_ids is not None and rec["record_id"] not in tourist_ids:

            continue

        for e in rec["entities"]:

            if e["type"] != "时间节点":

                continue

            bucket = entity_period(e)

            if bucket:

                alloc[rec["scenic_area"]][bucket] += 1

    # Merge into the four main periods (清晨→上午、傍晚→下午、深夜→晚上)

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

    tourist_ids = {t["record_id"] for t in tourists}

    t_period = tourist_period_allocation(tourist_ids)


    comparison = {}

    tau_sens = {scenic: {3: [], 5: [], 7: []} for scenic in official}

    # Extension: aggregation-rule sensitivity -- the same batch of (tourist, official route) tau pairs, summarized under three aggregation rules:
    # best (best-match, primary criterion) / mean (mean over all valid pairs) / first (only the first official route).
    # Best-match is inherently optimistic; it must be presented alongside the other two criteria to avoid optimistic interpretation.
    tau_agg = {scenic: {r: [] for r in ("best", "mean", "first")} for scenic in official}

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

                common = [p for p in o["norm_sequence"] if p in tset]  # official order

                t_common = [p for p in t["distinct_pois"] if p in o_set]  # tourist order

                if len(common) >= 5:

                    tau = kendall_tau(t_common, common)

                    if tau == tau and (best_tau is None or tau > best_tau):

                        best_tau = tau

            if best_tau is not None:

                taus.append(best_tau)

            # Extension: aggregation-rule sensitivity (all valid tau pairs for this tourist route)
            all_taus = []
            for o in officials:
                o_set = set(o["norm_sequence"])
                common = [q for q in o["norm_sequence"] if q in tset]
                t_common = [q for q in t["distinct_pois"] if q in o_set]
                if len(common) >= 5:
                    tau = kendall_tau(t_common, common)
                    if tau == tau:
                        all_taus.append(tau)
            if all_taus:
                tau_agg[scenic]["best"].append(max(all_taus))
                tau_agg[scenic]["mean"].append(sum(all_taus) / len(all_taus))
            # first: only against the first official route (fixed reference, no best-match; computed independently per tourist route)
            o = officials[0]
            o_set = set(o["norm_sequence"])
            common = [q for q in o["norm_sequence"] if q in tset]
            t_common = [q for q in t["distinct_pois"] if q in o_set]
            if len(common) >= 5:
                tau_first = kendall_tau(t_common, common)
                if tau_first == tau_first:
                    tau_agg[scenic]["first"].append(tau_first)

            # Threshold sensitivity -- best tau under different common-POI lower bounds (for robustness inspection)

            for thr in (3, 5, 7):

                best_thr = None

                for o in officials:

                    o_set = set(o["norm_sequence"])

                    common = [q for q in o["norm_sequence"] if q in tset]

                    t_common = [q for q in t["distinct_pois"] if q in o_set]

                    if len(common) >= thr:

                        tau = kendall_tau(t_common, common)

                        if tau == tau and (best_thr is None or tau > best_thr):

                            best_thr = tau

                if best_thr is not None:

                    tau_sens[scenic][thr].append(best_thr)


        off_alloc = official_period_allocation(officials)

        off_min = off_alloc.get("minutes", {})

        off_steps = off_alloc.get("steps", {})

        tour_alloc = t_period.get(scenic, Counter())

        has_official_time = (sum(off_min.get(k, 0) for k in PERIODS) > 0

                             or sum(off_steps.get(k, 0) for k in PERIODS) > 0)


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
            # Unmatched samples -- number of tourist routes with < 5 common POIs (tau not computable) and a note on the matching rule
            "n_tourists_unmatched": len(tourists_here) - len(taus),
            "matching_rule": "每条游客路线取各官方路线中公共POI≥5 的最大 tau（择优，敏感性见 tau_aggregation_sensitivity）",

            "official_has_time_info": has_official_time,

            # The two measures have different units -- official is the distribution of route-annotated durations (minutes), tourist is the mention frequency of period words in text,

            # they can only serve as proxy indicators for comparison, not be divided directly

            "official_time_basis": "路线标注时长（分钟，已知）+ 无时长步骤数（分别统计）",

            "tourist_time_basis": "文本时段词提及频次",

            # Extension: aggregation-rule sensitivity (best-match is inherently optimistic; presented alongside mean/first)
            "tau_aggregation_sensitivity": {
                r: {"n": len(tau_agg[scenic][r]),
                    "mean": round(sum(tau_agg[scenic][r]) / len(tau_agg[scenic][r]), 3)
                    if tau_agg[scenic][r] else None}
                for r in ("best", "mean", "first")},

            "tau_sensitivity": {str(thr): {

                "n": len(v), "mean": round(sum(v) / len(v), 3) if v else None}

                for thr, v in sorted(tau_sens[scenic].items())},

            "official_time_allocation_pct": pct(Counter(off_min)),

            "official_time_steps": off_steps,

            "official_time_minutes": off_min,

            "tourist_time_allocation_pct": pct(tour_alloc),

            "tourist_time_counts": dict(tour_alloc),

        }


    result = {

        "metrics_definition": {

            "coverage": "游客路线与官方 POI 全集的交集 / 官方全集（均值）",

            "jaccard": "交集 / 并集（均值）",

            "order_tau": "公共 POI≥5 时，游客序列与最佳匹配官方序列的 Kendall tau（取各官方路线中的最大值，均值）",

            "time_allocation": "官方按时段累计时长占比；游客按文本时段词+时刻落点计数占比，且只统计 tourist_routes 的同一批路线",

        },

        "by_scenic_area": comparison,

    }

    (OUT / "official_vs_tourist.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


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
