"""实体 schema 校验测试（离线）。"""

from __future__ import annotations

import unittest

from schema import TYPE_POI, make_entity_id, validate_entity


def make_entity(text: str = "光明顶", start: int = 0, end: int = 3, **overrides):
    entity = {
        "entity_id": make_entity_id("TEST", start, end),
        "type": TYPE_POI,
        "subtype": "山峰",
        "surface": text[start:end],
        "normalized": text[start:end],
        "frequency_key": text[start:end],
        "source_kind": "tourist",
        "source_file": "task2/inputs/tourist_routes_clean.jsonl",
        "source_record_id": "TEST",
        "source_id_field": "record_id",
        "source_line": 1,
        "scenic_area": "黄山",
        "start": start,
        "end": end,
        "offset_unit": "unicode_codepoint",
        "text_sha256": "0" * 64,
        "record_char_count": len(text),
        "sentence_index": 0,
        "clause_index": 0,
        "context": text,
        "method": "dictionary_longest_match",
        "rule_id": "POI_GAZETTEER",
        "confidence": 0.98,
        "iteration": "test",
        "counts_as_time_node": True,
    }
    entity.update(overrides)
    return entity


class SchemaTests(unittest.TestCase):
    def test_valid_entity(self) -> None:
        text = "光明顶"
        self.assertEqual(validate_entity(make_entity(text), text), [])

    def test_missing_field(self) -> None:
        entity = make_entity()
        del entity["source_file"]
        self.assertIn("missing:source_file", validate_entity(entity, "光明顶"))

    def test_bad_type_and_subtype(self) -> None:
        errors = validate_entity(make_entity(type="PLACE"), "光明顶")
        self.assertIn("bad_type:PLACE", errors)
        errors = validate_entity(make_entity(subtype="不存在"), "光明顶")
        self.assertTrue(any(item.startswith("bad_subtype:") for item in errors))

    def test_offset_mismatch(self) -> None:
        errors = validate_entity(make_entity("光明顶", 0, 2, surface="光明顶"), "光明顶")
        self.assertIn("offset_surface_mismatch", errors)

    def test_bad_offset_range(self) -> None:
        errors = validate_entity(make_entity("光明顶", 0, 10), "光明顶")
        self.assertTrue(any(item.startswith("offset_out_of_range:") for item in errors))

    def test_bad_confidence(self) -> None:
        errors = validate_entity(make_entity(confidence=1.5), "光明顶")
        self.assertTrue(any(item.startswith("bad_confidence:") for item in errors))

    def test_bad_counts_flag(self) -> None:
        errors = validate_entity(make_entity(counts_as_time_node="yes"), "光明顶")
        self.assertIn("bad_counts_as_time_node", errors)

    def test_generic_methods_are_valid(self) -> None:
        for method in ("generic_suffix", "area_name_match"):
            self.assertEqual(validate_entity(make_entity(method=method), "光明顶"), [])

    def test_source_kinds_can_be_configured(self) -> None:
        self.assertEqual(
            validate_entity(make_entity(source_kind="blog"), "光明顶", {"blog"}), []
        )
        self.assertIn(
            "bad_source_kind:blog",
            validate_entity(make_entity(source_kind="blog"), "光明顶"),
        )


if __name__ == "__main__":
    unittest.main()
