"""Real login UI test on port 5014; removes its disposable DB identity afterwards."""
import json
from pathlib import Path
import secrets
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from waitress import create_server

from app import create_app
from auth_service import AuthService
from storage import PostgresStore


def main():
    auth = AuthService()
    uid = '7' + ''.join(str(secrets.randbelow(10)) for _ in range(18))
    origin = 'http://127.0.0.1:5014'
    link = auth.issue_link(uid, 'Login UI check', origin)
    server = create_server(create_app(), host='127.0.0.1', port=5014, threads=4)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            context = browser.new_context(viewport={'width':1280,'height':900})
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(link)
            page.wait_for_selector('#consume-link:visible')
            assert '#' not in page.url
            page.locator('#consume-link').click()
            page.wait_for_url('**/shards')
            page.wait_for_selector('#password-reminder:visible')
            page.goto(origin+'/login')
            page.wait_for_url('**/shards')
            page.goto(origin+'/account')
            page.wait_for_selector('#password-form:visible')
            assert page.locator('#discord-user-id').inner_text() == uid
            page.locator('#password-form input[name=password]').fill('test1234')
            page.locator('#password-form input[name=confirm_password]').fill('test1234')
            page.locator('#password-form button').click()
            page.wait_for_url('**/shards')
            page.goto(origin + '/account')
            page.wait_for_selector('#profile-section:visible')
            Path('artifacts').mkdir(exist_ok=True)
            page.screenshot(path='artifacts/login-account-desktop.png')
            page.locator('#logout').click()
            page.wait_for_url('**/login')
            page.locator('#login-form input[name=username]').fill(uid)
            page.locator('#login-form input[name=password]').fill('test1234')
            page.locator('#login-form button').click()
            page.wait_for_url('**/shards')
            page.goto(origin + '/account')
            page.wait_for_selector('#profile-section:visible')
            assert page.locator('#password-form').is_hidden()
            new_link = auth.issue_link(uid, 'Login UI check', origin)
            page.goto(new_link)
            page.locator('#consume-link').click()
            page.wait_for_url('**/shards')
            page.goto(origin + '/login')
            page.wait_for_url('**/shards')
            page.goto(origin + '/shards')
            page.wait_for_function("() => document.querySelector('#account-link').textContent.includes('Login UI check')")
            assert page.locator('#login-notice').is_hidden()
            page.locator('#role-select').wait_for(state='hidden')
            other = browser.new_context(viewport={'width':390,'height':844})
            second = other.new_page()
            second.goto(link)
            second.locator('#consume-link').click()
            second.wait_for_selector('#message:visible')
            assert second.url.endswith('/login')
            assert second.locator('#profile-section').is_hidden()
            second.goto(origin + '/login')
            assert second.evaluate('document.documentElement.scrollWidth <= innerWidth')
            second.screenshot(path='artifacts/login-mobile.png')
            assert not errors, errors
            browser.close()
        print(json.dumps({'passed':['fragment removed','one-time link login','password setup','logout','password login','password reset restriction','account header','replay denied','mobile layout','no JS errors'],'discord_connected':False}))
    finally:
        server.task_dispatcher.shutdown(timeout=10)
        server.close()
        with PostgresStore().connection() as conn:
            player = conn.execute("SELECT player_id::text FROM onmyoji_shards.player_identities WHERE provider='discord' AND external_subject=%s", (uid,)).fetchone()
            if player:
                from auth_service import digest
                conn.execute('DELETE FROM onmyoji_shards.login_rate_limits WHERE key_hash IN (%s,%s)', (digest('user:'+uid),digest('password-set:'+player[0])))
                conn.execute('DELETE FROM onmyoji_shards.players WHERE id=%s', (player[0],))


if __name__ == '__main__':
    main()
