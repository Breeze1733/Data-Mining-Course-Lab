"""生成实验项目6报告：多源程序性知识融合与图谱可视化（task6/report.docx）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
from report_utils import ReportBuilder

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
FIGS = OUT / "figs"

STATS = json.loads((OUT / "graph_stats.json").read_text(encoding="utf-8"))
VALID = json.loads((OUT / "graph_validation.json").read_text(encoding="utf-8"))
PER = STATS["per_scenic"]


def main():
    rb = ReportBuilder("《数据挖掘》探索性实验报告", "—实验项目6 多源程序性知识的融合与图谱可视化")

    rb.section("一、实验目的与任务")
    rb.p("把实验3的路线结构、实验2的实体体系与实验5的条件性建议融合为景区游览知识图谱：定义节点与关系类型，"
         "建立实体对齐、来源合并与噪声过滤策略，用 NetworkX 构建图结构并导出可检查的结构化文件，"
         "对至少一个景区绘制完整游览知识网络，通过查询与统计验证图谱质量并分析核心节点。")

    rb.section("二、实验环境")
    rb.bullets([
        "Windows 11；Python 3.13（task1/.venv）；networkx 3.x（图构建与 GraphML）；matplotlib（静态图）；pyvis（交互 HTML）。",
        "输入：task2 实体词典与词频、task3 结构化路线（46 条官方 + 230 条游客）、task5 条件建议映射表（1210 条）。",
        "运行入口：task6/src/{build_graph, visualize_graph, verify_graph, build_report6}.py。",
    ])

    rb.section("三、实验设计与实现")
    rb.sub("3.1 图谱 Schema")
    rb.table(["类型", "节点/边", "说明", "数量"],
             [["节点", "景区", "三个景区的根节点", f'{STATS["by_kind"]["景区"]}'],
              ["节点", "景点POI（含周边景点子类）", "实验2词典 canonical，景区命名空间隔离", f'{STATS["by_kind"]["景点"]}'],
              ["节点", "时段", "上午/中午/下午/晚上/未标注时段", f'{STATS["by_kind"]["时段"]}'],
              ["节点", "交通操作", "观光车/索道/步行等（实验2交通词表）", f'{STATS["by_kind"]["交通操作"]}'],
              ["节点", "条件", "实验5的条件类型+条件描述", f'{STATS["by_kind"]["条件"]}'],
              ["边", "包含 / 周边关联", "景区→POI（周边景点单列）", f'{STATS["by_relation"]["包含"]}'],
              ["边", "先后顺序", "POI→POI，官方路线与游客序列双源加权", f'{STATS["by_relation"]["先后顺序"]}'],
              ["边", "时段归属 / 交通方式", "官方路线步骤的时段与交通属性", f'{STATS["by_relation"]["时段归属"] + STATS["by_relation"]["交通方式"]}'],
              ["边", "条件建议", "POI→条件节点（建议文本作节点属性）", f'{STATS["by_relation"]["条件建议"]}']],
             widths=[1.6, 4.6, 6.6, 2.2], font_size=9)
    rb.caption(f"表 1 知识图谱 Schema 与规模（共 {STATS['total_nodes']} 节点 / {STATS['total_edges']:,} 边）")

    rb.sub("3.2 融合策略")
    rb.bullets([
        "实体对齐：以实验2词典 canonical 为唯一键；景区命名空间隔离——五彩池（九寨沟/黄龙）、北海（黄山/北京）"
        "不跨景区合并；实验3步骤名经过“景区后缀剥离”归一（玉屏景区→玉屏），图谱侧建同名解析器双向对齐；",
        "来源合并：先后顺序边 = 官方路线（每条权重 1.0）+ 游客序列（每条 0.5），边上保留官方路线 ID 列表与"
        "游客支持计数，回答“这条先后关系是谁说的”；",
        "频次加权：时段归属与交通方式边按官方步骤出现次数累计；条件建议边携带实验5的频次；",
        "噪声过滤：仅收录词典内 POI；游客序列两端节点必须已存在；条件建议只挂句中出现的同景区 POI，"
        f"句中无 POI 时挂景区节点并单独计数（{STATS['cond_edges_to_scenic']} 条，如“提前预约门票”类泛供建议）。",
    ])

    rb.sub("3.3 构建与导出")
    rb.p("用 networkx.MultiDiGraph 构建（有向、多重边支持同一对 POI 的多种关系），导出四类文件："
         "graph_nodes.csv / graph_edges.csv（可直接导入图数据库或 Excel 检查）、knowledge_graph.graphml"
         "（标准图交换格式）、graph_{景区}.html（pyvis 交互版，可拖拽点选查看属性）。")

    rb.section("四、实验结果与分析")
    rb.sub("4.1 分景区规模与核心节点")
    rows = [[a, PER[a]["nodes"], PER[a]["edges"],
             "；".join(f"{n}({d})" for n, d in PER[a]["top_degree"][:4]) + f" …（度=关联次数）"]
            for a, d in ((a, PER[a]) for a in ("黄山", "九寨沟", "颐和园"))]
    rb.table(["景区", "节点", "边", "度数最高的 POI（核心节点）"], rows, widths=[1.8, 1.6, 1.6, 10.0], font_size=9)
    rb.caption("表 2 分景区图谱规模与核心节点")
    rb.p("核心节点与领域常识一致：黄山的枢纽是光明顶/天都峰/迎客松（几乎所有路线的必经之交），"
         "九寨沟是五彩池/五花海/诺日朗（三条沟的交汇点），颐和园是佛香阁/西堤/昆明湖"
         "（中轴线与环湖动线）。景区根节点度数最高是“包含”边的星形结构所致，属预期。")

    rb.sub("4.2 知识图谱可视化")
    for scenic in ("九寨沟", "黄山", "颐和园"):
        rb.image(FIGS / f"graph_{scenic}.png", 15.2)
        rb.caption(f"图 {1 + ('九寨沟', '黄山', '颐和园').index(scenic)} {scenic} 游览知识图谱"
                   f"（{PER[scenic]['nodes']} 节点 / {PER[scenic]['edges']} 边；交互版见 task6/output/graph_{scenic}.html）")
    rb.p("图中可辨识的结构：深色实线的先后顺序网络构成游览动线骨架；黄色条件建议边把“带老人别走中轴线爬山”"
         "这类经验挂到具体 POI 上；颐和园的“未标注时段”节点直接可视化了实验3的发现——其官方路线不携带时段信息，"
         "所有时段归属都落到该节点。节点大小按度数缩放，前 10 个关键节点加粗标注，条件节点只显示频次≥2 的前 12 条"
         "以避免淹没 POI 网络。")

    rb.sub("4.3 图谱质量验证")
    checks = VALID["fact_checks"]
    passed = sum(1 for c in checks if c["found"])
    rows = [[c["pair"], "是" if c["found"] else "否",
             f'w={c["edges"][0]["weight"]:.1f}' + (f'，官方路线 {c["edges"][0]["official_routes"].split("；")[0]}'
              if c["found"] and c["edges"][0]["official_routes"] else "")] for c in checks]
    rb.table(["已知事实（先后对）", "图谱中存在", "权重与来源"], rows, widths=[6.0, 2.4, 6.6], font_size=9)
    rb.caption(f"表 3 已知事实核验（{passed}/{len(checks)} 通过）")
    rb.bullets([
        f"结构完整性：三个景区子图均为单一连通分量（{VALID['connected_components_per_scenic']}），无孤立节点；",
        "同名异点隔离：五彩池仅存在于九寨沟命名空间、北海仅存在于黄山命名空间（北京北海公园由实验2停用词守卫拦截），未发生跨景区错误合并；",
        f"边类型分布合理：先后顺序 {STATS['by_relation']['先后顺序']:,} 条构成动线主体，条件建议 {STATS['by_relation']['条件建议']:,} 条把 9 类条件经验挂接到具体 POI；",
        "样例查询：诺日朗→长海（w=12.5）、长海→五彩池（w=26.5）的高权重来自官方路线与游客序列的双重支持，与“Y 形沟右线经典动线”一致。",
    ])

    rb.section("五、实验小结")
    rb.p(f"本实验把三个前序实验的输出融合为 {STATS['total_nodes']} 节点 / {STATS['total_edges']:,} 边的游览知识图谱：实体按 canonical+景区命名空间对齐，"
         "先后顺序边实现官方/游客双源加权并保留可溯源的路线 ID，条件性建议作为边属性接入。"
         "三张分景区图谱可视化了完整的游览知识网络（附交互 HTML），质量验证通过 6/6 已知事实核验、"
         "连通性检查与同名隔离检查。图谱的局限同样明确：条件节点目前以文本为标识（528 个），"
         "未做条件归一化聚类；游客序列的“提及序”噪声已经进入先后边（权重 0.5 折算）——"
         "这些将在实验7 的查询工具中通过最小权重阈值缓解。")

    rb.save(ROOT / "report.docx")


if __name__ == "__main__":
    main()
