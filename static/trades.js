'use strict';
(() => {
 const $=s=>document.querySelector(s),csrf=$('meta[name="csrf-token"]').content;
 let catalog=[];
 const node=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
 const statusNames={pending:'等待接受',accepted:'交換中／已預留',rejected:'已拒絕',cancelled:'已取消',completed:'雙方已完成'};
 function message(text){$('#trade-message').textContent=text;$('#trade-message').hidden=false;}
 async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw new Error(v.error||'操作失敗。');return v;}
 function addLine(direction='give'){
  const line=node('div');line.className='edit-line';const dir=node('select');dir.className='trade-direction';
  for(const [v,t] of [['give','我提供'],['receive','對方提供（我要）']]){const o=node('option',t);o.value=v;dir.append(o);}dir.value=direction;
  const shiki=node('select');shiki.className='trade-shikigami';const blank=node('option','選擇式神');blank.value='';shiki.append(blank);
  for(const r of catalog){const o=node('option',`${r.name} · ${r.rarity}`);o.value=r.id;shiki.append(o);}
  const qty=node('input');qty.type='number';qty.min='1';qty.max='99999';qty.value='1';qty.className='trade-quantity';qty.setAttribute('aria-label','交換數量');
  const remove=node('button','移除');remove.type='button';remove.className='secondary';remove.onclick=()=>line.remove();line.append(dir,shiki,qty,remove);$('#trade-lines').append(line);ShikigamiPicker.attach(shiki,catalog);
 }
 async function load(){
  const rows=await api('/api/trades'+($('#trade-scope').value==='mine'?'?mine=1':''));
  $('#trade-list').replaceChildren(...rows.map(r=>{
   const card=node('article');card.className='sample-card';
   card.append(node('h3',`${r.requester_name} · ${r.requester_account_name} ↔ ${r.recipient_name} · ${r.recipient_account_name}`),node('p',statusNames[r.status]));
   const ul=node('ul');for(const i of r.items)ul.append(node('li',`${i.direction==='give'?'發起方提供':'對方提供'} ${i.name} × ${i.quantity}`));card.append(ul);
   card.append(node('p',`發起方確認：${r.requester_confirmed?'已完成':'尚未'} · 對方確認：${r.recipient_confirmed?'已完成':'尚未'}`));
   if(r.my_side){
    const notice=node('p',`Bot 通知：${{pending:'等待發送',sending:'發送中',sent:'已發送',failed:'發送失敗，請檢查 Bot 權限／私訊設定'}[r.notification_status]||'等待通知'}`);card.append(notice);
    const actions=[];
    if(r.my_side==='recipient'&&r.status==='pending')actions.push(['accept','接受交換'],['reject','拒絕']);
    if(['pending','accepted'].includes(r.status))actions.push(['cancel','取消交換並釋放預留']);
    const confirmed=r.my_side==='requester'?r.requester_confirmed:r.recipient_confirmed;
    if(r.status==='accepted'&&!confirmed)actions.push(['confirm','我已實際完成交換']);
    if(r.notification_status==='failed')actions.push(['retry-notification','重試通知']);
    const controls=node('div');controls.className='tools';
    for(const [action,label] of actions){const button=node('button',label);button.onclick=async()=>{
     if(['confirm','cancel','reject'].includes(action)&&!window.confirm(action==='confirm'?'確認你已在遊戲中完成本次交換？雙方都確認後會扣除庫存。':label+'？'))return;
     button.disabled=true;try{await api(`/api/trades/${r.id}/${action}`,{});message('交換狀態已更新。');await load();}catch(e){message(e.message);button.disabled=false;}
    };controls.append(button);}card.append(controls);
   }return card;
  }));
  if(!rows.length)$('#trade-list').append(node('p','目前沒有交換紀錄。'));
 }
 async function init(){
  const [items,accounts,available]=await Promise.all([api('/api/shards/catalog'),api('/api/game-accounts'),api('/api/fragments?target=offers')]);catalog=items;
  for(const r of accounts){const o=node('option',`${r.nickname} · ${r.server_name}`);o.value=r.id;$('#trade-own').append(o);}
  const mine=new Set(accounts.map(r=>r.id)),other=new Map();for(const r of available)if(!mine.has(r.game_account_id))other.set(r.game_account_id,r);
  for(const [id,r] of other){const o=node('option',`${r.player_name} · ${r.nickname} · ${r.server_name}`);o.value=id;$('#trade-other').append(o);}
  const preset=new URLSearchParams(location.search).get('other_account_id');if(preset)$('#trade-other').value=preset;
  addLine('give');addLine('receive');$('#trade-add').onclick=()=>addLine();$('#trade-refresh').onclick=()=>load().catch(e=>message(e.message));$('#trade-scope').onchange=()=>load().catch(e=>message(e.message));
  $('#trade-submit').onclick=async()=>{
   const button=$('#trade-submit');button.disabled=true;
   try{const items=[...document.querySelectorAll('#trade-lines .edit-line')].map(row=>({direction:row.querySelector('.trade-direction').value,shikigami_id:row.querySelector('.trade-shikigami').value,quantity:Number(row.querySelector('.trade-quantity').value)}));
    await api('/api/trades',{game_account_id:$('#trade-own').value,other_account_id:$('#trade-other').value,items});message('已建立申請，等待對方接受。Bot 通知已排入佇列。');await load();
   }catch(e){message(e.message);}finally{button.disabled=false;}
  };await load();
 }
 init().catch(e=>message(e.message));
})();
