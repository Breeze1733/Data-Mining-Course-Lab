# 实验 4 程序性知识的共指消解

在 245 篇游记中检测出 1,877 处代词，输出来源、字符偏移、候选与消解结果。规则结合 POI、距离、语义类别和句子景区归属。冻结人工标注共 180 例，按文档划分开发 120 例和留出 60 例。综合判定准确率 63.3%（kind+identity 混合口径），开发 65.8%，留出 58.3%；其中 POI/景区先行词身份准确率 52.1%，集合成员命中率 2.1%。

`output/pronoun_cases.jsonl` 保存逐例结果，`resources/eval/annotation_gold.json` 保存人工先行词与判定备注，`evaluation.json` 保存指标和误差案例。`output/attribution/` 保存句级景区归属结果，供消解阶段过滤景区外候选。人工标注已按 task1 去重后的 canonical 记录对齐：8 条近重复副本的共指标注和 16 条句子归属标注按相同句子文本与相对偏移映射到 canonical 记录，标注总数不变。

在仓库根目录依次运行：

```text
python task4/src/attribute_sentences.py --output task4/output/attribution/attributed_sentences.jsonl
python task4/src/detect_and_resolve.py
python task4/src/annotate_sample.py --score
python task4/src/build_resolved_examples.py
```
