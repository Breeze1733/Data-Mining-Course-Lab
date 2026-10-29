"""实验2：实体词频可视化（柱状图 + 词云）与两轮迭代对比。

用法：python src/visualize.py --iteration refined
输入：output/exp2/entity_stats_{iteration}.json
输出：output/exp2/figs/*.png
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from wordcloud import WordCloud

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/exp2"
FIGS = None  # 运行时按迭代设定
FONT = "C:/Windows/Fonts/simhei.ttf"

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

COLORS = {"景点POI": "#2E7D32", "交通方式": "#1565C0", "时间节点": "#C62828"}


def bar_chart(freq: dict[str, int], title: str, path: Path, color: str, topn: int = 15):
    items = list(freq.items())[:topn]
    words = [w for w, _ in items][::-1]
    counts = [c for _, c in items][::-1]
    fig, ax = plt.subplots(figsize=(8, 5.2), dpi=150)
    ax.barh(words, counts, color=color, alpha=0.85)
    ax.set_title(title, fontsize=13)
    ax.set_xlabel("出现次数")
    ax.spines[["top", "right"]].set_visible(False)
    for i, v in enumerate(counts):
        ax.text(v, i, f" {v}", va="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def wordcloud_chart(freq: dict[str, int], title: str, path: Path, color: str):
    wc = WordCloud(font_path=FONT, width=1200, height=700, background_color="white",
                   colormap=color, max_words=120, prefer_horizontal=0.95, random_state=42)
    wc.generate_from_frequencies(freq)
    fig, ax = plt.subplots(figsize=(8, 4.8), dpi=150)
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    ax.set_title(title, fontsize=13)
    fig.tight_layout()
    with path.open("wb") as output:
        fig.savefig(output, format="png")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", default="refined")
    args = parser.parse_args()
    stats = json.loads((OUT / f"entity_stats_{args.iteration}.json").read_text(encoding="utf-8"))
    global FIGS
    FIGS = OUT / "figs" / args.iteration
    FIGS.mkdir(parents=True, exist_ok=True)

    colormap = {"景点POI": "Greens", "交通方式": "Blues", "时间节点": "Reds"}
    for etype, freq in stats["top_canonical"].items():
        bar_chart(freq, f"{etype} 词频 Top15（{args.iteration}）", FIGS / f"bar_{etype}.png", COLORS[etype])
        wordcloud_chart(freq, f"{etype} 词云（{args.iteration}）", FIGS / f"wc_{etype}.png", colormap[etype])

    # 三景区 × 三类型对比柱状图
    by_scenic = stats["by_scenic_area"]
    areas = list(by_scenic)
    types = ["景点POI", "交通方式", "时间节点"]
    import numpy as np
    x = np.arange(len(areas))
    width = 0.25
    fig, ax = plt.subplots(figsize=(7.5, 4.6), dpi=150)
    for i, t in enumerate(types):
        vals = [by_scenic[a].get(t, 0) for a in areas]
        ax.bar(x + (i - 1) * width, vals, width, label=t, color=COLORS[t], alpha=0.85)
    ax.set_xticks(x, areas)
    ax.set_ylabel("实体次数")
    ax.set_title(f"三景区实体分布对比（{args.iteration}）")
    ax.legend()
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIGS / "bar_by_scenic.png")
    plt.close(fig)

    if args.iteration == "refined":
        import shutil
        for chart in FIGS.glob("*.png"):
            shutil.copy2(chart, FIGS.parent / chart.name)
    print(json.dumps({"figs": sorted(p.name for p in FIGS.glob("*.png"))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
