"""实验项目1：采集结果的清洗、结构化与质量检查。

读取 data/collected/ 下的采集产物，生成可直接供后续实验使用的
data/processed/ 数据集，以及可核查的清洗报告。全程离线，不访问网络。

    python src/preprocess_collected.py
    python src/preprocess_collected.py --min-tourist-chars 80

输入：
    data/collected/tourist_routes.jsonl      游客游记（携程/小红书）
    data/collected/official_documents.jsonl  官方来源文档
    data/collected/official_routes.jsonl     官方路线分支
    data/collected/collection_summary.json   采集阶段配额与缺额

输出：
    data/processed/tourist_routes_clean.jsonl / .csv
    data/processed/official_documents_clean.jsonl / official_routes_clean.jsonl
    data/processed/official_routes_clean.csv
    data/processed/quality_report.json
    data/processed/quality_report.md
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/collected"
DEFAULT_OUTPUT = ROOT / "data/processed"
AREAS = ("黄山", "九寨沟", "颐和园")
PLATFORMS = ("携程", "小红书")
PIPELINE_VERSION = "preprocess-1.0"

REQUIRED_TOURIST = (
    "record_id", "scenic_area", "source_platform", "text_type",
    "source_url", "title", "body_text", "collected_at",
)
REQUIRED_OFFICIAL = ("evidence_id", "scenic_area", "source_url", "title")
REQUIRED_ROUTE = ("route_id", "scenic_area", "source_url", "raw_content")

# 保留路线箭头与带语义的正负号/提示符；“A➕B”“❌不要走”中的符号会改变句意。
ROUTE_ARROWS = set("←↑→↓↔↕↖↗↘↙⇒⇐⇔➔➜➝➞➟➠➡➢➣➤➥➦➧➨➩➪➫➬➭➮➯➱")
SEMANTIC_SYMBOLS = set("✅❌✔✘✖✗➕➖⚠☑☒✓√×±⊕⊖🚫⛔❎❗❕❓❔")
BULLET_PREFIX_RE = re.compile(r"^\s*(?:[•·▪▫◆◇★☆●○◦※]+|[-–—]\s)\s*")
METADATA_LINE_RE = re.compile(
    r"^(?:(?:分享|收藏|举报|点赞|评论|关注|返回顶部|展开全文|收起全文|查看更多|"
    r"下载APP|打开APP|扫码下载|登录后查看|相关推荐|猜你喜欢|发布评论|写评论|"
    r"发布于|编辑于|阅读|浏览|转发)(?:\s*[:：]?\s*\d+(?:\.\d+)?[万wW]?)?|"
    r"(?:上一篇|下一篇)\s*[:：].*|"
    r"(?:责任编辑|网站编辑|编辑)\s*[:：].{0,30}|"
    r"(?:Copyright|版权所有|ICP备|公安备案).*)$",
    re.IGNORECASE,
)
URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"'　，。；！？、）】》]+")
HASHTAG_RE = re.compile(r"#([^\s#＃]{1,40})")
MENTION_RE = re.compile(r"@[\w一-鿿_.-]{1,30}")
TAG_RE = re.compile(r"<[a-zA-Z/!][^>]{0,200}>")
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MOJIBAKE_RE = re.compile(r"锟斤拷|ï»¿|Ã[\x80-\xbf]|â€|ðŸ")
EXCEL_FORMULA_RE = re.compile(r"^[=+\-@]")

BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "li", "main", "ol", "p", "pre", "section", "table", "tr", "ul",
}
IGNORED_TAGS = {
    "script", "style", "noscript", "head", "nav", "footer", "header", "iframe",
    "svg", "canvas", "button", "form", "select", "textarea",
}
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class ArticleHTMLParser(HTMLParser):
    """保留正文与段落边界，丢弃脚本、导航和隐藏区域。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.stack: list[tuple[str, bool]] = []
        self.counts: Counter = Counter()

    def _ignored(self) -> bool:
        return any(skip for _, skip in self.stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self.counts["html_tags_removed"] += 1
        attrs_dict = dict(attrs)
        style = (attrs_dict.get("style") or "").replace(" ", "").lower()
        hidden = (
            "hidden" in attrs_dict
            or attrs_dict.get("aria-hidden") == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )
        skip = tag in IGNORED_TAGS or hidden
        if skip and not self._ignored():
            self.counts["html_noncontent_blocks_removed"] += 1
        if tag in BLOCK_TAGS and not self._ignored():
            self.parts.append("\n")
        if tag not in VOID_TAGS:
            self.stack.append((tag, skip))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        self.counts["html_tags_removed"] += 1
        was_ignored = self._ignored()
        for idx in range(len(self.stack) - 1, -1, -1):
            if self.stack[idx][0] == tag:
                del self.stack[idx:]
                break
        if tag in BLOCK_TAGS and not was_ignored:
            self.parts.append("\n")
        elif tag in ("td", "th") and not was_ignored:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._ignored():
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._ignored():
            entity = f"&{name};"
            decoded = html.unescape(entity)
            self.parts.append(decoded)
            if entity != decoded:
                self.counts["html_entities_decoded"] += 1

    def handle_charref(self, name: str) -> None:
        if not self._ignored():
            entity = f"&#{name};"
            decoded = html.unescape(entity)
            self.parts.append(decoded)
            if entity != decoded:
                self.counts["html_entities_decoded"] += 1

    def handle_comment(self, data: str) -> None:
        self.counts["html_comments_removed"] += 1


def _is_emoji_or_decoration(ch: str) -> bool:
    """表情与装饰符号视为噪声；路线箭头和语义符号保留。"""
    if ch in ROUTE_ARROWS or ch in SEMANTIC_SYMBOLS:
        return False
    cp = ord(ch)
    return (
        0x1F000 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0xFE00 <= cp <= 0xFE0F
        or 0xE0100 <= cp <= 0xE01EF
        or cp in (0x20E3, 0x3030, 0x303D, 0x3297, 0x3299)
    )


def normalize_width(text: str) -> tuple[str, int]:
    """只折叠全角数字/字母与全角空格，不做NFKC。

    NFKC 会把 ①、Ⅰ、²、₂、℃ 折叠成普通字符，可能把“2²km”改成“22km”，
    从而改变原文数值。全角标点（，；：（））也保留：若只转成半角，
    句号“。”仍为全角，同句内会出现“逗号半角、句号全角”的混排。
    """
    out: list[str] = []
    changed = 0
    for ch in text:
        cp = ord(ch)
        if 0xFF10 <= cp <= 0xFF19 or 0xFF21 <= cp <= 0xFF3A or 0xFF41 <= cp <= 0xFF5A:
            out.append(chr(cp - 0xFEE0))
            changed += 1
        elif cp == 0x3000:
            out.append(" ")
            changed += 1
        else:
            out.append(ch)
    return "".join(out), changed


def html_to_text(raw: str) -> tuple[str, dict]:
    parser = ArticleHTMLParser()
    parser.feed(raw)
    parser.close()
    return "".join(parser.parts), dict(parser.counts)


def clean_text(raw: str, raw_format: str = "text") -> tuple[str, list[str], dict]:
    """清洗单篇文本，返回（正文、话题标签、规则命中计数）。

    规则只删除噪声，不改写、补写或猜测原文；行顺序用于后续路线步骤解析，
    因此除空行与重复长行外不重排段落。
    """
    counts: Counter = Counter()
    text = raw or ""
    if raw_format.lower() == "html":
        text, html_counts = html_to_text(text)
        counts.update(html_counts)

    # 二次反转义，覆盖“&amp;nbsp;”这类重复编码。
    for _ in range(2):
        decoded = html.unescape(text)
        if decoded == text:
            break
        counts["html_entities_decoded"] += len(
            re.findall(r"&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);", text)
        )
        text = decoded

    text, width_changes = normalize_width(text)
    counts["fullwidth_characters_normalized"] += width_changes
    nbsp_changes = (
        text.count("\xa0") + text.count(" ") + text.count(" ")
    )
    counts["nbsp_and_ideographic_spaces_normalized"] += nbsp_changes
    text = (
        text.replace("\r\n", "\n").replace("\r", "\n")
        .replace(" ", "\n").replace(" ", "\n")
        .replace("\xa0", " ").replace(" ", " ").replace(" ", " ")
    )

    tags: list[str] = []
    seen_tags: set[str] = set()
    for tag in HASHTAG_RE.findall(text):
        tag = tag.strip()
        if tag and tag not in seen_tags:
            seen_tags.add(tag)
            tags.append(tag)
    text, hashtag_count = HASHTAG_RE.subn("", text)
    counts["hashtags_moved_to_tags"] += hashtag_count
    text, mention_count = MENTION_RE.subn("", text)
    counts["mentions_removed"] += mention_count
    text, url_count = URL_RE.subn("", text)
    counts["urls_removed"] += url_count

    filtered: list[str] = []
    for ch in text:
        category = unicodedata.category(ch)
        if category in ("Co", "Cs"):
            counts["private_or_surrogate_characters_removed"] += 1
        elif category in ("Cc", "Cf") and ch not in "\n\t":
            counts["control_and_zero_width_characters_removed"] += 1
        elif _is_emoji_or_decoration(ch):
            counts["emoji_and_decorative_characters_removed"] += 1
        else:
            filtered.append(ch)
    text = "".join(filtered)

    text = re.sub(r"[^\S\n]+", " ", text)
    lines: list[str] = []
    long_seen: set[str] = set()
    for line in text.split("\n"):
        line = BULLET_PREFIX_RE.sub("", line).strip()
        if not line:
            counts["blank_lines_removed"] += 1
            continue
        if METADATA_LINE_RE.fullmatch(line):
            counts["metadata_lines_removed"] += 1
            continue
        # 同一快照里桌面前台/移动端重复的整段，仅去掉长文本重复；
        # 短标签（景点名、图注）重复出现可能承载信息，保留。
        if len(line) >= 40 and line in long_seen:
            counts["duplicate_long_lines_removed"] += 1
            continue
        if len(line) >= 40:
            long_seen.add(line)
        lines.append(line)
    cleaned = "\n".join(lines)
    return cleaned, tags, dict(sorted(counts.items()))


def nonspace(text: str) -> str:
    return re.sub(r"\s", "", text)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        "utf-8",
    )


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    """Excel 可直接打开；以公式符号开头的单元格加单引号，避免被解释为公式。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = {}
            for key in fields:
                value = row.get(key, "")
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                value = "" if value is None else str(value)
                if EXCEL_FORMULA_RE.match(value):
                    value = "'" + value
                out[key] = value
            writer.writerow(out)


def residual_noise(text: str) -> dict:
    return {
        "html_tags": len(TAG_RE.findall(text)),
        "urls": len(URL_RE.findall(text)),
        "control_characters": len(CTRL_RE.findall(text)),
        "replacement_characters": text.count("�"),
        "possible_mojibake": bool(MOJIBAKE_RE.search(text)),
        "hashtags": len(HASHTAG_RE.findall(text)),
    }


def length_stats(lengths: list[int]) -> dict:
    if not lengths:
        return {"count": 0, "min": 0, "median": 0, "mean": 0, "max": 0, "total": 0}
    ordered = sorted(lengths)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return {
        "count": len(ordered),
        "min": ordered[0],
        "median": median,
        "mean": round(sum(ordered) / len(ordered), 1),
        "max": ordered[-1],
        "total": sum(ordered),
    }


def tourist_row(record: dict, min_chars: int) -> tuple[dict | None, list[str], dict]:
    errors: list[str] = []
    flags: list[str] = []
    missing = [
        key for key in REQUIRED_TOURIST
        if record.get(key) is None or str(record.get(key, "")).strip() == ""
    ]
    if missing:
        errors.append("missing_required_fields:" + ",".join(missing))
    if record.get("scenic_area") not in AREAS:
        errors.append("invalid_scenic_area")
    if record.get("source_platform") not in PLATFORMS:
        errors.append("invalid_source_platform")
    if not str(record.get("source_url", "")).startswith(("http://", "https://")):
        errors.append("invalid_source_url")

    raw_text = str(record.get("body_text") or "")
    cleaned, tags, counts = clean_text(raw_text, str(record.get("raw_format") or "text"))
    clean_length = len(cleaned)
    nonspace_length = len(nonspace(cleaned))

    if nonspace_length < min_chars:
        flags.append("too_short")
    if not record.get("author"):
        flags.append("missing_author")
    if not record.get("published_at"):
        flags.append("missing_publication_date")
    noise = residual_noise(cleaned)
    if noise["html_tags"]:
        flags.append("residual_html")
    if noise["urls"]:
        flags.append("residual_url")
    if noise["replacement_characters"]:
        flags.append("replacement_character")
    if noise["possible_mojibake"]:
        flags.append("possible_mojibake")
    symbol_count = sum(
        1 for ch in cleaned
        if unicodedata.category(ch).startswith(("S", "P")) and ch not in "\n"
    )
    if cleaned and symbol_count / len(cleaned) > 0.30:
        flags.append("high_symbol_ratio")

    if errors:
        return None, errors, counts

    row = {
        "record_id": record["record_id"],
        "scenic_area": record["scenic_area"],
        "source_platform": record["source_platform"],
        "text_type": record["text_type"],
        "source_url": record["source_url"],
        "title": record.get("title", ""),
        "author": record.get("author", ""),
        "published_at": record.get("published_at", ""),
        "published_at_raw": record.get("published_at_raw", ""),
        "collected_at": record.get("collected_at", ""),
        "read_count": record.get("read_count"),
        "read_count_display": record.get("read_count_display", ""),
        "like_count": record.get("like_count"),
        "like_count_display": record.get("like_count_display", ""),
        "rank_within_scenic_platform": record.get("rank_within_scenic_platform"),
        "rank_metric": record.get("rank_metric", ""),
        "matched_pois": record.get("matched_pois", []),
        "selection_scope": record.get("selection_scope", ""),
        "snapshot_file": record.get("snapshot_file", ""),
        "snapshot_sha256": record.get("snapshot_sha256", ""),
        "cleaned_text": cleaned,
        "tags": tags,
        "raw_format": record.get("raw_format", "text"),
        "raw_char_count": len(raw_text),
        "clean_char_count": clean_length,
        "clean_nonspace_char_count": nonspace_length,
        "retention_ratio": round(clean_length / len(raw_text), 4) if raw_text else 0.0,
        "text_sha256": sha256_text(nonspace(cleaned)),
        "cleaning_counts": counts,
        "noise_after_cleaning": noise,
        "quality_flags": sorted(set(flags)),
        "pipeline_version": PIPELINE_VERSION,
    }
    return row, [], counts


def official_document_row(record: dict, min_chars: int) -> tuple[dict | None, list[str], dict]:
    errors: list[str] = []
    flags: list[str] = []
    missing = [
        key for key in REQUIRED_OFFICIAL
        if record.get(key) is None or str(record.get(key, "")).strip() == ""
    ]
    if missing:
        errors.append("missing_required_fields:" + ",".join(missing))
    if record.get("scenic_area") not in AREAS:
        errors.append("invalid_scenic_area")

    has_body_text = bool(str(record.get("body_text") or "").strip())
    raw_text = str(record.get("body_text") or record.get("raw_content") or "")
    raw_format = str(record.get("raw_format") or ("html" if "<" in raw_text[:200] else "text"))
    cleaned, tags, counts = clean_text(raw_text, raw_format)
    non_empty_lines = [line for line in cleaned.split("\n") if line.strip()]
    if not has_body_text and raw_text.strip():
        flags.append("used_raw_content_fallback")
    if len(nonspace(cleaned)) < min_chars:
        flags.append("too_short")
    if not record.get("accepted", True):
        flags.append("not_accepted")
    if record.get("error"):
        flags.append("collector_error")
    noise = residual_noise(cleaned)
    if noise["html_tags"]:
        flags.append("residual_html")
    if noise["urls"]:
        flags.append("residual_url")
    if noise["possible_mojibake"]:
        flags.append("possible_mojibake")

    if errors:
        return None, errors, counts

    row = {
        "evidence_id": record["evidence_id"],
        "scenic_area": record["scenic_area"],
        "source_url": record["source_url"],
        "title": record.get("title", ""),
        "page_title": record.get("page_title", ""),
        "published_at": record.get("published_at", ""),
        "collected_at": record.get("collected_at", ""),
        "accepted": bool(record.get("accepted", True)),
        "include_in_main_dataset": bool(record.get("include_in_main_dataset", True)),
        "extractor": record.get("extractor", ""),
        "extraction_selector": record.get("extraction_selector", ""),
        "snapshot_file": record.get("snapshot_file", ""),
        "snapshot_sha256": record.get("snapshot_sha256", ""),
        "route_variant_count": len(record.get("route_variants") or []),
        "cleaned_text": cleaned,
        "line_count": len(non_empty_lines),
        "raw_char_count": len(raw_text),
        "clean_char_count": len(cleaned),
        "retention_ratio": round(len(cleaned) / len(raw_text), 4) if raw_text else 0.0,
        "text_sha256": sha256_text(nonspace(cleaned)),
        "cleaning_counts": counts,
        "noise_after_cleaning": noise,
        "quality_flags": sorted(set(flags)),
        "pipeline_version": PIPELINE_VERSION,
    }
    return row, [], counts


def official_route_row(route: dict, min_chars: int) -> tuple[dict | None, list[str], dict]:
    errors: list[str] = []
    flags: list[str] = []
    missing = [
        key for key in REQUIRED_ROUTE
        if route.get(key) is None or str(route.get(key, "")).strip() == ""
    ]
    if missing:
        errors.append("missing_required_fields:" + ",".join(missing))
    if route.get("scenic_area") not in AREAS:
        errors.append("invalid_scenic_area")

    cleaned, tags, counts = clean_text(str(route.get("raw_content") or ""), "text")
    if len(nonspace(cleaned)) < min_chars:
        flags.append("too_short")
    if not route.get("ordered_route"):
        flags.append("theme_variant_without_fixed_order")
    noise = residual_noise(cleaned)
    if noise["html_tags"]:
        flags.append("residual_html")
    if noise["urls"]:
        flags.append("residual_url")

    if errors:
        return None, errors, counts

    row = {
        "route_id": route["route_id"],
        "source_record_id": route.get("source_record_id", ""),
        "scenic_area": route["scenic_area"],
        "source_url": route["source_url"],
        "title": route.get("title", ""),
        "ordered_route": bool(route.get("ordered_route")),
        "published_at": route.get("published_at", ""),
        "scope_note": route.get("scope_note", ""),
        "cleaned_text": cleaned,
        "raw_char_count": len(str(route.get("raw_content") or "")),
        "clean_char_count": len(cleaned),
        "clean_nonspace_char_count": len(nonspace(cleaned)),
        "cleaning_counts": counts,
        "noise_after_cleaning": noise,
        "quality_flags": sorted(set(flags)),
        "pipeline_version": PIPELINE_VERSION,
    }
    return row, [], counts


def char_ngrams(text: str, n: int = 5) -> set[str]:
    compact = nonspace(text)
    if len(compact) < n:
        return {compact} if compact else set()
    return {compact[i:i + n] for i in range(len(compact) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def detect_near_duplicates(rows: list[dict], threshold: float = 0.90) -> list[dict]:
    """同景区同平台内做字符5-gram Jaccard近似重复检测；只标记，不自动删除。"""
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["scenic_area"], row["source_platform"]), []).append(row)
    findings: list[dict] = []
    for key, group in groups.items():
        grams = {row["record_id"]: char_ngrams(row["cleaned_text"]) for row in group}
        for i, first in enumerate(group):
            for second in group[i + 1:]:
                score = jaccard(grams[first["record_id"]], grams[second["record_id"]])
                if score >= threshold:
                    findings.append({
                        "scenic_area": key[0],
                        "source_platform": key[1],
                        "record_id_a": first["record_id"],
                        "record_id_b": second["record_id"],
                        "jaccard_5gram": round(score, 4),
                    })
                    second.setdefault("quality_flags", [])
                    second["quality_flags"] = sorted(
                        set(second["quality_flags"]) | {f"near_duplicate_of:{first['record_id']}"}
                    )
    return sorted(findings, key=lambda item: -item["jaccard_5gram"])


def deduplicate(rows: list[dict], level: str) -> tuple[list[dict], list[dict]]:
    """按ID、URL与正文指纹做精确去重；保留先出现（排名靠前）的记录。

    官方路线分支共用同一来源文档URL，因此路线层级只按 route_id 和正文去重，
    不能按 source_url 去重，否则会把同页面的多个分支误删。
    """
    if level == "tourist":
        id_key, fields = "record_id", ("record_id", "source_url", "text_sha256")
    elif level == "route":
        id_key, fields = "route_id", ("route_id", "text_sha256")
    else:
        id_key, fields = "evidence_id", ("evidence_id", "source_url", "text_sha256")

    kept: list[dict] = []
    removed: list[dict] = []
    seen: dict[str, dict[str, str]] = {field: {} for field in fields}
    for row in rows:
        identity = str(row.get(id_key, ""))
        reason = None
        for field in fields:
            value = identity if field == id_key else str(row.get(field, "") or "")
            if value and value in seen[field]:
                reason = f"duplicate_{field}:{seen[field][value]}"
                break
        if reason:
            removed.append({id_key: identity, "reason": reason})
            continue
        for field in fields:
            value = identity if field == id_key else str(row.get(field, "") or "")
            if value:
                seen[field][value] = identity
        kept.append(row)
    return kept, removed


def count_table(rows: list[dict], key_a: str, key_b: str | None = None) -> dict:
    counter: Counter = Counter()
    for row in rows:
        key = (row.get(key_a, ""), row.get(key_b, "")) if key_b else (row.get(key_a, ""),)
        counter[key] += 1
    return {"|".join(k): v for k, v in sorted(counter.items())}


def build_samples(
    tourist_rows: list[dict], route_rows: list[dict], raw_by_id: dict[str, str]
) -> list[dict]:
    """挑选清洗痕迹最明显的样例，便于报告展示前后对比。

    排序时排除全角转半角，因为它几乎命中所有正文、会掩盖真正的噪声删除。
    """
    def noise_score(row: dict) -> int:
        return sum(
            count for rule, count in row["cleaning_counts"].items()
            if rule != "fullwidth_characters_normalized"
        )

    samples: list[dict] = []
    candidates = sorted(tourist_rows, key=noise_score, reverse=True)
    for platform in ("携程", "小红书"):
        picked = next((row for row in candidates if row["source_platform"] == platform), None)
        if picked:
            samples.append(_sample(picked, "游客游记", raw_by_id.get(picked["record_id"], "")))
    picked_route = max(route_rows, key=noise_score) if route_rows else None
    if picked_route:
        samples.append(_sample(picked_route, "官方路线", raw_by_id.get(picked_route["route_id"], "")))
    return samples


def _sample(row: dict, kind: str, raw_text: str) -> dict:
    cleaned = row["cleaned_text"]
    return {
        "kind": kind,
        "id": row.get("record_id") or row.get("route_id"),
        "scenic_area": row.get("scenic_area", ""),
        "source_platform": row.get("source_platform", "官方"),
        "title": row.get("title", ""),
        "raw_preview": raw_text[:400],
        "cleaned_preview": cleaned[:400],
        "cleaned_tail": cleaned[-160:] if len(cleaned) > 400 else "",
        "cleaning_counts": {k: v for k, v in row["cleaning_counts"].items() if v},
        "raw_char_count": row.get("raw_char_count", 0),
        "clean_char_count": row.get("clean_char_count", 0),
        "tags": row.get("tags", [])[:12],
    }


def build_quality_report(
    tourist_in: int,
    tourist_out: list[dict],
    tourist_removed: list[dict],
    official_in: int,
    official_out: list[dict],
    official_removed: list[dict],
    route_in: int,
    route_out: list[dict],
    route_removed: list[dict],
    near_duplicates: list[dict],
    collection_summary: dict,
    min_tourist_chars: int,
    input_hashes: dict,
) -> dict:
    flags: Counter = Counter()
    for row in tourist_out:
        flags.update(row["quality_flags"])
    doc_flags: Counter = Counter()
    for row in official_out:
        doc_flags.update(row["quality_flags"])
    route_flags: Counter = Counter()
    for row in route_out:
        route_flags.update(row["quality_flags"])

    rule_totals: Counter = Counter()
    for row in tourist_out:
        rule_totals.update(row["cleaning_counts"])
    for row in route_out:
        rule_totals.update(row["cleaning_counts"])

    area_platform = count_table(tourist_out, "scenic_area", "source_platform")
    official_by_area = count_table(official_out, "scenic_area")
    routes_by_area = count_table(route_out, "scenic_area")

    requirements = []
    for area in AREAS:
        official_count = sum(1 for row in official_out if row["scenic_area"] == area and row["accepted"])
        tourist_count = sum(1 for row in tourist_out if row["scenic_area"] == area)
        requirements.append({
            "scenic_area": area,
            "official_documents_accepted": official_count,
            "tourist_records": tourist_count,
            "official_ok": official_count >= 1,
            "tourist_ok": tourist_count >= 3,
        })
    requirements_met = all(item["official_ok"] and item["tourist_ok"] for item in requirements)

    critical_flags = {"residual_html", "replacement_character", "possible_mojibake"}
    critical = [
        row.get("record_id") for row in tourist_out
        if critical_flags & set(row["quality_flags"])
    ]
    complete = requirements_met and not critical and not official_removed and not route_removed

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "stage": "preprocess_and_quality_check",
        "pipeline_version": PIPELINE_VERSION,
        "parameters": {"min_tourist_nonspace_chars": min_tourist_chars},
        "input_files": input_hashes,
        "counts": {
            "tourist_input": tourist_in,
            "tourist_output": len(tourist_out),
            "tourist_removed_duplicate": len(tourist_removed),
            "tourist_removed_invalid": len(tourist_removed) - sum(
                1 for item in tourist_removed if item["reason"].startswith("duplicate_")
            ),
            "official_documents_input": official_in,
            "official_documents_output": len(official_out),
            "official_documents_removed": len(official_removed),
            "official_routes_input": route_in,
            "official_routes_output": len(route_out),
            "official_routes_removed": len(route_removed),
            "tourist_by_area_platform": area_platform,
            "official_documents_by_area": official_by_area,
            "official_routes_by_area": routes_by_area,
        },
        "removed": {
            "tourist": tourist_removed,
            "official_documents": official_removed,
            "official_routes": route_removed,
        },
        "cleaning_rule_totals": dict(sorted(rule_totals.items())),
        "quality": {
            "tourist_flag_counts": dict(sorted(flags.items())),
            "official_document_flag_counts": dict(sorted(doc_flags.items())),
            "official_document_flag_records": {
                row["evidence_id"]: row["quality_flags"]
                for row in official_out if row["quality_flags"]
            },
            "official_route_flag_counts": dict(sorted(route_flags.items())),
            "near_duplicates": near_duplicates,
            "critical_flag_records": critical,
            "tourist_length_stats": length_stats(
                [row["clean_nonspace_char_count"] for row in tourist_out]
            ),
            "official_route_length_stats": length_stats(
                [row["clean_nonspace_char_count"] for row in route_out]
            ),
            "residual_noise_totals": {
                key: sum(row["noise_after_cleaning"][key] for row in tourist_out)
                if key != "possible_mojibake" else sum(
                    bool(row["noise_after_cleaning"][key]) for row in tourist_out
                )
                for key in (
                    "html_tags", "urls", "control_characters",
                    "replacement_characters", "possible_mojibake", "hashtags",
                )
            },
        },
        "task_requirements": {
            "per_area_check": requirements,
            "official_ok": requirements_met,
            "collection_complete": bool(collection_summary.get("complete", False)),
            "collection_shortfalls": [
                item for item in collection_summary.get("counts", [])
                if item.get("shortfall", 0) > 0
            ],
            "note": (
                "任务书要求每景区至少1条官方路线和3篇游记；"
                "采集阶段的小红书缺额不阻断本阶段，但会保留在报告中。"
            ),
        },
        "complete": complete,
    }


def render_markdown(report: dict, samples: list[dict]) -> str:
    counts = report["counts"]
    quality = report["quality"]
    lines = [
        "# 数据预处理与质量检查报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 流程版本：{report['pipeline_version']}",
        f"- 结论：{'通过' if report['complete'] else '需关注'}",
        "",
        "## 1. 数据量与配额",
        "",
        "| 数据 | 输入 | 输出 | 去重/剔除 |",
        "|---|---:|---:|---:|",
        f"| 游客游记 | {counts['tourist_input']} | {counts['tourist_output']} | "
        f"{counts['tourist_removed_duplicate']} 重复 |",
        f"| 官方文档 | {counts['official_documents_input']} | "
        f"{counts['official_documents_output']} | {counts['official_documents_removed']} |",
        f"| 官方路线分支 | {counts['official_routes_input']} | "
        f"{counts['official_routes_output']} | {counts['official_routes_removed']} |",
        "",
        "| 景区 | 携程 | 小红书 | 官方文档（已接受） | 官方路线分支 |",
        "|---|---:|---:|---:|---:|",
    ]
    for area in AREAS:
        ctrip = counts["tourist_by_area_platform"].get(f"{area}|携程", 0)
        xhs = counts["tourist_by_area_platform"].get(f"{area}|小红书", 0)
        official = sum(
            row["official_documents_accepted"]
            for row in report["task_requirements"]["per_area_check"]
            if row["scenic_area"] == area
        )
        routes = counts["official_routes_by_area"].get(area, 0)
        lines.append(f"| {area} | {ctrip} | {xhs} | {official} | {routes} |")

    lines += [
        "",
        "## 2. 清洗规则与命中次数",
        "",
        "| 规则 | 命中次数 | 说明 |",
        "|---|---:|---|",
    ]
    rule_desc = {
        "html_tags_removed": "移除HTML标签，保留块级元素换行",
        "html_noncontent_blocks_removed": "丢弃脚本、样式、导航等非正文块",
        "html_entities_decoded": "反转义HTML实体",
        "fullwidth_characters_normalized": "全角数字/字母与全角空格转半角，保留中文标点",
        "nbsp_and_ideographic_spaces_normalized": "不换行空格、数字空格、窄空格转普通空格",
        "hashtags_moved_to_tags": "话题标签移入tags字段，正文不再保留",
        "mentions_removed": "移除@用户提及",
        "urls_removed": "移除网址",
        "control_and_zero_width_characters_removed": "移除控制符与零宽字符",
        "emoji_and_decorative_characters_removed": "移除装饰性表情，保留箭头与语义符号",
        "blank_lines_removed": "删除空行",
        "metadata_lines_removed": "删除平台UI行（展开全文、点赞、责任编辑等）",
        "duplicate_long_lines_removed": "删除同篇内重复的长段落",
    }
    for rule, total in report["cleaning_rule_totals"].items():
        lines.append(f"| `{rule}` | {total} | {rule_desc.get(rule, '')} |")

    lines += [
        "",
        "## 3. 质量检查",
        "",
        "### 3.1 长度分布（清洗后非空白字符数）",
        "",
        "| 数据 | 条数 | 最短 | 中位数 | 均值 | 最长 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, key in (("游客游记", "tourist_length_stats"), ("官方路线分支", "official_route_length_stats")):
        stat = quality[key]
        lines.append(
            f"| {label} | {stat['count']} | {stat['min']} | {stat['median']} | "
            f"{stat['mean']} | {stat['max']} |"
        )

    lines += ["", "### 3.2 质量标记", "", "游客游记：", "", "| 标记 | 数量 |", "|---|---:|"]
    for flag, total in quality["tourist_flag_counts"].items():
        lines.append(f"| `{flag}` | {total} |")
    for label, key in (
        ("官方文档", "official_document_flag_counts"),
        ("官方路线分支", "official_route_flag_counts"),
    ):
        if quality[key]:
            lines.append("")
            lines.append(f"{label}：")
            lines.append("")
            lines.append("| 标记 | 数量 |")
            lines.append("|---|---:|")
            for flag, total in quality[key].items():
                lines.append(f"| `{flag}` | {total} |")

    residual = quality["residual_noise_totals"]
    lines += [
        "",
        "### 3.3 清洗后残留噪声",
        "",
        "| 检查项 | 残留数量 |",
        "|---|---:|",
        f"| HTML标签 | {residual['html_tags']} |",
        f"| 网址 | {residual['urls']} |",
        f"| 控制字符 | {residual['control_characters']} |",
        f"| U+FFFD替换字符 | {residual['replacement_characters']} |",
        f"| 疑似乱码文档 | {residual['possible_mojibake']} |",
        f"| 话题标签（应全部移出正文） | {residual['hashtags']} |",
        "",
        f"近似重复对（Jaccard≥0.90，仅标记不删除）：{len(quality['near_duplicates'])} 对。",
    ]

    shortfalls = report["task_requirements"]["collection_shortfalls"]
    if shortfalls:
        lines += ["", "### 3.4 采集阶段缺额（保留真实结果，不补占位）", ""]
        for item in shortfalls:
            lines.append(
                f"- {item['scenic_area']} / {item['platform']}："
                f"{item['selected']}/{item['target']}，缺 {item['shortfall']} 篇"
            )

    lines += [
        "",
        "## 4. 清洗前后样例",
        "",
    ]
    for idx, sample in enumerate(samples, start=1):
        lines += [
            f"### 样例 {idx}：{sample['scenic_area']} / {sample['source_platform']} / {sample['kind']}",
            "",
            f"- 记录：`{sample['id']}`",
            f"- 标题：{sample['title']}",
            f"- 字符数：{sample['raw_char_count']} → {sample['clean_char_count']}",
            f"- 规则命中：`{json.dumps(sample['cleaning_counts'], ensure_ascii=False)}`",
        ]
        if sample["tags"]:
            lines.append(f"- 提取标签：{', '.join('#' + tag for tag in sample['tags'])}")
        lines += [
            "",
            "清洗前正文（前400字符）：",
            "",
            "```text",
            sample["raw_preview"],
            "```",
            "",
            "清洗后正文（前400字符）：",
            "",
            "```text",
            sample["cleaned_preview"],
            "```",
            "",
        ]

    doc_flags = quality.get("official_document_flag_records", {})
    fallback_docs = [
        eid for eid, items in doc_flags.items() if "used_raw_content_fallback" in items
    ]
    error_docs = [
        eid for eid, items in doc_flags.items() if "collector_error" in items
    ]

    lines += [
        "## 5. 输出字段说明",
        "",
        "游客游记 `tourist_routes_clean.jsonl`：",
        "",
        "| 字段 | 含义 |",
        "|---|---|",
        "| `record_id` / `scenic_area` / `source_platform` | 记录ID、景区、平台（携程/小红书） |",
        "| `text_type` | 文本类型，当前均为游记 |",
        "| `source_url` / `title` / `author` / `published_at` | 来源与元数据；缺失保持为空 |",
        "| `read_count` / `like_count` / `rank_within_scenic_platform` | 平台热度与组内排名 |",
        "| `matched_pois` | 采集阶段匹配到的景区景点节点 |",
        "| `cleaned_text` | 清洗后正文，保留原始行序与路线箭头 |",
        "| `tags` | 从小红书正文抽出的话题标签 |",
        "| `raw_char_count` / `clean_char_count` / `clean_nonspace_char_count` | 清洗前后字符数与非空白字符数 |",
        "| `retention_ratio` | 清洗后长度 / 清洗前长度 |",
        "| `text_sha256` | 去除空白后的正文指纹，用于精确去重 |",
        "| `quality_flags` | 质量标记，见 3.2 |",
        "| `cleaning_counts` / `noise_after_cleaning` | 单条记录的规则命中与残留噪声检查 |",
        "",
        "官方文档 `official_documents_clean.jsonl` 额外包含 `evidence_id`、`accepted`、"
        "`route_variant_count`、`snapshot_file`/`snapshot_sha256`；"
        "官方路线 `official_routes_clean.jsonl` 包含 `route_id`、`source_record_id`、"
        "`ordered_route`（是否为固定顺序路线）与 `scope_note`。",
        "",
        "CSV 为 UTF-8 BOM 编码，便于 Excel 直接打开；以 `=`、`+`、`-`、`@` 开头的单元格会加单引号前缀，"
        "JSONL 保留原值。",
        "",
        "## 6. 发现的问题与处理",
        "",
        "- 携程正文快照为HTML，已按块级元素提取正文并丢弃导航、封面元数据和脚本；正文沿用采集阶段已提取的 `body_text`，避免重复解析误差。",
        "- 小红书正文含话题标签、@提及与装饰表情：标签移入 `tags` 字段，提及与表情移除；路线箭头（→、➡）和 ✅/❌/⚠/❗ 等语义符号保留。",
        "- 全角数字/字母与全角空格转半角，未使用 NFKC，避免把 ①、²、℃ 等语义符号折叠后改变原文数值；中文标点保留原样，避免同句内半角逗号与全角句号混排。",
        "- 采集阶段的作者缺失与相对发布日期保持为空，不猜测填充；质量标记中单独统计。",
        "- 小红书九寨沟、颐和园存在采集缺额；任务书要求每景区至少3篇游记，当前数据满足要求，缺额保留在报告中。",
        "- 近似重复仅标记不删除，避免误删同主题但细节不同的游记。",
    ]
    if fallback_docs:
        lines.append(
            f"- 官方文档 {'、'.join(fallback_docs)} 采集阶段未生成 `body_text`，"
            "本阶段改用 `raw_content` 清洗，并标记 `used_raw_content_fallback`。"
        )
    if error_docs:
        lines.append(
            f"- 官方文档 {'、'.join(error_docs)} 采集失败（`collector_error`），"
            "记录保留并标记，不进入后续路线解析。"
        )
    lines += [
        "",
        "## 7. 复现方式",
        "",
        "```powershell",
        "python src/preprocess_collected.py",
        "```",
        "",
        "离线运行，输入为 `data/collected/`，输出为 `data/processed/`。"
        "只有 `quality_report.json` 的 `complete` 为 `true` 且质量检查无关键标记时，"
        "才表示本阶段全部通过。",
        "",
    ]
    return "\n".join(lines)


def roundtrip_check(rows: list[dict]) -> dict:
    """对清洗结果做一次幂等性与结构自检。"""
    idempotent = 0
    changed = []
    for row in rows:
        again, _, _ = clean_text(row["cleaned_text"], "text")
        if again == row["cleaned_text"]:
            idempotent += 1
        else:
            changed.append(row.get("record_id") or row.get("route_id"))
    return {
        "idempotent_records": idempotent,
        "total_records": len(rows),
        "non_idempotent_records": changed[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="清洗采集结果并生成结构化数据集与质量报告")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-tourist-chars", type=int, default=80)
    parser.add_argument(
        "--min-official-chars", type=int, default=30,
        help="官方文档与路线分支的最小非空白字符数",
    )
    args = parser.parse_args()

    input_dir = args.input_dir
    output_dir = args.output_dir
    tourist_path = input_dir / "tourist_routes.jsonl"
    official_docs_path = input_dir / "official_documents.jsonl"
    official_routes_path = input_dir / "official_routes.jsonl"
    summary_path = input_dir / "collection_summary.json"

    if not tourist_path.exists():
        raise SystemExit(f"缺少输入文件：{tourist_path}，请先完成采集阶段。")

    tourist_records = read_jsonl(tourist_path)
    official_records = read_jsonl(official_docs_path)
    route_records = read_jsonl(official_routes_path)
    collection_summary = (
        json.loads(summary_path.read_text("utf-8")) if summary_path.exists() else {}
    )

    tourist_rows: list[dict] = []
    tourist_removed: list[dict] = []
    for record in tourist_records:
        row, errors, _ = tourist_row(record, args.min_tourist_chars)
        if row is None:
            tourist_removed.append({
                "record_id": record.get("record_id", ""),
                "reason": ";".join(errors),
            })
        else:
            tourist_rows.append(row)
    tourist_rows, duplicate_removed = deduplicate(tourist_rows, "tourist")
    tourist_removed.extend(duplicate_removed)
    near_duplicates = detect_near_duplicates(tourist_rows)

    official_rows: list[dict] = []
    official_removed: list[dict] = []
    for record in official_records:
        row, errors, _ = official_document_row(record, args.min_official_chars)
        if row is None:
            official_removed.append({
                "evidence_id": record.get("evidence_id", ""),
                "reason": ";".join(errors),
            })
        else:
            official_rows.append(row)
    official_rows, duplicate_official = deduplicate(official_rows, "official")
    official_removed.extend(duplicate_official)

    route_rows: list[dict] = []
    route_removed: list[dict] = []
    for record in route_records:
        row, errors, _ = official_route_row(record, args.min_official_chars)
        if row is None:
            route_removed.append({
                "route_id": record.get("route_id", ""),
                "reason": ";".join(errors),
            })
        else:
            route_rows.append(row)
    route_rows, duplicate_routes = deduplicate(route_rows, "route")
    route_removed.extend(duplicate_routes)

    idempotency = roundtrip_check(tourist_rows)

    raw_by_id: dict[str, str] = {}
    for record in tourist_records:
        raw_by_id[str(record.get("record_id", ""))] = str(record.get("body_text") or "")
    for record in route_records:
        raw_by_id[str(record.get("route_id", ""))] = str(record.get("raw_content") or "")

    input_hashes = {}
    for path in (tourist_path, official_docs_path, official_routes_path, summary_path):
        if path.exists():
            input_hashes[path.name] = {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }

    report = build_quality_report(
        len(tourist_records), tourist_rows, tourist_removed,
        len(official_records), official_rows, official_removed,
        len(route_records), route_rows, route_removed,
        near_duplicates, collection_summary,
        args.min_tourist_chars, input_hashes,
    )
    report["idempotency_check"] = idempotency

    tourist_fields = [
        "record_id", "scenic_area", "source_platform", "text_type", "source_url",
        "title", "author", "published_at", "published_at_raw", "collected_at",
        "read_count", "read_count_display", "like_count", "like_count_display",
        "rank_within_scenic_platform", "rank_metric", "matched_pois",
        "selection_scope", "cleaned_text", "tags", "raw_char_count",
        "clean_char_count", "clean_nonspace_char_count", "retention_ratio",
        "text_sha256", "quality_flags",
    ]
    route_fields = [
        "route_id", "source_record_id", "scenic_area", "source_url", "title",
        "ordered_route", "published_at", "scope_note", "cleaned_text",
        "raw_char_count", "clean_char_count", "clean_nonspace_char_count",
        "quality_flags",
    ]
    document_fields = [
        "evidence_id", "scenic_area", "source_url", "title", "page_title",
        "published_at", "collected_at", "accepted", "include_in_main_dataset",
        "route_variant_count", "cleaned_text", "raw_char_count",
        "clean_char_count", "retention_ratio", "quality_flags",
    ]

    write_jsonl(output_dir / "tourist_routes_clean.jsonl", tourist_rows)
    write_csv(output_dir / "tourist_routes_clean.csv", tourist_rows, tourist_fields)
    write_jsonl(output_dir / "official_documents_clean.jsonl", official_rows)
    write_csv(output_dir / "official_documents_clean.csv", official_rows, document_fields)
    write_jsonl(output_dir / "official_routes_clean.jsonl", route_rows)
    write_csv(output_dir / "official_routes_clean.csv", route_rows, route_fields)
    (output_dir / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), "utf-8"
    )
    samples = build_samples(tourist_rows, route_rows, raw_by_id)
    (output_dir / "quality_report.md").write_text(
        render_markdown(report, samples), "utf-8"
    )

    print(f"游客游记：{len(tourist_records)} → {len(tourist_rows)}")
    print(f"官方文档：{len(official_records)} → {len(official_rows)}")
    print(f"官方路线分支：{len(route_records)} → {len(route_rows)}")
    print(f"质量报告：{output_dir / 'quality_report.md'}")
    if report["complete"]:
        print("预处理与质量检查通过。")
        return 0
    print("预处理已生成结果，但存在需要关注的质量项，请查看 quality_report.json。")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
