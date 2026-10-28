"""交通方式识别：词典最长匹配 + 否定语境。

规则:
    - span 只取方式名词（“坐大巴”取“大巴”）；
    - 词典中带 linked_poi 的具名索道/缆车优先，并记录 linked_poi；
    - 票务、排队、停运、检修、关闭、站点名、包车广告等语境排除；
    - 裸“换乘”不是交通方式；换乘观光车只输出“观光车”。
"""

from __future__ import annotations

from pathlib import Path

from dictionary import Candidate, Gazetteer, TransportEntry, load_transport_lexicon


class TransportRules:
    def __init__(self, entries: list[TransportEntry]):
        self.entries = entries
        self._gazetteer = Gazetteer([], entries)

    @classmethod
    def load(cls, path: Path) -> "TransportRules":
        return cls(load_transport_lexicon(path))

    def extract(self, text: str) -> list[Candidate]:
        candidates = self._gazetteer.iter_transport_matches(text)
        for candidate in candidates:
            if not candidate.linked_poi:
                continue
            search_from = max(0, candidate.start - 8)
            index = text.find(candidate.linked_poi, search_from)
            if index >= 0:
                candidate.linked_poi_start = index
                candidate.linked_poi_end = index + len(candidate.linked_poi)
        return candidates


__all__ = ["TransportRules"]
