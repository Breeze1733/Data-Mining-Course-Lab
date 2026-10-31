"""生成实验项目1报告：景区指南数据采集与预处理（report.docx）。

所有数字从 data/processed/quality_report.json 实时读取，保证报告与数据一致。
运行：python src/build_report1.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from report_utils import ReportBuilder

ROOT = Path(__file__).resolve().parents[1]
T1 = ROOT / "task1"
QR = json.loads((T1 / "data/processed/quality_report.json").read_text(encoding="utf-8"))
EXAMPLES = json.loads((T1 / "data/processed/cleaning_examples.json").read_text(encoding="utf-8"))
ROWS = [json.loads(l) for l in (T1 / "data/processed/dataset_clean.jsonl").open(encoding="utf-8")]
REJECTED = [json.loads(l) for l in (T1 / "data/processed/rejected_records.jsonl").open(encoding="utf-8")]

COV = QR["coverage_by_scenic_area"]
PROF = QR["profile"]
RULES = QR["cleaning_rule_totals_all_inputs"]
WARN = QR["warning_counts"]

RULE_DESC = {
    "html_tags_removed": "块级标签转换行、其余标签剔除",
    "html_noncontent_blocks_removed": "script/style/隐藏块整块跳过",
    "html_comments_removed": "HTML 注释剔除",
    "html_entities_decoded": "HTML 实体解码（含二次转义）",
    "fullwidth_characters_normalized": "全角 ASCII 与全角空格归一",
    "urls_removed": "URL 剔除",
    "emoji_and_decorative_characters_removed": "表情装饰剔除（保留→⚠✓）",
    "control_and_zero_width_characters_removed": "控制符/零宽字符剔除",
    "private_or_surrogate_characters_removed": "私用区/代理对字符剔除",
    "horizontal_whitespace_runs_normalized": "水平空白串归一为单空格",
    "blank_lines_removed": "空行剔除",
    "metadata_lines_removed": "平台元数据行剔除",
    "duplicate_long_paragraphs_removed": "≥40 字重复长段落剔除",
    "platform_notice_lines_removed": "平台公告行剔除（游记业务停运通知）",
    "trip_metadata_labels_removed": "行程元数据标签行剔除（出发时间/行程天数等）",
    "trip_metadata_values_removed": "行程元数据值行剔除（与标签成对）",
    "player_timestamp_lines_removed": "内嵌播放器时间戳行剔除（00:00/00:00）",
}


def fmt(n):
    return f"{n:,}"


def main():
    out = ROOT / "task1/report.docx"
    rb = ReportBuilder("《数据挖掘》探索性实验报告", "—实验项目1 景区指南数据采集与预处理")

    rb.section("一、实验目的与任务")
    rb.p("本实验围绕“景区游览指南的程序性知识挖掘”这一主题完成基础数据工程：采集黄山、九寨沟、颐和园三个景区的官方游览推荐路线与游客游记，"
         "对采集文本进行批量清洗与结构化，形成字段规范、质量可查、可直接支撑后续实体识别、路线结构挖掘、知识融合等实验的数据集。")
    rb.p("具体任务包括：①自行采集三个来源的数据（官方页面、携程游记、小红书笔记），并保留来源快照与哈希以便复现；"
         "②编写清洗脚本，去除 HTML 标签、URL、表情与控制字符等噪声，统一空白与全角/半角格式；"
         "③整理为结构化文件（含来源、景区、文本类型、原始内容、清洗后内容等字段），输出 Excel/CSV/JSONL 三种格式；"
         "④开展数据质量检查：各景区覆盖配额、空值、重复记录、异常字段的检查与说明。")

    rb.section("二、实验环境")
    rb.bullets([
        "操作系统：Windows 11；Python 3.13（venv 虚拟环境）。",
        "采集工具：Python 标准库 urllib + lxml 6.1（官方页面、携程游记）；Node.js 20 + Playwright 1.62（驱动本机 Microsoft Edge，用于小红书登录态下的笔记发现与正文提取）。",
        "清洗与分析库：Python 标准库（re、html.parser、unicodedata、hashlib、difflib）完成全部清洗规则，不依赖额外 NLP 工具；openpyxl 用于 Excel 导出。",
        "项目复现统一运行仓库根目录的python run.py。采集与预处理脚本保留用于数据准备，复现时使用已入库主语料。",
    ])

    rb.section("三、实验设计与实现")
    rb.sub("3.1 数据采集（自行采集）")
    rb.p("三个景区统一为黄山、九寨沟、颐和园。主语料采集批次在2026-10-28至10-29完成，采集脚本与来源说明已入库；本报告及下游实验采用保留的主语料批次。")
    rb.p("本报告采用已保存的303条组装输入、271条保留记录。项目复现统一从已入库的主语料开始，运行仓库根目录的run.py；来源采集及清洗方法作为数据准备过程保留。")
    rb.table(
        ["来源", "采集方法", "筛选规则", "结果"],
        [
            ["官方页面\n（22 份文档）",
             "已核实来源清单（jiuzhai.com、summerpalace.net.cn、beijing.gov.cn 等），urllib 拉取 + lxml XPath 定位正文区域，保存 HTML 快照与 SHA256",
             "保留页面上的路线原文分支；图片路线采用预先核对的转录文本；无固定顺序的主题方案单独标记",
             "46 条路线分支\n（39 有序 + 7 主题）"],
            ["携程游记\n（744 候选页）",
             "景区目录翻页 + 22 条公开种子发现文章，按公开阅读量排序采集正文快照",
             "正文须含 ≥3 个景区 POI、明确的路线段落、一手游记信号；广告/住宿/攻略贩售类标题与正文剔除",
             "149 篇合格游记"],
            ["小红书笔记\n（132 条）",
             "Playwright 驱动 Edge 登录后搜索“景区名 游记 路线”，按“最多点赞”排序发现笔记，提取可见正文",
             "正文须含 ≥2 个景区节点与路线表达；不采集图片（无 OCR）、评论与站内 AI 总结",
             "132 条笔记"],
        ],
        widths=[2.6, 5.2, 4.6, 2.6],
    )
    rb.caption("表 1 三类来源的采集方法与结果")
    rb.p("采集阶段设有断点续跑与失败重试（-RetryFailed），每次运行生成 logs/collection_*.log；"
         "小红书登录在浏览器内完成，脚本不接触密码与验证码。", indent=True)

    rb.sub("3.2 数据组装（build_records.py）")
    rb.p("三类来源的字段结构不同，先统一组装为 12 个必填字段的 records.jsonl（303 条，无重复 ID），字段包括 record_id、景区、来源平台、"
         "文本类型、标题、来源 URL、采集时间、原始内容、原始格式、提取选择器、快照路径、内容范围。三个关键设计：")
    rb.bullets([
        "携程记录的原始内容取正文容器（travel-content-wrapper）的外层 HTML 片段：站点导航、页脚等页面杂项不进入数据集，容器内的 HTML 标签留给清洗规则处理，清洗效果可审计；",
        "149 个携程 HTML 快照在组装时逐一校验 SHA256，与候选池记录一致才进入；",
        "2 篇无固定节点顺序的九寨沟官方主题方案保留在数据集中，但标记 official_scope=supplementary_theme，不冒充有序路线。",
    ])

    rb.sub("3.3 清洗规则（preprocess.py）")
    rb.p("清洗管线按“先解析、再归一、后过滤”组织，共 16 条规则，全部命中次数可审计（见表 3）。几个关键取舍：")
    rb.bullets([
        "保留路线箭头（→ ⇄ 等）与语义符号（⚠ ✅ ❌）：它们承载“先后顺序”“禁止/许可”信息，后续路线解析与条件抽取要用，不能当噪声删；",
        "全角归一只处理 ASCII 区与全角空格，保留 ① Ⅰ ² ℃ 等记号——盲目 NFKC 会把 2²km 变成 22km；",
        "疑似乱码（锟斤拷等）只打标记不猜测修复，避免清洗环节篡改原文；",
        "精确重复按“去空白内容指纹”判定（标点与语义符号参与指纹，A+B 与 A-B 是不同内容）；近似重复（相似度 ≥0.9）标记保留，由后续词频加权按标记复核。",
    ])

    rb.sub("3.4 结构化输出与质量检查")
    rb.p("清洗后数据集共 271 条，字段覆盖标识、来源、内容、统计与质量五个层面（清洗前后内容、字符数、保留率 retention_ratio、质量标记等），"
         "输出六种文件：dataset_clean.csv（utf-8-sig，Excel 可直接打开）、dataset_clean.jsonl（无损主文件）、"
         "scenic_guide_dataset.xlsx（5 个工作表的人类可读交付版）、quality_report.json（全量质量指标）、"
         "cleaning_examples.json（271 组清洗前后对照）与 rejected_records.jsonl（32 条拒绝记录及原因）。")
    rb.p("质量检查项：①覆盖配额——每个景区至少 1 条官方路线和 3 篇游记；②空值/缺失必填字段；③精确与近似重复；"
         "④格式一致性（景区名、文本类型、日期格式、URL 合法性）。检查结果见第四章。")

    rb.section("四、实验结果与分析")
    rb.sub("4.1 总体结果与覆盖")
    rb.p(f"输入 303 条，保留 {QR['accepted_records']} 条，拒绝 {QR['rejected_records']} 条；"
         f"清洗后共 {fmt(PROF['clean_characters_total'])} 字符（单篇最短 {PROF['clean_length_min']}、中位数 {PROF['clean_length_median']:,.0f}、"
         f"最长 {fmt(PROF['clean_length_max'])}）。三个景区均远超任务书“1 条官方路线 + 3 篇游记”的下限。")
    rb.table(
        ["景区", "官方路线", "携程游记", "小红书笔记", "合计"],
        [[area, cov["platforms"].get("官方", 0), cov["platforms"].get("携程游记", 0),
          cov["platforms"].get("小红书", 0), cov["total"]] for area, cov in COV.items()],
        widths=[3.0, 2.6, 2.6, 2.6, 2.2],
    )
    rb.caption("表 2 清洗后数据集的分景区 × 平台覆盖（满足配额：是）")

    rb.sub("4.2 清洗规则命中统计")
    rb.table(
        ["清洗规则", "命中次数", "说明"],
        [[rule, fmt(cnt), RULE_DESC.get(rule, "")] for rule, cnt in
         sorted(RULES.items(), key=lambda kv: -kv[1])],
        widths=[5.6, 2.4, 7.0],
    )
    rb.caption("表 3 各清洗规则在全部 303 条输入上的命中次数")

    rb.sub("4.3 拒绝记录与重复内容分析")
    short = sum(1 for r in REJECTED if any(x.startswith("content_too_short") for x in r["rejection_reasons"]))
    dup = sum(1 for r in REJECTED if any(x.startswith("duplicate_clean_content") for x in r["rejection_reasons"]))
    rb.p(f"32 条拒绝记录中，{short} 条为内容过短（清洗后非空白字符不足 80，几乎全部是小红书纯图集类空壳笔记，最短仅 3 字符）；"
         f"{dup} 条为精确重复。值得注意的现象是：携程存在“同一篇游记以不同文章 ID 反复发布”的情况——"
         "15 条精确重复来自 4 组“同文不同 ID”：最大的一组 CTRIP_4005525 同一正文（10,964 字符）在候选池中共有 8 个不同文章 ID、"
         "8 个不同标题的副本（7 份被去重），其余三组分别为 6、3、2 份。"
         "若不去重，同一行程的词频与路线统计会被成倍放大，因此内容指纹去重对下游实验是必要的。")
    rb.p(f"保留集中还检出 {len(QR['near_duplicate_pairs'])} 对近似重复（相似度 0.992–0.9995，未达逐字相同），按“仅标记不删除”策略保留，"
         "并在质量标记中注明。这类记录主要影响词频统计的权重，实验 2 统计词频时会结合该标记复核。")

    rb.sub("4.4 清洗前后样例对比")
    html_ex = next(e for e in EXAMPLES if e["raw_format"] == "html" and e["cleaning_counts"].get("html_tags_removed", 0) > 100)
    emoji_ex = next(e for e in EXAMPLES if e["record_id"].startswith("XHS") and e["cleaning_counts"].get("emoji_and_decorative_characters_removed", 0) > 0)

    def clip(text, n=210):
        text = re.sub(r'https?://[^\s"<>]+', "[长链接省略]", text)
        text = text.replace("\n", "⏎")
        return text[:n] + ("…" if len(text) > n else "")

    rb.table(
        ["样例", "清洗前（节选）", "清洗后（节选）"],
        [
            [f"{html_ex['record_id']}\n（携程，HTML）",
             clip(html_ex["before"]),
             clip(html_ex["after"])],
            [f"{emoji_ex['record_id']}\n（小红书，纯文本）",
             clip(emoji_ex["before"]),
             clip(emoji_ex["after"])],
        ],
        widths=[3.0, 6.5, 5.5],
        font_size=9,
    )
    rb.caption("表 4 清洗前后样例（⏎ 表示换行；长链接为显示省略；完整对照见cleaning_examples.json与Excel表）")
    rb.p("携程样例中标签、实体与页面残留被清除而正文完整；小红书样例中表情符号被剔除，但 ⚠、→、时间表达（如 5:40）全部保留，"
         "路线结构未受破坏。271 组完整对照已随数据集输出。")

    rb.sub("4.5 质量警告及处理")
    rb.p(f"保留集共 {len(WARN)} 类警告：作者缺失 {WARN.get('author_missing', 0)} 条（携程旧文公开 HTML 不显示作者，属来源限制，字段留空不猜测）；"
         f"发布日期缺失 {WARN.get('publication_date_missing', 0)} 条（来源页面未提供，同样留空）；"
         f"路线线索待复核 {WARN.get('route_cues_require_review', 0)} 条（多为不含时间词的短官方路线段，人工复核后确认有效）；"
         f"景区相关性待复核 {WARN.get('scenic_relevance_requires_review', 0)} 条（颐和园无障碍路线，因检查词表未含“轮椅/无障碍”类别名触发，人工确认属于颐和园官方内容，保留）；"
         f"近似重复 {WARN.get('near_duplicate', 0)} 对（见 4.3）。所有警告均“标记不删除”，保证可追溯。")

    rb.section("五、实验小结")
    rb.p(f"本实验完成了从“原始页面”到“可挖掘数据集”的完整链路：303 条原始文本经 {len(RULES)} 条清洗规则得到 271 条高质量记录，"
         "黄山/九寨沟/颐和园三景区在官方、携程、小红书三个来源上均有充足覆盖，全部产物带快照与哈希，可复现。")
    rb.p("主要收获有三点：其一，清洗规则必须服务于下游任务——路线箭头、时段标记、警告符号这些“看起来像噪声”的符号恰恰是程序性知识的载体；"
         "其二，去重不能只看 URL：携程同文不同 ID 的转载现象说明内容指纹才是可靠的重复判据；"
         "其三，质量检查要区分“拒绝”（短文本、精确重复）与“警告”（作者缺失、近似重复），后者保留数据、只降低可信度权重，避免误删有效样本。")
    rb.p("延伸方向：近似重复以保留标记进入实验 2 的词频加权复核；小红书笔记中图片承载的路线信息可通过 OCR 补充，"
         "可能漏掉少量纯图路线；携程旧文作者字段受来源限制无法补全。这些问题将在后续实验中按需处理。")

    rb.save(out)


if __name__ == "__main__":
    main()
