# -*- coding: utf-8 -*-
"""F05：近重复游客对同一条边只计一次支持数（键名回归守卫）。"""
import unittest
import sys
from pathlib import Path

from build_graph import dedup_groups_from_quality  # noqa: E402


class F05DedupTests(unittest.TestCase):
    def test_dedup_groups_built_from_real_key(self):
        quality = {"near_duplicate_pairs": [
            {"record_id_a": "A", "record_id_b": "B", "similarity": 0.95},
            {"record_id_a": "B", "record_id_b": "C", "similarity": 0.93},
        ]}
        groups, rec2grp = dedup_groups_from_quality(quality)
        # A-B-C 应并入同一组（传递闭包）
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0], {"A", "B", "C"})
        self.assertEqual(rec2grp, {"A": 0, "B": 0, "C": 0})

    def test_missing_key_means_no_groups(self):
        groups, rec2grp = dedup_groups_from_quality({})
        self.assertEqual(groups, [])
        self.assertEqual(rec2grp, {})


if __name__ == "__main__":
    unittest.main()
