# docs — 过程账本

本目录是项目的过程记录（PROGRESS / METRICS / DECISIONS / README），
供开发者查阅；代码与八份实验报告不引用本目录。

## 仓库结构

- `task1/`–`task7/`：实验1–7 的源码（`src/`）、产物（`output/`）与报告（`report.docx`）；
  task1 另含采集脚本（`scripts/`）与白名单跟踪的数据（`data/`）。
- `common/`：评测与守护工具（跨任务数据契约与防篡改指纹校验、报告-数据一致性审计）。
- `tests/`：链路重建入口 `run.py` 与单元测试（单文件 `test_all.py`）。
- `docs/`：本账本；`metrics/`：指标账本与最新快照。
- 根目录：八份报告中的《实验总结反思》与任务书原文；`requirements.txt` 为全项目依赖。

## 技术路线：实验1–6 静态、LLM 仅实验7

实验1–6 的管线与评估全部为 jieba + 词典 + 正则 + 规则的确定性实现，无外部服务依赖，
克隆后按各实验 README 的冒烟链即可离线复现（"可复现性"为任务书评分维度之一，
技术路线允许等价替换）。调用 LLM API 的交付代码只有实验7 两处：
`task7/src/agent_cli.py`（LLMClient，OpenAI 兼容接口，读 task7/config.json，未配置自动回退规则规划器）、
`task7/src/run_tests.py`（场景测试入口）。意图解析对比实验（`llm_intent_eval.py`）、
模块消融与权重敏感性（`evaluations.py`）、同义改写扰动（`intent_robustness.py`）等一次性
分析脚本移至 `local/tools/`（不随仓库分发，结果已入库为对应 metrics/output json）。
task1 的 `build_official_expansion.py` 命中 "urlopen" 为网页抓取（采集爬虫），不是 LLM API。

任务7 验收双模式（`tests/run.py --task7 rules|llm|both`，默认 rules）：
`rules` 为静态复现口径（显式 `--rules`，不因本机 config.json 意外联网）；
`llm` 为在线动态验收（LLM 出行程与回答，产物单独写入 `*_llm.json` 与 `traces_llm/`，
不覆盖离线验收证据）；`both` 先离线再在线。在线运行的真实模式与结果记录在
`test_report_llm.json` 的 mode 字段。

## 术语与命名约定

- **人工标注评测集**（gold standard）：由作者逐例判定的标准答案集，用于对规则系统做无偏评估——
  实验4 的 `annotation_gold.json`、实验5 的复核样本、各抽检样本同属此类。
  英文标识符保留 `gold`（`annotation_gold.json` 等）。
- **dev / test**：用于迭代调试的样本为 dev（development set），只做最终评估、迭代不接触的样本为
  test（held-out test set）——机器学习评测数据的标准划分。文件名同此口径且不带轮次/版本号：
  实验4 为 `annotation_sample_dev/test.json` + `annotation_gold.json`（行内 `split` 字段），
  实验5 为 `review_dev.json` / `review_test.json`。
- 实验2 的 `entities_baseline/refined.jsonl` 等为任务书要求的"停用词迭代优化"两轮对比的**两个实验组**
  （baseline 即参照系统），非同一产物的多版本。
- `metrics/snapshots/snapshot_YYYYMMDD_HHMM.json` 为指标账本的时点记录（时间戳命名，
  `snapshot_latest.json` 为滚动指针），由 `metrics_snapshot.py` 动态生成。
