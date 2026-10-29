"""与实验3一致的名称归一化（剥离地理限定与“景区”后缀），供 task3/task6 共用。"""
from __future__ import annotations
import re

NORMALIZE_SUFFIX = re.compile(r"(?:风景区|景区|入口|出口)$")
GEO_PREFIX = {
    "黄山南大门": "南大门", "黄山北大门": "北大门", "黄山西门": "西门",
    "九寨沟沟口": "沟口", "九寨沟景区": "九寨沟",
}


def normalize(name: str) -> str:
    for pref, short in GEO_PREFIX.items():
        if name.startswith(pref) and name != pref:
            return normalize(short + name[len(pref):])
    return NORMALIZE_SUFFIX.sub("", name)


