import unittest
from time_periods import entity_period


class TimePeriodTests(unittest.TestCase):
    def test_meridiem_and_range_use_normalized_time(self):
        self.assertEqual(entity_period({"subtype": "时刻", "text": "下午三点半", "normalized": "15:30"}), "下午")
        self.assertEqual(entity_period({"subtype": "时刻区间", "text": "15:20–15:30", "normalized": "15:20~15:30"}), "下午")

    def test_duration_does_not_change_current_period(self):
        self.assertIsNone(entity_period({"subtype": "时长", "text": "三小时", "normalized": "3小时"}))
