# 实验 7 旅游规划 Agent

基于 LangGraph `create_react_agent` 实现模型自主决策的 ReAct Agent：模型在循环中决定调用哪些图谱工具、读取观察并判断证据是否足够，输出 JSON 规划依据；编排、时间预算与可行性校验保持确定性，保证行程中的每个景点都可回溯到图谱查询；最后由 LLM 润色文案并做站点覆盖率检查。

提交结果取自 2026 年 11 月 14 日入库的一批在线实测（gemini-3-flash，支持原生工具调用），14/14 达到该批功能断言。14 个场景采用混合意图解析，13 个生成行程的场景由模型自主调用 9–19 次图谱工具并完成润色；S5（故宫）走能力边界回退。报告记录了首轮 8/14 的失败归因与修复（避开确认话术、想去目的地入必去、意图提示收紧、候选补足）。

[output/online/](output/online/) 保存该批次汇总 `test_report_llm.json`、结构化行程 `itineraries_llm.json` 与 14 份轨迹 `traces_llm/`（含逐步 action/observation）。

在 `task7/` 将 `config.example.json` 复制为 `config.json`，填写 API Key、base_url 与模型名（需支持 OpenAI 工具调用协议）。从仓库根目录运行：

```text
python task7/src/agent_cli.py
python task7/src/run_tests.py --llm
```

第二条命令重跑 14 场景在线实测并写入 `local/agent_llm/`，归档批次供正式报告使用；未配置模型时 `agent_cli.py` 以规则模式离线运行（意图解析、编排与渲染全部可复现）。依赖见根目录 `requirements.txt`（langchain-core / langchain-openai / langgraph）。
