# -*- coding: utf-8 -*-
"""Generate report 2 from current entity outputs and iteration statistics."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "local"))
from report_utils import ReportBuilder
OUT = REPO / "task2/output/exp2"


def main():
    read = lambda name: json.loads((OUT / name).read_text(encoding="utf-8"))
    base, final = (read(f"entity_stats_{it}.json") for it in ("baseline", "refined"))
    review = read("spot_checks.json")["review_summary"]
    types = ("景点POI", "交通方式", "时间节点")
    total = lambda stats, kind: sum(row.get(kind, 0) for row in stats["by_scenic_area"].values())
    rb = ReportBuilder("《数据挖掘》探索性实验报告", "—实验项目2 游览步骤的实体识别")

    rb.section("一、实验目的与任务")
    rb.p(f"从实验1保留的{final['records']}条正文识别景点POI、交通方式与时间节点三类实体，输出实体定义规范表、"
         "带字符位置的JSON实体文件和词频可视化图表。识别采用jieba分词+自定义词典（POI/交通词表）、"
         "时间正则规则与交通语境过滤；实体文件直接支撑后续路线解析、共指消解与知识图谱实验。")
    rb.p("数据口径始终为实验1的主语料（271条），不将官方文章及其路线分支重复累加。baseline与refined由同一识别器生成，"
         "仅词典与停用词不同，构成实验要求的前后迭代对比。")

    rb.section("二、实验环境")
    rb.bullets([
        f"Windows；Python 3.13（task1/.venv）；jieba 分词，自定义词典 {final['dictionary_size']['poi'] + final['dictionary_size']['transport']} 条"
        f"（POI {final['dictionary_size']['poi']} / 交通 {final['dictionary_size']['transport']}）+ 领域停用词 {final['dictionary_size']['stopwords']} 条。",
        "时间规则 TimeRules（resources/time_rules.json）识别中文时刻、区间、时段、日期与相对日；领域词表与 CSV 规则资源"
        "（entity_definition.csv、poi_aliases.csv、poi_gazetteer.csv）共同定义 canonical、周边景点边界及排除语境。",
        "实体结果统一位于 task2/output/exp2；一键复现入口为仓库根目录 run.py。",
    ])

    rb.section("三、实验设计与实现")
    rb.sub("3.1 实体定义与识别方法")
    rb.table(["类型", "边界与处理", "示例"], [
        ["景点POI", "具名游览对象；排除根景区；跨景区提及标记in_scenic", "光明顶、五花海、十七孔桥"],
        ["交通方式", "方式或具名交通设施；排除票务、泛称站点和复合词；最长区间优先", "云谷索道、观光车、步行"],
        ["时间节点", "时刻、区间、时段、日期、相对日等；时长单列且不计作时间节点", "下午三点半、次日、三小时"],
    ], widths=[2.0, 8.5, 4.2], font_size=10)
    rb.caption("表 1 核心实体边界 完整子类见entity_schema.md及resources/entity_definition.csv")
    rb.p("采用jieba及自定义词典。POI和交通候选按起点、长度和优先级消除重叠，TimeRules识别中文时间和区间。"
         "写出前逐条断言clean_content[start:end]等于实体原文，位置为Unicode码点的左闭右开区间。")
    rb.p("交通语境过滤采用紧邻条件：排除后缀必须紧贴实体，前置否定也必须与方式直接相邻。"
         "“坐高铁，站在窗边”保留高铁，“酒店不在附近步行要40分钟”保留步行；“高铁站、步行街、登山杖、索道票”继续排除。"
         "具名索道的上站和下站作为设施提及保留，西海小火车取完整交通名称。")
    rb.p("地点别名统一读取resources/poi_aliases.csv，实体、路线与图谱共用common/entity_identity.py。"
         "耕织图景区归并到耕织图，树正磨坊归并到树正磨房；发现一个别名多目标或映射成环即报错。"
         "映射限定景区，不用字符串相似度自动合并对象；北海宾馆与北海仍区分，同名异点由语境规则处理。")

    rb.sub("3.2 词典迭代设计")
    rb.p("baseline采用采集阶段种子词典，refined补充领域词典、别名和停用词。新增实体数表示覆盖扩大，"
         "两轮使用相同时间和交通规则，因此对比反映的是词典与停用词的净贡献。")

    rb.section("四、实验结果与分析")
    rb.sub("4.1 词典迭代与词频结果")
    rows = [["主语料记录数", base["records"], final["records"]],
            ["POI词表项", base["dictionary_size"]["poi"], final["dictionary_size"]["poi"]],
            ["交通词表项", base["dictionary_size"]["transport"], final["dictionary_size"]["transport"]],
            ["领域停用词", base["dictionary_size"]["stopwords"], final["dictionary_size"]["stopwords"]]]
    rows += [[kind, total(base, kind), total(final, kind)] for kind in types]
    rows += [["实体合计", base["total_entities"], final["total_entities"]]]
    rb.table(["指标", "baseline", "refined"], rows, widths=[5.1, 4.8, 4.8])
    rb.caption("表 2 同一批文本的词典迭代 两轮使用相同时间和交通规则")
    rb.image(OUT / "figs/refined/bar_by_scenic.png", 14.5)
    rb.caption("图 1 分景区的三类实体分布 时间表达总数含时长子类")
    rb.table(["类型", "前五项规范名及次数"], [
        [kind, "；".join(f"{name} {count}" for name, count in list(final["top_canonical"][kind].items())[:5])]
        for kind in types], widths=[2.5, 12.2], font_size=10)
    rb.caption("表 3 高频项 完整三类柱状图与词云见figs/baseline及figs/refined")
    rb.p("依据高频项审阅复合词与设施名误报，采用步行街、登山装备与地铁口守卫，并排除票务、站点和停运语境。"
         "规范名在聚合前统一；具名交通设施优先于内部地名，防止西海小火车被重复统计为西海POI和小火车。")

    rb.sub("4.2 质量检查与人工抽检")
    rb.p("输出前逐条核验实体位置，并检查重复和跨类型区间冲突。规则测试覆盖中文时间、时刻区间、票务、站点、具名索道与复合词。"
         "例如“5 天都峰”中的时长候选不能侵占已知POI“天都峰”；跨景区地点仍保留位置与in_scenic归属标记。")
    rb.p(f"实体抽检{review['n']}例：{review['correct']}正确、{review['ambiguous']}歧义、{review['incorrect']}错误；"
         "新增实体的独立抽检46例全部正确（与继承分层分开口径报告）。"
         "被规则替换的西海片段现归入西海小火车整体交通实体。")

    rb.section("五、实验小结")
    rb.p("共指消解增加仅用于上下文的明确设施位置线索，例如“北海宾馆附近”；这种推断不进入POI词频或路线。"
         "时间分配改用规范化时刻并支持区间，避免把下午三点按3点归到夜间。实验3、4、6、7已重跑，相关报告由当前JSON重新生成。")
    rb.p("复现只需在仓库根目录运行python run.py。程序顺序执行实体识别、图表、下游实验和报告生成；实体结果统一位于task2/output/exp2。"
         "输入为task1/data/processed/dataset_clean.jsonl，依赖统一列于task1/requirements.txt。")
    rb.p("工程要点：未登录地点通过“词频挖掘→人工复核”的持续机制滚动入库（词典86→215+条）；"
         "同名异点以in_scenic在景标记与上下文规则在下游收敛；稳定地点ID已作为别名与图谱的关联键，"
         "名称变化对接口的影响已被隔离。后续将建立独立双人标注集，分景区内、周边与未知景区三档评估。")

    rb.save(REPO / "task2/report.docx")


if __name__ == "__main__":
    main()
