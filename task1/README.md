# 实验1 景区指南数据采集与预处理

入库的 271 条主语料和 46 条官方路线分支供后续实验使用。

- `data/processed/` 保存主语料 `dataset_clean.jsonl`、清洗审计 `quality_report.json` 和拒绝记录 `rejected_records.jsonl`。
- `data/raw/dataset_raw.jsonl` 是采集并汇总后的原始语料，作为数据清洗的输入。
- `data/raw/official_routes.jsonl` 保存官方路线分支，供实验 3 直接读取。
- `data/collected/` 保存采集汇总、候选审计和交付工作簿 `scenic_guide_dataset.xlsx`。实验 1 报告的清洗样例取自工作簿。

在 `task1/` 用仓库共享的 Python 环境运行 `python src/preprocess.py`，可从原始语料清洗数据，默认输出到 `data/rebuild/`，不依赖原始网页快照。

交付目录 `data/processed/` 已包含近重复分组字段。需要重新标注时运行 `python src/label_near_duplicates.py`（幂等），再用 `python src/export_dataset_xlsx.py` 生成交付工作簿。不要用 `preprocess.py` 覆盖 `data/processed/`：其中 249 条 `snapshot_sha256` 是事后回填的，当前清洗输入无法复现。

采集代码保留在 `scripts/`、`src/build_official_expansion.py`、`src/build_records.py` 和 `run_collection.ps1`。现有数据处理及后续实验使用已提供的采集结果，无需重新采集。原始网页、浏览器配置、日志和采集中间文件不随项目提交。
