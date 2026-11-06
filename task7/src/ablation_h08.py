"""实验7 H08 消融：各模块对最终规划的贡献。

对 14 个验收场景逐一禁用单个模块后重跑（规则模式），记录通过数与受影响场景，
量化每个模块对最终规划质量的边际贡献。禁用方式为运行期补丁（类方法替换：
先备份原引用，覆盖，跑完恢复），不改动生产代码路径；基线与消融共用
run_tests.evaluate_scenario 同一口径。

消融项（共 10 项 + 基线）：
- no_tips         禁用 query_conditions（条件贴士消失）
- no_order_check  禁用 query_order（官方后继校验消失）
- no_path         禁用 query_path（多跳动线查询消失）
- no_template     禁用官方路线模板（routes_by_scenic → []，编排退化为图谱拓扑排序）
- no_poi_cond     禁用 query_poi_conditions（站点级可行性校验失去数据源）
- no_avoid_must   意图解析丢弃 avoid/must（"不去/必去"约束失效）
- no_lodging      禁用住宿注入（_find_lodging_poi → None）
- no_sunrise      禁用日出重定位（_find_sunrise_poi → None）
- no_budget       禁用时段预算（_apply_time_budget 直通）
- no_visitormatch query_pois/query_conditions 的 visitor_type 恒为 None（人群适配消失）

输出 task7/output/ablation_modules.json：
每模块 n_passed（14 场景）、失败场景列表、相对基线的受影响场景数（贡献度）。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from agent_cli import GraphTools, IntentParser, ReActAgent
from run_tests import SCENARIOS, evaluate_scenario

OUT = ROOT / "output"

_ORIG = {}  # 原方法引用，_make_patches 时填充


def _err(**_kw):
    return {"error": "H08 消融：该工具已禁用"}


def _make_patches() -> dict[str, tuple[str, callable, callable]]:
    """名称 → (说明, 打补丁, 恢复)。恢复一律 setattr 回原引用，不用 delattr。"""
    _ORIG.update({
        "query_conditions": GraphTools.query_conditions,
        "query_order": GraphTools.query_order,
        "query_path": GraphTools.query_path,
        "routes_by_scenic": GraphTools.routes_by_scenic,
        "query_poi_conditions": GraphTools.query_poi_conditions,
        "query_pois": GraphTools.query_pois,
        "_find_lodging_poi": ReActAgent._find_lodging_poi,
        "_find_sunrise_poi": ReActAgent._find_sunrise_poi,
        "_apply_time_budget": ReActAgent._apply_time_budget,
        "parse": IntentParser.parse,
    })
    patches: dict[str, tuple[str, callable, callable]] = {}

    def add(name, desc, apply, undo):
        patches[name] = (desc, apply, undo)

    # ── 工具层消融 ──────────────────────────────────────────────
    add("no_tips", "禁用 query_conditions（条件贴士消失）",
        lambda: setattr(GraphTools, "query_conditions",
                        lambda self, scenic, visitor_type=None, limit=6: _err()),
        lambda: setattr(GraphTools, "query_conditions", _ORIG["query_conditions"]))
    add("no_order_check", "禁用 query_order（官方后继校验消失）",
        lambda: setattr(GraphTools, "query_order", lambda self, scenic, poi: _err()),
        lambda: setattr(GraphTools, "query_order", _ORIG["query_order"]))
    add("no_path", "禁用 query_path（多跳动线查询消失）",
        lambda: setattr(GraphTools, "query_path", lambda self, scenic, from_poi, to_poi: _err()),
        lambda: setattr(GraphTools, "query_path", _ORIG["query_path"]))
    add("no_template", "禁用官方路线模板（编排退化为图谱拓扑排序）",
        lambda: setattr(GraphTools, "routes_by_scenic", lambda self, scenic, days: []),
        lambda: setattr(GraphTools, "routes_by_scenic", _ORIG["routes_by_scenic"]))
    add("no_poi_cond", "禁用 query_poi_conditions（站点级可行性校验失去数据源）",
        lambda: setattr(GraphTools, "query_poi_conditions", lambda self, scenic, poi: _err()),
        lambda: setattr(GraphTools, "query_poi_conditions", _ORIG["query_poi_conditions"]))
    add("no_visitormatch", "query_pois/query_conditions 的 visitor_type 恒为 None（人群适配消失）",
        lambda: (setattr(GraphTools, "query_pois",
                        lambda self, scenic, visitor_type=None, limit=8:
                        _ORIG["query_pois"](self, scenic, None, limit)),
                 setattr(GraphTools, "query_conditions",
                         lambda self, scenic, visitor_type=None, limit=6:
                         _ORIG["query_conditions"](self, scenic, None, limit))),
        lambda: (setattr(GraphTools, "query_pois", _ORIG["query_pois"]),
                 setattr(GraphTools, "query_conditions", _ORIG["query_conditions"])))

    # ── 规划器方法消融 ──────────────────────────────────────────
    add("no_lodging", "禁用住宿注入（多日行程无住宿 POI）",
        lambda: setattr(ReActAgent, "_find_lodging_poi", lambda self, scenic: None),
        lambda: setattr(ReActAgent, "_find_lodging_poi", _ORIG["_find_lodging_poi"]))
    add("no_sunrise", "禁用日出重定位（看日出特殊需求失效）",
        lambda: setattr(ReActAgent, "_find_sunrise_poi", lambda self, scenic, ordered: None),
        lambda: setattr(ReActAgent, "_find_sunrise_poi", _ORIG["_find_sunrise_poi"]))
    add("no_budget", "禁用时段预算（POI 不裁剪，行程可能超载）",
        lambda: setattr(ReActAgent, "_apply_time_budget",
                        lambda self, ordered, days, n_days, sp, notes, trace: ordered),
        lambda: setattr(ReActAgent, "_apply_time_budget", _ORIG["_apply_time_budget"]))

    # ── 意图解析消融（包装 parse，丢弃 avoid/must）───────────────
    def _parse_no_avoid(self, query, trace):
        intent = _ORIG["parse"](self, query, trace)
        intent["avoid"] = []
        intent["must"] = []
        return intent

    add("no_avoid_must", "意图解析丢弃 avoid/must（不去/必去约束失效）",
        lambda: setattr(IntentParser, "parse", _parse_no_avoid),
        lambda: setattr(IntentParser, "parse", _ORIG["parse"]))
    return patches


def _run_all_scenarios() -> tuple[list, int, int]:
    """跑全部场景（规则模式），返回 (失败列表, 工具调用总数, 回答总字数)。"""
    fails, n_tools, n_chars = [], 0, 0
    for sc in SCENARIOS:
        agent = ReActAgent(None)
        result = agent.run(sc["query"])
        checks = evaluate_scenario(sc, result, rules=True)
        n_tools += len([t for t in result["trace"] if t.get("step") == "action"])
        n_chars += len(result["answer"])
        if not all(checks.values()):
            fails.append({"scenario": sc["id"],
                          "failed_checks": [k for k, v in checks.items() if not v]})
    return fails, n_tools, n_chars


def main() -> int:
    fails, n_tools, n_chars = _run_all_scenarios()
    baseline = {"ablation": "baseline（无禁用）", "description": "完整管线基线",
                "n_passed": len(SCENARIOS) - len(fails), "n_failed": len(fails),
                "failed_scenarios": fails,
                "avg_tool_calls": round(n_tools / len(SCENARIOS), 1),
                "avg_answer_chars": round(n_chars / len(SCENARIOS))}
    print(f'baseline         pass={baseline["n_passed"]:2d}/{len(SCENARIOS)}')
    rows = []
    base_pass = baseline["n_passed"]
    for name, (desc, apply, undo) in _make_patches().items():
        apply()
        try:
            fails, n_tools, n_chars = _run_all_scenarios()
        finally:
            undo()
        rows.append({"ablation": name, "description": desc,
                     "n_passed": len(SCENARIOS) - len(fails), "n_failed": len(fails),
                     "failed_scenarios": fails,
                     "avg_tool_calls": round(n_tools / len(SCENARIOS), 1),
                     "avg_answer_chars": round(n_chars / len(SCENARIOS)),
                     "contribution_n_scenarios": base_pass - (len(SCENARIOS) - len(fails))})
        print(f'{name:16s} pass={rows[-1]["n_passed"]:2d}/{len(SCENARIOS)} '
              f'fail={len(fails)} avg_tools={rows[-1]["avg_tool_calls"]}')
    report = {
        "title": "H08 模块消融：各模块对最终规划的贡献（实验7，规则模式）",
        "method": "对 14 个验收场景逐一禁用单个模块后重跑；口径与 run_tests.evaluate_scenario 一致；"
                  "contribution = 基线通过数 − 消融后通过数（受该模块影响的场景数）",
        "n_scenarios": len(SCENARIOS),
        "baseline": baseline,
        "ablations": sorted(rows, key=lambda r: -r["contribution_n_scenarios"]),
        "notes": [
            "contribution=0 不代表模块无用：验收断言未覆盖的行为（如排序质量、贴士排序）不受场景断言约束",
            "消融仅运行期补丁，生产代码路径未改动；基线与消融均为确定性规则模式（任务1-6离线，任务7 rules）",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ablation_modules.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({r["ablation"]: r["contribution_n_scenarios"] for r in rows},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
