"""把三类已采集的原始数据组装为 preprocess.py 可读的 data/raw/records.jsonl。

输入（全部为本机已有快照，不发网络请求）：
  data/raw/official_documents.jsonl            官方文档（include_in_main_dataset=true 的进入主数据集）
  data/crawl/ctrip_ranked_candidates.json      携程候选（accepted=true 且快照存在的进入）
  data/raw/xiaohongshu_browser_export.json     小红书笔记导出（全部进入，短文本由清洗阶段按长度规则淘汰）

携程记录的 raw_content 取正文容器（travel-content-wrapper，缺省时 rich-text-container）
的外层 HTML 片段：站点导航、页脚等页面杂项不进入，容器内的 HTML 标签交给
preprocess.clean_text 的 HTML 清洗规则处理，清洗效果可审计。
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from lxml import html

ROOT = Path(__file__).resolve().parents[1]
if getattr(sys.stdout, "encoding", "").lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

OFFICIAL_DOMAINS = {
    "www.jiuzhai.com", "jiuzhai.com",
    "summerpalace.net.cn", "www.summerpalace.net.cn",
    "wap.huangshan.com.cn", "huangshan.com.cn",
    "gygl.beijing.gov.cn", "www.beijing.gov.cn", "www.bjwmb.gov.cn",
    "news.bjd.com.cn", "www.ahsz.gov.cn",
}


def note_id(url: str) -> str:
    return url.rstrip("/").split("/")[-1].split("?")[0]


def wrapper_fragment(page_bytes: bytes) -> tuple[str, str]:
    """返回正文容器外层 HTML 片段与实际使用的选择器。"""
    doc = html.fromstring(page_bytes)
    nodes = doc.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " travel-content-wrapper ")]')
    selector = "travel-content-wrapper"
    if not nodes:
        nodes = doc.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " rich-text-container ")]')
        selector = "rich-text-container"
    if not nodes:
        raise ValueError("no article body container in snapshot")
    fragment = html.tostring(nodes[0], encoding="unicode")
    return fragment, selector


def build_official(docs: list[dict]) -> list[dict]:
    records = []
    for doc in docs:
        if not doc.get("accepted"):
            continue
        domain = urlsplit(doc["source_url"]).netloc
        selector = doc.get("extraction_selector") or doc.get("xpath", "")
        if doc.get("text_start") or doc.get("text_end"):
            selector += f"; text_start={doc.get('text_start', '')}; text_end={doc.get('text_end', '')}"
        records.append({
            "record_id": doc["evidence_id"],
            "scenic_area": doc["scenic_area"],
            "source_platform": "官方" if domain in OFFICIAL_DOMAINS else "官方推荐转载",
            "source_url": doc["source_url"],
            "title": doc["title"],
            "text_type": "official_route",
            "collected_at": doc["collected_at"],
            "raw_content": doc["raw_content"],
            "raw_format": "text",
            "extraction_selector": selector,
            "raw_file": doc["snapshot_file"],
            "content_scope": "official_target_route_section",
            "author": "",
            "published_at": doc.get("published_at", ""),
            "provenance_note": doc.get("provenance_note", ""),
            "snapshot_sha256": doc.get("snapshot_sha256", ""),
            # 采集阶段只把有具体节点顺序的文档计入有序路线数（include_in_main_dataset）；
            # 无固定顺序的主题方案仍是官方语料，保留标记供实验3区分使用方式。
            "official_scope": "main" if doc.get("include_in_main_dataset") else "supplementary_theme",
        })
    return records


def build_ctrip(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    records, problems = [], []
    for cand in candidates:
        if not cand.get("accepted"):
            continue
        path = ROOT / cand["raw_file"]
        if not path.exists():
            problems.append({"record_id": cand["record_id"], "problem": "snapshot_missing"})
            continue
        page = path.read_bytes()
        if cand.get("snapshot_sha256") and hashlib.sha256(page).hexdigest() != cand["snapshot_sha256"]:
            problems.append({"record_id": cand["record_id"], "problem": "snapshot_hash_mismatch"})
            continue
        try:
            fragment, selector = wrapper_fragment(page)
        except ValueError as exc:
            problems.append({"record_id": cand["record_id"], "problem": str(exc)})
            continue
        records.append({
            "record_id": cand["record_id"],
            "scenic_area": cand["scenic_area"],
            "source_platform": "携程游记",
            "source_url": cand["url"],
            "title": cand.get("title", ""),
            "text_type": "travelogue",
            "collected_at": cand["collected_at"],
            "raw_content": fragment,
            "raw_format": "html",
            "extraction_selector": f"{cand.get('extraction_selector', '')} (outer HTML of body container)",
            "raw_file": cand["raw_file"],
            "content_scope": "article_body_container_fragment",
            "author": cand.get("author", ""),
            "published_at": cand.get("published_at", ""),
        })
    return records, problems


def build_xhs(notes: list[dict]) -> list[dict]:
    records = []
    for note in notes:
        records.append({
            "record_id": "XHS_" + note_id(note["source_url"]),
            "scenic_area": note["scenic_area"],
            "source_platform": "小红书",
            "source_url": note["source_url"],
            "title": note.get("title", ""),
            "text_type": "travelogue",
            "collected_at": note["collected_at"],
            "raw_content": note["raw_content"],
            "raw_format": "text",
            "extraction_selector": note.get("extraction_selector", ""),
            "raw_file": "data/raw/xiaohongshu_browser_export.json",
            "content_scope": note.get("content_scope", "visible_note_text_only_no_image_OCR_no_comments"),
            "author": note.get("author", ""),
            "published_at": note.get("published_at_raw", ""),
            "like_count": note.get("like_count", ""),
        })
    return records


def main() -> int:
    docs = [json.loads(line) for line in (ROOT / "data/raw/official_documents.jsonl").open(encoding="utf-8") if line.strip()]
    candidates = json.loads((ROOT / "data/crawl/ctrip_ranked_candidates.json").read_text(encoding="utf-8"))
    notes = json.loads((ROOT / "data/raw/xiaohongshu_browser_export.json").read_text(encoding="utf-8"))

    official = build_official(docs)
    ctrip, problems = build_ctrip(candidates)
    xhs = build_xhs(notes)

    records, seen = [], set()
    duplicates = []
    for row in official + ctrip + xhs:
        if row["record_id"] in seen:
            duplicates.append(row["record_id"])
            continue
        seen.add(row["record_id"])
        records.append(row)

    out = ROOT / "data/raw/records.jsonl"
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "official_docs": len(official),
        "ctrip_travelogues": len(ctrip),
        "xhs_notes": len(xhs),
        "total_records": len(records),
        "duplicate_record_ids": duplicates,
        "ctrip_problems": problems,
        "output": out.as_posix(),
    }
    (ROOT / "data/raw/assembly_audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
