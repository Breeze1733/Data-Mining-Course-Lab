"""实体词频可视化：柱状图 + 词云。

字体、scope、top-N 和景区面板上限由 `config.json` 决定；景区数量不固定。
没有可用中文字体时降级为默认字体并写提示，不中断流程。

用法:
    python src/visualize_entities.py --entities outputs/entities.json --charts-dir outputs/charts
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from config import add_config_argument, load_config, scope_sources  # noqa: E402
from io_utils import write_csv  # noqa: E402
from schema import TYPE_POI, TYPE_TIME, TYPE_TRANSPORT  # noqa: E402

FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path(r"C:\Windows\Fonts\simsun.ttc"),
]
SCOPES = {
    "analysis": {"tourist", "official_route"},
    "all": {"tourist", "official_route", "official_document"},
    "tourist": {"tourist"},
    "official_route": {"official_route"},
    "official_document": {"official_document"},
}
FONT_HINTS = ("msyh", "simhei", "simsun", "notosanscjk", "sourcehansans", "wqy", "droid")
OTHER_AREA = "其他景区"


def find_font(config: dict | None = None) -> Path | None:
    config = config or {}
    viz = config.get("visualization", {})
    env_name = str(viz.get("font_env_var") or "TASK2_FONT")
    env_path = os.environ.get(env_name)
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(Path(item) for item in viz.get("font_candidates", []))
    candidates.extend(FONT_CANDIDATES)
    for path in candidates:
        if path.exists():
            return path
    try:
        from matplotlib import font_manager

        for path in font_manager.findSystemFonts():
            lowered = Path(path).name.lower()
            if any(hint in lowered for hint in FONT_HINTS):
                return Path(path)
    except Exception:  # noqa: BLE001 - 字体探测失败不应中断流程
        return None
    return None


def setup_matplotlib(font: Path | None) -> None:
    if font:
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun", "Noto Sans CJK SC"]
        plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["axes.unicode_minus"] = False


def load_entities(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def select(
    entities: Iterable[dict],
    scope: str,
    include_root_area: bool,
    config: dict | None = None,
) -> list[dict]:
    allowed = scope_sources(config, scope) if config is not None else SCOPES[scope]
    rows = [entity for entity in entities if entity["source_kind"] in allowed]
    if not include_root_area:
        rows = [
            entity
            for entity in rows
            if not (entity["type"] == TYPE_POI and entity.get("is_root_area"))
        ]
    return rows


def counts(entities: Iterable[dict], type_name: str, exclude_duration: bool = False) -> Counter:
    counter: Counter = Counter()
    for entity in entities:
        if entity["type"] != type_name:
            continue
        if exclude_duration and entity["subtype"] == "时长":
            continue
        counter[entity["frequency_key"]] += 1
    return counter


def barh(
    counter: Counter,
    title: str,
    path: Path,
    color: str,
    top_n: int = 20,
    dpi: int = 180,
) -> None:
    items = counter.most_common(top_n)
    if not items:
        return
    keys = [item[0] for item in items][::-1]
    values = [item[1] for item in items][::-1]
    height = max(4.0, 0.35 * len(items) + 1.5)
    fig, ax = plt.subplots(figsize=(10, height))
    ax.barh(keys, values, color=color)
    ax.set_xlabel("出现次数")
    ax.set_title(title)
    for index, value in enumerate(values):
        ax.text(value + max(values) * 0.01, index, str(value), va="center", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)


def plot_type_counts(entities: list[dict], path: Path, dpi: int = 180) -> None:
    labels = [TYPE_POI, TYPE_TRANSPORT, TYPE_TIME]
    values = [sum(1 for entity in entities if entity["type"] == label) for label in labels]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    bars = ax.bar(labels, values, color=["#4C78A8", "#F58518", "#54A24B"])
    ax.set_ylabel("实体出现次数")
    ax.set_title("三类实体词频总量")
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value, str(value), ha="center", va="bottom")
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)


def _area_panels(
    entities: list[dict], max_panels: int
) -> list[tuple[str, list[dict]]]:
    area_counts = Counter(entity["scenic_area"] for entity in entities)
    ordered = sorted(area_counts, key=lambda area: (-area_counts[area], area))
    if len(ordered) <= max_panels:
        shown = ordered
        rest: set[str] = set()
    else:
        shown = ordered[: max(1, max_panels - 1)]
        rest = set(ordered[max(1, max_panels - 1) :])
    panels = [
        (area, [entity for entity in entities if entity["scenic_area"] == area])
        for area in shown
    ]
    if rest:
        panels.append(
            (OTHER_AREA, [entity for entity in entities if entity["scenic_area"] in rest])
        )
    return panels


def plot_area_poi(
    entities: list[dict],
    path: Path,
    per_area: int = 10,
    max_panels: int = 12,
    dpi: int = 180,
) -> None:
    panels = _area_panels(entities, max_panels)
    if not panels:
        return
    cols = min(4, len(panels))
    rows = math.ceil(len(panels) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 4.5 * rows), squeeze=False)
    for index, (area, area_entities) in enumerate(panels):
        axis = axes[index // cols][index % cols]
        counter = Counter(
            entity["frequency_key"]
            for entity in area_entities
            if entity["type"] == TYPE_POI
        )
        items = counter.most_common(per_area)[::-1]
        if items:
            axis.barh([item[0] for item in items], [item[1] for item in items], color="#4C78A8")
        axis.set_title(f"{area} POI top{per_area}")
        axis.set_xlabel("出现次数")
    for index in range(len(panels), rows * cols):
        axes[index // cols][index % cols].axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)


def plot_type_by_area(entities: list[dict], path: Path, dpi: int = 180) -> None:
    areas = sorted({entity["scenic_area"] for entity in entities})
    if not areas:
        return
    types = [TYPE_POI, TYPE_TRANSPORT, TYPE_TIME]
    width = 0.8 / len(types)
    fig, ax = plt.subplots(figsize=(max(9, 1.2 * len(areas)), 5))
    for offset, type_name in enumerate(types):
        values = [
            sum(
                1
                for entity in entities
                if entity["scenic_area"] == area and entity["type"] == type_name
            )
            for area in areas
        ]
        positions = [index + (offset - (len(types) - 1) / 2) * width for index in range(len(areas))]
        ax.bar(positions, values, width=width, label=type_name)
    ax.set_xticks(range(len(areas)))
    rotation = 0 if len(areas) <= 12 else 45
    ax.set_xticklabels(areas, rotation=rotation, ha="right" if rotation else "center")
    ax.set_ylabel("实体出现次数")
    ax.set_title("分景区实体类型分布")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)


def plot_wordcloud(
    counter: Counter,
    title: str,
    path: Path,
    font: Path | None,
    max_words: int = 120,
    random_state: int = 42,
) -> bool:
    if font is None:
        return False
    try:
        from wordcloud import WordCloud
    except ImportError:
        return False
    if not counter:
        return False
    cloud = WordCloud(
        font_path=str(font),
        width=1200,
        height=800,
        background_color="white",
        max_words=max_words,
        prefer_horizontal=0.9,
        relative_scaling=0.5,
        random_state=random_state,
        colormap="tab20",
    ).generate_from_frequencies(dict(counter))
    figure = plt.figure(figsize=(10, 6.7))
    plt.imshow(cloud, interpolation="bilinear")
    plt.axis("off")
    plt.title(title)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return True


def run(
    entities_path: Path,
    charts_dir: Path,
    scope: str | None = None,
    include_root_area: bool = False,
    no_wordcloud: bool = False,
    config: dict | None = None,
) -> None:
    config = load_config() if config is None else config
    scope = scope or str(config["scope"].get("default") or "analysis")
    payload = load_entities(entities_path)
    entities = select(payload["entities"], scope, include_root_area, config)
    charts_dir.mkdir(parents=True, exist_ok=True)
    font = find_font(config)
    setup_matplotlib(font)

    viz = config.get("visualization", {})
    top_n = config.get("top_n", {})
    dpi = int(viz.get("dpi", 180))
    poi_limit = int(top_n.get("poi", 20))
    transport_limit = int(top_n.get("transport", 20))
    time_limit = int(top_n.get("time", 20))
    duration_limit = int(top_n.get("duration", 15))
    per_area = int(top_n.get("per_area", 10))
    max_panels = int(top_n.get("max_area_panels", 12))

    expected: set[str] = {
        "entity_freq_by_type.png",
        f"poi_top{poi_limit}.png",
        f"transport_top{transport_limit}.png",
        f"time_top{time_limit}.png",
        f"duration_top{duration_limit}.png",
        "poi_freq_by_area.png",
        "type_by_area.png",
    }
    plot_type_counts(entities, charts_dir / "entity_freq_by_type.png", dpi)
    barh(
        counts(entities, TYPE_POI),
        f"景点 POI top{poi_limit}",
        charts_dir / f"poi_top{poi_limit}.png",
        "#4C78A8",
        poi_limit,
        dpi,
    )
    barh(
        counts(entities, TYPE_TRANSPORT),
        f"交通方式 top{transport_limit}",
        charts_dir / f"transport_top{transport_limit}.png",
        "#F58518",
        transport_limit,
        dpi,
    )
    barh(
        counts(entities, TYPE_TIME, exclude_duration=True),
        f"时间节点 top{time_limit}（不含时长）",
        charts_dir / f"time_top{time_limit}.png",
        "#54A24B",
        time_limit,
        dpi,
    )
    barh(
        counts(
            [entity for entity in entities if entity["subtype"] == "时长"],
            TYPE_TIME,
        ),
        f"停留时长 top{duration_limit}",
        charts_dir / f"duration_top{duration_limit}.png",
        "#B279A2",
        duration_limit,
        dpi,
    )
    plot_area_poi(entities, charts_dir / "poi_freq_by_area.png", per_area, max_panels, dpi)
    plot_type_by_area(entities, charts_dir / "type_by_area.png", dpi)

    area_counts = Counter(entity["scenic_area"] for entity in entities)
    write_csv(
        charts_dir / "area_entity_counts.csv",
        [
            {"scenic_area": area, "entities": count}
            for area, count in sorted(area_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        ["scenic_area", "entities"],
    )

    if not no_wordcloud:
        results = {
            "wordcloud_poi.png": plot_wordcloud(
                counts(entities, TYPE_POI),
                "景点 POI 词云",
                charts_dir / "wordcloud_poi.png",
                font,
                int(viz.get("wordcloud_max_words", 120)),
                int(viz.get("wordcloud_random_state", 42)),
            ),
            "wordcloud_transport.png": plot_wordcloud(
                counts(entities, TYPE_TRANSPORT),
                "交通方式词云",
                charts_dir / "wordcloud_transport.png",
                font,
                int(viz.get("wordcloud_max_words", 120)),
                int(viz.get("wordcloud_random_state", 42)),
            ),
            "wordcloud_time.png": plot_wordcloud(
                counts(entities, TYPE_TIME, exclude_duration=True),
                "时间节点词云（不含时长）",
                charts_dir / "wordcloud_time.png",
                font,
                int(viz.get("wordcloud_max_words", 120)),
                int(viz.get("wordcloud_random_state", 42)),
            ),
        }
        if not all(results.values()):
            (charts_dir / "wordcloud_unavailable.txt").write_text(
                "词云生成失败或字体不可用；柱状图仍满足任务书“词云或柱状图”的要求。\n",
                encoding="utf-8",
            )
        else:
            stale_note = charts_dir / "wordcloud_unavailable.txt"
            if stale_note.exists():
                stale_note.unlink()

    for stale in charts_dir.glob("*.png"):
        if stale.name not in expected:
            stale.unlink()
    if font is None:
        (charts_dir / "font_unavailable.txt").write_text(
            "未找到中文字体；图表中文可能显示为方框。可通过 TASK2_FONT 环境变量或 "
            "config.json 的 visualization.font_candidates 指定字体。\n",
            encoding="utf-8",
        )
    print(f"[charts] written to {charts_dir} (font={font})", flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="task2 实体可视化")
    add_config_argument(parser)
    parser.add_argument("--entities", required=True)
    parser.add_argument("--charts-dir", required=True)
    parser.add_argument("--scope", default=None, help="默认取配置")
    parser.add_argument("--include-root-area", action="store_true")
    parser.add_argument("--no-wordcloud", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    run(
        entities_path=Path(args.entities),
        charts_dir=Path(args.charts_dir),
        scope=args.scope,
        include_root_area=args.include_root_area,
        no_wordcloud=args.no_wordcloud,
        config=config,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
