> 项目复现见根目录README；本页记录采集方法与来源。

# 任务1 景区路线自动采集

采集黄山、九寨沟、颐和园的官方游览路线，以及每景区携程25篇、小红书25篇游客路线文本。入口完成采集、来源留存、候选去重和热度筛选；后续清洗与挖掘另行执行。

运行不需要Codex、LLM或模型API Key。官方页面使用代码中的来源清单；携程使用目录入口及少量公开种子链接发现文章；小红书使用站内搜索自动发现笔记。正文由程序批量提取，路线有效性使用关键词、景点节点和正则规则检查。

## 从克隆到首次运行

运行环境：Windows、PowerShell 7+、Python 3.10+、Node.js 20+（含npm），以及已安装的Microsoft Edge。以下命令从克隆所得仓库根目录开始，不依赖原作者的磁盘路径。

```powershell
cd task1
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd ci
.\run_collection.ps1 -PythonExe .\.venv\Scripts\python.exe
```

使用虚拟环境Python的路径，无需激活虚拟环境。`npm.cmd ci` 根据已提交的 `package-lock.json` 安装Playwright；脚本通过 `channel=msedge` 启动本机Edge，无需下载Playwright自带浏览器。若终端不能识别 `python` 或 `node`，先安装相应运行环境并重新打开终端；若PowerShell策略限制本地脚本，按本机管理策略处理，或使用下文分步命令。

Python依赖为 `lxml`（解析HTML）和 `tzdata`（Windows时区数据），其他采集代码使用标准库。`requirements.txt` 仅对应本轮采集入口，旧版Word、Excel报告脚本需要的工具不在本轮安装范围内。

首次运行不需要已有数据、日志或浏览器会话；脚本会创建输出目录，并依次执行：

| 阶段 | 脚本 | 行为 |
|---|---|---|
| 官方来源 | `src/crawl_official.py` | 抓取已核实来源清单，保留正文、图片原件及全部路线分支 |
| 携程 | `src/crawl_ctrip_ranked.py` | 从公开种子和景区目录发现文章，采集正文与阅读量并保存候选池 |
| 小红书 | `src/crawl_xiaohongshu.mjs` | 登录后搜索、选择“最多点赞”、滚动发现笔记并提取正文 |
| 汇总 | `src/select_collection.py` | 去重后按平台热度选25篇，导出并检查配额、字段和快照 |

一键入口自动生成 `logs/collection_日期_时间_编号.log`，记录本次控制台输出与失败信息。首次采集需要联网，小红书阶段需要本人登录。站点改版、内容删除、登录状态和访问限制可能改变结果，新运行不保证得到历史上的同一批150篇。

## 小红书登录

1. 等待脚本打开独立Edge窗口，在小红书页面扫码或使用网站支持的方式完成本人登录。
2. 登录在浏览器里完成，不在终端输入密码或验证码。
3. 确认页面已经登录后，回到运行脚本的终端按Enter，脚本继续采集三个景区。
4. 下次运行保留同一个 `.browser-profile/`，可以复用仍有效的登录状态；终端仍会等待Enter，供本人确认页面可以访问。

该窗口与日常Edge配置隔离，其他浏览器或Codex里的登录不会自动复制过来。脚本不导出Cookie，不自动处理验证码。遇到验证、登录失效或访问限制，先用Ctrl+C停止，在网站完成本人操作后重跑。不要同时启动多个采集实例，它们共用队列和输出文件。

默认使用系统Edge。单独运行小红书时，可以通过 `--channel chrome` 使用已安装的Chrome，通过 `--profile .browser-profile-alt` 使用另一份本地会话。

## 断点续跑和失败重试

保留本机 `data/` 和 `research/` 下的运行文件，再执行原命令即可继续：

```powershell
.\run_collection.ps1 -PythonExe .\.venv\Scripts\python.exe
```

携程复用已保存的候选与正文快照，并重新扫描目录；官方阶段重新采集来源清单。小红书复用已保存正文和队列，跳过已成功采集的笔记。每条笔记提取后立即保存，后续失败不会丢失此前成功结果。默认每景区尝试采集35篇含路线的候选，为最终选25篇留出余量。

普通续跑不会反复尝试已经失败的项目。确认登录、网络等问题解决后，可以显式重试：

```powershell
.\run_collection.ps1 -PythonExe .\.venv\Scripts\python.exe -RetryFailed
```

`-RetryFailed` 重试携程有请求或提取错误的文章，以及小红书队列中带 `error` 的笔记；不会放宽正文质量规则。小红书重新发现同一笔记时，会更新队列中的公开详情链接，以替换已失效的临时链接。

只补采单个景区或提高候选余量：

```powershell
# 仅补九寨沟小红书，将候选目标提高到45篇
node src/crawl_xiaohongshu.mjs --area 九寨沟 --target 45 --retry-failed

# 仅补颐和园携程，最多扫描120页
.\.venv\Scripts\python.exe src/crawl_ctrip_ranked.py --area 颐和园 --max-pages 120 --pool-size 35 --retry-failed

# 使用现有采集结果重新筛选每平台25篇
.\.venv\Scripts\python.exe src/select_collection.py --per-platform 25
```

`--area` 支持 `all`、`黄山`、`九寨沟`、`颐和园`。小红书 `--target` 是候选数，最终数量以汇总为准。候选耗尽仍不足25篇时，保留真实结果并报告缺额，不生成占位记录。页面结构改变时需要更新选择器，重复登录无法修复结构不匹配。

一键入口支持 `-SkipXhs`、`-SkipCtrip` 跳过相应阶段，仍执行官方采集和汇总；被跳过的平台必须已有本地数据。`-PythonExe`、`-NodeExe` 可以指定解释器路径。

## 离线重建和分步运行

完成在线采集后，可以用保存的快照重建官方数据和游客筛选结果，不发网络请求、不启动浏览器：

```powershell
.\run_collection.ps1 -Offline -PythonExe .\.venv\Scripts\python.exe
```

新克隆没有快照，不能直接离线生成真实数据。离线模式不会回退联网补抓；缺少文件、配额不足或快照校验失败，会写入汇总并以失败状态结束。

也可以从 `task1` 目录分步执行。这些命令生成结构化采集日志，控制台总日志仅由一键入口自动生成：

```powershell
.\.venv\Scripts\python.exe src/crawl_official.py
.\.venv\Scripts\python.exe src/crawl_ctrip_ranked.py --area all --max-pages 120 --pool-size 35
node src/crawl_xiaohongshu.mjs --area all --target 35
.\.venv\Scripts\python.exe src/select_collection.py --per-platform 25
```

`select_collection.py` 成功时退出码为0；缺额、必填字段缺失或快照问题时为2。一键入口遇到上述问题会抛出错误并保留日志，不能仅凭文件已生成就判定完成。

不访问真实网站的入口回归检查：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s src -p test_collection.py -v
node --check src/crawl_xiaohongshu.mjs
```

## 输出、日志与缓存

| 路径 | 内容 |
|---|---|
| `data/collected/tourist_routes.csv` | Excel可查看的完整可读正文、来源、热度、排名与时间 |
| `data/collected/tourist_routes.jsonl` | 每行一篇的主文件，保留原文和嵌套元数据 |
| `data/collected/黄山/`、`九寨沟/`、`颐和园/` | 各景区携程和小红书前25篇独立清单 |
| `data/collected/eligible_candidate_pool.csv` | 通过正文检查的候选与入选标记，用于复核排名 |
| `data/collected/official_documents.jsonl` | 官方来源文档、日期、来源链与路线分支 |
| `data/collected/official_routes.jsonl` | 全部官方分支，`ordered_route` 区分有序路线和主题建议 |
| `data/collected/collection_summary.json` | 数量、缺额、重复剔除、字段缺失及快照哈希检查 |
| `data/raw/pages/`、`data/raw/catalogs/` | 携程正文、部分官方正文与携程目录HTML快照 |
| `research/official_expansion_pages/` | 官方HTML与图片原件 |
| `data/raw/xiaohongshu_browser_export.json`、`data/raw/notes/` | 小红书批量正文导出和有效笔记独立快照 |
| `research/ctrip_ranked_candidates.json`、`research/ctrip_ranked_log.json` | 携程断点候选池和目录请求日志 |
| `research/xiaohongshu_queue.json`、`research/xiaohongshu_crawl_log.json` | 小红书队列、成功记录与错误 |
| `research/official_expansion.json`、`research/official_collection_summary.json` | 官方采集明细与汇总 |
| `logs/collection_*.log` | 一键入口每次运行的控制台日志 |
| `.browser-profile/` | 本人本机的浏览器会话，不提交或分享 |

只有 `collection_summary.json` 的 `complete=true` 才表示配额、必填字段和快照检查全部通过。平台未显示的作者等可选元数据可能留空，汇总会另行统计。

主文件包含来源URL、平台、景区、文本类型、原文、采集时间、快照路径与哈希，以及平台热度和组内排名。CSV的 `raw_content` 是可读正文；JSONL的携程 `raw_content` 保留HTML片段。CSV对可能被Excel解释为公式的文本前缀加单引号，JSONL保留原文。

## 筛选范围与可复现边界

携程从黄山、九寨沟和北京目录，以及 `src/expand_ctrip.py` 中少量北京公开种子发现文章。热门目录上限分别为15、38、120页，也受 `--max-pages` 限制。北京目录涉及全城，只有通过颐和园景点节点、路线段落及正文检查的文章才入选。“热门”仅为发现入口，最终按公开阅读量数值重排。历史候选JSON存在时可复用，首次运行不依赖它们。

小红书搜索“景区名 游记 路线”，选择“最多点赞”，在含至少两个景区节点和路线表达的有效正文中筛选。只保存笔记正文，不采评论、私信或右侧AI搜索总结；图片与视频未OCR，路线仅在图片中的笔记可能被排除。排名为实际采到的有效候选池内前25，不等于平台全站精确前25。

“2.1万”等显示值转换为21000排序，并保留原显示值；同值按URL稳定排序，同景区同平台按URL和正文去重。相对发布日期保留平台原文，不猜填具体日期。

官方“全量”指 `research/build_official_expansion.py` 和 `src/crawl_official.py` 的已核实来源清单内全部文档及分支，固定清单不会自行发现新增页面。其中一份图片路线使用预先核对的转录文本并下载图片原件，不执行OCR。保留历史日期、季节与活动适用范围；检索边界见 `research/official_search_audit.md`、`research/huangshan_official_search_boundary.md` 和 `research/ctrip_search_boundary.md`。

## Git跟踪规则

提交代码、依赖声明、`package-lock.json`、来源定义和说明文档。仓库根目录的 `.gitignore` 管理根目录环境和通用系统文件；`task1/.gitignore` 管理本任务的虚拟环境、Node依赖、浏览器会话、`data/`、`logs/`、`qa/`，以及研究目录下的采集JSON、HTML和图片快照。原先已跟踪的这些生成文件从Git索引移除，本机文件保留；新克隆使用上述命令自行生成。

旧版 `collect.py`、`assemble.py`、`preprocess.py`、`export_xlsx.mjs` 及 `report.docx` 属于此前实验阶段，不是本轮入口；`sources.json` 是旧版来源配置，继续保留为文本配置。提交课程成果时可以另外打包本机 `data/collected/` 与必要证据，不要打包浏览器会话。

## 历史运行参考

2026年10月28日的一次在线采集及离线复跑结果，仅作配额和文件组织参考，新克隆会重新采集：

| 景区 | 携程 | 小红书 | 官方文档 | 有序路线分支 |
|---|---:|---:|---:|---:|
| 黄山 | 25 | 25 | 3 | 13 |
| 九寨沟 | 25 | 25 | 8 | 9 |
| 颐和园 | 25 | 25 | 11 | 17 |
| 合计 | 75 | 75 | 22 | 39 |

另保留九寨沟7个无固定顺序的主题方案。当次150篇游客正文共478864字符，快照与必填字段检查通过；20条携程作者字段因公开HTML未显示而留空。
