import re
import unittest

from app import create_app
from test_lottery import MemoryStore, settings
from auth_fixture import SignedInFixture


class EditingTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.client = create_app(self.store, auth_service=SignedInFixture()).test_client()
        html = self.client.get('/').get_data(as_text=True)
        self.token = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    def post(self, path, data):
        return self.client.post(path, json=data, headers={'X-CSRF-Token': self.token})

    def test_repeated_save_updates_one_record_and_preserves_card_positions(self):
        payload = settings()
        created = self.post('/api/draws', payload).json
        original = self.store.get(created['id'])
        for title in ['Changed title', 'Changed again']:
            payload['title'] = title
            updated = self.post(f'/api/draws/{created["id"]}/settings', payload)
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json['id'], created['id'])
            self.assertEqual(updated.json['created_at'], created['created_at'])
            self.assertEqual(updated.json['title'], title)
            self.assertEqual(self.store.get(created['id'])['cards'], original['cards'])
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.client.get('/api/draws').json[0]['title'], 'Changed again')

    def test_ready_roster_mode_and_time_can_change(self):
        payload = settings()
        created = self.post('/api/draws', payload).json
        payload.update(mode='instant', scheduled_at='2030-01-01T12:00:00+00:00',
                       participants=[{'name': 'New A', 'number': 42}, {'name': 'New B', 'number': 99}])
        updated = self.post(f'/api/draws/{created["id"]}/settings', payload)
        self.assertEqual(updated.status_code, 200)
        state = self.store.get(created['id'])
        self.assertEqual(state['participants'], payload['participants'])
        self.assertEqual({card['number'] for card in state['cards']}, {42, 99})
        self.assertEqual(state['mode'], 'instant')
        self.assertTrue(all(card['person'] is None for card in updated.json['cards']))
        self.assertEqual(len(self.store.list()), 1)

    def test_invalid_edit_leaves_original_untouched(self):
        payload = settings()
        created = self.post('/api/draws', payload).json
        original = self.store.get(created['id'])
        payload['participants'][0]['number'] = payload['participants'][1]['number']
        response = self.post(f'/api/draws/{created["id"]}/settings', payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.store.get(created['id']), original)

    def test_active_edit_preserves_selection_and_rejects_rule_changes(self):
        payload = settings()
        created = self.post('/api/draws', payload).json
        base = f'/api/draws/{created["id"]}'
        self.post(base + '/start', {})
        self.post(base + '/select', {'index': 0})
        original = self.store.get(created['id'])
        for key, value in [('mode', 'instant'), ('scheduled_at', '2030-01-01T12:00:00+00:00'),
                           ('participants', payload['participants'][:2])]:
            response = self.post(base + '/settings', {**payload, key: value})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(self.store.get(created['id']), original)
        response = self.post(base + '/settings', {**payload, 'prize': 'Updated gift'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['selected'], 0)
        self.assertEqual(self.store.get(created['id'])['cards'], original['cards'])
        self.assertEqual(response.json['started_at'], original['started_at'])

    def test_completed_metadata_edit_keeps_winner_and_results(self):
        payload = settings('instant')
        created = self.post('/api/draws', payload).json
        base = f'/api/draws/{created["id"]}'
        for action in ['start', 'select', 'reveal']:
            self.post(base + '/' + action, {'index': 0})
        original = self.store.get(created['id'])
        result = self.post(base + '/settings', {**payload, 'host': 'Corrected host'})
        self.assertEqual(result.status_code, 200)
        for key in ['id', 'winner', 'revealed', 'completed_at', 'started_at', 'status']:
            self.assertEqual(result.json[key], original[key])
        self.assertEqual(len(self.store.list()), 1)

    def test_practice_edit_stays_in_memory(self):
        payload = {**settings(), 'practice': True}
        created = self.post('/api/draws', payload).json
        base = f'/api/draws/{created["id"]}'
        response = self.post(base + '/settings', {**payload, 'title': 'Edited trial'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(base + '?practice=1').json['title'], 'Edited trial')
        self.assertEqual(self.store.calls, 0)

    def test_edit_still_requires_csrf_and_existing_id(self):
        created = self.post('/api/draws', settings()).json
        path = f'/api/draws/{created["id"]}/settings'
        self.assertEqual(self.client.post(path, json=settings()).status_code, 403)
        self.assertEqual(self.post(path, []).status_code, 400)
        self.assertEqual(self.post('/api/draws/00000000-0000-0000-0000-000000000000/settings', settings()).status_code, 404)


if __name__ == '__main__':
    unittest.main()
