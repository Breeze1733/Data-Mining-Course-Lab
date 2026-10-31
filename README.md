# 数据挖掘探索性实验

景区游览指南的程序性知识挖掘，按实验项目存放于task1至task7。

## 复现

使用仓库根目录的同一个Python环境（`.venv`），安装`requirements.txt`中的依赖后，在仓库根目录运行：

```powershell
python run.py
```

程序读取已入库的`task1/data/processed/dataset_clean.jsonl`，顺序执行实体识别及下游实验，更新图表和实验报告。默认离线运行，不重新联网采集，也不重填人工标注。Agent未配置API时使用规则模式。

实验2的baseline和refined由同一个识别器运行，分别用于迭代对比和最终下游输入；正式结果统一保存在各任务的`output`目录。

| 目录 | 实验 | 报告 |
|---|---|---|
| task1 | 数据采集与预处理 | task1/report.docx |
| task2 | 实体识别 | task2/report.docx |
| task3 | 路线层级结构 | task3/report.docx |
| task4 | 共指消解 | task4/report.docx |
| task5 | 条件建议抽取 | task5/report.docx |
| task6 | 知识图谱融合 | task6/report.docx |
| task7 | 旅游规划Agent | task7/report.docx |

总结反思为根目录的`实验总结反思.docx`。公共名称映射及报告排版工具在`common`，地点别名在`task2/resources/poi_aliases.csv`，由实体、路线和图谱统一读取。
