# 实验项目3：游览路线的层级结构挖掘

把 46 条官方路线分支解析为统一的步骤化结构，构建“天 → 时段 → 步骤”时间层级，并从游记中提取游客实际路线与官方路线做覆盖度/顺序一致性/时间分配三维对比。

## 目录结构

```
src/
  parse_routes.py         官方路线格式分类 + 结构化解析（六种格式、段级标记、连接点去重）
  compare_routes.py       游客路线提取 + 官方/游客三维度对比 + 图
  build_hierarchy_view.py 时间层级视图 + 代表路线树图
  build_report3.py        生成 report.docx
output/
  route_format_analysis.json   格式规律分析
  parsed_routes.jsonl          46 条结构化路线
  time_hierarchy.jsonl         时间层级视图（含时段推断）
  name_normalization.json      名称归一化规则与示例
  tourist_routes.jsonl         230 条游客实际路线（POI 序列）
  official_vs_tourist.json     对比指标（覆盖度/Jaccard/Kendall tau/时间分配）
  time_hierarchy_summary.json  层级聚合统计
  figs/                        对比图与 3 张层级树图
report.docx             实验项目3报告
```

## 运行方法（在 task1 虚拟环境内）

```powershell
cd task1
.\.venv\Scripts\python.exe -X utf8 ..\task3\src\parse_routes.py          # 结构化解析
.\.venv\Scripts\python.exe -X utf8 ..\task3\src\compare_routes.py        # 官方 vs 游客对比
.\.venv\Scripts\python.exe -X utf8 ..\task3\src\build_hierarchy_view.py  # 时间层级与树图
.\.venv\Scripts\python.exe -X utf8 ..\task3\src\build_report3.py         # 报告
```

## 输入 → 输出

| 输入 | 输出 |
|---|---|
| task1 官方路线 46 条 + task2 词典/实体 | parsed_routes.jsonl、route_format_analysis.json |
| parsed_routes + 实体 | time_hierarchy.jsonl、figs/tree_*.png |
| task2 实体输出（游记 POI 序列） | tourist_routes.jsonl、official_vs_tourist.json、figs/compare_*.png |

## 关键结论

- 39 条有序路线全部解析（平均 8.8 步/条）；九寨沟官方是“日程表”，黄山/颐和园是“节点链”。
- 游客 vs 官方：覆盖度 0.39–0.44，顺序一致性 Kendall tau 九寨沟 0.663 > 黄山 0.518 > 颐和园 0.25，梯度由空间约束强度决定（游客路线已按 in_scenic 在景标记过滤）。
- 官方路线时间止于闭园，游客 17% 的时间表达落在夜间（演出/晚餐/酒店）。
