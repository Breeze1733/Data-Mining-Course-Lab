"""生成实验项目3报告：游览路线的层级结构挖掘（task3/report.docx）。

数字实时读取 task3/output/ 下的解析与对比文件。运行：python src/build_report3.py（在 task1 venv 内，-X utf8）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
from report_utils import ReportBuilder

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
FIGS = OUT / "figs"

PARSED = [json.loads(l) for l in (OUT / "parsed_routes.jsonl").open(encoding="utf-8")]
FMT = json.loads((OUT / "route_format_analysis.json").read_text(encoding="utf-8"))
CMP = json.loads((OUT / "official_vs_tourist.json").read_text(encoding="utf-8"))["by_scenic_area"]
HIER = json.loads((OUT / "time_hierarchy_summary.json").read_text(encoding="utf-8"))
ORDERED = [p for p in PARSED if p["ordered_route"]]

PERIODS = ("上午", "中午", "下午", "晚上")


def main():
    rb = ReportBuilder("《数据挖掘》探索性实验报告", "—实验项目3 游览路线的层级结构挖掘")

    rb.section("一、实验目的与任务")
    rb.p("在实验1、2 的基础上挖掘游览路线的层次结构：分析官方推荐路线的文本描述格式规律，设计解析规则，"
         "把每条路线转换为统一的步骤化结构表示；构建以时间（上午/中午/下午/晚上）为维度的游览层级；"
         "进一步提取游客游记中的实际路线，与官方路线做覆盖度、顺序一致性、时间分配三个维度的量化对比，并分析差异原因。")

    rb.section("二、实验环境")
    rb.bullets([
        "Windows 11；Python 3.13（task1/.venv）；matplotlib 绘图。",
        "输入：task1/data/raw/official_routes.jsonl（46 条官方路线分支）、task2/output/exp2/（实体词典与实体输出）。",
        "运行入口：task3/src/{parse_routes, compare_routes, build_hierarchy_view, build_report3}.py。",
    ])

    rb.section("三、实验设计与实现")
    rb.sub("3.1 官方路线的格式规律分析")
    rb.p(f"对 {FMT['total_routes']} 条官方路线分支（{FMT['ordered_routes']} 条有序 + 7 条主题方案）逐条归纳描述模式，"
         "发现六种格式（表 1）。共性规律：①九寨沟官方文本是“日程表”形态——【上午】【中午】【下午】时段标记 + "
         "“A→B（时间范围 交通方式，时长）”的链式行；②黄山与颐和园官方文本是“节点链”形态——只有景点先后顺序，"
         "不携带时段与时长，时间安排完全留给游客；③标注风格多样：箭头（→）、破折号（—/──）、“第一站：”编号、"
         "“活动路线：”键值字段并存。")
    scenic_format_desc = {
        ("九寨沟", "arrow_chain"): "时段标记 + “A→B（7:00-8:10 观光车，约10分钟）”链式行，信息最完整",
        ("九寨沟", "kv_route_line"): "“活动路线：双龙海—芦苇海—盆景滩”键值字段 + 活动时长",
        ("九寨沟", "prose"): "叙述式：健康游/研学游线路，节点以引号或“从…至…”出现",
        ("九寨沟", "theme_prose"): "无固定顺序的季节/人群主题方案（银发游、亲子游等）",
        ("颐和园", "arrow_chain"): "短节点链（西门→畅观堂→镜桥沿线→…），无时间信息",
        ("颐和园", "numbered_list"): "阿拉伯数字编号列表（1.东宫门--仁寿殿--…）",
        ("颐和园", "numbered_stops"): "“第一站：…”站点列表，附花卉/消费推荐",
        ("颐和园", "prose"): "叙述式（由东宫门入园，至乐寿堂区域）",
        ("黄山", "arrow_chain"): "FAQ 方案的破折号链 + 括号注记（步行/午饭/夜宿），二日游带【第X日】标记",
    }
    rows = [[k.split("/")[0], k.split("/")[1], v, scenic_format_desc[tuple(k.split("/"))]]
            for k, v in FMT["format_counts"].items()]
    rb.table(["景区", "格式", "条数", "特征"], rows, widths=[1.8, 3.0, 1.3, 8.6], font_size=9)
    rb.caption("表 1 官方路线的六种描述格式（arrow_chain=箭头链，theme_prose=无固定顺序主题方案）")

    rb.sub("3.2 统一的结构化表示与解析规则")
    rb.p("每条路线解析为统一 schema：route_id、景区、格式、步骤列表；每个步骤含 step_no、day、period、"
         "原文、POI（归一化后）、交通方式、时间范围、时长、备注、住宿标记。解析规则按格式分层：")
    rb.bullets([
        "链式行：按 →/—/─ 等分隔符切分节点；括号内的信息（7:00-8:10、步行30分钟、夜宿）解析为时间/时长/交通/住宿属性；",
        "标记行：【第X日】【上午】等标记逐段识别（黄山“…—【第二日】丹霞峰…”的天数标记出现在链中间，必须段级处理）；",
        "“第X站：”编号列表与“活动路线：”键值字段各设专用分支；",
        "散文式路线：先分句再逐句解析，含 POI 的句子保留为步骤；",
        "链式连接点去重：仅有单个 POI 且与上一步末尾 POI 相同、无任何附加信息的段是链条的“回头引用”，不重复计步；",
        "纯开场白过滤：箭头链格式下无 POI、无时间的引导句（“由于一天时间相对紧凑…”）不算步骤。",
    ])
    rb.p(f"解析结果：39 条有序路线全部得到步骤（平均 {sum(p['step_count'] for p in ORDERED) / len(ORDERED):.1f} 步/条），"
         "7 条无固定顺序的主题方案解析为 POI 集合并单独标记（ordered_route=false），不冒充有序路线。")

    rb.sub("3.3 名称归一化与噪声处理")
    rb.p("公共别名表poi_aliases.csv与common/entity_identity.py统一供实验2、3、6使用，校验别名冲突与映射环。三层规则处理名称不一致问题：①词典 canonical 映射（清晏舫→石舫、诺日朗游客中心→诺日朗中心、玉屏→玉屏景区），"
         "映射表随词典文件提交；②地理限定语剥离（黄山南大门→南大门、XX风景区→XX）；③同名异点保护——"
         "五彩池（九寨沟/黄龙各一）、北海（黄山北海景区/北京北海公园）不跨景区合并，北海公园由实验2的停用词守卫拦截。"
         "归一化示例与应用统计见 name_normalization.json。已知的边界：简称与代词（“大峡谷”指西海大峡谷、“那里”指某景点）"
         "依赖上下文，本实验不做跨句合并，留给实验4 共指消解处理。")

    rb.sub("3.4 时间维度层级构建")
    rb.p("时段的确定按三级优先级：①文本显式标记（【上午】/上午：）；②时钟范围起点推断（5-11 点→上午、11-13→中午、"
         "13-18→下午、18-24→晚上）；③前向继承（未标注步骤沿用上一个已确定时段）。由此构建“天 → 时段 → 步骤”"
         "三层层级。游客文本另使用规范化时刻与时刻区间的起点归属四大时段，避免下午三点被当作凌晨3点；时长不参与时段分配。构建后输出结构树图（图 1–2；颐和园官方路线无任何时间信息，层级退化为单层节点链，不单独展示）。")
    rb.image(FIGS / "tree_JZG-EXP01-R1.png", 15.2)
    rb.caption("图 1 九寨沟“一日精华游”的时间层级（时段标记 + 时钟范围，层级最完整）")
    rb.image(FIGS / "tree_HS-O1-R8.png", 15.2)
    rb.caption("图 2 黄山“南门二日游”的时间层级（天级结构完整；时段无官方标注，层级止于“未标注时段”）")

    rb.sub("3.5 游客实际路线提取与对比方法")
    rb.p(f"游客路线来自实验2实体输出的阅读顺序：每篇游记取景区内 POI 序列（连续重复去重），保留 ≥4 个不同 POI 的记录，"
         f"共得到 {sum(d['n_tourist_routes'] for d in CMP.values())} 条游客路线"
         f"（九寨沟 {CMP['九寨沟']['n_tourist_routes']}、颐和园 {CMP['颐和园']['n_tourist_routes']}、黄山 {CMP['黄山']['n_tourist_routes']}）。"
         "对比指标：①景点覆盖度——游客路线与官方 POI 全集的交集占官方全集比例（辅以 Jaccard）；"
         "②顺序一致性——公共 POI ≥5 时计算游客序列与最佳匹配官方序列的 Kendall tau（对每条官方路线分别计算取最大，"
         "以兼容“官方多版本路线”的现实）；③时间分配——官方按步骤时长累计的时段占比 vs 游客文本时段词/时刻落点的时段占比。")

    rb.section("四、实验结果与分析")
    rb.sub("4.1 覆盖度与顺序一致性")
    rows = [[a, d["n_official_routes"], d["n_official_pois"], d["n_tourist_routes"],
             d["coverage_mean"], d["jaccard_mean"],
             d["order_tau_mean"], d["n_order_pairs"]] for a, d in CMP.items()]
    rb.table(["景区", "官方路线", "官方POI", "游客路线", "覆盖度", "Jaccard", "顺序tau", "tau样本数"],
             rows, widths=[2.0, 1.9, 1.8, 1.9, 1.8, 1.8, 1.8, 1.9])
    rb.caption("表 2 官方/游客路线三景区对比总览")
    rb.image(FIGS / "compare_coverage_order.png", 15.0)
    rb.caption("图 3 游客路线对官方景点的覆盖度与顺序一致性")

    rb.sub("4.2 时间分配对比")
    rb.image(FIGS / "compare_time_allocation.png", 15.0)
    rb.caption("图 4 官方路线与游客文本的时间分配（颐和园/黄山官方路线无时段信息，仅展示游客分布）")
    jt = CMP["九寨沟"]
    rb.p(f"只有九寨沟官方路线携带可量化的时段信息：官方为上午 {jt['official_time_allocation_pct']['上午']:.0%}、"
         f"中午 {jt['official_time_allocation_pct']['中午']:.0%}、下午 {jt['official_time_allocation_pct']['下午']:.0%}、晚上 0%；"
         f"游客文本为上午 {jt['tourist_time_allocation_pct']['上午']:.0%}、中午 {jt['tourist_time_allocation_pct']['中午']:.0%}、"
         f"下午 {jt['tourist_time_allocation_pct']['下午']:.0%}、晚上 {jt['tourist_time_allocation_pct']['晚上']:.0%}。"
         f"最显著的差异在“晚上”：官方路线止于 17:35 出沟，游客文本 {jt['tourist_time_allocation_pct']['晚上']:.0%} 的时间表达落在夜间——"
         "《藏谜》演出、镇上晚餐、酒店休整这些“游后安排”是官方指南的空白区。")

    rb.sub("4.3 差异原因分析")
    cov_lo = min(d["coverage_mean"] for d in CMP.values())
    cov_hi = max(d["coverage_mean"] for d in CMP.values())
    rb.p(f"覆盖度（{cov_lo:.2f}–{cov_hi:.2f}）：游客游记通常只覆盖景区的代表性子集，且周边联游分流明显——九寨沟游客文本中的黄龙、"
         "黄龙五彩池与九寨沟景区 POI 混在一起；黄山游客大量联动宏村。官方路线则追求全域覆盖，包含盆景滩、芦苇海等"
         "低频节点。两者本就不是一个任务：官方写“全景菜单”，游客记“我的选择”。")
    rb.p(f"顺序一致性（九寨沟 {CMP['九寨沟']['order_tau_mean']}、黄山 {CMP['黄山']['order_tau_mean']}、颐和园 {CMP['颐和园']['order_tau_mean']}）："
         "梯度与景区的空间约束强度一致。九寨沟游览依赖 Y 形沟内观光车单线，先后顺序被基础设施锁死，游客与官方高度一致；"
         "黄山有前山/后山两个索道方向（官方自己都写“反之也可”），顺序存在真实的双向自由度；"
         "颐和园最低，原因有二：其一，官方路线是季节/主题变体（赏花线、红色游、无障碍线），入口与侧重各不相同，"
         "游客则高度集中于“东宫门—长廊—佛香阁”经典中轴，与任意单条主题路线的公共 POI 排序都难以对齐；"
         "其二，游记中的 POI 顺序是“提及顺序”，拍照回顾型笔记（“P1机位在南湖岛…”）的提及序与实际行程序并不一致——"
         "这提示游客路线提取需要区分行程叙事与图集回顾两类文本。")
    rb.p("时段结构的形态差异：九寨沟官方是唯一带完整日程的指南（时段+时长+交通），黄山官方给“节点链+天级结构”，"
         "颐和园官方连天级结构都不给。这本身就是三种官方话语的差别——强约束型（观光车调度）、"
         "体力约束型（索道/住宿节点）、自由漫游型（皇家园林）。")

    rb.sub("4.4 口径说明与后续规划")
    rb.bullets([
        "游客路线采用“提及序”口径：以阅读顺序为动线近似，图集回顾型笔记的顺序影响已由顺序一致性指标显式度量；",
        "官方时段信息按景区实际提供程度纳入对比（九寨沟为完整日程口径，颐和园/黄山为节点链口径），对比在同一口径内进行；",
        "跨景区联游实体由 in_scenic 在景标记过滤，实验6 融合以共现消歧规则做归属校正。",
    ])

    rb.section("五、实验小结")
    rb.p(f"本实验把 46 条官方路线归纳为六种描述格式并全部解析为统一的步骤化结构（{len(ORDERED)} 条有序路线平均 {sum(p['step_count'] for p in ORDERED) / len(ORDERED):.1f} 步，"
         "带 POI/交通/时间/住宿属性），构建了“天→时段→步骤”的时间层级并输出结构树图；"
         f"从 249 篇游记中提取 {sum(d['n_tourist_routes'] for d in CMP.values())} 条游客实际路线，完成覆盖度、顺序一致性、时间分配三维度量化对比。"
         "核心发现：游客与官方的路线差异不是“对错”而是“任务不同”——覆盖度 ~0.4 反映精华式游览与全景式指南的分工，"
         "顺序一致性的景区梯度由空间基础设施约束强度决定，时间维度的“晚上空白”是官方指南最普遍的盲区。"
         "这些结构化路线与时段数据将直接作为实验6知识图谱的边（先后顺序、时间归属）。")

    rb.save(ROOT / "report.docx")


if __name__ == "__main__":
    main()
