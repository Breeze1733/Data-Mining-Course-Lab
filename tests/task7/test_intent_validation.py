# -*- coding: utf-8 -*-
"""G01：意图字段类型校验与范围约束。"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "task7/src"))
from agent_cli import IntentParser  # noqa: E402

VALID_DAYS = {0.5, 1, 1.5, 2, 3, 3.5, 4, 5}


class IntentValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parser = IntentParser(None)

    def _intent(self, q):
        return self.parser._parse_rules(q)

    def test_days_always_in_valid_range(self):
        for q in ("黄山两日游", "黄山玩半天", "黄山一日半游", "黄山三日半游",
                  "黄山五日游", "黄山3天游", "黄山周末游", "只有3小时游颐和园"):
            self.assertIn(self._intent(q)["days"], VALID_DAYS, q)

    def test_month_in_valid_range(self):
        for q in ("1月去黄山", "12月去黄山", "国庆去黄山", "春节去黄山", "夏天去黄山"):
            m = self._intent(q)["month"]
            self.assertIsNotNone(m, q)
            self.assertTrue(1 <= m <= 12, q)

    def test_explicit_fields_consistent(self):
        it = self._intent("黄山两日游，避开莲花峰")
        self.assertIn("days", it["explicit_fields"])
        self.assertIn("avoid", it["explicit_fields"])
        it2 = self._intent("黄山旅游")
        self.assertNotIn("days", it2["explicit_fields"])


if __name__ == "__main__":
    unittest.main()
