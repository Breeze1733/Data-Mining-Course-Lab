# 实验1 景区指南数据采集与预处理

项目复现统一在仓库根目录运行`python run.py`，使用已经入库的主语料。

- `data/processed/dataset_clean.jsonl`：271条清洗后正文，是后续实验的统一输入。
- `data/raw/official_routes.jsonl`：46条官方路线分支，供实验3解析。
- `data/processed/quality_report.json`、`cleaning_examples.json`、`rejected_records.jsonl`：清洗质量、前后样例及拒绝原因。
- `data/collected/scenic_guide_dataset.xlsx`：数据集交付工作簿。
- `src/build_records.py`、`preprocess.py`：原始材料组装与清洗。
- `src/build_report1.py`：报告生成。

## 目录结构

- `src/`：全部代码——官方/携程/小红书采集（`crawl_*.py`、`crawl_*.mjs`、`collect.py`）、组装与清洗（`assemble.py`、`build_records.py`、`preprocess.py`）、筛选汇总（`select_collection.py`、`import_browser_notes.py`）、导出与报告（`export_*`、`build_report1.py`）及`test_*.py`测试。
- `docs/`：来源考证与搜索边界审计笔记（`official_sources.md`等4篇）。
- `data/raw/`：原始网页快照与采集中间产物（HTML不入库，可由脚本再生）。
- `data/crawl/`：爬虫工作区——断点状态、候选池、抓取日志，全部可再生成，不入库。
- `data/collected/`、`data/processed/`：筛选汇总产物与清洗后语料，交付物入库。
- `sources.json`：采集来源清单（流水线输入配置）。
- `run_collection.ps1`：三平台联网采集总入口（日常复现不需要运行）。
- `package.json`、`node_modules/`：仅浏览器采集（Playwright/Node）使用。
- `logs/`：采集运行日志。

Python依赖为仓库根目录的共享环境（根目录`requirements.txt`），本目录不再单独放置。

采集工具和来源说明见`docs/`。重新联网采集依赖平台访问和登录状态，不保证与已保存批次完全一致；日常实验复现不需要重新采集。
