"""最终识别器的离线管线与字符位置检查。"""
import json
import tempfile
import unittest
from pathlib import Path
from extract_entities import main


class PipelineTests(unittest.TestCase):
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
