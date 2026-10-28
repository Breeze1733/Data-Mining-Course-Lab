"""Discover and verify extra public Ctrip travelogues without bypassing checks.

The directory boundary is the site's observed 15 Huangshan Scenic Area pages
and 38 Jiuzhaigou pages. Beijing is searched using separately verified URLs.
The script never writes sources.json; the reviewer merges the separate manifest.
"""
from __future__ import annotations
import argparse
import hashlib
import html as html_module
import json
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin
from lxml import html

ROOT=Path(__file__).resolve().parents[1]
RESEARCH=ROOT/'research'
PAGES=ROOT/'data/raw/pages'
RESEARCH.mkdir(parents=True,exist_ok=True)
PAGES.mkdir(parents=True,exist_ok=True)
LOCK=threading.Lock()
NEXT_REQUEST=0.0
DIRECTORIES=[('黄山','huangshan19',15),('九寨沟','jiuzhaigou25',38)]
NODES={
 '黄山':['云谷','玉屏','慈光阁','始信峰','光明顶','迎客松','天都峰','莲花峰','鳌鱼峰','排云亭','西海大峡谷','猴子观海','白鹅岭','狮子峰','太平索道','清凉台','丹霞峰','海心亭','北海','飞来石'],
 '九寨沟':['长海','五彩池','五花海','箭竹海','熊猫海','珍珠滩','诺日朗','犀牛海','老虎海','树正','火花海','芦苇海','原始森林','镜海','盆景滩','则查洼','日则沟'],
 '颐和园':['东宫门','北宫门','西门','新建宫门','长廊','昆明湖','万寿山','苏州街','佛香阁','排云殿','十七孔桥','铜牛','石舫','清晏舫','玉澜堂','乐寿堂','仁寿殿','谐趣园','知春亭','西堤','南湖岛','霁清轩','景福阁','四大部洲','邀月门','听鹂馆','文昌阁','文昌院','德和园','画中游','北如意门','智慧海','耶律楚材','德辉殿'],
}
PROMO_TITLE=re.compile(r'酒店|民宿|客栈|美食推荐|行李寄存|旅行险|保险|门票需要|门票预约|门票购买|免票政策|交通管制|高速.{0,10}通车|分享方式|推送规则|补充通知|更新的预告|景点指南|摄影师|藏服照|旅拍|探店|直通车|地陪|导游|旅游规划师|旅游策划师|包车')
PROMO_BODY=re.compile(r'巴士达|速8精选|添加微信|加我微信|微信号|包车电话|联系.{0,8}微信|全程纯玩|私人订制|定制师|旅游顾问|旅游规划师|旅游策划师|地陪导游|VX号|微芯|手机号|咨询.{0,5}电话')
VERB=re.compile(r'路线|线路|行程|游览|游玩|我们|我俩|徒步|步行|乘车|坐车|下车|来到|到达|出发|前往|沿着|经过|接着|之后|返回|[→➠]')
FIRSTHAND=re.compile(r'我(?!国|校|省|市|司|厂|区)|咱们|本人|一家人|全家|闺蜜|带着.{0,5}孩子|带娃')
BEIJING_SEEDS=[
 'https://you.ctrip.com/travels/Beijing1/3996366.html',
 'https://you.ctrip.com/travels/Beijing1/4178417.html',
 'https://you.ctrip.com/travels/Beijing1/4178339.html',
 'https://you.ctrip.com/travels/Beijing1/4178108.html',
 'https://you.ctrip.com/travels/Beijing1/3941039.html',
 'https://you.ctrip.com/travels/beijing1/4082358.html',
 'https://you.ctrip.com/travels/Beijing1/3987192.html',
 'https://you.ctrip.com/travels/beijing1/4011149.html',
 'https://you.ctrip.com/travels/Beijing1/4144300.html',
 'https://you.ctrip.com/travels/beijing1/4100843.html',
 'https://you.ctrip.com/travels/beijing1/3986203.html',
 'https://you.ctrip.com/travels/beijing1/4156664.html',
 'https://you.ctrip.com/travels/beijing1/4090827.html',
 'https://you.ctrip.com/travels/beijing1/1289220.html',
 'https://you.ctrip.com/travels/Beijing1/4024149.html',
 'https://you.ctrip.com/travels/beijing1/4011856.html',
 'https://you.ctrip.com/travels/beijing1/3889684.html',
 'https://you.ctrip.com/travels/beijing1/4132000.html',
 'https://you.ctrip.com/travels/youyouctripstar10000/4040658.html',
 'https://you.ctrip.com/travels/Beijing1/4151641.html',
 'https://you.ctrip.com/travels/beijing1/4131661.html',
 'https://you.ctrip.com/travels/beijing1/1206352.html',
]

def stamp():
 return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')

def save(path,data):
 temp=path.with_suffix(path.suffix+'.tmp')
 temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
 temp.replace(path)

def get(url):
 global NEXT_REQUEST
 with LOCK:
  delay=max(0,NEXT_REQUEST-time.monotonic())
  if delay: time.sleep(delay)
  NEXT_REQUEST=time.monotonic()+1.25
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=35) as response:
  return response.status,response.url,response.read()

def article_id(url):
 return re.search(r'/(\d+)\.html',url)[1]

def discover_job(job):
 scenic,slug,page=job
 url=f'https://you.ctrip.com/travels/{slug}/t2-p{page}'
 log={'kind':'directory','scenic_area':scenic,'page':page,'url':url,'time':stamp()}
 try:
  status,final,raw=get(url); d=html.fromstring(raw)
  title=''.join(d.xpath('//title/text()'))
  if '验证' in title:raise ValueError('verification page; no bypass attempted')
  out=[]
  for a in d.xpath('//a[contains(@href,"/travels/") and contains(@href,".html")]'):
   link=urljoin('https://you.ctrip.com',a.get('href')).replace('http://','https://')
   if not re.search(r'/\d+\.html',link):continue
   heading=''.join(a.xpath('.//h2//text()')).strip()
   if not heading:continue
   text=''.join(a.itertext()).strip()
   before=text.split('发表于',1)[0]
   author=before[len(heading):].strip() if before.startswith(heading) else ''
   if len(author)>50:author=''
   summary=' '.join(a.xpath('.//p//text()')).strip()
   date=re.search(r'发表于\s*(\d{4}-\d{2}-\d{2})',text)
   rec={'scenic_area':scenic,'title':heading,'url':link,'author':author,'summary':summary,'directory_url':url,'published_at':date[1] if date else ''}
   if PROMO_TITLE.search(heading):rec['directory_rejection']='promotional_or_non_travelogue_title'
   elif scenic=='黄山' and not re.search(r'黄山|迎客松|北海|玉屏|西海|始信|天都|莲花|光明顶',heading):rec['directory_rejection']='title_not_target_scenic_area'
   elif scenic=='九寨沟' and not re.search(r'九寨|九黄|四川|巴蜀|阿坝|川西|成都|甘南|川北|黄龙',heading):rec['directory_rejection']='title_not_target_scenic_area'
   out.append(rec)
  log.update(http_status=status,article_links=len(out),accepted=True)
  return out,log
 except Exception as exc:
  log.update(accepted=False,error=str(exc));return [],log

def body_parts(d):
 nodes=d.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," travel-content-wrapper ")]')
 selector='travel-content-wrapper'
 if not nodes:
  nodes=d.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," rich-text-container ")]')
  selector='rich-text-container div.content | h5.menu'
 if not nodes:return [],selector
 container=nodes[0]
 if selector.startswith('rich'):
  children=container.xpath('.//div[contains(concat(" ",normalize-space(@class)," ")," content ")] | .//h5[contains(concat(" ",normalize-space(@class)," ")," menu ")]')
  if children:return [html_module.unescape(''.join(x.itertext())).strip() for x in children if ''.join(x.itertext()).strip()],selector
 parts=[html_module.unescape(''.join(x.itertext())).strip() for x in container.xpath('.//p | .//h5')]
 parts=[p for p in parts if p]
 if parts:return parts,selector
 # Some pre-2010 articles put text and inline POI anchors directly in the
 # wrapper, without any p element. Join source line wrapping before splitting.
 text=html_module.unescape(''.join(container.itertext())).strip()
 text=re.sub(r'\s*\n\s*','',text)
 return [p for p in re.split(r'(?<=[。！？；])',text) if p.strip()],selector+'; legacy direct text sentences'

def verify_one(meta,refresh=False):
 rec=dict(meta);scenic=rec['scenic_area'];ident=article_id(rec['url'])
 rec.update(record_id=f'CTRIP_{ident}',source_platform='携程游记',text_type='travelogue',collected_at=stamp())
 try:
  path=PAGES/f'CTRIP_{ident}.html'
  if path.exists() and not refresh:raw=path.read_bytes();status='cached_snapshot';final=rec['url']
  else:
   status,final,raw=get(rec['url'])
   path.write_bytes(raw)
  rec.update(http_status=status,raw_file=f'data/raw/pages/CTRIP_{ident}.html',snapshot_sha256=hashlib.sha256(raw).hexdigest())
  d=html.fromstring(raw)
  fulltitle=''.join(d.xpath('//title/text()'))
  if '验证' in fulltitle:raise ValueError('verification page; no bypass attempted')
  title=''.join(d.xpath('//h1//text()')).strip()
  if title:rec['title']=title
  paras,selector=body_parts(d)
  text='\n'.join(paras)
  rec.update(body_readable=bool(paras),extraction_selector=selector,text_length=len(text))
  if not paras:raise ValueError('no recognizable article body')
  dates=d.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," travel-date ")]//text()')
  for v in dates:
   dt=re.search(r'20\d\d[.\-/]\d{1,2}[.\-/]\d{1,2}',v)
   if dt:rec['published_at']=dt[0].replace('.','-').replace('/','-');break
  pois=[poi for poi in NODES[scenic] if poi in text]
  local=[p for p in paras if any(poi in p for poi in NODES[scenic]) and VERB.search(p)]
  ordered=[p for p in local if sum(poi in p for poi in NODES[scenic])>=2 or re.search(r'[→➠]|路线|线路|接着|之后|然后|返回|前往|经过|沿着',p)]
  adverts=sorted(set(m[0] for m in PROMO_BODY.finditer(text)))
  rec.update(poi_count=len(pois),matched_pois=pois,route_paragraph_count=len(ordered),route_evidence=[p[:1200] for p in ordered[:12]],advertising_signals=adverts,firsthand_signal=bool(FIRSTHAND.search(text) or re.search(r'游记|纪行|纪实|游纪|刚回|亲测',rec['title'])),body_text_sha256=hashlib.sha256(text.encode()).hexdigest())
  rec['route_density']=round(sum(len(p) for p in ordered)/max(1,len(text)),4)
  reasons=[]
  if PROMO_TITLE.search(rec['title']):reasons.append('promotional_title')
  if len(pois)<3:reasons.append('fewer_than_3_target_POIs')
  if not ordered:reasons.append('no_clear_target_route_paragraph')
  if not rec['firsthand_signal']:reasons.append('no_firsthand_travel_signal')
  if adverts:reasons.append('promotional_body_signals')
  if re.search(r'内容全靠编|故事纯属虚构|行程纯属虚构',text):reasons.append('declared_fiction_or_fabrication')
  if len(text)<80:reasons.append('body_too_short')
  rec['quality_flags']=['short_but_route_bearing'] if len(text)<180 else []
  rec['accepted']=not reasons
  rec['rejection_reasons']=reasons
  rec['author_verification']='directory_display' if rec.get('author') else 'not_exposed_in_current_public_HTML'
 except Exception as exc:
  rec.update(accepted=False,error=str(exc),rejection_reasons=['fetch_or_extraction_failed'])
 return rec

def manifest(records):
 return [dict(record_id=r['record_id'],scenic_area=r['scenic_area'],source_platform='携程游记',source_url=r['url'],text_type='travelogue',extractor='ctrip',raw_file=r['raw_file'],published_at=r.get('published_at',''),date_note='平台显示日期，可能为更新日期',content_scope='article_body',selection_note=f"扩展目录筛选；目标POI {r['poi_count']}，路线段落 {r['route_paragraph_count']}，正文需复核",collected_at=r['collected_at'],expected_title=r['title'],author_hint=r.get('author','')) for r in records if r.get('accepted')]

def run(skip_discovery=False):
 logpath=RESEARCH/'ctrip_expansion_discovery.json'
 resultpath=RESEARCH/'ctrip_expansion.json'
 manifestpath=RESEARCH/'ctrip_expansion_sources.json'
 previous=json.loads(resultpath.read_text('utf-8')) if resultpath.exists() else []
 records={r['url']:r for r in previous}
 discovered=[];logs=[]
 if skip_discovery and logpath.exists():
  old=json.loads(logpath.read_text('utf-8'));discovered=old['candidates'];logs=old['requests']
 else:
  jobs=[(spot,slug,p) for spot,slug,total in DIRECTORIES for p in range(1,total+1)]
  with ThreadPoolExecutor(max_workers=2) as pool:
   for fut in as_completed([pool.submit(discover_job,j) for j in jobs]):
    found,log=fut.result();discovered.extend(found);logs.append(log)
    save(logpath,{'scope':'黄山景区公开最新目录1至15页；九寨沟公开最新目录1至38页；颐和园聚焦搜索URL，不代表全站穷尽','candidates':discovered,'requests':logs,'complete':False})
    print('DIRECTORY',log['scenic_area'],log['page'],log.get('article_links',0),log.get('error',''),flush=True)
  save(logpath,{'scope':'黄山景区公开最新目录1至15页；九寨沟公开最新目录1至38页；颐和园聚焦搜索URL，不代表全站穷尽','candidates':discovered,'requests':logs,'complete':True})
 existing=json.loads((ROOT/'sources.json').read_text('utf-8')) if (ROOT/'sources.json').exists() else []
 oldids={article_id(s['source_url']) for s in existing if '/travels/' in s.get('source_url','') and re.search(r'/\d+\.html',s['source_url'])}
 unique={article_id(r['url']):r for r in discovered if not r.get('directory_rejection') and article_id(r['url']) not in oldids}
 for url in BEIJING_SEEDS:
  if article_id(url) not in oldids:unique[article_id(url)]={'scenic_area':'颐和园','url':url,'title':'','author':'','summary':'聚焦搜索候选'}
 jobs=[r for r in unique.values() if r['url'] not in records]
 print('VERIFY_JOBS',len(jobs),flush=True)
 with ThreadPoolExecutor(max_workers=2) as pool:
  for fut in as_completed([pool.submit(verify_one,r) for r in jobs]):
   r=fut.result();records[r['url']]=r
   save(resultpath,list(records.values()));save(manifestpath,manifest(list(records.values())))
   print('ARTICLE',r['scenic_area'],r['record_id'],r.get('accepted'),r.get('text_length',0),r.get('poi_count',0),r.get('route_paragraph_count',0),r.get('title','')[:50],r.get('rejection_reasons'),flush=True)
 print('COMPLETE',len(records),'accepted',sum(r.get('accepted',False) for r in records.values()),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--skip-discovery',action='store_true');args=parser.parse_args();run(args.skip_discovery)
