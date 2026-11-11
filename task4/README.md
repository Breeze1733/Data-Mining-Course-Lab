# 实验 4 程序性知识的共指消解

在 249 篇游记中检测出 1,940 处代词，输出来源、字符偏移、候选与消解结果。规则结合 POI、距离、语义类别和句子景区归属。冻结人工标注共 180 例，按文档划分开发 120 例和留出 60 例。总体准确率 67.8%，开发 71.7%，留出 60.0%。

`output/pronoun_cases.jsonl` 保存逐例结果，`annotation_gold.json` 保存人工先行词与判定备注，`evaluation.json` 保存指标和误差案例。`output/attribution/` 保存句子归属结果、标注和评估。

在仓库根目录依次运行：

```text
python task4/src/attribute_sentences.py --output task4/output/attribution/attributed_sentences.jsonl
python task4/src/detect_and_resolve.py
python task4/src/annotate_sample.py --score
python task4/src/build_resolved_examples.py
```
