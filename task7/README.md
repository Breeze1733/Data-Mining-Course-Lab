# 实验项目7：旅游规划 Agent（ReAct 模式）

基于实验6知识图谱的旅游规划 Agent：意图解析 → 图谱查询工具调用 → 行程编排 → 文案生成，
显式“思考-行动-观察”循环并记录完整 trace。

## LLM 配置（可选）

复制 `config.example.json` 为 `config.json` 并填入任意 OpenAI 兼容接口（智谱/通义/DeepSeek/OpenAI 均可）
的 `base_url`、`api_key`、`model`。**未配置时自动使用内置规则规划器**（意图解析、编排、文案全部离线可复现），
LLM 仅用于意图解析与最终文案润色，行程编排始终基于图谱查询结果。

## 目录结构

```
src/
  graph_tools.py    图谱查询工具层（4 个工具，带参数 Schema 与调用 trace）
  agent_cli.py      LLMClient + IntentParser + ReActAgent + 交互命令行
  run_tests.py      6 场景批量测试（证据落盘）
output/
  traces/trace_*.json   每个场景的完整 ReAct 轨迹（thought/action/observation）
  itineraries.json      结构化行程
  test_report.json      测试汇总
config.example.json    LLM 配置模板
report.docx            实验项目7报告
```

## 运行方法（在 task1 虚拟环境内）

```powershell
cd task1
..\.venv\Scripts\python.exe -X utf8 ..\task7\src\run_tests.py      # 批量测试
..\.venv\Scripts\python.exe -X utf8 ..\task7\src\agent_cli.py      # 交互命令行
```

## 工具清单

| 工具 | 输入 | 输出 |
|---|---|---|
| query_pois | 景区、游客类型、limit | POI 列表（度数/词频/时段/交通/游客适配度） |
| query_route | 景区、天数 | 官方路线结构化步骤 |
| query_conditions | 景区、游客类型 | 条件性建议（人群/装备/天气…） |
| query_order | 景区、POI | 官方先后邻接（前驱/后继+权重） |

## 关键结论

- 6/6 场景通过：含无匹配景区回退（S5）与“半日+看日出”冲突提示（S6）。
- 每次规划真实调用 4 个图谱工具，官方路线模板按已选 POI 覆盖率选用（<60% 时改用图谱先后边拓扑排序）。
