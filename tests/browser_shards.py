import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'artifacts'
ARTIFACTS.mkdir(exist_ok=True)


def run():
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1050})
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        response = page.goto('http://127.0.0.1:5013/shards')
        assert response.status == 200
        page.wait_for_function("() => document.querySelector('#engine-status').textContent !== '正在檢查辨識引擎…'")
        page.screenshot(path=str(ARTIFACTS / 'shards-upload-desktop.png'), full_page=True)
        page.locator('.rail-item[data-tab="catalog"]').click()
        page.wait_for_selector('.catalog-card')
        assert page.locator('#add-shikigami').is_hidden()
        page.screenshot(path=str(ARTIFACTS / 'shards-catalog-desktop.png'), full_page=True)
        if '--preview-only' in sys.argv:
            assert not errors, errors
            browser.close()
            print('Initial upload/catalog preview passed, no database used.')
            return
        from PIL import Image
        fixture = ARTIFACTS / 'shards-test-image.png'
        Image.new('RGB', (300, 700), '#4f6357').save(fixture)
        denied = page.evaluate("""async () => (await fetch('/api/shards/catalog', {method:'POST',
          headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},
          body:JSON.stringify({name:'Not allowed',rarity:'UR'})})).status""")
        assert denied == 403
        page.locator('#role-select').select_option('admin')
        page.wait_for_selector('#add-shikigami:visible')
        page.locator('#add-shikigami').click()
        page.locator('#catalog-name').fill('Prototype test shikigami')
        page.locator('#catalog-rarity').select_option('UR')
        page.locator('#catalog-aliases').fill('Test alias\n測試別名')
        page.locator('#portrait-file').set_input_files(str(fixture))
        page.locator('#save-catalog').click()
        page.wait_for_selector('#catalog-dialog:not([open])', state='attached')
        card = page.locator('.catalog-card').filter(has_text='Prototype test shikigami')
        assert card.locator('img').count() == 1
        card.get_by_role('button', name='編輯資料').click()
        page.locator('#catalog-name').fill('Revised prototype shikigami')
        page.locator('#save-catalog').click()
        page.wait_for_selector('#catalog-dialog:not([open])', state='attached')
        card = page.locator('.catalog-card').filter(has_text='Revised prototype shikigami')
        assert card.count() == 1
        card.get_by_role('button', name='刪除', exact=True).click()
        page.locator('#confirm-delete').click()
        page.wait_for_selector('#delete-dialog:not([open])', state='attached')
        assert page.locator('.catalog-card').filter(has_text='Revised prototype shikigami').count() == 0
        page.locator('#role-select').select_option('user')
        page.wait_for_selector('#add-shikigami', state='hidden')
        page.locator('.rail-item[data-tab="upload"]').click()
        page.locator('#demo-button').click()
        page.wait_for_selector('#review-rows tr[data-row-id]')
        assert page.locator('#source-tag').inner_text() == 'DEMO · 預設結果'
        assert page.locator('#review-rows tr[data-row-id]').count() == 6
        page.screenshot(path=str(ARTIFACTS / 'shards-review-desktop.png'), full_page=True)
        page.locator('#export-button').click()
        assert '先逐項確認' in page.locator('#shards-toast').inner_text()
        records = page.evaluate("async () => (await fetch('/api/shards/catalog')).json()")
        extra = next(item['id'] for item in records if item['name'] == '鬼切')
        row_ids = page.locator('#review-rows tr[data-row-id]').evaluate_all('(rows) => rows.map(row => row.dataset.rowId)')
        # 未匹配条目可以先排除再恢复，不会卡在不可编辑状态。
        last = page.locator(f'tr[data-row-id="{row_ids[-1]}"]')
        last.get_by_role('button', name='排除此項').click()
        page.wait_for_selector(f'tr[data-row-id="{row_ids[-1]}"].excluded')
        last.get_by_role('button', name='恢復此項').click()
        page.wait_for_selector(f'tr[data-row-id="{row_ids[-1]}"]:not(.excluded)')
        for i, row_id in enumerate(row_ids):
            row = page.locator(f'tr[data-row-id="{row_id}"]')
            if i == 2:
                row.locator('input').fill('13')
            if i == 5:
                row.locator('select').select_option(extra)
            row.get_by_role('button', name='確認這一項', exact=True).click()
            page.wait_for_selector(f'tr[data-row-id="{row_id}"] .tag.good')
        assert page.locator('#stat-confirmed').inner_text() == '6'
        # 确认后再次改数字必须重新确认，不能静默导出旧值。
        first = page.locator(f'tr[data-row-id="{row_ids[0]}"]')
        first.locator('input').fill('24')
        page.locator('#export-button').click()
        assert '先逐項確認' in page.locator('#shards-toast').inner_text()
        first.locator('.row-actions .btn').click()
        page.wait_for_selector(f'tr[data-row-id="{row_ids[0]}"] .tag.good')
        with page.expect_download() as download:
            page.locator('#export-button').click()
        path = ARTIFACTS / 'shards-reviewed-test.json'
        download.value.save_as(str(path))
        exported = json.loads(path.read_text(encoding='utf-8'))
        assert exported['database_written'] is False and len(exported['items']) == 6
        assert exported['items'][0]['quantity'] == 24
        page.locator('#show-original').click()
        page.wait_for_selector('#original-dialog[open] img')
        page.locator('#close-original').click()
        page.locator('#return-upload').click()
        page.locator('#screenshot-file').set_input_files(str(fixture))
        assert page.locator('#analyze-button').is_enabled()
        page.locator('#analyze-button').click()
        page.wait_for_selector('#review-rows tr[data-row-id="test-row-0"]')
        assert page.locator('#source-tag').inner_text() == '本地圖片處理'
        assert page.locator('#review-rows tr[data-row-id]').count() == 2
        page.reload()
        page.wait_for_function("() => document.querySelector('#nav-review-count').textContent === '2'")
        page.set_viewport_size({'width': 390, 'height': 844})
        for name in ('upload', 'catalog', 'review'):
            page.locator(f'.rail-item[data-tab="{name}"]').click()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), name
            page.screenshot(path=str(ARTIFACTS / f'shards-{name}-mobile.png'), full_page=True)
        assert not errors, errors
        browser.close()
    print(json.dumps({'passed': ['user/admin mock roles and backend guard', 'catalog CRUD and avatar upload',
        'explicit demo label', 'review correction and confirmation', 'exclude and restore unmatched item',
        'dirty confirmed value blocks export', 'JSON download', 'original image preview',
        'real file upload with isolated test recognizer', 'reload recovery', '390px views', 'no JavaScript errors'],
        'database_access': False}, ensure_ascii=True))


if __name__ == '__main__':
    run()
