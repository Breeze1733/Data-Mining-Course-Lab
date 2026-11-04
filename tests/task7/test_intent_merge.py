# -*- coding: utf-8 -*-
"""P10：意图合并的显式时长保护与类型/范围校验（离线单测）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "task7" / "src"))
from agent_cli import IntentParser  # noqa: E402


class TestMergeDays(unittest.TestCase):
    def setUp(self):
        self.merge = IntentParser._merge_days

    def test_explicit_rules_not_overridden(self):
        # 规则显式解析“三天”= 3，LLM 给 1（或任何值）都不得覆盖
        self.assertEqual(self.merge(3, True, 1), 3)
        self.assertEqual(self.merge(3, True, 2), 3)

    def test_rule_default_filled_by_llm(self):
        # 规则未命中时长模式（默认 1，非显式），LLM 补缺 2 → 采用
        self.assertEqual(self.merge(1, False, 2), 2)
        self.assertEqual(self.merge(1, False, 0.5), 0.5)

    def test_invalid_llm_values_ignored(self):
        self.assertEqual(self.merge(1, False, "两天"), 1)   # 非数值
        self.assertEqual(self.merge(1, False, None), 1)
        self.assertEqual(self.merge(1, False, 9), 1)        # 越界
        self.assertEqual(self.merge(1, False, 0), 1)        # 越界
        self.assertEqual(self.merge(1, False, True), 1)     # 布尔视为非法

    def test_rules_parse_marks_explicit(self):
        parser = IntentParser(None)
        intent = parser._parse_rules("情侣黄山三日游")
        self.assertEqual(intent["days"], 3)
        self.assertTrue(intent["days_explicit"])
        intent2 = parser._parse_rules("九寨沟带孩子怎么玩")
        self.assertEqual(intent2["days"], 1)
        self.assertFalse(intent2["days_explicit"])


if __name__ == "__main__":
    unittest.main()
