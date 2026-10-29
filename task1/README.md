# 实验1 景区指南数据采集与预处理

项目复现统一在仓库根目录运行`python run.py`，使用已经入库的主语料。

- `data/processed/dataset_clean.jsonl`：271条清洗后正文，是后续实验的统一输入。
- `data/raw/official_routes.jsonl`：46条官方路线分支，供实验3解析。
- `data/processed/quality_report.json`、`cleaning_examples.json`、`rejected_records.jsonl`：清洗质量、前后样例及拒绝原因。
- `data/collected/scenic_guide_dataset.xlsx`：数据集交付工作簿。
- `src/build_records.py`、`preprocess.py`：原始材料组装与清洗。
- `src/build_report1.py`：报告生成。

采集工具和来源说明见`READ.md`及`research`。重新联网采集依赖平台访问和登录状态，不保证与已保存批次完全一致；日常实验复现不需要重新采集。
