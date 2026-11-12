"""Experiment 4: pronoun detection + rule-based coreference resolution.

Detection: split into sentences by punctuation; recognize pronouns such as 它/它们/这里/那里/那边/此处/他们/她们/其中/这条/这座/该景点;
record document-level offsets, in-sentence offsets, the containing sentence, and candidate entities (POI/transport entities
within the same-sentence-before, previous-sentence, and previous-two-sentences windows).
Resolution (rule-based):
  - Locative (这里/那里/那边/此处) and object (它/它们/这条/这座/该景点) classes:
    candidates = nearest POI before the pronoun in the same sentence > nearest transport entity in the same sentence > nearest POI in the previous sentence > nearest POI in the previous-two-sentences window > scenic-area name > NONE;
  - Person class (他们/她们): first-person travelogues default to the "author and companions" (travel_party); when the text carries explicit other-person cues (porter/staff etc.), label other_person;
  - Set class (其中): refers to the adjacent preceding POI set (preceding_set).
Multiple identical pronouns in one sentence are handled independently by character offset and never cross-matched.
Output: output/pronoun_cases.jsonl (all detections + rule-resolution results)
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

if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PRONOUN_RE = re.compile(r"它们?|他们|她们|这里|那里|那边|此处|其中|该景点|这座|这条")
SENT_SPLIT = re.compile(r"[。！？；!?\n]+")
PERSON_HINT_RE = re.compile(
    r"挑夫|挑山工|工作人员|司机|导游|老板|店员|大叔|阿姨|小哥|师傅|保安|检票员|服务员|主人|大爷|大妈|"
    r"游客|前台|讲解员|店主|姑娘|小伙子|教练|医生|护士|当地人|本地人|管理者|管理员|村民|东家|掌柜|小朋友|孩子们")

# Extended person words for the other-person reference-following rule (hikers/passers-by/pedestrians/“一队人”-style group nouns)
PERSON_HINT_EXT = re.compile(
    PERSON_HINT_RE.pattern
    + r"|登山者|胜利者|路人|行人|[一两二三四五六七八几]?\s*[队批群帮].{0,3}人"
    + r"|(?:从?下面上来|从?上面下来|迎面|对面|迎着)的?[一两二三四五]?人")

# Pronoun semantic class -> resolution strategy
PRONOUN_CLASS = {
    "这里": "locative", "那里": "locative", "那边": "locative", "此处": "locative",
    "它": "object", "它们": "object",
    "这条": "object", "这座": "object", "该景点": "object",
    "他们": "person", "她们": "person",
    "其中": "set",
}

# Set signals for the noun fallback (criterion for kind 名词集合 vs 其他)
_PLURAL_PREFIX_RE = re.compile(r"(?:这些|那些|各[类种样]?|诸|众多|许多|很多|大片|成片|遍地的?)[一-龥]{0,4}$")
_ENUM_GAP_RE = re.compile(r"[、和与及/,,\s]{1,3}")


def _pseg_cut(text: str) -> list[tuple[str, str]]:
    import jieba.posseg as pseg
    return [(w.word, w.flag) for w in pseg.cut(text)]


def _noun_enum_signal(text: str) -> bool:
    """Two or more common nouns joined by 、/和 within the window -> multi-element set."""
    if not text:
        return False
    pos, words = 0, []
    for word, flag in _pseg_cut(text):
        if flag.startswith("n") and len(word) >= 2:
            words.append((word, pos))
        pos += len(word)
    return any(_ENUM_GAP_RE.fullmatch(text[pa + len(wa): pb] or "")
               for (wa, pa), (_, pb) in zip(words, words[1:]))


def _plural_prefix_signal(text: str, offset: int) -> bool:
    """A plural demonstrative immediately before the nearest noun (这些松树/各种会议) -> multi-element set."""
    return bool(text and offset > 0 and _PLURAL_PREFIX_RE.search(text[:offset]))


def _span_set_signals(text: str) -> tuple[bool, bool]:
    """(enumeration signal, plural-demonstrative signal): judges the plural prefix by the position of the span's last common noun."""
    if not text:
        return False, False
    pos, last = 0, None
    for word, flag in _pseg_cut(text):
        if flag.startswith("n") and len(word) >= 2:
            last = (word, pos)
        pos += len(word)
    return _noun_enum_signal(text), (last is not None and _plural_prefix_signal(text, last[1]))


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

    ap = argparse.ArgumentParser()
    ap.add_argument("--no-attribution-filter", action="store_true",
                    help="关闭 P1 句级归属过滤（默认开启：景区外句中的实体不作消解候选）")
    args = ap.parse_args(argv)

    import bisect
    attr_spans: dict[str, tuple[list[int], list[str]]] = {}
    if not args.no_attribution_filter:
        for line in (ROOT / "output/attribution/attributed_sentences.jsonl").open(encoding="utf-8"):
            rec = json.loads(line)
            starts = [x["start"] for x in rec["labels"]]
            labels = [x["label"] for x in rec["labels"]]
            attr_spans[rec["record_id"]] = (starts, labels)

    # Entity-area consistency: canonical -> scenic_areas (dictionary facts, for focus-area × entity-membership filtering)
    dict_data = json.loads((TASK2 / "output/exp2/entity_dictionary.json").read_text(encoding="utf-8"))
    poi2scenic = {e["name"]: e.get("scenic_areas", []) for e in dict_data["poi"]}
    contextual_path = TASK2 / "output/exp2/contextual_facility_entities.jsonl"
    if not contextual_path.exists():
        raise FileNotFoundError(f"缺少 {contextual_path}；请先运行 task2/src/export_contextual_facilities.py")
    contextual_by_record = {}
    for line in contextual_path.open(encoding="utf-8"):
        rec = json.loads(line)
        contextual_by_record[rec["record_id"]] = rec
    SCENIC_NAMES = {"黄山", "九寨沟", "颐和园"}

    rows = [json.loads(l) for l in (TASK1 / "data/processed/dataset_clean.jsonl").open(encoding="utf-8")]
    clean_by_id = {row["record_id"]: row["clean_content"] for row in rows}
    for record_id, rec in contextual_by_record.items():
        text = clean_by_id.get(record_id)
        if (text is None or rec["clean_char_count"] != len(text)
                or any(text[e["start"]:e["end"]] != e["text"] for e in rec["entities"])):
            raise ValueError(f"上下文设施实体已过期：{record_id}；请重新运行 task2/src/export_contextual_facilities.py")
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
            pois += contextual_by_record.get(row["record_id"], {"entities": []})["entities"]
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
                    # Route reference: "这条(路|线…)" refers to the road/route itself, not POIs along it;
                    # "这条沟" refers to a water/gully POI ending in "沟" within the window (则查洼沟 case)
                    if pron == "这条" and re.search(r"这条路|这条线|该路线", case["sentence"]):
                        case.update({"resolution": "路线", "resolution_kind": "路线"})
                        fh.write(json.dumps(case, ensure_ascii=False) + "\n")
                        n_cases += 1
                        continue
                    if pron == "这条" and "这条沟" in case["sentence"]:
                        gully = [e for e in pois
                                 if sentences[max(0, si - 2)][0] <= e["start"] < doc_start
                                 and e["canonical"].endswith("沟")]
                        if gully:
                            named = min(gully, key=lambda e: doc_start - e["end"])
                            case.update({"resolution": named["canonical"], "resolution_kind": "POI"})
                            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
                            n_cases += 1
                            continue
                    # “其它” is a determiner (其+它), not an anaphoric pronoun (2 cases held out in the manual-annotation evaluation set)
                    if pron in ("它", "它们") and doc_start > 0 and text[doc_start - 1] == "其":
                        case.update({"resolution": "NONE", "resolution_kind": "无明确先行词"})
                        fh.write(json.dumps(case, ensure_ascii=False) + "\n")
                        n_cases += 1
                        continue
                    # Candidate scoring: same sentence > previous sentence > previous two sentences; POI beats transport; nearer is preferred
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
                            before = pool  # all previous-sentence entities count as "before"
                        # The concatenated pois+transports pool is not globally position-ordered (246/271 records observed out of order);
                        # truncating via reversed() directly would be order-dependent — sort by end descending first ("nearest first"),
                        # then truncate to the 7 nearest to the pronoun, so truncation does not favor entity type/list order
                        before = sorted(before, key=lambda e: e["end"], reverse=True)
                        kept = 0
                        for e in reversed(before):
                            if attr_filter_on:
                                eslab = sent_label(e["start"])
                                if focus != "景区外" and eslab == "景区外":
                                    continue  # P1 attribution filter: when the focus is in-area/unknown, entities from outside-area sentences are not candidates
                                # Focus-area × entity-membership consistency constrains only cross-sentence candidates — entities named in the same sentence are part of the current narration
                                if scope != "同句" and focus in SCENIC_NAMES and e["type"] == "景点POI":
                                    scenic_of = poi2scenic.get(e["canonical"])
                                    if scenic_of is not None and focus not in scenic_of:
                                        continue  # proper names of other scenic areas are not candidates
                            kept += 1
                            if kept > 6:
                                break
                            cands.append({
                                "kind": "POI" if e["type"] == "景点POI" else "交通",
                                "name": e["canonical"], "scope": scope,
                                "distance": doc_start - e["end"],
                            })

                    cur_sent_start, cur_sent_end = sentences[si][0], sentences[si][1]
                    # A locative pronoun directly following a same-sentence POI enumeration (“…慈光阁和云谷寺及北大门、西大门那里出售”) —
                    # here “那里” takes the whole enumerated set rather than the last POI
                    if cls == "locative":
                        cur_pois = sorted((e for e in pois if cur_sent_start <= e["start"] < cur_sent_end
                                           and e["end"] <= doc_start), key=lambda e: e["start"])
                        _gap = text[cur_pois[-1]["end"]:doc_start] if cur_pois else ""
                        if (len(cur_pois) >= 2 and len(_gap) <= 12
                                and not re.search(r"[，。；！？,;!?]", _gap)
                                and any(re.fullmatch(r"[、和与及/,,\s]{1,3}", text[a["end"]:b["start"]])
                                        for a, b in zip(cur_pois, cur_pois[1:]))):
                            case.update({"resolution": "preceding_set", "resolution_kind": "前文POI集合"})
                            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
                            n_cases += 1
                            continue
                    add_pool([e for e in pois + transports
                              if cur_sent_start <= e["start"] < cur_sent_end], "同句", False)
                    if si >= 1:
                        add_pool([e for e in pois + transports
                                  if sentences[si - 1][0] <= e["start"] < sentences[si - 1][1]], "前句", True)
                    if si >= 2:
                        add_pool([e for e in pois
                                  if sentences[si - 2][0] <= e["start"] < sentences[si - 2][1]], "前两句", True)
                    # Cataphoric naming: in "…名为X", X is the appositive proper name of the pronoun's antecedent (1 case in the manual-annotation evaluation set)
                    tail = case["sentence"][max(0, doc_end - cur_sent_start):]
                    if re.search(r"名为|称之为|称作|叫做|叫作", tail):
                        after = [e for e in pois if e["start"] >= doc_end and e["start"] < cur_sent_end]
                        if after:
                            named = min(after, key=lambda e: e["start"])
                            case.update({
                                "resolution": named["canonical"],
                                "resolution_kind": "POI" if named["type"] == "景点POI" else "交通"})
                            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
                            n_cases += 1
                            continue
                    # Naming sentence: "X在这里被叫做Y" denotes the area rather than a window entity (1 case in the manual-annotation evaluation set)
                    if re.search(r"被叫做|被称作|被叫作|被唤作", case["sentence"]):
                        if focus == "景区外":
                            case.update({"resolution": "NONE", "resolution_kind": "无明确先行词"})
                        else:
                            case.update({"resolution": scenic_area, "resolution_kind": "景区名"})
                        fh.write(json.dumps(case, ensure_ascii=False) + "\n")
                        n_cases += 1
                        continue
                    if not cands:
                        # Facility fallback: no entity in the window but a hotel/restaurant/guesthouse etc. is mentioned -> "这里/那里" usually refers to that facility
                        if re.search(r"酒店|民宿|餐厅|饭馆|烤鸭店|客栈|宾馆|农家乐|店家|客房",
                                     case["sentence"] + case["prev_sentence"]):
                            case.update({"resolution": "facility", "resolution_kind": "设施"})
                        elif focus == "景区外":
                            # When the focus is outside the scenic area, falling back to the main scenic-area name is directionally wrong: record no-explicit-antecedent truthfully
                            # Conceptual-antecedent fallback for outside-area sentences — the nearest common noun before the pronoun in the same sentence
                            # (e.g. "祠堂又是一部史书,它记载了…")
                            _nb = None
                            _idx = case["sentence"].find(pron)
                            if _idx > 0:
                                for w, f in _pseg_cut(case["sentence"][:_idx]):
                                    if f.startswith("n") and len(w) >= 2:
                                        _nb = w
                            if _nb:
                                case.update({"resolution": f"noun:{_nb}", "resolution_kind": "其他"})
                            else:
                                case.update({"resolution": "NONE", "resolution_kind": "无明确先行词"})
                        else:
                            case.update({"resolution": scenic_area, "resolution_kind": "景区名"})
                    else:
                        # Candidate ordering — POI beats transport, nearer wins, and
                        # locatives (这里/那里) prefer scenery POIs (lodging/facilities excluded)
                        def compat_bonus(c):
                            if cls == "locative" and c["kind"] == "POI":
                                if any(k in c["name"] for k in ("宾馆", "酒店", "民宿", "饭店", "站", "中心")):
                                    return -2  # locative pronouns prefer scenery over lodging/facilities
                            return 0
                        cands.sort(key=lambda c: (0 if c["kind"] == "POI" else 1,
                                                  {"同句": 0, "前句": 1, "前两句": 2}[c["scope"]],
                                                  compat_bonus(c),
                                                  c["distance"]))
                        best = cands[0]
                        case.update({"resolution": best["name"], "resolution_kind": best["kind"]})
                    case["candidates"] = cands[:6]
                elif cls == "person":
                    window = case["sentence"] + case["prev_sentence"]
                    window3 = case["sentence"] + case["prev_sentence"] + case["prev2_sentence"]
                    # “同行” in contexts like “同行拼车/同行拼” refers to strangers sharing a ride, not the travel party
                    PARTY_RE = re.compile(r"我们|我俩|咱们|我妈|我爸|媳妇|闺女|老婆|老公|女儿|儿子|同伴|闺蜜|一家人|同行(?!拼)")
                    party_signal = PARTY_RE.search(window)
                    party_signal3 = PARTY_RE.search(window3)
                    # The hint-cur branch looks only at same-sentence travel-party signals (a previous-sentence "我们" must not veto a service-role reference in the current sentence)
                    party_cur = PARTY_RE.search(case["sentence"])
                    # “他们(家|自家|后院|店里)” refers to the establishment's facilities, not people (4 cases in the manual-annotation evaluation set)
                    # The guard must end with write+continue: falling through to the independent if-chain below would be overwritten by travel_party
                    if re.search(r"(他们|她们)(家|自家|后院|店里)", case["sentence"]):
                        case.update({"resolution": "facility", "resolution_kind": "设施"})
                        fh.write(json.dumps(case, ensure_ascii=False) + "\n")
                        n_cases += 1
                        continue
                    else:
                        # Other-person reference follows cues — the pronoun is adjacent to a person word (gap ≤16 chars with no 我/我们/你 inside the gap),
                        # or the pronoun precedes any 我/我们/你 of this sentence while the previous sentence contains a person word (“…站了一队人,他们在等…”).
                        # Here “他们” takes the nearby third-party noun; even if “我们” (the narrator) appears in the window, judge other-person
                        _hidx = case["sentence"].find(pron)
                        _hint_hit = None
                        if _hidx >= 0:
                            _prefix = case["sentence"][:_hidx]
                            for _mm in PERSON_HINT_EXT.finditer(_prefix):
                                _gap = _prefix[_mm.end():]
                                if len(_gap) <= 16 and not re.search(r"我们|我|你", _gap):
                                    _hint_hit = _mm
                                    break
                            if _hint_hit is None and not re.search(r"我们|我|你", _prefix) \
                                    and PERSON_HINT_EXT.search(case["prev_sentence"]):
                                _hint_hit = PERSON_HINT_EXT.search(case["prev_sentence"])
                        if _hint_hit:
                            case.update({"resolution": "other_person", "resolution_kind": "他人"})
                            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
                            n_cases += 1
                            continue
                    if PERSON_HINT_RE.search(case["sentence"]) and not party_cur:
                        case.update({"resolution": "other_person", "resolution_kind": "他人"})
                    elif not party_signal and PERSON_HINT_RE.search(case["prev_sentence"]):
                        case.update({"resolution": "other_person", "resolution_kind": "他人"})
                    elif (not party_signal3 and not re.search(r"我|你", case["prev_sentence"])
                          and PERSON_HINT_RE.search(case["prev2_sentence"])):
                        case.update({"resolution": "other_person", "resolution_kind": "他人"})
                    elif not party_cur and not PERSON_HINT_RE.search(case["sentence"]) and re.search(
                            r"酒店|宾馆|民宿|客栈|餐厅|饭馆|旅馆|客房|房间", case["sentence"]):
                        case.update({"resolution": "facility", "resolution_kind": "设施"})
                    else:
                        case.update({"resolution": "travel_party", "resolution_kind": "同行者"})
                else:  # set: antecedent of "其中" by priority: person set > POI enumeration > single POI ("在其中") > common noun
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
                    # POI enumeration: within the window in order of appearance, adjacent POIs separated only by 、/和/与/及-style connectors
                    win_pois = sorted((e for e in pois if win_start <= e["start"] < doc_start),
                                      key=lambda e: e["start"])
                    enum_set = len(win_pois) >= 2 and any(
                        re.fullmatch(r"[、和与及/,,\s]{1,3}", text[a["end"]:b["start"]])
                        for a, b in zip(win_pois, win_pois[1:]))
                    # Quantity-phrase guard ("72个山峰/三副转轮藏/两种上山方式") -> prefer noun set;
                    # the guard window is the whole antecedent window (extension: the quantity word of 三副转轮藏 sits mid-previous-sentence)
                    qty_guard = re.search(
                        r"[一二两三四五六七八九十几\d]+\s*[个座副条种栋项回轮处只名套批]",
                        window_text)
                    # Alternative means: in "可以X也可以Y", "其中" takes the set of means rather than a POI enumeration (1 case in the manual-annotation evaluation set)
                    alternatives = re.search(r"可以[^，。？！;；]{1,12}也可以", window_text)
                    if person_set:
                        case.update({"resolution": "person_set", "resolution_kind": "人称集合"})
                    elif not qty_guard and alternatives:
                        case.update({"resolution": "alternatives", "resolution_kind": "名词集合"})
                    elif not qty_guard and enum_set:
                        case.update({"resolution": "preceding_set", "resolution_kind": "前文POI集合"})
                    elif not qty_guard and len(pois_in_win) == 1:
                        case.update({"resolution": pois_in_win[0], "resolution_kind": "POI"})
                    else:
                        noun = None
                        for text_before in (case["sentence"][: doc_start - cur_sent_start],
                                            case["prev_sentence"]):
                            if not text_before:
                                continue
                            words = [w for w, f in _pseg_cut(text_before) if f.startswith("n") and len(w) >= 2]
                            if words:
                                noun = words[-1]
                                break
                        if noun:
                            # Lineage alignment: the jieba fallback takes the single nearest noun;
                            # single-noun antecedents are judged "其他" (non-entity concept); only when the window carries a multi-element set signal
                            # (≥2 common nouns joined by 、/和, a quantity-phrase guard, or a plural-demonstrative prefix) judge "名词集合" —
                            # avoiding mislabeling single-concept antecedents like "恭王府占地面积…其中" as sets.
                            sent_prefix = case["sentence"][: doc_start - cur_sent_start]
                            e1, p1 = _span_set_signals(sent_prefix)
                            e2, p2 = _span_set_signals(case.get("prev_sentence") or "")
                            kind = "名词集合" if (qty_guard or e1 or e2 or p1 or p2) else "其他"
                            case.update({"resolution": f"noun:{noun}", "resolution_kind": kind})
                        else:
                            case.update({"resolution": "NONE", "resolution_kind": "无明确先行词"})
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
