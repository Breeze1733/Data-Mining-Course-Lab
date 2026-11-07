# -*- coding: utf-8 -*-
"""条件聚类对比词守卫——语义相斥的近文本不得因 Jaccard 高而合并。"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "task6/src"))
from build_graph import _contrast_blocked, _norm_cond_m as _norm_cond  # noqa: E402


class ClusterContrastTests(unittest.TestCase):
    def test_contrast_pairs_blocked(self):
        cases = [
            ("雨天路滑慢行", "雪天路滑慢行"),
            ("早上排队人多", "早上排队人少"),
            ("山上住宿方便", "山下住宿方便"),
        ]
        for a, b in cases:
            self.assertTrue(_contrast_blocked(_norm_cond(a), _norm_cond(b)),
                            f"{a} / {b} 语义相斥，不得合并")

    def test_variants_still_merge(self):
        ok = [
            ("黄山南大门", "黄山南大门入口"),   # 长度不同，属精简变体
            ("避开人流高峰", "避开人流高峰期"),  # 长度不同
        ]
        for a, b in ok:
            self.assertFalse(_contrast_blocked(_norm_cond(a), _norm_cond(b)),
                             f"{a} / {b} 为合法变体，不应被守卫拦截")


if __name__ == "__main__":
    unittest.main()
