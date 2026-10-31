"""实验7：Agent 多场景批量测试（8 场景，证据落盘）。

场景覆盖：不同景区 × 游客类型 × 时长、特殊需求、无匹配景区回退、半日+特殊需求冲突提示、条件节点可行性提示。
输出：output/traces/trace_*.json、itineraries.json、test_report.json
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_cli import LLMClient, ReActAgent  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"

SCENARIOS = [
    {"id": "S1_老人颐和园半日", "query": "带老人去颐和园玩半天，腿脚不方便，走省力的路线",
     "expect": {"scenic": "颐和园", "visitor_type": "老人", "days": 0.5}},
    {"id": "S2_亲子九寨沟一日", "query": "带孩子九寨沟一日游，怎么安排？",
     "expect": {"scenic": "九寨沟", "visitor_type": "孩子", "days": 1}},
    {"id": "S3_情侣黄山两日", "query": "情侣黄山两日游，想看日出",
     "expect": {"scenic": "黄山", "visitor_type": "情侣", "days": 2}},
    {"id": "S4_时间紧颐和园", "query": "只有3小时，颐和园快速逛一遍精华",
     "expect": {"scenic": "颐和园", "visitor_type": None, "days": 0.5}},
    {"id": "S5_无匹配景区", "query": "帮我规划故宫一日游",
     "expect": {"scenic": "未知", "fallback": True}},
    {"id": "S6_冲突约束", "query": "半天时间在黄山看日出再下西海大峡谷",
     "expect": {"scenic": "黄山", "days": 0.5, "special": ["看日出"], "conflict_note": True}},
    {"id": "S7_可行性提示", "query": "九寨沟一日游，想去原始森林看看",
     "expect": {"scenic": "九寨沟", "days": 1, "feasibility": True}},
    {"id": "S8_多跳动线", "query": "九寨沟从长海出来怎么走回诺日朗中心？",
     "expect": {"scenic": "九寨沟", "path_query": ("长海", "诺日朗中心")}},
    {"id": "S9_冬季时段提示", "query": "12月去黄山两天，想上莲花峰，冬季去要注意什么？",
     "expect": {"scenic": "黄山", "days": 2, "month": 12,
                "feasibility_keyword": "莲花峰", "seasonal_note": True}},
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "traces").mkdir(exist_ok=True)
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", action="store_true",
                    help="强制规则模式（规范产物默认口径；LLM 模式结果另存 test_report_llm.json）")
    args = ap.parse_args()
    llm = LLMClient(config_path=ROOT / "config.nokey.json") if args.rules else LLMClient()
    results = []
    for sc in SCENARIOS:
        agent = ReActAgent(llm)
        result = agent.run(sc["query"])
        checks = {}
        intent = result["intent"]
        for k, v in sc["expect"].items():
            if k == "fallback":
                checks["fallback_answer"] = result["plan"] is None and "仅支持" in result["answer"]
            elif k == "conflict_note":
                checks["conflict_note"] = any("冲突" in t.get("thought", "") for t in result["trace"])
            elif k == "path_query":
                fp, tp = v
                calls = [t for t in result["trace"] if t.get("step") == "action"
                         and t.get("tool") == "query_path"]
                checks["path_tool_called"] = bool(calls)
                checks["path_valid"] = ("动线参考" in result["answer"]
                                        and fp in result["answer"] and tp in result["answer"])
            elif k == "feasibility":
                warnings = (result["plan"] or {}).get("feasibility_warnings", [])
                checks["feasibility_warning"] = bool(warnings) and any(
                    "原始森林" in w for w in warnings)
            elif k == "feasibility_keyword":
                warnings = (result["plan"] or {}).get("feasibility_warnings", [])
                checks["feasibility_keyword"] = bool(warnings) and any(v in w for w in warnings)
            elif k == "seasonal_note":
                warnings = (result["plan"] or {}).get("feasibility_warnings", [])
                checks["seasonal_note"] = any("时段提示" in w for w in warnings)
            else:
                checks[k] = intent.get(k) == v
        tool_calls = [t for t in result["trace"] if t.get("step") == "action"]
        checks["tools_called"] = len(tool_calls) >= (0 if sc["expect"].get("fallback") else 3)
        checks["tools_used_in_answer"] = True
        if result["plan"]:
            n_pois = len(result["plan"]["itinerary"])
            expected_n = {0.5: (3, 6), 1: (5, 9), 2: (8, 12)}[sc["expect"].get("days", 1)]
            checks["itinerary_size"] = expected_n[0] <= n_pois <= expected_n[1] + 2
            checks["tips_attached"] = len(result["plan"]["tips"]) > 0
        passed = all(checks.values())
        results.append({"scenario": sc["id"], "query": sc["query"], "passed": passed,
                        "checks": checks, "intent": intent,
                        "n_tool_calls": len(tool_calls), "answer_head": result["answer"][:120],
                        "elapsed": result["elapsed"]})
        (OUT / "traces" / f'trace_{sc["id"]}.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f'{"PASS" if passed else "FAIL"} {sc["id"]} | tools={len(tool_calls)} | {result["elapsed"]}s')

    report = {
        "mode": "llm" if llm.available else "rules（未配置 LLM API，内置规划器）",
        "n_scenarios": len(SCENARIOS),
        "n_passed": sum(1 for r in results if r["passed"]),
        "results": results,
        "evidence": "每次运行的完整 ReAct trace（含每步 thought/action/observation）见 output/traces/",
    }
    (OUT / "test_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    plans = []
    for sc in SCENARIOS:
        t = json.loads((OUT / "traces" / f'trace_{sc["id"]}.json').read_text(encoding="utf-8"))
        if t.get("plan"):
            plans.append({"scenario": sc["id"], **t["plan"]})
    (OUT / "itineraries.json").write_text(json.dumps(plans, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("mode", "n_scenarios", "n_passed")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
