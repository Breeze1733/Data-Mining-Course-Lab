# -*- coding: utf-8 -*-
"""B03 词典扩充（2026-11-05）：实体句级评测（B01）漏检驱动的补录。

依据：B01 原始句子级实体评测（task2/output/exp2/entity_sentence_eval.json）的漏检清单，
逐条核对其**全语料出现频次**（≥2 视为有证据的真实专名/交通/时段表达，非评测样本特例）。

内容：
  1. POI 景区内遗漏：庐山/三清山（联游名山）、黄山南大门/白云宾馆（黄山入口与山上住宿）、
     后湖/慈福牌楼/新宫门（颐和园遗漏）；歙县/徽州（黄山周边人文地名）；
  2. POI 周边地标：敦煌/麦积山/莫高窟/鸣沙山/嘉峪关关城（河西走廊联游线）、横断山（地理专名）、
     九黄机场/成都东/成都东站/天府机场/虹桥火车站（交通设施）、归云山房（黄山周边民宿）、
     国子监街/五道营胡同/北锣鼓巷/恭王府博物馆（北京周边）；
  3. 交通：坐车（156 次，泛交通表达）、顺风车（5 次）；
  4. 时间规则：黄金周/周末（时段词）、（乾隆|康熙|雍正|光绪|宣统|明清)年间（纪年时段）、
     独立年份（19|20)\\d{2}年（低优先级，此前 2022年 等裸年份漏检）。

幂等：重复运行不产生重复条目。城市名（北京/成都）按设计不作为 POI 实体（泛地名），
根景区名（黄山/九寨沟/颐和园）按设计排除，均以评测报告双口径记录。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "resources/domain_seed.json"
TIMERULES = ROOT / "resources/time_rules.json"

SOURCE = "b03_recall_eval_2026-11-05"

# (name, canonical, scenic_areas, rationale) —— scenic_areas=[] 表示周边地标
POI_ADDITIONS = [
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

# (id, subtype, priority, regex, rationale)
TIME_ADDITIONS = [
    ("TIME_HOLIDAY_WEEK", "时段", 60, "黄金周|周末",
     "假期时段词，语料分别为5/43次"),
    ("TIME_DYNASTY_NIANJIAN", "时段", 59, "(乾隆|康熙|雍正|光绪|宣统|明清)年间",
     "纪年时段（乾隆年间等），语料15次"),
    ("TIME_YEAR_BARE", "年份", 40, "(?:(?:19|20)\\d{2})年",
     "独立年份（低优先级，日期区间规则优先），此前 2022年 等裸年份漏检"),
]


def main() -> int:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    poi_names = {e["name"] for e in seed["poi"]}
    tr_names = {e["name"] for e in seed["transport"]}
    added_poi, added_tr = 0, 0
    for name, canonical, areas, rationale in POI_ADDITIONS:
        if name in poi_names:
            continue
        seed["poi"].append({"name": name, "entity_type": "景点POI", "subtype": "景点",
                            "scenic_areas": areas, "canonical": canonical, "source": SOURCE})
        poi_names.add(name)
        added_poi += 1
    for name, canonical, subtype, rationale in TRANSPORT_ADDITIONS:
        if name in tr_names:
            continue
        seed["transport"].append({"name": name, "entity_type": "交通方式", "subtype": subtype,
                                  "scenic_areas": ["通用"], "canonical": canonical, "source": SOURCE})
        tr_names.add(name)
        added_tr += 1
    seed["meta"]["b03_expansion"] = {"date": "2026-11-05", "added_poi": added_poi,
                                     "added_transport": added_tr,
                                     "basis": "B01 句级实体评测漏检清单 + 全语料频次≥2 证据"}
    SEED.write_text(json.dumps(seed, ensure_ascii=False, indent=1), encoding="utf-8")

    trule = json.loads(TIMERULES.read_text(encoding="utf-8"))
    ids = {p["id"] for p in trule["patterns"]}
    added_time = 0
    for pid, subtype, priority, regex, rationale in TIME_ADDITIONS:
        if pid in ids:
            continue
        trule["patterns"].append({"id": pid, "subtype": subtype, "priority": priority,
                                  "regex": regex, "rationale": rationale,
                                  "counts_as_time_node": True, "source": SOURCE})
        ids.add(pid)
        added_time += 1
    TIMERULES.write_text(json.dumps(trule, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"added_poi": added_poi, "added_transport": added_tr, "added_time_rules": added_time},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
