"""task2 的路径常量与输入目录解析。

用法:
    from paths import DEFAULT_INPUT_DIR, TASK1_PROCESSED, OUTPUTS_DIR

约定:
    TASK2_ROOT   = <repo>/task2
    REPO_ROOT    = <repo>
    DEFAULT_INPUT_DIR = <repo>/task2/inputs   （task1 的冻结快照）
    TASK1_PROCESSED   = <repo>/task1/data/processed
"""

from __future__ import annotations

from pathlib import Path

TASK2_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TASK2_ROOT.parent

DEFAULT_INPUT_DIR = TASK2_ROOT / "inputs"
TASK1_PROCESSED = REPO_ROOT / "task1" / "data" / "processed"
RESOURCES_DIR = TASK2_ROOT / "resources"
DATA_DIR = TASK2_ROOT / "data"
OUTPUTS_DIR = TASK2_ROOT / "outputs"
LOGS_DIR = TASK2_ROOT / "logs"
CONFIG_FILE = TASK2_ROOT / "config.json"

# 默认快照文件名，仅为兼容旧调用；实际来源规格由 config.json 决定。
INPUT_FILES = (
    "tourist_routes_clean.jsonl",
    "official_routes_clean.jsonl",
    "official_documents_clean.jsonl",
)


def repo_relative(path: Path) -> str:
    """把仓库内路径转成 POSIX 形式，便于写进 JSON。"""
    path = path.resolve()
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()
