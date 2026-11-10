"""Check completion status of each stage so run_collection.ps1 can decide whether to skip.

Completion is judged from the data itself, not from extra state files; it is
recomputed before every run, so deleted or corrupted data is never mistaken
for completed.

Usage: python src/stage_status.py [per-platform count]
"""
from __future__ import annotations
import importlib.util, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREAS = ('黄山', '九寨沟', '颐和园')
STATE = ROOT / 'data/crawl/stage_state.json'


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text('utf-8').splitlines() if line.strip()]


def official_status():
    docs = read_jsonl(ROOT / 'data/raw/official_documents.jsonl')
    accepted = [d for d in docs if d.get('accepted')]
    return {
        'done': bool(docs) and len(accepted) == len(docs),
        'documents': len(docs),
        'accepted': len(accepted),
        'detail': f'{len(accepted)}/{len(docs)} 篇',
    }


def platform_status(module, func_name, per_platform):
    try:
        rows, _audit = getattr(module, func_name)()
    except Exception as exc:
        return {'done': False, 'error': str(exc)[:200], 'areas': {}}
    areas = {}
    for area in AREAS:
        count = sum(1 for r in rows if r.get('scenic_area') == area)
        areas[area] = {'eligible': count, 'target': per_platform, 'done': count >= per_platform}
    detail = ' '.join(f"{a}{v['eligible']}" for a, v in areas.items())
    total = sum(v['eligible'] for v in areas.values())
    return {'done': all(v['done'] for v in areas.values()), 'areas': areas,
            'total': total, 'detail': detail}


def main():
    per_platform = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    select = _load('select_collection', 'src/select_collection.py')
    status = {
        'official': official_status(),
        'ctrip': platform_status(select, 'ctrip_candidates', per_platform),
        'xiaohongshu': platform_status(select, 'xhs_candidates', per_platform),
        'per_platform': per_platform,
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(status, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
