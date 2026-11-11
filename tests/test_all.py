"""All unit tests for the offline pipeline, grouped by component."""
from __future__ import annotations

import ast
import csv
import json
import tempfile
import unittest
from pathlib import Path

from build_graph import _contrast_blocked, _norm_cond_m as _norm_cond, dedup_groups_from_quality
from compare_routes import entity_period
from dictionary import Candidate, Gazetteer, POIEntry, TransportEntry, load_transport_lexicon
from entity_identity import build_poi_lookup, canonical_name, read_aliases
from entity_rules import DictMatcher, contextual_facility_places, refined_dictionary, resolve_record_entities, time_entities
from extract_entities import main
from preprocess import canonicalize_url, clean_text, export_outputs, preprocess_records
from time_rules import TimeRules


RESOURCES = Path(__file__).resolve().parents[1] / "task2/resources"


def poi(pid, area, surface, canonical, subtype, parent="", priority=10, negative=""):
    return POIEntry(pid, area, surface, canonical, subtype, parent or canonical, "test", priority, negative)


def transport(tid, surface, normalized, subtype="其他", priority=8, linked="", negative_after=""):
    return TransportEntry(tid, surface, normalized, subtype, priority, False, "", negative_after, linked, "")


class DictionaryTests(unittest.TestCase):
    """Offline tests for gazetteer longest matching and overlap resolution."""

    def setUp(self) -> None:
        self.gazetteer = Gazetteer(
            [
                poi("P1", "九寨沟", "树正", "树正景区", "景区片区", priority=6),
                poi("P2", "九寨沟", "树正瀑布", "树正瀑布", "瀑布滩地"),
                poi("P3", "九寨沟", "树正群海", "树正群海", "湖泊水体"),
                poi("P4", "九寨沟", "诺日朗", "诺日朗景区", "景区片区", priority=6, negative="餐厅"),
                poi("P5", "九寨沟", "诺日朗中心站", "诺日朗中心站", "站点服务中心"),
                poi("P7", "黄山", "黄山", "黄山风景区", "景区"),
                poi("P8", "黄山", "光明顶", "光明顶", "山峰"),
                poi("P9", "黄山", "云谷", "云谷景区", "景区片区", priority=6),
            ],
            [
                transport("T1", "索道", "索道", "索道缆车"),
                transport("T2", "云谷索道", "索道", "索道缆车", 12, "云谷寺"),
                transport("T3", "观光车", "观光车", "景区车摆渡车"),
                transport("T4", "船", "游船", "水运", 4, negative_after="票|上"),
            ],
        )

    def test_longest_match(self) -> None:
        matches = self.gazetteer.iter_poi_matches("树正瀑布和树正群海", "九寨沟")
        surfaces = [match.surface for match in matches]
        self.assertEqual(surfaces, ["树正瀑布", "树正群海"])

    def test_area_isolation(self) -> None:
        matches = self.gazetteer.iter_poi_matches("庐山和黄山", "黄山")
        self.assertEqual([match.surface for match in matches], ["黄山"])
        self.assertNotIn("庐山", [match.normalized for match in matches])

    def test_negative_context(self) -> None:
        matches = self.gazetteer.iter_poi_matches("诺日朗餐厅用餐", "九寨沟")
        self.assertEqual(matches, [])

    def test_named_transport_linked_poi(self) -> None:
        matches = self.gazetteer.iter_transport_matches("坐云谷索道上山")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].surface, "云谷索道")
        self.assertEqual(matches[0].normalized, "索道")
        self.assertEqual(matches[0].linked_poi, "云谷寺")

    def test_transport_negative_after(self) -> None:
        self.assertEqual(self.gazetteer.iter_transport_matches("船票"), [])

    def test_area_helpers(self) -> None:
        self.assertTrue(self.gazetteer.has_area("黄山"))
        self.assertFalse(self.gazetteer.has_area("庐山"))
        self.assertEqual(self.gazetteer.area_entry_count("黄山"), 3)
        self.assertIn("光明顶", self.gazetteer.area_surfaces("黄山"))
        self.assertEqual(self.gazetteer.area_surfaces("庐山"), set())

    def test_overlap_resolution(self) -> None:
        candidates = self.gazetteer.iter_poi_matches("云谷索道", "黄山")
        candidates += self.gazetteer.iter_transport_matches("云谷索道")
        selected, suppressed = self.gazetteer.resolve_overlaps(candidates)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].type, "交通方式")
        self.assertEqual(selected[0].surface, "云谷索道")
        self.assertEqual(len(suppressed), 1)
        self.assertEqual(suppressed[0].surface, "云谷")


class EntityIdentityTests(unittest.TestCase):
    def test_route_display_name_maps_back_to_entity_canonical(self):
        lookup = build_poi_lookup([{"canonical": "玉屏景区", "scenic_areas": ["黄山"]}])
        self.assertEqual(lookup[("黄山", "玉屏")], "玉屏景区")
        self.assertNotIn(("九寨沟", "玉屏"), lookup)

    def test_ambiguous_display_shortening_fails(self):
        with self.assertRaises(ValueError):
            build_poi_lookup([{"canonical": "甲景区", "scenic_areas": ["某景区"]},
                              {"canonical": "甲", "scenic_areas": ["某景区"]}])

    def test_reviewed_aliases_are_idempotent(self):
        for name, area, target in [("耕织图景区", "颐和园", "耕织图"), ("树正磨坊", "九寨沟", "树正磨房")]:
            self.assertEqual(canonical_name(name, area), target)
            self.assertEqual(canonical_name(target, area), target)

    def test_different_place_and_facility_remain_distinct(self):
        self.assertEqual(canonical_name("五彩池", "九寨沟"), "五彩池")
        self.assertEqual(canonical_name("北海宾馆", "黄山"), "北海宾馆")
        self.assertEqual(canonical_name("耕织图景区", "黄山"), "耕织图景区")

    def test_conflicts_and_cycles_fail(self):
        for rows in ["黄山,A,B\n黄山,A,C\n", "黄山,A,B\n黄山,B,A\n"]:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "aliases.csv"
                path.write_text("area,alias,canonical\n" + rows, encoding="utf-8")
                with self.assertRaises(ValueError):
                    read_aliases(path)


class EntityRuleTests(unittest.TestCase):
    """Regressions discovered for the production entity rules."""

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
        """Counterexample set: longest-match priority, cross-type coexistence, facility compound guards, root scenic-area exclusion, and durations never swallowing transport."""
        # longest match: the sightseeing cable car merges into the long facility name; the "站" suffix does not block it
        self.assertEqual(self.surfaces("西海大峡谷观光缆车站"), ["西海大峡谷观光缆车"])
        # cross-type coexistence: adjacent POI and transport entities do not swallow each other
        self.assertEqual(self.surfaces("从云谷寺坐索道到白鹅岭"),
                         ["云谷寺", "索道", "白鹅岭"])
        # facility compound guard: the "北海" prefix of 北海宾馆 yields no entity; standalone "北海" does
        self.assertEqual(self.surfaces("北海宾馆旁边的北海好看"), ["北海"])
        # root scenic-area/admin name excluded by design: nested scenic-area names yield no POI entity
        self.assertEqual(self.surfaces("黄山市黄山区的黄山风景区"), [])
        # durations do not swallow transport entities
        self.assertEqual(self.surfaces("缆车5分钟一班"), ["缆车"])
        self.assertEqual([e["text"] for e in time_entities("缆车5分钟一班")], ["5分钟"])
        # named cableway vs generic cableway: the proper name wins and does not swallow the following POI
        self.assertEqual(self.surfaces("乘玉屏索道，再爬天都峰"), ["玉屏索道", "天都峰"])


REPO = Path(__file__).resolve().parents[1]
SCAN_GLOBS = ["task*/src/*.py", "common/*.py", "tests/*.py"]


def unreachable_after_return(path: Path) -> list[str]:
    hits = []
    tree = ast.parse(path.read_text(encoding="utf-8"))

    class V(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            self._block(node.body, f"def {node.name}")
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

        def _block(self, stmts, ctx):
            returned = False
            for s in stmts:
                if returned:
                    hits.append(f"{path.relative_to(REPO)}:{s.lineno} [{ctx}] "
                                f"return后不可达语句: {type(s).__name__}")
                self._recurse(s, ctx)
                if isinstance(s, (ast.Return, ast.Raise)):
                    returned = True

        def _recurse(self, s, ctx):
            if isinstance(s, (ast.If, ast.For, ast.While, ast.With)):
                for field in ("body", "orelse"):
                    blk = getattr(s, field, None)
                    if blk:
                        self._block(blk, ctx)
            elif isinstance(s, ast.Try):
                for field in ("body", "orelse", "finalbody"):
                    blk = getattr(s, field, None)
                    if blk:
                        self._block(blk, ctx)
                for h in s.handlers:
                    self._block(h.body, ctx)

    V().visit(tree)
    return hits


class TestNoDeadCode(unittest.TestCase):
    """Static guard: flag unreachable statements after return/raise across repository Python files."""

    def test_no_unreachable_after_return(self):
        files = sorted(set(f for g in SCAN_GLOBS for f in REPO.glob(g)))
        self.assertGreater(len(files), 20, "扫描范围异常：源文件数过少")
        hits = [h for f in files for h in unreachable_after_return(f)]
        self.assertEqual(hits, [], "发现 return 后不可达不可达代码（无输出且无异常报告风险）:\n" + "\n".join(hits))


class PipelineTests(unittest.TestCase):
    """Offline pipeline and character-offset checks for the final recognizer."""

    def test_pipeline_is_deterministic_and_offsets_are_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = [("A", "黄山", "下午三点半从光明顶坐云谷索道下山。"),
                       ("B", "九寨沟", "树正磨坊，步行到五花海，停留半小时。")]
            rows = [{"record_id": key, "scenic_area": area, "clean_content": text,
                     "clean_char_count": len(text), "source_platform": "测试", "text_type": "travelogue"}
                    for key, area, text in samples]
            source = root / "input.jsonl"
            source.write_text("".join(json.dumps(r, ensure_ascii=False)+"\n" for r in rows), encoding="utf-8")
            for target in ("a", "b"):
                self.assertEqual(main(["--input", str(source), "--output-dir", str(root/target)]), 0)
            output = root / "a/entities_refined.jsonl"
            self.assertEqual(output.read_bytes(), (root/"b/entities_refined.jsonl").read_bytes())
            results = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            for original, result in zip(rows, results):
                last = -1
                for entity in result["entities"]:
                    self.assertEqual(original["clean_content"][entity["start"]:entity["end"]], entity["text"])
                    self.assertGreaterEqual(entity["start"], last)
                    last = entity["end"]
            self.assertIn("树正磨房", [e["canonical"] for e in results[1]["entities"]])

    def test_empty_input_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/"empty.jsonl"
            source.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "为空"):
                main(["--input", str(source), "--output-dir", str(Path(directory)/"out")])


def fixture(**changes):
    row = {
        "record_id": "unit_001", "scenic_area": "黄山", "source_platform": "unit_test_fixture",
        "source_url": "https://example.org/article/1", "title": "黄山路线测试",
        "text_type": "official_route", "collected_at": "2026-10-28T12:00:00+08:00",
        "raw_content": "测试路线：上午8:30到达云谷寺→始信峰→光明顶，下午16:00下山。保留各站顺序及数值。",
        "raw_format": "text", "extraction_selector": "fixture", "raw_file": "fixture_only",
        "content_scope": "artificial unit test fixture; never collected data", "author": "", "published_at": "",
    }
    row.update(changes)
    return row


class CleaningTests(unittest.TestCase):
    """Regression tests for semantic preservation, validation and lossless exports.

    The strings below are artificial unit-test fixtures, not collected source data.
    """

    def test_html_noise_removed_without_losing_route_or_time(self):
        raw = '<nav>首页 导航</nav><article><p>黄山　路线：８：３０ 云谷寺→始信峰➡光明顶</p><p>海拔１８６０米&nbsp;下午１６：００下山。</p><script>steal()</script><p style="display:none">隐藏广告</p></article>'
        text, counts, _ = clean_text(raw, "html")
        self.assertIn("8:30 云谷寺→始信峰➡光明顶", text)
        self.assertIn("1860米 下午16:00下山", text)
        self.assertNotIn("导航", text)
        self.assertNotIn("steal", text)
        self.assertNotIn("隐藏广告", text)
        self.assertGreaterEqual(counts["html_noncontent_blocks_removed"], 3)

    def test_emoji_url_control_and_long_duplicates(self):
        long_line = "黄山路线经过始信峰和光明顶，游客需要根据自己的体力安排停留时间，下午沿原路返回云谷寺。"
        raw = "收藏 99\n\u200b🧭黄山：08:10→09:20\nhttps://example.org/noise\n" + long_line + "\n" + long_line + "\n光明顶\n光明顶"
        text, counts, _ = clean_text(raw)
        self.assertNotIn("example.org", text)
        self.assertNotIn("\u200b", text)
        self.assertNotIn("🧭", text)
        self.assertNotIn("收藏", text)
        self.assertIn("08:10→09:20", text)
        self.assertEqual(text.count(long_line.replace("，", ",")), 1)
        self.assertTrue(text.endswith("光明顶\n光明顶"))
        self.assertEqual(counts["duplicate_long_paragraphs_removed"], 1)

    def test_reject_empty_and_tracking_url_duplicate(self):
        rows, report, rejected, _ = preprocess_records([
            fixture(), fixture(record_id="unit_002", raw_content="<script>empty()</script>", raw_format="html"),
            fixture(record_id="unit_003", source_url="https://example.org/article/1?utm_source=test#comments", raw_content="另外一条黄山路线从玉屏楼出发，上午经过迎客松后，继续游览天都峰周边，下午乘坐索道返回山下。"),
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rejected), 2)
        self.assertTrue(any("empty_clean_content" in item["rejection_reasons"] for item in rejected))
        self.assertTrue(any(any(x.startswith("duplicate_source_url:") for x in item["rejection_reasons"]) for item in rejected))
        self.assertEqual(report["duplicate_source_urls_in_accepted"], 0)

    def test_bad_url_and_missing_field_are_not_accepted(self):
        rows, report, rejected, _ = preprocess_records([fixture(source_url="javascript:alert(1)", title="")])
        self.assertFalse(rows)
        self.assertIn("invalid_source_url", rejected[0]["rejection_reasons"])
        self.assertEqual(report["missing_required_fields_in_input"]["title"], 1)

    def test_mojibake_is_flagged_not_replaced_by_guessed_words(self):
        rows, report, _, _ = preprocess_records([fixture(raw_content=fixture()["raw_content"] + "原页面含有�与锟斤拷字符。")])
        self.assertIn("�", rows[0]["clean_content"])
        self.assertIn("锟斤拷", rows[0]["clean_content"])
        self.assertIn("replacement_character_present", rows[0]["quality_flags"])
        self.assertIn("suspected_encoding_corruption", rows[0]["quality_flags"])

    def test_url_identity_parameters_preserved(self):
        self.assertEqual(canonicalize_url("https://EXAMPLE.org/read?id=123&utm_source=x#abc"), "https://example.org/read?id=123")
        self.assertNotEqual(canonicalize_url("https://example.org/read?id=123"), canonicalize_url("https://example.org/read?id=124"))

    def test_unicode_numbers_units_and_route_semantics_survive(self):
        raw = "①路线Ⅰ：２²km，水温２０℃，水质H₂O。②路线Ⅱ：Ａ➕Ｂ➖Ｃ。✅可走 ✔推荐 ❌不走 ✘关闭 ⚠危险 🚫禁止入内 ❤装饰"
        text, counts, _ = clean_text(raw)
        self.assertIn("①路线Ⅰ:2²km", text)
        self.assertNotIn("22km", text)
        self.assertIn("20℃", text)
        self.assertIn("H₂O", text)
        self.assertIn("②路线Ⅱ:A➕B➖C", text)
        for semantic in ("✅可走", "✔推荐", "❌不走", "✘关闭", "⚠危险", "🚫禁止入内"):
            self.assertIn(semantic, text)
        self.assertNotIn("❤", text)
        self.assertGreater(counts["fullwidth_characters_normalized"], 0)

    def test_deduplication_does_not_conflate_opposite_semantic_symbols(self):
        common = "黄山上午从云谷寺出发，经过始信峰到达光明顶，下午根据体力选择后续游览路线。"
        rows, _, rejected, _ = preprocess_records([
            fixture(raw_content=common + "✔路段A➕路段B"),
            fixture(record_id="unit_002", source_url="https://example.org/article/2", raw_content=common + "✘路段A➖路段B"),
        ])
        self.assertEqual(len(rows), 2)
        self.assertFalse(rejected)

    def test_long_excel_cell_is_externalized_without_csv_json_loss(self):
        huge = fixture()["raw_content"] + "\n" + ("很长的黄山游览叙述。" * 4000)
        rows, report, rejected, examples = preprocess_records([fixture(raw_content=huge)])
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            export_outputs(out, rows, report, rejected, examples)
            written = json.loads((out / "dataset_clean.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(written["raw_content"], huge)
            with (out / "dataset_clean.csv").open(encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(next(csv.DictReader(handle))["raw_content"], huge)
            audit = json.loads((out / "quality_report.json").read_text(encoding="utf-8"))
            self.assertEqual(len(audit["xlsx_long_text_externalization"]), 2)
            for entry in audit["xlsx_long_text_externalization"]:
                self.assertEqual((out / entry["path"]).read_text(encoding="utf-8"), rows[0][entry["field"]])
                self.assertEqual((out / entry["path"]).read_bytes(), rows[0][entry["field"]].encode("utf-8"))
            self.assertFalse((out / "dataset_clean.xlsx").exists())
            self.assertEqual(audit["xlsx_authoring"]["engine"], "@oai/artifact-tool")


class TimePeriodTests(unittest.TestCase):
    def test_meridiem_and_range_use_normalized_time(self):
        self.assertEqual(entity_period({"subtype": "时刻", "text": "下午三点半", "normalized": "15:30"}), "下午")
        self.assertEqual(entity_period({"subtype": "时刻区间", "text": "15:20–15:30", "normalized": "15:20~15:30"}), "下午")

    def test_duration_does_not_change_current_period(self):
        self.assertIsNone(entity_period({"subtype": "时长", "text": "三小时", "normalized": "3小时"}))


class ClusterContrastTests(unittest.TestCase):
    """Contrast-term guard for conditional clustering: semantically opposed near-duplicates must not merge despite high Jaccard similarity."""

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
            ("黄山南大门", "黄山南大门入口"),   # different length, a condensed variant
            ("避开人流高峰", "避开人流高峰期"),  # different length
        ]
        for a, b in ok:
            self.assertFalse(_contrast_blocked(_norm_cond(a), _norm_cond(b)),
                             f"{a} / {b} 为合法变体，不应被守卫拦截")


class F05DedupTests(unittest.TestCase):
    """F05: near-duplicate records count edge support only once (key-name regression guard)."""

    def test_dedup_groups_built_from_real_key(self):
        quality = {"near_duplicate_pairs": [
            {"record_id_a": "A", "record_id_b": "B", "similarity": 0.95},
            {"record_id_a": "B", "record_id_b": "C", "similarity": 0.93},
        ]}
        groups, rec2grp = dedup_groups_from_quality(quality)
        # A-B-C should end up in one group (transitive closure)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0], {"A", "B", "C"})
        self.assertEqual(rec2grp, {"A": 0, "B": 0, "C": 0})

    def test_missing_key_means_no_groups(self):
        groups, rec2grp = dedup_groups_from_quality({})
        self.assertEqual(groups, [])
        self.assertEqual(rec2grp, {})


class TimeRuleTests(unittest.TestCase):
    """Offline unit tests for time rules."""

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

    def test_b07_weekday_not_duration(self) -> None:
        """Counterexample: weekday evenings do not yield a "五晚" duration (only period words); lodging "三晚" is still a duration."""
        for text in ("周五晚上", "周二早上", "周日晚上"):
            items = self.candidates(text)
            self.assertFalse([i for i in items if i.subtype == "时长"],
                             f"{text} 不应抽出时长实体")
        items = self.candidates("周五晚上")
        self.assertEqual([i.normalized for i in items], ["晚上"])
        items = self.candidates("住宿三晚")
        durations = [item for item in items if item.subtype == "时长"]
        self.assertEqual(durations[0].normalized, "3晚")

    def test_b07_midnight_is_extracted(self) -> None:
        """Counterexample: 半夜X点 must be extracted (半夜 was missing from the period vocabulary, and 12点 was misassigned to noon)."""
        items = self.candidates("半夜12点")
        self.assertTrue(items, "半夜12点应抽出时刻实体")
        self.assertEqual(items[0].subtype, "时刻")


class TransportRuleTests(unittest.TestCase):
    """Transport lexicon matching rules (offline)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = Gazetteer([], load_transport_lexicon(RESOURCES / "transport_lexicon.csv"))

    def surfaces(self, text: str) -> list[str]:
        return [candidate.surface for candidate in self.rules.iter_transport_matches(text)]

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
        items = self.rules.iter_transport_matches("坐云谷索道上山")
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
