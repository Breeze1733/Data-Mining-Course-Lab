# 实验 5 条件性游览建议的抽取

从 267 条主语料抽取"条件→建议"对：候选 1,060 对（含召回修复新增触发词），经非游览建议过滤与建议性结构门剔除 279 对后剩 781 对，去重得到 770 行映射（392 行带显式条件）。按景区隔离去重，同句重复与近重复合并进 `sources` / `pair_ids`；task6 只消费 `mapping_table.json` 与 `extraction_stats.json` 的 `condition_refinement` 字段。

- `src/extract_conditionals.py`：主抽取器。P1–P6 模式层级（显式连词/…的话/当…时/建议推断/人群可以/否定建议）加规定类扩展；输出前做边界修补（`refine`）、逐字条件区间校验（`validate_pairs`）、句级景区归属过滤（复用 task4 的 `Attributor`，不复制其代码）。
- 过滤规则（`filtered` 计数见 `extraction_stats.json`）：非游览主题（住宿设施/外卖配送/餐馆菜单/广告推广/纯吐槽/第一人称愿望/体验叙述）逐对剔除；建议性结构门要求建议部分含建议动词、劝导标记、处方动词或具体装备/票务名词，拦截诗歌、散文、菜单、反问句等叙述误入。
- `src/export_mapping_xlsx.py`：生成交付工作簿 `output/mapping_table.xlsx`（映射表/人群统计/条件类型统计/字段说明）。
- `src/visualize.py`：生成 `output/figs/` 三张图（条件类型×景区、游客类型×景区、模式×极性），任务书要求的游客类型分组对比柱状图为 `crowd_breakdown.png`。
- `src/spot_check.py`：人工抽查工具。`--sample 48` 按模式分层抽样，`--miss-sample 20` 列出含触发词但未产出的句子排查漏抽，`--score` 汇总判定写回 `review_summary`。冻结审计文件在 `resources/eval/conditional_spot_checks.json`：52 条抽样严格正确率 65.4%、含边界 76.9%，边界切分 10、非游览主题 5、误抽 3；漏抽排查 20 句中 3 句真漏抽（含蓄负评、句尾"强烈推荐"、"留意一下"未入触发词表）。

在仓库根目录运行：

```text
python task5/src/extract_conditionals.py
python task5/src/export_mapping_xlsx.py
python task5/src/visualize.py
python task5/src/spot_check.py --score
```

`--no-attribution-filter` 关闭句级归属过滤；`--ltp-model` 可选用 LTP 做语义角色标注（需自行安装 torch 与 ltp，当前默认规则管线不依赖）。

审计判定与边界口径：correct=条件与建议均成立且成对；boundary=存在切分/条件推断瑕疵但核心语义成立；incorrect=误触发或语义不成立。判定为单人判读，样本与逐条备注见 `resources/eval/conditional_spot_checks.json`。
