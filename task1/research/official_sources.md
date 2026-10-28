# 任务1官方路线来源核验

核验日期：2026-10-28。以下均为真实网页，已通过 web 浏览和 Python 标准库 urllib 实际读取。只将抓取成功的页面用于正式数据；HTTP 412 页面作为发现记录保留，不声称完成抓取。

## 建议采用的三条官方来源

### 黄山

- 标题：黄山风景区常见旅游咨询（HTML 嵌入 JSON 内 title 另为“黄山风景区清明假期常见旅游咨询”）。
- 页面日期：2021-02-13 11:10:29。
- URL：https://wap.huangshan.com.cn/detail/strategy/fjqlyzx
- 官方性：平台注册协议 https://wap.huangshan.com.cn/register/protocol 自称“黄山旅游官方平台”，明确 huangshan.com.cn 与平台标识为黄山智慧旅游有限公司注册商标。页面属于景区运营官方平台，并非普通旅行社投稿。
- 抓取情况：urllib GET，User-Agent Mozilla/5.0，HTTP 200，约 47 KB HTML；无需登录。
- 内容：含北门、南门的一日及多日游线路。建议取“一日游线路”下“从南门上”的第②条，其顺序为云谷寺、白鹅岭站、始信峰、北海、光明顶、白云宾馆、海心亭、鳌鱼峰、莲花亭、迎客松、玉屏索道。
- 提取建议：该页同时有 `var data=[{"data":{..."content":"<p>..."}}]` 数据与渲染正文，选择其中一个来源，避免重复提取。可从嵌入 JSON 的 `data[0].data.content` 提取 HTML，再限定到第 20 问游览线路范围，排除票务、防疫、页头页脚。已实际验证 `json.loads(re.search(r'var data=(\[.*?\]);\s*var module', html, re.S).group(1))[0]['data']['content']` 可解出内容。原文从 `20.清明假期期间，一日游、二日游路线怎么选择？` 开始，到 `21.黄山旅游常用咨询电话有哪些？` 之前结束；若取一日游，可再截到 `（2）二日游路线` 之前。
- 时效注意：这是 2021 年历史指南，适合本次文本清洗实验，不能作为 2026 年门票、开放、轮休和疫情措施的现行依据。保留发布日期，不将历史防疫内容用于出行建议。

### 九寨沟

- 标题：九寨沟景区官方网站 - 游玩方式；建议记录标题为“游玩方式 一日精华游”。
- URL：https://www.jiuzhai.com/intelligent-service/way-of-play
- 官方性：页脚版权主体“九寨沟风景名胜区管理局”，当前页脚年份 2002—2026；网站自称景区官方网站。
- 日期：未见一日游模块单独的发布/更新时间，应留空，不用抓取日期冒充发布日期。
- 抓取情况：urllib GET，User-Agent Mozilla/5.0，HTTP 200，约 81 KB HTML；无需登录。
- 内容：上午由沟口、原始森林、芳草海、天鹅海、箭竹海、熊猫海、五花海、镜海到诺日朗；中午用餐；下午长海、五彩池、犀牛海、老虎海、树正一带、双龙海、盆景滩后出沟。原文保留逐段时间、交通方式和游览时长。
- 提取建议：直接选 `#imagegrid-8941-particle` 模块，标题“一日精华游”，正文 `.g-imagegrid-desc`；XPath 为 `//*[@id='imagegrid-8941-particle']/div[contains(concat(' ', normalize-space(@class), ' '), ' g-imagegrid ')]/div[contains(concat(' ', normalize-space(@class), ' '), ' g-imagegrid-desc ')]`，也可宽松用 `//*[@id='imagegrid-8941-particle']//*[contains(@class,'g-imagegrid-desc')]`；排除后面的二日舒适游与三日多彩游。该段有错误/非标准 `<br>` 标记，HTML 解析器应保留换行而非只依赖段落标签。
- 质量注意：原文尾段“盆景滩→沟口”的时间与前段存在重叠，忠实保留并在异常检查中标注；不能静默替作者改时间。页面其他模块有“天鹅湖/天鹅海”等名称差异，本任务只做清洗，不强行实体归一。

### 颐和园

- 标题：北京市属公园暑期红色游。
- URL：https://gygl.beijing.gov.cn/xxgk/xxgk_gyxx/202507/t20250725_4158254.html
- 页面日期：2025-07-25；页面来源可在 `.article-info` 检查。
- 官方性：北京市公园管理中心政府网站，主办单位为北京市公园管理中心，是颐和园主管单位发布的官方推荐。
- 抓取情况：带 User-Agent Mozilla/5.0 的 urllib GET 为 HTTP 200，约 130 KB HTML；无 UA 的 urllib 曾返回 403，不能据此断言需要登录。
- 内容：正文有两条颐和园主题游路线。建议选“颐和园西门”开头的路线，依次到畅观堂、镜桥沿线、玉带桥、耕织图爱国主义教育基地、豳风桥、界湖桥、绮望轩、四大部洲。另一条由东宫门至益寿堂、谐趣园与霁清轩、须弥灵境遗址、苏州街。
- 提取建议：正文容器 class=`view TRS_UEDITOR trs_paper_default trs_web`；其中两条路线为独立 `<p>`。不要把后面香山、天坛、北海的路线混为颐和园路线。精确 XPath 可用 `//div[contains(@class,'TRS_UEDITOR')]//p[starts-with(normalize-space(.),'颐和园西门') or starts-with(normalize-space(.),'颐和园东宫门')]`。无 XPath 库时逐个提取 `<p>` 的纯文本，再按这两个前缀保留两段即可；保留主题游属性。

## 备用来源

1. 黄山风景区管理委员会《西海大峡谷游玩线路推荐》：https://hsgwh.huangshan.gov.cn/lyfw/xltj/9195903.html 。页面搜索索引可看到 2024-07-14 发布、来源“黄山旅游官方平台”，含一日游与两日游。实际 web open 和 urllib 均 HTTP 412，本轮不能视为成功直接采集。
2. 黄山市政府推荐多条黄山一日与二日游线路：https://www.huangshan.gov.cn/zwgk/public/6615714/11607391.html 。搜索索引内容完整，urllib HTTP 412，不宜作为本轮成功抓取证据。
3. 北京市公园管理中心《市属公园首次推出APEC精品文化之旅》：https://gygl.beijing.gov.cn/xxgk/xxgk_gyxx/201912/t20191206_883660.html 。带 Mozilla UA 的 urllib HTTP 200。实际内容发布时间为 2014-12-04 15:03，不能按 URL 中的 2019 冒充日期。含颐和园仁寿殿至昆明湖的经典线路，较 2025 红色游更经典但更旧。若优先常规游览线路，可用此页替换主题游，逐段读取正文，仅取 `颐和园：` 到 `天坛公园：` 之间的小节（共标题、路线、推荐拍照留念处三段）；其中路线正文以 `游览路线：仁寿殿` 开头。既能保留官方路线又避免混入其他公园。
4. 北京市政府英文站 Summer Palace：https://english.beijing.gov.cn/specials/parktours/guidevisitors/summerpalace/ 。Travel Routes 有 3 条英文线路，是政府官方内容；若使用需保留英文原文，中文译文另字段，不能把译文当成原始文本。

## 复现片段

```python
from urllib.request import Request, urlopen
req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urlopen(req, timeout=25) as response:
    raw_html = response.read().decode("utf-8", errors="replace")
```

无需账号和登录态即可获取上述建议使用的三个页面；实际采集时保留原始 HTML、HTTP 状态、URL、抓取时间、网页 hash 和正文抽取范围即可追溯。
