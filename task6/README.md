# 实验项目6：多源程序性知识融合与图谱可视化

融合实验2（实体）、实验3（路线结构）、实验5（条件建议）为景区游览知识图谱（NetworkX），702 节点 / 2,545 边，含分景区可视化与质量验证。

## 目录结构

```
src/
  build_graph.py       图谱构建（Schema、实体对齐、双源加权、条件边、CSV/GraphML 导出）
  visualize_graph.py   静态 PNG（分景区）+ pyvis 交互 HTML
  verify_graph.py      质量验证（已知事实核验、连通性、同名隔离）
  build_report6.py     生成 report.docx
output/
  graph_nodes.csv / graph_edges.csv / knowledge_graph.graphml
  graph_stats.json / graph_validation.json
  graph_{景区}.html     交互图谱
  figs/graph_*.png
report.docx           实验项目6报告
```

## 运行方法（在 task1 虚拟环境内）

```powershell
cd task1
.\.venv\Scripts\python.exe -X utf8 ..\task6\src\build_graph.py
.\.venv\Scripts\python.exe -X utf8 ..\task6\src\visualize_graph.py
.\.venv\Scripts\python.exe -X utf8 ..\task6\src\verify_graph.py
.\.venv\Scripts\python.exe -X utf8 ..\task6\src\build_report6.py
```

## 关键结论

- Schema：景区/景点POI/时段/交通操作/条件 5 类节点；包含/先后顺序/时段归属/交通方式/条件建议 5 类边。
- 融合：canonical+景区命名空间对齐（五彩池/北海不跨景区合并）；先后边=官方 1.0/条+游客 0.5/条，保留路线 ID 溯源。
- 验证：6/6 已知事实核验通过，各景区子图单连通，无孤立节点；核心节点（光明顶/五彩池/佛香阁）与领域常识一致。

公共别名与图谱引用一致性检查：在根目录运行`python common/verify_entity_identity.py`。本轮7条别名、489处官方路线POI引用全部对齐，无缺身份属性的节点。
