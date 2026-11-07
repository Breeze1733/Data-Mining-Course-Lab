"""Regressions discovered for the production entity rules."""
import unittest

import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / "task2/src"))
from entity_rules import DictMatcher, refined_dictionary, time_entities, contextual_facility_places, resolve_record_entities


class EntityRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        entries, stopwords, _ = refined_dictionary()
        cls.matcher = DictMatcher(entries, stopwords)

    def surfaces(self, text, area="黄山"):
        return [e["text"] for e in self.matcher.find(text, scenic=area)]

    def test_unrelated_suffix_does_not_remove_mode(self):
        self.assertEqual(self.surfaces("坐高铁，站在窗边"), ["高铁"])
        self.assertEqual(self.surfaces("坐观光车，到站后步行"), ["观光车", "步行"])

    def test_unrelated_negation_does_not_remove_mode(self):
        self.assertEqual(self.surfaces("酒店不在附近步行要40分钟"), ["步行"])

    def test_local_compound_guards_and_cloud_tickets(self):
        self.assertEqual(self.surfaces("步行街、登山杖、地铁口、索道票"), [])

    def test_named_facility_and_longest_overlap(self):
        self.assertEqual(self.surfaces("云谷索道下站乘缆车"), ["云谷索道", "缆车"])
        self.assertEqual(self.surfaces("西海大峡谷观光缆车"), ["西海大峡谷观光缆车"])

    def test_cross_area_flag_is_preserved(self):
        entity = self.matcher.find("前往宏村", scenic="九寨沟")[0]
        self.assertEqual(entity["text"], "宏村")
        self.assertFalse(entity["in_scenic"])

    def test_chinese_time_and_next_day(self):
        self.assertEqual([e["text"] for e in time_entities("次日下午三点半，7点到9点")],
                         ["次日", "下午三点半", "7点到9点"])

    def test_facility_proximity_is_context_only(self):
        self.assertEqual(self.surfaces("北海宾馆附近岔路多"), [])
        places = contextual_facility_places("北海宾馆附近岔路多", "黄山")
        self.assertEqual([e["canonical"] for e in places], ["北海"])
        self.assertEqual(contextual_facility_places("北海宾馆提供早餐", "黄山"), [])

    def test_duration_cannot_consume_known_poi(self):
        text = "5 天都峰"
        entities = resolve_record_entities(self.matcher.find(text, "黄山") + time_entities(text))
        self.assertEqual([e["text"] for e in entities], ["天都峰"])

    def test_overlap_policy_preserves_poi(self):
        from dictionary import Candidate, Gazetteer
        duration = Candidate(0, 3, "5 天", "时间节点", "时长", "5天", "5天", "regex", "DURATION")
        poi = Candidate(2, 5, "天都峰", "景点POI", "山峰", "天都峰", "天都峰", "dictionary_longest_match", "POI")
        selected, suppressed = Gazetteer([], []).resolve_overlaps([duration, poi])
        self.assertEqual(selected, [poi])
        self.assertIn(duration, suppressed)

    def test_b09_overlap_counterexamples(self):
        """ 反例组：长词优先、跨类型共存、设施复合词守卫、根景区设计排除、时长不吞交通。"""
        # 长词优先：观光缆车并入设施长名，"站"后缀不阻断
        self.assertEqual(self.surfaces("西海大峡谷观光缆车站"), ["西海大峡谷观光缆车"])
        # 跨类型共存：POI 与交通相邻不互吞
        self.assertEqual(self.surfaces("从云谷寺坐索道到白鹅岭"),
                         ["云谷寺", "索道", "白鹅岭"])
        # 设施复合词守卫：北海宾馆的"北海"前缀不出实体，独立"北海"正常出
        self.assertEqual(self.surfaces("北海宾馆旁边的北海好看"), ["北海"])
        # 根景区/行政名设计排除：嵌套景区名整体不出 POI 实体
        self.assertEqual(self.surfaces("黄山市黄山区的黄山风景区"), [])
        # 时长不吞交通实体
        self.assertEqual(self.surfaces("缆车5分钟一班"), ["缆车"])
        self.assertEqual([e["text"] for e in time_entities("缆车5分钟一班")], ["5分钟"])
        # 命名索道 vs 通用索道：专名优先且不吞后续 POI
        self.assertEqual(self.surfaces("乘玉屏索道，再爬天都峰"), ["玉屏索道", "天都峰"])


if __name__ == "__main__":
    unittest.main()
