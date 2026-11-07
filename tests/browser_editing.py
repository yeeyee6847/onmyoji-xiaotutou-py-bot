"""对 5011 端口的独立内存测试服务验证编辑流程，不连接真实数据库。"""
import json

from playwright.sync_api import sync_playwright


def state(page):
    return page.evaluate("""async () => {
      const [kind, id] = location.hash.slice(1).split('/');
      return (await fetch('/api/draws/' + id + (kind === 'practice' ? '?practice=1' : ''))).json();
    }""")


def count(page):
    return page.evaluate("async () => (await (await fetch('/api/draws')).json()).length")


def run():
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 1000})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:5011')
        page.locator('#title').fill('Original draw')
        page.locator('#host').fill('Host')
        page.locator('#prize').fill('Gift')
        for i in range(3):
            page.locator('.person-name').nth(i).fill(f'Person {i}')
            page.locator('.person-number').nth(i).fill(str(i + 1))
        page.locator('#create-button').click()
        page.wait_for_selector('#draw-content:visible')
        original = state(page)
        assert count(page) == 1
        page.locator('.draw-bottom [data-view="setup"]').click()
        assert page.locator('#submit-label').inner_text() == '儲存修改'
        assert page.locator('#title').input_value() == 'Original draw'
        page.locator('#title').fill('Updated draw')
        page.locator('.person-number').nth(0).fill('40')
        page.locator('#create-button').click()
        page.wait_for_selector('#draw-content:visible')
        updated = state(page)
        assert updated['id'] == original['id'] and count(page) == 1
        assert updated['title'] == 'Updated draw'
        assert updated['participants'][0]['number'] == 40
        # 编辑时先试玩，返回后仍能保存同一场正式抽奖，保留待保存的资料。
        page.locator('.nav-item[data-view="setup"]').click()
        page.locator('#prize').fill('Previewed gift')
        page.locator('#practice-button').click()
        page.wait_for_selector('#draw-content:visible')
        assert state(page)['practice'] is True and count(page) == 1
        page.locator('.nav-item[data-view="setup"]').click()
        assert page.locator('#submit-label').inner_text() == '儲存修改'
        assert page.locator('#prize').input_value() == 'Previewed gift'
        page.locator('#create-button').click()
        page.wait_for_selector('#draw-content:visible')
        assert state(page)['id'] == original['id'] and count(page) == 1
        assert state(page)['prize'] == 'Previewed gift'
        # 刷新后能回到原场次编辑；开始后锁定影响结果的设定。
        page.reload()
        page.wait_for_selector('#draw-content:visible')
        page.locator('#start-button').click()
        page.wait_for_function("() => document.querySelector('#start-button').hidden")
        page.locator('.nav-item[data-view="setup"]').click()
        assert page.locator('#scheduled-at').is_disabled()
        assert page.locator('.person-name').nth(0).is_disabled()
        assert page.locator('input[value="instant"]').is_disabled()
        page.locator('#title').fill('Active renamed draw')
        page.locator('#create-button').click()
        page.wait_for_selector('#draw-content:visible')
        assert state(page)['status'] == 'active' and count(page) == 1
        # 只有明确选择另建新抽奖才新增记录。
        page.locator('.nav-item[data-view="setup"]').click()
        page.locator('#new-draw-button').click()
        assert page.locator('#submit-label').inner_text() == '建立正式抽獎'
        assert page.locator('.person-name').nth(0).is_enabled()
        page.locator('#title').fill('Separate draw')
        page.locator('#create-button').click()
        page.wait_for_selector('#draw-content:visible')
        assert state(page)['id'] != original['id'] and count(page) == 2
        # 历史列表也能直接编辑旧场次。
        page.locator('.nav-item[data-view="history"]').click()
        row = page.locator('.history-card').filter(has_text='Active renamed draw')
        row.get_by_role('button', name='編輯設定').click()
        page.wait_for_selector('#view-setup:visible')
        assert page.locator('#title').input_value() == 'Active renamed draw'
        page.locator('#host').fill('Corrected host')
        page.locator('#create-button').click()
        page.wait_for_selector('#draw-content:visible')
        assert state(page)['id'] == original['id'] and count(page) == 2
        # 新按钮在手机上也不会撑开页面。
        page.set_viewport_size({'width': 390, 'height': 844})
        page.locator('.nav-item[data-view="setup"]').click()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        browser.close()
    print(json.dumps({'passed': ['update same draw without duplicate', 'roster changes saved',
        'practice preview keeps formal edit target and unsaved settings', 'reload and edit',
        'active rules locked', 'explicit new draw creates a separate record', 'history editing',
        'mobile layout', 'no JavaScript errors']}, ensure_ascii=True))


if __name__ == '__main__':
    run()
