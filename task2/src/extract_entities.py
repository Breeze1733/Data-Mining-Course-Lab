"""实验2：三类实体识别（jieba 分词 + 自定义词典最长匹配 + 时间正则）。

用法：
  python src/exp2/extract_entities.py --iteration baseline   # 第1轮：采集种子词典（无停用词、无别名）
  python src/exp2/extract_entities.py --iteration refined    # 第2轮：整理后词典 + 领域停用词

输出：output/exp2/entities_{iteration}.jsonl（逐记录实体，含偏移量）、entity_stats_{iteration}.json
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import jieba

ROOT = Path(__file__).resolve().parents[1]  # task2/
OUT = ROOT / "output/exp2"
TASK1 = ROOT.parent / "task1"

# 时间节点正则：优先级从左到右（同一位置先命中的胜出）
TIME_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("日期", "date", re.compile(
        r"20\d{2}年\d{1,2}月\d{1,2}[日号]|[10]?\d月[123]?\d?[日号]|Day\s*\d+|第[一二三四五六七八九十\d]+天")),
    ("时刻", "clock", re.compile(
        r"\d{1,2}[:：点](?:\d{1,2}|半)?分?\s*[-–—~～至]{1,2}\s*\d{1,2}[:：点](?:\d{1,2}|半)?分?"
        r"|(?:清晨|早上|上午|中午|下午|傍晚|晚上|夜里|深夜|凌晨)约?\d{1,2}[点:：](?:\d{1,2}|半)?分?(?:左右)?"
        r"|\d{1,2}[点:：](?:\d{1,2}|半)?分?(?:左右)?")),
    ("时长", "duration", re.compile(
        r"(?:约|大概|差不多|将近|近)?\d+(?:\.\d+)?\s*(?:个)?(?:小时|钟头|分钟)|半小时")),
    ("时段", "period", re.compile(
        r"清晨|早上|上午|中午|下午|傍晚|晚上|夜里|深夜|凌晨|全天")),
]
TIME_COMBINED = re.compile("|".join(f"(?P<g{i}>{p.pattern})" for i, (_, _, p) in enumerate(TIME_PATTERNS)))


def time_entities(text: str) -> list[dict]:
    found = []
    for m in TIME_COMBINED.finditer(text):
        gid = m.lastgroup
        idx = int(gid[1:])
        label, sub, _ = TIME_PATTERNS[idx]
        found.append({"text": m.group(), "type": "时间节点", "subtype": label,
                      "start": m.start(), "end": m.end(), "canonical": m.group(),
                      "in_scenic": True})
    return found


# 复合词守卫：这些词后接特定后缀时是另一个词的一部分（步行街/火车站/高铁站/登山杖），不算实体。
# 具名索道（云谷索道等）不在此列——“云谷索道站”仍指向该索道，保留。
WORD_GUARDS = {
    "步行": ("街",), "登山": ("杖",),
    "火车": ("站", "北站", "南站", "东站", "西站", "总站"),
    "高铁": ("站", "北站", "南站", "东站", "西站"),
    "大巴": ("站", "总站"), "公交": ("站", "总站"), "班车": ("站",),
    "索道": ("站",), "缆车": ("站",),
    "地铁": ("站", "口"), "登山": ("杖", "鞋", "口", "服", "包", "靴"),
}


class DictMatcher:
    """自定义词典最长匹配：长词优先、位置互斥、停用词守卫、复合词守卫。

    find(text, scenic=...) 传入记录主景区时，为每个 POI 命中计算 in_scenic 标记。
    """

    def __init__(self, entries: list[dict], stopwords: set[str]):
        self.by_name: dict[str, dict] = {}
        for e in entries:
            self.by_name[e["name"]] = e
        # 长词优先，保证“西海大峡谷”不会被“西海”抢先
        self.names = sorted(self.by_name, key=len, reverse=True)
        self.pattern = re.compile("|".join(re.escape(n) for n in self.names))
        self.stopwords = stopwords

    def find(self, text: str, scenic: str | None = None) -> list[dict]:
        found = []
        taken: set[int] = set()
        for m in self.pattern.finditer(text):
            name = m.group()
            # 停用词守卫：若某停用词包含该词且从同一位置开始（如“北海”⊂“北海公园”），丢弃
            if any(sw.startswith(name) and text[m.start():m.start() + len(sw)] == sw
                   for sw in self.stopwords):
                continue
            if any(text[m.end():m.end() + len(g)] == g for g in WORD_GUARDS.get(name, ())):
                continue
            if any(p in taken for p in range(m.start(), m.end())):
                continue
            entry = self.by_name[name]
            taken.update(range(m.start(), m.end()))
            # 在景标记：POI 是否属于当前记录的主景区（多景点游记的归属判据，供下游过滤）
            in_scenic = scenic is None or scenic in entry.get("scenic_areas", ["通用"])
            found.append({"text": name, "type": entry["entity_type"], "subtype": entry["subtype"],
                          "start": m.start(), "end": m.end(), "canonical": entry["canonical"],
                          "in_scenic": in_scenic})
        return found


def load_dictionary(iteration: str) -> tuple[list[dict], set[str], bool]:
    if iteration == "refined":
        d = json.loads((OUT / "entity_dictionary.json").read_text(encoding="utf-8"))
        return d["poi"] + d["transport"], set(d["domain_stopwords"]), True
    # baseline：只含采集阶段的景区 POI 种子与通用交通词，代表“未经语料挖掘整理”的初始词典
    sys.path.insert(0, str(TASK1 / "src"))
    from expand_ctrip import NODES
    entries = [{"name": poi, "entity_type": "景点POI", "subtype": "景点",
                "scenic_areas": [area], "canonical": poi, "source": "seed"}
               for area, pois in NODES.items() for poi in pois]
    basic_transport = ["观光车", "大巴", "索道", "缆车", "步行", "徒步", "高铁", "飞机",
                       "公交车", "地铁", "游船", "电瓶车", "摆渡车", "环保车", "自驾"]
    entries += [{"name": t, "entity_type": "交通方式", "subtype": "通用", "scenic_areas": ["通用"],
                 "canonical": t, "source": "basic"} for t in basic_transport]
    return entries, set(), False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", choices=["baseline", "refined"], required=True)
    args = parser.parse_args()

    entries, stopwords, use_userdict = load_dictionary(args.iteration)
    if use_userdict:
        jieba.load_userdict(str(OUT / "entity_userdict.txt"))
        jieba.setLogLevel(60)

    matcher = DictMatcher(entries, stopwords)
    rows = [json.loads(line) for line in (TASK1 / "data/processed/dataset_clean.jsonl").open(encoding="utf-8")]

    out_path = OUT / f"entities_{args.iteration}.jsonl"
    type_scenic = defaultdict(Counter)
    subtype_counter = Counter()
    canonical_freq: dict[str, Counter] = defaultdict(Counter)
    per_record_counts = []
    segmentation_tokens = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            text = row["clean_content"]
            # jieba 分词证据（词典词已通过 load_userdict 保证成词；分词结果用于统计与实验3参考）
            toks = [t for t in jieba.cut(text) if t.strip()]
            segmentation_tokens += len(toks)
            ents = matcher.find(text, scenic=row["scenic_area"]) + time_entities(text)
            ents.sort(key=lambda e: (e["start"], e["end"]))
            for e in ents:
                type_scenic[row["scenic_area"]][e["type"]] += 1
                subtype_counter[f'{e["type"]}/{e["subtype"]}'] += 1
                canonical_freq[e["type"]][e["canonical"]] += 1
            rec = {
                "record_id": row["record_id"], "scenic_area": row["scenic_area"],
                "source_platform": row["source_platform"], "text_type": row["text_type"],
                "clean_char_count": row["clean_char_count"], "entities": ents,
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            per_record_counts.append(len(ents))

    stats = {
        "iteration": args.iteration,
        "dictionary_size": {"poi": sum(1 for e in entries if e["entity_type"] == "景点POI"),
                            "transport": sum(1 for e in entries if e["entity_type"] == "交通方式"),
                            "stopwords": len(stopwords)},
        "records": len(rows),
        "total_entities": sum(per_record_counts),
        "entities_per_record_mean": round(sum(per_record_counts) / len(rows), 2),
        "segmentation_tokens_total": segmentation_tokens,
        "by_scenic_area": {k: dict(v) for k, v in type_scenic.items()},
        "by_subtype": dict(subtype_counter),
        "top_canonical": {t: dict(c.most_common(40)) for t, c in canonical_freq.items()},
    }
    (OUT / f"entity_stats_{args.iteration}.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: stats[k] for k in ("iteration", "total_entities", "entities_per_record_mean")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
