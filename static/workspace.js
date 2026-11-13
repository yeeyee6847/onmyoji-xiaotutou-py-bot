'use strict';
(() => {
  const $=s=>document.querySelector(s), mode=document.body.dataset.mode, csrf=$('meta[name="csrf-token"]').content;
  let catalog=[], page=1, total=0, revision=0;
  const node=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
  function message(text){$('#workspace-message').textContent=text;$('#workspace-message').hidden=false;}
  async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw new Error(v.error||'操作失敗');return v;}
  function selectShikigami(value=''){
    const s=node('select');const blank=node('option','選擇式神…');blank.value='';s.append(blank);
    for(const item of catalog){const o=node('option',`${item.name} · ${item.rarity}`);o.value=item.id;s.append(o);}s.value=value;return s;
  }
  function addManual(){
    const line=node('div');line.className='edit-line';const shiki=selectShikigami();shiki.className='manual-shikigami';
    const target=node('select');target.className='manual-target';for(const [v,t] of [['offers','可提供'],['wants','想要']]){const o=node('option',t);o.value=v;target.append(o);}
    const qty=node('input');qty.type='number';qty.min='0';qty.max='99999';qty.value='0';qty.className='manual-quantity';qty.setAttribute('aria-label','碎片數量');
    const remove=node('button','移除');remove.type='button';remove.className='secondary';remove.onclick=()=>line.remove();
    line.append(shiki,target,qty,remove);$('#manual-rows').append(line);ShikigamiPicker.attach(shiki,catalog);
  }
  async function results(){
    const requestId=++revision;
    const params=new URLSearchParams();if(mode==='mine'){params.set('mine','1');if($('#workspace-account').value)params.set('game_account_id',$('#workspace-account').value);}
    for(const [key,id] of [['shikigami_id','workspace-shikigami'],['target','workspace-target'],['server','workspace-server']])if($('#'+id).value)params.set(key,$('#'+id).value);
    if($('#workspace-rarity').value)params.set('rarity',$('#workspace-rarity').value);
    const rows=await api('/api/fragments?'+params);
    if(requestId!==revision)return;
    const filtered=rows.filter(r=>!$('#workspace-rarity').value||r.rarity===$('#workspace-rarity').value);
    $('#workspace-empty').hidden=filtered.length>0;
    $('#workspace-rows').replaceChildren(...filtered.map(row=>{
      const quantityText=mode==='mine'&&row.reserved?`${row.quantity}（可用 ${row.available}／預留 ${row.reserved}）`:String(row.quantity);
      const tr=node('tr');for(const text of [row.name,row.target==='wants'?'想要':'可提供',quantityText,row.player_name,`${row.nickname} · ${row.server_name}`])tr.append(node('td',text));
      const action=node('td');
      if(mode==='mine'){
        const input=node('input');input.type='number';input.min='0';input.max='99999';input.value=row.quantity;input.setAttribute('aria-label',`${row.name}數量`);
        const save=node('button','覆蓋儲存');save.onclick=async()=>{
          save.disabled=true;try{if(input.value==='')throw new Error('請填寫數量；清空記錄請填 0。');await api('/api/fragments',{game_account_id:row.game_account_id,items:[{shikigami_id:row.shikigami_id,target:row.target,quantity:Number(input.value)}]});message('數量已覆蓋儲存。');await results();}catch(e){message(e.message);}finally{save.disabled=false;}
        };
        const remove=node('button','刪除');remove.className='danger';remove.type='button';
        remove.onclick=async()=>{
          if(!window.confirm(`確定刪除「${row.nickname}」的「${row.name}」${row.target==='wants'?'想要':'可提供'}碎片記錄？`))return;
          remove.disabled=save.disabled=true;
          try{await api('/api/fragments/delete',{game_account_id:row.game_account_id,shikigami_id:row.shikigami_id,target:row.target});message('碎片記錄已刪除。');await results();}
          catch(e){message(e.message);}finally{remove.disabled=save.disabled=false;}
        };action.append(input,save,remove);
      }else {const link=node('a','提出交換');link.href='/trades?other_account_id='+row.game_account_id;action.append(link);}tr.append(action);return tr;
    }));
  }
  async function samples(){
    const data=await api(`/api/admin/samples?status=${$('#sample-status').value}&page=${page}`);total=data.total;
    $('#samples-page').textContent=`第 ${page} 頁 · 共 ${total} 張`;$('#samples-prev').disabled=page===1;$('#samples-next').disabled=page*40>=total;
    $('#sample-grid').replaceChildren(...data.items.map(item=>{
      const card=node('article');card.className='sample-card';const images=node('div');images.className='sample-images';
      for(const kind of ['crop','portrait']){const img=node('img');img.src=`/api/admin/samples/${item.id}/image?kind=${kind}`;img.alt=kind==='crop'?'原始裁切':'比對區域';img.loading='lazy';images.append(img);}
      const select=selectShikigami(item.shikigami_id||'');card.append(images,node('p',`OCR：${item.raw_name||'未讀出'} · ${item.status}`),select);ShikigamiPicker.attach(select,catalog);
      const controls=node('div');controls.className='tools';
      for(const [action,label] of [['approve','確認並啟用'],['reject','停用'],['delete','刪除']]){
        const button=node('button',label);button.className=action==='approve'?'':'secondary';button.onclick=async()=>{button.disabled=true;try{await api('/api/admin/samples/'+item.id,{action,shikigami_id:select.value});await samples();}catch(e){message(e.message);button.disabled=false;}};controls.append(button);
      }card.append(controls);return card;
    }));
    if(!data.items.length)$('#sample-grid').append(node('p','沒有此狀態的樣本。'));
  }
  async function init(){
    const [items,me,accounts]=await Promise.all([api('/api/shards/catalog'),api('/api/auth/me'),api('/api/game-accounts')]);catalog=items;
    $('#admin-nav').hidden=me.user.role!=='admin';$('#workspace-title').textContent={mine:'我的碎片與人工匯入',search:'搜索碎片',samples:'头像參考庫審核'}[mode];
    if(mode==='samples'){
      $('#samples-section').hidden=false;
      $('#sample-status').onchange=()=>{page=1;samples().catch(e=>message(e.message));};$('#samples-refresh').onclick=()=>samples().catch(e=>message(e.message));
      $('#samples-prev').onclick=()=>{page--;samples().catch(e=>message(e.message));};$('#samples-next').onclick=()=>{page++;samples().catch(e=>message(e.message));};await samples();return;
    }
    $('#fragment-controls').hidden=$('#fragment-results').hidden=false;$('#account-control').hidden=mode!=='mine';$('#manual-section').hidden=mode!=='mine';
    for(const r of catalog){const o=node('option',`${r.name} · ${r.rarity}`);o.value=r.id;$('#workspace-shikigami').append(o);}ShikigamiPicker.attach($('#workspace-shikigami'),catalog);
    for(const r of accounts){const o=node('option',`${r.nickname} · ${r.server_name}`);o.value=r.id;$('#workspace-account').append(o);}
    if(mode==='mine'){
      const updateAccount=()=>{$('#manual-account-selected').textContent=$('#workspace-account').value?'匯入至：'+$('#workspace-account').selectedOptions[0].textContent:'請先在上方選擇要匯入的遊戲帳號。';};
      $('#workspace-account').onchange=()=>{updateAccount();results().catch(e=>message(e.message));};
      if(accounts.length===1)$('#workspace-account').value=accounts[0].id;updateAccount();
      $('#manual-account-form').onsubmit=async event=>{
        event.preventDefault();const form=event.currentTarget,button=form.querySelector('button'),notice=$('#manual-account-message');button.disabled=true;notice.hidden=true;
        try{
          const account=await api('/api/game-accounts',Object.fromEntries(new FormData(form)));
          const option=node('option',`${account.nickname} · ${account.server_name}`);option.value=account.id;$('#workspace-account').append(option);$('#workspace-account').value=account.id;
          updateAccount();form.reset();$('#manual-account-create').open=false;message('已新增並選取遊戲帳號，可以直接匯入碎片。');await results();
        }catch(e){notice.textContent=e.message;notice.hidden=false;}finally{button.disabled=false;}
      };
    }
    if(!accounts.length&&mode==='mine')message('請先到「遊戲帳號」新增帳號，再人工匯入。');
    const preset=new URLSearchParams(location.search).get('shikigami_id');if(preset)$('#workspace-shikigami').value=preset;
    $('#workspace-search').onclick=()=>results().catch(e=>message(e.message));
    $('#manual-add').onclick=addManual;
    $('#manual-save').onclick=async()=>{
      const button=$('#manual-save');button.disabled=true;
      try{
        if(!$('#workspace-account').value)throw new Error('請先選擇要寫入的遊戲帳號。');
        if([...document.querySelectorAll('.manual-quantity')].some(input=>input.value===''))throw new Error('請填寫數量；清空記錄請填 0。');
        const items=[...document.querySelectorAll('#manual-rows .edit-line')].map(row=>({shikigami_id:row.querySelector('.manual-shikigami').value,target:row.querySelector('.manual-target').value,quantity:Number(row.querySelector('.manual-quantity').value)}));
        await api('/api/fragments',{game_account_id:$('#workspace-account').value,items});message('人工清單已保存，數量已覆蓋；其他式神保持不變。');await results();
      }catch(e){message(e.message);}finally{button.disabled=false;}
    };
    if(mode==='mine')addManual();await results();
  }
  init().catch(e=>message(e.message));
})();
