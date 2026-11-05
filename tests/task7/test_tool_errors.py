# -*- coding: utf-8 -*-
"""G09：工具错误参数的稳定结构化返回（离线单测）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "task7" / "src"))
from graph_tools import GraphTools  # noqa: E402


class TestToolErrors(unittest.TestCase):
    def setUp(self):
        self.t = GraphTools()

    def test_bad_scenic_structured_error(self):
        for tool, args in (("query_pois", {"scenic": "泰山"}),
                           ("query_route", {"scenic": "泰山", "days": 1}),
                           ("query_conditions", {"scenic": "泰山"})):
            with self.subTest(tool=tool):
                res = getattr(self.t, tool)(**args)
                self.assertIn("error", res)
                self.assertIn("泰山", res["error"])

    def test_unknown_poi_structured_error(self):
        res = self.t.query_order("黄山", "不存在的景点")
        self.assertIn("error", res)
        res2 = self.t.query_path("黄山", "不存在A", "不存在B")
        self.assertIn("error", res2)

    def test_limit_validation(self):
        for bad in (-5, 0, "abc", None):
            res = self.t.query_pois("黄山", None, bad)
            self.assertIn("error", res)
            self.assertNotIn("pois", res)
        res = self.t.query_pois("黄山", None, 3)
        self.assertIn("pois", res)
        self.assertLessEqual(len(res["pois"]), 3)

    def test_cross_scenic_path_structured_error(self):
        res = self.t.query_path("黄山", "长海", "迎客松")
        self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main()
