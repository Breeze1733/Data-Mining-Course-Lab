"""词典最长匹配与重叠消解测试（离线）。"""

from __future__ import annotations

import unittest

from dictionary import Gazetteer, POIEntry, TransportEntry


def poi(pid, area, surface, canonical, subtype, parent="", priority=10, negative=""):
    return POIEntry(pid, area, surface, canonical, subtype, parent or canonical, "test", priority, negative)


def transport(tid, surface, normalized, subtype="其他", priority=8, linked="", negative_after=""):
    return TransportEntry(tid, surface, normalized, subtype, priority, False, "", negative_after, linked, "")


class DictionaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gazetteer = Gazetteer(
            [
                poi("P1", "九寨沟", "树正", "树正景区", "景区片区", priority=6),
                poi("P2", "九寨沟", "树正瀑布", "树正瀑布", "瀑布滩地"),
                poi("P3", "九寨沟", "树正群海", "树正群海", "湖泊水体"),
                poi("P4", "九寨沟", "诺日朗", "诺日朗景区", "景区片区", priority=6, negative="餐厅"),
                poi("P5", "九寨沟", "诺日朗中心站", "诺日朗中心站", "站点服务中心"),
                poi("P7", "黄山", "黄山", "黄山风景区", "景区"),
                poi("P8", "黄山", "光明顶", "光明顶", "山峰"),
                poi("P9", "黄山", "云谷", "云谷景区", "景区片区", priority=6),
            ],
            [
                transport("T1", "索道", "索道", "索道缆车"),
                transport("T2", "云谷索道", "索道", "索道缆车", 12, "云谷寺"),
                transport("T3", "观光车", "观光车", "景区车摆渡车"),
                transport("T4", "船", "游船", "水运", 4, negative_after="票|上"),
            ],
        )

    def test_longest_match(self) -> None:
        matches = self.gazetteer.iter_poi_matches("树正瀑布和树正群海", "九寨沟")
        surfaces = [match.surface for match in matches]
        self.assertEqual(surfaces, ["树正瀑布", "树正群海"])

    def test_area_isolation(self) -> None:
        matches = self.gazetteer.iter_poi_matches("庐山和黄山", "黄山")
        self.assertEqual([match.surface for match in matches], ["黄山"])
        self.assertNotIn("庐山", [match.normalized for match in matches])

    def test_negative_context(self) -> None:
        matches = self.gazetteer.iter_poi_matches("诺日朗餐厅用餐", "九寨沟")
        self.assertEqual(matches, [])

    def test_named_transport_linked_poi(self) -> None:
        matches = self.gazetteer.iter_transport_matches("坐云谷索道上山")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].surface, "云谷索道")
        self.assertEqual(matches[0].normalized, "索道")
        self.assertEqual(matches[0].linked_poi, "云谷寺")

    def test_transport_negative_after(self) -> None:
        self.assertEqual(self.gazetteer.iter_transport_matches("船票"), [])

    def test_area_helpers(self) -> None:
        self.assertTrue(self.gazetteer.has_area("黄山"))
        self.assertFalse(self.gazetteer.has_area("庐山"))
        self.assertEqual(self.gazetteer.area_entry_count("黄山"), 3)
        self.assertIn("光明顶", self.gazetteer.area_surfaces("黄山"))
        self.assertEqual(self.gazetteer.area_surfaces("庐山"), set())

    def test_overlap_resolution(self) -> None:
        candidates = self.gazetteer.iter_poi_matches("云谷索道", "黄山")
        candidates += self.gazetteer.iter_transport_matches("云谷索道")
        selected, suppressed = self.gazetteer.resolve_overlaps(candidates)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].type, "交通方式")
        self.assertEqual(selected[0].surface, "云谷索道")
        self.assertEqual(len(suppressed), 1)
        self.assertEqual(suppressed[0].surface, "云谷")


if __name__ == "__main__":
    unittest.main()
