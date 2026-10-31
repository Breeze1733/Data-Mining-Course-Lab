"""Offline final review of the expansion snapshots and author diversity.

Never changes sources.json. All excluded articles and snapshots stay in the
data/crawl ledger; the output manifest contains accepted independent authors.
"""
import collections
import hashlib
import json
import re
from pathlib import Path
from lxml import html
import expand_ctrip as expansion

ROOT=Path(__file__).resolve().parents[1]
CRAWL=ROOT/'data/crawl'

MANUAL_REJECT={
 'CTRIP_4100903':'原文自称“开局一张图，内容全靠编”，不作为实游证据',
 'CTRIP_4011981':'主要内容为北海雲亼管家接待与酒店体验，推广倾向明显',
 'CTRIP_3961636':'标题和主要内容为北海雲亼酒店体验推广，排除以保持游客实游口径',
}

def score(r):
 return min(r.get('poi_count',0),20)/20+min(r.get('route_paragraph_count',0),10)/10+min(r.get('route_density',0),1)*0.8

def run():
 path=CRAWL/'ctrip_expansion.json'
 old=json.loads(path.read_text('utf-8'))
 records=[]
 for r in old:
  raw=r.get('raw_file')
  if raw and (ROOT/raw).exists():
   n=expansion.verify_one(r)
   n['collected_at']=r['collected_at']
   n['reviewed_at']=expansion.stamp()
  else:n=r
  if n['record_id'] in MANUAL_REJECT:
   n['accepted']=False;n.setdefault('rejection_reasons',[]).append('manual_promotional_or_fiction_exclusion');n['manual_review_note']=MANUAL_REJECT[n['record_id']]
  n['accepted_before_author_dedup']=bool(n.get('accepted'))
  records.append(n)
 discoveries=json.loads((CRAWL/'ctrip_expansion_discovery.json').read_text('utf-8'))['candidates']
 author_lookup={expansion.article_id(r['url']):r['author'] for r in discoveries if r.get('author')}
 for r in records:
  if not r.get('author'):r['author']=author_lookup.get(expansion.article_id(r['url']),'')
 sources=json.loads((ROOT/'sources.json').read_text('utf-8'))
 existing_authors=set()
 seed_hashes={}
 lookup=[]
 for s in sources:
  if re.search(r'/travels/.*/\d+\.html',s.get('source_url','')):
   ident=expansion.article_id(s['source_url']);author=s.get('author_hint') or author_lookup.get(ident,'')
   lookup.append({'record_id':s['record_id'],'source_url':s['source_url'],'author':author,'basis':'public_directory_display' if author else 'not_verified'})
   if author:existing_authors.add((s['scenic_area'],author))
   raw=s.get('raw_file')
   if raw and (ROOT/raw).exists():
    paras,_=expansion.body_parts(html.fromstring((ROOT/raw).read_bytes()))
    if paras:seed_hashes[(s['scenic_area'],hashlib.sha256('\n'.join(paras).encode()).hexdigest())]=s['record_id']
 groups=collections.defaultdict(list)
 for r in records:
  if not r.get('accepted'):continue
  seedkey=(r['scenic_area'],r.get('body_text_sha256',''))
  if seedkey in seed_hashes:
   r['accepted']=False;r['rejection_reasons'].append('same_body_as_seed_record');r['duplicate_of']=seed_hashes[seedkey];continue
  if r.get('author'):
   key=(r['scenic_area'],r['author'])
   if key in existing_authors:
    r['accepted']=False;r['rejection_reasons'].append('same_author_as_seed_record');continue
   groups[key].append(r)
 for key,group in groups.items():
  if len(group)<2:continue
  winner=max(group,key=score)
  for r in group:
   if r is not winner:
    r['accepted']=False;r['rejection_reasons'].append('same_author_keep_richer_route');r['richer_route_record_id']=winner['record_id']
 seen={}
 for r in sorted(records,key=score,reverse=True):
  if not r.get('accepted') or not r.get('body_text_sha256'):continue
  key=(r['scenic_area'],r['body_text_sha256'])
  if key in seen:
   r['accepted']=False;r['rejection_reasons'].append('duplicate_article_body');r['duplicate_of']=seen[key]
  else:seen[key]=r['record_id']
 expansion.save(path,records)
 expansion.save(CRAWL/'ctrip_expansion_sources.json',expansion.manifest(records))
 expansion.save(CRAWL/'ctrip_author_lookup.json',lookup)
 summary={
  'reviewed_at':expansion.stamp(),
  'directory_pages_observed':53,
  'directory_links_observed':len(discoveries),
  'articles_verified':len(records),
  'readable':sum(r.get('body_readable',False) for r in records),
  'accepted_before_author_dedup':dict(collections.Counter(r['scenic_area'] for r in records if r.get('accepted_before_author_dedup'))),
  'accepted_final':dict(collections.Counter(r['scenic_area'] for r in records if r.get('accepted'))),
  'rejection_reasons':dict(collections.Counter(reason for r in records if not r.get('accepted') for reason in r.get('rejection_reasons',[]))),
  'author_policy':'每景区对公开目录显示的同作者保留路线较丰富的一篇；与既有种子作者相同的扩展篇不重复纳入。公开HTML未展示的作者保持空值。',
 }
 expansion.save(CRAWL/'ctrip_expansion_summary.json',summary)
 print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':run()
