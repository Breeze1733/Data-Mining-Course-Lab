# 实验2 游览步骤的实体识别

统一复现入口为仓库根目录的`python run.py`。

输入：`task1/data/processed/dataset_clean.jsonl`。
输出：`output/exp2/`中的实体JSONL、类型定义、词频统计、图表与抽检结果；最终实体供实验3至7使用。

- `src/extract_entities.py`：唯一识别器，使用jieba、领域词典和规则，记录Unicode字符位置。
- `src/entity_rules.py`、`dictionary.py`、`time_rules.py`：词典匹配、交通语境、时间归一化和区间消解。
- `resources/`：领域词表、POI及交通规则、时间规则、实体定义和地点别名。
- `src/build_dictionary.py`、`visualize.py`、`spot_check.py`、`iter_compare.py`：词典、图表、抽检和迭代统计。
- `src/build_report2.py`：从当前结果生成实验报告。

baseline与refined是同一程序的两次词典迭代，保留其结果以满足任务书的优化前后对比要求。下游统一读取`entities_refined.jsonl`，不需要选择代码版本或切换数据口径。

地点别名通过`common/entity_identity.py`统一处理。实体写出前检查字符位置和区间重叠；历史抽检仅在文档、类型、原文及位置一致时继承判定。
