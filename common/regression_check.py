# -*- coding: utf-8 -*-
"""人工标注评测回归守护：一条命令输出全部守护指标，并与上次认可状态对比。

用法（建议每次冒烟链全绿后运行）：
    python common/regression_check.py                 # 重打分 + 对比 + 输出结论
    python common/regression_check.py --update-state  # 本轮改动已确认无害，把当前状态固化为新基准

守护内容：
  1. 静态守护：主数据集 271 条；图谱事实核验 6/6 与名称对齐；Agent 场景 6/6；
     task2 抽检 / task5 复核汇总与人工标注评测文件自洽；
  2. 重打分：task4 --score（当前消解器 vs 120 例人工标注评测集）、task5 --score（当前条件对复核汇总）；
  3. 人工标注评测文件指纹：三个人工标注评测文件的 SHA256 与上次不同即告警（该文件只允许追加复核，
     不允许为好看而改判——改判必须先在优化记录中说明并 --update-state 留痕）。

退出码：0 = 无退化；1 = 有守护指标退化或人工标注评测文件指纹变化。
状态存 metrics/regression_state.json（随提交入库，作为"上次认可状态"）。
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "metrics" / "regression_state.json"
PY = ROOT / ".venv/Scripts/python.exe"

GOLD_FILES = {
    "task2_spot_checks": ROOT / "task2/output/exp2/spot_checks.json",
    "task4_annotation_gold": ROOT / "task4/output/annotation_gold.json",
    "task5_review_dev": ROOT / "task5/output/review_dev.json",
}


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[warn] 读取失败 {path}: {e}", file=sys.stderr)
        return None


def run_scorer(cwd: Path, script: str, flag: str) -> tuple[bool, str]:
    proc = subprocess.run(
        [str(PY), "-X", "utf8", script, flag],
        cwd=cwd, capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace",
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-800:]


def collect_guards() -> dict:
    """收集全部守护指标（含子进程重打分）。"""
    g: dict = {}

    # 静态：数据集规模
    ds = ROOT / "task1/data/processed/dataset_clean.jsonl"
    g["dataset.count"] = sum(1 for ln in ds.open(encoding="utf-8") if ln.strip()) if ds.exists() else None


    # 静态：图谱核验
    gv = load_json(ROOT / "task6/output/graph_validation.json")
    if gv:
        checks = gv.get("fact_checks", [])
        g["graph.fact_checks"] = f"{sum(1 for c in checks if c.get('found'))}/{len(checks)}"
        g["graph.name_alignment_passed"] = bool(gv.get("name_alignment", {}).get("passed"))
    else:
        g["graph.fact_checks"] = None
        g["graph.name_alignment_passed"] = None

    # 静态：Agent 场景
    tr = load_json(ROOT / "task7/output/test_report.json")
    g["agent.passed"] = None if tr is None else f"{tr.get('n_passed')}/{tr.get('n_scenarios')}"

    # 静态自洽：task2 抽检汇总 vs 样本重算
    sp = load_json(ROOT / "task2/output/exp2/spot_checks.json")
    if sp:
        samples = sp.get("samples", [])
        present = [s for s in samples if s.get("present_in_current_output")]
        verdicts = {}
        for s in present:
            verdicts[s.get("verdict")] = verdicts.get(s.get("verdict"), 0) + 1
        rs = sp.get("review_summary", {})
        g["task2.spot_n"] = rs.get("n")
        g["task2.spot_self_consistent"] = (
            rs.get("n") == len(present) and rs.get("correct") == verdicts.get("correct")
        )
    else:
        g["task2.spot_n"] = None
        g["task2.spot_self_consistent"] = False

    # 静态自洽：task5 复核汇总 vs 人工标注评测集重算
    rg = load_json(ROOT / "task5/output/review_dev.json")
    rs5 = load_json(ROOT / "task5/output/review_summary.json")
    if rg and rs5:
        counts = {}
        for r in rg.get("reviews", []):
            counts[r.get("verdict")] = counts.get(r.get("verdict"), 0) + 1
        v = rs5.get("verdicts", {})
        g["task5.review_n"] = rs5.get("n")
        g["task5.review_self_consistent"] = (
            rs5.get("n") == rg.get("n")
            and v.get("correct") == counts.get("correct")
            and v.get("boundary") == counts.get("boundary")
            and v.get("wrong") == counts.get("wrong")
        )
        g["task5.verdicts"] = f"{counts.get('correct', 0)}/{counts.get('boundary', 0)}/{counts.get('wrong', 0)}"
    else:
        g["task5.review_n"] = None
        g["task5.review_self_consistent"] = False
        g["task5.verdicts"] = None

    # 重打分：task4 消解（当前消解器 vs 120 例人工标注评测集）
    ok4, out4 = run_scorer(ROOT / "task4", "../task4/src/annotate_sample.py", "--score")
    ev = load_json(ROOT / "task4/output/evaluation.json") if ok4 else None
    g["task4.score_rerun_ok"] = ok4
    g["task4.coref_accuracy"] = ev.get("accuracy_overall") if ev else None
    g["task4.coref_n"] = ev.get("n") if ev else None
    if not ok4:
        g["task4.score_error_tail"] = out4

    # 重打分：task5 条件对（review_summary 由人工标注评测集重算生成，上面已读）
    ok5, out5 = run_scorer(ROOT / "task5", "../task5/src/review_and_charts.py", "--score")
    g["task5.score_rerun_ok"] = ok5
    if not ok5:
        g["task5.score_error_tail"] = out5
    rs5b = load_json(ROOT / "task5/output/review_summary.json")
    if rs5b:
        v = rs5b.get("verdicts", {})
        g["task5.verdicts"] = f"{v.get('correct', 0)}/{v.get('boundary', 0)}/{v.get('wrong', 0)}"
        g["task5.review_n"] = rs5b.get("n")

    # 人工标注评测文件指纹
    g["gold.sha256"] = {k: sha256(p) for k, p in GOLD_FILES.items()}
    return g


# 数值型守护指标：下降即退化（None 表示未知，不比较方向）
DOWN_IS_BAD = {"task4.coref_accuracy", "task5.verdicts", "task2.spot_n", "task5.review_n"}


def parse_verdicts(s) -> tuple[int, ...] | None:
    if not isinstance(s, str) or "/" not in s:
        return None
    try:
        return tuple(int(x) for x in s.split("/"))
    except ValueError:
        return None


def compare(now: dict, last: dict | None) -> list[dict]:
    """返回 [{name, now, last, status}]；status ∈ same/new/improved/degraded/changed"""
    rows = []
    flat_last = {}
    if last:
        flat_last = {k: v for k, v in last.get("guards", {}).items() if k != "gold.sha256"}
        flat_last.update({f"gold.{k}": v for k, v in last.get("gold.sha256", {}).items()})
    flat_now = {k: v for k, v in now.items() if k != "gold.sha256"}
    flat_now.update({f"gold.{k}": v for k, v in now["gold.sha256"].items()})

    for name in sorted(set(flat_now) | set(flat_last)):
        cur, prev = flat_now.get(name), flat_last.get(name)
        if name.startswith("gold."):
            status = "same" if cur == prev else "changed"
        elif prev is None:
            status = "new"
        elif cur == prev:
            status = "same"
        else:
            if name in DOWN_IS_BAD:
                a, b = parse_verdicts(cur), parse_verdicts(prev)
                if a is not None and b is not None:
                    status = "improved" if a > b else "degraded"
                else:
                    try:
                        status = "improved" if float(cur) > float(prev) else "degraded"
                    except (TypeError, ValueError):
                        status = "changed"
            else:
                status = "changed"
        rows.append({"name": name, "now": cur, "last": prev, "status": status})
    return rows


VERDICT_MARK = {"same": "=", "new": "+", "improved": "↑", "degraded": "↓", "changed": "~"}


def main() -> int:
    ap = argparse.ArgumentParser(description="人工标注评测回归守护")
    ap.add_argument("--update-state", action="store_true", help="把当前状态固化为新基准（需先人工确认无退化）")
    args = ap.parse_args()

    last = load_json(STATE_PATH) if STATE_PATH.exists() else None
    now = collect_guards()

    rows = compare(now, last)
    degraded = [r for r in rows if r["status"] == "degraded"]
    gold_changed = [r for r in rows if r["name"].startswith("gold.") and r["status"] == "changed"]
    hard_fail = [
        r for r in rows
        if r["name"] in ("dataset.count", "graph.fact_checks", "agent.passed", "graph.name_alignment_passed")
        and r["status"] in ("degraded", "changed")
    ]

    print(f"== 回归守护 @ {datetime.now().strftime('%Y-%m-%d %H:%M')} ==")
    print(f"{'指标':38s} {'now':>10s} {'last':>10s}  判定")
    for r in rows:
        if r["name"].startswith("gold."):
            print(f"{r['name']:38s} {'...':>10s} {'...':>10s}  {r['status']}")
        else:
            print(f"{r['name']:38s} {str(r['now']):>10s} {str(r['last']):>10s}  {VERDICT_MARK[r['status']]} {r['status']}")

    problems = []
    if not now.get("task4.score_rerun_ok", True):
        problems.append("task4 重打分失败（人工标注评测集对齐断裂？）: " + str(now.get("task4.score_error_tail", ""))[:300])
    if not now.get("task5.score_rerun_ok", True):
        problems.append("task5 重打分失败: " + str(now.get("task5.score_error_tail", ""))[:300])
    if now.get("task2.spot_self_consistent") is False:
        problems.append("task2 抽检汇总与样本重算不一致")
    if now.get("task5.review_self_consistent") is False:
        problems.append("task5 复核汇总与人工标注评测集重算不一致")
    if degraded:
        problems.append("守护指标退化: " + ", ".join(r["name"] for r in degraded))
    if hard_fail:
        problems.append("硬守护异常（数据集/图谱/Agent）: " + ", ".join(r["name"] for r in hard_fail))
    if gold_changed:
        problems.append("人工标注评测文件指纹变化（须在优化记录中说明后 --update-state）: "
                        + ", ".join(r["name"].split(".", 1)[1] for r in gold_changed))

    if problems:
        print("\n❌ 回归守护未通过：")
        for p in problems:
            print("  -", p)
        code = 1
    else:
        print("\n✅ 回归守护通过" + ("（含与上次状态的对比，无退化）" if last else "（首次运行，状态将作为基准）"))
        code = 0

    if args.update_state:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "guards": {k: v for k, v in now.items() if k != "gold.sha256"},
            "gold.sha256": now["gold.sha256"],
            "notes": "人工标注判定历史只允许追加复核；指纹变化必须在优化记录中说明。",
        }
        STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[state] 已更新基准 -> {STATE_PATH.relative_to(ROOT)}")
        code = 0
    return code


if __name__ == "__main__":
    sys.exit(main())
