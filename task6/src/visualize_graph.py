"""实验6：知识图谱可视化（静态 PNG + pyvis 交互 HTML）。

静态图：每景区一张，POI 节点按度数着色突出关键节点；条件节点只显示频次≥2 的前 12 条。
交互图：pyvis HTML，含物理布局，节点可拖拽、点选查看属性。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
FIGS = OUT / "figs"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

AREAS = ("黄山", "九寨沟", "颐和园")
KIND_COLOR = {"景区": "#B71C1C", "景点": "#2E7D32", "周边景点": "#7CB342", "时段": "#C62828",
              "交通操作": "#1565C0", "条件": "#F9A825"}
KIND_SIZE = {"景区": 900, "景点": 300, "周边景点": 200, "时段": 350, "交通操作": 280, "条件": 200}


def load_graph() -> nx.MultiDiGraph:
    return nx.read_graphml(OUT / "knowledge_graph.graphml")


def subgraph_for(G: nx.MultiDiGraph, scenic: str, max_conds: int = 12) -> nx.MultiDiGraph:
    nodes = [n for n in G.nodes if f":{scenic}:" in n]
    sub = G.subgraph(nodes).copy()
    # 条件节点只保留频次高的前 N 条，避免淹没 POI 网络
    conds = [(n, d.get("frequency", 1)) for n, d in sub.nodes(data=True) if d.get("kind") == "条件"]
    keep = {n for n, f in sorted(conds, key=lambda x: -x[1])[:max_conds] if f >= 2}
    drop = [n for n, d in sub.nodes(data=True) if d.get("kind") == "条件" and n not in keep]
    sub.remove_nodes_from(drop)
    return sub


def draw_static(sub: nx.MultiDiGraph, scenic: str, path: Path):
    # 主网络（POI/景区/时段/交通）做 spring 布局；条件节点锚定在邻居外侧，避免飞出画面
    main_nodes = [n for n, d in sub.nodes(data=True) if d.get("kind") != "条件"]
    cond_nodes = [n for n, d in sub.nodes(data=True) if d.get("kind") == "条件"]
    main = sub.subgraph(main_nodes)
    pos = nx.spring_layout(main, k=0.9, iterations=150, seed=7, weight="weight")
    for cn in cond_nodes:
        anchors = [pos[u] for u in sub.predecessors(cn) if u in pos] or list(pos.values())[:1]
        cx = sum(p[0] for p in anchors) / len(anchors)
        cy = sum(p[1] for p in anchors) / len(anchors)
        # 沿远离主网络重心的方向外推
        gx = sum(p[0] for p in pos.values()) / len(pos)
        gy = sum(p[1] for p in pos.values()) / len(pos)
        dx, dy = cx - gx, cy - gy
        norm = (dx ** 2 + dy ** 2) ** 0.5 or 1.0
        step = min(0.35, 0.18 + 0.05 * sub.degree(cn))
        pos[cn] = (cx + dx / norm * step, cy + dy / norm * step)

    degrees = dict(sub.degree())
    max_deg = max(degrees.values()) or 1
    fig, ax = plt.subplots(figsize=(14, 10.5), dpi=150)

    # 分层画边：包含/周边关联最淡，先后最深
    style = {"包含": (dict(width=0.5, edge_color="#CFD8DC", alpha=0.5, style="dashed")),
             "周边关联": (dict(width=0.5, edge_color="#C5E1A5", alpha=0.5, style="dashed")),
             "先后顺序": (dict(width=1.1, edge_color="#37474F", alpha=0.55)),
             "时段归属": (dict(width=0.8, edge_color="#EF9A9A", alpha=0.6)),
             "交通方式": (dict(width=0.9, edge_color="#64B5F6", alpha=0.7)),
             "条件建议": (dict(width=0.8, edge_color="#F9A825", alpha=0.55))}
    for rel, kw in style.items():
        edges = [(u, v) for u, v, d in sub.edges(data=True) if d.get("relation") == rel]
        if edges:
            nx.draw_networkx_edges(sub, pos, edgelist=edges, ax=ax, arrows=True, arrowsize=9,
                                   connectionstyle="arc3,rad=0.07", **kw)

    for kind in ("景区", "时段", "交通操作", "条件", "周边景点", "景点"):
        nodes = [n for n, d in sub.nodes(data=True) if d.get("kind") == kind]
        if not nodes:
            continue
        sizes = [KIND_SIZE.get(kind, 200) * (0.55 + 0.9 * degrees[n] / max_deg) for n in nodes]
        nx.draw_networkx_nodes(sub, pos, nodelist=nodes, ax=ax,
                               node_color=KIND_COLOR.get(kind, "#888888"),
                               node_size=sizes, alpha=0.92, linewidths=0.4)
    top = set(sorted(degrees, key=degrees.get, reverse=True)[:10])
    for n, d in sub.nodes(data=True):
        kind = d.get("kind", "")
        if kind == "条件":
            label = f'[{d.get("cond_type", "")}] {d.get("name", "")[:9]}'
            ax.text(pos[n][0], pos[n][1] - 0.055, label, fontsize=6.3, ha="center", va="center",
                    color="#8D6E63", family="SimHei")
        else:
            ax.text(pos[n][0], pos[n][1], d.get("label", n), fontsize=7.5, ha="center", va="center",
                    fontweight="bold" if n in top else "normal", family="SimHei")
    handles = [plt.Line2D([], [], marker="o", ls="", color=c, label=k) for k, c in KIND_COLOR.items()]
    ax.legend(handles=handles, loc="upper left", fontsize=8, framealpha=0.9)
    ax.set_title(f"{scenic} 游览知识图谱（{sub.number_of_nodes()} 节点 / {sub.number_of_edges()} 边；"
                 f"节点大小∝度数，深色实线=先后顺序，黄线=条件建议，虚线=包含）", fontsize=11)
    ax.axis("off")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def draw_interactive(G: nx.MultiDiGraph, scenic: str, path: Path):
    from pyvis.network import Network
    sub = subgraph_for(G, scenic, max_conds=25)
    net = Network(height="750px", width="100%", directed=True, notebook=False, font_color="#333333",
                  cdn_resources="remote")
    net.barnes_hut(gravity=-6000, spring_length=120)
    for n, d in sub.nodes(data=True):
        kind = d.get("kind", "景点")
        deg = sub.degree(n)
        net.add_node(n, label=d.get("label", n), title=f'{d.get("label", n)}｜{kind}',
                     color=KIND_COLOR.get(kind, "#888888"),
                     size=12 + min(30, deg * 2), font={"size": 12 if kind in ("景点", "景区") else 9})
    for u, v, d in sub.edges(data=True):
        net.add_edge(u, v, title=f'{d.get("relation")} w={d.get("weight", 1):.1f}',
                     width=min(4, 0.6 + float(d.get("weight", 1)) ** 0.5 * 0.5),
                     color={"先后顺序": "#37474F", "条件建议": "#F9A825"}.get(d.get("relation"), "#B0BEC5"))
    net.write_html(str(path))


def main() -> int:
    FIGS.mkdir(parents=True, exist_ok=True)
    G = load_graph()
    for scenic in AREAS:
        sub = subgraph_for(G, scenic)
        draw_static(sub, scenic, FIGS / f"graph_{scenic}.png")
        draw_interactive(G, scenic, OUT / f"graph_{scenic}.html")
        print(f"{scenic}: static {sub.number_of_nodes()}n/{sub.number_of_edges()}e, html ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
