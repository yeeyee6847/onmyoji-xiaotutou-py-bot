import io
import json
import os
import re
import shutil
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

from app import create_app
from lottery import DrawError
from shards.catalog import MockCatalog
from shards.vision import detect_cards, image_data, load_image, match_name, parse_quantity


def png(image=None):
    stream = io.BytesIO()
    (image or Image.new('RGB', (180, 240), '#514b36')).save(stream, format='PNG')
    return stream.getvalue()


class NoDatabase:
    def __getattr__(self, name):
        raise AssertionError('Shard prototype must not access the database: ' + name)


def fake_inspector(image, catalog, manual, progress):
    progress(1, 2)
    rows = []
    for index in range(2):
        rows.append(dict(id=f'row-{index}', index=index + 1, bbox=[0, 0, 100, 100], crop=image_data(image),
            raw_name=catalog[index]['name'], raw_quantity='5', name_confidence=.96, quantity_confidence=.95,
            shikigami_id=catalog[index]['id'], quantity=5, suggestions=[], included=True, confirmed=False, needs_review=False))
    return rows, ''


class ShardTests(unittest.TestCase):
    def setUp(self):
        workspace = Path(__file__).resolve().parents[1]
        directory = workspace / 'instance'
        directory.mkdir(exist_ok=True)
        target = directory / ('shards-test-' + uuid.uuid4().hex)
        target.mkdir()
        self.temp = SimpleNamespace(name=str(target))
        def cleanup():
            assert target.resolve().is_relative_to(directory.resolve())
            shutil.rmtree(target)
        self.addCleanup(cleanup)
        self.app = create_app(NoDatabase(), shard_options={'root': self.temp.name, 'inspector': fake_inspector})
        self.app.testing = True
        self.client = self.app.test_client()
        html = self.client.get('/shards').get_data(as_text=True)
        self.token = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    def post(self, path, data):
        return self.client.post(path, json=data, headers={'X-CSRF-Token': self.token})

    def upload(self, extra=None):
        return self.client.post('/api/shards/uploads', data={'image': (io.BytesIO(png()), 'long.png'), **(extra or {})},
                                headers={'X-CSRF-Token': self.token})

    def wait_job(self, job_id):
        for _ in range(100):
            job = self.client.get('/api/shards/jobs/' + job_id).json
            if job['status'] in ('done', 'failed'):
                return job
            time.sleep(.01)
        self.fail('background job did not finish')

    def test_public_page_and_mock_role(self):
        self.assertEqual(self.client.get('/shards').status_code, 200)
        info = self.client.get('/api/shards/session').json
        self.assertEqual(info['role'], 'user')
        self.assertTrue(info['mock'])
        self.assertFalse(info['database_written'])
        self.assertEqual(self.client.post('/api/shards/role', json={'role': 'admin'}).status_code, 403)

    def test_admin_catalog_crud_and_alias_collision(self):
        payload = dict(name='Prototype UR', rarity='UR', aliases=['UR alias'], image='')
        self.assertEqual(self.post('/api/shards/catalog', payload).status_code, 403)
        self.post('/api/shards/role', {'role': 'admin'})
        response = self.post('/api/shards/catalog', payload)
        self.assertEqual(response.status_code, 201)
        item = response.json
        self.assertTrue((Path(self.temp.name) / 'catalog.json').is_file())
        self.assertEqual(self.post('/api/shards/catalog', {**payload, 'name': 'Different'}).status_code, 409)
        edited = self.post('/api/shards/catalog/' + item['id'], {**payload, 'name': 'Revised UR'})
        self.assertEqual(edited.json['name'], 'Revised UR')
        self.assertEqual(MockCatalog(self.temp.name).list()[-1]['name'], 'Revised UR')
        self.assertEqual(self.post('/api/shards/catalog/' + item['id'] + '/delete', {}).status_code, 200)
        self.assertFalse(any(row['id'] == item['id'] for row in self.client.get('/api/shards/catalog').json))

    def test_alias_match_is_exact_but_fuzzy_is_only_suggested(self):
        catalog = self.client.get('/api/shards/catalog').json
        matched, suggestions = match_name('花鳥卷', catalog)
        self.assertIsNotNone(matched)
        self.assertEqual(suggestions[0]['name'], '花鸟卷')
        matched, suggestions = match_name('花乌卷', catalog)
        self.assertIsNone(matched)
        self.assertTrue(suggestions)

    def test_quantity_does_not_guess_uncertain_characters(self):
        for raw, expected in [('0', 0), ('1307', 1307), ('1,307', 1307), (' 23 ', 23), ('1?', None), ('I3', None), ('3 7', None), ('', None)]:
            self.assertEqual(parse_quantity(raw), expected)

    def test_upload_review_export_and_session_isolation(self):
        response = self.upload()
        self.assertEqual(response.status_code, 202)
        job = self.wait_job(response.json['id'])
        self.assertEqual(job['status'], 'done')
        self.assertEqual(len(job['rows']), 2)
        self.assertNotIn('owner', job)
        base = '/api/shards/jobs/' + job['id']
        self.assertEqual(self.client.get(base + '/export').status_code, 409)
        other = self.app.test_client()
        self.assertEqual(other.get(base).status_code, 404)
        self.assertEqual(other.get(base + '/image').status_code, 404)
        for row in job['rows']:
            checked = self.post(base + '/rows/' + row['id'], dict(shikigami_id=row['shikigami_id'], quantity=0, included=True, confirmed=True))
            self.assertEqual(checked.status_code, 200)
        exported = self.client.get(base + '/export')
        self.assertEqual(exported.status_code, 200)
        data = json.loads(exported.data)
        self.assertEqual(len(data['items']), 2)
        self.assertEqual(data['items'][0]['quantity'], 0)
        self.assertFalse(data['database_written'])

    def test_duplicates_and_invalid_quantities_blocked(self):
        job = self.wait_job(self.upload().json['id'])
        base = '/api/shards/jobs/' + job['id']
        first = job['rows'][0]['shikigami_id']
        for row in job['rows']:
            path = base + '/rows/' + row['id']
            self.assertEqual(self.post(path, dict(shikigami_id=first, quantity=True, included=True, confirmed=True)).status_code, 400)
            self.assertEqual(self.post(path, dict(shikigami_id=first, quantity=4, included=True, confirmed=True)).status_code, 200)
        self.assertEqual(self.client.get(base + '/export').status_code, 409)
        self.post(base + '/rows/' + job['rows'][1]['id'], dict(included=False, confirmed=False))
        self.assertEqual(self.client.get(base + '/export').status_code, 200)

    def test_demo_is_explicitly_labeled(self):
        response = self.post('/api/shards/demo', {})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['source'], 'demo')
        self.assertIn('预设演示', response.json['warning'])
        self.assertTrue(all(not row['confirmed'] for row in response.json['rows']))

    def test_excluded_unmatched_row_can_be_restored_before_manual_correction(self):
        job = self.post('/api/shards/demo', {}).json
        row = job['rows'][-1]
        path = '/api/shards/jobs/' + job['id'] + '/rows/' + row['id']
        self.assertIsNone(row['shikigami_id'])
        self.assertEqual(self.post(path, dict(included=False, confirmed=False)).status_code, 200)
        restored = self.post(path, dict(included=True, confirmed=False, shikigami_id=None, quantity=None))
        self.assertEqual(restored.status_code, 200)
        self.assertTrue(restored.json['included'])
        self.assertFalse(restored.json['confirmed'])

    def test_images_and_manual_grid_validated(self):
        with self.assertRaises(DrawError):
            load_image(b'not an image')
        self.assertEqual(self.upload({'manual': '1', 'columns': '0', 'rows': '25', 'left': '0', 'right': '90', 'top': '0', 'bottom': '90'}).status_code, 400)

    def test_large_image_upload_uses_shards_limit_without_changing_raffle_limit(self):
        image = Image.frombytes('RGB', (300, 300), os.urandom(300 * 300 * 3))
        content = png(image)
        self.assertGreater(len(content), 128 * 1024)
        response = self.client.post('/api/shards/uploads', data={'image': (io.BytesIO(content), 'larger.png')}, headers={'X-CSRF-Token': self.token})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.wait_job(response.json['id'])['status'], 'done')
        oversized = self.client.post('/api/draws', data=b'x' * (140 * 1024), content_type='application/json', headers={'X-CSRF-Token': self.token})
        self.assertEqual(oversized.status_code, 413)

    def test_image_above_twelve_megabytes_rejected(self):
        content = b'x' * (12 * 1024 * 1024 + 1)
        response = self.client.post('/api/shards/uploads', data=content, content_type='image/png', headers={'X-CSRF-Token': self.token})
        self.assertEqual(response.status_code, 413)

    def test_portrait_upload_requires_admin(self):
        def upload():
            return self.client.post('/api/shards/portraits', data={'image': (io.BytesIO(png()), 'face.png')}, headers={'X-CSRF-Token': self.token})
        self.assertEqual(upload().status_code, 403)
        self.post('/api/shards/role', {'role': 'admin'})
        response = upload()
        self.assertEqual(response.status_code, 200)
        image = self.client.get(response.json['image'])
        self.assertEqual(image.status_code, 200)
        image.close()

    def test_opencv_detects_synthetic_five_column_grid(self):
        image = Image.new('RGB', (600, 600), '#302a20')
        painter = ImageDraw.Draw(image)
        for row in range(3):
            for column in range(5):
                x, y = 40 + column * 110, 50 + row * 170
                painter.rectangle((x, y, x + 62, y + 62), outline='#edaa35', width=3)
        boxes = detect_cards(image)
        self.assertEqual(len(boxes), 15)
        self.assertEqual([round(b[1] / 10) for b in boxes[:5]], [5] * 5)


if __name__ == '__main__':
    unittest.main()
