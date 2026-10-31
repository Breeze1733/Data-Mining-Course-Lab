
## 术语约定

- **人工标注评测集**（gold standard set）：由作者逐例判定的标准答案集，用于对规则系统做无偏评估——
  实验4 的 `annotation_gold.json`（180 例 = 开发 120 + 留出 60）、实验2/4/5 的抽检与复核样本同属此类。
  账本早期行文中的"黄金集"自第 4 轮起统一为本表述；英文标识符保留 `gold`（`annotation_gold.json` 等）。
- **开发集 / 留出集**（dev / holdout）：第 1 轮 120 例允许规则迭代查看错误；第 2 轮 60 例只做终评对照（DECISIONS D4）。

## LLM 接入范围（全仓盘点，2026-10-31）

- **当前代码树中调用 LLM API 的只有实验7（task7）**，共三处：
  `task7/src/agent_cli.py`（LLMClient，OpenAI 兼容接口，读 task7/config.json，未配置自动回退规则规划器）、
  `task7/src/run_tests.py`（场景测试入口；`--rules` 用 config.nokey.json 强制规则模式）、
  `task7/src/llm_intent_eval.py`（意图解析对比实验，手动运行）。
- **实验1–6 无任何 LLM 调用**：管线（tests/run.py 链）与评估全部为 jieba+词典+正则+规则的静态实现，
  无 key 可克隆复现。`tests/run.py` 中的场景测试固定 `--rules`，规范产物（test_report.json、traces/）
  不依赖外部服务；LLM 模式的运行证据由手动运行产生，不入规范产物。
- **历史说明**：第2/3轮曾在实验4 做过 LLM 对比实验（受限消解、扩展空间消解、方案C 归属 few-shot），
  其脚本与逐例产物已随 commit cca7e5b 移除（实验1–6 统一纯静态口径）；实验结论保留在 PROGRESS 第2/3轮
  与 DECISIONS D3。该轮产物（llm_resolution_eval_v2.json、llm_eval_v2_run.log）及 task7 旧 8 场景时代的
  test_report_llm.json、traces_llm/、review_r2_draft.json 已于 2026-10-31 清理，仓库只保留与当前代码对应的产物。
- task1 的 `build_official_expansion.py` 与 `tests/task1/test_collection.py` 命中 "urlopen" 为网页抓取
  （采集爬虫），不是 LLM API。

## 产物命名约定（学术界通行的 dev/test/gold 口径）

人工核验的参考答案类文件用 **gold**，用于迭代调试的样本用 **dev（development set）**，只做最终评估、
迭代不接触的样本用 **test（held-out test set）**——即机器学习评测数据的标准三分命名。文件名同样
不带轮次/版本号（历史行文中的 review_r2.json、annotation_sample_expand.json 均已按此更名）：

- 实验4 消解：`annotation_sample_dev.json`（120 例抽样清单）/ `annotation_sample_test.json`（60 例）/
  `annotation_gold.json`（180 例判定全集，行内 `split` 字段区分 dev/test）；
- 实验5 条件建议：`review_dev.json`（49 例复核，回归守护夹具）/ `review_test.json`（30 例独立抽检判定）；
- 实验2 的 `entities_baseline/refined.jsonl` 等为任务书要求的"停用词迭代优化"两轮对比的**两个实验组**
  （baseline 即参照系统，学术标准用语），非同一产物的多版本；
- `metrics/snapshots/snapshot_YYYYMMDD_HHMM.json` 为指标账本的时点记录（时间戳命名，
  `snapshot_latest.json` 为滚动指针），由 `metrics_snapshot.py` 动态生成。
