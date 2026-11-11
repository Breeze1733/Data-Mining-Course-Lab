"""Screen and merge genuine Xiaohongshu notes exported from a logged-in DOM.

Run after the browser export exists::

    python src/import_browser_notes.py

The input export is never modified. Every candidate body, including rejected
ones, receives a text snapshot and an audit entry. No page is fetched, no text is
rewritten and there is no record-count limit. All classifications describe the
source text's narrative form, not independently verified physical travel.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from preprocess import clean_text


ROOT = Path(__file__).resolve().parents[1]
PREFIXES = {"黄山": "HS", "九寨沟": "JZG", "颐和园": "YHY"}
# Aliases of one node count once; regional destinations such as 宏村/黄龙 do
# not count as POIs of the selected scenic area.
POIS = {
    "黄山": {
        "迎客松": ("迎客松",), "光明顶": ("光明顶",), "始信峰": ("始信峰",),
        "排云亭": ("排云亭",), "西海大峡谷": ("西海大峡谷", "西海峡谷"),
        "天都峰": ("天都峰",), "莲花峰": ("莲花峰",), "鳌鱼峰": ("鳌鱼峰", "鳌鱼背"),
        "一线天": ("一线天",), "百步云梯": ("百步云梯",), "玉屏楼": ("玉屏楼",),
        "白鹅岭": ("白鹅岭",), "清凉台": ("清凉台",), "猴子观海": ("猴子观海",),
        "狮子峰": ("狮子峰",), "飞来石": ("飞来石",), "步仙桥": ("步仙桥",),
        "云谷寺": ("云谷寺",), "慈光阁": ("慈光阁",), "松谷庵": ("松谷庵",),
        "玉屏索道": ("玉屏索道", "玉屏站", "玉屏缆车"),
        "云谷索道": ("云谷索道", "云谷缆车"), "太平索道": ("太平索道", "太平缆车"),
        "天海": ("天海站", "天海景区"), "排云溪": ("排云溪站", "排云溪"),
        "北海宾馆": ("北海宾馆",), "白云宾馆": ("白云宾馆",),
        "西海饭店": ("西海饭店",), "狮林大酒店": ("狮林大酒店",),
    },
    "九寨沟": {
        "原始森林": ("原始森林",), "草海": ("草海",), "天鹅海": ("天鹅海",),
        "箭竹海": ("箭竹海",), "箭竹海瀑布": ("箭竹海瀑布",),
        "熊猫海": ("熊猫海",), "五花海": ("五花海",), "珍珠滩": ("珍珠滩",),
        "珍珠滩瀑布": ("珍珠滩瀑布",), "镜海": ("镜海",), "长海": ("长海",),
        "五彩池": ("五彩池",), "诺日朗中心": ("诺日朗中心", "诺日朗游客中心", "诺日朗服务中心"),
        "诺日朗瀑布": ("诺日朗瀑布",), "犀牛海": ("犀牛海",), "老虎海": ("老虎海",),
        "树正瀑布": ("树正瀑布",), "树正群海": ("树正群海",), "树正寨": ("树正寨",),
        "卧龙海": ("卧龙海",), "火花海": ("火花海",), "双龙海": ("双龙海",),
        "芦苇海": ("芦苇海",), "盆景滩": ("盆景滩",), "则查洼寨": ("则查洼寨", "则渣洼寨"),
        "季节海": ("上季节海", "下季节海", "上下季节海"),
    },
    "颐和园": {
        "东宫门": ("东宫门",), "北宫门": ("北宫门",), "新建宫门": ("新建宫门",),
        "西门": ("颐和园西门", "西门"), "南如意门": ("南如意门",), "北如意门": ("北如意门",),
        "仁寿殿": ("仁寿殿",), "德和园": ("德和园",), "玉澜堂": ("玉澜堂",),
        "宜芸馆": ("宜芸馆",), "乐寿堂": ("乐寿堂",), "长廊": ("长廊",),
        "排云门": ("排云门",), "排云殿": ("排云殿",), "佛香阁": ("佛香阁",),
        "万寿山": ("万寿山",), "昆明湖": ("昆明湖",), "十七孔桥": ("十七孔桥",),
        "南湖岛": ("南湖岛",), "铜牛": ("铜牛",), "西堤": ("西堤",),
        "景明楼": ("景明楼",), "练桥": ("练桥",), "镜桥": ("镜桥",),
        "玉带桥": ("玉带桥",), "豳风桥": ("豳风桥",), "界湖桥": ("界湖桥",),
        "半壁桥": ("半壁桥", "半璧桥"), "绣漪桥": ("绣漪桥",), "石舫": ("石舫",),
        "苏州街": ("苏州街",), "画中游": ("画中游",), "四大部洲": ("四大部洲",),
        "谐趣园": ("谐趣园",), "养云轩": ("养云轩",), "文昌阁": ("文昌阁",),
    },
}
ROUTE_PATTERNS = (
    r"路线|线路|行程|走法|入园|出园|游览次序|游览顺序|游玩顺序|游览路线|游览安排",
    r"→|⇒|➡|➜|->|—>|-->", r"先.{0,60}(?:再|然后)|随后|之后|接着|接下来",
    r"从.{1,25}(?:走到|走向|到达|出发|进入|坐车|乘车)|沿.{1,25}(?:走|到)",
    r"(?:上午|下午|早上|傍晚|第一天|第二天|\d{1,2}[:：]\d{2}).{0,30}(?:到|走|游|去|上车|下车)",
)
AD_PATTERNS = (
    r"(?:加|添加|联系).{0,12}(?:微信|微[信xX]|[vV][xX]|[vV]信)",
    r"私信.{0,20}(?:报团|包车|预订|预约|咨询|定制|报名)",
    r"(?:扫码|联系我|戳我).{0,20}(?:报名|咨询|定制|包车|预订)",
    r"(?:报团|包车|私家团|定制游).{0,12}(?:优惠|报价|下单|咨询|报名)",
    r"(?:旅行社|旅游公司|订票平台).{0,15}(?:咨询|联系|报名|客服)",
)
QUESTION_PATTERNS = (
    r"求(?:路线|攻略|助|推荐)|请问|求问|求解|有谁.{0,12}去过|有人.{0,15}(?:去过|走过)",
    r"有没有.{0,20}(?:路线|攻略|推荐)|该怎么(?:走|安排)|怎么安排(?:比较|才|更)",
)
FIRST_PERSON_STRONG = (
    r"(?:我|我们|本人|自己|咱们).{0,18}(?:去了|去过|走了|走过|逛了|玩了|到达|出发|坐了|坐上|回来|游玩|徒步|游览|提前一天)",
    r"亲测|实测|我从.{0,20}(?:走到|去了|走|坐|到)|我们是.{0,20}(?:进|出|走|到)",
    r"(?:今天|昨天|上周|周末|周五|此次|这次|此行).{0,35}(?:抵达|爬了|走了|坐上|游览|游玩|出发|下山|上山)",
)
ADVICE_PATTERN = r"建议|推荐|适合|可以按|可以先|最佳路线|攻略如下|路线如下|游览攻略|避坑"


def canonical_note_url(value: str) -> tuple[str, str]:
    """Normalize public note identity; tracking/access query strings are not IDs."""
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or parts.hostname not in ("xiaohongshu.com", "www.xiaohongshu.com"):
        raise ValueError("not_a_full_xiaohongshu_note_url")
    match = re.fullmatch(r"/(?:explore|discovery/item|search_result)/([0-9a-fA-F]{24})/?", parts.path)
    if not match:
        raise ValueError("missing_24_digit_note_id")
    note_id = match[1].lower()
    return "https://www.xiaohongshu.com/explore/" + note_id, note_id


def text_list(value) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    return []


def metadata_dates(row: dict) -> tuple[str, str, list[str]]:
    """Derive only explicitly year-qualified publication dates from DOM metadata."""
    raw = row.get("published_at_raw", "")
    candidates = text_list(raw) + text_list(row.get("date_candidates", []))
    if not candidates and row.get("published_at"):
        candidates = text_list(row["published_at"])
    raw_text = raw if isinstance(raw, str) else " | ".join(text_list(raw))
    if not raw_text:
        raw_text = " | ".join(candidates)
    absolute = set()
    for value in candidates:
        for match in re.finditer(r"(?<!\d)((?:19|20)\d{2})[年./-](\d{1,2})[月./-](\d{1,2})(?:日)?", value):
            try:
                absolute.add(date(*(int(part) for part in match.groups())).isoformat())
            except ValueError:
                continue
    flags = []
    if len(absolute) == 1:
        return absolute.pop(), raw_text, flags
    flags.append("publication_date_ambiguous" if absolute else "publication_year_unknown")
    return "", raw_text, flags


def poi_hits(area: str, body: str) -> list[dict]:
    """Return distinct nodes; a longer matched POI suppresses nested substrings."""
    matches = []
    for canonical, aliases in POIS.get(area, {}).items():
        for alias in aliases:
            for found in re.finditer(re.escape(alias), body):
                matches.append((found.start(), found.end(), canonical, alias))
    matches.sort(key=lambda item: (-(item[1] - item[0]), item[0]))
    retained = []
    for item in matches:
        if not any(item[0] >= old[0] and item[1] <= old[1] for old in retained):
            retained.append(item)
    result = {}
    for start, end, node, alias in sorted(retained):
        result.setdefault(node, {"poi": node, "matched_text": alias, "position_in_screened_text": start})
    return list(result.values())


def regex_evidence(patterns: tuple[str, ...], text: str) -> list[str]:
    results = []
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match and match.group() not in results:
            results.append(match.group())
    return results


def advertisement_evidence(text: str) -> list[str]:
    results = []
    for pattern in AD_PATTERNS:
        for match in re.finditer(pattern, text, re.I):
            preceding = text[max(0, match.start() - 10):match.start()]
            if re.search(r"(?:不要|切勿|别|拒绝|不用|无需|谨防|警惕|不能).{0,6}$", preceding):
                continue
            if match.group() not in results:
                results.append(match.group())
    return results


def experienced_evidence(text: str) -> list[str]:
    results = []
    for pattern in FIRST_PERSON_STRONG:
        for match in re.finditer(pattern, text, re.I):
            claim = match.group()
            if re.search(r"计划|想要|想去|准备|打算|建议|推荐|如果|可以|将要", claim):
                continue
            if claim not in results:
                results.append(claim)
    return results


def advisory_evidence(text: str) -> list[str]:
    """Count assertive advice, not phrases such as '求建议' or '推荐吗？'."""
    results = []
    for match in re.finditer(ADVICE_PATTERN, text):
        left = max(text.rfind(mark, 0, match.start()) for mark in "。！？!?\n") + 1
        stops = [text.find(mark, match.end()) for mark in "。！？!?\n"]
        stops = [index for index in stops if index >= 0]
        right = min(stops) if stops else len(text)
        sentence = text[left:right]
        if right < len(text) and text[right] in "？?":
            continue
        if regex_evidence(QUESTION_PATTERNS, sentence):
            continue
        preceding = text[max(left, match.start() - 12):match.start()]
        if re.search(r"(?:求|请|有没有|有何|哪条|哪个|哪种).{0,8}$", preceding):
            continue
        if match.group() not in results:
            results.append(match.group())
    return results


def screen_note(row: dict) -> dict:
    """Evaluate a candidate without editing its original title/body."""
    errors, flags = [], []
    body = row.get("raw_content")
    if not isinstance(body, str):
        errors.append("body_not_string")
        body = ""
    area = row.get("scenic_area", "")
    if area not in PREFIXES:
        errors.append("unknown_scenic_area")
    try:
        canonical, note_id = canonical_note_url(str(row.get("source_url", "")))
    except (ValueError, TypeError):
        canonical, note_id = "", ""
        errors.append("invalid_full_note_url")
    screened, _, _ = clean_text(body, "text")
    length = len(re.sub(r"\s", "", screened))
    if length < 80:
        errors.append("body_shorter_than_80_nonspace_characters")
    nodes = poi_hits(area, screened)
    if len(nodes) < 2:
        errors.append("fewer_than_2_distinct_in_scenic_area_pois")
    route = regex_evidence(ROUTE_PATTERNS, screened)
    if not route:
        errors.append("no_route_or_visit_sequence_evidence")
    # Advertising is screened from both title and body, but "酒店推荐" alone
    # is not an advertisement: ordinary travellers also discuss accommodation.
    ads = advertisement_evidence(str(row.get("title", "")) + "\n" + screened)
    if ads:
        errors.append("commercial_solicitation")
    actual = experienced_evidence(screened)
    advice = advisory_evidence(screened)
    questions = regex_evidence(QUESTION_PATTERNS, str(row.get("title", "")) + "\n" + screened)
    if questions and not actual and not advice:
        errors.append("question_request_without_experienced_or_advisory_route")
    elif questions:
        flags.append("contains_question_cue_with_substantive_route_requires_review")
    if actual:
        subtype = "first_person_travelogue"
    elif advice:
        subtype = "visitor_route_advice"
    else:
        subtype = "uncertain"
        flags.append("narrative_subtype_uncertain")
    collected = row.get("collected_at", "")
    try:
        parsed = datetime.fromisoformat(str(collected).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            flags.append("collection_time_has_no_explicit_timezone")
    except ValueError:
        errors.append("missing_or_invalid_collection_datetime")
    published, date_raw, date_flags = metadata_dates(row)
    flags += date_flags
    author = row.get("author", "")
    if not isinstance(author, str) or not author.strip():
        authors = text_list(row.get("authors", []))
        author = authors[0] if len(authors) == 1 else ""
        if len(authors) > 1:
            flags.append("multiple_author_candidates")
    if not author:
        flags.append("author_missing")
    if not row.get("title"):
        errors.append("title_missing")
    return {
        "accepted": not errors, "rejection_reasons": errors, "flags": list(dict.fromkeys(flags)),
        "canonical_url": canonical, "note_id": note_id, "scenic_area": area,
        "body_nonspace_characters": length, "poi_count": len(nodes), "poi_hits": nodes,
        "route_evidence": route, "advertising_evidence": ads, "question_evidence": questions,
        "first_person_evidence": actual, "advice_evidence": advice, "note_subtype": subtype,
        "published_at": published, "published_at_raw": date_raw, "author": author,
    }


def load_array(path: Path, required=False) -> list[dict]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Browser export not found: {path}")
        return []
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"Expected an array of note objects: {path}")
    return value


def iso_sort_value(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError):
        return 0.0


def run(input_path: Path, output_path: Path, audit_path: Path) -> dict:
    if input_path.resolve() in (output_path.resolve(), audit_path.resolve()):
        raise ValueError("Input browser export must remain separate from all outputs")
    exported = load_array(input_path, required=True)
    existing = load_array(output_path)
    existing_by_url = {}
    timestamp_lookup = {}
    for row in existing:
        try:
            canonical, _ = canonical_note_url(row.get("source_url", ""))
            existing_by_url[canonical] = row
            if row.get("collected_at"):
                timestamp_lookup[canonical] = row["collected_at"]
        except (ValueError, TypeError):
            continue
    # An earlier collection may hold a timestamp absent from the legacy notes.
    current_records = ROOT / "data/raw/dataset_raw.jsonl"
    if current_records.exists():
        for line in current_records.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            try:
                canonical, _ = canonical_note_url(row.get("source_url", ""))
                if row.get("collected_at"):
                    timestamp_lookup.setdefault(canonical, row["collected_at"])
            except (ValueError, TypeError):
                pass
    browser_dir = ROOT / "data/raw/browser"
    candidate_dir = browser_dir / "screening_candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    groups = defaultdict(list)
    checks = []
    input_digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
    # Existing notes participate as candidates so a bad/empty new DOM capture
    # cannot overwrite a previously valid note. All duplicate bodies stay in audit.
    all_rows = [("existing", index, row) for index, row in enumerate(existing, 1)]
    all_rows += [("browser_export", index, row) for index, row in enumerate(exported, 1)]
    for origin, index, original in all_rows:
        row = dict(original)
        try:
            canonical, _ = canonical_note_url(str(row.get("source_url", "")))
            if not row.get("collected_at") and canonical in timestamp_lookup:
                row["collected_at"] = timestamp_lookup[canonical]
                inherited_timestamp = True
            else:
                inherited_timestamp = False
        except (ValueError, TypeError):
            inherited_timestamp = False
        checked = screen_note(row)
        raw = row.get("raw_content", "")
        raw = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        body_digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        identity = checked["note_id"][-8:] or "invalid_url"
        relative = f"data/raw/browser/screening_candidates/{origin}_{index:04d}_{identity}_{body_digest[:10]}.txt"
        (ROOT / relative).write_bytes(raw.encode("utf-8"))
        checked.update({"origin": origin, "input_index": index, "title": row.get("title", ""),
                        "source_url_input": row.get("source_url", ""), "candidate_snapshot": relative,
                        "candidate_sha256": body_digest, "collected_at": row.get("collected_at", ""),
                        "collection_time_inherited_from_existing_record": inherited_timestamp,
                        "merge_action": "rejected_by_screening" if not checked["accepted"] else "pending_merge"})
        checks.append(checked)
        if checked["canonical_url"]:
            groups[checked["canonical_url"]].append((row, checked))
    merged = []
    used_ids = set()
    for canonical, candidates in groups.items():
        accepted = [(row, checked) for row, checked in candidates if checked["accepted"]]
        if not accepted:
            continue
        # Prefer the fullest valid body; use the latest genuine capture only as
        # a tie breaker. There is no top-N or per-scenic-area cap.
        accepted.sort(key=lambda pair: (pair[1]["body_nonspace_characters"], iso_sort_value(pair[0].get("collected_at", ""))), reverse=True)
        chosen, selected = accepted[0]
        areas = {checked["scenic_area"] for _, checked in accepted}
        if len(areas) > 1:
            selected["flags"].append("same_note_exported_for_multiple_scenic_areas")
        old = existing_by_url.get(canonical, {})
        record_id = old.get("record_id") or f"{PREFIXES[selected['scenic_area']]}-X{selected['note_id'][-8:]}"
        if record_id in used_ids:
            record_id = f"{PREFIXES[selected['scenic_area']]}-X{selected['note_id']}"
            selected["flags"].append("short_note_id_collision_full_note_id_used")
        used_ids.add(record_id)
        relative = f"data/raw/browser/{record_id}.txt"
        body = chosen["raw_content"]
        (ROOT / relative).write_bytes(body.encode("utf-8"))
        result = {**old, **chosen,
            "record_id": record_id, "scenic_area": selected["scenic_area"],
            "source_platform": "小红书", "source_url": canonical, "text_type": "travelogue",
            "raw_format": "text", "raw_file": relative,
            "extraction_selector": chosen.get("extraction_selector", "#detail-desc.innerText"),
            "content_scope": chosen.get("content_scope", "visible_note_text_only_no_image_OCR_no_comments"),
            "author": selected["author"], "published_at": selected["published_at"],
            "published_at_raw": selected["published_at_raw"], "note_subtype": selected["note_subtype"],
            "acquisition_method": "用户扫码登录后浏览器DOM自动提取；原始导出保留并经规则筛选",
            "snapshot_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "screening_flags": list(dict.fromkeys(selected["flags"])),
            "screening_poi_hits": [item["poi"] for item in selected["poi_hits"]],
            "screening_route_evidence": selected["route_evidence"],
            "date_note": "仅采用原始日期元数据明确给出的年份",
        }
        merged.append(result)
        selected["merge_action"] = "selected_for_merged_dataset"
        selected["record_id"] = record_id
        for _, duplicate in accepted[1:]:
            duplicate["merge_action"] = "canonical_url_duplicate_retained_in_audit"
            duplicate["merged_record_id"] = record_id
    by_area = Counter(row["scenic_area"] for row in merged)
    by_subtype = Counter(row["note_subtype"] for row in merged)
    audit = {
        "input_export": str(input_path), "input_export_sha256": input_digest,
        "input_export_records": len(exported), "existing_records": len(existing),
        "screened_candidate_records": len(checks), "screening_rejected_candidates": sum(not c["accepted"] for c in checks),
        "screening_accepted_candidates": sum(c["accepted"] for c in checks), "merged_unique_notes": len(merged),
        "selected_by_scenic_area": dict(by_area), "selected_by_note_subtype": dict(by_subtype),
        "rejection_reason_counts": dict(Counter(reason for c in checks for reason in c["rejection_reasons"])),
        "flag_counts": dict(Counter(flag for c in checks for flag in c["flags"])),
        "policy": {"min_body_nonspace_characters": 80, "min_distinct_in_scenic_area_pois": 2,
                   "route_or_sequence_evidence_required": True, "record_count_limit": None,
                   "first_person_label_meaning": "source contains first-person/experienced narrative cues; physical visit not independently verified",
                   "advice_label_meaning": "visitor-authored route advice; not claimed to be an actual completed route",
                   "uncertain_label_meaning": "route evidence exists but narrative form requires review",
                   "publication_year_inference": "never infer year from collection date or month/day metadata",
                   "duplicate_policy": "canonical note URL; keep fullest valid body, then latest genuine collection timestamp",
                   "raw_text_policy": "byte-exact UTF-8 snapshots; original browser export unchanged"},
        "candidates": checks,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes((json.dumps(merged, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    audit_path.write_bytes((json.dumps(audit, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return {key: audit[key] for key in ("input_export_records", "existing_records", "screening_rejected_candidates", "merged_unique_notes", "selected_by_scenic_area", "selected_by_note_subtype")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Screen logged-in Xiaohongshu DOM exports without rewriting source text.")
    parser.add_argument("--input", type=Path, default=ROOT / "data/raw/xiaohongshu_browser_export.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/raw/xiaohongshu.json")
    parser.add_argument("--audit", type=Path, default=ROOT / "data/crawl/xiaohongshu_screening.json")
    args = parser.parse_args()
    print(json.dumps(run(args.input, args.output, args.audit), ensure_ascii=False))


if __name__ == "__main__":
    main()
