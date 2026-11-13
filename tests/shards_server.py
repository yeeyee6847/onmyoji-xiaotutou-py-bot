"""隔离的浏览器测试服务：假识别器 + 临时图鉴，禁止任何数据库访问。"""
import sys
import shutil
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from auth_fixture import SignedInFixture
from waitress import serve


class NoDatabase:
    def __getattr__(self, name):
        raise AssertionError('Database access is forbidden in shard UI tests: ' + name)


def inspector(image, catalog, manual, progress):
    from shards.vision import image_data
    rows = [dict(id=f'test-row-{i}', index=i+1, bbox=[0, 0, 100, 100], crop=image_data(image),
                 raw_name=item['name'], raw_quantity='12', name_confidence=.95, quantity_confidence=.94,
                 shikigami_id=item['id'], quantity=12, suggestions=[], included=True, confirmed=False, needs_review=False)
            for i, item in enumerate(catalog[:2])]
    return rows, '隔离自动化测试识别器，非真实 OCR 结果。'


if __name__ == '__main__':
    parent = Path(__file__).resolve().parents[1] / 'instance'
    parent.mkdir(exist_ok=True)
    directory = parent / ('shards-browser-' + uuid.uuid4().hex)
    directory.mkdir()
    try:
        app = create_app(NoDatabase(), shard_options={'root': directory, 'inspector': inspector}, auth_service=SignedInFixture())
        print('Isolated shards preview: http://127.0.0.1:5013/shards', flush=True)
        serve(app, host='127.0.0.1', port=5013, threads=4)
    finally:
        assert directory.resolve().is_relative_to(parent.resolve())
        shutil.rmtree(directory)
