"""交通规则单元测试（离线）。"""

from __future__ import annotations

import unittest
from pathlib import Path

from transport_rules import TransportRules

RESOURCES = Path(__file__).resolve().parents[1] / "resources"


class TransportRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = TransportRules.load(RESOURCES / "transport_lexicon.csv")

    def surfaces(self, text: str) -> list[str]:
        return [candidate.surface for candidate in self.rules.extract(text)]

    def test_basic_modes(self) -> None:
        self.assertIn("大巴", self.surfaces("坐大巴上山"))
        self.assertIn("步行", self.surfaces("步行到山顶"))
        self.assertIn("观光车", self.surfaces("换乘观光车"))

    def test_ticket_and_station_excluded(self) -> None:
        self.assertEqual(self.surfaces("索道票"), [])
        self.assertEqual(self.surfaces("索道站"), [])
        self.assertEqual(self.surfaces("观光车票"), [])

    def test_transfer_is_not_a_mode(self) -> None:
        self.assertEqual(self.surfaces("换乘"), [])
        self.assertEqual(self.surfaces("换乘观光车"), ["观光车"])

    def test_named_cableway(self) -> None:
        items = self.rules.extract("坐云谷索道上山")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].surface, "云谷索道")
        self.assertEqual(items[0].normalized, "索道")
        self.assertEqual(items[0].linked_poi, "云谷寺")

    def test_boat(self) -> None:
        self.assertIn("船", self.surfaces("坐船游湖"))
        self.assertEqual(self.surfaces("船票"), [])

    def test_advertisement_excluded(self) -> None:
        self.assertEqual(self.surfaces("包车电话"), [])
        self.assertEqual(self.surfaces("包车师傅"), [])

    def test_high_speed_rail_station_excluded(self) -> None:
        self.assertIn("高铁", self.surfaces("坐高铁到黄山"))
        self.assertEqual(self.surfaces("高铁站"), [])


if __name__ == "__main__":
    unittest.main()
