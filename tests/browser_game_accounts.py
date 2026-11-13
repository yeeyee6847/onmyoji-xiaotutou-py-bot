"""Real game-account persistence/UI, with an explicitly synthetic OCR row; cleanup in finally."""
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from playwright.sync_api import sync_playwright
from waitress import create_server
from types import SimpleNamespace

from app import create_app
from storage import PostgresStore


def main():
    with PostgresStore().connection() as conn:
        player=str(conn.execute("INSERT INTO onmyoji_shards.players(display_name) VALUES ('Game account UI check') RETURNING id").fetchone()[0])
        item=conn.execute('SELECT id::text,name FROM onmyoji_shards.shikigami WHERE is_active LIMIT 1').fetchone()
    catalog=SimpleNamespace(list=lambda:[dict(id=item[0],name=item[1],rarity='SSR',aliases=[],image='')])
    def inspector(image, records, manual, progress):
        from shards.vision import image_data
        rows = [dict(id='one',index=1,bbox=[0,0,30,30],crop=image_data(image),raw_name=item[1],raw_quantity='15',
                     shikigami_id=item[0],quantity=15,name_confidence=.99,quantity_confidence=.99,
                     included=True,confirmed=False,needs_review=False,suggestions=[],target='offers')]
        rows.append(dict(rows[0],id='two',index=2,target='wants',quantity=57,raw_quantity='57'))
        return rows,'Synthetic OCR for UI test only.'
    user=dict(id=player,display_name='Game account UI check',role='user',password_set=True)
    server=create_server(create_app(auth_service=SimpleNamespace(current=lambda token:user),
                                    shard_options=dict(catalog=catalog,inspector=inspector)),host='127.0.0.1',port=5015,threads=4)
    threading.Thread(target=server.run,daemon=True).start()
    try:
        Path('artifacts').mkdir(exist_ok=True)
        fixture=Path('artifacts/game-account-test.png');Image.new('RGB',(180,180),'#4e6952').save(fixture)
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport=dict(width=1440,height=1050))
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto('http://127.0.0.1:5015/shards')
            page.wait_for_function("() => document.querySelector('#game-account-select').options.length === 1")
            for name in ('First account','Second account'):
                page.locator('#game-account-manager summary').click()
                page.locator('#game-account-form input[name=nickname]').fill(name)
                page.locator('#game-account-form button').click()
                page.wait_for_function("name => document.querySelector('#game-account-select').selectedOptions[0]?.textContent === name",arg=name)
            second=page.locator('#game-account-select').input_value()
            page.locator('#screenshot-file').set_input_files(str(fixture.resolve()))
            page.locator('#analyze-button').click()
            page.wait_for_selector('#review-rows tr[data-row-id=one]')
            assert 'Second account' in page.locator('#job-meta').inner_text()
            page.locator('#target-filters button[data-target=wants]').click()
            assert page.locator('#review-rows tr[data-row-id]').count()==1
            assert page.locator('#review-rows tr').first.get_attribute('data-row-id')=='two'
            page.locator('#target-filters button[data-target=all]').click()
            for row_id in ('one','two'):
                page.locator(f'#review-rows tr[data-row-id={row_id}] .row-actions button').first.click()
                page.wait_for_selector(f'#review-rows tr[data-row-id={row_id}] .tag.good')
            page.locator('#save-import-button').click()
            page.wait_for_function("() => document.querySelector('#job-meta').textContent.includes('已保存至帳號')")
            page.screenshot(path='artifacts/game-account-saved.png')
            page.goto('http://127.0.0.1:5015/game-accounts')
            page.wait_for_function("() => document.querySelector('#game-account-select').options.length === 3")
            page.locator('#game-account-select').select_option(second)
            page.wait_for_selector('#account-fragments li')
            assert page.locator('#account-fragments li').count()==2
            assert '15' in page.locator('#account-fragments li').nth(0).inner_text()
            assert '57' in page.locator('#account-fragments li').nth(1).inner_text()
            page.set_viewport_size(dict(width=390,height=844))
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path='artifacts/game-accounts-mobile.png')
            assert not errors,errors
            browser.close()
        print(json.dumps({'passed':['multiple account creation','upload account choice','confirmed import saved','saved fragments visible','mobile layout','no JS errors'],'ocr':'synthetic test row'}))
    finally:
        server.task_dispatcher.shutdown(timeout=10);server.close()
        with PostgresStore().connection() as conn:
            conn.execute('DELETE FROM onmyoji_shards.players WHERE id=%s',(player,))


if __name__=='__main__':main()
