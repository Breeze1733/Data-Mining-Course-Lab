# 实验项目4：程序性知识的共指消解
从 249 篇游记中检测 1,940 处代词（它/这里/那里/他们/其中等 12 类），实现规则消解（POI 优先 + 距离约束 + 语义类别分流 + 焦点×归属一致性过滤），180 例人工标注评测（开发 120 + 测试 60，按文档分组）。
## 目录结构
```
src/
  detect_and_resolve.py   代词检测 + 规则消解（v2：人称角色词表、jieba 名词先行词）
  annotate_sample.py      分层抽样（seed=42）、人工判定写入、评估与图
output/
  pronoun_cases.jsonl     全部 1940 处代词（位置/所在句/候选池/消解结果）
  annotation_sample_dev/test.json  开发 120 例 / 测试 60 例抽样清单
  annotation_gold.json    人工标注（先行词、类别、备注）
  evaluation.json         准确率（总体/分类别）与 69 个错误案例
  resolved_examples.json  消解后文本改写示例
  figs/coref_evaluation.png
report.docx             实验项目4报告
```
## 运行方法（在 task1 虚拟环境内）
```powershell
cd task1
..\.venv\Scripts\python.exe -X utf8 ..\task4\src\detect_and_resolve.py     # 检测 + 消解
..\.venv\Scripts\python.exe -X utf8 ..\task4\src\annotate_sample.py --sample  # 生成抽样
..\.venv\Scripts\python.exe -X utf8 ..\task4\src\annotate_sample.py --fill    # 写入人工判定
..\.venv\Scripts\python.exe -X utf8 ..\task4\src\annotate_sample.py --score   # 评估
```
## 关键结论
- 规则消解总体准确率 42.5%（v1 27.5% → v2 42.5%）：处所 40% / 物体 36.7% / 人称 36.7% / 集合 56.7%。
- 两类结构性难题：多景点游记的“景区外指代”（主景区标签 ≠ 句子叙述焦点）；“其中”类部分格结构的普通名词先行词。
- 人工标注含多景点漂移、后置命名、同句劫持、人称语境依赖等典型案例，可作为实验7 LLM 消解的对照测试集。