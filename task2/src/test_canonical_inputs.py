import json
import tempfile
import unittest
from pathlib import Path
from prepare_canonical_inputs import main


class CanonicalInputTests(unittest.TestCase):
    def test_text_identity_and_partition_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "dataset.jsonl"
            rows = [{"record_id": "T1", "text_type": "travelogue", "scenic_area": "任意景区", "clean_content": "上午到甲桥→乙湖。"},
                    {"record_id": "O1", "text_type": "official_route", "scenic_area": "任意景区", "clean_content": "官方正文。"}]
            source.write_text("".join(json.dumps(r, ensure_ascii=False)+"\n" for r in rows), encoding="utf-8")
            main(["--dataset", str(source), "--output-dir", str(root / "out")])
            tourist = json.loads((root / "out/tourist_routes_clean.jsonl").read_text(encoding="utf-8"))
            official = json.loads((root / "out/official_documents_clean.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(tourist["cleaned_text"], rows[0]["clean_content"])
            self.assertEqual(official["evidence_id"], "O1")
            self.assertTrue(official["accepted"])

    def test_missing_optional_routes_do_not_import_repository_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "dataset.jsonl"
            source.write_text(json.dumps({"record_id": "T1", "text_type": "travelogue", "clean_content": "游记。"}), encoding="utf-8")
            main(["--dataset", str(source), "--official-routes", str(root / "absent.jsonl"), "--output-dir", str(root / "out")])
            self.assertEqual((root / "out/official_routes_clean.jsonl").read_text(encoding="utf-8"), "")
