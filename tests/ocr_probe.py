"""显式运行的真实 OCR 合成图片检查；不读取数据库或用户图片。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw, ImageFont
from shards.vision import parse_quantity, recognize_line


def run():
    font_path = Path('C:/Windows/Fonts/msyh.ttc')
    if not font_path.exists():
        raise SystemExit('此本机探测脚本需要 Microsoft YaHei 字体；不影响 Web OCR 使用。')
    results = []
    for expected in ('不知火', '1307', '花鸟卷', '0'):
        image = Image.new('RGB', (220, 65), '#393328')
        draw = ImageDraw.Draw(image)
        draw.text((12, 5), expected, font=ImageFont.truetype(str(font_path), 38), fill='#fff9e7', stroke_width=1, stroke_fill='#19170f')
        text, score = recognize_line(image)
        result = dict(expected=expected, recognized=text, score=round(score, 3), needs_manual=False)
        results.append(result)
        if text != expected:
            if expected == '0' and parse_quantity(text) is None:
                result['needs_manual'] = True
            else:
                raise AssertionError(json.dumps(results, ensure_ascii=True))
    print(json.dumps({'real_local_ocr': True, 'input': 'synthetic clear text, not the user game screenshot', 'results': results}, ensure_ascii=True))


if __name__ == '__main__':
    run()
