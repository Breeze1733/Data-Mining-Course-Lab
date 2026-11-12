"""Build the scenic-node seed used by task2 baseline and the Ctrip expansion scripts.

The seed was migrated from the original inline ``NODES`` literal in
``task1/scripts/expand_ctrip.py``; this script is now its single source of truth.
The generated JSON must not be deleted: both ``expand_ctrip.py`` and
``task2/src/extract_entities.py --iteration baseline`` read it.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/processed/scenic_nodes.json"

NODES = {
    "黄山": [
        "云谷", "玉屏", "慈光阁", "始信峰", "光明顶", "迎客松", "天都峰", "莲花峰",
        "鳌鱼峰", "排云亭", "西海大峡谷", "猴子观海", "白鹅岭", "狮子峰", "太平索道",
        "清凉台", "丹霞峰", "海心亭", "北海", "飞来石",
    ],
    "九寨沟": [
        "长海", "五彩池", "五花海", "箭竹海", "熊猫海", "珍珠滩", "诺日朗", "犀牛海",
        "老虎海", "树正", "火花海", "芦苇海", "原始森林", "镜海", "盆景滩", "则查洼",
        "日则沟",
    ],
    "颐和园": [
        "东宫门", "北宫门", "西门", "新建宫门", "长廊", "昆明湖", "万寿山", "苏州街",
        "佛香阁", "排云殿", "十七孔桥", "铜牛", "石舫", "清晏舫", "玉澜堂", "乐寿堂",
        "仁寿殿", "谐趣园", "知春亭", "西堤", "南湖岛", "霁清轩", "景福阁", "四大部洲",
        "邀月门", "听鹂馆", "文昌阁", "文昌院", "德和园", "画中游", "北如意门",
        "智慧海", "耶律楚材", "德辉殿",
    ],
}


def main() -> int:
    data = {
        "source": "task1/scripts/build_scenic_nodes.py",
        "count": sum(len(v) for v in NODES.values()),
        "scenic_nodes": NODES,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: len(v) for k, v in NODES.items()}, ensure_ascii=False), data["count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
