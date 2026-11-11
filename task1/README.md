# 实验1 景区指南数据采集与预处理

在仓库根目录运行 `python tests/run.py`，从入库的 271 条主语料和 46 条官方路线分支复现实验 2–7。

- `data/processed/` 保存主语料 `dataset_clean.jsonl`、清洗审计 `quality_report.json` 和拒绝记录 `rejected_records.jsonl`。
- `data/raw/` 保存官方来源文档和实验 3 读取的 `official_routes.jsonl`。
- `data/collected/` 保存采集汇总、候选审计和交付工作簿 `scenic_guide_dataset.xlsx`。实验 1 报告的清洗样例取自工作簿。

保留本地 `data/raw/records.jsonl` 和原始快照时，可在 `task1/` 用仓库共享的 Python 环境运行 `python src/preprocess.py`。默认输出到 `data/rebuild/`，清洗后按原始快照字节补齐缺失的 `snapshot_sha256`。核对重建文件与 `data/processed/` 的 SHA-256 即可验证提交版。只有原始记录而缺少快照时，仍可清洗正文，缺失的快照哈希无法补齐。

`src/build_records.py` 从本地采集资料组装原始记录。新一轮采集使用 `run_collection.ps1` 和 `scripts/`，需要平台访问，浏览器采集依赖见 `package.json`。原始记录、HTML 快照和爬虫工作目录仅保存在本地。
