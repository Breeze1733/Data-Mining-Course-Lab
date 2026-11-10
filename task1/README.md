# 实验1 景区指南数据采集与预处理

项目复现统一在仓库根目录运行`python tests/run.py`，使用已经入库的主语料。

- `data/processed/dataset_clean.jsonl`：271条清洗后正文，是后续实验的统一输入。
- `data/raw/official_routes.jsonl`：46条官方路线分支，供实验3解析。
- `data/processed/quality_report.json`、`rejected_records.jsonl`：清洗质量审计与拒绝记录（`cleaning_examples.json` 为可重建示例，不入库）。
- `data/collected/scenic_guide_dataset.xlsx`：数据集交付工作簿。
- `src/build_records.py`、`preprocess.py`：原始材料组装与清洗。
- 报告再生成脚本在 `../local/`（不随仓库分发）。

## 目录结构

- `src/`：清洗与分析（`build_records.py`、`preprocess.py`、`build_official_expansion.py`）。
- `scripts/`：采集爬虫与配套（`crawl_official.py`、`crawl_ctrip_ranked.py`、`crawl_xiaohongshu.mjs`、`expand_ctrip.py`、`select_collection.py`、`stage_status.py`、`import_browser_notes.py`）。
- `data/`：只入库下游实验的输入与交付审计文件——`processed/dataset_clean.jsonl`（实验2-7统一输入）、`raw/official_routes.jsonl`（实验3输入）、`processed/quality_report.json`、`rejected_records.jsonl` 等清洗审计文件，以及`collected/`的汇总、候选审计与`scenic_guide_dataset.xlsx`交付簿。HTML快照、爬虫工作区`crawl/`与中间产物不入库。
- `run_collection.ps1`：三平台联网采集总入口（日常复现不需要运行）。
- `package.json`、`package-lock.json`：浏览器采集（Playwright/Node）的依赖清单，入库；`node_modules/` 由 `npm install` 生成，不入库。

Python依赖为仓库根目录的共享环境（根目录`requirements.txt`），本目录不再单独放置。

采集工具和来源说明见`docs/`。重新联网采集依赖平台访问和登录状态，不保证与已保存批次完全一致；日常实验复现不需要重新采集。
