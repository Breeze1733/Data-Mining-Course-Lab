# -*- coding: utf-8 -*-
"""H04：正式产物的原子写出——先写临时文件再 os.replace，杜绝半写文件污染正式结果。

Windows 下 os.replace 对刚关闭的临时文件偶发 PermissionError（WinError 5，
杀毒/索引器短暂持锁，实测约数轮触发一次，曾致 unittest 随机红）。统一在此小退避重试。
"""
import os
import time
from pathlib import Path


def _replace_with_retry(tmp: Path, path: Path, attempts: int = 5, delay: float = 0.05) -> None:
    for i in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def atomic_write_text(path: Path | str, text: str, encoding: str = "utf-8",
                      newline: str | None = None) -> None:
    """newline 语义与 open 一致：None=平台翻译（JSON 等默认）；""=原样写出（CSV 的 CRLF 由
    csv.writer 自己产生，二次翻译会产生
）。"""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding=encoding, newline=newline) as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    _replace_with_retry(tmp, path)
