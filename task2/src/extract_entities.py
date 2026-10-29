"""实验2唯一实体识别器。默认读取实验1主语料，结果供实验3至7使用。

baseline和refined是同一识别器的词典迭代参数，不是两套实现。
"""
from __future__ import annotations
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
import jieba
from entity_rules import DictMatcher, time_entities, refined_dictionary, resolve_record_entities

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/exp2"
TASK1 = ROOT.parent / "task1"


def load_dictionary(iteration: str):
    if iteration == "refined":
        return refined_dictionary()
    if iteration != "baseline":
        raise ValueError(f"未知迭代: {iteration}")
    sys.path.insert(0, str(TASK1 / "src"))
    from expand_ctrip import NODES
    entries = [{"name": poi, "entity_type": "景点POI", "subtype": "景点",
                "scenic_areas": [area], "canonical": poi, "source": "seed"}
               for area, pois in NODES.items() for poi in pois]
    basic = ["观光车", "大巴", "索道", "缆车", "步行", "徒步", "高铁", "飞机",
             "公交车", "地铁", "游船", "电瓶车", "摆渡车", "环保车", "自驾"]
    entries += [{"name": word, "entity_type": "交通方式", "subtype": "通用",
                 "scenic_areas": ["通用"], "canonical": word, "source": "basic"} for word in basic]
    return entries, set(), False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", choices=["baseline", "refined"], default="refined")
    parser.add_argument("--input", type=Path, default=TASK1 / "data/processed/dataset_clean.jsonl")
    parser.add_argument("--output-dir", type=Path, default=OUT)
    args = parser.parse_args(argv)
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    entries, stopwords, use_userdict = load_dictionary(args.iteration)
    if use_userdict:
        jieba.load_userdict(str(OUT / "entity_userdict.txt"))
        jieba.setLogLevel(60)

    matcher = DictMatcher(entries, stopwords)
    with args.input.open(encoding="utf-8") as source:
        rows = [json.loads(line) for line in source if line.strip()]

    if not rows:
        raise ValueError("输入数据集为空")
    out_path = out / f"entities_{args.iteration}.jsonl"
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
            ents = resolve_record_entities(matcher.find(text, scenic=row["scenic_area"]) + time_entities(text))
            assert all(text[e["start"]:e["end"]] == e["text"] for e in ents)
            ents.sort(key=lambda e: (e["start"], e["end"]))
            assert all(a["end"] <= b["start"] for a, b in zip(ents, ents[1:]))
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
    (out / f"entity_stats_{args.iteration}.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: stats[k] for k in ("iteration", "total_entities", "entities_per_record_mean")},
                     ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
