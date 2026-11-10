# -*- coding: utf-8 -*-
"""Atomic write for official artifacts -- write to a temp file first, then os.replace,
so half-written files can never pollute official results.

On Windows, os.replace occasionally raises PermissionError (WinError 5) on a just-closed
temp file (antivirus/indexer briefly holds the lock; observed roughly once every few
rounds, and it once caused random unittest failures). A small backoff retry is applied
uniformly here.
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
    """newline semantics match open: None=platform translation (the default for JSON etc.);
    ""=write out as-is (CSV's CRLF is produced by csv.writer itself; a second
translation would corrupt it)."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding=encoding, newline=newline) as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    _replace_with_retry(tmp, path)
