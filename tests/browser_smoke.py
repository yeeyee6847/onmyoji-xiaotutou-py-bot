"""对运行在 localhost:5000 的真实页面进行浏览器验证；只创建试玩。"""
import json
import sys
from collections import Counter
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)


def current_state(page):
    return page.evaluate("""async () => {
      const [kind, id] = location.hash.slice(1).split('/');
      return (await fetch('/api/draws/' + id + (kind === 'practice' ? '?practice=1' : ''))).json();
    }""")


def scratch(page, index):
    canvas = page.locator(f'.scratch-card[data-index="{index}"] canvas')
    canvas.scroll_into_view_if_needed()
    box = canvas.bounding_box()
    page.mouse.move(box["x"] + 8, box["y"] + 8)
    page.mouse.down()
    page.wait_for_function("""i => document.querySelector('#draw-notice').textContent.includes('這張卡')
      || document.querySelector('.scratch-card[data-index="' + i + '"] .scratch-name').textContent.length > 0""", arg=index)
    for line, offset in enumerate(range(10, int(box["height"]) - 4, 15)):
        y = box["y"] + offset
        left, right = box["x"] + 5, box["x"] + box["width"] - 5
        page.mouse.move(left if line % 2 == 0 else right, y, steps=8)
        page.mouse.move(right if line % 2 == 0 else left, y, steps=16)
        if page.locator(f'.scratch-card[data-index="{index}"].revealed').count():
            break
    page.mouse.up()
    if not page.locator(f'.scratch-card[data-index="{index}"].revealed').count():
        page.screenshot(path=str(ARTIFACTS / 'scratch-debug.png'), full_page=True)
        print('scratch metrics', json.dumps(page.locator(f'.scratch-card[data-index="{index}"]').evaluate("""n => {
          const c=n.querySelector('canvas'), a=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
          let empty=0,total=0; for(let i=3;i<a.length;i+=64){total++;if(a[i]<100)empty++;}
          return {coverage:empty/total,status:n.innerText,state:c.className};
        }"""), ensure_ascii=True), flush=True)
    page.wait_for_selector(f'.scratch-card[data-index="{index}"].revealed', timeout=5000)


def run():
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        page = context.new_page()
        def record_error(error):
            errors.append(str(error))
            print('browser error:', str(error), flush=True)
        page.on("pageerror", record_error)
        response = page.goto("http://127.0.0.1:5000")
        assert response.status == 200
        page.wait_for_selector('#connection-dot.connected')
        before = page.evaluate("async () => (await fetch('/api/draws')).json()")
        page.locator('#title').fill('週末的小確幸抽獎')
        page.locator('#host').fill('小兔')
        page.locator('#prize').fill('一杯快樂的奶茶')
        for i, (name, number) in enumerate([('小月', 7), ('阿茶', 23), ('小白', 88)]):
            page.locator('.person-name').nth(i).fill(name)
            page.locator('.person-number').nth(i).fill(str(number))
        page.screenshot(path=str(ARTIFACTS / 'setup-desktop.png'), full_page=True)
        # 重复号码应在创建前阻止。
        page.locator('.person-number').nth(1).fill('7')
        page.locator('#practice-button').click()
        assert not page.locator('#form-error').is_hidden()
        page.locator('.person-number').nth(1).fill('23')
        page.locator('#practice-button').click()
        page.wait_for_selector('#draw-content:visible')
        assert page.locator('#again-button').is_visible()
        page.locator('#start-button').click()
        page.wait_for_function("() => document.querySelector('#start-button').hidden")
        # 只轻点卡片会锁定，不会立即淘汰；刷新仍恢复同一张卡。
        canvas = page.locator('.scratch-card[data-index="0"] canvas')
        canvas.click(position={"x": 10, "y": 10})
        page.wait_for_function("() => document.querySelector('#draw-notice').textContent.includes('這張卡')")
        state = current_state(page)
        assert state['selected'] == 0 and state['revealed'] == []
        assert state['cards'][1]['person'] is None
        page.reload()
        page.wait_for_selector('#draw-content:visible')
        assert current_state(page)['selected'] == 0
        # 试玩中直接重新开局；旧局仍可恢复，新局没有旧的选择或结果。
        previous = current_state(page)
        page.locator('#again-button').click()
        page.wait_for_selector('#start-button:visible')
        fresh = current_state(page)
        assert fresh['id'] != previous['id']
        assert fresh['participants'] == previous['participants']
        assert fresh['selected'] is None and fresh['revealed'] == [] and fresh['winner'] is None
        assert all(card['person'] is None for card in fresh['cards'])
        page.locator('#start-button').click()
        page.wait_for_function("() => document.querySelector('#start-button').hidden")
        scratch(page, 0)
        state = current_state(page)
        assert state['status'] == 'active' and state['winner'] is None
        assert state['revealed'] == [0]
        page.screenshot(path=str(ARTIFACTS / 'draw-desktop.png'), full_page=True)
        scratch(page, 1)
        page.wait_for_selector('#winner-dialog[open]')
        state = current_state(page)
        assert state['status'] == 'completed' and state['winner']['number'] == state['cards'][2]['person']['number']
        page.screenshot(path=str(ARTIFACTS / 'winner-desktop.png'), full_page=True)
        page.locator('#winner-done').click()
        # 即中式，第一张确认后立即结束。
        page.locator('.nav-item[data-view="setup"]').click()
        page.locator('.mode-option:has(input[value="instant"])').click()
        page.locator('#practice-button').click()
        page.wait_for_selector('#start-button:visible')
        page.locator('#start-button').click()
        page.wait_for_function("() => document.querySelector('#start-button').hidden")
        # 键盘提供逐条擦除，也不依赖鼠标操作。
        for _ in range(5):
            button = page.locator('.scratch-card[data-index="1"] .card-keyboard')
            if button.is_disabled():
                break
            button.focus()
            page.keyboard.press('Enter')
            page.wait_for_timeout(150)
            if page.locator('#winner-dialog[open]').count():
                break
        page.wait_for_selector('#winner-dialog[open]')
        state = current_state(page)
        assert state['status'] == 'completed' and state['revealed'] == [1]
        assert state['winner'] == state['cards'][1]['person']
        page.locator('#winner-done').click()
        if '--sample-randomness' in sys.argv:
            # 定位「总是点第一张」的反馈：实际按按钮新开局并点第一张卡。
            # 仅报告观察值，不用随机分布断言制造偶发失败。
            first_cards = Counter()
            previous_id = state['id']
            for _ in range(30):
                page.locator('#again-button').click()
                page.wait_for_selector('#start-button:visible')
                fresh = current_state(page)
                assert fresh['id'] != previous_id
                previous_id = fresh['id']
                page.locator('#start-button').click()
                page.wait_for_function("() => document.querySelector('#start-button').hidden")
                page.locator('.scratch-card[data-index="0"] canvas').click(position={"x": 10, "y": 10})
                page.wait_for_function("() => document.querySelector('.scratch-card[data-index=\"0\"] .scratch-name').textContent.length > 0")
                selected = current_state(page)
                assert selected['selected'] == 0
                first_cards[selected['cards'][0]['person']['number']] += 1
            print(json.dumps({'new_practice_rounds': 30, 'first_card_number_counts': dict(first_cards)}, ensure_ascii=True), flush=True)
        after = page.evaluate("async () => (await fetch('/api/draws')).json()")
        assert [s['id'] for s in before] == [s['id'] for s in after], '试玩不能创建数据库记录'
        # 移动端所有主要视图无横向溢出。
        page.set_viewport_size({"width": 390, "height": 844})
        for view in ['setup', 'draw', 'history']:
            page.locator(f'.nav-item[data-view="{view}"]').click()
            if view == 'history':
                page.wait_for_timeout(500)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'{view} overflow'
            page.screenshot(path=str(ARTIFACTS / f'{view}-mobile.png'), full_page=True)
        assert not errors, errors
        browser.close()
    print(json.dumps({"browser": "Microsoft Edge", "passed": [
        "page and Supabase connection", "duplicate validation", "partial scratch does not eliminate",
        "selected card survives reload", "practice restart creates fresh round", "real mouse scratching", "elimination last-survivor result",
        "instant-win result", "keyboard scratching", "practice creates no database records",
        "390px responsive views", "no JavaScript errors"], "screenshots": str(ARTIFACTS)}, ensure_ascii=True))


if __name__ == '__main__':
    run()
