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
     "expect": {"scenic": "颐和园", "visitor_type": "老人", "days": 0.5, "tips_in_answer": True}},
    {"id": "S2_亲子九寨沟一日", "query": "带孩子九寨沟一日游，怎么安排？",
     "expect": {"scenic": "九寨沟", "visitor_type": "孩子", "days": 1}},
    {"id": "S3_情侣黄山两日", "query": "情侣黄山两日游，想看日出",
     "expect": {"scenic": "黄山", "visitor_type": "情侣", "days": 2,
                "sunrise_last_day_first": "光明顶"}},
    {"id": "S4_时间紧颐和园", "query": "只有3小时，颐和园快速逛一遍精华",
     "expect": {"scenic": "颐和园", "visitor_type": None, "days": 0.5}},
    {"id": "S5_无匹配景区", "query": "帮我规划故宫一日游",
     "expect": {"scenic": "未知", "fallback": True}},
    {"id": "S6_冲突约束", "query": "半天时间在黄山看日出再下西海大峡谷",
     "expect": {"scenic": "黄山", "days": 0.5, "special": ["看日出"], "conflict_note": True}},
    {"id": "S7_可行性提示", "query": "九寨沟一日游，想去原始森林看看",
     "expect": {"scenic": "九寨沟", "days": 1, "feasibility": True, "feasibility_in_answer": "原始森林"}},
    {"id": "S8_多跳动线", "query": "九寨沟从长海出来怎么走回诺日朗中心？",
     "expect": {"scenic": "九寨沟", "path_query": ("长海", "诺日朗中心")}},
    {"id": "S9_冬季时段提示", "query": "12月去黄山两天，想上莲花峰，冬季去要注意什么？",
     "expect": {"scenic": "黄山", "days": 2, "month": 12,
                "feasibility_keyword": "莲花峰", "seasonal_note": True}},
    {"id": "S10_三日多天编排", "query": "九寨沟三天深度游，慢慢逛",
     "expect": {"scenic": "九寨沟", "days": 3, "multi_day": True}},
    {"id": "S11_多人群贴士", "query": "带老人和孩子去九寨沟一日游，走路要少",
     "expect": {"scenic": "九寨沟", "days": 1, "multi_visitor": ["老人", "孩子"], "tips_attached": True}},
    {"id": "S12_不去地点", "query": "九寨沟一日游，不要去原始森林，人多",
     "expect": {"scenic": "九寨沟", "days": 1, "avoid_respected": "原始森林"}},
    {"id": "S13_未知景点", "query": "九寨沟一日游，想去月亮湾看看",
     "expect": {"scenic": "九寨沟", "days": 1, "unknown_poi_not_in_plan": "月亮湾"}},
    {"id": "S14_多约束集成", "query": "黄山三天游，冬季去，避开莲花峰",
     "expect": {"scenic": "黄山", "days": 3, "month": 12, "avoid_respected": "莲花峰",
                "multi_day": True}},
    {"id": "S15_必去地点", "query": "黄山两日游，一定要去天都峰",
     "expect": {"scenic": "黄山", "days": 2, "must_respected": "天都峰"}},
    {"id": "S16_无日出景点诚实回退", "query": "颐和园两日游，想看日出",
     "expect": {"scenic": "颐和园", "days": 2, "sunrise_honest": True}},
    {"id": "S17_出入口编排", "query": "颐和园一日游，北宫门进东宫门出",
     "expect": {"scenic": "颐和园", "days": 1, "entrance_first": "北宫门", "exit_last": "东宫门"}},
    {"id": "S18_避开住宿日出取舍", "query": "黄山两日游想看日出，不要住白云宾馆",
     "expect": {"scenic": "黄山", "days": 2, "avoid_respected": "白云宾馆",
                "sunrise_tradeoff": True}},
    {"id": "S19_一天半游不退化为单日", "query": "黄山一天半游",
     "expect": {"scenic": "黄山", "days": 1.5, "half_tail_multi_day": True}},
]


def check_half_tail_multi_day(result):
    """验收：小数天数不退化为单日——1.5 天须跨 2 天且尾日为半日（时段封顶上午/中午）。

    此前 int(1.5)=1 把一天半游退化为单日成单日 4 站（低于 sizing 下限 6）。
    """
    plan = result.get("plan") or {}
    it = plan.get("itinerary", [])
    days = sorted({x["day"] for x in it})
    if days != [1, 2]:
        return False
    tail_periods = [x["period"] for x in it if x["day"] == 2]
    return all(p in ("上午", "中午") for p in tail_periods) and bool(tail_periods)


def check_sunrise_tradeoff(result):
    """验收：唯一山上住宿被避开时，日出安排必须给出取舍说明而非照常声称住宿山上。"""
    plan = result.get("plan") or {}
    pois = [it["poi"] for it in plan.get("itinerary", [])]
    no_lodging = not any(any(k in p for k in ("宾馆", "酒店", "民宿")) for p in pois)
    noted = any("避开山上住宿" in n and "取舍" in n or "恢复住宿" in n
                for n in (plan.get("special_notes") or []))
    return no_lodging and noted


def check_entrance_exit(result, en, ex):
    """验收：入口 POI 为行程首站、出口 POI 为末站（识别出入口被忽略的退化）。"""
    plan = result.get("plan") or {}
    pois = [it["poi"] for it in plan.get("itinerary", [])]
    return bool(pois) and pois[0] == en and pois[-1] == ex


def check_sunrise_honest(result):
    """验收：景区无日出观景点时不得伪造日出安排——须如实说明并照常给出行程。"""
    plan = result.get("plan") or {}
    notes = plan.get("special_notes") or []
    noted = any("无日出观景点" in n for n in notes)
    no_fake = all("日出" not in it["period"] and "日出" not in it["poi"] for it in plan.get("itinerary", []))
    return bool(plan.get("itinerary")) and noted and no_fake
def check_unknown_poi(result, poi):
    """ 验收：图谱中不存在的景点不得被编造进行程。"""
    plan = result.get("plan") or {}
    pois = [it["poi"] for it in plan.get("itinerary", [])]
    return plan is not None and all(poi not in p for p in pois)
def check_avoid(result, expect_poi):
    """ 验收：不去地点不出现在行程，且回答说明避开。"""
    plan = result.get("plan") or {}
    pois = [it["poi"] for it in plan.get("itinerary", [])]
    not_in = all(expect_poi not in p for p in pois)
    noted = any(expect_poi in (plan.get("special_notes") or [])[0:1][0] if plan.get("special_notes") else False
                for _ in [0]) or any(expect_poi in n for n in (plan.get("special_notes") or []))
    return not_in and noted
def check_sunrise(result, expect_poi):
    """ 验收（语义口径）：日出观景点排最后一日首位，且住宿前提以任意表述进入回答——
    规则模式渲染“说明：看日出…住宿山上”，在线润色会转述（如“夜宿山顶”），断言语义不断言前缀。"""
    plan = result.get("plan") or {}
    it = plan.get("itinerary", [])
    last_day = max((x["day"] for x in it), default=1)
    last_first = next((x["poi"] for x in it if x["day"] == last_day), None)
    lodging_mentioned = any(k in result["answer"] for k in ("住宿山上", "夜宿", "住宿", "山上酒店"))
    return last_first == expect_poi and lodging_mentioned


def check_multi_day(result):
    plan = result.get("plan") or {}
    days = {it["day"] for it in plan.get("itinerary", [])}
    return plan.get("days") == 3 and days == {1, 2, 3}


def check_invariants(result):
    """行程不变量（凡有计划的场景通用）——天号连续、日内时段单调、
    半日封顶上午/中午、住宿节点固定晚上。任何一条被破坏即规划回归。"""
    plan = result.get("plan") or {}
    it = plan.get("itinerary", [])
    if not it:
        return True
    period_order = {"上午": 0, "中午": 1, "下午": 2, "晚上": 3, "未标注时段": 4}
    days = sorted({x["day"] for x in it})
    if days != list(range(1, len(days) + 1)):
        return False
    for d in days:
        seq = [period_order.get(x["period"], 9) for x in it if x["day"] == d]
        if seq != sorted(seq):
            return False
    if plan.get("days") == 0.5:
        if any(x["period"] not in ("上午", "中午") for x in it):
            return False
    for x in it:
        if any(k in x["poi"] for k in ("宾馆", "酒店", "民宿", "饭店")) and x["period"] != "晚上":
            return False
    return True


def check_must(result, expect_poi):
    """验收：必去地点必须在行程中，且回答/贴士说明必去落实（识别 must 不可达代码退化）。"""
    plan = result.get("plan") or {}
    pois = [it["poi"] for it in plan.get("itinerary", [])]
    in_plan = any(expect_poi in p for p in pois)
    noted = any(expect_poi in n for n in (plan.get("special_notes") or [])) \
        or expect_poi in result["answer"]
    return in_plan and noted


def evaluate_scenario(sc: dict, result: dict, rules: bool = True) -> dict:
    """单场景验收检查（run_tests 与  消融共用同一口径，避免两处断言漂移）。

    rules=True 时 tips_in_answer 为硬检查（离线渲染器必须保证贴士进回答）；
    在线润色可能转述/省略，为软检查（计划里有贴士即可）。
    """
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
        elif k == "sunrise_last_day_first":
            checks["sunrise_last_day_first"] = check_sunrise(result, v)
        elif k == "unknown_poi_not_in_plan":
            checks["unknown_poi_not_in_plan"] = check_unknown_poi(result, v)
        elif k == "avoid_respected":
            checks["avoid_respected"] = check_avoid(result, v)
        elif k == "must_respected":
            checks["must_respected"] = check_must(result, v)
        elif k == "sunrise_honest":
            checks["sunrise_honest"] = check_sunrise_honest(result)
        elif k == "entrance_first":
            plan = result.get("plan") or {}
            pois = [it["poi"] for it in plan.get("itinerary", [])]
            checks["entrance_first"] = check_entrance_exit(result, v, sc["expect"]["exit_last"])
        elif k == "exit_last":
            pass  # 已并入 entrance_first 的端点检查
        elif k == "sunrise_tradeoff":
            checks["sunrise_tradeoff"] = check_sunrise_tradeoff(result)
        elif k == "half_tail_multi_day":
            checks["half_tail_multi_day"] = check_half_tail_multi_day(result)
        elif k == "multi_visitor":
            vt = intent.get("visitor_types") or []
            checks["multi_visitor"] = all(v in vt for v in v)
        elif k == "multi_day":
            checks["multi_day"] = check_multi_day(result)
        elif k == "seasonal_note":
            warnings = (result["plan"] or {}).get("feasibility_warnings", [])
            checks["seasonal_note"] = any("时段提示" in w for w in warnings)
        elif k == "tips_in_answer":
            # 离线渲染器保证贴士进回答（硬检查）；在线润色可能省略（软检查）
            plan = result.get("plan") or {}
            if not rules:
                checks["tips_in_answer"] = plan is not None and len(plan.get("tips") or []) > 0
            else:
                tip_keys = [t["suggestion"][:8].strip() for t in (plan.get("tips") or [])[:4]]
                checks["tips_in_answer"] = plan is not None and any(
                    k in result["answer"] for k in tip_keys if k)
        elif k == "feasibility_in_answer":
            # 验收：警告文本出现在最终回答中
            checks["feasibility_in_answer"] = v in result["answer"]
        else:
            checks[k] = intent.get(k) == v
    tool_calls = [t for t in result["trace"] if t.get("step") == "action"]
    checks["tools_called"] = len(tool_calls) >= (0 if sc["expect"].get("fallback") else 3)

    def answer_covers_plan(res):
        """最终回答必须覆盖计划内容（真实检查，非恒真）——
        有计划时回答需提及至少 60% 行程站点名；回退场景需列出全部支持景区。"""
        plan = res.get("plan")
        if plan is None:
            return all(a in res["answer"] for a in ("黄山", "九寨沟", "颐和园"))
        pois = [it["poi"] for it in plan["itinerary"]]
        if not pois:
            return False
        hit = sum(1 for poi in pois if poi in res["answer"])
        return hit >= max(1, int(0.6 * len(pois)))

    checks["tools_used_in_answer"] = answer_covers_plan(result)
    checks["itinerary_invariants"] = check_invariants(result)
    if result["plan"]:
        n_pois = len(result["plan"]["itinerary"])
        expected_n = {0.5: (3, 6), 1: (5, 9), 1.5: (6, 11), 2: (8, 13),
                      3: (9, 14), 3.5: (10, 15), 4: (11, 16), 5: (12, 17)}[sc["expect"].get("days", 1)]
        checks["itinerary_size"] = expected_n[0] <= n_pois <= expected_n[1] + 2
        checks["tips_attached"] = len(result["plan"]["tips"]) > 0
    return checks


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
    online = llm.available and not args.rules
    trace_dir = OUT / ("traces_llm" if online else "traces")
    trace_dir.mkdir(exist_ok=True)
    results = []
    for sc in SCENARIOS:
        agent = ReActAgent(llm)
        result = agent.run(sc["query"])
        checks = evaluate_scenario(sc, result, rules=args.rules)
        tool_calls = [t for t in result["trace"] if t.get("step") == "action"]
        passed = all(checks.values())
        results.append({"scenario": sc["id"], "query": sc["query"], "passed": passed,
                        "checks": checks, "intent": result["intent"],
                        "n_tool_calls": len(tool_calls), "answer_head": result["answer"][:120]})
        # elapsed 只打印不入库：持久化产物保持确定性，重复构建零 diff
        (trace_dir / f'trace_{sc["id"]}.json').write_text(
            json.dumps({k: v for k, v in result.items() if k != "elapsed"},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        print(f'{"PASS" if passed else "FAIL"} {sc["id"]} | tools={len(tool_calls)} | {result["elapsed"]}s')

    report = {
        "mode": ("llm（在线模式）" if online else
                 "rules（--rules 强制离线）" if args.rules else
                 "rules（未配置 LLM API，内置规划器）"),
        "n_scenarios": len(SCENARIOS),
        "n_passed": sum(1 for r in results if r["passed"]),
        "results": results,
        "evidence": "每次运行的完整 ReAct trace（含每步 thought/action/observation）见 output/traces/",
    }
    # 在线模式单独记录，不覆盖离线验收证据（提示词 §2.3）
    suffix = "_llm" if online else ""
    trace_dir = OUT / ("traces" if not online else "traces_llm")
    trace_dir.mkdir(exist_ok=True)
    (OUT / f"test_report{suffix}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    plans = []
    for sc in SCENARIOS:
        t = json.loads((trace_dir / f'trace_{sc["id"]}.json').read_text(encoding="utf-8"))
        if t.get("plan"):
            plans.append({"scenario": sc["id"], **t["plan"]})
    (OUT / f"itineraries{suffix}.json").write_text(json.dumps(plans, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("mode", "n_scenarios", "n_passed")}, ensure_ascii=False))
    failed = [r["scenario"] for r in results if not r["passed"]]
    if failed:
        print(f"FAILED scenarios: {failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
