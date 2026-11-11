# 实验 3 游览路线的层级结构挖掘

从 46 条官方路线分支归纳六种描述格式，统一表示步骤、时段、景点、交通和活动。39 条有序路线均得到步骤，其中 34 条拆成至少两步，另外 5 条保留为含多个景点的单步骤段落。全部 560 个片段中，416 个是带 POI/交通/时间/时长/站点/住宿信号的路线步骤，144 条纯叙述片段单独存放在 `narrative_segments`，不再计入步骤和时间层级。对缺乏时段信息的步骤保留“未标注时段”。7 条无固定顺序的主题方案单独标记。

游客路线按游记中 POI 的出现顺序提取，其中可能包含介绍或推荐，并不都代表实际移动。颐和园和黄山官方路线大多没有时段信息；时段分析主要来自九寨沟官方文本和游客游记。

- `output/parsed_routes.jsonl`、`time_hierarchy.jsonl`、`route_format_analysis.json` 和 `name_normalization.json` 支持查看解析与归一化结果；每个 step 带可回溯 `raw_content` 的 `span` 和 `span_status`。
- `output/tourist_routes.jsonl` 和 `official_vs_tourist.json` 保存 225 条游客路线及三景区的覆盖度、顺序一致性和时间分配对比；游客时间分配只统计这 225 条路线。图表和代表路线树见 `output/figs/`。
- `output/tourist_time_hierarchy.jsonl` 与 `tourist_routes.jsonl` 按 `record_id` 一一对应（225 条，含 36 条无时段空记录）；`output/validation.json` 汇总官方/游客两侧的计数与一致性检查。

在仓库根目录依次运行 `python task3/src/parse_routes.py`、`python task3/src/compare_routes.py`、`python task3/src/build_hierarchy_view.py`。
