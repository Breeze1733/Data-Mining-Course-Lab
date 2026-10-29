# 实验项目1：景区指南数据采集与预处理

采集黄山、九寨沟、颐和园三个景区的官方路线与游客游记（22 官方文档 / 149 篇携程游记 / 132 条小红书笔记），并完成清洗、去重、结构化与质量检查。采集方法、来源清单与可复现边界详见 [READ.md](READ.md)。

## 目录结构

```
src/                  采集与清洗脚本
data/raw/             原始快照（HTML/JSONL）与组装后的 records.jsonl
data/processed/       清洗管线的机器可读产物（CSV/JSONL/质量报告）
data/collected/       人类可读的 Excel 交付版
report.docx           实验项目1报告
```

`data/` 默认整体忽略，只放行交付物与实验 2–7 的公共输入（见 `.gitignore` 末尾的 `!` 规则）。HTML 快照、`records.jsonl`、切分文本、CSV 副本均可由 `src/` 下的脚本再生，不入库。

## 运行方法

环境准备（Windows，PowerShell 7+，Python 3.10+，Node 20+ 仅采集阶段需要）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

清洗与结构化（离线，不发网络请求）：

```powershell
.\.venv\Scripts\python.exe -X utf8 src\build_records.py        # 三类原始数据 → data/raw/records.jsonl（303 条）
.\.venv\Scripts\python.exe -X utf8 src\preprocess.py --input data/raw/records.jsonl --output-dir data/processed --require-target
.\.venv\Scripts\python.exe -X utf8 src\export_dataset_xlsx.py  # → data/collected/scenic_guide_dataset.xlsx
.\.venv\Scripts\python.exe -X utf8 src\build_report1.py        # 重新生成 report.docx（数字实时读质量报告）
```

重新在线采集（需要网络与小红书登录）见 READ.md。单元测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s src -p test_preprocess.py -v
```

## 输入 → 输出

| 输入 | 输出 |
|---|---|
| `data/raw/official_documents.jsonl`、`research/ctrip_ranked_candidates.json`、`data/raw/xiaohongshu_browser_export.json` | `data/raw/records.jsonl`（303 条统一记录） |
| `data/raw/records.jsonl` | `data/processed/dataset_clean.{jsonl,csv}`（271 条）、`quality_report.json`、`cleaning_examples.json`、`rejected_records.jsonl`（32 条） |
| `data/processed/*` | `data/collected/scenic_guide_dataset.xlsx`（5 工作表）、`report.docx` |

## 下游引用

实验 2–7 的公共输入：`data/processed/dataset_clean.jsonl`（清洗后文本）、`data/raw/official_routes.jsonl`（官方路线分支，实验3用）。
