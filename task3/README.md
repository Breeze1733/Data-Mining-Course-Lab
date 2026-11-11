# 实验 3 游览路线的层级结构挖掘

从 46 条官方路线分支归纳六种描述格式，统一表示步骤、时段、景点、交通和活动。39 条有序路线均得到步骤，其中 36 条拆成至少两步，另外 3 条保留为含多个景点的单步骤段落。对缺乏时段信息的步骤保留“未标注时段”。7 条无固定顺序的主题方案单独标记。

- `output/parsed_routes.jsonl`、`time_hierarchy.jsonl`、`route_format_analysis.json` 和 `name_normalization.json` 支持查看解析与归一化结果。
- `output/tourist_routes.jsonl` 和 `official_vs_tourist.json` 保存 229 条游客路线及三景区的覆盖度、顺序一致性和时间分配对比。图表和代表路线树见 `output/figs/`。

在仓库根目录运行 `python tests/run.py`。本实验入口依次为 `src/parse_routes.py`、`src/compare_routes.py`、`src/build_hierarchy_view.py`。
