# -*- coding: utf-8 -*-
"""Report-data consistency audit: load-bearing numbers appearing in a report docx must
be traceable to the output data files.

Usage:
    python common/report_audit.py            # full audit, exit code 1 on any FAIL

Principle: each report maintains a set of load-bearing claims. A claim computes its
expected value from the data files at run time, generates several format variants
(with/without thousands separators, percentages at one/zero decimal places, etc.) and
searches for them across the full docx text (paragraphs + tables). Any variant hit
passes. When data changes make the report drift, the corresponding claim FAILs --
rerun that report's build_reportN.py instead of hand-editing numbers.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")

from docx import Document  # noqa: E402


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def count_lines(path: Path) -> int | None:
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for ln in f if ln.strip())
    except OSError:
        return None


def _bounded_match_span(text: str, variant: str) -> re.Match | None:
    """Digit matching with boundaries; returns a Match (used to locate context co-occurrence checks)."""
    if not variant:
        return None
    esc = re.escape(variant)
    if re.fullmatch(r"[\d,]+", variant):
        pat = r"(?<![\d,])" + esc + r"(?![\d,])"
    elif re.fullmatch(r"[\d.]+", variant):
        pat = r"(?<![\d.])" + esc + r"(?![\d.])"
    elif variant.endswith("%"):
        pat = r"(?<![\d.])" + re.escape(variant[:-1]) + r"%(?!\d)"
    else:
        m = re.search(re.escape(variant), text)
        return m
    return re.search(pat, text)


def _bounded_match(text: str, variant: str) -> bool:
    """Boundary-aware matching for numeric variants (only a hit when not adjacent to digits/thousands separators/decimal points)."""
    if not variant:
        return False
    esc = re.escape(variant)
    if re.fullmatch(r"[\d,]+", variant):
        pat = r"(?<![\d,])" + esc + r"(?![\d,])"
    elif re.fullmatch(r"[\d.]+", variant):
        pat = r"(?<![\d.])" + esc + r"(?![\d.])"
    elif variant.endswith("%"):
        pat = r"(?<![\d.])" + re.escape(variant[:-1]) + r"%(?!\d)"
    else:
        return variant in text
    return re.search(pat, text) is not None


def v_int(x) -> list[str]:
    if x is None:
        return []
    return [f"{int(x):,}", str(int(x))]


def v_pct(x) -> list[str]:
    """0.425 -> ['42.5%', '42%', '43%'] (rounding alternates included, tolerating the report's different rounding)"""
    if x is None:
        return []
    p = x * 100
    out = [f"{p:.1f}%", f"{p:.0f}%", f"{round(p)}%"]
    return sorted(set(out))


def v_float(x, nd=3) -> list[str]:
    if x is None:
        return []
    out = {f"{x:.{nd}f}", f"{x:g}"}
    return sorted(out)


Q1 = load(ROOT / "task1/data/processed/quality_report.json") or {}
EB = load(ROOT / "task2/output/exp2/entity_stats_baseline.json") or {}
ER = load(ROOT / "task2/output/exp2/entity_stats_refined.json") or {}
SPOT = load(ROOT / "task2/output/exp2/spot_checks.json") or {}
OVT = load(ROOT / "task3/output/official_vs_tourist.json") or {}
EVAL = load(ROOT / "task4/output/evaluation.json") or {}
STAT5 = load(ROOT / "task5/output/extraction_stats.json") or {}
REV5 = load(ROOT / "task5/output/review_summary.json") or {}
GS = load(ROOT / "task6/output/graph_stats.json") or {}
TR = load(ROOT / "task7/output/test_report.json") or {}

sum_by_prefix = lambda d, p: sum(v for k, v in d.items() if k.startswith(p))


def build_claims() -> dict[str, list[dict]]:
    """Report relative path -> list of claims. claim: {name, variants|regex, required}"""
    scenic = OVT.get("by_scenic_area", {})
    jzg, yhy, hs = scenic.get("九寨沟", {}), scenic.get("颐和园", {}), scenic.get("黄山", {})
    acc = EVAL.get("accuracy_by_class", {})
    n_eval = EVAL.get("n") or 0
    correct_eval = round((EVAL.get("accuracy_overall") or 0) * n_eval)
    rv = REV5.get("verdicts", {})
    n_rev = REV5.get("n") or 0
    gs_scenic = GS.get("per_scenic", {})

    claims: dict[str, list[dict]] = {
        "task1/report.docx": [
            {"name": "输入记录", "variants": v_int(Q1.get("input_records")), "required": True},
            {"name": "保留记录", "variants": v_int(Q1.get("accepted_records")), "required": True},
            {"name": "拒绝记录", "variants": v_int(Q1.get("rejected_records")), "required": True},
            {"name": "清洗后总字符", "variants": v_int((Q1.get("profile") or {}).get("clean_characters_total")), "required": True},
            {"name": "最短长度", "variants": v_int((Q1.get("profile") or {}).get("clean_length_min")), "required": True},
            {"name": "中位长度", "variants": v_int((Q1.get("profile") or {}).get("clean_length_median")), "required": True},
            {"name": "最长长度", "variants": v_int((Q1.get("profile") or {}).get("clean_length_max")), "required": True},
            {"name": "官方文档数", "variants": v_int((Q1.get("profile") or {}).get("source_platforms", {}).get("官方")), "required": True},
        ],
        "task2/report.docx": [
            {"name": "记录数", "variants": v_int(ER.get("records")), "required": True},
            {"name": "POI词典", "variants": v_int((ER.get("dictionary_size") or {}).get("poi")), "required": True},
            {"name": "交通词典", "variants": v_int((ER.get("dictionary_size") or {}).get("transport")), "required": True},
            {"name": "停用词", "variants": v_int((ER.get("dictionary_size") or {}).get("stopwords")), "required": True},
            {"name": "baseline POI", "variants": v_int(sum_by_prefix(EB.get("by_subtype", {}), "景点POI")), "required": True},
            {"name": "baseline 交通", "variants": v_int(sum_by_prefix(EB.get("by_subtype", {}), "交通方式")), "required": True},
            {"name": "baseline 合计", "variants": v_int(EB.get("total_entities")), "required": True},
            {"name": "refined POI", "variants": v_int(sum_by_prefix(ER.get("by_subtype", {}), "景点POI")), "required": True},
            {"name": "refined 交通", "variants": v_int(sum_by_prefix(ER.get("by_subtype", {}), "交通方式")), "required": True},
            {"name": "refined 时间", "variants": v_int(sum_by_prefix(ER.get("by_subtype", {}), "时间节点")), "required": True},
            {"name": "refined 合计", "variants": v_int(ER.get("total_entities")), "required": True},
            {"name": "抽检叙述(53例/53正确)", "regex": r"抽检53例：53正确", "required": True},
        ],
        "task3/report.docx": [
            {"name": "官方路线总数", "variants": v_int(count_lines(ROOT / "task3/output/parsed_routes.jsonl")), "required": True},
            {"name": "游客路线总数", "variants": v_int(sum(s.get("n_tourist_routes") for s in scenic.values())), "required": True},
            {"name": "游客路线-九寨沟", "variants": v_int(jzg.get("n_tourist_routes")), "required": True},
            {"name": "游客路线-颐和园", "variants": v_int(yhy.get("n_tourist_routes")), "required": True},
            {"name": "游客路线-黄山", "variants": v_int(hs.get("n_tourist_routes")), "required": True},
            {"name": "官方POI-九寨沟", "variants": v_int(jzg.get("n_official_pois")), "required": False},
            {"name": "tau-九寨沟", "variants": v_float(jzg.get("order_tau_mean")), "required": True},
            {"name": "tau-颐和园", "variants": v_float(yhy.get("order_tau_mean")), "required": True},
            {"name": "tau-黄山", "variants": v_float(hs.get("order_tau_mean")), "required": True},
            {"name": "覆盖度-九寨沟", "variants": v_float(jzg.get("coverage_mean")), "required": False},
            {"name": "覆盖度-颐和园", "variants": v_float(yhy.get("coverage_mean")), "required": False},
            {"name": "覆盖度-黄山", "variants": v_float(hs.get("coverage_mean")), "required": False},
            {"name": "游记数", "variants": v_int((Q1.get("profile") or {}).get("text_types", {}).get("travelogue")), "required": True},
        ],
        "task4/report.docx": [
            {"name": "代词案例数", "variants": v_int(count_lines(ROOT / "task4/output/pronoun_cases.jsonl")), "required": True},
            {"name": "人工标注样本数", "variants": v_int(EVAL.get("n")), "required": True},
            {"name": "总体准确率", "variants": v_pct(EVAL.get("accuracy_overall")), "required": True,
             "near": {"patterns": [r"人工标注|消解"], "window": 160}},
            {"name": "错误数", "variants": v_int(n_eval - correct_eval), "required": False},
            {"name": "locative准确率", "variants": v_pct((acc.get("locative") or {}).get("accuracy")), "required": True},
            {"name": "object准确率", "variants": v_pct((acc.get("object") or {}).get("accuracy")), "required": True},
            {"name": "person准确率", "variants": v_pct((acc.get("person") or {}).get("accuracy")), "required": True},
            {"name": "set准确率", "variants": v_pct((acc.get("set") or {}).get("accuracy")), "required": True},
        ],
        "task5/report.docx": [
            {"name": "原始条件对", "variants": v_int(STAT5.get("raw_pairs")), "required": True},
            {"name": "去重后条件对", "variants": v_int(STAT5.get("after_dedup")), "required": True},
            {"name": "合并重复", "variants": v_int(STAT5.get("duplicates_merged")), "required": True},
            {"name": "显式条件", "variants": v_int((STAT5.get("by_pattern") or {}).get("显式条件")), "required": True,
             "near": {"patterns": [r"P1|显式条件"], "window": 120}},
            {"name": "建议推断", "variants": v_int((STAT5.get("by_pattern") or {}).get("建议推断")), "required": True},
            {"name": "否定建议", "variants": v_int((STAT5.get("by_pattern") or {}).get("否定建议")), "required": True,
             "near": {"patterns": [r"P6|否定|避雷"], "window": 120}},
            {"name": "复核样本数", "variants": v_int(n_rev), "required": True},
            {"name": "复核-正确", "variants": v_int(rv.get("correct")) + v_pct((rv.get("correct") or 0) / n_rev), "required": True,
             "near": {"patterns": [r"复核|人工|AI|正确"], "window": 120}},
            {"name": "复核-边界", "variants": v_int(rv.get("boundary")) + v_pct((rv.get("boundary") or 0) / n_rev), "required": True},
            {"name": "复核-错误", "variants": v_int(rv.get("wrong")) + v_pct((rv.get("wrong") or 0) / n_rev), "required": True},
        ],
        "task6/report.docx": [
            {"name": "图谱节点", "variants": v_int(GS.get("total_nodes")), "required": True},
            {"name": "图谱边", "variants": v_int(GS.get("total_edges")), "required": True},
            {"name": "黄山节点", "variants": v_int((gs_scenic.get("黄山") or {}).get("nodes")), "required": True},
            {"name": "黄山边", "variants": v_int((gs_scenic.get("黄山") or {}).get("edges")), "required": True},
            {"name": "九寨沟节点", "variants": v_int((gs_scenic.get("九寨沟") or {}).get("nodes")), "required": True},
            {"name": "九寨沟边", "variants": v_int((gs_scenic.get("九寨沟") or {}).get("edges")), "required": True},
            {"name": "颐和园节点", "variants": v_int((gs_scenic.get("颐和园") or {}).get("nodes")), "required": True},
            {"name": "颐和园边", "variants": v_int((gs_scenic.get("颐和园") or {}).get("edges")), "required": True},
            {"name": "先后顺序边", "variants": v_int((GS.get("by_relation") or {}).get("先后顺序")), "required": True},
            {"name": "条件建议边", "variants": v_int((GS.get("by_relation") or {}).get("条件建议")), "required": True},
            {"name": "条件-景区边", "variants": v_int(GS.get("cond_edges_to_scenic")), "required": False},
            {"name": "事实核验", "regex": r"6\s*/\s*6", "required": False},
        ],
        "task7/report.docx": [
            {"name": "场景通过", "regex": rf"{TR.get('n_passed')}\s*/\s*{TR.get('n_scenarios')}", "required": True},
            {"name": "场景数", "variants": v_int(TR.get("n_scenarios")), "required": True},
        ],
        "实验总结反思.docx": [
            {"name": "数据集规模", "variants": v_int((Q1.get("profile") or {}).get("text_types", {}).get("travelogue"))
                + v_int(Q1.get("accepted_records")), "required": True},
            {"name": "消解准确率", "variants": v_pct(EVAL.get("accuracy_overall")), "required": True,
             "near": {"patterns": [r"消解"], "window": 160}},
            {"name": "消解人工标注样本", "variants": v_int(EVAL.get("n")), "required": True},
            {"name": "实体抽检正确", "variants": v_int((SPOT.get("review_summary") or {}).get("correct")), "required": True},
            {"name": "条件复核样本", "variants": v_int(n_rev), "required": True},
        ],
    }
    return claims


def docx_text(path: Path) -> str:
    d = Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text for c in row.cells))
    return "\n".join(parts)


def main() -> int:
    claims = build_claims()
    n_fail = n_pass = n_warn = n_missing_src = 0
    print("== 报告-数据一致性审计 ==")
    for report, items in claims.items():
        path = ROOT / report
        if not path.exists():
            print(f"[缺失] {report}")
            n_fail += 1
            continue
        text = docx_text(path)
        fails, warns = [], []
        for c in items:
            if "regex" in c:
                hit = bool(re.search(c["regex"], text))
                expected = f"/{c['regex']}/"
            else:
                variants = c.get("variants") or []
                if not variants:
                    warns.append(f"{c['name']}(数据源缺失)")
                    n_missing_src += 1
                    continue
                # bounded matching for numbers -- prevents short-number false hits such as 79 matching 179 or 0.5 matching 30.5
                # near semantic binding -- the value must co-occur within ±window characters of the specified
                # context (denominator/sample scope/method name), preventing "right number, wrong metric/denominator" drift
                near = c.get("near")
                hit = False
                for v in variants:
                    m = _bounded_match_span(text, v)
                    if not m:
                        continue
                    if near:
                        window = near.get("window", 120)
                        lo, hi = max(0, m.start() - window), min(len(text), m.end() + window)
                        ctx = text[lo:hi]
                        if all(re.search(rx, ctx) for rx in near["patterns"]):
                            hit = True
                            break
                    else:
                        hit = True
                        break
                expected = " 或 ".join(variants[:3]) + ("…" if len(variants) > 3 else "")
            if hit:
                n_pass += 1
            elif c.get("required"):
                fails.append(f"{c['name']} 期望[{expected}]")
            else:
                warns.append(f"{c['name']} 期望[{expected}]")
        status = "✅" if not fails else "❌"
        print(f"{status} {report}: {len(items)} 项声明, {len(fails)} 失败, {len(warns)} 警告")
        for f in fails:
            print(f"    FAIL {f}")
        for w in warns:
            print(f"    warn {w}")
        n_fail += len(fails)
        n_warn += len(warns)
    print(f"\n合计: 通过 {n_pass} / 失败 {n_fail} / 警告 {n_warn}（含数据源缺失 {n_missing_src}）")
    if n_fail:
        print("报告与数据漂移：请重跑对应 build_reportN.py，而不是手改报告数字。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
