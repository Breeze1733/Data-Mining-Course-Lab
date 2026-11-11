# 实验2 游览步骤的实体识别

在仓库根目录依次运行以下命令：

```text
python task2/src/export_dictionary.py
python task2/src/extract_entities.py --iteration baseline
python task2/src/extract_entities.py --iteration refined
python task2/src/visualize.py --iteration baseline
python task2/src/visualize.py --iteration refined
python task2/src/spot_check.py --reconcile
python task2/src/entity_sentence_eval.py
python task2/src/compare_iterations.py
```

输入：`task1/data/processed/dataset_clean.jsonl`。
输出：`output/exp2/`中的实体JSONL、词频统计、图表与抽检结果；最终实体供实验3至7使用。

- `src/extract_entities.py`：唯一识别器，使用jieba、领域词典和规则，记录Unicode字符位置。
- `src/entity_rules.py`、`dictionary.py`、`time_rules.py`：词典匹配、交通语境、时间归一化和区间消解。
- `resources/`：领域词表、POI及交通规则、时间规则和地点别名。
- `src/export_dictionary.py`、`visualize.py`、`spot_check.py`、`compare_iterations.py`：导出词典、绘图、核对抽检和比较优化前后结果。
- 报告再生成脚本在 `../local/`（不随仓库分发）。

baseline 与 refined 由同一识别器运行。两组统计和图表随仓库提供，图表位于 `figs/baseline/` 和 `figs/refined/`。运行上述命令可生成 baseline 逐条结果。下游统一读取入库的 `entities_refined.jsonl`。

统计口径：task1 已在清洗阶段物理去重，输入为 267 条唯一记录，被移除的近重复副本见 `task1/data/processed/rejected_records.jsonl`（拒绝原因 `near_duplicate_of:<canonical>`）。`dedup_weight` 因此恒为 1.0，加权统计与原始统计一致：`records_after_dedup` = 267，`duplicate_records` = 0，`records_in_duplicate_groups` = 3（canonical 记录仍保留组号）。分景区核心榜见 `top_canonical_in_scenic` 与 `top_canonical_by_scenic`，只统计 `in_scenic=true`。时间实体 `canonical` 去除内部空白，`text` 仍是原文切片，`start/end` 可直接回溯原文。冻结句级评测样本中若有文档被去重，`entity_sentence_eval.py` 会把同文同跨度的句子映射到 canonical 记录，评测口径不变（`sample_remap` 字段记录映射情况）。

冻结评测资产（人工策划的评测输入，与 `output/` 下可再生产物分开，存放于 `resources/eval/`）：句级实体评测样本 `resources/eval/entity_sentence_sample.json`（40 句，3 景区×（每景区前 5 条开头句＋随机正文句），14/14/12，seed=20261106）与金标 `resources/eval/entity_sentence_gold.json` 一同冻结，金标为开发 agent 逐句判读（AI 辅助判读，非独立人工标注；POI/交通严格跨度含包含式变体，时间重叠口径），判读完成后识别规则不再据其修改。第一轮样本（`entity_sentence_sample_dev.json`、`entity_sentence_gold_dev.json`）曾用于扩充领域词典，属开发历史，为避免污染冻结评测已从仓库删除，仅在此备注。task5 的句级覆盖评测样本 `task5/resources/eval/coverage_sample_expanded.json`（60 句，seed=77，排除既有抽样记录；AI 逐句判读 ai_advice/gist，口径：条件性建议或带触发词的建议计入，攻略式时间安排/路线罗列/无触发词泛建议任务外）。人工抽检判定记录 `resources/eval/spot_checks.json`（冻结人工抽检；`spot_check.py --reconcile` 只做 canonical 映射对齐与历史判定继承）。

地点别名通过`common/entity_identity.py`统一处理。实体写出前检查字符位置和区间重叠；历史抽检仅在文档、类型、原文及位置一致时继承判定。
