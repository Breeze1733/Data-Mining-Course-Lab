# 实验项目5：条件性游览建议的抽取

从实验1清洗后的 271 条文本中抽取「条件 → 建议」对，构建可查询的映射表：原始 1,290 对，去重后 1,210 对，人工校验 49 条（正确 20 / 边界 16 / 错误 13）。

## 目录结构

```
src/
  extract_conditionals.py   触发词与 4 类句式规则抽取、条件类型映射、去重
  review_and_charts.py      人工校验抽样与分组统计图
  export_mapping_xlsx.py    映射表 Excel 导出
  build_report5.py          生成 report.docx
output/
  conditional_pairs.jsonl       条件-建议对（1,210 条，保留原句与来源）
  mapping_table.json            映射表（条件类型 / 条件描述 / 建议内容 / 景区 / 来源）
  conditional_mapping_table.xlsx  映射表交付版
  extraction_stats.json         抽取统计
  review_sample.json / review_gold.json / review_summary.json  人工校验样本、标注与汇总
  figs/cond_type_by_scenic.png、figs/crowd_breakdown.png
report.docx                  实验项目5报告
```

## 运行方法（在 task1 虚拟环境内）

```powershell
cd task1
..\.venv\Scripts\python.exe -X utf8 ..\task5\src\extract_conditionals.py
..\.venv\Scripts\python.exe -X utf8 ..\task5\src\review_and_charts.py
..\.venv\Scripts\python.exe -X utf8 ..\task5\src\export_mapping_xlsx.py
..\.venv\Scripts\python.exe -X utf8 ..\task5\src\build_report5.py
```

## 关键结论

- 句式：P1 显式条件 603、P4 建议推断 582、P6 否定建议 101、P5 人群可以 4，共 1,290 对；同句重复与前后缀近重复合并 80 对。
- 分布：九寨沟 648 / 黄山 393 / 颐和园 249；游记 1,266 对，官方路线仅 24 对——条件性建议基本来自游客经验而非官方指南。
- 人群细分：孩子 13、情侣 8、体力有限 7、恐高 6、老人 3、家庭 3、晕车 2、行动不便 1，其余未细分，是映射表最主要的稀疏来源。
- 校验：49 条抽样中边界切分 16 条（33%），错误 13 条（27%），主要错在跨分句建议被截断与否定句极性反转。
