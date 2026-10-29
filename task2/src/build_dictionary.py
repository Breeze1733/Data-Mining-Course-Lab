"""导出实体识别使用的领域词典。"""
import json
from pathlib import Path
from entity_rules import refined_dictionary
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/exp2"

def main():
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

if __name__ == "__main__":
    main()
