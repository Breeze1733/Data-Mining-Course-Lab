"""实验4：代词检测 + 基于规则的指代消解。

检测：按标点分句，识别 它/它们/这里/那里/那边/此处/他们/她们/其中/这条/这座/该景点 等代词，
记录文档级偏移、句内偏移、所在句、候选实体（同句在前、前句、前两句窗口内的 POI/交通实体）。
消解（规则法）：
  - 处所类（这里/那里/那边/此处）与物体类（它/它们/这条/这座/该景点）：
    候选 = 同句代词前最近 POI > 同句最近交通实体 > 前句最近 POI > 前两句窗口最近 POI > 景区名 > NONE；
  - 人称类（他们/她们）：游记一手文本默认指“作者及同行者”（travel_party），正文含明确他人（挑夫/工作人员等）线索时标注 other_person；
  - 集合类（其中）：指代前文紧邻的 POI 集合（preceding_set）。
同句多个相同代词按字符偏移各自处理，不会错配。
输出：output/pronoun_cases.jsonl（全部检测 + 规则消解结果）
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK1 = ROOT.parent / "task1"
TASK2 = ROOT.parent / "task2"
OUT = ROOT / "output"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PRONOUN_RE = re.compile(r"它们?|他们|她们|这里|那里|那边|此处|其中|该景点|这座|这条")
SENT_SPLIT = re.compile(r"[。！？；!?\n]+")
PERSON_HINT_RE = re.compile(
    r"挑夫|挑山工|工作人员|司机|导游|老板|店员|大叔|阿姨|小哥|师傅|保安|检票员|服务员|主人|大爷|大妈|"
    r"游客|前台|讲解员|店主|姑娘|小伙子|教练|医生|护士")

# 代词语义类别 → 消解策略
PRONOUN_CLASS = {
    "这里": "locative", "那里": "locative", "那边": "locative", "此处": "locative",
    "它": "object", "它们": "object",
    "这条": "object", "这座": "object", "该景点": "object",
    "他们": "person", "她们": "person",
    "其中": "set",
}


def split_sentences(text: str) -> list[tuple[int, int, str]]:
    sents = []
    start = 0
    for m in SENT_SPLIT.finditer(text):
        if m.start() > start:
            sents.append((start, m.start(), text[start:m.start()]))
        start = m.end()
    if start < len(text):
        sents.append((start, len(text), text[start:]))
    return [(s, e, t) for s, e, t in sents if t.strip()]


def main() -> int:
    import jieba  # noqa: F401  （词典加载依赖 jieba 初始化）

    sys.path.insert(0, str(TASK2 / "src"))
    from extract_entities import DictMatcher, load_dictionary
    from entity_rules import contextual_facility_places

    entries, stopwords, _ = load_dictionary("refined")
    matcher = DictMatcher(entries, stopwords)

    rows = [json.loads(l) for l in (TASK1 / "data/processed/dataset_clean.jsonl").open(encoding="utf-8")]
    ents = {json.loads(l)["record_id"]: json.loads(l) for l in
            (TASK2 / "output/exp2/entities_refined.jsonl").open(encoding="utf-8")}

    n_cases = 0
    out_path = OUT / "pronoun_cases.jsonl"
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            if row["text_type"] != "travelogue":
                continue
            text = row["clean_content"]
            rec_ents = ents.get(row["record_id"], {}).get("entities", [])
            pois = [e for e in rec_ents if e["type"] == "景点POI" and e["subtype"] == "景点"]
            pois += contextual_facility_places(text, row["scenic_area"])
            pois.sort(key=lambda e: (e["start"], e["end"]))
            transports = [e for e in rec_ents if e["type"] == "交通方式"]
            scenic_area = row["scenic_area"]

            sentences = split_sentences(text)
            sent_index_of_pron = []
            for si, (ss, se, stext) in enumerate(sentences):
                for m in PRONOUN_RE.finditer(stext):
                    sent_index_of_pron.append((si, ss + m.start(), ss + m.end(), m.group()))

            for si, doc_start, doc_end, pron in sent_index_of_pron:
                cls = PRONOUN_CLASS[pron]
                case = {
                    "record_id": row["record_id"], "scenic_area": scenic_area,
                    "source_platform": row["source_platform"],
                    "pronoun": pron, "pronoun_class": cls,
                    "doc_start": doc_start, "doc_end": doc_end,
                    "sentence_id": si,
                    "sentence": sentences[si][2],
                    "prev_sentence": sentences[si - 1][2] if si >= 1 else "",
                    "prev2_sentence": sentences[si - 2][2] if si >= 2 else "",
                }
                if cls in ("locative", "object"):
                    # 候选打分：同句在前 > 前句 > 前两句；POI 优先于交通；距离近优先
                    cands = []

                    def add_pool(pool, scope, is_prev):
                        before = [e for e in pool if e["end"] <= doc_start]
                        if is_prev:
                            before = pool  # 前句实体全部视为“在前”
                        for e in reversed(before[-6:]):
                            cands.append({
                                "kind": "POI" if e["type"] == "景点POI" else "交通",
                                "name": e["canonical"], "scope": scope,
                                "distance": doc_start - e["end"],
                            })

                    cur_sent_start, cur_sent_end = sentences[si][0], sentences[si][1]
                    add_pool([e for e in pois + transports
                              if cur_sent_start <= e["start"] < cur_sent_end], "同句", False)
                    if si >= 1:
                        add_pool([e for e in pois + transports
                                  if sentences[si - 1][0] <= e["start"] < sentences[si - 1][1]], "前句", True)
                    if si >= 2:
                        add_pool([e for e in pois
                                  if sentences[si - 2][0] <= e["start"] < sentences[si - 2][1]], "前两句", True)
                    if not cands:
                        case.update({"resolution": scenic_area, "resolution_kind": "景区名",
                                     "evidence": "窗口内无实体，回退到景区名"})
                    else:
                        cands.sort(key=lambda c: (0 if c["kind"] == "POI" else 1,
                                                  {"同句": 0, "前句": 1, "前两句": 2}[c["scope"]],
                                                  c["distance"]))
                        best = cands[0]
                        case.update({"resolution": best["name"], "resolution_kind": best["kind"],
                                     "evidence": f'{best["scope"]}最近{best["kind"]}，距离{best["distance"]}字符'})
                    case["candidates"] = cands[:6]
                elif cls == "person":
                    window = case["sentence"] + case["prev_sentence"]
                    party_signal = re.search(r"我们|我俩|咱们|我妈|我爸|媳妇|闺女|老婆|老公|女儿|儿子|同伴|闺蜜|一家人|同行", window)
                    if PERSON_HINT_RE.search(case["sentence"]) and not party_signal:
                        case.update({"resolution": "other_person", "resolution_kind": "他人",
                                     "evidence": "句中含他人角色词且无同行者信号"})
                    elif not party_signal and PERSON_HINT_RE.search(case["prev_sentence"]):
                        case.update({"resolution": "other_person", "resolution_kind": "他人",
                                     "evidence": "前句含他人角色词且本窗口无同行者信号"})
                    else:
                        case.update({"resolution": "travel_party", "resolution_kind": "同行者",
                                     "evidence": "一手游记默认指作者及同行者"})
                else:  # set：“其中”的先行词多为普通名词集合，用 jieba 词性找最近名词
                    import jieba.posseg as pseg
                    cur_sent_start = sentences[si][0]
                    noun = None
                    for text_before in (case["sentence"][: doc_start - cur_sent_start],
                                        case["prev_sentence"]):
                        if not text_before:
                            continue
                        words = [w for w, f in pseg.cut(text_before) if f.startswith("n") and len(w) >= 2]
                        if words:
                            noun = words[-1]
                            break
                    if noun:
                        case.update({"resolution": f"noun:{noun}", "resolution_kind": "名词集合",
                                     "evidence": f"最近的普通名词“{noun}”（jieba 词性）"})
                    else:
                        case.update({"resolution": "NONE", "resolution_kind": "无明确先行词",
                                     "evidence": "窗口内无 POI 也无普通名词"})
                fh.write(json.dumps(case, ensure_ascii=False) + "\n")
                n_cases += 1

    from collections import Counter
    stats = Counter()
    with out_path.open(encoding="utf-8") as fh:
        for line in fh:
            c = json.loads(line)
            stats[(c["pronoun_class"], c["resolution_kind"])] += 1
    print(json.dumps({"total_cases": n_cases,
                      "by_class_kind": {f"{a}/{b}": v for (a, b), v in sorted(stats.items())}},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
