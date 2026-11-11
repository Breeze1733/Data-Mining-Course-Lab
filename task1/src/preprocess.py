"""Task 1: clean captured scenic-area articles and export auditable datasets.

Offline entry point (run from task1):
    python src/preprocess.py --input data/raw/dataset_raw.jsonl --output-dir data/rebuild

Only the Python standard library and the saved raw dataset are required for preprocessing.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SCENIC_AREAS = ("黄山", "九寨沟", "颐和园")
SCENIC_ALIASES = {
    "黄山": ("黄山", "迎客松", "光明顶", "始信峰", "玉屏", "云谷", "西海大峡谷", "huangshan"),
    "九寨沟": ("九寨沟", "九寨", "五花海", "诺日朗", "树正", "日则沟", "则查洼", "jiuzhai"),
    "颐和园": ("颐和园", "万寿山", "昆明湖", "佛香阁", "十七孔桥", "summer palace"),
}
REQUIRED_FIELDS = (
    "record_id", "scenic_area", "source_platform", "source_url", "title",
    "text_type", "collected_at", "raw_content", "raw_format",
    "extraction_selector", "raw_file", "content_scope",
)
BASE_FIELDS = list(REQUIRED_FIELDS) + ["author", "published_at"]
DERIVED_FIELDS = [
    "clean_content", "raw_char_count", "extracted_char_count", "clean_char_count",
    "clean_nonspace_char_count", "retention_ratio", "canonical_source_url",
    "content_sha256", "cleaning_counts", "quality_flags",
]
DUPLICATE_FIELDS = ("duplicate_group", "duplicate_role", "duplicate_of", "dedup_weight")
NEAR_DUPLICATE_THRESHOLD = 0.9
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "li", "main", "ol", "p", "pre", "section", "table", "tr", "ul",
}
IGNORED_TAGS = {
    "script", "style", "noscript", "head", "nav", "footer", "header", "iframe",
    "svg", "canvas", "button", "form", "select", "textarea",
}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
ROUTE_ARROWS = set("←↑→↓↔↕↖↗↘↙⇒⇐⇔➔➜➝➞➟➠➡➢➣➤➥➦➧➨➩➪➫➬➭➮➯➱")
# These glyphs can encode permission, prohibition, risk, or route composition.
# Removing them would change statements such as "❌不要走" or "A➕B".
SEMANTIC_SYMBOLS = set("✅❌✔✘✖✗➕➖⚠☑☒✓√×±⊕⊖🚫⛔❎❗❕❓❔")
URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"'\u3000，。；！？、）】》]+")
METADATA_LINE_RE = re.compile(
    r"^(?:(?:分享|收藏|举报|点赞|评论|关注|返回顶部|展开全文|收起全文|查看更多|"
    r"下载APP|打开APP|扫码下载|登录后查看|相关推荐|猜你喜欢|发布评论|写评论)"
    r"(?:\s*[:：]?\s*\d+(?:\.\d+)?[万wW]?)?|"
    r"(?:上一篇|下一篇)\s*[:：].*|(?:责任编辑|网站编辑|编辑)\s*[:：].{0,30}|"
    r"(?:Copyright|版权所有|ICP备|公安备案).*)$",
    re.IGNORECASE,
)
TRACKING_QUERY_KEYS = {"from", "source", "spm", "xsec_token", "xsec_source", "share_from_user_hidden", "share_time", "share_id", "app_platform", "app_version", "share_from_user_id", "share_user_id", "xhsshare", "channel", "entry", "appuid", "exsource", "xhs_explore_source", "scm"}
EXCEL_LIMIT = 32767
# Page furniture inside the 携程 travelogue container: platform notices, trip metadata label blocks, embedded player timestamps.
PLATFORM_NOTICE_RE = re.compile(r"战略方向的调整|停止游记业务的运维")
TRIP_META_LABELS = {"出发时间", "行程天数", "人均花费", "和谁出行", "游玩时间", "人均费用", "出行天数"}
PLAYER_TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}\s*/\s*\d{1,2}:\d{2}$")


class ArticleHTMLParser(HTMLParser):
    """Keep article text and block boundaries, discarding executable/UI regions."""

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
        hidden = ("hidden" in attrs_dict or attrs_dict.get("aria-hidden") == "true"
                  or "display:none" in style or "visibility:hidden" in style)
        skip = tag in IGNORED_TAGS or hidden
        if skip and not self._ignored():
            self.counts["html_noncontent_blocks_removed"] += 1
        if tag in BLOCK_TAGS and not self._ignored():
            self.parts.append("\n")
        if tag not in VOID_TAGS:
            self.stack.append((tag, skip))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
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
    """Strip presentation noise; explicitly preserve route arrow characters."""
    if ch in ROUTE_ARROWS or ch in SEMANTIC_SYMBOLS:
        return False
    cp = ord(ch)
    return (
        0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF
        or 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF
        or cp in (0x20E3, 0x3030, 0x303D, 0x3297, 0x3299)
    )


def normalize_width_only(text: str) -> tuple[str, int]:
    """Normalize fullwidth ASCII and ideographic space without semantic folding.

    General NFKC is deliberately avoided: 1., Ⅰ, ², ₂ and ℃ are meaningful
    notation, and flattening 2²km into 22km would corrupt source information.
    """
    parts = []
    changed = 0
    for ch in text:
        cp = ord(ch)
        if 0xFF01 <= cp <= 0xFF5E:
            parts.append(chr(cp - 0xFEE0))
            changed += 1
        elif cp == 0x3000:
            parts.append(" ")
            changed += 1
        else:
            parts.append(ch)
    return "".join(parts), changed


def extract_text(raw_content: str, raw_format: str) -> tuple[str, dict]:
    counts: Counter = Counter()
    if raw_format.lower() == "html":
        parser = ArticleHTMLParser()
        parser.feed(raw_content)
        parser.close()
        text = "".join(parser.parts)
        counts.update(parser.counts)
    else:
        text = raw_content
    return text, dict(counts)


def clean_text(raw_content: str, raw_format: str = "text") -> tuple[str, dict, int]:
    """Return clean text, actual rule counts, and pre-normalization text length.

    The rules preserve words, numeric values, time expressions, ordered route
    arrows and paragraph order. They do not invent missing words or repair
    suspected mojibake by guessing the intended Chinese.
    """
    text, initial_counts = extract_text(raw_content, raw_format)
    extracted_length = len(text)
    counts = Counter(initial_counts)
    # A second unescape covers double-escaped entities found in captured HTML.
    for _ in range(2):
        entity_count = len(re.findall(r"&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);", text))
        decoded = html.unescape(text)
        if decoded == text:
            break
        counts["html_entities_decoded"] += entity_count
        text = decoded
    text, width_changes = normalize_width_only(text)
    counts["fullwidth_characters_normalized"] += width_changes
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u2028", "\n").replace("\u2029", "\n")
    text, n = URL_RE.subn("", text)
    counts["urls_removed"] += n
    filtered = []
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
    original_space_count = len(re.findall(r"[^\S\n]+", text))
    text = re.sub(r"[^\S\n]+", " ", text)
    counts["horizontal_whitespace_runs_normalized"] += original_space_count
    paragraphs: list[str] = []
    long_seen: set[str] = set()
    drop_next_meta_value = False
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            counts["blank_lines_removed"] += 1
            continue
        if PLATFORM_NOTICE_RE.search(line):
            counts["platform_notice_lines_removed"] += 1
            continue
        # Trip metadata blocks are an interleaved “label line + value line” structure (出发时间/8月/行程天数/7天…), removed in pairs.
        if line.rstrip(":：") in TRIP_META_LABELS:
            counts["trip_metadata_labels_removed"] += 1
            drop_next_meta_value = True
            continue
        if drop_next_meta_value:
            drop_next_meta_value = False
            if len(line) <= 20:
                counts["trip_metadata_values_removed"] += 1
                continue
        drop_next_meta_value = False
        if PLAYER_TIMESTAMP_RE.match(line):
            counts["player_timestamp_lines_removed"] += 1
            continue
        if METADATA_LINE_RE.fullmatch(line):
            counts["metadata_lines_removed"] += 1
            continue
        # Long verbatim duplicated paragraphs usually arise from desktop/mobile
        # copies in one capture. Short recurring POI labels or captions are kept.
        if len(line) >= 40 and line in long_seen:
            counts["duplicate_long_paragraphs_removed"] += 1
            continue
        if len(line) >= 40:
            long_seen.add(line)
        paragraphs.append(line)
    return "\n".join(paragraphs), dict(sorted(counts.items())), extracted_length


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
             if key.lower() not in TRACKING_QUERY_KEYS and not key.lower().startswith("utm_")]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(sorted(query)), ""))


def valid_http_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return parts.scheme.lower() in ("http", "https") and bool(parts.hostname) and not any(ch.isspace() for ch in url)
    except ValueError:
        return False


def _nonspace(text: str) -> str:
    return re.sub(r"\s", "", text)


def _content_fingerprint(text: str) -> str:
    # Exact-content rejection may ignore whitespace, never punctuation/symbols:
    # "A+B", "A-B", "✔可走" and "✘可走" are different source statements.
    # Similar-but-not-identical records are handled by the warning-only check.
    normalized = _nonspace(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _date_is_iso(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except (ValueError, TypeError):
        return False


def find_near_duplicate(row: dict, accepted: list[dict]) -> tuple[str, float] | None:
    """Return the earliest accepted same-area record whose clean text is nearly identical."""
    text = _nonspace(row["clean_content"])
    for earlier in accepted:
        if earlier["scenic_area"] != row["scenic_area"]:
            continue
        other = _nonspace(earlier["clean_content"])
        # A length upper bound avoids expensive comparisons for very different texts.
        if 2 * min(len(other), len(text)) / max(1, len(other) + len(text)) < NEAR_DUPLICATE_THRESHOLD:
            continue
        score = SequenceMatcher(None, other, text, autojunk=False).ratio()
        if score >= NEAR_DUPLICATE_THRESHOLD:
            return earlier["record_id"], score
    return None


def build_near_duplicate_groups(pairs: list[dict], positions: dict[str, int]) -> list[dict]:
    """Union-find the pair list; canonical = earliest input record.

    Every non-canonical member of a group is removed from the delivered dataset.
    The group record is kept in the quality report so the removed ids remain auditable.
    """
    parent: dict[str, str] = {}

    def find(item: str) -> str:
        parent.setdefault(item, item)
        root = item
        while parent[root] != root:
            root = parent[root]
        while parent[item] != root:
            parent[item], item = root, parent[item]
        return root

    for pair in pairs:
        left, right = pair["record_id_a"], pair["record_id_b"]
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    members: dict[str, list[str]] = {}
    for item in parent:
        members.setdefault(find(item), []).append(item)

    groups = []
    for ids in members.values():
        if len(ids) < 2:
            continue
        ids.sort(key=lambda record_id: positions.get(record_id, sys.maxsize))
        groups.append(ids)
    groups.sort(key=lambda ids: positions.get(ids[0], sys.maxsize))

    pair_scores: dict[str, list[float]] = {}
    for pair in pairs:
        for record_id in (pair["record_id_a"], pair["record_id_b"]):
            pair_scores.setdefault(record_id, []).append(float(pair.get("similarity", 0.0)))

    result = []
    for index, ids in enumerate(groups, start=1):
        scores = [score for record_id in ids for score in pair_scores.get(record_id, [])]
        result.append({
            "group_id": f"DUP_{index:03d}",
            "canonical_record_id": ids[0],
            "record_ids": ids,
            "duplicate_record_ids": ids[1:],
            "member_count": len(ids),
            "duplicate_count": len(ids) - 1,
            "max_similarity": round(max(scores, default=0.0), 4),
        })
    return result


def _number(value):
    return int(value) if float(value).is_integer() else round(float(value), 4)


def summarize_dataset(accepted: list[dict], rejected: list[dict], deduplicated: list[dict],
                      near_duplicates: list[dict], record_checks: list[dict],
                      aggregate_rules: dict, input_missing: dict, input_records: int,
                      positions: dict[str, int], min_travelogue_length: int,
                      min_official_length: int) -> dict:
    """Build the quality report and annotate duplicate-group fields on rows.

    ``accepted`` holds the records that remain after near-duplicate removal;
    ``deduplicated`` holds the removed duplicates (kept in a separate audit file).
    """
    groups = build_near_duplicate_groups(near_duplicates, positions)
    by_id = {row["record_id"]: row for row in accepted + deduplicated}
    for row in accepted + deduplicated:
        row["duplicate_group"] = ""
        row["duplicate_role"] = ""
        row["duplicate_of"] = ""
        row["dedup_weight"] = 1.0
    for group in groups:
        canonical = group["canonical_record_id"]
        for record_id in group["record_ids"]:
            row = by_id.get(record_id)
            if row is None:
                continue
            row["duplicate_group"] = group["group_id"]
            if record_id == canonical:
                row["duplicate_role"] = "canonical"
                row["dedup_weight"] = 1.0
            else:
                row["duplicate_role"] = "duplicate"
                row["duplicate_of"] = canonical
                row["dedup_weight"] = 0.0

    coverage = {}
    for scenic_area in SCENIC_AREAS:
        current = [r for r in accepted if r["scenic_area"] == scenic_area]
        official = sum(r["text_type"] == "official_route" for r in current)
        travelogue = sum(r["text_type"] == "travelogue" for r in current)
        coverage[scenic_area] = {"total": len(current), "official_route": official, "travelogue": travelogue,
                                 "meets_main_target_1_official_5_travelogues": official >= 1 and travelogue >= 5,
                                 "meets_minimum_1_official_3_travelogues": official >= 1 and travelogue >= 3,
                                 "platforms": dict(Counter(r["source_platform"] for r in current))}
    lengths = sorted(r["clean_char_count"] for r in accepted)
    median = (lengths[(len(lengths) - 1) // 2] + lengths[len(lengths) // 2]) / 2 if lengths else 0
    warning_counts = Counter(flag.split(":", 1)[0] for row in accepted for flag in row["quality_flags"])
    weight_sum = sum(row["dedup_weight"] for row in accepted)
    report = {
        "input_records": input_records,
        "accepted_records": len(accepted),
        "rejected_records": len(rejected),
        "deduplicated_records": len(deduplicated),
        "main_target_met": all(v["meets_main_target_1_official_5_travelogues"] for v in coverage.values()),
        "minimum_target_met": all(v["meets_minimum_1_official_3_travelogues"] for v in coverage.values()),
        "coverage_by_scenic_area": coverage,
        "profile": {"source_platforms": dict(Counter(r["source_platform"] for r in accepted)),
                    "text_types": dict(Counter(r["text_type"] for r in accepted)),
                    "raw_formats": dict(Counter(r["raw_format"] for r in accepted)),
                    "raw_characters_total": sum(r["raw_char_count"] for r in accepted),
                    "extracted_characters_total": sum(r["extracted_char_count"] for r in accepted),
                    "clean_characters_total": sum(lengths),
                    "clean_length_min": min(lengths, default=0), "clean_length_max": max(lengths, default=0),
                    "clean_length_mean": round(sum(lengths) / len(lengths), 2) if lengths else 0,
                    "clean_length_median": median},
        "missing_required_fields_in_input": dict(input_missing),
        "missing_required_fields_in_accepted": {key: sum(row.get(key) in (None, "") for row in accepted) for key in REQUIRED_FIELDS},
        "optional_fields_missing_in_accepted": {key: sum(not row.get(key) for row in accepted) for key in ("author", "published_at")},
        "duplicate_source_urls_in_accepted": len(accepted) - len({r["canonical_source_url"] for r in accepted}),
        "duplicate_clean_contents_in_accepted": len(accepted) - len({_content_fingerprint(r["clean_content"]) for r in accepted}),
        "near_duplicate_pairs": near_duplicates,
        "near_duplicate_groups": groups,
        "near_duplicate_group_count": len(groups),
        "near_duplicate_records_removed": len(deduplicated),
        "near_duplicate_records_in_groups": sum(1 for r in accepted if r["duplicate_group"]),
        "near_duplicate_redundant_records": len(deduplicated),
        "effective_records_after_dedup": _number(weight_sum),
        "warning_counts": dict(warning_counts),
        "cleaning_rule_totals_all_inputs": dict(sorted(Counter(aggregate_rules).items())),
        "record_checks": record_checks,
        "validation_policy": {"min_travelogue_nonspace_characters": min_travelogue_length,
                              "min_official_nonspace_characters": min_official_length,
                              "near_duplicate_similarity_threshold": NEAR_DUPLICATE_THRESHOLD,
                              "long_duplicate_paragraph_min_characters": 40,
                              "suspected_mojibake_action": "flag_only_no_guessed_repair",
                              "unicode_normalization": "fullwidth ASCII U+FF01..U+FF5E and ideographic space U+3000 only; preserve superscripts, subscripts, circled numbers, Roman numerals and units",
                              "semantic_symbols": "preserve route arrows, check/cross marks, plus/minus, warning and prohibition symbols",
                              "near_duplicate_action": "remove_later_duplicates_keep_earliest_record",
                              "exact_content_duplicate_key": "clean text with whitespace removed; punctuation, case and semantic symbols preserved",
                              "title_and_article_content_used_for_scenic_relevance": True,
                              "dedup_weight_policy": "retained records=1.0; removed duplicates are absent from dataset_clean and listed in deduplicated_records.jsonl",
                              "duplicate_group_rule": "transitive closure of near_duplicate_pairs; canonical = earliest input record; later members removed",
                              "duplicate_fields": list(DUPLICATE_FIELDS),
                              "main_target": "Each of 3 scenic areas: >=1 official route and >=5 travelogues",
                              "minimum_target": "Each of 3 scenic areas: >=1 official route and >=3 travelogues"},
    }
    fields: list[str] = []
    for row in accepted:
        for key in row:
            if key not in fields:
                fields.append(key)
    for key in DUPLICATE_FIELDS:
        if key not in fields:
            fields.append(key)
    report["dataset_fields"] = fields
    report["xlsx_authoring"] = {"engine": "openpyxl", "script": "src/export_dataset_xlsx.py",
                                "status": "generated"}
    report["xlsx_long_text_externalization"] = []
    report["output_files"] = {"csv": "dataset_clean.csv", "jsonl": "dataset_clean.jsonl",
                              "xlsx": "dataset_clean.xlsx", "quality_report": "quality_report.json",
                              "cleaning_examples": "cleaning_examples.json",
                              "rejected_records": "rejected_records.jsonl",
                              "deduplicated_records": "deduplicated_records.jsonl"}
    return report


def preprocess_records(records: list[dict], min_travelogue_length: int = 80,
                       min_official_length: int = 30) -> tuple[list[dict], dict, list[dict], list[dict], list[dict]]:
    """Validate and clean records; reject invalid/exact-duplicate records and near-duplicate copies."""
    accepted: list[dict] = []
    rejected: list[dict] = []
    deduplicated: list[dict] = []
    examples: list[dict] = []
    record_checks: list[dict] = []
    seen_ids: dict[str, str] = {}
    seen_urls: dict[str, str] = {}
    seen_fingerprints: dict[str, str] = {}
    aggregate_rules: Counter = Counter()
    input_missing: Counter = Counter()
    near_duplicates: list[dict] = []
    positions = {str(row.get("record_id", "")): index for index, row in enumerate(records, start=1)}
    for position, original in enumerate(records, start=1):
        row = dict(original)
        row.pop("provenance_note", None)
        # Preserve source data types in raw JSON; normalize only scalar metadata.
        for key in BASE_FIELDS:
            if key != "raw_content":
                row[key] = "" if row.get(key) is None else str(row.get(key, "")).strip()
        raw = row.get("raw_content")
        errors: list[str] = []
        flags: list[str] = []
        missing = [key for key in REQUIRED_FIELDS if row.get(key) is None or row.get(key) == ""]
        input_missing.update(missing)
        if missing:
            errors.append("missing_required_fields:" + ",".join(missing))
        if row["scenic_area"] not in SCENIC_AREAS:
            errors.append("invalid_scenic_area")
        if row["text_type"] not in ("official_route", "travelogue"):
            errors.append("invalid_text_type")
        if row["raw_format"].lower() not in ("html", "text"):
            errors.append("invalid_raw_format")
        if not valid_http_url(row["source_url"]):
            errors.append("invalid_source_url")
        if row["collected_at"] and not _date_is_iso(row["collected_at"]):
            errors.append("invalid_collection_datetime")
        if not isinstance(raw, str):
            errors.append("raw_content_not_string")
            raw = "" if raw is None else str(raw)
        cleaned, rule_counts, extracted_length = clean_text(raw, row["raw_format"])
        aggregate_rules.update(rule_counts)
        nonspace_length = len(_nonspace(cleaned))
        if not cleaned:
            errors.append("empty_clean_content")
        minimum = min_official_length if row["text_type"] == "official_route" else min_travelogue_length
        if cleaned and nonspace_length < minimum:
            errors.append(f"content_too_short:{nonspace_length}<{minimum}")
        canonical = canonicalize_url(row["source_url"]) if valid_http_url(row["source_url"]) else row["source_url"]
        fingerprint = _content_fingerprint(cleaned)
        if row["record_id"] in seen_ids:
            errors.append("duplicate_record_id:" + seen_ids[row["record_id"]])
        if canonical in seen_urls:
            errors.append("duplicate_source_url:" + seen_urls[canonical])
        if cleaned and fingerprint in seen_fingerprints:
            errors.append("duplicate_clean_content:" + seen_fingerprints[fingerprint])
        if "\ufffd" in cleaned:
            flags.append("replacement_character_present")
        # Typical double-decoded UTF-8 sequences are warnings, never auto-repairs.
        if re.search(r"(?:Ã.|Â.|锟斤拷|烫烫烫|屯屯屯)", cleaned):
            flags.append("suspected_encoding_corruption")
        aliases = SCENIC_ALIASES.get(row["scenic_area"], ())
        if aliases and not any(alias.lower() in (row["title"] + "\n" + cleaned).lower() for alias in aliases):
            flags.append("scenic_relevance_requires_review")
        if not row["author"] and row["text_type"] == "travelogue":
            flags.append("author_missing")
        if not row["published_at"]:
            flags.append("publication_date_missing")
        if not re.search(r"→|⇒|➡|➜|路线|线路|行程|上午|下午|早上|然后|随后|之后|先.{0,30}再|第一天|第二天|day\s*\d|[0-2]?\d[:：][0-5]\d", cleaned, re.I):
            flags.append("route_cues_require_review")
        row.update({
            "raw_content": raw,
            "clean_content": cleaned,
            "raw_char_count": len(raw),
            "extracted_char_count": extracted_length,
            "clean_char_count": len(cleaned),
            "clean_nonspace_char_count": nonspace_length,
            "retention_ratio": round(len(cleaned) / extracted_length, 6) if extracted_length else 0,
            "canonical_source_url": canonical,
            "content_sha256": hashlib.sha256(cleaned.encode("utf-8")).hexdigest(),
            "cleaning_counts": rule_counts,
            "quality_flags": flags,
        })
        check = {"input_position": position, "record_id": row["record_id"], "scenic_area": row["scenic_area"],
                 "text_type": row["text_type"], "raw_char_count": len(raw), "extracted_char_count": extracted_length,
                 "clean_char_count": len(cleaned), "clean_nonspace_char_count": nonspace_length,
                 "cleaning_counts": rule_counts, "errors": errors, "warnings": flags, "accepted": not errors}
        record_checks.append(check)
        if errors:
            row["rejection_reasons"] = errors
            row["input_position"] = position
            rejected.append(row)
            continue
        # Compare within a scenic area. The earliest accepted record is the canonical
        # copy; later near-identical copies are removed from the delivered dataset.
        match = find_near_duplicate(row, accepted)
        if match is not None:
            duplicate_of, duplicate_score = match
            reason = f"near_duplicate_of:{duplicate_of}"
            row["deduplication_reason"] = reason
            row["near_duplicate_of"] = duplicate_of
            row["near_duplicate_similarity"] = round(duplicate_score, 4)
            row["input_position"] = position
            check["errors"] = [reason]
            check["accepted"] = False
            near_duplicates.append({"record_id_a": duplicate_of, "record_id_b": row["record_id"],
                                    "similarity": round(duplicate_score, 4), "action": "removed_as_duplicate"})
            # A later exact copy of a removed near-duplicate is still an exact duplicate
            # of an input record, so keep the duplicate keys for subsequent rows.
            seen_ids[row["record_id"]] = row["record_id"]
            seen_urls[canonical] = row["record_id"]
            seen_fingerprints[fingerprint] = row["record_id"]
            deduplicated.append(row)
            continue
        accepted.append(row)
        seen_ids[row["record_id"]] = row["record_id"]
        seen_urls[canonical] = row["record_id"]
        seen_fingerprints[fingerprint] = row["record_id"]
        examples.append({"record_id": row["record_id"], "scenic_area": row["scenic_area"], "title": row["title"],
                         "source_url": row["source_url"], "raw_format": row["raw_format"],
                         "before": raw[:1500], "after": cleaned[:1500], "raw_char_count": len(raw),
                         "clean_char_count": len(cleaned), "cleaning_counts": rule_counts,
                         "sample_is_excerpt": len(raw) > 1500 or len(cleaned) > 1500})

    report = summarize_dataset(accepted, rejected, deduplicated, near_duplicates, record_checks,
                               dict(aggregate_rules), dict(input_missing), len(records), positions,
                               min_travelogue_length, min_official_length)
    return accepted, report, rejected, deduplicated, examples


def read_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_number}: each JSONL record must be an object")
            records.append(obj)
    return records


def _json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _scalar(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def export_outputs(output_dir: Path, rows: list[dict], report: dict,
                   rejected: list[dict], deduplicated: list[dict],
                   examples: list[dict]) -> None:
    """Write lossless CSV/JSONL and prepare long-cell sidecars for optional XLSX.

    ``rows`` is the deduplicated corpus; removed near-duplicate copies go to
    ``deduplicated_records.jsonl`` for audit. Use ``src/export_dataset_xlsx.py``
    to author the deliverable workbook from these files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = BASE_FIELDS + DERIVED_FIELDS
    extras = sorted({key for row in rows for key in row} - set(fields))
    fields += extras
    _jsonl(output_dir / "dataset_clean.jsonl", rows)
    _jsonl(output_dir / "rejected_records.jsonl", rejected)
    _jsonl(output_dir / "deduplicated_records.jsonl", deduplicated)
    _json(output_dir / "cleaning_examples.json", examples)
    with (output_dir / "dataset_clean.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        csv_fields = [key for key in fields if key != "provenance_note"]
        writer = csv.DictWriter(handle, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _scalar(row.get(key, "")) for key in csv_fields})

    externalized = []
    long_dir = output_dir / "long_text"
    for row_index, row in enumerate(rows, start=2):
        for key in fields:
            value = _scalar(row.get(key, ""))
            if isinstance(value, str) and len(value) > EXCEL_LIMIT:
                long_dir.mkdir(exist_ok=True)
                safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", row["record_id"]) or f"row{row_index}"
                target = long_dir / f"{row_index:04d}_{safe_id}_{key}.txt"
                # Byte-exact UTF-8 prevents Windows newline translation from
                # changing the sidecar or making its SHA-256 audit inaccurate.
                target.write_bytes(value.encode("utf-8"))
                rel_path = target.relative_to(output_dir).as_posix()
                externalized.append({"record_id": row["record_id"], "field": key, "characters": len(value), "path": rel_path,
                                     "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()})
    report["xlsx_authoring"] = {"engine": "openpyxl", "script": "src/export_dataset_xlsx.py",
                                "status": "generated"}
    report["dataset_fields"] = fields
    report["xlsx_long_text_externalization"] = externalized
    report["output_files"] = {"csv": "dataset_clean.csv", "jsonl": "dataset_clean.jsonl",
                              "xlsx": "dataset_clean.xlsx", "quality_report": "quality_report.json",
                              "cleaning_examples": "cleaning_examples.json",
                              "rejected_records": "rejected_records.jsonl",
                              "deduplicated_records": "deduplicated_records.jsonl"}
    _json(output_dir / "quality_report.json", report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean scenic-area captures and export CSV/JSONL with quality audit.")
    parser.add_argument("--input", type=Path, default=Path("data/raw/dataset_raw.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/rebuild"))
    parser.add_argument("--min-travelogue-length", type=int, default=80)
    parser.add_argument("--min-official-length", type=int, default=30)
    parser.add_argument("--require-target", action="store_true", help="Return exit code 2 if any scenic area lacks 1 official route and 5 travelogues.")
    args = parser.parse_args(argv)
    records = read_jsonl(args.input)
    rows, report, rejected, deduplicated, examples = preprocess_records(records, args.min_travelogue_length, args.min_official_length)
    report["input_path"] = args.input.as_posix()
    report["input_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest()
    export_outputs(args.output_dir, rows, report, rejected, deduplicated, examples)
    print(json.dumps({key: report[key] for key in ("input_records", "accepted_records", "rejected_records", "deduplicated_records", "main_target_met", "minimum_target_met")}, ensure_ascii=False))
    return 2 if args.require_target and not report["main_target_met"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
