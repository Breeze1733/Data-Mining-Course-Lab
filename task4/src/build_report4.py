"""生成实验项目4报告：程序性知识的共指消解（task4/report.docx）。

数字实时读取 task4/output/ 下的检测、标注与评估文件。运行：python src/build_report4.py（-X utf8）
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
from report_utils import ReportBuilder

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
FIGS = OUT / "figs"

EVAL = json.loads((OUT / "evaluation.json").read_text(encoding="utf-8"))
GOLD = json.loads((OUT / "annotation_gold.json").read_text(encoding="utf-8"))
EXAMPLES = json.loads((OUT / "resolved_examples.json").read_text(encoding="utf-8"))
CASES = [json.loads(l) for l in (OUT / "pronoun_cases.jsonl").open(encoding="utf-8")]

# v1 规则在同一批人工标注上的准确率（annotation_gold 保存了 v1 预测）
CANON = {"POI": "POI", "交通": "交通", "景区名": "景区", "他人": "他人", "同行者": "同行者",
         "名词集合": "集合-其他", "前文POI集合": "集合-POI", "无明确先行词": "无"}


def v1_accuracy() -> float:
    ok = 0
    for g in GOLD["annotations"]:
        kind = CANON.get(g["rule_kind"])
        km = kind == g["gold_kind"]
        nm = g["rule_resolution"] == g["gold_antecedent"] if g["gold_kind"] in ("POI", "景区") else True
        ok += bool(km and nm)
    return ok / len(GOLD["annotations"])


def main():
    rb = ReportBuilder("《数据挖掘》探索性实验报告", "—实验项目4 程序性知识的共指消解")

    rb.section("一、实验目的与任务")
    rb.p("游记文本大量使用“它、这里、那里、他们、其中”等代词回指前文实体，直接抽取会把指代错当实体。"
         "本实验从 249 篇游记中检测全部代词及所在句（记录文档级偏移，避免同句多个相同代词错配），"
         "实现基于规则的指代消解（POI 优先 + 距离约束 + 语义类别分流），人工标注 120 例作为评测集，"
         "统计准确率、分析典型错误并迭代改进规则，输出消解后的文本示例。")

    rb.section("二、实验环境")
    rb.bullets([
        "Windows 11；Python 3.13（task1/.venv）；jieba（词性标注，用于“其中”类先行词 noun 探测）。",
        "输入：task1/data/processed/dataset_clean.jsonl（249 篇游记）、task2/output/exp2/entities_refined.jsonl（实体及位置）。",
        "运行入口：task4/src/{detect_and_resolve, annotate_sample, build_report4}.py。",
    ])

    rb.section("三、实验设计与实现")
    rb.sub("3.1 代词检测与待消解样本构建")
    rb.p(f"按句号/问叹号/分号/换行分句，检测 12 类代词，共 {len(CASES):,} 处（覆盖 177 篇游记）。"
         "每条记录包含：代词、语义类别、文档级与句内位置、所在句、前两句原文、候选实体池。"
         "同句出现多个相同代词时按各自字符偏移独立成案，杜绝错配。")
    cls_counter = Counter(c["pronoun_class"] for c in CASES)
    rb.table(["语义类别", "代词", "检测数", "消解策略"],
             [["处所类", "这里/那里/那边/此处", f"{cls_counter['locative']:,}", "最近 POI > 交通实体 > 前句 POI > 景区名回退"],
              ["物体类", "它/它们/这条/这座/该景点", f"{cls_counter['object']:,}", "同处所类策略（POI 优先）"],
              ["人称类", "他们/她们", f"{cls_counter['person']:,}", "同行者/他人二分（角色词 + 第一人称信号）"],
              ["集合类", "其中", f"{cls_counter['set']:,}", "jieba 最近普通名词（部分格结构）"]],
             widths=[1.8, 4.4, 1.8, 7.0])
    rb.caption("表 1 代词的语义类别与消解策略")

    rb.sub("3.2 规则消解方法")
    rb.p("处所/物体类候选打分：同句代词前实体 > 前句实体 > 前两句窗口；同类内 POI 优先于交通实体；距离近优先；"
         "窗口内无实体时回退到景区名（显式标记为低置信）。人称类结合两类信号：句中/前句出现角色词"
         "（挑山工、导游、前台、店主等 20+ 词）且无第一人称同行信号（我们/我妈/媳妇/同伴…）时判“他人”，否则默认“同行者”。"
         "集合类针对“其中”的部分格本质——先行词多为普通名词集合（“6顿餐”“72座峰”“五种冰川地貌”），"
         "POI 词典无法覆盖，改用 jieba 词性标注取代词前最近的普通名词。")

    rb.p("消解候选前置过滤——句级归属过滤默认开启（--no-attribution-filter 可关）：由特征规则判定每句的"
         "叙述焦点（景区专名命中 +3/次；联游景区/城市地标/住宿餐饮/往返大交通等景区外信号 +2/次；"
         "索道/观光车/门票等园内基础设施 +1 仅证明在园内；转移词“接着/然后/下一站/回到”在无专名冲突时"
         "继承前句标签），景区外句子中的实体不进入消解候选。权重在 495 句标注集上按 seed=42 对半分迭代"
         "（tune 半区调参、holdout 半区仅一次评估，无泄漏），实验5 的条件抽取同样采用该过滤。")

    rb.p("本轮上游改动后复跑，公共别名表统一耕织图景区与耕织图；对北海宾馆附近等明确位置短语，仅向共指候选补入地点线索，不作为POI实体或图谱同一对象。该处理避免了设施过滤对局部指代线索的损伤。")

    rb.sub("3.3 人工标注")
    rb.p(f"沿用seed=42按“代词类别×景区”每格10例生成的{EVAL['n']}例历史标注。字段为gold_antecedent、gold_kind和备注，"
         "类别区分POI、景区、设施、人称、集合等。多景点游记按实际所指标注，省略或诗化指代单列为无明确先行词。"
         "完整标签见annotation_gold.json；复测先核验文档ID、代词及起止位置，不重新抽样或重填金标准。")

    rb.section("四、实验结果与分析")
    rb.sub("4.1 消解准确率与两轮迭代")
    rb.p(f"第 1 版规则在同一批标注上的总体准确率为 {v1_accuracy():.1%}；标注暴露的系统性问题促成第 2 版规则："
         f"①“其中”类 0/30 全错——部分格先行词根本不是 POI，改用 jieba 最近普通名词后提升至 "
         f"{EVAL['accuracy_by_class']['set']['accuracy']:.0%}；②人称类默认“同行者”错杀服务场景，"
         f"扩充角色词表并要求“无同行者信号”双条件后，他人/同行者混淆减少。"
         f"第 2 版总体准确率 {EVAL['accuracy_overall']:.1%}。")
    rows = [["处所类", str(EVAL["accuracy_by_class"]["locative"]["n"]), f'{EVAL["accuracy_by_class"]["locative"]["accuracy"]:.0%}'],
            ["物体类", str(EVAL["accuracy_by_class"]["object"]["n"]), f'{EVAL["accuracy_by_class"]["object"]["accuracy"]:.0%}'],
            ["人称类", str(EVAL["accuracy_by_class"]["person"]["n"]), f'{EVAL["accuracy_by_class"]["person"]["accuracy"]:.0%}'],
            ["集合类", str(EVAL["accuracy_by_class"]["set"]["n"]), f'{EVAL["accuracy_by_class"]["set"]["accuracy"]:.0%}'],
            ["总体", str(EVAL["n"]), f'{EVAL["accuracy_overall"]:.1%}']]
    rb.table(["代词类别", "标注数", "准确率（v2）"], rows, widths=[4.0, 3.0, 3.0])
    rb.caption("表 2 规则消解准确率（120 例人工标注；v1 总体 27.5%，集合类 0/30）")
    rb.image(FIGS / "coref_evaluation.png", 14.5)
    rb.caption("图 1 分类别准确率与标注样本的代词分布")

    rb.sub("4.2 典型错误与归因")
    rb.p(f"{len(EVAL['errors'])} 个错误案例呈现四类系统性模式（全部案例见 evaluation.json）：")
    rb.bullets([
        "多景点游记漂移（占错误的最大比例）：评测样本中约三分之一的“这里/那里”实指磁器口、景山公园、清华北大、"
        "金山岭长城等景区外地点——采集时的主景区标签不等于句子级叙述焦点，规则只能在景区内实体池里选，"
        "天然选不出“景区外正确答案”；",
        "先行词不在实体体系内：这条路线/这条路/祠堂/五步蛇/老别墅——路线与普通名词先行词没有实体表示，"
        "POI 优先策略必然错配；",
        "后置命名与同句劫持：“这座楼阁于乾隆二十五年竣工，名为佛香阁”的先行词在代词之后；"
        "“清晏舫俗称石舫，在长廊西端湖边，它的前身…”中同句“长廊”按距离劫持了句首主语“清晏舫”；",
        "人称的语境依赖：“叫他们端回去”（店家）、“替他们捏把汗”（同行者）表面上无法从窗口词面区分，"
        "需要叙事角色追踪。",
    ])

    rb.sub("4.3 消解后的文本示例")
    rows = [[e["pronoun"], e["antecedent"], e["after"][:80]] for e in EXAMPLES[:5]]
    rb.table(["代词", "消解为", "消解后句子（节选，【】标出替换位置）"], rows, widths=[1.5, 2.5, 11.0], font_size=9)
    rb.caption("表 3 规则消解正确的文本改写示例（完整 6 例见 resolved_examples.json）")
    rb.p("正确案例集中在“前句明确提及单个 POI、代词紧跟其后”的句式（如“过了黄龙寺就看到了五彩池，已经有很多人在那里了”）；"
         "这印证了规则法的适用边界——局部、单候选、强邻接的指代。")

    rb.sub("4.4 方法局限与改进方向")
    rb.bullets([
        f"规则法只利用了局部窗口的词面信息，{EVAL['accuracy_overall']:.1%} 的准确率说明旅游游记的指代远比“最近名词”复杂；",
        "最直接的改进是篇章级叙述焦点追踪：为每篇游记维护“当前叙述地点”状态机（随行程推进更新），"
        "处所类代词优先指向焦点而非最近实体，可同时解决多景点漂移与景区名误回退两类错误；",
        "集合类需要普通名词的概念层表示（“6顿餐”“72座峰”），纯词典路线不可行，"
        "更适合用 LLM 做受限抽取（只判定先行词类别与指称，不让它自由生成）；",
        "标注参考了规则输出（未做严格盲标），gold 以语义判断为准，但个别边界案例（如诗化指代）存在主观性。",
    ])

    rb.section("五、实验小结")
    rb.p(f"本实验构建了完整的共指消解流程：1940 处代词检测（带偏移与候选池）→ 规则消解（POI 优先 + 距离约束 + 语义分流）→ "
         f"120 例人工标注 → 两轮规则迭代 → 误差分类分析。总体准确率从 v1 的 27.5% 提升到 v2 的 {EVAL['accuracy_overall']:.1%}，"
         "但结果坦诚地表明：窗口级规则在多景点游记上的消解能力有限，“景区外指代”与“普通名词先行词”是两类结构性难题。"
         "本轮产出的标注集与误差分类可直接用于实验7 的 LLM 消解对比实验；消解后的（po）文本改写示例验证了输出链路的可用性。")

    rb.save(ROOT / "report.docx")


if __name__ == "__main__":
    main()
