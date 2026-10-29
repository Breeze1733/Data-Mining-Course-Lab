"""Compatibility import of the single shared name-normalization module."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
from entity_identity import normalize
__all__ = ["normalize"]
