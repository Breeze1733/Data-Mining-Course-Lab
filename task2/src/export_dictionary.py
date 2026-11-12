"""Export the final entity dictionary and jieba user dictionary."""

import json
from pathlib import Path

from entity_rules import refined_dictionary
from poi_aliases import aliases, build_poi_lookup, canonical_name, normalization_rules

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/exp2"


def export_dictionary():
    OUT.mkdir(parents=True, exist_ok=True)
    entries, stopwords, _ = refined_dictionary()
    poi = [e for e in entries if e["entity_type"] == "景点POI"]
    lookup = build_poi_lookup(poi)
    data = {"poi": poi,
            "transport": [e for e in entries if e["entity_type"] == "交通方式"],
            "domain_stopwords": sorted(stopwords), "source": "resources/domain_seed.json + CSV resources",
            # Data contract for downstream tasks: no cross-folder code imports.
            "aliases": [{"area": area, "alias": alias, "canonical": canonical_name(alias, area)}
                        for area, alias in sorted(aliases())],
            "poi_lookup": [{"scenic_area": area, "variant": variant, "canonical": canonical}
                           for (area, variant), canonical in sorted(lookup.items())],
            "normalization": normalization_rules()}
    (OUT / "entity_dictionary.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "entity_userdict.txt").write_text("\n".join(f'{e["name"]} 100000 nz' for e in entries)+"\n", encoding="utf-8")
    print({k: len(data[k]) for k in ("poi", "transport", "domain_stopwords")})


if __name__ == "__main__":
    export_dictionary()
