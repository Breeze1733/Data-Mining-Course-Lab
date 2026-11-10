# -*- coding: utf-8 -*-
"""Data version fingerprints -- evaluation artifacts are bound to the SHA256 prefix of
their input data, so stale results that were not recomputed no longer pass as
new-version evidence."""
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
