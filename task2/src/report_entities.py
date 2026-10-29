"""Generate report 2 from current outputs and the version-comparison evidence."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "common"))
from report_utils import ReportBuilder
OUT = REPO / "task2/output/exp2"


def main():
    read = lambda name: json.loads((OUT / name).read_text(encoding="utf-8"))
    base, final = (read(f"entity_stats_{it}.json") for it in ("baseline", "refined"))
    review = read("spot_checks.json")["review_summary"]
    metrics = {m: json.loads((REPO / f"review/merge_20261029/{m}_cases.json").read_text(encoding="utf-8"))["summary"]
               for m in ("local", "cloud", "merged")}
    types = ("景点POI", "交通方式", "时间节点")
    total = lambda stats, kind: sum(row.get(kind, 0) for row in stats["by_scenic_area"].values())
    rb = ReportBuilder("数据挖掘探索性实验报告", "实验项目2 游览步骤的实体识别")
    rb.section("一、实验目的与输入口径")
    rb.p(f"从实验1保留的 {final['records']} 条主语料识别景点POI、交通方式和时间表达，形成定义规范表、带字符位置的JSON和词频图表。"
         "整合两份实现后，保留本地领域词典、跨景区标记及实验3至7的逐记录接口，吸收云端的模块化规则、配置、输入哈希校验和未知景区兜底。")
    rb.p("本报告按主语料逐文档统计。配置接口另外处理游客、官方路线分支及支撑文档：analysis仅含游客和官方分支，all也包含支撑文档。"
         "官方文章与从中拆出的分支不属于同一统计层级，配置接口的实体总数不与本报告直接比较。")
    rb.section("二、实体定义与整合方法")
    rb.table(["类型", "边界与处理", "示例"], [
        ["景点POI", "具名游览对象；主接口排除根景区；跨景区提及标记in_scenic", "光明顶、五花海、十七孔桥"],
        ["交通方式", "方式或具名交通设施；排除票务、泛称站点和复合词；最长区间优先", "云谷索道、观光车、步行"],
        ["时间表达", "时刻、区间、时段、日期、相对日等；时长单列且不计作时间节点", "下午三点半、次日、三小时"],
    ], widths=[2.0, 8.5, 4.2], font_size=10)
    rb.caption("表 1 核心实体边界 完整子类见entity_schema.md及resources/entity_definition.csv")
    rb.p("采用jieba及自定义词典。主接口在domain_seed.json基础上补入CSV词表，保留原有canonical与周边景点边界。"
         "POI和交通候选按起点、长度和优先级消除重叠，TimeRules识别中文时间和区间。写出前逐条断言clean_content[start:end]等于实体原文，位置为Unicode码点的左闭右开区间。")
    rb.p("修正云端交通语境窗口的误过滤：排除后缀必须紧贴实体，前置否定也必须与方式直接相邻。"
         "“坐高铁，站在窗边”保留高铁，“酒店不在附近步行要40分钟”保留步行；“高铁站、步行街、登山杖、索道票”继续排除。"
         "具名索道的上站和下站作为设施提及保留，西海小火车取完整交通名称。")
    rb.p("地点别名统一读取resources/poi_aliases.csv，实体、路线与图谱共用common/entity_identity.py。"
         "耕织图景区归并到耕织图，树正磨坊归并到树正磨房；发现一个别名多目标或映射成环即报错。"
         "映射限定景区，不用字符串相似度自动合并对象；北海宾馆与北海仍区分，同名异点仍需语境消歧。")
    rb.section("三、词典迭代与词频结果")
    rows = [["主语料记录数", base["records"], final["records"]],
            ["POI词表项", base["dictionary_size"]["poi"], final["dictionary_size"]["poi"]],
            ["交通词表项", base["dictionary_size"]["transport"], final["dictionary_size"]["transport"]],
            ["领域停用词", base["dictionary_size"]["stopwords"], final["dictionary_size"]["stopwords"]]]
    rows += [[kind, total(base, kind), total(final, kind)] for kind in types]
    rows += [["实体合计", base["total_entities"], final["total_entities"]]]
    rb.table(["指标", "baseline", "refined"], rows, widths=[5.1, 4.8, 4.8])
    rb.caption("表 2 同一批文本的词典迭代 两轮均使用整合后的时间和交通规则")
    rb.p("baseline采用采集阶段种子词典，refined补充领域词典、别名和停用词。新增实体数只表示覆盖扩大，不等于准确率上升。"
         "两轮均已替换时间规则，因此不把本轮baseline与历史baseline直接比较来宣称优化效果。")
    rb.image(OUT / "figs/refined/bar_by_scenic.png", 14.5)
    rb.caption("图 1 分景区的三类实体分布 时间表达总数含时长子类")
    rb.table(["类型", "前五项规范名及次数"], [
        [kind, "；".join(f"{name} {count}" for name, count in list(final["top_canonical"][kind].items())[:5])]
        for kind in types], widths=[2.5, 12.2], font_size=10)
    rb.caption("表 3 高频项 完整三类柱状图与词云见figs/baseline及figs/refined")
    rb.p("依据高频项审阅复合词与设施名误报，保留本地的步行街、登山装备和地铁口守卫，并加入云端票务、站点和停运语境规则。"
         "规范名在聚合前统一；具名交通设施优先于内部地名，防止西海小火车被重复统计为西海POI和小火车。")
    rb.section("四、版本对照与质量检查")
    rb.table(["实现", "案例通过", "区间P", "区间R", "F1"], [
        [label, f"{metrics[m]['passed']}/{metrics[m]['cases']}", f"{metrics[m]['precision']:.1%}",
         f"{metrics[m]['recall']:.1%}", f"{metrics[m]['f1']:.3f}"]
        for m, label in [("local", "本地原版"), ("cloud", "云端原版"), ("merged", "整合版")]
    ], widths=[3.0, 3.1, 2.9, 2.9, 2.8], font_size=10)
    for row in rb.doc.tables[-1].rows[:-1]:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.keep_with_next = True
    rb.caption("表 4 同一组34个边界回归案例的精确区间对照")
    rb.p("案例覆盖中文时间、区间、票务、站点、具名索道、复合词及跨景区提及，定义于本次代码审核并用于规则修正。"
         "这是开发回归证据，不是独立测试集，不代表整批语料准确率。原始案例、逐项误报漏报及复现方式见review/merge_20261029。")
    rb.p(f"历史分层抽样共 {review['historical_sample_count']} 例，按文档ID、类型、原文及起止位置对齐，本轮仍存在 {review['n']} 例，"
         f"继承判定为 {review['correct']} 正确、{review['ambiguous']} 歧义、{review['incorrect']} 错误；另 {review['removed_or_changed']} 例被规则替换。"
         "被替换的西海片段现归入西海小火车整体交通实体。本轮没有重新随机抽样，新增实体尚待独立人工评估，不把继承标签的比例当作总体精度。")
    rb.section("五、下游影响与复现")
    rb.p("共指消解增加仅用于上下文的明确设施位置线索，例如“北海宾馆附近”；这种推断不进入POI词频或路线。"
         "时间分配改用规范化时刻并支持区间，避免把下午三点按3点归到夜间。实验3、4、6、7已重跑，相关报告由当前JSON重新生成。")
    rb.p("主报告复现：仓库根目录运行python common/run_pipeline.py --reports。单步识别：python task2/src/extract_entities.py --iteration baseline或refined。"
         "逐记录产物位于task2/output/exp2，供实验3至7读取。依赖包括jieba、matplotlib、wordcloud、networkx、pyvis和python-docx等。")
    rb.p("配置接口复现：运行task2/run_task2.ps1，从主语料适配并冻结输入，执行iter1和iter2、统计、图表、QC和哈希清单，产物位于task2/outputs。"
         "该接口支持来源字段映射和未知景区低置信兜底，两种接口的输入范围与统计口径详见task2/README.md。")
    rb.p("局限包括未登录地点、同名异点以及主景区标签与句子叙述地点不一致。下一步应建立独立双人标注集，分别评估景区内、周边与未知景区，"
         "并将稳定地点ID作为别名与图谱的关联键，减少名称变化对接口的影响。")
    rb.save(REPO / "task2/report.docx")


if __name__ == "__main__":
    main()
