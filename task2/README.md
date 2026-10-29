# 实验项目2：游览步骤的实体识别

从实验1清洗后的 271 条文本中识别三类实体：**景点POI、交通方式、时间节点**（时刻/时段/时长/日期四类）。方法：jieba 分词 + 自定义词典最长匹配（POI/交通）+ 正则规则（时间节点），含两轮迭代（baseline 种子词典 → refined 语料挖掘整理词典）。

## 目录结构

```
src/
  build_dictionary.py   词典构建（词频挖掘候选 + 人工整理 + jieba 用户词典导出）
  extract_entities.py   实体抽取（--iteration baseline|refined）
  visualize.py          词频柱状图 + 词云 + 分景区对比图
  spot_check.py         人工质检抽样（分层随机，固定种子）
output/
  exp2/entity_dictionary.json   整理后的词典（POI/交通/停用词）
  exp2/entity_userdict.txt      jieba 自定义词典
  exp2/entity_schema.md         实体定义规范表
  exp2/entities_{iteration}.jsonl  逐记录实体（含偏移量）
  exp2/entity_stats_{iteration}.json 词频统计
  exp2/iter_compare.json        两轮迭代对比
  exp2/spot_checks.json         质检样例与判定
  exp2/figs/*.png               可视化图表
report.docx              实验项目2报告
```

## 运行方法（在 task1 的虚拟环境内）

```powershell
cd task1
.\.venv\Scripts\python.exe -X utf8 ..\task2\src\build_dictionary.py
.\.venv\Scripts\python.exe -X utf8 ..\task2\src\extract_entities.py --iteration baseline
.\.venv\Scripts\python.exe -X utf8 ..\task2\src\extract_entities.py --iteration refined
.\.venv\Scripts\python.exe -X utf8 ..\task2\src\visualize.py --iteration refined
.\.venv\Scripts\python.exe -X utf8 ..\task2\src\spot_check.py
```

## 输入 → 输出

| 输入 | 输出 |
|---|---|
| `task1/data/processed/dataset_clean.jsonl`（271 条清洗后文本） | `output/exp2/entities_{iteration}.jsonl`、`entity_stats_{iteration}.json` |
| 词频统计 | `output/exp2/figs/*.png` |
| 抽样实体 + 人工判定 | `output/exp2/spot_checks.json`（样例正确率） |

## 主要参数

- 词典：POI 128 条（含周边景点/原始森林内部节点等子类）、交通 37 条（8 个子类）、领域停用词 28 条；时间节点 4 类正则（优先级：日期 > 时刻 > 时长 > 时段）。
- 匹配：长词优先、位置互斥；停用词守卫防止“北海”命中“北海公园”。
- 质检抽样：每类型 × 景区分层，随机种子 42。
