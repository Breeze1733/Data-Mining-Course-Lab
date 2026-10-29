"""实体 schema 常量与校验。"""

from __future__ import annotations

import hashlib
from typing import Any

TYPE_POI = "景点POI"
TYPE_TRANSPORT = "交通方式"
TYPE_TIME = "时间节点"
TYPES = (TYPE_POI, TYPE_TRANSPORT, TYPE_TIME)

POI_SUBTYPES = {
    "景区",
    "景区片区",
    "山峰",
    "湖泊水体",
    "瀑布滩地",
    "峡谷森林",
    "建筑殿阁",
    "门入口",
    "站点服务中心",
    "桥梁",
    "村寨街区",
    "其他",
}

TRANSPORT_SUBTYPES = {
    "索道缆车",
    "景区车摆渡车",
    "步行徒步",
    "公路客运",
    "铁路",
    "航空",
    "城市公交",
    "自驾出租",
    "水运",
    "轨道车",
    "骑行",
    "其他",
}

TIME_SUBTYPES = {
    "时刻",
    "时刻区间",
    "时段",
    "日期",
    "日期区间",
    "月份区间",
    "相对日",
    "季节",
    "节日",
    "重复",
    "时长",
}

SUBTYPES = {
    TYPE_POI: POI_SUBTYPES,
    TYPE_TRANSPORT: TRANSPORT_SUBTYPES,
    TYPE_TIME: TIME_SUBTYPES,
}

METHODS = {
    "dictionary_longest_match",
    "dictionary_alias",
    "regex",
    "regex_range",
    "regex_merge",
    "jieba_ns",
    "context_rule",
    "generic_suffix",
    "area_name_match",
}

SOURCE_KINDS = {"tourist", "official_route", "official_document"}

REQUIRED_FIELDS = (
    "entity_id",
    "type",
    "subtype",
    "surface",
    "normalized",
    "frequency_key",
    "source_kind",
    "source_file",
    "source_record_id",
    "source_id_field",
    "source_line",
    "scenic_area",
    "start",
    "end",
    "offset_unit",
    "text_sha256",
    "record_char_count",
    "sentence_index",
    "clause_index",
    "context",
    "method",
    "rule_id",
    "confidence",
    "iteration",
    "counts_as_time_node",
)


def make_entity_id(record_id: str, start: int, end: int) -> str:
    """与类型无关的稳定 ID：同一 span 在迭代前后保持一致。"""
    digest = hashlib.sha1(f"{record_id}|{start}|{end}".encode("utf-8")).hexdigest()
    return "ENT-" + digest[:12]


def validate_entity(
    entity: dict[str, Any],
    text: str,
    source_kinds: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in entity:
            errors.append(f"missing:{field}")
    if errors:
        return errors

    entity_type = entity["type"]
    if entity_type not in TYPES:
        errors.append(f"bad_type:{entity_type}")
    elif entity["subtype"] not in SUBTYPES[entity_type]:
        errors.append(f"bad_subtype:{entity_type}/{entity['subtype']}")
    allowed_kinds = source_kinds if source_kinds is not None else SOURCE_KINDS
    if entity["source_kind"] not in allowed_kinds:
        errors.append(f"bad_source_kind:{entity['source_kind']}")
    if entity["method"] not in METHODS:
        errors.append(f"bad_method:{entity['method']}")
    try:
        start = int(entity["start"])
        end = int(entity["end"])
    except (TypeError, ValueError):
        errors.append("bad_offset_type")
        return errors
    if not (0 <= start < end <= len(text)):
        errors.append(f"offset_out_of_range:{start}:{end}:{len(text)}")
    elif text[start:end] != entity["surface"]:
        errors.append("offset_surface_mismatch")
    if entity["offset_unit"] != "unicode_codepoint":
        errors.append(f"bad_offset_unit:{entity['offset_unit']}")
    try:
        confidence = float(entity["confidence"])
        if not 0.0 <= confidence <= 1.0:
            errors.append(f"bad_confidence:{confidence}")
    except (TypeError, ValueError):
        errors.append("bad_confidence_type")
    if not isinstance(entity["counts_as_time_node"], bool):
        errors.append("bad_counts_as_time_node")
    return errors
