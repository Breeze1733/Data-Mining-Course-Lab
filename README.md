# 《数据挖掘》探索性实验代码仓库

围绕黄山、九寨沟、颐和园三个景区的官方指南与游客游记，构建程序性知识挖掘链路：数据采集与预处理 → 实体识别 → 路线结构挖掘 → 共指消解 → 条件建议抽取 → 知识图谱融合 → 旅游规划 Agent

## 环境准备

- Python 3，安装依赖：`pip install -r requirements.txt`
- 实验 1 的在线采集需要 Node.js ≥ 20 与 Playwright
- 实验 7 需将 `task7/config.example.json` 复制为 `task7/config.json`，填入兼容工具调用的模型接口；未配置时 CLI 以规则模式运行

## 各实验代码运行入口

### 实验 1 景区指南数据采集与预处理（task1/）

采集三景区官方路线、携程游记、小红书笔记，解析 HTML、清洗平台噪声、校验字段并去重，输出结构化 JSONL 语料。

```powershell
# 在线采集制作数据集
powershell -ExecutionPolicy Bypass -File task1/run_collection.ps1

# 从已保存的原始语料离线重跑清洗
python src/preprocess.py --input data/raw/dataset_raw.jsonl --output-dir data/rebuild --require-target
```

### 实验 2 游览步骤的实体识别（task2/）

以词典与时间规则识别游览步骤中的景点 POI、交通方式、时间节点三类实体，输出带字符位置、规范名与规则来源的 JSONL（baseline / refined 两轮迭代）。

```bash
python task2/src/export_dictionary.py
python task2/src/extract_entities.py --iteration baseline
python task2/src/extract_entities.py --iteration refined
python task2/src/visualize.py --iteration baseline|refined
python task2/src/spot_check.py --reconcile
python task2/src/entity_sentence_eval.py
python task2/src/compare_iterations.py
```

### 实验 3 游览路线的层级结构挖掘（task3/）

将官方路线解析为统一步骤与"上午/中午/下午/晚上"时段层级；再从游记实体序列提取游客路线，与官方路线做覆盖度、顺序一致性（Kendall tau）、时间分配三维对比。

```bash
python task3/src/parse_routes.py
python task3/src/compare_routes.py
python task3/src/build_hierarchy_view.py
```

### 实验 4 程序性知识的共指消解（task4/）

句级景区归属过滤加候选排序规则，把代词消解到正确先行词；含 180 例人工标注评测（开发 120 + 留出 60），输出逐例消解与评测报告。

```bash
python task4/src/attribute_sentences.py --output task4/output/attribution/attributed_sentences.jsonl
python task4/src/detect_and_resolve.py
python task4/src/annotate_sample.py --score
python task4/src/build_resolved_examples.py
```

### 实验 5 条件性游览建议的抽取（task5/）

以触发模式（显式连词/…的话/当…时/建议推断/人群可以/否定建议）加建议性结构门，从语料抽取"条件 → 建议"对，过滤非游览主题；输出映射表、统计与分层抽查结果。

```bash
python task5/src/extract_conditionals.py
python task5/src/export_mapping_xlsx.py
python task5/src/visualize.py
python task5/src/spot_check.py --score
```

### 实验 6 多源程序性知识的融合与图谱可视化（task6/）

对齐实验 2 的实体体系、实验 3 的路线结构、实验 5 的条件建议，构建分景区游览知识图谱（NetworkX，别名表对齐 + 频次加权），导出 GraphML、CSV 与交互式 HTML 子图。

```bash
python task6/src/build_graph.py
python task6/src/verify_graph.py
python task6/src/visualize_graph.py
```

### 实验 7 程序性知识应用：旅游规划 Agent（task7/）

基于 LangGraph 的 ReAct Agent 自主调用图谱查询工具收集证据，由确定性编排器完成选点校验、分天分时段排序、交通与可行性校验，生成个性化行程与自然语言回答；`run_tests` 覆盖多类约束场景。

```bash
python task7/src/agent_cli.py
python task7/src/run_tests.py --llm
```
