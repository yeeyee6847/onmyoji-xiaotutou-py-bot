'use strict';
const $ = (selector, scope = document) => scope.querySelector(selector);
const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];
const csrf = $('meta[name="csrf-token"]').content;
const form = $('#setup-form');
let draw = null;
let editingDraw = null;
let view = 'setup';
let networkBusy = false;
let observer = null;
let toastTimer;
const modeNames = {elimination: '淘汰式 · 留到最後', instant: '即中式 · 一刮就中'};
const statusNames = {ready: '等待開場', active: '抽獎進行中', completed: '已揭曉'};

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function toast(message) {
  clearTimeout(toastTimer);
  $('#toast').textContent = message;
  $('#toast').hidden = false;
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4800);
}
async function api(path, body) {
  const options = {headers: {'X-CSRF-Token': csrf}};
  if (body !== undefined) {
    options.method = 'POST';
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let response;
  try { response = await fetch(path, options); }
  catch { throw new Error('連線中斷，請檢查網路並重試；正式抽獎的進度會保留。'); }
  let data;
  try { data = await response.json(); }
  catch { throw new Error('伺服器暫時無法回應，請稍後重試。'); }
  if (!response.ok) throw new Error(data.error || '操作未完成，請重試。');
  return data;
}
function showView(next) {
  if (next === 'setup' && view !== 'setup') {
    if (draw && !draw.practice) openEditor(draw);
    else if (editingDraw) openEditor(editingDraw);
  }
  view = next;
  $$('.view').forEach(node => { node.hidden = node.id !== `view-${next}`; });
  $$('.nav-item').forEach(node => node.classList.toggle('active', node.dataset.view === next));
  $('#breadcrumb-current').textContent = {setup: editingDraw ? '編輯抽獎' : '建立抽獎', draw: '刮獎現場', history: '抽獎紀錄'}[next];
  if (next === 'draw' && draw) renderDraw();
  if (next === 'history') loadHistory();
  window.scrollTo({top: 0, behavior: 'instant'});
}
$$('[data-view]').forEach(button => button.addEventListener('click', () => showView(button.dataset.view)));

function addPerson(name = '', number = '', focus = false) {
  if ($$('.person-row').length >= 100) return toast('每場最多可以有 100 位參與者。');
  const row = el('div', 'person-row');
  const wrap = el('div', 'person-name-wrap');
  wrap.append(el('span', 'person-index'));
  const nameInput = el('input', 'person-name');
  nameInput.type = 'text'; nameInput.maxLength = 60; nameInput.placeholder = '參與者的名字';
  nameInput.value = name; nameInput.autocomplete = 'off'; nameInput.required = true;
  wrap.append(nameInput);
  const numberInput = el('input', 'person-number');
  numberInput.type = 'number'; numberInput.min = '1'; numberInput.max = '100';
  numberInput.step = '1'; numberInput.placeholder = '01–100'; numberInput.value = number;
  numberInput.required = true; numberInput.inputMode = 'numeric';
  const remove = el('button', 'remove-person');
  remove.type = 'button'; remove.title = '移除參與者';
  remove.innerHTML = '<svg aria-hidden="true"><use href="#i-close"/></svg>';
  remove.addEventListener('click', () => { row.remove(); refreshPeople(); saveDraft(); });
  row.append(wrap, numberInput, remove);
  $('#participant-rows').append(row);
  refreshPeople();
  if (focus) nameInput.focus();
}
function people() {
  return $$('.person-row').map(row => ({name: $('.person-name', row).value.trim(), number: Number($('.person-number', row).value)}));
}
function refreshPeople() {
  const rows = $$('.person-row');
  rows.forEach((row, index) => {
    $('.person-index', row).textContent = String(index + 1).padStart(2, '0');
    $('.person-name', row).setAttribute('aria-label', `第 ${index + 1} 位參與者名稱`);
    $('.person-number', row).setAttribute('aria-label', `第 ${index + 1} 位參與者的幸運號碼`);
    $('.remove-person', row).setAttribute('aria-label', `移除第 ${index + 1} 位參與者`);
  });
  $('#participant-count').textContent = `${rows.length} 位參與者`;
  const count = people().filter(p => p.name && p.number).length;
  $('#preview-count').textContent = String(count).padStart(2, '0');
  $('#preview-people').textContent = count ? `${count} 位，準備接住好運` : '等待好運入座';
}
function updatePreview() {
  $('#preview-title').textContent = $('#title').value.trim() || '你的下一個幸運時刻';
  $('#preview-prize').textContent = $('#prize').value.trim() || '一份值得期待的驚喜';
  $('#preview-host').textContent = $('#host').value.trim() || '就是你';
  const mode = $('input[name="mode"]:checked').value;
  $('#preview-mode').textContent = modeNames[mode];
  $$('.mode-option').forEach(label => label.classList.toggle('selected', $('input', label).checked));
  refreshPeople();
}
function settings() {
  const date = new Date($('#scheduled-at').value);
  return {title: $('#title').value.trim(), host: $('#host').value.trim(), prize: $('#prize').value.trim(),
    scheduled_at: Number.isNaN(date.getTime()) ? '' : date.toISOString(),
    mode: $('input[name="mode"]:checked').value, participants: people()};
}
function editorControls() {
  const locked = editingDraw && editingDraw.status !== 'ready';
  $('#submit-label').textContent = editingDraw ? '儲存修改' : '建立正式抽獎';
  $('#new-draw-button').hidden = !editingDraw;
  $('#editing-notice').hidden = !editingDraw;
  $('#editing-notice').textContent = editingDraw ? `正在編輯「${editingDraw.title}」，儲存後更新同一筆抽獎。${locked ? '抽獎已開始，可修改標題、主辦人與獎品；名單、模式和時間已鎖定。' : '開始前可修改所有設定；修改名單後卡片會重新洗牌。'}` : '';
  $$('#participant-rows input, #participant-rows button, input[name="mode"], #scheduled-at, #add-person, #bulk-toggle, #bulk-input, #bulk-import').forEach(node => { node.disabled = !!locked; });
  // 试玩原样使用已锁定的名单，避免截断 datetime-local 的秒数。
  $('#practice-button').hidden = !!locked;
  if (locked) $('#bulk-area').hidden = true;
}
function openEditor(state) {
  editingDraw = state;
  for (const key of ['title', 'host', 'prize']) $(`#${key}`).value = state[key];
  const date = new Date(state.scheduled_at);
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  $('#scheduled-at').value = date.toISOString().slice(0, 16);
  $(`input[name="mode"][value="${state.mode}"]`).checked = true;
  $('#participant-rows').replaceChildren();
  state.participants.forEach(person => addPerson(person.name, person.number));
  $('#form-error').hidden = true;
  editorControls(); updatePreview(); saveDraft();
}
$('#new-draw-button').addEventListener('click', () => {
  if (networkBusy) return;
  editingDraw = null;
  editorControls();
  $('#breadcrumb-current').textContent = '建立抽獎';
  $('#editing-notice').hidden = false;
  $('#editing-notice').textContent = '正在建立新的抽獎。你可以沿用目前設定，原抽獎會保留在抽獎紀錄中。';
  toast('已切換為建立新抽獎。');
});
function saveDraft() {
  try { sessionStorage.setItem('lucky-draft', JSON.stringify({...settings(), localTime: $('#scheduled-at').value})); } catch {}
}
function restoreDraft() {
  let saved;
  try { saved = JSON.parse(sessionStorage.getItem('lucky-draft')); } catch {}
  if (saved && typeof saved === 'object') {
    for (const key of ['title', 'host', 'prize']) if (typeof saved[key] === 'string') $(`#${key}`).value = saved[key];
    if (typeof saved.localTime === 'string') $('#scheduled-at').value = saved.localTime;
    if (['elimination', 'instant'].includes(saved.mode)) $(`input[value="${saved.mode}"]`).checked = true;
    if (Array.isArray(saved.participants)) saved.participants.slice(0, 100).forEach(p => addPerson(p.name || '', p.number || ''));
  }
  if (!$('#scheduled-at').value) {
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    $('#scheduled-at').value = now.toISOString().slice(0, 16);
  }
  if (!$('.person-row')) { addPerson(); addPerson(); addPerson(); }
  updatePreview();
}
form.addEventListener('input', () => { updatePreview(); saveDraft(); $('#form-error').hidden = true; });
form.addEventListener('change', () => { updatePreview(); saveDraft(); });
$('#add-person').addEventListener('click', () => { addPerson('', '', true); saveDraft(); });
$('#bulk-toggle').addEventListener('click', () => { $('#bulk-area').hidden = !$('#bulk-area').hidden; if (!$('#bulk-area').hidden) $('#bulk-input').focus(); });
$('#bulk-import').addEventListener('click', () => {
  const lines = $('#bulk-input').value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (lines.length < 2 || lines.length > 100) return toast('請輸入 2–100 位參與者，每行一位。');
  const parsed = [];
  const names = new Set(), numbers = new Set();
  for (let i = 0; i < lines.length; i++) {
    const match = lines[i].match(/^(.+?)[,，\t]+\s*(\d+)\s*$/);
    if (!match) return toast(`第 ${i + 1} 行格式不正確，請使用「名字, 號碼」。`);
    const name = match[1].trim(), number = Number(match[2]);
    if (name.length > 60 || !Number.isInteger(number) || number < 1 || number > 100) return toast(`第 ${i + 1} 行名稱過長，或號碼不在 1–100 內。`);
    if (names.has(name.toLocaleLowerCase()) || numbers.has(number)) return toast(`第 ${i + 1} 行有重複的名字或號碼，請先調整。`);
    names.add(name.toLocaleLowerCase()); numbers.add(number); parsed.push({name, number});
  }
  $('#participant-rows').replaceChildren();
  parsed.forEach(p => addPerson(p.name, p.number));
  $('#bulk-area').hidden = true; saveDraft(); updatePreview(); toast(`已匯入 ${parsed.length} 位參與者。`);
});
async function createDraw(practice) {
  if (networkBusy) return;
  const payload = settings();
  const saving = !practice && editingDraw;
  if (editingDraw && editingDraw.status !== 'ready') {
    for (const key of ['scheduled_at', 'participants', 'mode']) payload[key] = editingDraw[key];
  }
  if (!form.reportValidity()) return;
  if (payload.participants.length < 2) return showFormError('至少需要 2 位參與者。');
  const nums = new Set(), names = new Set();
  for (const p of payload.participants) {
    if (!p.name || !Number.isInteger(p.number) || p.number < 1 || p.number > 100) return showFormError('請填妥每位參與者的名字及 1–100 的整數號碼。');
    if (nums.has(p.number)) return showFormError(`號碼 ${p.number} 重複了，請選擇不同的號碼。`);
    if (names.has(p.name.toLocaleLowerCase())) return showFormError(`名字「${p.name}」重複了，請使用可區別的名字。`);
    nums.add(p.number); names.add(p.name.toLocaleLowerCase());
  }
  networkBusy = true;
  $('#create-button').disabled = $('#practice-button').disabled = true;
  try {
    draw = await api(saving ? `/api/draws/${editingDraw.id}/settings` : '/api/draws', {...payload, practice});
    if (practice && editingDraw) editingDraw = {...editingDraw, ...payload};
    if (!practice) editingDraw = draw;
    saveCurrent(); showView('draw');
    toast(saving ? '修改已儲存，已更新原抽獎，沒有新增紀錄。' : practice ? '已進入試玩，所有操作都不會寫入資料庫。' : '正式抽獎已建立並儲存，準備迎接好運。');
  } catch (error) { showFormError(error.message); }
  finally { networkBusy = false; $('#create-button').disabled = $('#practice-button').disabled = false; }
}
function showFormError(message) { $('#form-error').textContent = message; $('#form-error').hidden = false; $('#form-error').scrollIntoView({block: 'nearest', behavior: 'smooth'}); }
form.addEventListener('submit', event => { event.preventDefault(); createDraw(false); });
$('#practice-button').addEventListener('click', () => createDraw(true));
function saveCurrent() {
  if (!draw) return;
  const hash = `#${draw.practice ? 'practice' : 'draw'}/${draw.id}`;
  history.replaceState(null, '', hash);
  try { sessionStorage.setItem('lucky-current', JSON.stringify({id: draw.id, practice: draw.practice})); } catch {}
}
function formatTime(value) { return new Date(value).toLocaleString('zh-TW', {year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false}); }
function isWinner(card) { return draw.status === 'completed' && card.person && card.person.number === draw.winner.number; }
function updateDrawSummary() {
  $('#draw-title').textContent = draw.title;
  $('#draw-description').textContent = `${draw.host} 主辦 · ${modeNames[draw.mode]} · ${formatTime(draw.scheduled_at)}`;
  $('#draw-badge').textContent = draw.practice ? '試玩模式 · 不記錄結果' : '正式抽獎';
  $('#draw-prize').textContent = draw.prize;
  $('#nav-count').textContent = draw.participants.length;
  $('#draw-progress').textContent = draw.status === 'completed' ? '幸運已揭曉' : draw.mode === 'elimination' ? `${draw.participants.length - draw.revealed.length} / ${draw.participants.length} 位` : `${draw.participants.length} 位參與者`;
  $('#remaining-label').textContent = draw.status === 'completed' ? '本次結果' : draw.mode === 'elimination' ? '仍在場上的好運' : '第一張即是得主';
  $('#start-button').hidden = draw.status !== 'ready';
  $('#again-button').hidden = !draw.practice;
  $('#again-button').textContent = draw.status === 'completed' ? '再試一次並洗牌' : '重新試玩並洗牌';
  const wait = new Date(draw.scheduled_at) > new Date() && !draw.practice;
  $('#start-button').disabled = wait;
  let notice;
  if (draw.status === 'ready') notice = wait ? `好運將在 ${formatTime(draw.scheduled_at)} 開場。到時按「開始抽獎」即可；等待時可返回設定試玩。` : '卡片已經隨機排好。準備好了，就按「開始抽獎」，選一張用滑鼠或手指慢慢刮開。';
  else if (draw.status === 'completed') notice = `${draw.practice ? '試玩結束' : '抽獎結束'}：${draw.winner.name}（${draw.winner.number} 號）獲得 ${draw.prize}。${draw.practice ? '這次結果不會寫入資料庫。' : '結果已自動儲存到 Supabase。'}`;
  else notice = draw.selected !== null ? '這張卡的好運正在揭曉，請繼續刮完選中的卡片，再選下一張。' : draw.mode === 'elimination' ? '刮開約一半的塗層即確認淘汰，最後留下的一位自動獲獎。慢慢刮，讓期待多停留一下。' : '準備接住好運！刮開約一半的塗層後，就會揭曉唯一的幸運得主。';
  if (draw.practice) notice += ' 重新試玩會建立新局並重新隨機分配號碼；刷新頁面會保留本局。';
  $('#draw-notice').textContent = notice;
  $('#draw-save-status').textContent = draw.practice ? '✧ 試玩結果不寫入資料庫' : '✓ 正式抽獎進度已儲存';
  $('#roster-count').textContent = `${draw.participants.length} 位`;
  const eliminated = new Set(draw.revealed.map(i => draw.cards[i].person?.number));
  $('#draw-roster').replaceChildren(...draw.participants.map(person => {
    const won = draw.winner?.number === person.number;
    const node = el('span', `roster-person${won ? ' won' : draw.mode === 'elimination' && eliminated.has(person.number) ? ' out' : ''}`);
    node.append(el('b', '', String(person.number).padStart(2, '0')), document.createTextNode(person.name));
    if (won) node.append(document.createTextNode(' ✧'));
    return node;
  }));
}
function renderDraw() {
  $('#draw-empty').hidden = !!draw;
  $('#draw-content').hidden = !draw;
  if (!draw) return;
  if (observer) observer.disconnect();
  updateDrawSummary();
  const grid = $('#scratch-grid'); grid.replaceChildren();
  observer = new ResizeObserver(entries => {
    for (const entry of entries) { if (entry.contentRect.width > 0) entry.target.repaint?.(); }
  });
  draw.cards.forEach(card => {
    const won = isWinner(card);
    const visible = card.revealed || draw.status === 'completed';
    const element = el('article', `scratch-card${visible ? ' revealed' : ''}${won ? ' winner' : card.revealed && draw.mode === 'elimination' ? ' eliminated' : ''}`);
    element.dataset.index = card.index;
    const top = el('div', 'scratch-ticket-top'); top.append(el('span', '', `LUCKY CARD ${String(card.index + 1).padStart(2, '0')}`), el('span', '', '✧'));
    const surface = el('div', 'scratch-surface');
    const content = el('div', 'scratch-content');
    const num = el('span', 'scratch-number', card.person ? String(card.person.number).padStart(2, '0') : '');
    const name = el('span', 'scratch-name', card.person?.name || '');
    content.append(num, name);
    const canvas = el('canvas', 'scratch-canvas'); canvas.setAttribute('aria-hidden', 'true');
    surface.append(content, canvas);
    const status = el('div', 'card-status', won ? '✧ 本場幸運得主' : card.revealed ? draw.mode === 'elimination' ? '這次先休息，好運下次見' : '幸運已揭曉' : draw.status === 'completed' ? '下次再接住好運' : '好運就在這裡，等你刮開');
    const keyboard = el('button', 'card-keyboard', '鍵盤刮開'); keyboard.type = 'button';
    keyboard.setAttribute('aria-label', `選擇並刮開第 ${card.index + 1} 張卡片`);
    keyboard.disabled = visible || draw.status !== 'active' || (draw.selected !== null && draw.selected !== card.index);
    element.append(top, surface, status, keyboard); grid.append(element);
    if (!visible) setupScratch({card, element, canvas, surface, num, name, status, keyboard});
    else canvas.remove();
  });
}
async function operation(action, index) {
  return api(`/api/draws/${draw.id}/${action}`, {practice: draw.practice, ...(index !== undefined ? {index} : {})});
}
$('#start-button').addEventListener('click', async () => {
  if (networkBusy) return;
  networkBusy = true; $('#start-button').disabled = true;
  try { draw = await operation('start'); renderDraw(); toast('好運開場了，選一張卡片開始刮吧。'); }
  catch (error) { toast(error.message); }
  finally { networkBusy = false; if (draw.status === 'ready') updateDrawSummary(); }
});
$('#again-button').addEventListener('click', async () => {
  if (networkBusy) return;
  networkBusy = true; $('#again-button').disabled = true;
  try {
    const {title, host, prize, mode, scheduled_at, participants} = draw;
    draw = await api('/api/draws', {title, host, prize, mode, scheduled_at, participants, practice: true});
    saveCurrent(); renderDraw();
    toast('新一局已建立，號碼已重新隨機洗牌。');
  }
  catch (error) { toast(error.message); }
  finally { networkBusy = false; $('#again-button').disabled = false; }
});

function setupScratch({card, element, canvas, surface, num, name, status, keyboard}) {
  let context, width = 0, height = 128, held = false, lastPoint = null;
  let selected = draw.selected === card.index, completed = false, selecting = false, finishing = false;
  let moves = 0, pointer = null;
  const drawId = draw.id;
  function paint() {
    if (completed) return;
    const bounds = surface.getBoundingClientRect();
    const nextWidth = Math.round(bounds.width), nextHeight = Math.round(bounds.height);
    if (!nextWidth || (nextWidth === width && nextHeight === height && context)) return;
    width = nextWidth; height = nextHeight;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    context = canvas.getContext('2d', {willReadFrequently: true});
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.globalCompositeOperation = 'source-over';
    const gradient = context.createLinearGradient(0, 0, width, height);
    gradient.addColorStop(0, '#d5cddd'); gradient.addColorStop(.48, '#c5bbd0'); gradient.addColorStop(1, '#dcd5e3');
    context.fillStyle = gradient; context.fillRect(0, 0, width, height);
    context.strokeStyle = '#ffffff26'; context.lineWidth = .7;
    for (let x = -height; x < width; x += 5) { context.beginPath(); context.moveTo(x, 0); context.lineTo(x + height, height); context.stroke(); }
    context.textAlign = 'center'; context.fillStyle = '#fff9'; context.font = '25px sans-serif'; context.fillText('✧', width / 2, height / 2 - 13);
    context.font = '11px "Microsoft JhengHei", sans-serif'; context.fillStyle = '#fff'; context.fillText('刮開，遇見好運', width / 2, height / 2 + 12);
    context.fillStyle = '#ffffffb0'; context.font = '6px sans-serif'; context.fillText('S C R A T C H  &  S M I L E', width / 2, height / 2 + 30);
    context.globalCompositeOperation = 'destination-out';
    context.strokeStyle = '#000'; context.fillStyle = '#000';
    lastPoint = null;
  }
  surface.repaint = paint; paint(); observer.observe(surface);
  if (draw.status !== 'active' || (draw.selected !== null && !selected)) canvas.classList.add('locked');
  function point(event) { const r = canvas.getBoundingClientRect(); return {x: event.clientX - r.left, y: event.clientY - r.top}; }
  function erase(p) {
    if (!context || completed || finishing) return;
    context.lineWidth = 28; context.lineCap = 'round'; context.lineJoin = 'round';
    context.beginPath();
    if (lastPoint) { context.moveTo(lastPoint.x, lastPoint.y); context.lineTo(p.x, p.y); context.stroke(); }
    else { context.arc(p.x, p.y, 14, 0, Math.PI * 2); context.fill(); }
    lastPoint = p;
    moves++;
    if (moves % 5 === 0) checkCoverage();
  }
  function checkCoverage() {
    if (!context || completed || finishing) return;
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let empty = 0, total = 0;
    for (let i = 3; i < pixels.length; i += 64) { total++; if (pixels[i] < 100) empty++; }
    if (empty / total >= .47) finish();
  }
  async function select() {
    if (selected) return true;
    if (selecting || networkBusy || draw.status !== 'active') return false;
    if (draw.selected !== null && draw.selected !== card.index) { toast('請先刮完剛才選中的卡片。'); return false; }
    selecting = networkBusy = true; canvas.classList.add('busy');
    try {
      draw = await operation('select', card.index);
      if (draw.id !== drawId) return false;
      const person = draw.cards[card.index].person;
      num.textContent = String(person.number).padStart(2, '0'); name.textContent = person.name;
      selected = true; updateDrawSummary();
      $$('.scratch-card').forEach(node => {
        if (Number(node.dataset.index) !== card.index) { $('.scratch-canvas', node)?.classList.add('locked'); const btn = $('.card-keyboard', node); if (btn) btn.disabled = true; }
      });
      status.textContent = '繼續刮開，驚喜就快出現了';
      return true;
    } catch (error) { toast(error.message); return false; }
    finally { selecting = networkBusy = false; canvas.classList.remove('busy'); }
  }
  async function finish() {
    if (finishing || completed || !selected || networkBusy) return;
    finishing = networkBusy = true; keyboard.disabled = true;
    status.textContent = draw.practice ? '正在揭曉…' : '正在確認並儲存結果…';
    try {
      draw = await operation('reveal', card.index);
      completed = true; element.classList.add('revealed');
      observer.unobserve(surface);
      updateDrawSummary();
      if (draw.status === 'completed') { renderDraw(); showWinner(); }
      else {
        element.classList.add('eliminated'); status.textContent = '這次先休息，好運下次見';
        $$('.scratch-card:not(.revealed)').forEach(node => { $('.scratch-canvas', node)?.classList.remove('locked'); const btn = $('.card-keyboard', node); if (btn) btn.disabled = false; });
      }
    } catch (error) { toast(error.message); status.textContent = '儲存尚未確認，繼續刮或按下重試'; keyboard.textContent = '重試確認結果'; keyboard.disabled = false; }
    finally { finishing = networkBusy = false; }
  }
  canvas.addEventListener('pointerdown', async event => {
    if (event.button !== 0 || draw.status !== 'active' || completed || finishing) return;
    event.preventDefault();
    held = true; pointer = event.pointerId; lastPoint = null;
    canvas.setPointerCapture(event.pointerId);
    const p = point(event);
    if (await select()) { if (held) erase(p); }
    else held = false;
  });
  canvas.addEventListener('pointermove', event => { if (held && selected && !selecting && event.pointerId === pointer) erase(point(event)); });
  function end(event) {
    if (event.pointerId !== pointer) return;
    held = false; lastPoint = null;
    if (selected) checkCoverage();
  }
  canvas.addEventListener('pointerup', end); canvas.addEventListener('pointercancel', end);
  keyboard.addEventListener('click', async () => {
    if (!await select()) return;
    // 鍵盤使用者每次按下擦除一條，仍逐步揭曉。
    if (keyboard.textContent === '重試確認結果') return finish();
    const y = Math.min(height - 4, (Number(keyboard.dataset.stroke || 0) + 1) * 20);
    keyboard.dataset.stroke = String(Number(keyboard.dataset.stroke || 0) + 1);
    lastPoint = {x: 0, y}; erase({x: width, y}); lastPoint = null; checkCoverage();
  });
}
function showWinner() {
  $('#winner-name').textContent = draw.winner.name;
  $('#winner-number').textContent = `幸運號碼 ${String(draw.winner.number).padStart(2, '0')}`;
  $('#winner-prize').textContent = `獲得 ${draw.prize}`;
  $('#winner-eyebrow').textContent = draw.practice ? 'JUST FOR FUN · 試玩結果' : 'THE LUCKY ONE IS…';
  $('#winner-save').textContent = draw.practice ? '這是試玩結果，未計入正式抽獎，也不會寫入資料庫。' : '這個幸運時刻，已經自動為你保存到 Supabase。';
  $('#winner-done').firstChild.textContent = draw.practice ? '完成這次試玩' : '收下這份好運';
  if (!$('#winner-dialog').open) $('#winner-dialog').showModal();
}
$('#close-winner').addEventListener('click', () => $('#winner-dialog').close());
$('#winner-done').addEventListener('click', () => $('#winner-dialog').close());

async function loadHistory() {
  const container = $('#history-list');
  container.replaceChildren(el('p', 'section-description', '正在尋找那些幸運時刻…'));
  try {
    const records = await api('/api/draws');
    if (!records.length) {
      const empty = el('div', 'empty-state panel');
      empty.append(el('span', 'empty-symbol', '✧'), el('h2', '', '第一份好運，等你收藏'), el('p', '', '建立正式抽獎後，這裡會保存設定、名單與得獎結果。試玩不會出現在這裡。'));
      container.replaceChildren(empty); return;
    }
    container.replaceChildren(...records.map(record => {
      const row = el('article', 'panel history-card');
      const icon = el('span', 'history-icon'); icon.innerHTML = '<svg aria-hidden="true"><use href="#i-ticket"/></svg>';
      const info = el('div', 'history-info'); info.append(el('h2', '', record.title), el('p', '', `${record.host} 主辦 · ${record.prize}`), el('p', '', `${formatTime(record.scheduled_at)} · ${record.participants.length} 位 · ${modeNames[record.mode]}`));
      const result = el('div', 'history-result'); result.append(el('span', `status-pill ${record.status}`, statusNames[record.status]), el('div', '', record.winner ? `${record.winner.name} · ${record.winner.number} 號` : '幸運得主尚未揭曉'));
      const open = el('button', 'button secondary small', record.status === 'completed' ? '查看結果' : '繼續抽獎');
      open.addEventListener('click', async () => {
        open.disabled = true;
        try { draw = await api(`/api/draws/${record.id}`); saveCurrent(); showView('draw'); }
        catch (error) { toast(error.message); open.disabled = false; }
      });
      const edit = el('button', 'button secondary small', '編輯設定');
      edit.addEventListener('click', async () => {
        edit.disabled = true;
        try { draw = await api(`/api/draws/${record.id}`); saveCurrent(); showView('setup'); }
        catch (error) { toast(error.message); }
        finally { edit.disabled = false; }
      });
      row.append(icon, info, result, edit, open); return row;
    }));
  } catch (error) {
    const empty = el('div', 'empty-state panel'); empty.append(el('span', 'empty-symbol', '✧'), el('h2', '', '暫時無法讀取紀錄'), el('p', '', error.message)); container.replaceChildren(empty);
  }
}
$('#refresh-history').addEventListener('click', loadHistory);
async function checkConnection() {
  try {
    const data = await api('/api/health');
    $('#connection-dot').className = `connection-dot ${data.connected ? 'connected' : 'offline'}`;
    $('#connection-label').textContent = data.connected ? 'Supabase 已連接' : '資料庫待連接 · 可試玩';
    $('.sidebar-bottom').title = data.message;
  } catch { $('#connection-dot').className = 'connection-dot offline'; $('#connection-label').textContent = '暫時離線'; }
}
async function restoreCurrent() {
  let saved;
  const match = location.hash.match(/^#(practice|draw)\/([a-f0-9-]{36})$/);
  if (match) saved = {id: match[2], practice: match[1] === 'practice'};
  else { try { saved = JSON.parse(sessionStorage.getItem('lucky-current')); } catch {} }
  if (!saved || typeof saved.id !== 'string' || !/^[a-f0-9-]{36}$/.test(saved.id)) return;
  try {
    draw = await api(`/api/draws/${saved.id}${saved.practice ? '?practice=1' : ''}`);
    if (match) showView('draw');
    else {
      $('#nav-count').textContent = draw.participants.length;
      if (!draw.practice && view === 'setup') openEditor(draw);
    }
  }
  catch (error) { if (match) toast(error.message); }
}
restoreDraft();
checkConnection();
restoreCurrent();
setInterval(() => { if (draw && view === 'draw' && draw.status === 'ready') updateDrawSummary(); }, 1000);
