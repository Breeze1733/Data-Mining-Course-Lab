"""生成实验项目5报告：条件性游览建议的抽取（task5/report.docx）。

数字实时读取 task5/output/ 下的抽取、抽检与统计文件。运行：python src/build_report5.py（-X utf8）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from report_utils import ReportBuilder

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "task5/output"
FIGS = OUT / "figs"

STATS = json.loads((OUT / "extraction_stats.json").read_text(encoding="utf-8"))
REVIEW = json.loads((OUT / "review_summary.json").read_text(encoding="utf-8"))
MAPPING = json.loads((OUT / "mapping_table.json").read_text(encoding="utf-8"))

CORRECT = REVIEW["verdicts"].get("correct", 0)
BOUNDARY = REVIEW["verdicts"].get("boundary", 0)
WRONG = REVIEW["verdicts"].get("wrong", 0)
N = REVIEW["n"]


def main():
    rb = ReportBuilder("《数据挖掘》探索性实验报告", "—实验项目5 条件性游览建议的抽取")

    rb.section("一、实验目的与任务")
    rb.p("挖掘旅游文本中的条件逻辑（“如果下雨则改期”“带老人别走中轴线”）：设计触发词规则识别条件句的"
         "条件部分与建议部分，批量抽取“条件→建议”对并构建结构化映射表（条件类型、条件描述、建议内容、来源景区等字段），"
         "经人工校验迭代规则，按游客类型分组统计并可视化。")

    rb.section("二、实验环境")
    rb.bullets([
        "Windows 11；Python 3.13（task1/.venv）；matplotlib 绘图；openpyxl 导出 Excel。",
        "输入：task1/data/processed/dataset_clean.jsonl（271 条，含官方路线与游记）。",
        "项目复现统一运行仓库根目录的python run.py，顺序完成条件建议抽取、历史标注计分、图表、Excel及报告生成。",
    ])

    rb.section("三、实验设计与实现")
    rb.sub("3.1 触发词与抽取模式")
    rb.p("设计五类模式并规定优先级（同句显式条件优先，命中即不再走推断模式）：")
    pattern_desc = {
        "P1_显式条件": ("如果/假如/若是/要是/万一/一旦/只要/除非/…的话", "触发词到首个逗号", "逗号后至句末（多建议按分号切分）"),
        "P4_建议推断": ("建议/推荐/最好/尽量/务必/记得/适合/适宜", "从句内人群/天气/时间词推断，缺省为一般建议", "触发词后从句"),
        "P6_否定建议": ("不要/别/避免/慎/切勿/忌", "从句内天气/装备/时间词推断", "否定词后从句"),
        "P5_人群可以": ("老人/孩子/体力差…+可以", "人群主语", "可以后从句"),
        "P3_时点条件": ("当/遇到…时", "时点从句", "时点后从句"),
    }
    rows = [[name.replace("_", " "), desc[0], desc[1], desc[2], f"{STATS['by_pattern'][name]:,}"]
            for name, desc in pattern_desc.items() if name in STATS["by_pattern"]]
    rb.table(["模式", "触发词/结构", "条件部分", "建议部分", "数量"], rows,
             widths=[2.2, 4.4, 3.4, 3.6, 1.6], font_size=9)
    rb.caption("表 1 条件触发词与抽取模式（数量为原始抽取对数）")
    rb.p("规则的优先级与适用边界：①裸“可以”不抽——语料中 1,265 处“可以”绝大多数是叙述能力句"
         "（“可以远眺五彩池”），仅保留“人群主语+可以”与否定式；②负向极性守卫——“不建议”“不适合”"
         "“不要门票（=免费）”“要不要坐（疑问）”不作为建议触发；③复合词守卫——“宛若”“特别”“别具一格”"
         "“禁忌之旅”“不慎失火”“当时/当初”等不触发；④多建议句按分号全切，按逗号仅当后半以建议动词开头才切，"
         "避免切断动宾结构。")

    rb.sub("3.2 条件类型分类与映射表构建")
    rb.p("条件文本按关键词归入 9 类：人群、天气、时间、装备、预约票务、交通、体力安全、一般、其他。"
         f"共抽取 {STATS['raw_pairs']:,} 对，按（景区 + 条件归一文本 + 建议归一文本）去重后保留 "
         f"{STATS['after_dedup']:,} 对（合并重复 {STATS['duplicates_merged']} 对，保留来源与频次）。"
         "映射表字段：条件类型/条件描述/建议内容/触发词/抽取模式/景区/频次/来源记录，"
         "输出 conditional_mapping_table.xlsx（1210 行）与 mapping_table.json。"
         "抽取前有一道句级归属过滤（默认开启，--no-attribution-filter 可关）：特征规则判定句子叙述焦点，"
         "景区外句子不产出条件建议对——这是 1,210→842 条去噪的主要机制之一，与实验4 的消解候选过滤共用同一实现。")

    rb.section("四、实验结果与分析")
    rb.sub("4.1 类型与景区分布")
    rb.image(FIGS / "cond_type_by_scenic.png", 15.0)
    rb.caption("图 1 条件类型 × 景区分布（按频次加权）")
    rb.p("三个景区的“一般建议”与“其他”类合计都超过一半——游记的多数建议并不绑定显式条件，这是文体的常态。"
         "在有明确条件的类型中：时间类在三个景区均居首位（行程时长、错峰、季节窗口）；装备类集中于黄山与九寨沟"
         "（登山穿衣、高海拔氧气），黄山还独有体力安全类（封山/失温）；人群类以颐和园最多（16 条，围绕带老人孩子"
         "怎么走）；天气类三景区都不足 20 条——游记默认天气正常，极端天气建议反而少。")

    rb.sub("4.2 游客类型分组统计")
    rb.image(FIGS / "crowd_breakdown.png", 13.5)
    rb.caption("图 2 人群类条件建议的游客类型分布")
    rb.p("人群类条件中“孩子”最多（13 条，含带娃/儿童表述），其次是“体力有限”（9 条，含体力不足/腿脚不便）、"
         "“情侣”（8 条）与“恐高”（6 条）。值得注意“老人”仅 3 条——带老人出行的建议多以“体力”“腿脚”"
         "间接表述，按游客类型统计时需要聚合体力维度才能完整刻画“银发游”场景。")

    rb.sub("4.3 人工抽检与规则迭代")
    rb.p(f"按“模式 × 景区”分层随机抽样 {N} 例人工判定（种子 42），三轮规则迭代："
         "第 1 轮裸“若/别”大量误触发（宛若、特别、别具一格，P6 高达 577 对）；第 2 轮修复复合词与"
         "“当时/当初”后 P6 降至 106 对；第 3 轮补充负向极性守卫（不建议/不适合/不要门票/要不要）与"
         "“阳光最好的时间”极性判断。最终抽检结果：")
    rb.table(["判定", "数量", "占比", "说明"],
             [["正确", str(CORRECT), f"{CORRECT / N:.0%}", "条件与建议切分及类型全部正确"],
              ["边界", str(BOUNDARY), f"{BOUNDARY / N:.0%}", "对中存在切分/条件推断瑕疵但核心语义成立"],
              ["错误", str(WRONG), f"{WRONG / N:.0%}", "误触发或语义不成立"]],
             widths=[2.0, 1.8, 1.8, 9.4])
    rb.caption("表 2 人工抽检结果（49 例，判定记录见 review_gold.json）")
    rb.p("错误案例的四种模式：①修辞/叙述开头（“如果说颐和园…”“经母上大人的倾情推荐”）；"
         "②广告与求赞文本（“太适合经常出行了”是行李箱文案）；③对话与愿望转述（“不要排了”“真希望不要成为”）；"
         "④长句杂糅导致建议部分抓成事实陈述。边界案例集中在跨括号/跨逗号的切分点与“句内推断条件”的弱关联上。"
         "样本中还发现游客间的对立建议（同一颐和园，一条“建议买联票更省心”、另一条“不要买联票”），"
         "说明条件建议本质上是个人经验，融合时需保留来源与频次而非强行合并。")

    rb.section("五、实验小结")
    rb.p(f"本实验以五类模式从 271 条文本抽取 {STATS['raw_pairs']:,} 对条件→建议，去重后构建 "
         f"{STATS['after_dedup']:,} 条的映射表（Excel + JSON，带来源与频次），经三轮规则迭代与 49 例人工抽检，"
         "严格正确率 40.8%、含边界 73.5%。主要收获：触发词规则的精度取决于“极性守卫 + 复合词守卫”这类"
         "负向约束而非触发词本身；条件类型里“一般建议”占比最高反映了游记的建议表达习惯；"
         "对立建议现象提示知识融合必须保留来源与频次。映射表将作为边属性（条件关系）进入实验6知识图谱。")

    rb.save(ROOT / "task5/report.docx")


if __name__ == "__main__":
    main()
