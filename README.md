# 《数据挖掘》探索性实验：景区游览指南的程序性知识挖掘

黄山 / 九寨沟 / 颐和园三景区多源文本的程序性知识挖掘：采集清洗 → 实体识别 → 路线解析 →
共指消解 → 条件建议抽取 → 知识图谱 → 旅游规划 Agent。

## 目录结构

| 目录 | 内容 |
|---|---|
| `task1/`–`task7/` | 实验1–7 源码（`src/`）、产物（`output/`）、报告（`report.docx`）；task1 含采集脚本与数据 |
| `common/` | 评测守护：指标快照、人工标注评测集回归守护、报告-数据一致性审计 |
| `tests/` | 链路重建入口 `run.py` + 65 个单元测试 |
| `docs/` | 过程账本（PROGRESS / METRICS / DECISIONS / BACKLOG / review） |
| `metrics/` | 指标快照（`snapshot_latest.json` 为最新） |

## 复现

```bash
pip install -r requirements.txt
python tests/run.py                              # 全链路重建 + 单元测试
python common/regression_check.py                # 守护指标零退化
python common/report_audit.py                    # 报告-数据一致性（应 70/70）
```

实验1–6 为纯静态管线（jieba+词典+正则+规则，无 key 可复现）；实验7 Agent 在配置
`task7/config.json`（OpenAI 兼容接口）时启用 LLM，未配置自动回退规则规划器。
最终指标见 `docs/METRICS.md` 终表。
