# -*- coding: utf-8 -*-
"""H04：正式产物的原子写出——先写临时文件再 os.replace，杜绝半写文件污染正式结果。"""
import os
from pathlib import Path


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
    os.replace(tmp, path)
