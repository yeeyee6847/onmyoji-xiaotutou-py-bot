'use strict';
(() => {
 const $=s=>document.querySelector(s),csrf=$('meta[name="csrf-token"]').content;
 let catalog=[],partners=[],stock={give:[],receive:[]},stockRevision=0,stockLoading=false;
 const node=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
 const statusNames={pending:'等待接受',accepted:'交換中／已預留',rejected:'已拒絕',cancelled:'已取消',completed:'雙方已完成'};
 function message(text){$('#trade-message').textContent=text;$('#trade-message').hidden=false;}
 async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw new Error(v.error||'操作失敗。');return v;}
 function addLine(direction='give'){
  const line=node('div');line.className='edit-line';const dir=node('select');dir.className='trade-direction';
  for(const [v,t] of [['give','我提供'],['receive','對方提供（我要）']]){const o=node('option',t);o.value=v;dir.append(o);}dir.value=direction;
  const shiki=node('select');shiki.className='trade-shikigami';shiki.setAttribute('aria-label','交換式神');
  const qty=node('input');qty.type='number';qty.required=true;qty.min='1';qty.max='99999';qty.value='1';qty.className='trade-quantity';qty.setAttribute('aria-label','交換數量');
  const count=node('span');count.className='trade-stock minor';count.setAttribute('aria-live','polite');
  const remove=node('button','移除');remove.type='button';remove.className='secondary';remove.onclick=()=>line.remove();line.append(dir,shiki,qty,count,remove);$('#trade-lines').append(line);ShikigamiPicker.attach(shiki,()=>stock[dir.value]);
  dir.onchange=()=>refreshLine(line);shiki.onchange=()=>showStock(line);refreshLine(line);return line;
 }
 function showStock(line){
  const direction=line.querySelector('.trade-direction').value,id=line.querySelector('.trade-shikigami').value;
  const row=stock[direction].find(r=>r.id===id),qty=line.querySelector('.trade-quantity');
  qty.max=String(row?.available||0);qty.disabled=!row;
  line.querySelector('.trade-stock').textContent=row?`${direction==='give'?'我方':'對方'}可用 ${row.available} 片（已扣除預留）`:'請先選擇帳號及式神';
 }
 function refreshLine(line){
  const direction=line.querySelector('.trade-direction').value,select=line.querySelector('.trade-shikigami'),value=select.value;
  const blank=node('option',stockLoading?'載入庫存中…':stock[direction].length?'選擇式神':'此帳號沒有可交換的碎片');blank.value='';
  select.replaceChildren(blank,...stock[direction].map(r=>{const o=node('option',`${r.name} · ${r.rarity} · 可用 ${r.available} 片`);o.value=r.id;return o;}));
  select.value=stock[direction].some(r=>r.id===value)?value:'';select.disabled=stockLoading||!stock[direction].length;
  line.querySelector('.picker-launch').disabled=select.disabled;showStock(line);
 }
 async function loadStock(){
  const revision=++stockRevision;stockLoading=true;stock={give:[],receive:[]};
  document.querySelectorAll('#trade-lines .edit-line').forEach(refreshLine);$('#trade-submit').disabled=true;
  const own=$('#trade-own').value,other=$('#trade-other').value;
  try{
   const rows=await Promise.all([own?api('/api/fragments?mine=1&target=offers&game_account_id='+own):[],other?api('/api/fragments?target=offers&game_account_id='+other):[]]);
   if(revision!==stockRevision)return;
   for(const [i,direction] of ['give','receive'].entries())stock[direction]=catalog.flatMap(r=>{const f=rows[i].find(f=>f.shikigami_id===r.id&&f.available>0);return f?[{...r,available:f.available}]:[];});
  }finally{if(revision===stockRevision){stockLoading=false;document.querySelectorAll('#trade-lines .edit-line').forEach(refreshLine);$('#trade-submit').disabled=false;}}
 }
 function filterPartners(){
  const value=$('#trade-other').value,q=$('#trade-other-search').value.trim().toLocaleLowerCase();
  const rows=partners.filter(r=>r.id===value||`${r.player_name} ${r.nickname} ${r.server_name}`.toLocaleLowerCase().includes(q));
  const blank=node('option',rows.length?'請選擇對方帳號':'找不到符合的帳號');blank.value='';
  $('#trade-other').replaceChildren(blank,...rows.map(r=>{const o=node('option',`${r.player_name} · ${r.nickname} · ${r.server_name}`);o.value=r.id;return o;}));$('#trade-other').value=value;
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
     button.disabled=true;try{const result=await api(`/api/trades/${r.id}/${action}`,{});message(result.status==='completed'?'交換已完成，完成紀錄僅 Admin 可查看。':'交換狀態已更新。');await Promise.all([load(),loadStock()]);}catch(e){message(e.message);button.disabled=false;}
    };controls.append(button);}card.append(controls);
   }return card;
  }));
  if(!rows.length)$('#trade-list').append(node('p','目前沒有交換紀錄。'));
 }
 async function init(){
  const [items,accounts,available]=await Promise.all([api('/api/shards/catalog'),api('/api/game-accounts'),api('/api/trades/partners')]);catalog=items;partners=available;
  for(const r of accounts){const o=node('option',`${r.nickname} · ${r.server_name}`);o.value=r.id;$('#trade-own').append(o);}
  filterPartners();$('#trade-other-search').oninput=filterPartners;
  const params=new URLSearchParams(location.search),preset=params.get('other_account_id');if(preset){$('#trade-other').value=preset;if(!$('#trade-other').value)message('此帳號目前沒有可交換的碎片，或是你自己的帳號。');}
  if(accounts.length===1)$('#trade-own').value=accounts[0].id;
  addLine('give');addLine('receive');$('#trade-own').onchange=$('#trade-other').onchange=()=>loadStock().catch(e=>message(e.message));
  $('#trade-add').onclick=()=>addLine();$('#trade-refresh').onclick=()=>Promise.all([load(),loadStock()]).catch(e=>message(e.message));$('#trade-scope').onchange=()=>load().catch(e=>message(e.message));
  await loadStock();
  const preselected=params.get('shikigami_id'),direction=params.get('direction')==='give'?'give':'receive';
  if(preselected){const line=[...document.querySelectorAll('#trade-lines .edit-line')].find(r=>r.querySelector('.trade-direction').value===direction);const select=line.querySelector('.trade-shikigami');select.value=preselected;showStock(line);}
  $('#trade-submit').onclick=async()=>{
   const button=$('#trade-submit');button.disabled=true;
   try{if(stockLoading)throw new Error('請等待庫存載入。');
    const items=[...document.querySelectorAll('#trade-lines .edit-line')].map(row=>{
     const direction=row.querySelector('.trade-direction').value,id=row.querySelector('.trade-shikigami').value,qty=row.querySelector('.trade-quantity');
     const available=stock[direction].find(r=>r.id===id)?.available||0;
     if(!id||!qty.checkValidity()||Number(qty.value)>available)throw new Error('請選擇可提供的式神，並填寫不超過可用碎片的正整數。');
     return {direction,shikigami_id:id,quantity:Number(qty.value)};
    });
    await api('/api/trades',{game_account_id:$('#trade-own').value,other_account_id:$('#trade-other').value,items});message('已建立申請，等待對方接受。Bot 通知已排入佇列。');await load();
   }catch(e){message(e.message);}finally{button.disabled=false;}
  };await load();
 }
 init().catch(e=>message(e.message));
})();
