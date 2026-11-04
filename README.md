# 《数据挖掘》探索性实验：景区游览指南的程序性知识挖掘

黄山 / 九寨沟 / 颐和园三景区多源文本的程序性知识挖掘，按实验项目存放于 task1 至 task7：
采集清洗 → 实体识别 → 路线解析 → 共指消解 → 条件建议抽取 → 知识图谱 → 旅游规划 Agent。

## 复现

使用仓库根目录的同一个 Python 环境（`.venv`），安装 `requirements.txt` 中的依赖后，在仓库根目录运行：

```bash
python tests/run.py                              # 静态复现：全链路重建 + 单元测试 + 任务7 离线规则模式
python tests/run.py --task7 llm                  # 动态验收：任务7 在线 LLM 模式（产物写入 *_llm.json / traces_llm/）
python tests/run.py --task7 both                 # 先静态复现，再在线动态验收
python common/regression_check.py                # 人工标注评测集回归守护（应全绿）
python common/report_audit.py                    # 报告-数据一致性审计（应 70/70）
```

程序读取已入库的 `task1/data/processed/dataset_clean.jsonl`，顺序执行实体识别及下游实验，
更新各实验输出与图表。默认离线运行，不重新联网采集，也不重填人工标注判定。
Agent 未配置 API 时使用规则模式；配置 `task7/config.json`（OpenAI 兼容接口）后启用 LLM。

实验2 的 baseline 和 refined 由同一个识别器运行，分别用于迭代对比和最终下游输入；
正式结果统一保存在各任务的 `output` 目录。

## 目录结构

| 目录 | 实验 | 报告 |
|---|---|---|
| task1 | 数据采集与预处理 | task1/report.docx |
| task2 | 实体识别 | task2/report.docx |
| task3 | 路线层级结构 | task3/report.docx |
| task4 | 共指消解 | task4/report.docx |
| task5 | 条件建议抽取 | task5/report.docx |
| task6 | 知识图谱融合 | task6/report.docx |
| task7 | 旅游规划 Agent | task7/report.docx |
| task1/scripts | 采集爬虫 | — |
| common | 回归守护 / 审计 / 快照等评测基础设施 | — |
| docs | 过程账本（PROGRESS / METRICS / DECISIONS / BACKLOG / review） | — |
| metrics | 指标快照（`snapshot_latest.json` 为最新） | — |

总结反思为根目录的 `实验总结反思.docx`。公共名称映射在 `task2/resources`、
`common/entity_identity.py`，地点别名在 `task2/resources/poi_aliases.csv`，由实体、路线和图谱统一读取。

## 技术路线

实验1–6 为纯静态管线（jieba + 词典 + 正则 + 规则，无 key 可复现）；LLM 仅实验7 按任务书要求使用
（意图解析混合模式、文案润色），`docs/README.md` 有接入范围与命名约定的完整说明。
最终指标见 `docs/METRICS.md` 终表。
