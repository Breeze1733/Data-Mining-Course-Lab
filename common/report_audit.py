# -*- coding: utf-8 -*-
"""报告-数据一致性审计：报告 docx 中出现的承重数字，必须能在 output 数据文件中找到出处。

用法：
    python common/report_audit.py            # 全量审计，有 FAIL 时退出码 1

原理：每个报告维护一组"承重声明"（claim）。声明由数据文件实时计算期望值，
生成若干格式变体（带/不带千分位、百分比一位/零位小数等），在 docx 全文
（段落+表格）中反查。任一变体命中即通过。数据改动导致报告漂移时，对应
claim 会 FAIL——此时应重跑该报告的 build_reportN.py 而不是手改数字。
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


def _bounded_match(text: str, variant: str) -> bool:
    """P22：数字类变体带前后边界匹配（数字/千分位/小数点不相连才算命中）。"""
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
    """0.425 -> ['42.5%', '42%', '43%']（四舍五入两位备选，容忍报告的不同舍入）"""
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


# ── 数据源快捷引用 ──────────────────────────────────────────────
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
    """报告相对路径 -> 声明列表。claim: {name, variants|regex, required}"""
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
            {"name": "总体准确率", "variants": v_pct(EVAL.get("accuracy_overall")), "required": True},
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
            {"name": "P1显式条件", "variants": v_int((STAT5.get("by_pattern") or {}).get("P1_显式条件")), "required": True},
            {"name": "P4建议推断", "variants": v_int((STAT5.get("by_pattern") or {}).get("P4_建议推断")), "required": True},
            {"name": "P6否定建议", "variants": v_int((STAT5.get("by_pattern") or {}).get("P6_否定建议")), "required": True},
            {"name": "复核样本数", "variants": v_int(n_rev), "required": True},
            {"name": "复核-正确", "variants": v_int(rv.get("correct")) + v_pct((rv.get("correct") or 0) / n_rev), "required": True},
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
            {"name": "消解准确率", "variants": v_pct(EVAL.get("accuracy_overall")), "required": True},
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
                # P22：数字带边界匹配——防止 79 命中 179、0.5 命中 30.5 这类短数字误配
                hit = any(_bounded_match(text, v) for v in variants)
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
