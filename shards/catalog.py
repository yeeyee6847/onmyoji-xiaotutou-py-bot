import copy
import json
import os
import re
import threading
import unicodedata
import uuid
from pathlib import Path

from lottery import DrawError

RARITIES = ('SSR', 'SP', 'UR', 'COLLAB')
SEED = [
    ('少羽大天狗', 'SP', []), ('稻荷神御馔津', 'SP', ['稻荷神御饌津']),
    ('烬天玉藻前', 'SP', ['燼天玉藻前']), ('骁浪荒川之主', 'SP', ['驍浪荒川之主']),
    ('不知火', 'SSR', []), ('玉藻前', 'SSR', []), ('茨木童子', 'SSR', []),
    ('酒吞童子', 'SSR', []), ('花鸟卷', 'SSR', ['花鳥卷']), ('一目连', 'SSR', ['一目連']),
    ('鬼切', 'SSR', []), ('八岐大蛇', 'SSR', []), ('辉夜姬', 'SSR', ['輝夜姬']),
    ('大天狗', 'SSR', []), ('鬼灯', 'COLLAB', ['鬼燈']), ('犬夜叉', 'COLLAB', []),
]


def normalized(text):
    return re.sub(r'[^\w\u3400-\u9fff]', '', unicodedata.normalize('NFKC', text).casefold())


class MockCatalog:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / 'catalog.json'
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return [dict(id=f'seed-{i+1:03}', name=n, rarity=r, aliases=a, image='') for i, (n, r, a) in enumerate(SEED)]
        return json.loads(self.path.read_text(encoding='utf-8'))

    def list(self):
        with self.lock:
            return copy.deepcopy(self._read())

    def save(self, payload, item_id=None):
        if not isinstance(payload, dict):
            raise DrawError('式神资料格式不正确。')
        name, rarity = payload.get('name'), payload.get('rarity')
        aliases, image = payload.get('aliases', []), payload.get('image', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
            raise DrawError('请输入 1–40 字的式神名字。')
        if rarity not in RARITIES:
            raise DrawError('分类必须是 SSR、SP、UR 或联动式神。')
        if not isinstance(aliases, list) or len(aliases) > 20 or any(not isinstance(a, str) or not 1 <= len(a.strip()) <= 40 for a in aliases):
            raise DrawError('识别别名最多 20 个，每个 1–40 字。')
        if not isinstance(image, str) or (image and not re.fullmatch(r'/api/shards/portraits/[a-f0-9-]{36}', image)):
            raise DrawError('请使用上传的头像图片。')
        item = dict(id=item_id or str(uuid.uuid4()), name=name.strip(), rarity=rarity,
                    aliases=list(dict.fromkeys(a.strip() for a in aliases)), image=image)
        with self.lock:
            records = self._read()
            if item_id and not any(r['id'] == item_id for r in records):
                raise DrawError('找不到这位式神。', 404)
            words = {normalized(w) for w in [item['name'], *item['aliases']]}
            for existing in records:
                if existing['id'] != item_id and words.intersection(normalized(w) for w in [existing['name'], *existing['aliases']]):
                    raise DrawError(f'名字或别名与「{existing["name"]}」重复，会造成识别冲突。', 409)
            records = [r for r in records if r['id'] != item_id]
            records.append(item)
            self._write(records)
        return item

    def delete(self, item_id):
        with self.lock:
            records = self._read()
            kept = [r for r in records if r['id'] != item_id]
            if len(kept) == len(records):
                raise DrawError('找不到这位式神。', 404)
            self._write(kept)

    def _write(self, records):
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, self.path)
