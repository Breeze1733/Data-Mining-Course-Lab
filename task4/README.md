# 实验 4 程序性知识的共指消解

在 249 篇游记中检测出 1,940 处代词，输出来源、字符偏移、候选与消解结果。规则结合 POI、距离、语义类别和句子景区归属。冻结人工标注共 180 例，按文档划分开发 120 例和留出 60 例。总体准确率 67.8%，开发 71.7%，留出 60.0%。

`output/pronoun_cases.jsonl` 保存逐例结果，`annotation_gold.json` 保存人工先行词与判定备注，`evaluation.json` 保存指标和误差案例。`output/attribution/` 保存句子归属结果、标注和评估。

在仓库根目录运行 `python tests/run.py`。本实验依次完成句子归属、检测与消解、冻结标注计分和文本改写示例生成。计分入口为 `src/annotate_sample.py --score`。
