'use strict';
window.ShikigamiPicker = (() => {
  let dialog, search, rarity, list, records=[], choose;
  function element(tag,text) {const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;}
  function render() {
    const q=search.value.trim().toLocaleLowerCase();
    const filtered=records.filter(r=>(!rarity.value||r.rarity===rarity.value)&&[r.name,r.name_simplified,...(r.aliases||[])].filter(Boolean).join(' ').toLocaleLowerCase().includes(q));
    list.replaceChildren(...filtered.map(r=>{
      const b=element('button');b.type='button';b.className='picker-option';
      if(r.image){const img=element('img');img.src=r.image;img.alt='';img.loading='lazy';b.append(img);}
      b.append(element('strong',r.name),element('small',`${r.rarity} · ${r.name_simplified||''}`));
      b.addEventListener('click',()=>{dialog.close();choose(r);});return b;
    }));
    if(!filtered.length)list.append(element('p','沒有符合的式神。'));
  }
  function open(catalog,value,callback) {
    if(!dialog){
      dialog=element('dialog');dialog.className='picker-dialog';dialog.setAttribute('aria-label','搜尋並選擇式神');
      const head=element('div');head.className='picker-tools';search=element('input');search.type='search';search.placeholder='搜尋繁體／簡體名字或別名';search.setAttribute('aria-label','搜尋式神');
      rarity=element('select');rarity.setAttribute('aria-label','篩選 Rarity');
      for(const [v,t] of [['','全部 Rarity'],['SSR','SSR'],['SP','SP'],['UR','UR'],['COLLAB','聯動']]){const o=element('option',t);o.value=v;rarity.append(o);}
      const close=element('button','關閉');close.type='button';close.onclick=()=>dialog.close();
      head.append(search,rarity,close);list=element('div');list.className='picker-results';dialog.append(head,list);document.body.append(dialog);
      search.oninput=rarity.onchange=render;
    }
    records=catalog;choose=callback;search.value='';rarity.value='';render();dialog.showModal();search.focus();
  }
  function attach(select,catalog){
    const b=element('button','搜尋／按 Rarity 選擇');b.type='button';b.className='picker-launch';
    b.onclick=()=>open(catalog,select.value,r=>{select.value=r.id;select.dispatchEvent(new Event('change',{bubbles:true}));});
    select.after(b);return b;
  }
  return {open,attach};
})();
