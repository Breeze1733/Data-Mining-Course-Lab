/**
 * 小红书可见页面自动采集。只读取搜索卡片和笔记正文，不调用私有API、不导出Cookie。
 * CLI: node src/crawl_xiaohongshu.mjs --area 颐和园 --target 55
 * 首次运行在独立浏览器窗口扫码；以后同一profile可断点续跑。
 * 也可将已登录的Codex浏览器Tab传给createCrawler，使用相同脚本批量运行。
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const EXPORT=path.join(ROOT,'data/raw/xiaohongshu_browser_export.json');
const LOG=path.join(ROOT,'research/xiaohongshu_crawl_log.json');
const QUEUE=path.join(ROOT,'research/xiaohongshu_queue.json');
export function parseLikes(value){
  const s=String(value??'').trim().replaceAll(',','');
  const m=s.match(/^(\d+(?:\.\d+)?)\s*(万|w|W|千|k|K)?\+?$/);
  if(!m)return null;
  return Math.round(Number(m[1])*({万:10000,w:10000,W:10000,千:1000,k:1000,K:1000}[m[2]]||1));
}
async function read(file,fallback){try{return JSON.parse(await fs.readFile(file,'utf8'));}catch(e){if(e.code==='ENOENT')return fallback;throw e;}}
async function save(file,obj){await fs.mkdir(path.dirname(file),{recursive:true});await fs.writeFile(file+'.tmp',JSON.stringify(obj,null,2),'utf8');await fs.rename(file+'.tmp',file);}
const canonical=u=>u.split('?')[0].replace('/search_result/','/explore/');
const POIS={黄山:/迎客松|光明顶|云谷|玉屏|始信峰|西海|排云亭|天都峰|莲花峰|白鹅岭|鳌鱼峰|猴子观海|太平索道/g,九寨沟:/长海|五彩池|五花海|箭竹海|熊猫海|珍珠滩|诺日朗|犀牛海|树正|原始森林|镜海|芦苇海|盆景滩/g,颐和园:/东宫门|北宫门|西门|新建宫门|昆明湖|万寿山|佛香阁|十七孔桥|长廊|石舫|西堤|谐趣园|苏州街|仁寿殿|乐寿堂|玉澜堂|画中游|南湖岛/g};
function quickValid(r){return r.raw_content.replace(/\s/g,'').length>=80&&new Set(r.raw_content.match(POIS[r.scenic_area])||[]).size>=2&&/路线|线路|行程|游览|徒步|步行|入园|出园|乘车|下车|先|然后|之后|→|➡|—/.test(r.raw_content);}

export async function createCrawler(tab,{area='颐和园',target=55,keyword=`${area} 游记 路线`,retryFailed=false}={}){
  if(!POIS[area])throw Error('景区必须是黄山、九寨沟或颐和园');
  const pw=tab.playwright||tab;
  const observe=async()=>{if(tab.getAXState)await tab.getAXState({emit:false});};
  const back=async()=>tab.back?tab.back():tab.goBack();
  const waitVisible=(milliseconds)=>tab.playwright?{state:'visible',timeoutMs:milliseconds}:{state:'visible',timeout:milliseconds};
  let rows=await read(EXPORT,[]),log=await read(LOG,[]),queues=await read(QUEUE,{});
  if(retryFailed)for(const item of queues[area]||[]){if(item.error){delete item.attempted;delete item.error;}}
  const flush=async()=>{await save(EXPORT,rows);await save(LOG,log);await save(QUEUE,queues);};
  const count=()=>rows.filter(r=>r.scenic_area===area&&quickValid(r)).length;
  async function prepare(){
    // 使用页面实际暴露的三种搜索框，兼容新旧搜索UI。
    let input;
    for(const id of ['#search-input-ai','#search-input','#search-input-in-feeds']){
      if(await pw.locator(id).isVisible()){input=pw.locator(id);break;}
    }
    if(!input){await tab.goto('https://www.xiaohongshu.com/explore');await observe();
      for(const id of ['#search-input-in-feeds','#search-input','#search-input-ai'])if(await pw.locator(id).isVisible()){input=pw.locator(id);break;}}
    if(!input)throw Error('未发现可见搜索框；请完成登录或检查页面');
    // 新版 textarea 的 fill 只修改 DOM，未必触发站点受控输入状态。
    // 已连接浏览器用真实键盘输入；独立 Playwright 用逐字输入。
    await input.click();
    if(tab.playwright&&tab.typeText){await tab.pressKey(null,'ctrl+a');await tab.typeText(null,keyword);await tab.pressKey(null,'Return');}
    else{await input.fill('');await input.pressSequentially(keyword);await input.press('Enter');}
    await observe();
    await pw.locator('a.title[href*="/search_result/"]').filter({hasText:area}).first().waitFor(waitVisible(20000));
    await pw.locator('.filter').filter({visible:true}).first().click();await observe();
    const sort=pw.locator('.tags:not([aria-hidden="true"])').filter({hasText:/^最多点赞$/});
    try{await sort.waitFor(waitVisible(1800));}catch{if(await sort.count()===0){await pw.locator('.filter').filter({visible:true}).first().click();await observe();}}
    await sort.click();await observe();
    await pw.locator('a.title[href*="/search_result/"]').filter({hasText:area}).first().waitFor(waitVisible(20000));
    let status=await pw.evaluate(()=>Array.from(document.querySelectorAll('.tags.active')).map(x=>x.textContent));
    if(!status.includes('最多点赞')){await pw.locator('.filter').filter({visible:true}).first().click();await observe();status=await pw.evaluate(()=>Array.from(document.querySelectorAll('.tags.active')).map(x=>x.textContent));}
    if(!status.includes('最多点赞'))throw Error('点赞排序未成功');
    try{await pw.getByText('收起',{exact:true}).click();await observe();}catch{}
    queues[area]=queues[area]||[];
    log.push({kind:'search',area,keyword,sort:'最多点赞',time:new Date().toISOString()});
    await flush();
  }
  async function discover({scrolls=6}={}){
    let stale=0,added=0;
    for(let n=0;n<=scrolls;n++){
      const cards=await pw.evaluate(()=>Array.from(document.querySelectorAll('.note-item')).map(item=>{
        const a=item.querySelector('a.title[href*="/search_result/"]');
        return a?{title:a.textContent.trim(),url:a.href,like_count_display:item.querySelector('.like-wrapper .count')?.textContent?.trim()||'',author:item.querySelector('.author .name')?.textContent?.trim()||'',published_at_raw:item.querySelector('.author .time')?.textContent?.trim()||''}:null;
      }).filter(Boolean));
      let found=0;
      for(const c of cards){
        c.like_count=parseLikes(c.like_count_display);c.like_count_observed_at=new Date().toISOString();
        const old=queues[area].find(x=>canonical(x.url)===canonical(c.url));
        if(old)Object.assign(old,c);else{queues[area].push(c);found++;}
      }
      added+=found;stale=found?0:stale+1;await flush();
      if(stale>=3)break;
      const point=await pw.evaluate(()=>{const e=document.querySelector('.search-layout-wrapper')||document.scrollingElement;const r=e.getBoundingClientRect();return [Math.round(r.left+r.width*0.75),Math.round(r.top+Math.min(r.height*0.7,500))];});
      if(tab.scroll)await tab.scroll(point,'down',2);else{await tab.mouse.move(point[0],point[1]);await tab.mouse.wheel(0,1200);}
      await observe();
    }
    queues[area].sort((a,b)=>(b.like_count??-1)-(a.like_count??-1));await flush();
    return {area,discovered:queues[area].length,added,valid_saved:count()};
  }
  async function step({batchSize=12}={}){
    let processed=0;
    const done=new Set(rows.map(x=>canonical(x.source_url)));
    for(const c of queues[area]||[]){
      if(count()>=target||processed>=batchSize)break;
      if(done.has(canonical(c.url))||c.attempted)continue;
      const began=new Date().toISOString();
      try{
        // 优先SPA点击；若虚拟列表移除了该卡片，才用其真实公开URL导航。
        const card=pw.locator('a.title').filter({hasText:c.title});
        if(await card.count()===1)await card.click();else await tab.goto(c.url,{waitUntil:'domcontentloaded',timeout:15000});
        await observe();
        // 笔记被删或链接失效时页面只剩外壳，等不到正文容器就直接判失败，不死等。
        try{await pw.locator('#detail-desc').waitFor(waitVisible(8000));}
        catch{throw Error('笔记不可访问：页面无正文容器');}
        const r=await pw.evaluate(()=>({title:document.querySelector('#detail-title')?.innerText||'',raw_content:document.querySelector('#detail-desc')?.innerText||'',source_url:location.href.split('?')[0],source_url_with_token:location.href,author:document.querySelector('#noteContainer .username,.note-container .username')?.innerText||'',published_at_raw:Array.from(document.querySelectorAll('.note-container .date,#noteContainer .date')).slice(0,1).map(x=>x.innerText).join('')}));
        if(canonical(r.source_url)!==canonical(c.url))throw Error('详情URL与目标不符，未入库');
        Object.assign(r,{scenic_area:area,collected_at:new Date().toISOString(),like_count:c.like_count,like_count_display:c.like_count_display,like_count_observed_at:c.like_count_observed_at||began,like_count_source:'搜索卡片可见点赞数',search_keyword:keyword,search_sort:'最多点赞',source_platform:'小红书',raw_format:'text',extraction_selector:'#detail-desc.innerText',content_scope:'visible_note_text_only_no_image_OCR_no_comments'});
        rows.push(r);done.add(canonical(c.url));c.attempted=true;
        log.push({kind:'note',area,url:r.source_url,title:r.title,chars:r.raw_content.length,like_count:r.like_count,route_candidate:quickValid(r),time:r.collected_at});
        await flush();
        await back();await observe();
      }catch(e){
        if(/exec context not found|Debugger unattached/.test(String(e)))throw e;
        c.attempted=true;c.error=String(e).slice(0,300);log.push({kind:'note_failure',area,url:canonical(c.url),error:c.error,time:began});await flush();try{await back();await observe();}catch{}
      }
      processed++;
    }
    return {area,processed,total_raw:rows.filter(r=>r.scenic_area===area).length,route_candidates:count(),target,remaining:(queues[area]||[]).filter(c=>!c.attempted&&!done.has(canonical(c.url))).length};
  }
  return {prepare,discover,step,status:()=>({area,route_candidates:count(),target,queued:(queues[area]||[]).length})};
}

if(typeof process!=='undefined'&&process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const value=(key,fallback)=>{const i=process.argv.indexOf(key);return i<0?fallback:process.argv[i+1];};
  const area=value('--area','all'),target=Number(value('--target','35'));
  if(area!=='all'&&!POIS[area])throw Error('--area 必须为 all、黄山、九寨沟或颐和园');
  if(!Number.isInteger(target)||target<1)throw Error('--target 必须为正整数');
  const {chromium}=await import('playwright');
  const profile=path.resolve(value('--profile',path.join(ROOT,'.browser-profile')));
  const context=await chromium.launchPersistentContext(profile,{channel:value('--channel','msedge'),headless:false,viewport:null});
  const page=context.pages()[0]||await context.newPage();await page.goto('https://www.xiaohongshu.com/explore');
  console.log('请在浏览器完成本人登录。脚本不会读取/导出Cookie，不自动解决验证码。登录后在终端按 Enter。');
  const {createInterface}=await import('node:readline/promises');const rl=createInterface({input:process.stdin,output:process.stdout});await rl.question('');rl.close();
  try{for(const spot of area==='all'?Object.keys(POIS):[area]){
    const crawler=await createCrawler(page,{area:spot,target,retryFailed:process.argv.includes('--retry-failed')});await crawler.prepare();
    // 先把候选池填到目标数量再开始读取，避免读到一半再回头找链接。
    let round=0;
    while(crawler.status().queued<target&&round<12){const d=await crawler.discover({scrolls:6});console.log(d);round++;if(!d.added)break;}
    while(crawler.status().route_candidates<target){const r=await crawler.step({batchSize:10});console.log(r);if(!r.processed){const d=await crawler.discover({scrolls:5});console.log(d);if(!d.added)break;}}
  }}finally{await context.close();}
}
