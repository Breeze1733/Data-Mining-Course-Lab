"""Adapt the committed canonical corpus into the configurable source schema.

The 22 official documents stay distinct from their 46 route branches. Analysis
scope uses tourist+official_route; all includes the supporting documents too.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path


def read(path):
    return [json.loads(line) for line in path.open(encoding="utf-8-sig") if line.strip()]


def write(path, records):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--official-routes", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "task1/src"))
    from preprocess_collected import clean_text
    corpus = read(args.dataset)
    tourist, official = [], []
    for row in corpus:
        adapted = {**row, "cleaned_text": row["clean_content"],
                   "text_sha256": hashlib.sha256(row["clean_content"].encode("utf-8")).hexdigest()}
        if row["text_type"] == "travelogue":
            tourist.append(adapted)
        else:
            official.append({**adapted, "evidence_id": row["record_id"], "accepted": True})
    routes = []
    for row in (read(args.official_routes) if args.official_routes and args.official_routes.exists() else []):
        text, _, _ = clean_text(row["raw_content"], row.get("raw_format", "text"))
        routes.append({**row, "cleaned_text": text, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    write(out / "tourist_routes_clean.jsonl", tourist)
    write(out / "official_documents_clean.jsonl", official)
    write(out / "official_routes_clean.jsonl", routes)
    provenance = {"pipeline_version": "canonical-snapshot-1.0", "canonical_records": len(corpus),
                  "source_dataset": str(args.dataset.resolve()),
                  "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
                  "tourist": len(tourist), "official_documents": len(official), "official_routes": len(routes),
                  "note": "官方文档与分支为两个层级；analysis 不含官方文档，避免重复计数。主报告使用 canonical corpus 的逐记录接口。"}
    (out / "quality_report.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(provenance, ensure_ascii=False))


if __name__ == "__main__":
    main()
