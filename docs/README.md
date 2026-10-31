
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

## 产物命名约定

产物文件名只描述内容与角色，**不带轮次/版本号**：历史文件 review_r2.json（r2 即"第二轮"）已更名为
`review_fresh.json`（30 例新鲜抽检的人工判定）。仓库中成对出现的名字是不同的实验对象，不是同一产物
的多个版本：

- `entities_baseline/refined.jsonl`、`entity_stats_baseline/refined.json` 及对应词云图——任务书实验2
  明确要求"根据可视化调整停用词、重新识别并优化"的两轮迭代，baseline 与 refined 是对比实验的两个实验组；
- `annotation_sample.json` / `annotation_sample_expand.json`——消解评测的开发集抽样与留出集抽样
  （DECISIONS D4），内容不同、各有唯一职责；
- `metrics/snapshots/snapshot_YYYYMMDD_HHMM.json`——指标账本每时点一条的记录，文件名是时间戳
  （`snapshot_latest.json` 为滚动指针），由 `metrics_snapshot.py` 动态生成。
