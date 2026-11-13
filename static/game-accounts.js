'use strict';
(() => {
  const manager = document.querySelector('#game-account-manager');
  if (!manager) return;
  const select = document.querySelector('#game-account-select');
  const form = document.querySelector('#game-account-form');
  const error = document.querySelector('#game-account-error');
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '無法讀取遊戲帳號。');
    return data;
  }
  let revision = 0;
  async function showFragments() {
    const list = document.querySelector('#account-fragments');
    if (!list) return;
    const note = document.querySelector('#account-fragments-note');
    const current = ++revision;
    list.replaceChildren();
    note.textContent = select.value ? '載入中…' : '請先選擇遊戲帳號。';
    if (!select.value) return;
    try {
      const rows = await api(`/api/game-accounts/${select.value}/fragments`);
      if (current !== revision) return;
      note.textContent = rows.length ? '顯示每位式神最近確認的數量；未出現在新圖中的舊記錄會保留。' : '此帳號尚未保存碎片清單。';
      list.replaceChildren(...rows.map(row => { const item = document.createElement('li'); item.textContent = `【${row.target === 'wants' ? '想要' : '可提供'}】${row.name}：${row.quantity}`; return item; }));
    } catch (problem) { if (current === revision) note.textContent = problem.message; }
  }
  async function load(selected = '') {
    const rows = await api('/api/game-accounts');
    const blank = document.createElement('option'); blank.value = ''; blank.textContent = '請選擇遊戲帳號…';
    select.replaceChildren(blank, ...rows.map(row => {
      const option = document.createElement('option'); option.value = row.id;
      option.textContent = row.nickname + (row.server_name === '未指定' ? '' : ` · ${row.server_name}`); return option;
    }));
    select.value = selected;
    document.querySelector('#game-account-hint').textContent = rows.length ? '請選擇這張碎片長圖所屬的遊戲帳號。' : '你還沒有遊戲帳號，請先新增一個；可以新增多個帳號。';
    await showFragments();
  }
  select.addEventListener('change', showFragments);
  form.addEventListener('submit', async event => {
    event.preventDefault(); error.hidden = true;
    const button = form.querySelector('button'); button.disabled = true;
    try {
      const item = await api('/api/game-accounts', Object.fromEntries(new FormData(form)));
      await load(item.id); form.reset(); manager.querySelector('details').open = false;
    } catch (problem) { error.textContent = problem.message; error.hidden = false; }
    finally { button.disabled = false; }
  });
  load().catch(problem => { error.textContent = problem.message; error.hidden = false; select.replaceChildren(); });
})();
