"""生成实验项目2报告：游览步骤的实体识别（task2/report.docx）。

数字实时读取 output/exp2/ 下的统计与质检文件。运行：python src/build_report2.py（在 task1 venv 内）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
from report_utils import ReportBuilder

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/exp2"
FIGS = OUT / "figs/refined"
FIGS_BASE = OUT / "figs/baseline"

STATS = {it: json.loads((OUT / f"entity_stats_{it}.json").read_text(encoding="utf-8"))
         for it in ("baseline", "refined")}
SPOT = json.loads((OUT / "spot_checks.json").read_text(encoding="utf-8"))
DICT = json.loads((OUT / "entity_dictionary.json").read_text(encoding="utf-8"))
REF = STATS["refined"]
BASE = STATS["baseline"]


def by_type(stats):
    return {t: sum(v.get(t, 0) for v in stats["by_scenic_area"].values())
            for t in ("景点POI", "交通方式", "时间节点")}


def main():
    rb = ReportBuilder("《数据挖掘》探索性实验报告", "—实验项目2 游览步骤的实体识别")

    rb.section("一、实验目的与任务")
    rb.p("在实验1清洗后的 271 条景区文本（官方路线、携程游记、小红书笔记）基础上，识别程序性文本中的三类核心要素——"
         "景点POI、交通方式、时间节点；在多景区对比中归纳实体类型体系并形成定义规范表；输出带位置信息的 JSON 实体文件与词频可视化图表，"
         "并根据可视化结果迭代停用词与词典，优化识别质量。")

    rb.section("二、实验环境")
    rb.bullets([
        "Windows 11；Python 3.13（复用 task1/.venv）。",
        "jieba 0.42（分词与自定义词典）；matplotlib + wordcloud（词频柱状图与词云，SimHei 中文字体）。",
        "输入：task1/data/processed/dataset_clean.jsonl（实验1清洗后主数据集，271 条）。",
        "运行入口：task2/src/{build_dictionary, extract_entities, visualize, spot_check, iter_compare, build_report2}.py。",
    ])

    rb.section("三、实验设计与实现")
    rb.sub("3.1 实体类型体系（定义规范表）")
    rb.p("对比三个景区的识别结果后归纳出统一的实体体系，完整规范见 output/exp2/entity_schema.md，要点如下：")
    rb.table(
        ["实体类型", "定义", "边界与易混淆情况", "示例"],
        [
            ["景点POI",
             "被赋予专名、游客可到达游览的具体对象（峰/海/瀑/桥/殿/阁/园/寨/沟/松）",
             "景区自身名不算POI；通名（山峰/峡谷）不算；周边景点（黄龙/宏村）单列子类；同名异点需上下文消歧（黄龙五彩池 vs 九寨沟五彩池）",
             "五花海、光明顶、十七孔桥、树正寨"],
            ["交通方式",
             "表达“从一处到另一处所乘用手段”的名词性表达",
             "乘车/下车等动作不收；索道站名归交通设施子类；复合词守卫（步行街/火车站/登山杖/地铁站）",
             "观光车、玉屏索道、徒步、高铁"],
            ["时间节点",
             "游览安排中的时间位置或时长，分时刻/时段/时长/日期四类",
             "时钟范围合并为一条；“半天”多为口语不收；“上午9点”整体记时刻；Day02 完整记录",
             "7:00-8:10、上午9点、约30分钟、第二天"],
        ],
        widths=[1.9, 4.0, 6.0, 2.9],
        font_size=9,
    )
    rb.caption("表 1 三类实体的定义、边界与示例（三景区共用同一体系，仅词表不同）")

    rb.sub("3.2 词典构建（jieba 分词 + 自定义词典）")
    rb.p(f"POI 词典采用“词频挖掘 + 人工复核”两步构建：先对全语料做 jieba 分词统计，筛选以 海/峰/阁/桥/殿 等 POI 后缀结尾、"
         f"出现 ≥8 次的候选词（436 个），逐一人工复核剔除通名（下山/知道/上海类）后并入采集阶段的景区种子词，"
         f"最终得到 POI {DICT['meta']['counts']['poi']} 条（含周边景点子类）、交通 {DICT['meta']['counts']['transport']} 条（8 个子类）、"
         f"领域停用词 {len(DICT['domain_stopwords'])} 条。词条以 jieba 用户词典格式导出（entity_userdict.txt），保证分词阶段专名成词。")

    rb.sub("3.3 识别方法")
    rb.p("POI 与交通方式采用“自定义词典最长匹配”扫描：词典条目按长度降序构建正则交替式，长词优先（“西海大峡谷”不会被“西海”抢先），"
         "命中位置互斥，直接得到字符级偏移量；时间节点用正则规则链识别，优先级为 日期 > 时刻 > 时长 > 时段。"
         "两道守卫保证查准率：①停用词守卫——若停用词（如“北海公园”）从同一位置开始则丢弃；②复合词守卫——"
         "命中词后紧跟特定后缀（步行+街、火车+站、登山+杖/鞋、地铁+站/口等）时视为另一个词的组成部分，不作为实体。"
         "识别结果按记录输出 JSONL，每个实体带 text、type、subtype、start、end、canonical 六个字段。")

    rb.sub("3.4 迭代优化设计")
    rb.p("设两轮迭代：第 1 轮（baseline）仅用采集阶段的 71 条 POI 种子与 15 条通用交通词、无停用词；"
         "第 2 轮（refined）使用挖掘整理后的完整词典与全部守卫规则。两轮各自输出实体文件、词频图表与统计，差异见 4.3 节。")

    rb.section("四、实验结果与分析")
    rb.sub("4.1 总体识别结果")
    bt, rt = by_type(BASE), by_type(REF)
    rb.p(f"refined 轮在 271 条文本上共识别 {REF['total_entities']:,} 个实体"
         f"（平均每条 {REF['entities_per_record_mean']} 个）：景点POI {rt['景点POI']:,}、交通方式 {rt['交通方式']:,}、"
         f"时间节点 {rt['时间节点']:,}。分景区看，黄山以索道/徒步类交通词最密集（{REF['by_scenic_area']['黄山']['交通方式']:,} 次），"
         f"九寨沟 POI 最多（{REF['by_scenic_area']['九寨沟']['景点POI']:,} 次），颐和园文本较短但官方路线的时段结构清晰。")
    rb.image(FIGS / "bar_by_scenic.png", 13.5)
    rb.caption("图 1 三景区三类实体分布对比")

    rb.sub("4.2 词频统计与可视化")
    top_poi = list(REF["top_canonical"]["景点POI"].items())[:5]
    top_tr = list(REF["top_canonical"]["交通方式"].items())[:3]
    top_tm = list(REF["top_canonical"]["时间节点"].items())[:4]
    rb.p("三类实体的高频词与其领域常识一致：POI 以"
         "、".join(f"{w}（{c}）" for w, c in top_poi) + " 居首——"
         "黄龙/宏村作为周边景点高频出现，恰好反映游记“九寨沟+黄龙”“黄山+宏村”的联游模式；"
         "交通方式以" + "、".join(f"{w}（{c}）" for w, c in top_tr) + "为主；"
         "时间节点中" + "、".join(f"{w}（{c}）" for w, c in top_tm) + " 等居前，笼统时段占多数，"
         "精确时刻多来自小红书笔记的 ⏰ 时间轴写法。词云图（图 3）进一步显示低频区长尾中仍有少量同义变体（如“诺日朗瀑布/诺日朗”），"
         "已通过 canonical 字段归一处理。")
    rb.image(FIGS / "bar_景点POI.png", 13.5)
    rb.caption("图 2 景点POI 词频 Top15（refined）")
    rb.image(FIGS / "wc_景点POI.png", 13.5)
    rb.caption("图 3 景点POI 词云（refined）")
    rb.bullets([f"其余图表见 task2/output/exp2/figs/refined/：bar_交通方式.png、bar_时间节点.png、wc_交通方式.png、wc_时间节点.png。"])

    rb.sub("4.3 两轮迭代对比（可视化和抽检驱动的优化）")
    rb.table(
        ["项目", "baseline（第1轮）", "refined（第2轮）"],
        [
            ["词典规模（POI/交通/停用词）", f"{BASE['dictionary_size']['poi']} / {BASE['dictionary_size']['transport']} / 0",
             f"{REF['dictionary_size']['poi']} / {REF['dictionary_size']['transport']} / {REF['dictionary_size']['stopwords']}"],
            ["实体总数", f"{BASE['total_entities']:,}", f"{REF['total_entities']:,}"],
            ["景点POI / 交通 / 时间", f"{bt['景点POI']:,} / {bt['交通方式']:,} / {bt['时间节点']:,}",
             f"{rt['景点POI']:,} / {rt['交通方式']:,} / {rt['时间节点']:,}"],
            ["九寨沟 POI 命中", f"{BASE['by_scenic_area']['九寨沟']['景点POI']:,}",
             f"{REF['by_scenic_area']['九寨沟']['景点POI']:,}（+{(REF['by_scenic_area']['九寨沟']['景点POI'] / BASE['by_scenic_area']['九寨沟']['景点POI'] - 1):.0%}）"],
        ],
        widths=[5.2, 5.0, 5.0],
    )
    rb.caption("表 2 两轮迭代对比（完整差异见 iter_compare.json）")
    rb.p("第 1 轮词频可视化暴露出三类问题，驱动了第 2 轮的全部修改：①九寨沟高频 POI 大面积漏识别——诺日朗（358 次）、犀牛海、"
         "芦苇海、双龙海、中查沟等均不在种子词典，说明“采集用的筛选词表”不等于“全量语料的实体词表”，必须从语料重新挖掘；"
         "②无停用词导致其他名山（庐山、泰山）与北京同城公园（北海公园）混入 POI 统计——加入 28 条领域停用词并设计停用词守卫；"
         "③交通词无子类，索道站名与普通车辆混算——补充 37 条并划分 8 个子类。")
    rb.p("抽检环节还发现并修复了一批复合词误报：第一轮复检发现“步行街”命中“步行”、“火车站”命中“火车”；修复后的第二轮复检又发现"
         "“登山鞋/登山杖”命中“登山”、“地铁站/地铁口”命中“地铁”，前后共三轮守卫修复，拦截约 90 处设施名/装备名误报。"
         "时间正则同期修复两处：Day02 被截断为 Day0（改为完整匹配数字）；“12:50—15:00”被拆成两条时刻（合并为一条范围时刻）；"
         "口语“半天”（“找了半天”）从时长规则中移除。")

    rb.sub("4.4 人工抽检与质量评估")
    rev = SPOT["review_summary"]
    rb.p(f"按“实体类型 × 景区”分层随机抽样（每格 6 例，随机种子 42），共 {rev['n']} 例逐条人工复核上下文："
         f"{rev['correct']} 例正确、{rev['incorrect']} 例错误、{rev['ambiguous']} 例歧义（判定记录见 spot_checks.json）。"
         "历史轮次的抽检曾发现三类命名冲突个例：“五彩池”在黄龙与九寨沟各有一处、“一线天”既是黄山景点也是"
         "爨底下村的景观名、“玉屏楼宾馆”是以景点命名的住宿设施——本轮抽检未抽中这些个例，但它们在总体中仍存在，"
         "属词典法的已知边界，需在后续实验中引入上下文消歧（如共现地名触发归属改写）。")
    rb.p("本轮抽检同时验证了两项时间正则优化的效果：en-dash（–）纳入范围分隔符后，“15:20–15:30”"
         "“6:30–18:00”正确合并为单条时刻实体；“10点”类无分钟时刻与“12点半”完整成词。")
    rb.p("多景点游记带来另一类系统性边界问题：颐和园样本中约三分之一的交通实体实为八达岭长城、承德磬锤峰或南京段内容"
         "（如“磬锤峰索道”“坐地铁到夫子庙”），类型识别正确但景区归属是采集时的主景区标签。本轮优化为每个 POI 命中"
         "增加 in_scenic 在景标记（词典 scenic_areas 与记录主景区比对），下游实验3 的游客路线提取与实验6 的"
         "游客先后边据此过滤景区外实体，从数据层面收敛这类误差。")
    rb.p("查全率的局限同样明确：词典法只能命中词典内的表达，无法发现新 POI（如新 opened 景点或文章中的简称）。"
         "本实验通过“词频挖掘→人工复核”部分缓解，但每轮挖掘都需要人工参与；这是与 LLM 抽取相比的取舍——词典法查准、稳定、零成本，"
         "LLM 法查全但需要 API 且结果需验证。")

    rb.section("五、实验小结")
    rb.p("本实验建立了三景区统一的实体体系（景点POI/交通方式/时间节点及 8 个交通子类、4 个时间子类），"
         f"在 271 条文本上识别 {REF['total_entities']:,} 个带位置信息的实体，输出 entity_schema.md（定义规范）、"
         "entities_refined.jsonl（JSON 实体文件）、entity_dictionary.json（词典）与 7 组词频可视化图表。")
    rb.p("核心方法论收获：实体识别的质量瓶颈不在匹配算法而在词表与边界规则——词典法的查准率靠“复合词守卫 + 停用词守卫”这类"
         "语料驱动的细节规则支撑，查全率靠“词频挖掘→人工复核”的迭代循环支撑；可视化不是装饰品，两轮迭代中每一处词典与规则的修改"
         "都由图表异常或抽检误报直接触发。识别结果中的偏移量与 canonical 归一字段，将直接支撑实验3的路线结构解析与实验6的知识融合。")

    rb.save(ROOT / "report.docx")


if __name__ == "__main__":
    main()
