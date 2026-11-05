# -*- coding: utf-8 -*-
"""H05：数据版本指纹——评估产物绑定其输入数据的 SHA256 前缀，
旧结果未重算时不再被当作新版本证据。"""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SOURCES = {
    "dataset_clean": "task1/data/processed/dataset_clean.jsonl",
    "entity_dictionary": "task2/output/exp2/entity_dictionary.json",
    "entities_refined": "task2/output/exp2/entities_refined.jsonl",
}


def data_fingerprints() -> dict:
    out = {}
    for key, rel in SOURCES.items():
        p = ROOT / rel
        out[key] = hashlib.sha256(p.read_bytes()).hexdigest()[:12] if p.exists() else None
    return out
