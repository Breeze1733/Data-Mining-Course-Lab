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

## 目录约定

每个 `taskN/` 统一为：`src/`（代码）、`output/`（该实验的结构化成果，入库）、`report.docx`（报告）、`README.md`（方法与运行方式）。中间数据放各任务自己的 `data/`，不入库，可由 `src/` 下的脚本再生。

`task1` 是采集任务，多一层原始快照，按 `data/raw`（HTML/JSON 快照）→ `data/collected`（采集整理结果）→ `data/processed`（清洗管线产物）三段组织。其中交付物与下游公共输入已用 `!` 规则单独放行入库，其余继续忽略。

## 产物清单

| 任务 | 入库的关键产物 |
|---|---|
| `task1/` | `data/processed/dataset_clean.jsonl`（271 条）、`quality_report.json`、`cleaning_examples.json`、`rejected_records.jsonl`（32 条）；`data/raw/official_routes.jsonl`（46 条）；`data/collected/scenic_guide_dataset.xlsx` |
| `task2/` | `output/exp2/entities_{baseline,refined}.jsonl`、`entity_dictionary.json`、`entity_schema.md`、`iter_compare.json`、`figs/` |
| `task3/` | `output/parsed_routes.jsonl`、`time_hierarchy.jsonl`、`official_vs_tourist.json`、`name_normalization.json`、`figs/` |
| `task4/` | `output/pronoun_cases.jsonl`、`annotation_gold.json`、`evaluation.json`、`resolved_examples.json`、`figs/` |
| `task5/` | `output/conditional_pairs.jsonl`、`mapping_table.json`、`conditional_mapping_table.xlsx`、`review_summary.json`、`figs/` |
| `task6/` | `output/graph_{nodes,edges}.csv`、`knowledge_graph.graphml`、`graph_{景区}.html`、`figs/` |
| `task7/` | `output/itineraries.json`、`test_report.json`、`traces/`（6 组场景轨迹） |

## 数据流

`task1` 产出清洗后的主数据集 `task1/data/processed/dataset_clean.jsonl`（271 条）与官方路线结构 `task1/data/raw/official_routes.jsonl`（46 条），是实验 2–7 的公共输入；`task1/READ.md` 说明采集方法。跨任务公共工具（报告版式）在 `common/`。

Python 环境：`task1/.venv`（复用；依赖见 `task1/requirements.txt`，另加 jieba、matplotlib、wordcloud、networkx、pandas、openpyxl、python-docx）。运行示例：

```powershell
cd task1
.\.venv\Scripts\python.exe -X utf8 ..\task2\src\extract_entities.py --iteration refined
```

## 合并版本复现

使用已入库的主语料离线重建实验2、3、4、6、7：`python common/run_pipeline.py --reports`。本轮审核依据、两个原始提交、统一案例和合并决策见`review/merge_20261029/README.md`。实验1主数据与实验5条件建议未改变。

实体、路线与图谱共用`common/entity_identity.py`和`task2/resources/poi_aliases.csv`；运行`python common/verify_entity_identity.py`检查别名目标和路线引用。配置化实体接口见task2/README.md，统计口径与主报告分别说明。
