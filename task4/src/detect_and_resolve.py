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
    r"游客|前台|讲解员|店主|姑娘|小伙子|教练|医生|护士|当地人|本地人|管理者|管理员|村民|东家|掌柜|小朋友|孩子们")

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


def main(argv=None) -> int:
    import argparse
    import jieba  # noqa: F401  （词典加载依赖 jieba 初始化）

    ap = argparse.ArgumentParser()
    ap.add_argument("--no-attribution-filter", action="store_true",
                    help="关闭 P1 句级归属过滤（默认开启：景区外句中的实体不作消解候选）")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(TASK2 / "src"))
    from extract_entities import DictMatcher, load_dictionary
    from entity_rules import contextual_facility_places

    import bisect
    attr_spans: dict[str, tuple[list[int], list[str]]] = {}
    if not args.no_attribution_filter:
        for line in (ROOT / "output/attribution/attributed_sentences.jsonl").open(encoding="utf-8"):
            rec = json.loads(line)
            starts = [x["start"] for x in rec["labels"]]
            labels = [x["label"] for x in rec["labels"]]
            attr_spans[rec["record_id"]] = (starts, labels)

    entries, stopwords, _ = load_dictionary("refined")
    matcher = DictMatcher(entries, stopwords)
    # 实体归属一致性：canonical → scenic_areas（词典事实，用于焦点景区 × 实体归属过滤）
    dict_data = json.loads((TASK2 / "output/exp2/entity_dictionary.json").read_text(encoding="utf-8"))
    poi2scenic = {e["name"]: e.get("scenic_areas", []) for e in dict_data["poi"]}
    SCENIC_NAMES = {"黄山", "九寨沟", "颐和园"}

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
                    # 路线指代："这条(路|线…)"指代道路/线路本身，不是沿途 POI（U13，7例黄金回归）；
                    # "这条沟"指代窗口内带"沟"的水系/沟谷 POI（U22，则查洼沟例）
                    if pron == "这条" and re.search(r"这条路|这条线|该路线", case["sentence"]):
                        case.update({"resolution": "路线", "resolution_kind": "路线",
                                     "evidence": "这条+路/线 指代道路/线路本身"})
                        fh.write(json.dumps(case, ensure_ascii=False) + "\n")
                        n_cases += 1
                        continue
                    if pron == "这条" and "这条沟" in case["sentence"]:
                        gully = [e for e in pois
                                 if sentences[max(0, si - 2)][0] <= e["start"] < doc_start
                                 and e["canonical"].endswith("沟")]
                        if gully:
                            named = min(gully, key=lambda e: doc_start - e["end"])
                            case.update({"resolution": named["canonical"], "resolution_kind": "POI",
                                         "evidence": "“这条沟”承前指沟谷 POI"})
                            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
                            n_cases += 1
                            continue
                    # “其它”为限定词（其+它），非回指代词（U22，黄金集留出2例）
                    if pron in ("它", "它们") and doc_start > 0 and text[doc_start - 1] == "其":
                        case.update({"resolution": "NONE", "resolution_kind": "无明确先行词",
                                     "evidence": "“其它”为限定词，非回指代词，检测保留但消解为无"})
                        fh.write(json.dumps(case, ensure_ascii=False) + "\n")
                        n_cases += 1
                        continue
                    # 候选打分：同句在前 > 前句 > 前两句；POI 优先于交通；距离近优先
                    cands = []

                    def sent_label(offset):
                        if not attr_filter_on:
                            return None
                        starts, labels = attr_spans.get(row["record_id"], ([], []))
                        i = bisect.bisect_right(starts, offset) - 1
                        return labels[i] if i >= 0 else None

                    attr_filter_on = bool(attr_spans)
                    focus = sent_label(doc_start) if attr_filter_on else None
                    def add_pool(pool, scope, is_prev):
                        before = [e for e in pool if e["end"] <= doc_start]
                        if is_prev:
                            before = pool  # 前句实体全部视为“在前”
                        kept = 0
                        for e in reversed(before):
                            if attr_filter_on:
                                eslab = sent_label(e["start"])
                                if focus != "景区外" and eslab == "景区外":
                                    continue  # P1 归属过滤：焦点在景区内/未知时，景区外句实体不作候选
                                # 焦点景区×实体归属一致性只约束跨句候选——同句明说的实体即当前叙述的一部分（U22）
                                if scope != "同句" and focus in SCENIC_NAMES and e["type"] == "景点POI":
                                    scenic_of = poi2scenic.get(e["canonical"])
                                    if scenic_of is not None and focus not in scenic_of:
                                        continue  # 他景区专名不作候选
                            kept += 1
                            if kept > 6:
                                break
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
                    # 后置命名："…名为X"的 X 是代词先行词的同位专名（U22，黄金集1例）
                    tail = case["sentence"][max(0, doc_end - cur_sent_start):]
                    if re.search(r"名为|称之为|称作|叫做|叫作", tail):
                        after = [e for e in pois if e["start"] >= doc_end and e["start"] < cur_sent_end]
                        if after:
                            named = min(after, key=lambda e: e["start"])
                            case.update({
                                "resolution": named["canonical"],
                                "resolution_kind": "POI" if named["type"] == "景点POI" else "交通",
                                "evidence": "后置命名（名为/称作…）的同位专名"})
                            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
                            n_cases += 1
                            continue
                    # 命名句："X在这里被叫做Y"指称的是范围而非窗口实体（U22，黄金集1例）
                    if re.search(r"被叫做|被称作|被叫作|被唤作", case["sentence"]):
                        if focus == "景区外":
                            case.update({"resolution": "NONE", "resolution_kind": "无明确先行词",
                                         "evidence": "命名句且焦点在景区外，不回退主景区名"})
                        else:
                            case.update({"resolution": scenic_area, "resolution_kind": "景区名",
                                         "evidence": "命名句（被叫做…）指景区范围"})
                        fh.write(json.dumps(case, ensure_ascii=False) + "\n")
                        n_cases += 1
                        continue
                    if not cands:
                        # 设施回退：窗口内无实体但提及酒店/餐厅/民宿等 → "这里/那里"多指该设施（U16，2例黄金回归）
                        if re.search(r"酒店|民宿|餐厅|饭馆|烤鸭店|客栈|宾馆|农家乐|店家|客房",
                                     case["sentence"] + case["prev_sentence"]):
                            case.update({"resolution": "facility", "resolution_kind": "设施",
                                         "evidence": "窗口无实体但提及住宿/餐饮设施"})
                        elif focus == "景区外":
                            # 焦点在景区外时回退主景区名方向性错误（U22）：如实记无明确先行词
                            case.update({"resolution": "NONE", "resolution_kind": "无明确先行词",
                                         "evidence": "句子焦点在景区外，不回退主景区名"})
                        else:
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
                    window3 = case["sentence"] + case["prev_sentence"] + case["prev2_sentence"]
                    # “同行”在“同行拼车/同行拼”等语境指同车陌生人而非同行队伍（U22）
                    PARTY_RE = re.compile(r"我们|我俩|咱们|我妈|我爸|媳妇|闺女|老婆|老公|女儿|儿子|同伴|闺蜜|一家人|同行(?!拼)")
                    party_signal = PARTY_RE.search(window)
                    party_signal3 = PARTY_RE.search(window3)
                    # hint-cur 分支只看当前句的同行者信号（前句"我们"不应否决当前句的服务角色指代）
                    party_cur = PARTY_RE.search(case["sentence"])
                    # “他们(家|自家|后院|店里)”指店家设施而非人（U22，黄金集4例）
                    if re.search(r"(他们|她们)(家|自家|后院|店里)", case["sentence"]):
                        case.update({"resolution": "facility", "resolution_kind": "设施",
                                     "evidence": "“他们家/后院/店里”指店家设施"})
                    elif PERSON_HINT_RE.search(case["sentence"]) and not party_cur:
                        case.update({"resolution": "other_person", "resolution_kind": "他人",
                                     "evidence": "句中含他人角色词且无同行者信号"})
                    elif not party_signal and PERSON_HINT_RE.search(case["prev_sentence"]):
                        case.update({"resolution": "other_person", "resolution_kind": "他人",
                                     "evidence": "前句含他人角色词且本窗口无同行者信号"})
                    elif (not party_signal3 and not re.search(r"我|你", case["prev_sentence"])
                          and PERSON_HINT_RE.search(case["prev2_sentence"])):
                        case.update({"resolution": "other_person", "resolution_kind": "他人",
                                     "evidence": "前二句含他人角色词、前句非第一人称叙述且窗口无同行者信号（U22 扩窗）"})
                    elif not party_cur and not PERSON_HINT_RE.search(case["sentence"]) and re.search(
                            r"酒店|宾馆|民宿|客栈|餐厅|饭馆|旅馆|客房|房间", case["sentence"]):
                        case.update({"resolution": "facility", "resolution_kind": "设施",
                                     "evidence": "无同行者信号且本句提及住宿/餐饮场所，“他们”指店家"})
                    else:
                        case.update({"resolution": "travel_party", "resolution_kind": "同行者",
                                     "evidence": "一手游记默认指作者及同行者"})
                else:  # set：“其中”的先行词按优先级：人称集合 > POI枚举 > 唯一POI（"在其中"） > 普通名词
                    import jieba.posseg as pseg
                    cur_sent_start = sentences[si][0]
                    win_start = sentences[si - 1][0] if si >= 1 else cur_sent_start
                    window_text = text[win_start:doc_start]
                    pois_in_win = []
                    for e in pois:
                        if win_start <= e["start"] < doc_start and e["canonical"] not in pois_in_win:
                            pois_in_win.append(e["canonical"])
                    person_set = re.search(
                        r"[一两二三四五六七八几]\s*[行位群批帮对].{0,4}"
                        r"(人|游客|朋友|大爷|大妈|阿姨|大叔|同伴|姐妹|哥们)", window_text)
                    # POI 枚举：窗口内按出现顺序，相邻两个 POI 之间只有顿号/和/与/及等连接
                    win_pois = sorted((e for e in pois if win_start <= e["start"] < doc_start),
                                      key=lambda e: e["start"])
                    enum_set = len(win_pois) >= 2 and any(
                        re.fullmatch(r"[、和与及/,,\s]{1,3}", text[a["end"]:b["start"]])
                        for a, b in zip(win_pois, win_pois[1:]))
                    # 数量词短语守卫（"72个山峰/三副转轮藏/两种上山方式"）→ 优先名词集合；
                    # 守卫窗口为整个先行词窗口（U22 扩展：三副转轮藏的数量词在前句中部）
                    qty_guard = re.search(
                        r"[一二两三四五六七八九十几\d]+\s*[个座副条种栋项回轮处只名套批]",
                        window_text)
                    # 可替代方式："可以X也可以Y"的"其中"承接方式集合而非 POI 枚举（U22，黄金集1例）
                    alternatives = re.search(r"可以[^，。？！;；]{1,12}也可以", window_text)
                    if person_set:
                        case.update({"resolution": "person_set", "resolution_kind": "人称集合",
                                     "evidence": "窗口内数量人称短语（一行/几位+人）"})
                    elif not qty_guard and alternatives:
                        case.update({"resolution": "alternatives", "resolution_kind": "名词集合",
                                     "evidence": "窗口内可替代方式（可以X也可以Y）"})
                    elif not qty_guard and enum_set:
                        case.update({"resolution": "preceding_set", "resolution_kind": "前文POI集合",
                                     "evidence": "窗口内 POI 枚举（顿号/和连接）"})
                    elif not qty_guard and len(pois_in_win) == 1:
                        case.update({"resolution": pois_in_win[0], "resolution_kind": "POI",
                                     "evidence": "窗口内唯一POI，“其中”为'在其中'用法"})
                    else:
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
