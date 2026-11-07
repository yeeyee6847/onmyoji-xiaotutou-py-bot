'use strict';
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const csrf = $('meta[name="csrf-token"]').content;
let role = 'user', catalog = [], job = null, selectedFile = null, polling = null;
let filter = 'all', rarity = 'all', selectedPortrait = '', portraitFile = null, deletingId = null;
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
  if (name === 'catalog') renderCatalog();
  window.scrollTo({top: 0, behavior: 'instant'});
}
$$('[data-tab]').forEach(button => button.addEventListener('click', () => tab(button.dataset.tab)));
$('#return-upload').addEventListener('click', () => tab('upload'));
function setRole() {
  $('#role-select').value = role; $('#user-circle').textContent = role === 'admin' ? '管' : '友';
  $('#add-shikigami').hidden = role !== 'admin';
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
  catalog = await api('/api/shards/catalog'); $('#nav-catalog-count').textContent = String(catalog.length).padStart(2, '0'); renderCatalog();
}
function renderCatalog() {
  const search = $('#catalog-search').value.trim().toLocaleLowerCase();
  const records = catalog.filter(item => (rarity === 'all' || item.rarity === rarity) && [item.name, ...item.aliases].join(' ').toLocaleLowerCase().includes(search));
  if (!records.length) {
    const empty = node('div', 'empty-state paper'); empty.append(node('span', '', '✳'), node('h2', '', '這一頁圖鑑，還等著補上名字'), node('p', '', '換個關鍵字，或切換 Admin 新增一位式神。')); $('#catalog-grid').replaceChildren(empty); return;
  }
  $('#catalog-grid').replaceChildren(...records.map((item, index) => {
    const card = node('article', 'catalog-card'), head = node('div', 'catalog-card-head');
    head.append(node('span', `tag ${item.rarity}`, rarityLabels[item.rarity]), node('span', 'catalog-number', `ARCHIVE ${String(index + 1).padStart(3, '0')}`));
    const avatar = node('div', 'catalog-avatar');
    if (item.image) { const img = node('img'); img.src = item.image; img.alt = item.name; img.loading = 'lazy'; avatar.append(img); }
    else avatar.append(node('span', '', item.name.slice(0, 1)), node('small', '', '肖像待補'));
    card.append(head, avatar, node('h3', '', item.name), node('p', 'catalog-aliases', item.aliases.length ? `識別別名：${item.aliases.join('、')}` : '使用正式名字辨識'));
    if (role === 'admin') {
      const actions = node('div', 'catalog-actions'), edit = node('button', 'subtle', '編輯資料 ↗'), remove = node('button', 'subtle delete-link', '刪除');
      edit.addEventListener('click', () => openCatalog(item));
      remove.addEventListener('click', () => { deletingId = item.id; $('#delete-description').textContent = `「${item.name}」將從本機 Mock 圖鑑移除，尚未匯出的對應條目需要重新核對。`; $('#delete-dialog').showModal(); });
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
function openCatalog(item = null) {
  $('#catalog-form').reset(); $('#catalog-id').value = item?.id || '';
  $('#catalog-name').value = item?.name || ''; $('#catalog-rarity').value = item?.rarity || 'SSR';
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
      aliases: $('#catalog-aliases').value.split(/\r?\n/).map(s => s.trim()).filter(Boolean), image: selectedPortrait});
    await loadCatalog(); $('#catalog-dialog').close(); if (job?.status === 'done') renderRows(); toast('式神圖鑑已儲存至本機 Mock 資料。');
  } catch (error) { $('#catalog-error').textContent = error.message; $('#catalog-error').hidden = false; }
  finally { $('#save-catalog').disabled = false; }
});
$('#cancel-delete').addEventListener('click', () => $('#delete-dialog').close());
$('#confirm-delete').addEventListener('click', async () => {
  $('#confirm-delete').disabled = true;
  try { await api(`/api/shards/catalog/${deletingId}/delete`, {}); await loadCatalog(); $('#delete-dialog').close(); toast('已從 Mock 圖鑑移除。'); }
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
  $$('#review-filters button').forEach(b => b.classList.toggle('active', b.dataset.filter === filter));
  try { sessionStorage.setItem('shards-job', job.id); } catch {}
  tab('review'); if (['queued', 'processing'].includes(job.status)) pollJob(job.id);
}
$('#analyze-button').addEventListener('click', async () => {
  if (!selectedFile || uploading) return; uploading = true; $('#analyze-button').disabled = $('#demo-button').disabled = true;
  try {
    const data = new FormData(); data.append('image', selectedFile);
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
  $('#job-filename').textContent = job.filename; $('#job-meta').textContent = `${job.width} × ${job.height} px · ${job.source === 'demo' ? '預設演示資料' : '你的原始長圖'} · 不寫入資料庫`;
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
  $('#stat-review').textContent = rows.filter(r => r.included && (!r.shikigami_id || r.quantity === null || r.needs_review) && !r.confirmed).length;
  $('#stat-confirmed').textContent = rows.filter(r => r.included && r.confirmed && !r.dirty).length;
  $('#stat-quantity').textContent = rows.filter(r => r.included && r.confirmed && !r.dirty).reduce((sum, r) => sum + r.quantity, 0).toLocaleString();
}
function rowStatus(row) {
  if (!row.included) return ['neutral', '已排除'];
  if (row.dirty) return ['warning', '尚未儲存'];
  if (row.confirmed) return ['good', '已確認'];
  if (!row.shikigami_id) return ['red', '待選式神'];
  if (row.quantity === null) return ['warning', '待填數量'];
  return ['warning', row.needs_review ? '建議再看一眼' : '已配對 · 待確認'];
}
function renderRows() {
  if (!job || job.status !== 'done') return;
  updateStats();
  const records = job.rows.filter(row => filter === 'all' || (filter === 'pending' && row.included && !row.confirmed) || (filter === 'confirmed' && row.included && row.confirmed) || (filter === 'excluded' && !row.included));
  $('#review-rows').replaceChildren(...records.map(row => {
    const tr = node('tr', row.included ? '' : 'excluded'); tr.dataset.rowId = row.id;
    const cropCell = node('td'), crop = node('button', 'crop-button');
    const image = node('img'); image.src = row.crop; image.alt = `第 ${row.index} 格原圖裁切`; crop.append(image, node('span', '', String(row.index).padStart(3, '0')));
    crop.addEventListener('click', () => showOriginal(row.crop)); cropCell.append(crop);
    const raw = node('td'); raw.append(node('span', 'ocr-name', row.raw_name || '未讀出名字'), node('span', 'ocr-quantity', `數量原文：${row.raw_quantity || '未讀出'}`), node('span', 'score-note', `OCR 分數 ${row.name_confidence.toFixed(2)} / ${row.quantity_confidence.toFixed(2)}`));
    const target = node('td'), select = node('select', 'review-select'); select.setAttribute('aria-label', `第 ${row.index} 格對應式神`);
    const empty = node('option', '', '請選擇式神…'); empty.value = ''; select.append(empty);
    catalog.forEach(item => { const option = node('option', '', `${item.name} · ${rarityLabels[item.rarity]}`); option.value = item.id; select.append(option); });
    select.value = row.shikigami_id || ''; select.disabled = !row.included; target.append(select);
    if (!row.shikigami_id && row.suggestions.length) target.append(node('small', 'suggestion-note', `候選：${row.suggestions.map(s => s.name).join('、')}`));
    const qtyCell = node('td'), quantity = node('input', 'quantity-input'); quantity.type = 'number'; quantity.min = '0'; quantity.max = '99999'; quantity.step = '1'; quantity.placeholder = '待核對'; quantity.value = row.quantity ?? ''; quantity.inputMode = 'numeric'; quantity.disabled = !row.included; quantity.setAttribute('aria-label', `第 ${row.index} 格碎片數量`); qtyCell.append(quantity);
    const statusCell = node('td'), [style, label] = rowStatus(row), badge = node('span', `tag ${style}`, label); statusCell.append(badge);
    const actionsCell = node('td'), actions = node('div', 'row-actions'), confirm = node('button', 'btn secondary small', row.confirmed ? '重新確認' : '確認這一項'), exclude = node('button', 'subtle', row.included ? '排除此項' : '恢復此項');
    confirm.disabled = !row.included; actions.append(confirm, exclude); actionsCell.append(actions);
    function dirty() { row.shikigami_id = select.value || null; row.quantity = quantity.value === '' ? null : Number(quantity.value); row.dirty = true; row.confirmed = false; const [cls, text] = rowStatus(row); badge.className = `tag ${cls}`; badge.textContent = text; updateStats(); }
    select.addEventListener('change', dirty); quantity.addEventListener('input', dirty);
    async function save(included, confirmed) {
      confirm.disabled = exclude.disabled = true;
      try {
        const saved = await api(`/api/shards/jobs/${job.id}/rows/${row.id}`, {shikigami_id: select.value || null, quantity: quantity.value === '' ? null : Number(quantity.value), included, confirmed});
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
    const url = URL.createObjectURL(await response.blob()), anchor = node('a'); anchor.href = url; anchor.download = 'shards-reviewed.json'; document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1500); toast('已匯出 Mock 清單，沒有寫入資料庫。');
  } catch (error) { toast(error.message); }
  finally { $('#export-button').disabled = false; }
});
async function init() {
  try {
    const info = await api('/api/shards/session'); role = info.role;
    $('#engine-status').textContent = info.ocr_installed ? '本地 OCR 已安裝 · 首次需載入模型' : 'OpenCV 切格可用 · OCR 為可選安裝';
    await loadCatalog(); setRole();
    let id; try { id = sessionStorage.getItem('shards-job'); } catch {}
    if (id && /^[a-f0-9-]{36}$/.test(id)) {
      try { job = await api(`/api/shards/jobs/${id}`); renderJob(); if (['queued', 'processing'].includes(job.status)) pollJob(id); }
      catch { try { sessionStorage.removeItem('shards-job'); } catch {} }
    }
  } catch (error) { toast(error.message); $('#engine-status').textContent = '暫時無法連線'; }
}
init();
