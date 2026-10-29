"""时间规则单元测试（离线）。"""

from __future__ import annotations

import unittest
from pathlib import Path

from dictionary import Candidate
from time_rules import TimeRules

RESOURCES = Path(__file__).resolve().parents[1] / "resources"


class TimeRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = TimeRules.load(RESOURCES / "time_rules.json")

    def candidates(self, text: str) -> list[Candidate]:
        return self.rules.extract(text)

    def test_clock_range_is_one_entity(self) -> None:
        items = self.candidates("7:00-8:10 乘车")
        ranges = [item for item in items if item.subtype == "时刻区间"]
        self.assertEqual(len(ranges), 1)
        self.assertEqual(ranges[0].normalized, "07:00-08:10")
        self.assertEqual(ranges[0].surface, "7:00-8:10")

    def test_period_clock_merge(self) -> None:
        items = self.candidates("下午3点半下山")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].normalized, "15:30")
        self.assertEqual(items[0].subtype, "时刻")

    def test_evening_clock(self) -> None:
        items = self.candidates("晚上8点到达")
        self.assertEqual(items[0].normalized, "20:00")

    def test_noon_clock(self) -> None:
        items = self.candidates("中午1点吃饭")
        self.assertEqual(items[0].normalized, "13:00")

    def test_ambiguous_clock(self) -> None:
        items = self.candidates("6点出发")
        self.assertTrue(items[0].ambiguous_meridiem)
        self.assertEqual(items[0].normalized, "06:00")

    def test_duration_is_separate(self) -> None:
        items = self.candidates("游览2小时后下山")
        durations = [item for item in items if item.subtype == "时长"]
        self.assertEqual(len(durations), 1)
        self.assertEqual(durations[0].normalized, "2小时")
        self.assertFalse(durations[0].counts_as_time_node)

    def test_half_hour(self) -> None:
        items = self.candidates("半小时后集合")
        durations = [item for item in items if item.subtype == "时长"]
        self.assertEqual(durations[0].normalized, "0.5小时")

    def test_more_than_one_hour(self) -> None:
        items = self.candidates("走了一个多小时")
        durations = [item for item in items if item.subtype == "时长"]
        self.assertEqual(durations[0].normalized, ">1小时")

    def test_first_day_not_duration(self) -> None:
        items = self.candidates("第一天进沟")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].subtype, "相对日")
        self.assertEqual(items[0].normalized, "第1天")

    def test_date(self) -> None:
        items = self.candidates("10月30日到达")
        self.assertEqual(items[0].subtype, "日期")
        self.assertEqual(items[0].normalized, "10-30")

    def test_date_range(self) -> None:
        items = self.candidates("5月6日-9日游玩")
        self.assertEqual(items[0].subtype, "日期区间")
        self.assertEqual(items[0].normalized, "05-06~05-09")

    def test_month_list(self) -> None:
        items = self.candidates("三、四月最合适")
        self.assertEqual(items[0].subtype, "月份区间")
        self.assertEqual(items[0].normalized, "03-04月")

    def test_day_label(self) -> None:
        items = self.candidates("Day 2 去长海")
        self.assertEqual(items[0].subtype, "相对日")
        self.assertEqual(items[0].normalized, "第2天")

    def test_video_00_excluded(self) -> None:
        items = self.candidates("00:00\n早上8点出发")
        self.assertFalse(any(item.surface == "00:00" for item in items))
        self.assertTrue(any(item.normalized == "08:00" for item in items))

    def test_video_pair_excluded(self) -> None:
        items = self.candidates("00:00/00:00")
        self.assertEqual(items, [])

    def test_product_and_distance_not_time(self) -> None:
        self.assertEqual(self.candidates("一日游"), [])
        self.assertEqual(self.candidates("10米"), [])

    def test_duration_month(self) -> None:
        items = self.candidates("住了一个月")
        durations = [item for item in items if item.subtype == "时长"]
        self.assertEqual(durations[0].normalized, "1个月")

    def test_half_day(self) -> None:
        items = self.candidates("玩了半天")
        durations = [item for item in items if item.subtype == "时长"]
        self.assertEqual(durations[0].normalized, "0.5天")

    def test_yidian_adverb_not_time(self) -> None:
        self.assertEqual(self.candidates("一点也不夸张"), [])
        self.assertEqual(self.candidates("半点办法都没有"), [])

    def test_period_yidian_is_time(self) -> None:
        items = self.candidates("下午一点到达")
        self.assertEqual(items[0].normalized, "13:00")


if __name__ == "__main__":
    unittest.main()
