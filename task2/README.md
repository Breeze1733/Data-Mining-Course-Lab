# 实验2 游览步骤的实体识别

统一复现入口为仓库根目录的`python tests/run.py`。

输入：`task1/data/processed/dataset_clean.jsonl`。
输出：`output/exp2/`中的实体JSONL、类型定义、词频统计、图表与抽检结果；最终实体供实验3至7使用。

- `src/extract_entities.py`：唯一识别器，使用jieba、领域词典和规则，记录Unicode字符位置。
- `src/entity_rules.py`、`dictionary.py`、`time_rules.py`：词典匹配、交通语境、时间归一化和区间消解。
- `resources/`：领域词表、POI及交通规则、时间规则、实体定义和地点别名。
- `src/visualize.py`、`spot_check.py`、`ablation_dictionary.py`：图表、抽检和词典迭代对比。
- 报告再生成脚本在 `../local/`（不随仓库分发）。

baseline 与 refined 由同一识别器运行。两组统计和图表随仓库提供，图表位于 `figs/baseline/` 和 `figs/refined/`。运行复现入口可生成 baseline 逐条结果。下游统一读取入库的 `entities_refined.jsonl`。

地点别名通过`common/entity_identity.py`统一处理。实体写出前检查字符位置和区间重叠；历史抽检仅在文档、类型、原文及位置一致时继承判定。
