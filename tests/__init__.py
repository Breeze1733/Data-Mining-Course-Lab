# 统一路径设置：所有测试共享，不需要逐文件配置
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in ("task1/src", "task1/scripts", "task2/src", "task3/src",
           "task4/src", "task5/src", "task6/src", "task7/src", "common"):
    _p = str(_ROOT / _p)
    if _p not in sys.path:
        sys.path.insert(0, _p)
