# 实验 5 条件性游览建议的抽取

从 267 条官方路线和游客游记中抽取 **963 对**条件建议，去重后保留 **949 行**。其中 **551/963（57.2%）** 的条件是可回切原文的连续片段（显式 447、句内推断 104），其余 **412 对（42.8%）** 在句中找不到可核验条件，`condition_text` 留空并标记 `condition_kind=absent`，不再用类别标签冒充条件。按映射表行计，542/949（57.1%）行带原文条件片段。

> 审计记录中的 1,025 对 / 966 行 / 79 条复核基于旧的数据快照；当前 task1 数据集为 267 条记录，重跑后以上述数字为准。

当前开发复核为 **75 条**分层样本：正确 27、边界 23、错误 25；严格正确率 **36.0%**（95% CI 26.1%–47.3%），边界率 30.7%，宽松（正确+边界）66.7%。复核样本由当前抽取结果确定性抽样，75 条逐条对齐当前映射表（`missing=0`、`content_drift=0`），可完全复算。

## 字段口径

- `condition_text`：**只存原句连续片段或空串**。空串表示句中无可核验条件，不是“没有建议”。
- `condition_span`：`[a,b]`，满足 `sentence[a:b] == condition_text`；空条件时为 null。
- `condition_kind`：`explicit`（显式条件/规定引入）/ `inferred`（句内人群、天气、时间、装备词）/ `absent`（无可核验条件）。
- `condition_label`：旧口径标签（如 `一般建议`、`时间条件（句内）`、`游客为老人`），**只作来源展示，不是条件**。
- `condition_type`：旧的条件主题桶，保留给下游兼容；`condition_type_verified` 才是按 `condition_text` 重算的核验类型（缺失时为 `无`）。`extraction_stats.json` 的 `condition_type_mismatch` 记录两者不一致的对数（当前 110/551），用于暴露旧分桶偏差。
- `condition_absent_reason`：`no_keyword` / `keyword_only_in_advice` / `regulation_not_conditional` / `label_unmapped`。
- `pair_id`：由记录、原句、条件/建议文本和 span 生成的内容哈希；`mapping_table.json` 另有 `pair_ids`（合并成员，前 10 个）。

`output/conditional_pairs.jsonl` 保存逐对候选、完整原句和来源，`mapping_table.json` 与 `conditional_mapping_table.xlsx` 为交付映射表。xlsx 列包含：条件类型（核验）、条件描述（原文）、条件来源、条件标签（旧口径）、建议内容、触发词、抽取模式、景区、频次、条件位置、来源记录。`extraction_stats.json`、`review_summary.json`、`extraction_coverage_eval.json` 和 `figs/` 提供统计、复核和分组图。

`output/review_test.json` 是 2026-11-05 的历史冻结样本，未参与当前汇总，抽取规则已变更，不能代表当前抽取。

## 运行

在仓库根目录依次运行：

```text
python task5/src/extract_conditionals.py
python task5/src/review_and_charts.py --score
python task5/src/review_and_charts.py --charts
python task5/src/review_and_charts.py --xlsx
python task5/src/coverage_eval.py
```

`output/review_dev.json` 是已判读的复核记录，随仓库提交；正常重跑不需要重新抽样。只有抽取规则改变、`--score` 报 `stale review sample` 或抽取指纹不一致时，才重新抽样并判读：

```text
python task5/src/review_and_charts.py --sample --per-cell 6 --seed 20261111 --force
# 判读 output/review_dev.json（AI 辅助，文件内声明口径）
python task5/src/review_and_charts.py --score
```

`review_dev.json` 是唯一需要人工填写的复核记录（判读字段），其余产物都只由脚本生成。`--sample` 遇到已有判读的当前格式样本会拒绝覆盖，需显式 `--force`；旧格式（无 `sample_meta`）可直接重建。

按仓库 `CLAUDE.md`：改代码后必须重跑本任务全部入口；上游变化不会自动刷新 task5 产物。task6 仍按旧口径读取 `mapping_table.json` 的 `condition_text`，本次未改 task6，其图谱产物仍是历史状态，不能作为当前证据；`task5/report.docx` 同样保持历史状态。
