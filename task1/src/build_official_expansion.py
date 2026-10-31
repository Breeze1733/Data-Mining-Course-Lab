"""Reproduce the expanded official-source discovery evidence (read-only HTTP GET).

Does not modify the main collector, dataset, report, or source manifest.
"""
from __future__ import annotations
import hashlib, json, re, time, urllib.request, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from lxml import html
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'data' / 'crawl'
PAGES = HERE / 'official_expansion_pages'

class Text(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.out=[]; self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'): self.skip+=1
        if tag in ('p','div','br','h1','h2','h3','h4','h5','li','tr'): self.out.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'): self.skip=max(0,self.skip-1)
        if tag in ('p','div','h1','h2','h3','h4','h5','li','tr'): self.out.append('\n')
    def handle_data(self,data):
        if not self.skip:self.out.append(data)
def text_of(fragment):
    p=Text();p.feed(fragment)
    return '\n'.join(x.strip() for x in ''.join(p.out).splitlines() if x.strip())
def cut(text,start='',end=''):
    if start:
        i=text.find(start)
        if i<0:raise ValueError('missing start marker '+start)
        text=text[i:]
    if end:
        i=text.find(end,len(start))
        if i<0:raise ValueError('missing end marker '+end)
        text=text[:i]
    return text.strip()

def S(id,area,url,title,date,xpath,start='',end='',variants=(),note='',primary=True):
    return dict(evidence_id=id,scenic_area=area,source_url=url,title=title,published_at=date,
        extractor='official_xpath_text_range',xpath=xpath,text_start=start,text_end=end,
        variant_definitions=list(variants),provenance_note=note,include_in_main_dataset=primary)

JIUZHAI_BODY='//*[@itemprop="articleBody"]'
BJ_EDITOR='//div[contains(@class,"TRS_UEDITOR")]'
SOURCES=[
 S('JZG-EXP01','九寨沟','https://www.jiuzhai.com/intelligent-service/way-of-play',
   '游玩方式 一日精华游 二日舒适游 三日多彩游','',
   '//div[starts-with(@id,"imagegrid-") and h2[normalize-space(.)="一日精华游" or normalize-space(.)="二日舒适游" or normalize-space(.)="三日多彩游"]]',
   variants=[('一日精华游','一日精华游','二日舒适游'),('二日舒适游','二日舒适游','三日多彩游'),('三日多彩游','三日多彩游','')],
   note='九寨沟风景名胜区管理局官网；既有一日模块扩充为三种多日方案。同页只有1份文档，不伪装为3个来源。三日方案包含神仙池与九寨沟县城，属景区及周边范围。'),
 S('JZG-EXP02','九寨沟','https://www.jiuzhai.com/news/scenic-news/17-fuwu/5298-2016-09-02-06-05-49',
   '九寨沟景区一日游推荐线路','2016-09-02',JIUZHAI_BODY,
   '九寨沟景区一日游推荐线路','路线图',
   [('2016版一日游','上午：','')],
   '管理局官网历史指南。与现版精华游在徒步连接和途经节点上不同；历史票价及开放安排不纳入路线正文。'),
 S('JZG-EXP03','九寨沟','https://www.jiuzhai.com/news/scenic-news/17-fuwu/5299-2016-09-02-06-08-16',
   '九寨沟景区二日游推荐线路','2016-09-02',JIUZHAI_BODY,
   '九寨沟景区二日游推荐线路','旅游路线图',
   [('2016版二日游','第一天：','')],
   '管理局官网历史指南；第一天日则沟+长海，第二天镜海与树正沟，区别于现版二日先则查洼/树正再日则。'),
 S('JZG-EXP04','九寨沟','https://www.jiuzhai.com/news/scenic-news/17-fuwu/5297-2016-09-02-06-00-58-1',
   '九寨沟景区三日游推荐线路','2016-09-02',JIUZHAI_BODY,
   '九寨沟景区三日游推荐线路','旅游线路图',
   [('2016版三日游','第一天：','')],
   '管理局官网历史指南，三天都在九寨沟沟内，区别于现版含神仙池的三日方案。'),
 S('JZG-EXP05','九寨沟','https://www.jiuzhai.com/news/scenic-news/9013-2023-06-12-08-54-37',
   '九寨沟最新推出两条生态文化体验线路','2023-06-12',JIUZHAI_BODY,
   '今年','为挖掘生态文化价值内涵',
   [('原始森林健康游线路','“原始森林健康游线路”','“树正自然研学游线路”'),('树正自然研学游线路','“树正自然研学游线路”','')],
   '管理局原创发布；两条不同的景区内专题路径；保留1000米/1800米与节点描述，不将后面的健康知识链接当作路线。'),
 S('JZG-EXP06','九寨沟','https://www.jiuzhai.com/news/scenic-news/11323-2026-08-11-02-52-20',
   '天下九寨沟 大美阿坝州 万象自然科学行旅体验官招募','2026-08-11',JIUZHAI_BODY,
   '8月15日','本期主讲人',
   [('万象自然科学行旅 双龙海 芦苇海 盆景滩','本次体验活动','')],
   '管理局官网活动公告；8月15日特定活动、2.2公里约2小时，属于历史活动线路。'),
 S('JZG-SUP01','九寨沟','https://www.jiuzhai.com/tourism-product/ecology',
   '生态之旅 扎如沟生态游与原始森林生态游','',
   '//div[contains(@class,"g-blockcontent-header") and h2[normalize-space(.)="扎如沟生态游" or normalize-space(.)="原始森林生态游"]]',
   variants=[('扎如沟生态游','扎如沟生态游','原始森林生态游'),('原始森林生态游','原始森林生态游','')],
   note='官方主题指南，提及4天朝圣/3天科考/1天漫游但未给各自具体节点，不能拆成3条精确路线；仅补充语料，不计入有序游览路线数。',primary=False),
 S('JZG-SUP02','九寨沟','https://www.jiuzhai.com/tourism-product/discovery-tour',
   '发现之旅 五类季节主题游','',
   '//div[contains(@class,"g-blockcontent-header") and h2]',
   '发现之旅','',
   [('民俗风情游','民俗风情游','五、六月'),('温馨银发游','温馨银发游','七、八、九月'),('避暑亲子游','避暑亲子游','十、十一月'),('浪漫彩林游','浪漫彩林游','十二、一、二月'),('蓝冰童话游','蓝冰童话游','')],
   '官方季节主题方案，无固定节点顺序；仅补充语料，不计入有序路线数。',False),
 S('YHY-EXP01','颐和园','https://gygl.beijing.gov.cn/xxgk/xxgk_gyxx/202507/t20250725_4158254.html',
   '北京市属公园暑期红色游 颐和园','2025-07-25',
   '//div[contains(@class,"TRS_UEDITOR")]//p[starts-with(normalize-space(.),"颐和园西门") or starts-with(normalize-space(.),"颐和园东宫门")]',
   variants=[('颐和园西门红色游','颐和园西门','颐和园东宫门'),('颐和园东宫门红色游','颐和园东宫门','')],
   note='北京市公园管理中心原始官方发布；既有网页拆识2条方案，文档计1份。'),
 S('YHY-EXP02','颐和园','https://gygl.beijing.gov.cn/xxgk/xxgk_gyxx/201912/t20191206_883660.html',
   '市属公园首次推出APEC精品文化之旅 颐和园','2014-12-04',
   '//div[contains(@class,"details_page")]',
   '颐和园：','天坛公园：',
   [('APEC世界文化遗产经典线','颐和园：','')],
   '市公园管理中心原始官方发布，实际日期2014-12-04，URL中的2019不是内容发布日期。'),
 S('YHY-EXP03','颐和园','https://www.bjwmb.gov.cn/yw/10093077.html',
   '颐和园西堤桃花进入观赏期 三条赏花小众线路推荐','2025-03-14',
   '//div[contains(concat(" ",normalize-space(@class)," ")," article-text ")]',
   '颐和园春季赏花','',
   [('玉兰观赏路线','1.玉兰观赏路线','2.后山赏花路线'),('后山赏花路线','2.后山赏花路线','3.耕织图赏花路线'),('耕织图赏花路线','3.耕织图赏花路线','')],
   '首都文明网政府网站转载北京日报客户端，文章明确“颐和园为游客推荐”；属于官方园方推荐经媒体报道。'),
 S('YHY-EXP04','颐和园','https://www.beijing.gov.cn/renwen/zt/jhhszn/shxl/202603/t20260323_4563399.html',
   '品质赏花主题游线路 架着船儿赏桃花','2026-03-20',BJ_EDITOR,
   '线路1 架着船儿赏桃花','线路2 喝着茶饮赏玉兰',
   [('架着船儿赏桃花','线路1 架着船儿赏桃花','')],
   '北京市政府站，来源北京市文化和旅游局，含完整精简箭头线路。正文实际日期2026-03-20，URL为03-23。'),
 S('YHY-EXP05','颐和园','https://gygl.beijing.gov.cn/xxgk/xxgk_gyxx/202604/t20260403_4574682.html',
   '清明假期不扎堆 反向遛弯指南 颐和园','2026-04-03',BJ_EDITOR,
   '颐和园','02',
   [('2026清明反向遛弯路线','颐和园','')],
   '北京市公园管理中心官方发布，按第一站至第五站组织景点与茶咖休憩。'),
 S('YHY-EXP06','颐和园','https://www.beijing.gov.cn/renwen/rwzyd/xltj/202603/t20260316_4558171.html',
   '北京公园的花开了 六条路线中的耕织图谐趣园寻梅探春线','2026-03-16',
   '//div[contains(@class,"TRS_UEDITOR")]//p[contains(.,"■颐和园")]',
   variants=[('耕织图谐趣园寻梅探春线','■颐和园','')],
   note='北京市政府转载北京日报，明确为市公园管理中心推荐。短主题线路但有明确景区内两个点位，不补造中间连接点。'),
 S('YHY-EXP07','颐和园','https://www.beijing.gov.cn/fwcj/calendar/yyhd/68d5f9e7da495a1c2b9c577b.html',
   '颐和秋韵 桂香满园 2025北京桂花文化节','',
   '//div[contains(@class,"activity-details")]',
   '观赏指南：','特别提示：',
   [('2025金秋赏桂推荐路线','推荐路线：','')],
   '北京市政府活动页面，来源颐和园，活动2025-09-23至10-12；未见独立发布日期，不用活动开始时间冒充发布日期。'),
 S('YHY-EXP08','颐和园','https://www.beijing.gov.cn/ywdt/gzdt/202510/t20251004_4215781.html',
   '16条错峰游路线 颐和园南如意门至北如意门','2025-10-04',
   '//div[contains(@class,"TRS_UEDITOR")]//p[contains(.,"在颐和园，官方推荐")]',
   variants=[('2025国庆错峰路线','在颐和园','')],
   note='北京市政府转载北京日报，明确官方推荐；与2025红色西门线入口、南岸经过路径均有区别。'),
 S('YHY-EXP09','颐和园','https://news.bjd.com.cn/2026/03/23/11646602.shtml',
   '最新春花实况 此时颐和园西堤美如画','2026-03-23',
   '//div[contains(concat(" ",normalize-space(@class)," ")," article-content ")]',
   '推荐赏花路线','春日里',
   [('2026西堤省力赏花线','①','②'),('2026东西环线后湖赏花线','②','③'),('2026经典西南线赏花线','③','')],
   '北京日报页面，页尾来源为北京海淀，属于海淀官方发布经媒体转载，保留来源链；共有3条不同方案。'),
 S('YHY-EXP10','颐和园','https://summerpalace.net.cn/single/detail/508.html',
   '轮椅服务 两条环形无障碍游览路线','',
   '//div[contains(@class,"details_building1")]//div[@class="text"]',
   '园区内建设了两条环形无障碍游览路线：','',
   [('无障碍环形平缓路线 6962延米','之一起点','之二起点'),('无障碍环形含山体道路路线 2565延米','之二起点','')],
   '颐和园运营方官方网站。未见发布日期应留空。两条环线不同，保留第二条“含山体道路”的原文限定，不能简化为无坡道。www域一次504，规范非www域200。'),
]

def run(offline=False):
    PAGES.mkdir(parents=True,exist_ok=True)
    prior_path=HERE/'official_expansion.json'
    prior={s['evidence_id']:s for s in json.loads(prior_path.read_text('utf-8'))} if prior_path.exists() else {}
    result=[]
    for spec in SOURCES:
        s=dict(spec); definitions=s.pop('variant_definitions')
        try:
            path=PAGES/(s['evidence_id']+'.html')
            if offline:
                data=path.read_bytes();status=prior.get(s['evidence_id'],{}).get('http_status','offline_snapshot')
            else:
                req=urllib.request.Request(s['source_url'],headers={'User-Agent':'Mozilla/5.0'})
                with urllib.request.urlopen(req,timeout=30) as r:
                    data=r.read();status=r.status
                path.write_bytes(data)
            page=data.decode('utf-8',errors='strict');tree=html.fromstring(page)
            ns=tree.xpath(s['xpath'])
            fragment='\n'.join(html.tostring(n,encoding='unicode',with_tail=False) for n in ns)
            text=text_of(fragment)
            s['http_status']=status;s['collected_at']=(prior.get(s['evidence_id'],{}).get('collected_at') or datetime.fromtimestamp(path.stat().st_mtime,ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')) if offline else datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
            s['snapshot_file']=path.relative_to(ROOT).as_posix()
            s['snapshot_sha256']=hashlib.sha256(data).hexdigest()
            s['body_node_count']=len(ns)
            s['page_title']=''.join(tree.xpath('//title/text()')).strip()
            s['body_text']=text
            s['raw_content']=cut(text,s['text_start'],s['text_end'])
            variants=[]
            for title,start,end in definitions:
                variants.append({'title':title,'source_text':cut(s['raw_content'],start,end),
                                 'text_start':start,'text_end':end})
            s['route_variants']=variants
            s['accepted']=bool(s['raw_content']) and all(v['source_text'] for v in variants)
            print('OK',s['evidence_id'],len(s['raw_content']),len(variants),flush=True)
        except Exception as e:
            s['accepted']=False;s['error']=str(e)
            print('FAIL',s['evidence_id'],str(e),flush=True)
        result.append(s)
        if not offline:time.sleep(0.3)
    image_page='https://gygl.beijing.gov.cn/xxgk/xxgk_gyxx/202504/t20250405_4056238.html'
    image_url='https://gygl.beijing.gov.cn/xxgk/xxgk_gyxx/202504/W020250405458451200119.jpg'
    image_path=PAGES/'YHY_QM2025_0.jpg'
    image_id='YHY-EXP11'
    image_text='颐和园\n「西门入园」\n↓\n畅观堂\n【观赏品种】玉兰\n↓\n玉带桥\n【观赏品种】白花山碧桃、“品虹”桃、“品霞”桃\n↓\n耕织图\n【观赏品种】白花山碧桃、连翘\n【时令美食】水村居茶社\n↓\n石舫\n【观赏品种】樱花\n↓\n画中游\n↓\n「北如意门出园」'
    try:
        if not image_path.exists():
            if offline:raise FileNotFoundError('离线快照缺失：'+str(image_path))
            with urllib.request.urlopen(urllib.request.Request(image_url,headers={'User-Agent':'Mozilla/5.0'}),timeout=30) as r:image_path.write_bytes(r.read())
    except Exception as e:
        result.append(dict(evidence_id=image_id,scenic_area='颐和园',source_url=image_page,accepted=False,error=str(e)))
        (HERE/'official_expansion.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('FAIL',image_id,str(e),flush=True)
        return
    image_capture_time=prior.get(image_id,{}).get('collected_at') or datetime.fromtimestamp(image_path.stat().st_mtime,ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
    result.append(dict(evidence_id=image_id,scenic_area='颐和园',source_url=image_page,
        title='清明 游园赏花宝藏路线来啦 颐和园西门至北如意门',published_at='2025-04-03',
        extractor='official_image_visual_transcription',image_url=image_url,
        extraction_selector='正文第一张长图中“颐和园”标题至“北如意门出园”区域，逐字转录路线节点和观赏品种；图示箭头转录为↓',
        provenance_note='北京市公园管理中心，来源畅游公园。下载图片原件并使用代码中预先核对的颐和园路线转录，不执行OCR；不混入下方天坛公园路线。',
        raw_content=image_text,raw_format='text',http_status=200,collected_at=image_capture_time,
        snapshot_file=image_path.relative_to(ROOT).as_posix(),snapshot_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),
        route_variants=[dict(title='2025清明西门入北如意门出赏花线',source_text=image_text)],
        accepted=True,include_in_main_dataset=True))
    (HERE/'official_expansion.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':run('--offline' in sys.argv)
