"""Explicit real-DB checks; all test records roll back."""
import io
import re
import time
import unittest
import uuid
from types import SimpleNamespace

from PIL import Image

from app import create_app
from lottery import DrawError
from shards.accounts import GameAccounts
from storage import PostgresStore
from auth_postgres_checks import TransactionStore


class GameAccountChecks(unittest.TestCase):
    def setUp(self):
        self.outer = PostgresStore().connection()
        self.conn = self.outer.__enter__()
        def cleanup():
            self.conn.rollback()
            self.outer.__exit__(None,None,None)
        self.addCleanup(cleanup)
        self.service = GameAccounts(TransactionStore(self.conn))
        self.player = str(self.conn.execute("INSERT INTO onmyoji_shards.players(display_name) VALUES ('Account check') RETURNING id").fetchone()[0])
        self.other = str(self.conn.execute("INSERT INTO onmyoji_shards.players(display_name) VALUES ('Other account check') RETURNING id").fetchone()[0])
        self.shikigami = str(self.conn.execute('SELECT id FROM onmyoji_shards.shikigami WHERE is_active LIMIT 1').fetchone()[0])

    def job(self, account, quantity=15):
        return dict(id=str(uuid.uuid4()),source='upload',status='done',filename='test.png',game_account=account,
                    rows=[dict(index=1,included=True,confirmed=True,shikigami_id=self.shikigami,quantity=quantity,
                               raw_name='raw',raw_quantity=str(quantity),name_confidence=.95,quantity_confidence=.97,bbox=[0,0,30,40])])

    def test_multiple_accounts_duplicate_and_owner_validation(self):
        first = self.service.create(self.player,dict(nickname='First'))
        second = self.service.create(self.player,dict(nickname='Second',player_id=self.other))
        self.assertEqual(len(self.service.list(self.player)),2)
        self.assertEqual(self.service.list(self.other),[])
        self.assertEqual(self.service.owned(self.player,second['id'])['nickname'],'Second')
        with self.assertRaises(DrawError): self.service.owned(self.other,first['id'])
        with self.assertRaises(DrawError): self.service.create(self.player,dict(nickname='First'))
        with self.assertRaises(DrawError): self.service.create(self.player,dict(nickname=' '))
        with self.assertRaises(DrawError): self.service.owned(self.player,'bad-uuid')

    def test_confirmed_import_persists_once_and_latest_quantity_is_not_added(self):
        account = self.service.create(self.player,dict(nickname='First'))
        first = self.job(account,15)
        self.service.save_import(self.player,first)
        self.service.save_import(self.player,first)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM onmyoji_shards.fragment_import_rows WHERE import_id=%s',(first['id'],)).fetchone()[0],1)
        self.assertEqual(self.service.fragments(self.player,account['id'])[0]['quantity'],15)
        self.conn.execute("UPDATE onmyoji_shards.fragment_imports SET created_at=now()-interval '1 minute' WHERE id=%s",(first['id'],))
        self.service.save_import(self.player,self.job(account,7))
        self.assertEqual(self.service.fragments(self.player,account['id'])[0]['quantity'],7)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM onmyoji_shards.fragment_offers WHERE game_account_id=%s',(account['id'],)).fetchone()[0],0)

    def test_incomplete_demo_duplicates_and_foreign_account_rejected(self):
        account = self.service.create(self.player,dict(nickname='First'))
        job = self.job(account)
        with self.assertRaises(DrawError): self.service.save_import(self.other,job)
        with self.assertRaises(DrawError): self.service.fragments(self.other,account['id'])
        job['rows'][0]['confirmed'] = False
        with self.assertRaises(DrawError): self.service.save_import(self.player,job)
        job['rows'][0]['confirmed'] = True
        job['source'] = 'demo'
        with self.assertRaises(DrawError): self.service.save_import(self.player,job)
        job['source'] = 'upload'
        job['rows'].append(dict(job['rows'][0],index=2))
        with self.assertRaises(DrawError): self.service.save_import(self.player,job)

    def test_wants_and_offers_are_persisted_in_separate_imports_atomically(self):
        account=self.service.create(self.player,dict(nickname='Two lists'))
        job=self.job(account,3)
        job['rows'][0]['target']='offers'
        job['rows'].append(dict(job['rows'][0],index=2,target='wants',quantity=57))
        result=self.service.save_import(self.player,job)
        self.assertEqual(set(result['import_ids']),{'offers','wants'})
        self.service.save_import(self.player,job)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM onmyoji_shards.fragment_imports WHERE game_account_id=%s',(account['id'],)).fetchone()[0],2)
        self.assertEqual({r['target']:r['quantity'] for r in self.service.fragments(self.player,account['id'])},{'offers':3,'wants':57})

    def test_upload_account_binding_confirmation_save_and_export(self):
        account = self.service.create(self.player,dict(nickname='First'))
        foreign = self.service.create(self.other,dict(nickname='Foreign'))
        user = dict(id=self.player,role='user',display_name='test',password_set=True)
        catalog = SimpleNamespace(list=lambda:[dict(id=self.shikigami,name='Test',rarity='SSR',aliases=[],image='')])
        def inspector(image, snapshot, manual, progress):
            row = self.job(account)['rows'][0]
            row.update(id='row-one',crop='',suggestions=[],needs_review=False,confirmed=False)
            return [row],''
        app = create_app(auth_service=SimpleNamespace(current=lambda token:user),game_accounts=self.service,
                         shard_options=dict(catalog=catalog,inspector=inspector))
        client = app.test_client()
        page = client.get('/shards').get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"',page).group(1)
        headers = {'X-CSRF-Token':token}
        def upload(value):
            data=io.BytesIO(); Image.new('RGB',(180,180)).save(data,format='PNG');data.seek(0)
            return client.post('/api/shards/uploads',data={'game_account_id':value,'image':(data,'test.png')},headers=headers)
        self.assertEqual(upload('').status_code,400)
        self.assertEqual(upload(foreign['id']).status_code,404)
        response = upload(account['id']);self.assertEqual(response.status_code,202)
        job_id=response.json['id'];self.assertEqual(response.json['game_account']['id'],account['id'])
        for _ in range(30):
            state=client.get('/api/shards/jobs/'+job_id).json
            if state['status']=='done':break
            time.sleep(.02)
        base='/api/shards/jobs/'+job_id
        self.assertEqual(client.post(base+'/save',json={},headers=headers).status_code,409)
        reviewed=client.post(base+'/rows/row-one',json=dict(included=True,confirmed=True,shikigami_id=self.shikigami,quantity=15),headers=headers)
        self.assertEqual(reviewed.status_code,200)
        self.assertEqual(client.post(base+'/save',json={},headers=headers).status_code,200)
        exported=client.get(base+'/export').json
        self.assertEqual(exported['game_account']['id'],account['id'])
        self.assertTrue(exported['database_written'])
        self.assertEqual(client.post(base+'/rows/row-one',json={},headers=headers).status_code,409)
        self.assertEqual(client.get('/api/game-accounts/'+account['id']+'/fragments').json[0]['quantity'],15)
        user['id']=self.other
        self.assertEqual(client.get(base).status_code,404)


if __name__ == '__main__':
    unittest.main()
