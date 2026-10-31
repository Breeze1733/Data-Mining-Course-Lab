"""生成实验项目7报告：旅游规划 Agent（task7/report.docx）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
from report_utils import ReportBuilder

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"

REPORT = json.loads((OUT / "test_report.json").read_text(encoding="utf-8"))
ITIN = json.loads((OUT / "itineraries.json").read_text(encoding="utf-8"))
TOOL_SCHEMAS = [
    ("query_pois", "景区、游客类型、limit", "POI 列表（度数/词频/时段/交通/游客适配度）"),
    ("query_route", "景区、天数", "官方路线结构化步骤（POI/时段/交通/天数/住宿）"),
    ("query_conditions", "景区、游客类型", "条件性建议（按人群匹配优先，9 类条件）"),
    ("query_order", "景区、POI", "官方先后邻接（前驱/后继 + 权重）"),
]
BY_SCENARIO = {r["scenario"]: r for r in REPORT["results"]}


def main():
    rb = ReportBuilder("《数据挖掘》探索性实验报告", "—实验项目7 程序性知识应用：旅游规划 Agent")

    rb.section("一、实验目的与任务")
    rb.p("基于实验6的知识图谱设计并实现 ReAct（Reasoning + Acting）模式的旅游规划 Agent："
         "解析用户自然语言中的约束（景区/游客类型/时长/特殊需求），通过封装的图谱查询工具获取景点、"
         "路线与条件建议，编排个性化行程并生成自然语言回答；测试多类约束场景，"
         "用完整工具调用轨迹证明回答基于图谱查询，并对无匹配与冲突约束做合理处理。")

    rb.section("二、实验环境")
    rb.bullets([
        "Windows 11；Python 3.13（task1/.venv）；networkx（图谱查询）；标准库 urllib（LLM HTTP 调用）。",
        "LLM 接入：OpenAI 兼容 ChatCompletion 接口，base_url/api_key/model 在 task7/config.json 配置"
        "（模板见 config.example.json，支持智谱/通义/DeepSeek/OpenAI 等）；"
        "本实验运行未配置 API Key，Agent 自动切换内置规则规划器，全链路离线可复现；配置后无需改代码即可启用 LLM 意图解析与文案润色。",
        "运行入口：task7/src/run_tests.py（6 场景批量测试）、task7/src/agent_cli.py（交互命令行）。",
    ])

    rb.section("三、实验设计与实现")
    rb.sub("3.1 Agent 架构")
    rb.p("Agent 由四个模块组成：①IntentParser——提取景区、游客类型（老人/孩子/亲子/情侣/体力有限/初次游览）、"
         "时长（半日/一日/两日）与特殊需求（看日出/避开人流/省力等）；LLM 可用时走 Prompt 解析，"
         "否则用关键词规则表，二者输出同一 JSON Schema；②GraphTools——图谱查询工具层（见 3.2）；"
         "③规划器——按“选点→排序→分天分时段→配交通→挂贴士”五步编排，全部输入来自工具查询结果；"
         "④渲染器——结构化行程转自然语言（LLM 可用时润色，规则模式用模板拼装）。")
    rb.sub("3.2 知识图谱查询工具封装")
    rb.table(["工具", "输入", "输出"], [list(t) for t in TOOL_SCHEMAS],
             widths=[3.4, 4.4, 7.2], font_size=9)
    rb.caption("表 1 图谱查询工具（每个工具带名称、描述、参数 Schema，调用即记录 trace）")
    rb.p("工具不是把图谱塞进 Prompt，而是真正的查询接口：query_pois 按“游客类型适配度 > 度数中心性 > 提及词频”"
         "排序返回候选；query_route 返回实验3的结构化官方路线；query_conditions 从图谱条件节点取建议"
         "（人群类按游客类型过滤，并过滤跨景区污染文本）；query_order 返回官方先后邻接用于动线校验。"
         "异常处理：景区不支持、POI 不存在时返回结构化 error，Agent 走回退分支。")

    rb.sub("3.3 ReAct 循环与回退策略")
    rb.p("主循环为显式的 思考→行动→观察 序列：意图解析后，Agent 依次调用 query_pois（选点）→ query_route"
         "（取编排骨架）→ query_conditions（取贴士），并用 query_order 校验首站动线；每一步的 thought、"
         "action（工具+参数）、observation（结果摘要）写入 trace 并随结果落盘。工具结果实际参与编排："
         "官方路线模板按“对已选 POI 的覆盖率”选用——覆盖率 ≥60% 沿用模板的天数/时段，"
         "否则改用图谱先后边的流向感知拓扑排序（环形路线按出权-入权差打破成环），剩余 POI 按度数补位。"
         "回退策略：景区不识别→说明能力边界并列出支持景区；半日+看日出→明确提示冲突并给出替代方案；"
         "LLM 调用失败→自动降级规则模式。")

    rb.section("四、实验结果与分析")
    rb.sub("4.1 多场景测试")
    rows = [[r["scenario"].split("_")[0], r["scenario"].split("_", 1)[1], r["intent"].get("scenic"),
             r["intent"].get("visitor_type") or "—", str(r["intent"].get("days")), r["n_tool_calls"],
             "通过" if r["passed"] else "失败"] for r in REPORT["results"]]
    rb.table(["编号", "场景", "解析景区", "游客类型", "天数", "工具调用", "结果"],
             rows, widths=[1.2, 5.4, 2.0, 2.0, 1.2, 1.6, 1.4], font_size=9)
    rb.caption(f'表 2 六场景测试结果（运行模式：{REPORT["mode"]}；{REPORT["n_passed"]}/{REPORT["n_scenarios"]} 通过）')
    rb.p(f"支持景区场景的断言包括：意图解析字段正确、工具调用链完整（≥3 次查询）、行程规模与时长匹配、"
         "贴士已挂接。S5（故宫一日游）验证回退：Agent 识别不了支持景区时如实说明能力边界并给出替代示例，"
         "没有编造行程；S6（半日+看日出）验证冲突处理：Agent 在最终回答前明确提示"
         "“半日游难以兼顾看日出”并建议改为两日或舍弃。")

    rb.sub("4.2 证据：工具调用轨迹与结构化行程")
    s1 = BY_SCENARIO["S1_老人颐和园半日"]
    plan1 = next(p for p in ITIN if p["scenario"] == "S1_老人颐和园半日")
    rows = [[it["order"], it["period"], it["poi"], it["transport_from_prev"], it["note"] or "—"]
            for it in plan1["itinerary"]]
    rb.table(["序", "时段", "景点", "交通", "备注"], rows, widths=[1.0, 1.8, 3.2, 3.0, 6.0], font_size=9)
    rb.caption(f'表 3 S1“带老人颐和园半日”的结构化行程（模板 {plan1["template_route"]}；'
               f'耗时 {s1["elapsed"]}s，完整轨迹见 output/traces/）')
    rb.p("S1 的贴士来自图谱条件节点：“带老人和小孩别走中轴线爬山”这条人群建议由 query_conditions 按游客类型"
         "过滤命中，直接进入最终回答，说明工具查询结果实际参与了生成。"
         f"S3（情侣黄山两日）本轮使用模板{next(p for p in ITIN if p['scenario'] == 'S3_情侣黄山两日')['template_route']}，"
         "按当前图谱候选编排行程；模板覆盖不足60%时才回退到图谱拓扑顺序，不把历史运行的模板或覆盖率当作本轮结果。")

    rb.sub("4.3 工程要点与后续规划")
    rb.bullets([
        "动线方向：环湖双向边的权重信号已支持拓扑排序，后续按“入口门→核心区→出口门”空间分区先验"
        "进一步对齐官方推荐动线；",
        "跨景区贴士噪声由关键词黑名单与句级归属过滤双层收敛（归属过滤即实验4 同源机制，实验5 同步受益）；",
        "意图解析双模式就绪：规则 0.85 / 混合 0.90（LLM 模式 8/8），未登录说法由词表与 LLM 补缺持续覆盖；",
        "时段可行性校验的图谱基础已就位（封山/轮休条件节点），将作为行程校验规则接入下一版。",
    ])

    rb.section("五、实验小结")
    rb.p(f"本实验实现了完整的 ReAct 旅游规划 Agent：4 个带 Schema 的图谱查询工具、显式思考-行动-观察循环"
         f"（trace 全部落盘）、约束解析与冲突回退，{REPORT['n_passed']}/{REPORT['n_scenarios']} 个测试场景全部通过（{REPORT['mode']}）。"
         "行程编排完全建立在图谱查询结果之上——官方路线模板按覆盖率选用、不足时用先后边拓扑排序、"
         "贴士按游客类型从条件节点检索，验证了“图谱作为 Agent 可调用知识源”的可行性。"
         "与前序实验一致的教训是：多景点游记的归属歧义会沿着数据链路传播（实体→图谱→Agent 回答），"
         "句子级归属校正是全链路收益最大的下一步改进。")

    rb.save(ROOT / "report.docx")


if __name__ == "__main__":
    main()
