'use strict';
(() => {
  const $=s=>document.querySelector(s),node=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
  let page=1,revision=0;
  async function load(){
    const request=++revision;$('#records-message').textContent='載入中…';
    $('#records-prev').disabled=$('#records-next').disabled=true;$('#records-list').replaceChildren();
    try{
      const response=await fetch('/api/trade-records?'+new URLSearchParams({status:$('#records-status').value,page}));
      const data=await response.json();if(request!==revision)return;
      if(!response.ok)throw new Error(data.error||'無法讀取交換紀錄。');
      $('#records-list').replaceChildren(...data.items.map(r=>{
        const card=node('article');card.className='sample-card';
        card.append(node('h2',r.status==='completed'?'已完成交換':'正在交換'),node('p',`${r.requester_name} · ${r.requester_account_name}（${r.requester_server}） ↔ ${r.recipient_name} · ${r.recipient_account_name}（${r.recipient_server}）`));
        for(const [direction,name] of [['give',r.requester_account_name],['receive',r.recipient_account_name]]){
          card.append(node('h3',`${name} 提供`));const list=node('ul');
          for(const item of r.items.filter(i=>i.direction===direction))list.append(node('li',`${item.name} × ${item.quantity} 片`));card.append(list);
        }
        card.append(node('p',`雙方確認：${r.requester_confirmed?'已完成':'尚未'}／${r.recipient_confirmed?'已完成':'尚未'}`),node('small',`建立：${new Date(r.created_at).toLocaleString('zh-TW')} · 更新：${new Date(r.updated_at).toLocaleString('zh-TW')}`));
        return card;
      }));
      $('#records-message').textContent=data.items.length?'':$('#records-status').value==='completed'?'目前沒有已完成的交換紀錄。':'目前沒有玩家正在交換。';
      $('#records-page').textContent=`第 ${page} 頁`;$('#records-prev').disabled=page<=1;$('#records-next').disabled=!data.has_more;
    }catch(error){if(request===revision){$('#records-message').textContent=error.message;$('#records-prev').disabled=page<=1;}}
  }
  $('#records-status').onchange=$('#records-refresh').onclick=()=>{page=1;load();};
  $('#records-prev').onclick=()=>{page--;load();};$('#records-next').onclick=()=>{page++;load();};load();
})();
