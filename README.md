# 《数据挖掘》探索性实验：景区游览指南的程序性知识挖掘

按实验项目分文件夹组织，一个实验项目一个 `taskN/`：

| 目录 | 实验项目 | 报告 |
|---|---|---|
| `task1/` | 实验项目1 景区指南数据采集与预处理 | `task1/report.docx` |
| `task2/` | 实验项目2 游览步骤的实体识别 | `task2/report.docx` |
| `task3/` | 实验项目3 游览路线的层级结构挖掘 | `task3/report.docx` |
| `task4/` | 实验项目4 程序性知识的共指消解 | `task4/report.docx` |
| `task5/` | 实验项目5 条件性游览建议的抽取 | `task5/report.docx` |
| `task6/` | 实验项目6 多源程序性知识融合与图谱可视化 | `task6/report.docx` |
| `task7/` | 实验项目7 旅游规划 Agent | `task7/report.docx` |
| 根目录 `实验总结反思.docx` | 实验总结反思 | — |

每个 `taskN/` 内部：`src/`（代码）、`output/`（该实验的结构化成果，入库提交）、`report.docx`（报告）。中间数据放各任务自己的 `data/`（不入库）。

数据流：`task1` 产出清洗后的主数据集 `task1/data/processed/dataset_clean.jsonl`（271 条）与官方路线结构 `task1/data/raw/official_routes.jsonl`（46 条），是实验 2–7 的公共输入；`task1/READ.md` 说明采集方法。跨任务公共工具（报告版式）在 `common/`。

Python 环境：`task1/.venv`（复用；依赖见 `task1/requirements.txt`，另加 jieba、matplotlib、wordcloud、networkx、pandas、openpyxl、python-docx）。运行示例：

```powershell
cd task1
.\.venv\Scripts\python.exe -X utf8 ..\task2\src\extract_entities.py --iteration refined
```
