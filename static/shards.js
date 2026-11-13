'use strict';
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const csrf = $('meta[name="csrf-token"]').content;
let role = 'user', catalog = [], job = null, selectedFile = null, polling = null;
let catalogWritable = true;
let mockMode = true, fragmentTotals = {};
let filter = 'all', rarity = 'all', selectedPortrait = '', portraitFile = null, deletingId = null;
let targetFilter = 'all';
let toastTimer, uploading = false;
const rarityLabels = {SSR: 'SSR', SP: 'SP', UR: 'UR', COLLAB: '聯動式神'};
function node(tag, cls, text) {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  if (text !== undefined) element.textContent = text;
  return element;
}
function toast(text) {
  clearTimeout(toastTimer); $('#shards-toast').textContent = text; $('#shards-toast').hidden = false;
  toastTimer = setTimeout(() => { $('#shards-toast').hidden = true; }, 4500);
}
async function api(path, body) {
  const options = {headers: {'X-CSRF-Token': csrf}};
  if (body !== undefined) {
    options.method = 'POST';
    if (body instanceof FormData) options.body = body;
    else { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
  }
  let response;
  try { response = await fetch(path, options); }
  catch { throw new Error('連線中斷，請檢查網路後重試。'); }
  let result;
  try { result = await response.json(); }
  catch { throw new Error('伺服器暫時無法回應，請稍後重試。'); }
  if (!response.ok) throw new Error(response.status === 413 ? '檔案太大，請選擇小於 12 MB 的圖片。' : result.error || '操作未完成，請重試。');
  return result;
}
function tab(name) {
  $$('.tab-panel').forEach(panel => { panel.hidden = panel.id !== `panel-${name}`; });
  $$('.rail-item').forEach(button => button.classList.toggle('active', button.dataset.tab === name));
  $('#crumb-current').textContent = {upload: '匯入碎片', review: '識別與核對', catalog: '式神圖鑑'}[name];
  if (name === 'review') renderJob();
  if (name === 'catalog') loadCatalog().catch(error => toast(error.message));
  window.scrollTo({top: 0, behavior: 'instant'});
}
$$('[data-tab]').forEach(button => button.addEventListener('click', () => tab(button.dataset.tab)));
$('#return-upload').addEventListener('click', () => tab('upload'));
$('#password-reminder-close').addEventListener('click',()=>$('#password-reminder').hidden=true);
function setRole() {
  $('#role-select').value = role; $('#user-circle').textContent = role === 'admin' ? '管' : '友';
  $('#add-shikigami').hidden = role !== 'admin';
  if (!mockMode) {
    $('#add-shikigami').hidden = !catalogWritable;
    $('#role-select').closest('.role-control').hidden = true;
    $('#catalog-notice').textContent = role === 'admin' ? 'Admin：可新增、編輯圖鑑，並審核头像參考。統計為全站現有數量。' : '點擊式神头像查看誰可提供、誰需要。統計為全站現有數量。';
    renderCatalog();
    return;
  }
  $('#catalog-notice').textContent = role === 'admin' ? 'Admin 演示身分：可新增、編輯、刪除式神與上傳肖像。內容僅保存在本機 Mock 圖鑑，不會改動資料庫。' : '一般用戶：可查看式神圖鑑、上傳長圖與核對碎片。管理圖鑑請使用右上方的 Admin 演示身分。';
  renderCatalog();
}
$('#role-select').addEventListener('change', async event => {
  const select = event.target; select.disabled = true;
  try { role = (await api('/api/shards/role', {role: select.value})).role; setRole(); toast(`已切換為 ${role === 'admin' ? 'Admin' : '一般用戶'} 演示身分。`); }
  catch (error) { toast(error.message); select.value = role; }
  finally { select.disabled = false; }
});
async function loadCatalog() {
  catalog = await api('/api/shards/catalog');
  if(!mockMode)fragmentTotals=await api('/api/fragments/totals');
  $('#nav-catalog-count').textContent = String(catalog.length).padStart(2, '0'); renderCatalog();
}
function renderCatalog() {
  const search = $('#catalog-search').value.trim().toLocaleLowerCase();
  const records = catalog.filter(item => (rarity === 'all' || item.rarity === rarity) && [item.name,item.name_simplified||'', ...item.aliases].join(' ').toLocaleLowerCase().includes(search));
  if (!records.length) {
    const empty = node('div', 'empty-state paper'); empty.append(node('span', '', '✳'), node('h2', '', '這一頁圖鑑，還等著補上名字'), node('p', '', catalogWritable ? '換個關鍵字，或切換 Admin 新增一位式神。' : '沒有符合的啟用式神，請檢查篩選條件或 Supabase 資料。')); $('#catalog-grid').replaceChildren(empty); return;
  }
  $('#catalog-grid').replaceChildren(...records.map((item, index) => {
    const card = node('article', 'catalog-card'), head = node('div', 'catalog-card-head');
    head.append(node('span', `tag ${item.rarity}`, rarityLabels[item.rarity]), node('span', 'catalog-number', item.display_order == null ? '未編號' : `#${String(item.display_order).padStart(3, '0')}`));
    const avatar = node('button', 'catalog-avatar');avatar.type='button';avatar.setAttribute('aria-label',`查看${item.name}的碎片`);
    if(!mockMode)avatar.addEventListener('click',()=>showFragmentOwners(item));
    if (item.image) { const img = node('img'); img.src = item.image; img.alt = item.name; img.loading = 'lazy'; img.referrerPolicy = 'no-referrer'; avatar.append(img); }
    else avatar.append(node('span', '', item.name.slice(0, 1)), node('small', '', '肖像待補'));
    card.append(head, avatar, node('h3', '', item.name), node('p', 'catalog-aliases', item.aliases.length ? `識別別名：${item.aliases.join('、')}` : '使用正式名字辨識'));
    if(!mockMode){const totals=fragmentTotals[item.id]||{};card.append(node('p','catalog-aliases',`可提供 ${totals.offers||0} · 想要 ${totals.wants||0}`));if(totals.offers_reserved)card.append(node('p','catalog-aliases',`交換中已預留 ${totals.offers_reserved}`));}
    if (catalogWritable && role === 'admin') {
      const actions = node('div', 'catalog-actions'), edit = node('button', 'subtle', '編輯資料 ↗'), remove = node('button', 'subtle delete-link', '刪除');
      edit.addEventListener('click', () => openCatalog(item));
      remove.addEventListener('click', () => { deletingId = item.id; $('#delete-description').textContent = mockMode ? `「${item.name}」將從本機 Mock 圖鑑移除。` : `「${item.name}」將停用，歷史記錄會保留。`; $('#delete-dialog').showModal(); });
      actions.append(edit, remove); card.append(actions);
    }
    return card;
  }));
}
$('#catalog-search').addEventListener('input', renderCatalog);
$$('#rarity-filters button').forEach(button => button.addEventListener('click', () => {
  rarity = button.dataset.rarity; $$('#rarity-filters button').forEach(b => b.classList.toggle('active', b === button)); renderCatalog();
}));
function previewPortrait(value) {
  $('#portrait-preview').hidden = !value; $('#portrait-placeholder').hidden = !!value;
  if (value) $('#portrait-preview').src = value; else $('#portrait-preview').removeAttribute('src');
}
async function openCatalog(item = null) {
  $('#catalog-form').reset(); $('#catalog-id').value = item?.id || '';
  $('#catalog-name').value = item?.name || ''; $('#catalog-rarity').value = item?.rarity || 'SSR';
  $('#catalog-simple').value=item?.name_simplified||'';
  $('#catalog-order').value=item?.display_order??Math.max(0,...catalog.map(r=>r.display_order||0))+1;
  if(!item&&!mockMode){try{$('#catalog-order').value=(await api('/api/shards/catalog/next-order')).display_order;}catch(error){toast(error.message);return;}}
  $('#catalog-image-path').value=item?.image||'';
  $$('.real-catalog-field').forEach(el=>el.hidden=mockMode);$('#catalog-simple').required=!mockMode;
  $('.portrait-editor').hidden=!mockMode;
  $('#catalog-save-location').textContent=mockMode?'保存至本機 Mock 圖鑑':'保存至 Supabase';
  $('#catalog-aliases').value = item?.aliases.join('\n') || ''; selectedPortrait = item?.image || ''; portraitFile = null;
  previewPortrait(selectedPortrait); $('#catalog-error').hidden = true;
  $('#catalog-dialog-title').textContent = item ? '編輯式神' : '新增式神'; $('#catalog-dialog').showModal();
}
$('#add-shikigami').addEventListener('click', () => openCatalog());
$('#close-catalog').addEventListener('click', () => $('#catalog-dialog').close());
$('#portrait-file').addEventListener('change', event => {
  const file = event.target.files[0]; if (!file) return;
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 12 * 1024 * 1024) return toast('請選擇 12 MB 內的 PNG、JPG 或 WebP 肖像。');
  portraitFile = file; const reader = new FileReader(); reader.onload = () => previewPortrait(reader.result); reader.readAsDataURL(file);
});
$('#remove-portrait').addEventListener('click', () => { selectedPortrait = ''; portraitFile = null; $('#portrait-file').value = ''; previewPortrait(''); });
$('#catalog-form').addEventListener('submit', async event => {
  event.preventDefault(); $('#save-catalog').disabled = true; $('#catalog-error').hidden = true;
  try {
    if (portraitFile) { const data = new FormData(); data.append('image', portraitFile); selectedPortrait = (await api('/api/shards/portraits', data)).image; portraitFile = null; }
    const id = $('#catalog-id').value;
    await api(`/api/shards/catalog${id ? `/${id}` : ''}`, {name: $('#catalog-name').value.trim(), rarity: $('#catalog-rarity').value,
      name_simplified:$('#catalog-simple').value.trim(),display_order:$('#catalog-order').value?Number($('#catalog-order').value):null,
      ...(!mockMode?{image_path:$('#catalog-image-path').value.trim()}:{}),
      aliases: $('#catalog-aliases').value.split(/\r?\n/).map(s => s.trim()).filter(Boolean), image: selectedPortrait});
    await loadCatalog(); $('#catalog-dialog').close(); if (job?.status === 'done') renderRows(); toast('式神圖鑑已儲存。');
  } catch (error) { $('#catalog-error').textContent = error.message; $('#catalog-error').hidden = false; }
  finally { $('#save-catalog').disabled = false; }
});
$('#cancel-delete').addEventListener('click', () => $('#delete-dialog').close());
$('#confirm-delete').addEventListener('click', async () => {
  $('#confirm-delete').disabled = true;
  try { await api(`/api/shards/catalog/${deletingId}/delete`, {}); await loadCatalog(); $('#delete-dialog').close(); toast('圖鑑已更新。'); }
  catch (error) { toast(error.message); }
  finally { $('#confirm-delete').disabled = false; }
});
function chooseFile(file) {
  if (!file) return;
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) return toast('請上傳 PNG、JPG 或 WebP 圖片。');
  if (file.size > 12 * 1024 * 1024) return toast('圖片太大，請選擇 12 MB 內的原圖。');
  selectedFile = file; $('#selected-file').hidden = false; $('#file-name').textContent = file.name;
  $('#file-size').textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB · 圖片將在伺服器本地處理`;
  $('#analyze-button').disabled = uploading; $('#upload-error').hidden = true;
}
$('#dropzone').addEventListener('click', () => $('#screenshot-file').click());
$('#dropzone').addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); $('#screenshot-file').click(); } });
$('#screenshot-file').addEventListener('change', event => chooseFile(event.target.files[0]));
$('#clear-file').addEventListener('click', () => { selectedFile = null; $('#screenshot-file').value = ''; $('#selected-file').hidden = true; $('#analyze-button').disabled = true; });
$('#dropzone').addEventListener('dragover', event => { event.preventDefault(); $('#dropzone').classList.add('dragging'); });
$('#dropzone').addEventListener('dragleave', () => $('#dropzone').classList.remove('dragging'));
$('#dropzone').addEventListener('drop', event => { event.preventDefault(); $('#dropzone').classList.remove('dragging'); chooseFile(event.dataTransfer.files[0]); });
function acceptJob(data) {
  clearTimeout(polling); job = data; filter = 'all';
  targetFilter = 'all';
  $$('#target-filters button').forEach(b => b.classList.toggle('active', b.dataset.target === 'all'));
  $$('#review-filters button').forEach(b => b.classList.toggle('active', b.dataset.filter === filter));
  try { sessionStorage.setItem('shards-job', job.id); } catch {}
  tab('review'); if (['queued', 'processing'].includes(job.status)) pollJob(job.id);
}
$('#analyze-button').addEventListener('click', async () => {
  if (!selectedFile || uploading) return;
  const gameAccountId = $('#game-account-select')?.value;
  if (!mockMode && !gameAccountId) return toast('請先新增並選擇這張圖所屬的遊戲帳號。');
  uploading = true; $('#analyze-button').disabled = $('#demo-button').disabled = true;
  try {
    const data = new FormData(); data.append('image', selectedFile);
    if (gameAccountId) data.append('game_account_id', gameAccountId);
    if ($('#manual-grid').checked) { data.append('manual', '1'); for (const key of ['columns', 'rows', 'left', 'top', 'right', 'bottom']) data.append(key, $(`#grid-${key}`).value); }
    acceptJob(await api('/api/shards/uploads', data));
  } catch (error) { $('#upload-error').textContent = error.message; $('#upload-error').hidden = false; }
  finally { uploading = false; $('#analyze-button').disabled = !selectedFile; $('#demo-button').disabled = false; }
});
$('#demo-button').addEventListener('click', async () => {
  if (uploading) return; $('#demo-button').disabled = true;
  try { acceptJob(await api('/api/shards/demo', {})); }
  catch (error) { toast(error.message); }
  finally { $('#demo-button').disabled = false; }
});
function pollJob(id) {
  polling = setTimeout(async () => {
    try {
      const current = await api(`/api/shards/jobs/${id}`);
      if (job?.id !== id) return;
      job = current; renderJob();
      if (['queued', 'processing'].includes(job.status)) pollJob(id);
      else if (job.status === 'done') toast(`已定位 ${job.rows.length} 張卡片，接下來請核對名字與數量。`);
    } catch (error) { toast(error.message); }
  }, 1300);
}
function renderJob() {
  $('#review-empty').hidden = !!job; $('#review-content').hidden = !job; if (!job) return;
  $('#job-filename').textContent = job.filename; $('#job-meta').textContent = `${job.width} × ${job.height} px · ${job.game_account ? `遊戲帳號：${job.game_account.nickname} · ` : ''}${job.database_written ? '已保存至帳號' : '待核對，尚未保存'}`;
  $('#save-import-button').hidden = !job.game_account || job.source === 'demo';
  $('#save-import-button').disabled = job.database_written || job.status !== 'done';
  $('#save-note').textContent = job.database_written ? '這份清單已保存。可在遊戲帳號頁查看；修正數量請重新上傳。' : job.game_account ? `核對完成後保存到「${job.game_account.nickname}」。記錄數量，不會自動加入交換提供清單。` : '此為演示資料，只能匯出，不會寫入遊戲帳號。';
  $('#source-tag').textContent = job.source === 'demo' ? 'DEMO · 預設結果' : '本地圖片處理';
  $('#job-progress').hidden = !['queued', 'processing'].includes(job.status);
  $('#progress-label').textContent = job.total ? `已處理 ${job.progress} / ${job.total} 張卡片，請稍候…` : '正在定位卡片與載入模型。首次 OCR 可能需要下載模型，請保留此頁面。';
  $('#progress-bar').value = job.total ? job.progress / job.total * 100 : 5;
  $('#job-warning').hidden = !job.warning; $('#job-warning').textContent = job.warning;
  $('#job-warning').className = `inline-message${job.status === 'failed' ? ' error' : ''}`;
  $('#results-area').hidden = job.status !== 'done';
  $('#nav-review-count').textContent = job.status === 'done' ? job.rows.length : '…';
  if (job.status === 'done') renderRows();
}
function updateStats() {
  const rows = job?.rows || [];
  $('#stat-total').textContent = rows.length;
  $('#stat-review').textContent = rows.filter(r => r.included && (!r.shikigami_id || r.quantity === null || r.target === 'unknown' || r.needs_review) && !r.confirmed).length;
  $('#target-summary').textContent = `可提供 ${rows.filter(r => (r.target || 'offers') === 'offers').length} 項 · 想要 ${rows.filter(r => r.target === 'wants').length} 項 · 待分類 ${rows.filter(r => r.target === 'unknown').length} 項`;
  $('#stat-confirmed').textContent = rows.filter(r => r.included && r.confirmed && !r.dirty).length;
  $('#stat-quantity').textContent = rows.filter(r => r.included && r.confirmed && !r.dirty).reduce((sum, r) => sum + r.quantity, 0).toLocaleString();
}
function rowStatus(row) {
  if (!row.included) return ['neutral', '已排除'];
  if (row.dirty) return ['warning', '尚未儲存'];
  if (row.confirmed) return ['good', '已確認'];
  if (row.target === 'unknown') return ['warning', '待確認分類'];
  if (!row.shikigami_id) return ['red', '待選式神'];
  if (row.quantity === null) return ['warning', '待填數量'];
  return ['warning', row.needs_review ? '建議再看一眼' : '已配對 · 待確認'];
}
function renderRows() {
  if (!job || job.status !== 'done') return;
  updateStats();
  const records = job.rows.filter(row => (targetFilter === 'all' || (row.target || 'offers') === targetFilter) &&
    (filter === 'all' || (filter === 'pending' && row.included && !row.confirmed) || (filter === 'confirmed' && row.included && row.confirmed) || (filter === 'excluded' && !row.included)));
  $('#review-rows').replaceChildren(...records.map(row => {
    const tr = node('tr', row.included ? '' : 'excluded'); tr.dataset.rowId = row.id;
    const cropCell = node('td'), crop = node('button', 'crop-button');
    const image = node('img'); image.src = row.crop; image.alt = `第 ${row.index} 格原圖裁切`; crop.append(image, node('span', '', String(row.index).padStart(3, '0')));
    crop.addEventListener('click', () => showOriginal(row.crop)); cropCell.append(crop);
    const raw = node('td'); raw.append(node('span', 'ocr-name', row.raw_name || '未讀出名字'), node('span', 'ocr-quantity', `數量原文：${row.raw_quantity || '未讀出'}`), node('span', 'score-note', `OCR 分數 ${row.name_confidence.toFixed(2)} / ${row.quantity_confidence.toFixed(2)}`));
    const purpose = node('select', 'review-select'); purpose.setAttribute('aria-label', `第 ${row.index} 格碎片分類`);
    for (const [value,label] of [['unknown','請確認分類…'],['offers','可提供的碎片'],['wants','我想要的碎片']]) {
      const option = node('option', '', label); option.value = value; purpose.append(option);
    }
    purpose.value = row.target || 'offers'; purpose.disabled = !row.included || job.database_written;
    raw.append(purpose);
    if (row.quantity === null && row.quantity_readings?.length) {
      const readings = [...new Set(row.quantity_readings.map(item => item.raw).filter(Boolean))];
      raw.append(node('small', 'suggestion-note', `數量未達一致，請看原圖：${readings.join(' / ') || '未讀出'}`));
    }
    const target = node('td'), select = node('select', 'review-select'); select.setAttribute('aria-label', `第 ${row.index} 格對應式神`);
    const empty = node('option', '', '請選擇式神…'); empty.value = ''; select.append(empty);
    catalog.forEach(item => { const option = node('option', '', `${item.name} · ${rarityLabels[item.rarity]}`); option.value = item.id; select.append(option); });
    select.value = row.shikigami_id || ''; select.disabled = !row.included; target.append(select);
    const picker=ShikigamiPicker.attach(select,catalog);picker.disabled=!row.included||job.database_written;
    select.disabled ||= job.database_written;
    if (!row.shikigami_id && row.suggestions.length) target.append(node('small', 'suggestion-note', `候選：${row.suggestions.map(s => s.name).join('、')}`));
    if(row.visual_candidates?.length){
      const candidates=row.visual_candidates.map(v=>`${catalog.find(c=>c.id===v.id)?.name||'未知'} ${Math.round(v.score*100)}分`);
      target.append(node('small','suggestion-note',`${row.visual_conflict?'头像與名字不一致，請核對':'头像參考候選'}：${candidates.join('、')}`));
    }
    const qtyCell = node('td'), quantity = node('input', 'quantity-input'); quantity.type = 'number'; quantity.min = '0'; quantity.max = '99999'; quantity.step = '1'; quantity.placeholder = '待核對'; quantity.value = row.quantity ?? ''; quantity.inputMode = 'numeric'; quantity.disabled = !row.included; quantity.setAttribute('aria-label', `第 ${row.index} 格碎片數量`); qtyCell.append(quantity);
    const statusCell = node('td'), [style, label] = rowStatus(row), badge = node('span', `tag ${style}`, label); statusCell.append(badge);
    quantity.disabled ||= job.database_written;
    const actionsCell = node('td'), actions = node('div', 'row-actions'), confirm = node('button', 'btn secondary small', row.confirmed ? '重新確認' : '確認這一項'), exclude = node('button', 'subtle', row.included ? '排除此項' : '恢復此項');
    confirm.disabled = !row.included; actions.append(confirm, exclude); actionsCell.append(actions);
    if (job.database_written) confirm.disabled = exclude.disabled = true;
    function dirty() { row.target = purpose.value; row.shikigami_id = select.value || null; row.quantity = quantity.value === '' ? null : Number(quantity.value); row.dirty = true; row.confirmed = false; const [cls, text] = rowStatus(row); badge.className = `tag ${cls}`; badge.textContent = text; updateStats(); }
    purpose.addEventListener('change', dirty);
    select.addEventListener('change', dirty); quantity.addEventListener('input', dirty);
    async function save(included, confirmed) {
      confirm.disabled = exclude.disabled = true;
      try {
        const saved = await api(`/api/shards/jobs/${job.id}/rows/${row.id}`, {target:purpose.value, shikigami_id: select.value || null, quantity: quantity.value === '' ? null : Number(quantity.value), included, confirmed});
        job.rows[job.rows.findIndex(r => r.id === row.id)] = saved; renderRows();
      } catch (error) { toast(error.message); confirm.disabled = !row.included; exclude.disabled = false; }
    }
    confirm.addEventListener('click', () => save(true, true));
    exclude.addEventListener('click', () => save(!row.included, false));
    tr.append(cropCell, raw, target, qtyCell, statusCell, actionsCell); return tr;
  }));
  if (!records.length) { const tr = node('tr'), td = node('td', '', '這個篩選下沒有條目。'); td.colSpan = 6; tr.append(td); $('#review-rows').append(tr); }
}
$$('#review-filters button').forEach(button => button.addEventListener('click', () => { filter = button.dataset.filter; $$('#review-filters button').forEach(b => b.classList.toggle('active', b === button)); renderRows(); }));
$$('#target-filters button').forEach(button => button.addEventListener('click', () => { targetFilter = button.dataset.target; $$('#target-filters button').forEach(b => b.classList.toggle('active', b === button)); renderRows(); }));
function showOriginal(src) { $('#original-image').src = src; $('#original-dialog').showModal(); }
$('#show-original').addEventListener('click', () => { if (job) showOriginal(job.image_url); });
$('#close-original').addEventListener('click', () => $('#original-dialog').close());
$('#export-button').addEventListener('click', async () => {
  const rows = job.rows.filter(row => row.included);
  if (!rows.length || rows.some(row => !row.confirmed || row.dirty)) return toast('請先逐項確認要匯出的資料，或排除不需要的條目。');
  $('#export-button').disabled = true;
  try {
    const response = await fetch(`/api/shards/jobs/${job.id}/export`);
    if (!response.ok) throw new Error((await response.json()).error || '匯出未完成。');
    const url = URL.createObjectURL(await response.blob()), anchor = node('a'); anchor.href = url; anchor.download = 'shards-reviewed.json'; document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1500); toast('已匯出核對清單。');
  } catch (error) { toast(error.message); }
  finally { $('#export-button').disabled = false; }
});
$('#save-import-button').addEventListener('click', async () => {
  const rows = job?.rows.filter(row => row.included) || [];
  if (!rows.length || rows.some(row => !row.confirmed || row.dirty)) return toast('請先確認所有保留條目，並儲存你的修改。');
  $('#save-import-button').disabled = true;
  try {
    await api(`/api/shards/jobs/${job.id}/save`, {});
    job.database_written = true; renderJob(); toast(`清單已保存到「${job.game_account.nickname}」。`);
  } catch (error) { toast(error.message); $('#save-import-button').disabled = false; }
});
async function showFragmentOwners(item){
  let dialog=$('#fragment-owners-dialog');
  if(!dialog){dialog=node('dialog');dialog.id='fragment-owners-dialog';const close=node('button','關閉');close.type='button';close.onclick=()=>dialog.close();dialog.append(close,node('h2'),node('div','owners-content'));document.body.append(dialog);}
  $('h2',dialog).textContent=item.name;const content=$('.owners-content',dialog);content.textContent='載入中…';dialog.showModal();
  try{
    const rows=await api('/api/fragments?shikigami_id='+item.id);content.replaceChildren();
    for(const [target,title] of [['offers','誰可提供'],['wants','誰需要']]){
      content.append(node('h3','',title));const list=node('ul');const entries=rows.filter(r=>r.target===target);
      for(const r of entries)list.append(node('li','',`${r.player_name} · ${r.nickname} · ${r.server_name}：${r.quantity}`));
      if(!entries.length)list.append(node('li','','尚無記錄'));content.append(list);
    }
    const link=node('a','','到搜索頁查看');link.href='/search-fragments?shikigami_id='+item.id;content.append(link);
    const trades=await api('/api/trades?shikigami_id='+item.id);content.append(node('h3','','誰正在交換'));
    const ongoing=node('ul');for(const trade of trades)ongoing.append(node('li','',`${trade.requester_name} · ${trade.requester_account_name} ↔ ${trade.recipient_name} · ${trade.recipient_account_name}`));
    if(!trades.length)ongoing.append(node('li','','目前沒有交換中記錄'));content.append(ongoing);
  }catch(error){content.textContent=error.message;}
}
async function init() {
  try {
    const info = await api('/api/shards/session'); role = info.role;
    mockMode=info.catalog_source==='mock';
    catalogWritable = info.catalog_writable !== false;
    if (!mockMode) {
      $('#account-link').textContent = info.authenticated ? `${info.display_name} · 我的帳號` : '登入 / 我的帳號';
      $('#login-notice').hidden = info.authenticated;
      $('#password-reminder').hidden=info.password_set!==false;
      $('.mock-pill').textContent = 'SUPABASE';
      $('.mock-banner p').textContent = '式神圖鑑與遊戲帳號已連接 Supabase。選擇遊戲帳號上傳碎片，逐項核對後再保存；演示結果不會寫入帳號。';
      $('#panel-catalog .small-note').textContent = '資料來源：onmyoji_shards.shikigami。圖片使用 image_path 的 HTTPS 網址；未提供圖片會顯示文字佔位。';
      $('#sample-admin-link').hidden=role!=='admin';
    }
    $('#engine-status').textContent = info.ocr_installed ? '本地 OCR 已安裝 · 首次需載入模型' : 'OpenCV 切格可用 · OCR 為可選安裝';
    await loadCatalog(); setRole();
    if (location.hash === '#catalog') tab('catalog');
    let id; try { id = sessionStorage.getItem('shards-job'); } catch {}
    if (id && /^[a-f0-9-]{36}$/.test(id)) {
      try { job = await api(`/api/shards/jobs/${id}`); renderJob(); if (['queued', 'processing'].includes(job.status)) pollJob(id); }
      catch { try { sessionStorage.removeItem('shards-job'); } catch {} }
    }
  } catch (error) { toast(error.message); $('#engine-status').textContent = '暫時無法連線'; }
}
init();
