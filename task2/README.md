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

## 延伸机制说明（不属于实验2 四项任务）

`task4/src/attribute_sentences.py`、`task4/src/build_attribution.py`、`task4/src/sample_sentences.py` 与
`task4/output/attribution/`（495 句标注集、全量归属、评估数据）是**句级归属**环节：判定每句叙述焦点
属于哪个景区，供实验4（消解候选过滤）与实验5（条件对过滤）共用——实验2 的任务书四项任务
（实体识别/规范表/词频可视化/成果输出）均不包含它，实体识别本身为纯 jieba+词典+规则，全程无 LLM。
权重在标注集上按 seed=42 对半分迭代（tune 调参、holdout 一次终评）。详见 DECISIONS.md D2 与 review/。
