'use strict';
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const $ = selector => document.querySelector(selector);
const accountPage = document.body.dataset.accountPage === 'true';
// The fragment is not sent to the server or access logs. Remove it from this history entry immediately.
let loginToken = new URLSearchParams(location.hash.slice(1)).get('token');
if (location.hash) history.replaceState(null, '', location.pathname);
function message(text) { $('#message').textContent = text; $('#message').hidden = false; }
async function api(path, data) {
  const options = data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify(data)};
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '操作失敗，請稍後重試。');
  return result;
}
async function submit(form, path) {
  const button = form.querySelector('button'); button.disabled = true;
  try {
    const result = await api(path, Object.fromEntries(new FormData(form)));
    if (result.redirect) location.replace(result.redirect);
    else { form.reset(); message('密碼已儲存。之後可以使用 Discord user ID 和密碼登入。'); }
  } catch (error) { message(error.message); }
  finally { button.disabled = false; }
}
$('#login-form').addEventListener('submit', event => { event.preventDefault(); submit(event.target, '/api/auth/password-login'); });
$('#password-form').addEventListener('submit', event => { event.preventDefault(); submit(event.target, '/api/auth/password'); });
$('#consume-link').addEventListener('click', async event => {
  event.target.disabled = true;
  try {
    const result = await api('/api/auth/discord-link', {token:loginToken});
    loginToken = null; location.replace(result.redirect);
  } catch (error) { message(error.message); event.target.disabled = false; }
});
$('#logout').addEventListener('click', async () => {
  try { const result = await api('/api/auth/logout', {}); location.replace(result.redirect); }
  catch (error) { message(error.message); }
});
if (loginToken) {
  $('#magic-section').hidden = false; $('#password-section').hidden = true;
} else if (accountPage) {
  api('/api/auth/me').then(({user}) => {
    if (!user) return location.replace('/login');
    $('#profile-section').hidden = false;
    $('#display-name').textContent = user.display_name;
    $('#discord-user-id').textContent = user.discord_user_id;
    $('#account-role').textContent = user.role === 'admin' ? 'Admin' : '一般用戶';
    $('#password-state').textContent = user.password_set ? '已設定網站登入密碼。' : '尚未設定密碼，可以先完成設定。';
    $('#password-form').hidden = !user.can_set_password;
    $('#reverify-note').hidden = user.can_set_password;
  }).catch(error => message(error.message));
} else {
  api('/api/auth/me').then(({user}) => {
    if (user) location.replace(user.password_set ? '/shards' : '/account');
  }).catch(error => message(error.message));
}
