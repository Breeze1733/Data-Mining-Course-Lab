"""配置加载、合并与路径解析测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from config import DEFAULTS, load_config, resolve_path, scope_sources, source_kinds


class ConfigTests(unittest.TestCase):
    def test_defaults_match_shipped_config(self) -> None:
        config = load_config()
        self.assertEqual(source_kinds(config), ["tourist", "official_route", "official_document"])
        self.assertEqual(config["top_n"]["poi"], DEFAULTS["top_n"]["poi"])
        self.assertIn("analysis", config["scope"]["scopes"])

    def test_file_override_and_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "input": {"dir": "my_inputs"},
                        "top_n": {"poi": 7},
                        "poi_fallback": {"mode": "always"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = load_config(path)
            self.assertEqual(config["top_n"]["poi"], 7)
            self.assertEqual(config["top_n"]["transport"], DEFAULTS["top_n"]["transport"])
            self.assertEqual(config["poi_fallback"]["mode"], "always")
            self.assertEqual(resolve_path(config, config["input"]["dir"]), (root / "my_inputs").resolve())

    def test_invalid_source_kind_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(
                json.dumps({"input": {"sources": {"bad kind": {"file": "x.jsonl", "id_field": "id"}}}}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_config(path)

    def test_scope_can_be_source_list(self) -> None:
        config = load_config()
        self.assertEqual(scope_sources(config, "tourist"), {"tourist"})
        self.assertEqual(scope_sources(config, "tourist,blog"), {"tourist", "blog"})


if __name__ == "__main__":
    unittest.main()
