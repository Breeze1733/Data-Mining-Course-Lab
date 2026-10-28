"""位置与切分工具。

硬约束:
    - 偏移基于原始 cleaned_text，不修改文本；
    - start 含、end 不含，单位为 Unicode code point；
    - 任何实体写出前必须满足 text[start:end] == surface。
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

SENTENCE_END = re.compile(r"[。！？!?；;\n]+")
CLAUSE_DELIM = re.compile(r"[，,、：:；;→➡➔⇒\s]+")
EDGE_TRIM = " \t\r\n，,。；;、：:→➡➔⇒-—–~～()（）[]【】<>《》\"'“”‘’"


@dataclass(frozen=True)
class Span:
    start: int
    end: int


def build_sentence_spans(text: str) -> list[Span]:
    spans: list[Span] = []
    start = 0
    for match in SENTENCE_END.finditer(text):
        end = match.end()
        if end > start:
            spans.append(Span(start, end))
        start = end
    if start < len(text):
        spans.append(Span(start, len(text)))
    if not spans and text:
        spans.append(Span(0, len(text)))
    return spans


def build_clause_spans(text: str, start: int, end: int) -> list[Span]:
    spans: list[Span] = []
    cursor = start
    for match in CLAUSE_DELIM.finditer(text, start, end):
        if match.start() > cursor:
            spans.append(Span(cursor, match.start()))
        cursor = match.end()
    if cursor < end:
        spans.append(Span(cursor, end))
    if not spans:
        spans.append(Span(start, end))
    return spans


def _index_of(spans: list[Span], position: int, *, allow_end: bool = False) -> int:
    if not spans:
        return 0
    for index, span in enumerate(spans):
        if span.start <= position < span.end:
            return index
    if allow_end and position == spans[-1].end:
        return len(spans) - 1
    # 位置落在分隔符上：归到前一个 span
    for index in range(len(spans) - 1, -1, -1):
        if spans[index].start <= position:
            return index
    return 0


def locate(text: str, start: int, end: int) -> tuple[int, int, int, int, list[Span], list[Span]]:
    """返回 (sentence_index, clause_index, sentence_start, sentence_end, sentences, clauses)。"""
    sentences = build_sentence_spans(text)
    sentence_index = _index_of(sentences, start, allow_end=True)
    sentence = sentences[sentence_index]
    clauses = build_clause_spans(text, sentence.start, sentence.end)
    clause_index = _index_of(clauses, start, allow_end=True)
    return (
        sentence_index,
        clause_index,
        sentence.start,
        sentence.end,
        sentences,
        clauses,
    )


def trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start] in EDGE_TRIM:
        start += 1
    while end > start and text[end - 1] in EDGE_TRIM:
        end -= 1
    return start, end


def context_window(text: str, start: int, end: int, radius: int = 20) -> tuple[str, int, int]:
    context_start = max(0, start - radius)
    context_end = min(len(text), end + radius)
    return text[context_start:context_end], context_start, context_end


def assert_span(text: str, start: int, end: int, surface: str) -> None:
    if not (0 <= start < end <= len(text)):
        raise AssertionError(f"非法偏移: start={start}, end={end}, len={len(text)}")
    if text[start:end] != surface:
        raise AssertionError(
            f"偏移与文本不一致: {surface!r} != {text[start:end]!r} "
            f"(start={start}, end={end})"
        )


def build_length_preserving_view(text: str) -> tuple[str, list[int]]:
    """全角数字/字母/冒号逐一映射为 ASCII，长度不变，index_map 为恒等映射。

    只用于让正则同时兼容全角冒号；最终 surface 与偏移仍使用原串。
    """
    chars: list[str] = []
    for char in text:
        code = ord(char)
        if 0xFF10 <= code <= 0xFF19:  # ０-９
            chars.append(chr(code - 0xFF10 + ord("0")))
        elif 0xFF21 <= code <= 0xFF3A:  # Ａ-Ｚ
            chars.append(chr(code - 0xFF21 + ord("A")))
        elif 0xFF41 <= code <= 0xFF5A:  # ａ-ｚ
            chars.append(chr(code - 0xFF41 + ord("a")))
        elif char == "：":
            chars.append(":")
        else:
            chars.append(char)
    return "".join(chars), list(range(len(text)))
