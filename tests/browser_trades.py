"""Two-party browser lifecycle; synthetic identities and Discord delivery suppressed."""
from pathlib import Path
import secrets
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from waitress import create_server
from app import create_app
from shards.accounts import GameAccounts
from shards.management import FragmentManagement
from storage import PostgresStore


def main():
    players=[];accounts=[]
    with PostgresStore().connection() as c:
        for name in ('Trade UI A','Trade UI B'):
            identity=str(c.execute('INSERT INTO onmyoji_shards.players(display_name) VALUES (%s) RETURNING id',(name,)).fetchone()[0]);players.append(identity)
            uid='5'+''.join(str(secrets.randbelow(10)) for _ in range(18));c.execute("INSERT INTO onmyoji_shards.player_identities(player_id,provider,external_subject) VALUES (%s,'discord',%s)",(identity,uid))
        items=c.execute('SELECT id::text,name FROM onmyoji_shards.shikigami WHERE is_active ORDER BY id LIMIT 2').fetchall()
    for index,player in enumerate(players):
        account=GameAccounts().create(player,dict(nickname=f'Trade UI account {index}'));accounts.append(account['id'])
        FragmentManagement().write(player,dict(game_account_id=account['id'],items=[dict(shikigami_id=items[index][0],target='offers',quantity=10)]))
    active=dict(id=players[0],role='user',password_set=True,display_name='Trade UI A')
    server=create_server(create_app(auth_service=SimpleNamespace(current=lambda token:active,rate_limit=lambda *a,**k:None)),host='127.0.0.1',port=5017,threads=4)
    threading.Thread(target=server.run,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True);page=browser.new_page(viewport=dict(width=1440,height=1050));errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
            origin='http://127.0.0.1:5017';page.goto(origin+'/trades?other_account_id='+accounts[1]+'&shikigami_id='+items[1][0])
            page.wait_for_function("() => document.querySelectorAll('.trade-shikigami option').length === 4")
            assert page.locator('#trade-own').input_value()==accounts[0]
            assert page.locator('#trade-other').input_value()==accounts[1]
            assert page.locator('.trade-shikigami').nth(1).input_value()==items[1][0]
            page.locator('#trade-other-search').fill('not-a-player')
            assert page.locator('#trade-other option').count()==2  # Preserve selected account.
            page.locator('#trade-other').select_option('')
            page.locator('#trade-other-search').fill('Trade UI account 1')
            assert page.locator('#trade-other option').count()==2
            page.locator('#trade-other').select_option(accounts[1])
            page.wait_for_function("() => document.querySelectorAll('.trade-shikigami option').length === 4 && !document.querySelector('#trade-submit').disabled")
            for index in range(2):
                assert page.locator('.trade-shikigami').nth(index).locator('option').count()==2
                page.locator('.trade-shikigami').nth(index).select_option(items[index][0])
                assert '10' in page.locator('.trade-stock').nth(index).inner_text()
                assert page.locator('.trade-quantity').nth(index).get_attribute('max')=='10'
                page.locator('.trade-quantity').nth(index).fill('3')
            page.locator('.picker-launch').first.click()
            assert page.locator('.picker-option').count()==1
            assert '10' in page.locator('.picker-option').inner_text()
            page.locator('.picker-option').click()
            page.locator('.trade-quantity').first.fill('11');page.locator('#trade-submit').click()
            page.wait_for_function("() => document.querySelector('#trade-message').textContent.includes('正整數')")
            page.locator('.trade-quantity').first.fill('3')
            page.locator('#trade-submit').click();page.wait_for_function("() => document.querySelector('#trade-list').textContent.includes('等待接受')")
            # Mark synthetic notification events delivered; no actual Discord messages in browser tests.
            with PostgresStore().connection() as c:c.execute("UPDATE onmyoji_shards.trade_outbox SET status='sent' WHERE trade_id IN (SELECT id FROM onmyoji_shards.trades WHERE requester_id=%s)",(players[0],))
            active['id']=players[1];page.reload();page.wait_for_selector('#trade-list button')
            page.get_by_role('button',name='接受交換',exact=True).click();page.wait_for_function("() => document.querySelector('#trade-list').textContent.includes('已預留')")
            page.wait_for_function("() => document.querySelector('.trade-shikigami').textContent.includes('可用 7 片')")
            page.goto(origin+'/trade-records');page.wait_for_selector('#records-list article')
            assert page.locator('#records-status option').count()==1
            assert 'Trade UI account 0' in page.locator('#records-list').inner_text()
            assert 'Trade UI account 1' in page.locator('#records-list').inner_text()
            page.set_viewport_size(dict(width=390,height=844));assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.goto(origin+'/trades');page.wait_for_selector('#trade-list button')
            page.get_by_role('button',name='我已實際完成交換',exact=True).click();page.wait_for_function("() => document.querySelector('#trade-list').textContent.includes('對方確認：已完成')")
            active['id']=players[0];page.reload();page.get_by_role('button',name='我已實際完成交換',exact=True).click()
            page.wait_for_function("() => document.querySelector('#trade-message').textContent.includes('交換已完成') && !document.querySelector('#trade-list').textContent.includes('雙方已完成')")
            page.goto(origin+'/trade-records');page.wait_for_function("() => document.querySelector('#records-message').textContent !== '載入中…'")
            assert 'Trade UI account 0' not in page.locator('#records-list').inner_text()
            active['role']='admin';page.reload();page.locator('#records-status').select_option('completed')
            page.wait_for_function("() => document.querySelector('#records-list').textContent.includes('Trade UI account 0')")
            assert '已完成交換' in page.locator('#records-list').inner_text()
            with PostgresStore().connection() as c:
                qty=c.execute("SELECT quantity FROM onmyoji_shards.fragment_current WHERE game_account_id=ANY(%s::uuid[]) AND target='offers'",(accounts,)).fetchall()
                assert [r[0] for r in qty]==[7,7]
            page.set_viewport_size(dict(width=390,height=844));assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            Path('artifacts').mkdir(exist_ok=True);page.screenshot(path='artifacts/trades-mobile.png')
            assert not errors,errors;browser.close()
        print('Account search, deep link, owned-only picker and quantities, excess validation, two-party lifecycle, mobile and JS checks passed.')
    finally:
        server.task_dispatcher.shutdown(timeout=10);server.close()
        with PostgresStore().connection() as c:
            c.execute('DELETE FROM onmyoji_shards.trades WHERE requester_id=ANY(%s::uuid[])',(players,))
            c.execute('DELETE FROM onmyoji_shards.players WHERE id=ANY(%s::uuid[])',(players,))


if __name__=='__main__':main()
