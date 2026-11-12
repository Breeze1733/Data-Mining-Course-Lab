# 实验 5 条件性游览建议的抽取

从 267 条官方路线和游客游记中抽取 **963 对**条件建议，去重后保留 **949 行**。原始抽取中 **551/963（57.2%）** 的条件是原文连续片段（显式 447、句内推断 104），其余 **412 对（42.8%）** 标记为无显式条件。映射表经条件修正后，524/949 行保留非空条件。

> 审计记录中的 1,025 对 / 966 行 / 79 条复核基于旧的数据快照；当前 task1 数据集为 267 条记录，重跑后以上述数字为准。

原始抽取的开发复核为 **75 条**分层样本：正确 27、边界 23、错误 25；严格正确率 **36.0%**（95% CI 26.1%–47.3%），边界率 30.7%，宽松（正确+边界）66.7%。复核按原始条件片段对齐，不能用作修正后的独立准确率。

## 字段口径

- `condition_text`：**只存原句连续片段或空串**。空串表示句中无可核验条件，不是“没有建议”。
- `condition_span`：`[a,b]`，满足 `sentence[a:b] == condition_text`；空条件时为 null。
- `condition_kind`：`explicit`（显式条件/规定引入）/ `inferred`（句内人群、天气、时间、装备词）/ `absent`（无可核验条件）。
- `condition_label`：旧口径标签（如 `一般建议`、`时间条件（句内）`、`游客为老人`），**只作来源展示，不是条件**。
- `condition_type`：旧的条件主题桶，保留给下游兼容；`condition_type_verified` 是按 `condition_text` 重算的关键词分类（缺失时为 `无`）。`extraction_stats.json` 的 `condition_type_mismatch` 记录两者不一致的对数（当前 108/551）。
- `condition_absent_reason`：`no_keyword` / `keyword_only_in_advice` / `regulation_not_conditional` / `label_unmapped`。
- `pair_id`：由记录、原句、条件/建议文本和 span 生成的内容哈希；`mapping_table.json` 的 `pair_ids` 和 `sources` 保存全部去重成员和来源。

`output/conditional_pairs.jsonl` 保存逐对候选、完整原句和来源，`mapping_table.json` 与 `conditional_mapping_table.xlsx` 为交付映射表。LTP 的分词与语义角色结果保存在对应行的 `semantic_roles`，与该行条件和建议动作相匹配的角色保存在 `semantic_role_links`，Excel 的“LTP 条件与动作”列展示匹配结果。`extraction_stats.json`、`review_summary.json`、`extraction_coverage_eval.json` 和 `figs/` 提供统计、复核和分组图。

LTP 只处理句内推断条件和结构较复杂的显式条件；简单的“如果下雨”由规则处理。当前使用 LTP 4.2.14 / Small 模型，对 170 个句子、190 对原始候选执行语义角色标注，其中 11 条映射存在可与建议动作对应的条件角色。角色匹配不覆盖规则抽取结果，也不视为正确性的证明。

`resources/eval/review_test.json` 是 2026-11-05 起冻结的 30 例独立抽检集（开发 agent 逐例判读，AI 辅助判读，非独立人工标注），仅用于终评对照，判分后规则改动不得参考其错误明细；其内记录的判定结论基于冻结当时的抽取，未参与当前汇总，抽取规则已变更，不能代表当前抽取。

## 运行

在仓库根目录依次运行：

```text
local/ltp_env/Scripts/python task5/src/extract_conditionals.py --ltp-model local/ltp_model
python task5/src/review_and_charts.py --score
python task5/src/review_and_charts.py --charts
python task5/src/review_and_charts.py --xlsx
python task5/src/coverage_eval.py
```

LTP 独立环境使用 Python 3.12。以下命令安装依赖并获取固定版本的 `LTP/small` 模型：

```powershell
py -3.12 -m venv local/ltp_env
local/ltp_env/Scripts/python -m pip install ltp==4.2.14 torch==2.5.1 transformers==4.35.2 huggingface-hub==0.25.2
local/ltp_env/Scripts/huggingface-cli download LTP/small --revision dea87bf0da3c5d054bbd426a78d7fa9efd347799 --local-dir local/ltp_model
```

环境和模型放在不提交的 `local/` 目录；省略 `--ltp-model` 时只运行规则，不生成 LTP 角色结果。

`resources/eval/review_dev.json` 是已判读的复核记录，随仓库提交；正常重跑不需要重新抽样。只有抽取规则改变或 `--score` 报 `stale review sample` 时，才重新抽样并判读：

```text
python task5/src/review_and_charts.py --sample --per-cell 6 --seed 20261111 --force
# 判读 resources/eval/review_dev.json（AI 辅助，文件内声明口径）
python task5/src/review_and_charts.py --score
```

`review_dev.json` 保存原始抽取的开发复核判读记录。`--sample` 遇到已有判读的当前格式样本会拒绝覆盖，需显式 `--force`；旧格式（无 `sample_meta`）可直接重建。

抽取脚本按原句中的否定词、词语和片段位置修正条件，并在同一映射表中保留修正前文本与位置。当前 949 行中 29 行被修正，非空条件由 542 行变为 524 行，统计保存在 `extraction_stats.json`。实验 6 直接读取映射表。

本地报告生成脚本位于 `local/build_report5.py` 和 `local/build_report6.py`。
