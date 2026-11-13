"""Browser integration with disposable DB fixtures, no Discord or real OCR accuracy claim."""
import json
from pathlib import Path
import sys
import threading
import uuid
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright
from waitress import create_server

from app import create_app
from shards.accounts import GameAccounts
from shards.catalog import PostgresCatalog
from shards.samples import SampleLibrary
from shards.vision import image_data
from storage import PostgresStore


def main():
    prefix='UI-'+uuid.uuid4().hex[:12]
    with PostgresStore().connection() as c:
        player=str(c.execute('INSERT INTO onmyoji_shards.players(display_name) VALUES (%s) RETURNING id',(prefix,)).fetchone()[0])
    account=GameAccounts().create(player,dict(nickname='Main UI account'))
    catalog=PostgresCatalog().list();item=catalog[0]
    image=Image.fromarray(np.random.default_rng(18).integers(0,256,(70,70,3),dtype=np.uint8))
    job=str(uuid.uuid4());SampleLibrary().capture(player,job,[dict(index=1,crop=image_data(image),portrait=image_data(image),raw_name=item['name'],shikigami_id=item['id'])])
    with PostgresStore().connection() as c:sample=str(c.execute('SELECT id FROM onmyoji_shards.portrait_samples WHERE job_id=%s',(job,)).fetchone()[0])
    user=dict(id=player,display_name=prefix,role='user',password_set=True)
    server=create_server(create_app(auth_service=SimpleNamespace(current=lambda token:user)),host='127.0.0.1',port=5016,threads=5)
    threading.Thread(target=server.run,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport=dict(width=1440,height=1050));errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            origin='http://127.0.0.1:5016'
            page.goto(origin+'/my-fragments');page.wait_for_selector('.manual-shikigami')
            page.locator('#workspace-account').select_option(account['id'])
            page.locator('#manual-rows .picker-launch').click()
            page.locator('.picker-dialog input').fill(item.get('name_simplified') or item['name'])
            page.locator('.picker-dialog select').select_option(item['rarity'])
            page.locator('.picker-option').filter(has=page.get_by_text(item['name'],exact=True)).first.click()
            page.locator('.manual-quantity').fill('2');page.locator('#manual-save').click()
            page.wait_for_function("() => document.querySelector('#workspace-rows tr td:nth-child(3)')?.textContent === '2'")
            page.locator('.manual-quantity').fill('3');page.locator('#manual-save').click()
            page.wait_for_function("() => document.querySelector('#workspace-rows tr td:nth-child(3)')?.textContent === '3'")
            page.goto(origin+'/search-fragments?shikigami_id='+item['id'])
            page.wait_for_selector('#workspace-rows tr');assert 'Main UI account' in page.locator('#workspace-rows').inner_text()
            page.goto(origin+'/shards#catalog');page.wait_for_selector('.catalog-card')
            page.locator('.catalog-card').filter(has=page.get_by_role('heading',name=item['name'],exact=True)).locator('.catalog-avatar').click()
            page.wait_for_function("() => document.querySelector('.owners-content')?.textContent.includes('Main UI account')")
            page.locator('#fragment-owners-dialog button').click()
            user['role']='admin';page.reload();page.wait_for_selector('#add-shikigami:visible')
            page.locator('#add-shikigami').click();page.wait_for_selector('#catalog-dialog[open]')
            assert not page.locator('#catalog-order').is_disabled()
            default_order=int(page.locator('#catalog-order').input_value())
            page.locator('#catalog-name').fill(prefix);page.locator('#catalog-simple').fill(prefix+'S');page.locator('#catalog-rarity').select_option('UR')
            page.locator('#save-catalog').click();page.wait_for_selector('#catalog-dialog',state='hidden')
            page.locator('#catalog-search').fill(prefix)
            page.wait_for_function("() => document.querySelectorAll('.catalog-card').length === 1")
            page.locator('.catalog-actions button').first.click();page.locator('#catalog-order').fill(str(default_order+2));page.locator('#catalog-rarity').select_option('SSR')
            page.locator('#save-catalog').click();page.wait_for_selector('#catalog-dialog',state='hidden')
            assert f'#{default_order+2:03}' in page.locator('.catalog-card').inner_text()
            page.goto(origin+'/admin/samples');page.wait_for_selector('.sample-card')
            card=page.locator('.sample-card').filter(has=page.locator(f'img[src*="/{sample}/image"]'))
            card.get_by_role('button',name='確認並啟用',exact=True).click()
            page.wait_for_function("id => ![...document.querySelectorAll('.sample-images img')].some(i=>i.src.includes(id))",arg=sample)
            page.locator('#sample-status').select_option('approved')
            page.wait_for_selector(f'img[src*="/{sample}/image"]')
            page.set_viewport_size(dict(width=390,height=844))
            for path in ('/my-fragments','/search-fragments','/admin/samples','/shards#catalog'):
                page.goto(origin+path);page.wait_for_selector('.catalog-card' if path.startswith('/shards') else '#workspace-title')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),path
            Path('artifacts').mkdir(exist_ok=True);page.screenshot(path='artifacts/feature-workspace-mobile.png')
            assert not errors,errors;browser.close()
        print(json.dumps({'passed':['search picker and rarity','manual 2 to 3 overwrite','global search','owner details','admin create edit editable order','reference approval','390px layout','no JS errors']}))
    finally:
        server.task_dispatcher.shutdown(timeout=10);server.close()
        with PostgresStore().connection() as c:
            c.execute('DELETE FROM onmyoji_shards.players WHERE id=%s',(player,))
            c.execute('DELETE FROM onmyoji_shards.shikigami WHERE name=%s',(prefix,))


if __name__=='__main__':main()
