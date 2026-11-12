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
输出：`output/exp2/` 中的实体 JSONL、词频统计、图表与评测结果；最终实体供实验 3 至 7 使用。

- `src/export_dictionary.py`：构建领域词典并导出 `entity_dictionary.json` 和 Jieba 自定义词典 `entity_userdict.txt`。
- `src/extract_entities.py`：实体识别器，基于领域词典最长匹配与时间规则抽取景点 POI、景区交通方式与时间节点，记录字符位置与规范名。
- `src/entity_rules.py`、`dictionary.py`、`time_rules.py`：词典正向最长匹配、前后缀否定过滤、时间正则与区间消解。
- `src/visualize.py`、`spot_check.py`、`entity_sentence_eval.py`、`compare_iterations.py`：绘图、抽样核对、句级评测与迭代对比。

baseline 与 refined 均聚焦于核心景区内实体识别（排除外部联游点与城际交通）。两组统计和图表位于 `figs/baseline/` 和 `figs/refined/`。下游统一读取入库的 `entities_refined.jsonl`。

统计口径：task1 已在清洗阶段物理去重，输入为 267 条唯一记录。分景区核心榜见 `top_canonical_in_scenic` 与 `top_canonical_by_scenic`。时间实体 `canonical` 去除内部空白，`text` 保持原文切片，`start/end` 严格对应字符索引。地点别名通过 `common/entity_identity.py` 统一归一化。
