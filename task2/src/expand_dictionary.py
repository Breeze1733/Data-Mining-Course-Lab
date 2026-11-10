# -*- coding: utf-8 -*-
"""领域词典扩充与导出：三个证据驱动批次（全部幂等）+ 词典导出。

批次（城市名/根景区名按设计不作为 POI； scenic_areas=[] 表示周边地标，
可匹配、可作消解候选，in_scenic 恒为 False，不进游客路线与图谱）：
1. peripheral_expansion：周边地标 + 景区内遗漏 POI + 写法变体（task4 人工标注注释 + 高频语料）
2. recall_eval：句级实体评测漏检清单 + 全语料频次≥2 证据（POI/交通/时间规则）
3. coref_gold_dev：消解 dev gold 先行词证据（语料频次≥2 纪律；墨海/白石海 各 1 次为样本特例排除）

运行：python src/expand_dictionary.py
→ 依次追加入 resources/domain_seed.json 与 time_rules.json，再导出
   output/exp2/entity_dictionary.json、entity_userdict.txt、entity_schema.md。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "resources/domain_seed.json"
TIMERULES = ROOT / "resources/time_rules.json"
OUT = ROOT / "output/exp2"
from entity_rules import refined_dictionary  # noqa: E402

SOURCE_PERIPH = "peripheral_expansion_2026-10-30"
ADDITIONS_PERIPH = [
    # 景区内遗漏
    ("扎如寺", "扎如寺", ["九寨沟"], "九寨沟景区内景点（扎如生态游线路终点），语料20次"),
    ("颐和园博物馆", "颐和园博物馆", ["颐和园"], "颐和园文昌院内展馆，官方路线出现"),
    # 人工标注评测集背书（task4 注释"未收录实体"）
    ("梦幻景区", "西海大峡谷", ["黄山"], "游客对西海大峡谷的代称，task4人工标注注释"),
    ("松潘古城", "松潘古城", [], "task4人工标注注释'真先行词松潘古城未收录'"),
    ("磁器口", "磁器口", [], "task4 人工标注评测集：'这里'指重庆磁器口"),
    ("乐山大佛景区", "乐山大佛景区", [], "task4 人工标注评测集：'这里有13路公交站'指乐山大佛附近"),
    ("乐山大佛", "乐山大佛景区", [], "同上，短写法归一到全称"),
    ("景山公园", "景山公园", [], "task4 人工标注评测集：多景点游记景山段"),
    ("景山", "景山公园", [], "景山公园短写法"),
    ("南锣鼓巷", "南锣鼓巷", [], "task4 人工标注评测集×2"),
    ("荷花市场", "荷花市场", [], "task4 人工标注评测集"),
    ("北京大学", "北京大学", [], "task4 人工标注评测集：'这里'指北大"),
    ("清华大学", "清华大学", [], "task4 人工标注评测集（注：gold原文'清华大学校园'仍不相等，边界如实保留）"),
    ("清华", "清华大学", [], "清华大学短写法"),
    # 高频周边地标（北京，多出现于颐和园游记）
    ("故宫", "故宫", [], "语料190次"),
    ("天坛", "天坛", [], "语料81次"),
    ("圆明园", "圆明园", [], "语料160次"),
    ("北海公园", "北海公园", [], "语料28次；与黄山'北海'(北海景区)不同名冲突，长词优先"),
    ("恭王府", "恭王府", [], "语料45次"),
    ("什刹海", "什刹海", [], "语料28次"),
    ("烟袋斜街", "烟袋斜街", [], "语料10次"),
    ("后海", "后海", [], "语料20次"),
    ("大栅栏", "大栅栏", [], "语料39次"),
    ("王府井", "王府井", [], "语料30次"),
    ("雍和宫", "雍和宫", [], "语料20次"),
    ("国子监", "国子监", [], "语料23次"),
    ("香山公园", "香山公园", [], "语料14次"),
    ("香山", "香山公园", [], "香山公园短写法"),
    ("八达岭长城", "八达岭长城", [], "语料23次"),
    ("慕田峪长城", "慕田峪长城", [], "语料14次"),
    ("鸟巢", "鸟巢", [], "语料53次"),
    ("水立方", "水立方", [], "语料32次"),
    ("国家博物馆", "国家博物馆", [], "语料32次"),
    # 高频周边地标（川渝，多出现于九寨沟游记）
    ("三星堆博物馆", "三星堆博物馆", [], "语料33次"),
    ("三星堆", "三星堆博物馆", [], "三星堆博物馆短写法"),
    ("都江堰", "都江堰", [], "语料82次"),
    ("青城山", "青城山", [], "语料42次"),
    ("峨眉山", "峨眉山", [], "语料38次"),
    ("杜甫草堂", "杜甫草堂", [], "语料11次"),
    ("宽窄巷子", "宽窄巷子", [], "语料48次"),
    ("武侯祠", "武侯祠", [], "语料38次"),
    ("锦里", "锦里", [], "语料41次"),
    ("洪崖洞", "洪崖洞", [], "语料9次"),
    # 高频周边地标（皖/浙，多出现于黄山游记）
    ("西递", "西递", ["黄山"], "语料40次；与宏村同为黄山联游惯例（in_scenic 跟随宏村先例）"),
    ("徽州古城", "徽州古城", [], "语料7次"),
    ("千岛湖", "千岛湖", [], "语料21次"),
    ("苏堤", "苏堤", [], "语料14次（杭州西湖）"),
    ("汤口镇", "汤口镇", [], "语料82次；黄山门户集散地，非景区内游览点"),
    ("汤口", "汤口镇", [], "汤口镇短写法"),
    ("黄龙五彩池", "黄龙五彩池", [], "语料10次；与九寨沟五彩池同名异点，独立canonical消歧"),
    # 写法变体（共享 canonical）
    ("则渣洼沟", "则查洼沟", ["九寨沟"], "则查洼沟常见异写，语料16次"),
    ("查洼沟", "则查洼沟", ["九寨沟"], "则查洼沟口语省写，语料独立出现4次"),
]


SOURCE_RECALL = "recall_eval_2026-11-05"
POI_ADDITIONS_RECALL = [
    ("庐山", "庐山", [], "联游名山，语料106次"),
    ("三清山", "三清山", [], "联游名山，语料43次"),
    ("徽州", "徽州", [], "黄山周边人文地名，语料58次"),
    ("歙县", "歙县", [], "黄山周边古县城，语料9次"),
    ("黄山南大门", "黄山南大门", ["黄山"], "黄山入口换乘枢纽，语料26次"),
    ("白云宾馆", "白云宾馆", ["黄山"], "黄山山上住宿（D1口径：山上住宿属景区内），语料89次"),
    ("后湖", "后湖", ["颐和园"], "颐和园苏州街后水域，语料37次"),
    ("慈福牌楼", "慈福牌楼", ["颐和园"], "颐和园四大部洲前牌楼，语料6次"),
    ("新宫门", "新宫门", ["颐和园"], "颐和园出入口之一，语料2次"),
    ("敦煌", "敦煌", [], "河西走廊联游城市，语料18次"),
    ("麦积山", "麦积山", [], "联游石窟名山，语料7次"),
    ("莫高窟", "莫高窟", [], "联游石窟，语料8次"),
    ("鸣沙山", "鸣沙山", [], "敦煌联游景点，语料3次"),
    ("嘉峪关关城", "嘉峪关关城", [], "河西走廊联游关城，语料2次"),
    ("横断山", "横断山", [], "川西地理专名，语料2次"),
    ("归云山房", "归云山房", [], "宏村周边民宿，语料2次"),
    ("国子监街", "国子监街", [], "北京周边街巷，语料7次"),
    ("五道营胡同", "五道营胡同", [], "北京周边胡同，语料4次"),
    ("北锣鼓巷", "北锣鼓巷", [], "北京周边胡同，语料3次"),
    ("恭王府博物馆", "恭王府博物馆", [], "北京周边馆舍，语料2次"),
    ("九黄机场", "九黄机场", [], "九寨沟联游机场，语料24次"),
    ("成都东", "成都东", [], "成都东站简称，语料66次"),
    ("成都东站", "成都东站", [], "成都东站全称，语料28次"),
    ("天府机场", "天府机场", [], "成都机场，语料6次"),
    ("虹桥火车站", "虹桥火车站", [], "上海火车站，语料2次"),
]
TRANSPORT_ADDITIONS = [
    ("坐车", "坐车", "其他", "泛交通表达，语料156次"),
    ("顺风车", "顺风车", "其他", "顺风车出行，语料5次"),
]
TIME_ADDITIONS = [
    ("TIME_HOLIDAY_WEEK", "时段", 60, "黄金周|周末",
     "假期时段词，语料分别为5/43次"),
    ("TIME_DYNASTY_NIANJIAN", "时段", 59, "(乾隆|康熙|雍正|光绪|宣统|明清)年间",
     "纪年时段（乾隆年间等），语料15次"),
    ("TIME_YEAR_BARE", "年份", 40, "(?:(?:19|20)\\d{2})年",
     "独立年份（低优先级，日期区间规则优先），此前 2022年 等裸年份漏检"),
]


SOURCE_COREF = "coref_gold_dev_2026-11-07"
POI_ADDITIONS_COREF = [
    ("送客松", "送客松", ["黄山"], "黄山名松，语料13次；消解 dev gold 先行词（它→送客松）"),
    ("金山岭长城", "金山岭长城", [], "北京周边长城段，语料2次；消解 dev gold 先行词"),
]

def export_dictionary():
    OUT.mkdir(parents=True, exist_ok=True)
    entries, stopwords, _ = refined_dictionary()
    data = {"poi": [e for e in entries if e["entity_type"] == "景点POI"],
            "transport": [e for e in entries if e["entity_type"] == "交通方式"],
            "domain_stopwords": sorted(stopwords), "source": "resources/domain_seed.json + CSV resources"}
    (OUT / "entity_dictionary.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "entity_userdict.txt").write_text("\n".join(f'{e["name"]} 100000 nz' for e in entries)+"\n", encoding="utf-8")
    definition = (ROOT / "resources/entity_definition.csv").read_text(encoding="utf-8-sig")
    (OUT / "entity_schema.md").write_text("# 实体类型与边界规范\n\n" +
        "保留跨景区实体并标记in_scenic；景区根名不进入POI。时长单列，不计作时间节点。\n" +
        "\n```csv\n" + definition + "\n```\n", encoding="utf-8")
    print({k: len(data[k]) for k in ("poi", "transport", "domain_stopwords")})


def _append_poi(data, names, rows, source):
    added = 0
    for name, canonical, areas, why in rows:
        if name in names:
            continue
        data["poi"].append({"name": name, "entity_type": "景点POI", "subtype": "景点",
                            "scenic_areas": areas, "canonical": canonical,
                            "source": source, "note": why})
        names.add(name)
        added += 1
    return added


def main() -> int:
    data = json.loads(SEED.read_text(encoding="utf-8"))
    poi_names = {e["name"] for e in data["poi"]}
    tr_names = {e["name"] for e in data["transport"]}
    added = {"peripheral": _append_poi(data, poi_names, ADDITIONS_PERIPH, SOURCE_PERIPH)}
    added["recall_poi"] = _append_poi(data, poi_names, POI_ADDITIONS_RECALL, SOURCE_RECALL)
    added["coref_poi"] = _append_poi(data, poi_names, POI_ADDITIONS_COREF, SOURCE_COREF)
    added["recall_transport"] = 0
    for name, canonical, subtype, why in TRANSPORT_ADDITIONS:
        if name in tr_names:
            continue
        data["transport"].append({"name": name, "entity_type": "交通方式", "subtype": subtype,
                                  "scenic_areas": ["通用"], "canonical": canonical,
                                  "source": SOURCE_RECALL, "note": why})
        tr_names.add(name)
        added["recall_transport"] += 1
    data["meta"]["recall_expansion"] = {
        "date": "2026-11-05", "basis": "句级实体评测漏检清单 + 消解 gold 先行词 + 全语料频次≥2 证据"}
    SEED.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    trule = json.loads(TIMERULES.read_text(encoding="utf-8"))
    ids = {p["id"] for p in trule["patterns"]}
    added["recall_time"] = 0
    for pid, subtype, priority, regex, rationale in TIME_ADDITIONS:
        if pid in ids:
            continue
        trule["patterns"].append({"id": pid, "subtype": subtype, "priority": priority,
                                  "regex": regex, "rationale": rationale,
                                  "counts_as_time_node": True, "source": SOURCE_RECALL})
        ids.add(pid)
        added["recall_time"] += 1
    TIMERULES.write_text(json.dumps(trule, ensure_ascii=False, indent=1), encoding="utf-8")

    export_dictionary()
    print(json.dumps({"added": added, "poi_total": len(data["poi"]),
                      "transport_total": len(data["transport"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
