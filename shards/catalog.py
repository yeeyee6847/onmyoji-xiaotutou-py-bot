import copy
import json
import os
import re
import threading
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import urlsplit

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


class PostgresCatalog:
    """Read the real catalogue without granting demo roles database writes."""

    def __init__(self, store=None):
        from storage import PostgresStore
        self.store = store if store is not None else PostgresStore()

    def list(self):
        with self.store.connection() as conn:
            rows = conn.execute('''
                SELECT s.id::text, s.name, s.rarity, s.image_path,
                       COALESCE(array_agg(a.alias ORDER BY a.alias)
                                FILTER (WHERE a.alias IS NOT NULL), ARRAY[]::text[]),
                       s.display_order, s.name_simplified
                FROM onmyoji_shards.shikigami s
                LEFT JOIN onmyoji_shards.shikigami_aliases a ON a.shikigami_id = s.id
                WHERE s.is_active
                GROUP BY s.id
                ORDER BY s.display_order DESC NULLS LAST, s.name, s.id
            ''').fetchall()
        return [dict(id=row[0], name=row[1], rarity=row[2],
                     image=row[3] if row[3] and row[3].startswith('https://') else '',
                     aliases=row[4], display_order=row[5], name_simplified=row[6]) for row in rows]

    def save(self,payload,item_id=None):
        if not isinstance(payload,dict):raise DrawError('资料格式不正确。')
        name,simple,rarity=payload.get('name'),payload.get('name_simplified'),payload.get('rarity')
        if any(not isinstance(v,str) or not 1<=len(v.strip())<=40 for v in (name,simple)):
            raise DrawError('繁体与简体名字都需要填写，最多 40 字。')
        if rarity not in RARITIES:raise DrawError('请选择正确 Rarity。')
        image=payload.get('image_path',payload.get('image',''))
        if not isinstance(image,str) or len(image)>2048:raise DrawError('图片路径格式不正确。')
        image=image.strip()
        if image:
            try:parsed=urlsplit(image)
            except ValueError:raise DrawError('图片网址格式不正确。') from None
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
                raise DrawError('图片路径需要完整的 HTTPS 图片网址。')
        order=payload.get('display_order')
        if order not in (None,'') and (type(order) is not int or not 1<=order<=2147483647):
            raise DrawError('排序编号需要为正整数。')
        try:identity=str(uuid.UUID(item_id)) if item_id else str(uuid.uuid4())
        except ValueError:raise DrawError('无效的式神编号。') from None
        with self.store.connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('shikigami-catalog',0))")
            if item_id and not conn.execute('SELECT id FROM onmyoji_shards.shikigami WHERE id=%s AND is_active',(identity,)).fetchone():
                raise DrawError('找不到式神。',404)
            if order in (None,''):order=conn.execute('SELECT coalesce(max(display_order),0)+1 FROM onmyoji_shards.shikigami').fetchone()[0]
            if order>2147483647:raise DrawError('排序编号超出范围。')
            if conn.execute('SELECT 1 FROM onmyoji_shards.shikigami WHERE id<>%s AND (lower(name)=lower(%s) OR display_order=%s)',(identity,name.strip(),order)).fetchone():
                raise DrawError('名字或排序编号已被使用，请修改后重试。',409)
            aliases=payload.get('aliases',[])
            if not isinstance(aliases,list) or len(aliases)>20 or any(not isinstance(a,str) or not 1<=len(a.strip())<=40 for a in aliases):
                raise DrawError('别名最多 20 个，每个 1–40 字。')
            other=conn.execute('''SELECT s.name,s.name_simplified,a.alias FROM onmyoji_shards.shikigami s
             LEFT JOIN onmyoji_shards.shikigami_aliases a ON a.shikigami_id=s.id WHERE s.id<>%s''',(identity,)).fetchall()
            words={normalized(v) for v in [name,simple,*aliases]}
            if any(words.intersection(normalized(v) for v in r if v) for r in other):
                raise DrawError('名字或别名与其他式神重复。',409)
            conn.execute('''INSERT INTO onmyoji_shards.shikigami(id,name,name_simplified,rarity,image_path,display_order)
             VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name,
             name_simplified=EXCLUDED.name_simplified,rarity=EXCLUDED.rarity,image_path=EXCLUDED.image_path,display_order=EXCLUDED.display_order''',
             (identity,name.strip(),simple.strip(),rarity,image or None,order))
            conn.execute('DELETE FROM onmyoji_shards.shikigami_aliases WHERE shikigami_id=%s',(identity,))
            for alias in dict.fromkeys(a.strip() for a in aliases):
                conn.execute('INSERT INTO onmyoji_shards.shikigami_aliases(shikigami_id,alias) VALUES (%s,%s)',(identity,alias))
        return dict(id=identity,name=name.strip(),name_simplified=simple.strip(),rarity=rarity,image=image,display_order=order,aliases=aliases)

    def next_order(self):
        with self.store.connection() as conn:
            return conn.execute('SELECT coalesce(max(display_order),0)+1 FROM onmyoji_shards.shikigami').fetchone()[0]

    def delete(self,item_id):
        try:identity=str(uuid.UUID(item_id))
        except ValueError:raise DrawError('无效的式神编号。') from None
        with self.store.connection() as conn:
            if conn.execute('UPDATE onmyoji_shards.shikigami SET is_active=false WHERE id=%s AND is_active',(identity,)).rowcount!=1:
                raise DrawError('找不到式神。',404)


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
