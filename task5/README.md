# 实验 5 条件性游览建议的抽取

从 271 条官方路线和游客游记中抽取 1,025 对条件建议，去重后保留 966 对。开发复核 79 条中正确 39、边界 19、错误 21，另有 30 条独立冻结复核。

`output/conditional_pairs.jsonl` 保存候选、原句和来源，`mapping_table.json` 与 `conditional_mapping_table.xlsx` 为交付映射表。`extraction_stats.json`、`review_summary.json`、`extraction_coverage_eval.json` 和 `figs/` 提供统计、复核和分组图。覆盖率评估使用的辅助判读与人工复核分别说明。

在仓库根目录依次运行：

```text
python task5/src/extract_conditionals.py
python task5/src/review_and_charts.py --score
python task5/src/review_and_charts.py --charts
python task5/src/review_and_charts.py --xlsx
python task5/src/coverage_eval.py
```
