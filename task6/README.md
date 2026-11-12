# 实验 6 知识图谱融合与可视化

融合实体、路线结构与条件建议，构建 634 节点、2,825 边的游览知识图谱。实体以规范名和景区对齐，顺序边保留官方及游记的全部方向和证据，条件建议保留可追溯来源。已知事实核验 6/6，各景区子图连通，无孤点。

- `output/knowledge_graph.graphml` 保存完整图谱属性；`graph_nodes.csv` 和 `graph_edges.csv` 保存节点、关系及权重。
- [九寨沟](output/graph_九寨沟.html)、[黄山](output/graph_黄山.html)和[颐和园](output/graph_颐和园.html)交互图保留各景区的全部节点和关系。`output/figs/` 的静态概览筛选高频条件节点，突出主路线。
- `output/graph_stats.json` 和 `graph_validation.json` 保存计数与核验。

实验 6 读取实验 5 的 `mapping_table.json`。在仓库根目录依次运行 `python task6/src/build_graph.py`、`python task6/src/verify_graph.py` 和 `python task6/src/visualize_graph.py`。

同景区条件文本经空白与首尾标点规范化后精确合并。顺序边按每条官方路线每方向 1.0、每篇游记每方向 0.5 计权，保留双向证据；官方方向优先推荐。事实核验按去重后的官方路线 ID 计数，并检查同一路线支持的图内路径。
