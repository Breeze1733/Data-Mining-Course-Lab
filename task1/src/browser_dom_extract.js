// 小红书登录由本人在浏览器完成。打开真实笔记详情后，在浏览器控制工具
// 的只读 evaluate 中执行这个函数；保存返回的 JSON。不要采集评论或登录信息。
// 图片内文字不在 #detail-desc 中，本实验没有将图片OCR冒充为可见正文。
() => {
  const desc = document.querySelector('#detail-desc');
  const title = document.querySelector('#detail-title');
  if (!desc || !title || desc.innerText.trim().length < 80) {
    throw new Error('正文为空、过短或尚未加载，拒绝纳入');
  }
  return {
    title: title.innerText,
    source_url: location.href.split('?')[0],
    raw_content: desc.innerText,
    raw_format: 'text',
    extraction_selector: '#detail-title; #detail-desc.innerText',
    author: document.querySelector('#noteContainer .username,.note-container .username')?.innerText || '',
    published_at_raw: Array.from(document.querySelectorAll('.note-container .date,#noteContainer .date')).slice(0,1).map(x=>x.innerText).join(''),
    published_at: '', // 不把月日/相对时间猜成完整发布日期
    acquisition_method: '本人登录后 浏览器DOM自动提取'
  };
}
