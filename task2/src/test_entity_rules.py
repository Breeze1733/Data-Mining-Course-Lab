"""Regressions discovered for the production entity rules."""
import unittest

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


if __name__ == "__main__":
    unittest.main()
