# 实验项目2：游览步骤的实体识别

在实验1清洗后的景区文本上识别三类实体：**景点POI、交通方式、时间节点**，输出带出现位置的 JSON、实体定义规范表、词频统计与可视化，并通过 iter1 → iter2 的迭代展示优化前后变化。

本实现采用 **jieba 自定义词典 + 规则/正则** 的离线方案，不调用 LLM 或外部 API；所有位置基于 `cleaned_text` 的 Unicode 码点偏移，左闭右开，可用 `text[start:end] == surface` 逐条核验。

> 本目录不绑定具体景区、具体篇数或固定来源组合。task1 的当前输出只是样本；输入中的 `scenic_area`、文档数、来源文件是否存在都由运行数据决定。

## 1. 目录

```text
task2/
├─ src/                     # 识别、统计、可视化、QC、测试
├─ resources/
│  ├─ poi_gazetteer.csv     # 按景区隔离的 POI 词典（canonical/aliases/parent_poi/否定语境）
│  ├─ poi_suffix_rules.csv  # 无词典景区的通用后缀兜底规则与防误报词表
│  ├─ transport_lexicon.csv # 交通方式词典 + 票务/站点/广告否定语境
│  ├─ time_rules.json       # 时刻/区间/日期/相对日/季节/节日/时长规则与排除项
│  ├─ entity_definition.csv # 权威实体定义规范表
│  ├─ stopwords_extraction.txt
│  └─ iter1_baseline/       # 首轮基线词典/规则（由 build_baseline.py 生成）
├─ inputs/                  # 输入快照（数据 git 忽略，仅 README 入库）
├─ data/                    # iter1 中间结果、候选、错误日志（git 忽略）
├─ outputs/                 # 最终交付物；git 忽略，由 run_task2.ps1 生成
├─ config.json              # 输入来源、字段映射、资源路径、阈值与 top-N
├─ prepare_inputs.ps1       # 从 task1 复制输入并写 manifest
├─ run_task2.ps1            # 一键复现
└─ requirements.txt
```

## 2. 数据流

```text
task1/data/processed  →  task2/inputs（冻结快照 + manifest）
      → iter1 基线（粗粒度词典/规则）
      → iter2 最终（完整词典/规则）
      → outputs/（实体 JSON、统计、图表、QC、迭代对比、运行清单）
```

## 3. 数据契约

默认快照文件与来源名（可在 `config.json` 中修改）：

| 文件 | 来源名 | 必选 | ID 字段 | 接受字段 | 用途 |
|---|---|---|---|---|---|
| `tourist_routes_clean.jsonl` | `tourist` | 否 | `record_id` | — | 游客游记 |
| `official_routes_clean.jsonl` | `official_route` | 否 | `route_id` | — | 官方线路 |
| `official_documents_clean.jsonl` | `official_document` | 否 | `evidence_id` | `accepted` | 官方文档 |
| `quality_report.json` | — | 否 | — | — | task1 provenance |

- **记录数不是契约**：实际条数从 `inputs/manifest.json` 或运行摘要读取，程序不假设固定数量。
- **景区是开放集合**：`scenic_area` 是唯一位置字段，取值由数据决定；不假设只有几个景区，也没有经纬度字段。
- **字段映射可配置**：默认读取 `scenic_area`、`cleaned_text`、`text_sha256`、`source_url`、`title`/`page_title`、`matched_pois` 等；换字段名时改 `config.json` 的 `input.field_map`。
- **可选来源**：`required=false` 的文件缺失时跳过并告警；只有 `required=true` 才报错。至少要有任意一个有记录的来源。
- **接受字段**：只有配置了 `accept_field` 且该行确实有该字段时才过滤；没有 `accepted` 字段的数据集不会被误杀。
- **manifest**：记录每个来源的 `source_kind`、`id_field`、字节数、SHA-256、记录数与接受数；识别前会校验本次使用文件的哈希。
- **定义表中的正反例**来自当前样本，仅用于说明边界口径，不限制可处理的景区范围。

## 4. 配置

`config.json`（不存在时使用内置默认值）主要键：

| 键 | 作用 |
|---|---|
| `input.dir` / `input.fallback_dirs` | 输入目录及回退目录 |
| `input.sources` | 来源名 → 文件名、ID 字段、平台字段、接受字段、是否必选、显示名 |
| `input.field_map` | 逻辑字段 → 候选列名列表 |
| `resources.*` | 词典、规则、停用词、定义表、兜底规则、iter1 目录 |
| `outputs.*` | 输出目录、iter1 目录、图表/QC 子目录、manifest |
| `scope` | 统计口径：`analysis`、`all` 或逗号分隔的来源名 |
| `top_n` | 各类型 top-N、分景区 top-N、景区面板上限 |
| `sampling` | 人工抽查种子、配额、边界案例上限 |
| `poi_fallback` | 通用后缀兜底开关、模式、置信度、前缀长度、jieba 边界 |
| `area` | 根景区后缀、景区别名、是否要求景区非空 |
| `visualization` | 字体候选、环境变量、DPI、词云参数 |
| `comparison` | 粗粒度子类、票务词、噪声指标规则 |
| `qc` | 抽查配额、边界案例、类型混淆正则 |

优先级：**CLI 参数 > `config.json` > 内置默认值**。各脚本都支持 `--config`。

## 5. 识别方法

- **POI 词典**：按 `area` 严格隔离，最长匹配；词典条目可带 `negative_after` 否定语境。
- **无词典景区兜底**：`resources/poi_suffix_rules.csv` 定义常见景区后缀（峰、湖、寺、门、桥、洞、谷、观景台、停车场、游客中心、索道等）及防误报词表。景区在词典中没有任何条目时，启用低置信候选：
  - `method=generic_suffix`，`confidence` 较低，实体带 `fallback=true`；
  - 具名索道/缆车/观光车/码头归 **交通方式**，其余归 **景点POI**；
  - 根景区名由 `area.root_suffixes` + `area.aliases` 生成，标记 `is_root_area=true`；
  - `extract_summary.json` 写入 `missing_gazetteer_area` 警告。
  - 模式：`missing_area_only`（默认）、`always`、`never`；可用 `--generic-fallback` 覆盖。
- **根景区名**：保留并标记，默认从 POI 图表和 top 榜排除，但计入 JSON。
- **交通方式**：词典最长匹配 + 票务/站点/排队/停运/广告否定语境；具名索道记录 `linked_poi`；裸“换乘”不单独作为方式。
- **时间节点**：正则识别时刻、时刻区间、时段、日期、日期区间、月份区间、相对日、季节、节日、重复；`时长` 保留为 TIME 子类但 `counts_as_time_node=false`，词频与图表单独分列。
- **重叠消解**：按起点升序、长度降序、rank 降序贪心选取互不重叠的实体；被抑制项写入 `data/intermediate/suppressed_<iteration>.jsonl`。
- **jieba**：把词典词注入 jieba 自定义词典，用 search 模式做候选发现与边界校验；最终边界始终由确定性最长匹配/正则给出，jieba 不覆盖偏移。
- **稳定 ID**：`entity_id = ENT- + SHA1(source_record_id|start|end)` 前 12 位，与类型无关；同一 span 在迭代前后保持同一 ID。
- **偏移断言**：每个实体写入前校验 `text[start:end] == surface`，失败即整轮报错。

## 6. 运行

```powershell
cd task2
# 1) 冻结 task1 的预处理输出（首次或 task1 更新后）
.\prepare_inputs.ps1 -Task1Dir ..\task1\data\processed -Config .\config.json

# 2) 安装依赖（复用仓库根 .venv；该 venv 由 uv 创建，可能没有 pip）
uv pip install --python ..\.venv\Scripts\python.exe -r requirements.txt

# 3) 一键运行：iter1 → iter2 → 统计/图表 → 对比 → QC → 定义表 → manifest
.\run_task2.ps1 -PythonExe ..\.venv\Scripts\python.exe -Config .\config.json

# 可选：只跑测试
..\.venv\Scripts\python.exe -m unittest discover -s src -p "test_*.py" -v
```

`run_task2.ps1` 支持 `-SkipPrepare`、`-SkipIter1`、`-NoWordcloud`、`-RunTests`、`-Task1Dir`、`-InputDir`、`-Config`。

也可以单独运行：

```powershell
..\.venv\Scripts\python.exe src\extract_entities.py --config config.json `
    --input-dir inputs --resources resources --iteration iter2 --output-dir outputs
..\.venv\Scripts\python.exe src\stats_entities.py --config config.json `
    --entities outputs\entities.json --output-dir outputs
..\.venv\Scripts\python.exe src\visualize_entities.py --config config.json `
    --entities outputs\entities.json --charts-dir outputs\charts
..\.venv\Scripts\python.exe src\compare_iterations.py --config config.json `
    --iter1 data\iterations\iter1\entities.json --iter2 outputs\entities.json `
    --output-dir outputs --charts-dir outputs\charts
..\.venv\Scripts\python.exe src\qc_entities.py --config config.json `
    --input-dir inputs --entities outputs\entities.json --output-dir outputs\qc
```

子集调试：`--area`（可重复）、`--limit`、`--record-id`、`--sources`、`--generic-fallback off|missing|always`。

## 7. 输出

| 文件 | 内容 |
|---|---|
| `outputs/entities.json` | 顶层元数据 + 全部实体（类型、子类型、surface、normalized、来源、start/end、句/小句位置、context、method、confidence、is_root_area、linked_poi、fallback 等） |
| `outputs/entities.jsonl` | 一行一个实体，便于下游流式读取 |
| `outputs/by_area/*.json` | 按景区拆分；文件名会做非法字符替换 |
| `outputs/extract_summary.json` | 文档数、实体数、按类型/来源/景区计数、warnings、poi_fallback 统计 |
| `outputs/entity_definition.csv/.md` | 实体定义规范表 |
| `outputs/frequency_*.csv` | 词频、分景区/分来源统计；来源列按实际来源动态生成 |
| `outputs/charts/*.png` | 三类 top-N、分景区、类型分布、时长、词云、迭代前后对比 |
| `outputs/charts/area_entity_counts.csv` | 各景区实体数（景区多时用于面板聚合） |
| `outputs/qc/` | `qc_metrics.json`、`qc_report.md`、重复/类型混淆、人工抽查模板与复核表 |
| `outputs/iteration_comparison.*` | iter1 vs iter2 指标与说明 |
| `outputs/run_manifest.json` | 输入/输出 SHA-256、大小、配置哈希、warnings |

所有规模、景区数、图表面板数都由本次运行数据决定；文档不记录固定结果数字。

## 8. 泛化与局限

- **无词典景区**：会启用低置信后缀兜底并告警；兜底候选容易把泛称当专名，建议通过 `fallback=true` 过滤或补充 `poi_gazetteer.csv`。把 `poi_fallback.mode` 设为 `never` 可关闭兜底，但仍保留 `missing_gazetteer_area` 警告。
- **缺 `matched_pois`**：QC 银标准指标自动降级为不可用，不影响主流程。
- **官方文档与官方线路可能重复**：统计默认 `scope=analysis`（游客 + 官方线路），可用 `--scope all` 对照。
- **没有坐标**：task1 数据不含经纬度，位置只能到文本偏移。
- **词典覆盖有限**：未登录 POI 可能漏识别；跨景区同名/同名城市需要词典否定语境或兜底词表处理。
- **人工抽查样本有限**：复核表会按 `entity_id` 与本次输出比对，完全不匹配时标记 `stale_reviewed`，不静默沿用旧标签。
- **时长口径**：`时长` 是 TIME 子类但不算时间节点，词频与图表单独分列。

## 9. 复现校验

- 输入快照 `inputs/manifest.json` 固定 SHA-256；识别前校验，不匹配即报错。
- 实体 ID 稳定，偏移可用 `text[start:end] == surface` 逐条回核。
- `outputs/run_manifest.json` 递归记录本次所有输入/输出文件的哈希。
- 测试覆盖偏移、最长匹配、时间/交通规则、schema、端到端管线、未知景区兜底、可变来源与景区数。
- 回归校验（可选，需事先保留一份旧 `outputs/` 快照）：

  ```powershell
  ..\.venv\Scripts\python.exe src\verify_outputs.py --config config.json `
      --baseline data\regression_baseline_<stamp> --current outputs --inputs inputs
  ```
