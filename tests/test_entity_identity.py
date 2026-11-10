import tempfile
import unittest
from pathlib import Path
import sys as _sys
from pathlib import Path as _P
from entity_identity import canonical_name, read_aliases, build_poi_lookup


class EntityIdentityTests(unittest.TestCase):
    def test_route_display_name_maps_back_to_entity_canonical(self):
        lookup = build_poi_lookup([{"canonical": "玉屏景区", "scenic_areas": ["黄山"]}])
        self.assertEqual(lookup[("黄山", "玉屏")], "玉屏景区")
        self.assertNotIn(("九寨沟", "玉屏"), lookup)

    def test_ambiguous_display_shortening_fails(self):
        with self.assertRaises(ValueError):
            build_poi_lookup([{"canonical": "甲景区", "scenic_areas": ["某景区"]},
                              {"canonical": "甲", "scenic_areas": ["某景区"]}])

    def test_reviewed_aliases_are_idempotent(self):
        for name, area, target in [("耕织图景区", "颐和园", "耕织图"), ("树正磨坊", "九寨沟", "树正磨房")]:
            self.assertEqual(canonical_name(name, area), target)
            self.assertEqual(canonical_name(target, area), target)

    def test_different_place_and_facility_remain_distinct(self):
        self.assertEqual(canonical_name("五彩池", "九寨沟"), "五彩池")
        self.assertEqual(canonical_name("北海宾馆", "黄山"), "北海宾馆")
        self.assertEqual(canonical_name("耕织图景区", "黄山"), "耕织图景区")

    def test_conflicts_and_cycles_fail(self):
        for rows in ["黄山,A,B\n黄山,A,C\n", "黄山,A,B\n黄山,B,A\n"]:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "aliases.csv"
                path.write_text("area,alias,canonical\n" + rows, encoding="utf-8")
                with self.assertRaises(ValueError):
                    read_aliases(path)
