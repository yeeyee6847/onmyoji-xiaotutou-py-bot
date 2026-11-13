"""Explicit integration suite; fixtures are isolated in a rolled-back transaction."""
import io
import re
import unittest
import uuid
from types import SimpleNamespace

import numpy as np
from PIL import Image

from app import create_app
from auth_postgres_checks import TransactionStore
from lottery import DrawError
from shards.accounts import GameAccounts
from shards.catalog import PostgresCatalog
from shards.management import FragmentManagement
from shards.samples import SampleLibrary,PortraitMatcher
from shards.vision import image_data
from storage import PostgresStore


class ManagementChecks(unittest.TestCase):
    def setUp(self):
        self.outer=PostgresStore().connection();self.conn=self.outer.__enter__()
        def cleanup():self.conn.rollback();self.outer.__exit__(None,None,None)
        self.addCleanup(cleanup);self.store=TransactionStore(self.conn)
        self.player=str(self.conn.execute("INSERT INTO onmyoji_shards.players(display_name) VALUES ('Feature check') RETURNING id").fetchone()[0])
        self.other=str(self.conn.execute("INSERT INTO onmyoji_shards.players(display_name) VALUES ('Other feature check') RETURNING id").fetchone()[0])
        self.accounts=GameAccounts(self.store);self.fragments=FragmentManagement(self.store);self.samples=SampleLibrary(self.store);self.catalog=PostgresCatalog(self.store)
        self.account=self.accounts.create(self.player,dict(nickname='Main'))
        self.item=self.catalog.list()[0]
        self.user=dict(id=self.player,role='user',password_set=True,display_name='Feature check')
        self.app=create_app(auth_service=SimpleNamespace(current=lambda token:self.user),game_accounts=self.accounts,
                            shard_options=dict(catalog=self.catalog))
        self.client=self.app.test_client();text=self.client.get('/shards').get_data(as_text=True)
        self.csrf=re.search(r'name="csrf-token" content="([^"]+)"',text).group(1)

    def post(self,path,payload):return self.client.post(path,json=payload,headers={'X-CSRF-Token':self.csrf})

    def write(self,quantity,target='offers',player=None):
        return self.fragments.write(player or self.player,dict(game_account_id=self.account['id'],items=[dict(shikigami_id=self.item['id'],target=target,quantity=quantity)]))

    def test_manual_overwrite_zero_scope_and_totals(self):
        self.write(2);self.write(3);self.write(9,'wants')
        data=self.fragments.totals()[self.item['id']]
        self.assertEqual(data,dict(offers=3,wants=9))
        self.write(0);self.assertEqual(self.fragments.totals()[self.item['id']]['offers'],0)
        with self.assertRaises(DrawError):self.write(30,player=self.other)
        public=self.fragments.search(shikigami_id=self.item['id'])
        self.assertEqual(len(public),1);self.assertEqual(public[0]['quantity'],9)
        self.assertNotIn('discord_user_id',public[0]);self.assertNotIn('player_id',public[0])
        self.assertEqual(len(self.fragments.search(mine=self.other)),0)
        self.assertEqual(len(self.fragments.search(server='no such server')),0)

    def test_import_replay_does_not_undo_later_manual_edit(self):
        row=dict(index=1,included=True,confirmed=True,shikigami_id=self.item['id'],quantity=2,raw_name='x',raw_quantity='2',name_confidence=.9,quantity_confidence=.9,bbox=[0,0,30,30],target='offers')
        job=dict(id=str(uuid.uuid4()),source='upload',status='done',filename='x.png',game_account=self.account,rows=[row])
        self.accounts.save_import(self.player,job);self.write(3);self.accounts.save_import(self.player,job)
        self.assertEqual(self.accounts.fragments(self.player,self.account['id'])[0]['quantity'],3)

    def test_delete_is_owned_category_scoped_and_csrf_protected(self):
        self.write(3);self.write(9,'wants')
        body=dict(game_account_id=self.account['id'],shikigami_id=self.item['id'],target='offers')
        self.assertEqual(self.client.post('/api/fragments/delete',json=body).status_code,403)
        self.user['id']=self.other
        self.assertEqual(self.post('/api/fragments/delete',body).status_code,404)
        self.user['id']=self.player
        self.assertEqual(self.post('/api/fragments/delete',dict(body,target='invalid')).status_code,400)
        self.assertEqual(self.post('/api/fragments/delete',body).status_code,200)
        rows=self.fragments.search(mine=self.player,account=self.account['id'])
        self.assertEqual([(r['target'],r['quantity']) for r in rows],[('wants',9)])
        self.assertEqual(self.post('/api/fragments/delete',body).status_code,200)
        self.write(0)
        self.assertEqual(self.post('/api/fragments/delete',body).status_code,200)
        self.assertEqual(len(self.fragments.search(mine=self.player,account=self.account['id'])),1)

    def test_admin_catalog_create_edit_conflicts_and_user_denial(self):
        name='New-'+uuid.uuid4().hex[:12];payload=dict(name=name,name_simplified=name+'S',rarity='UR',image_path='https://example.test/avatar.png')
        self.assertEqual(self.post('/api/shards/catalog',dict(payload,role='admin')).status_code,403)
        self.assertEqual(self.client.get('/admin/samples').status_code,403)
        self.user['role']='admin';expected=self.catalog.next_order()
        response=self.post('/api/shards/catalog',payload);self.assertEqual(response.status_code,201)
        identity=response.json['id'];self.assertEqual(response.json['display_order'],expected)
        changed=dict(payload,name=name+'E',display_order=expected+2,rarity='SSR',image_path='https://example.test/new.png')
        self.assertEqual(self.post('/api/shards/catalog/'+identity,changed).status_code,200)
        self.assertEqual(self.post('/api/shards/catalog',dict(payload,display_order=expected+2)).status_code,409)
        self.assertEqual(self.post('/api/shards/catalog/'+identity,dict(changed,display_order=0)).status_code,400)
        self.assertEqual(self.post('/api/shards/catalog/not-a-uuid',changed).status_code,400)
        self.user['role']='user'
        self.assertEqual(self.post('/api/shards/catalog/'+identity,changed).status_code,403)

    def test_pending_samples_never_match_until_reviewed_and_can_be_disabled(self):
        image=Image.fromarray(np.random.default_rng(12).integers(0,256,(45,60,3),dtype=np.uint8))
        row=dict(index=1,crop=image_data(image),portrait=image_data(image),raw_name='raw',shikigami_id=self.item['id'])
        job=str(uuid.uuid4());self.samples.capture(self.player,job,[row])
        sid=str(self.conn.execute('SELECT id FROM onmyoji_shards.portrait_samples WHERE job_id=%s',(job,)).fetchone()[0])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM onmyoji_shards.portrait_samples WHERE job_id=%s AND status='approved'",(job,)).fetchone()[0],0)
        self.assertEqual(self.client.get('/api/admin/samples/'+sid+'/image').status_code,403)
        self.assertEqual(self.post('/api/admin/samples/'+sid,dict(action='approve',shikigami_id=self.item['id'])).status_code,403)
        self.user['role']='admin'
        self.assertEqual(self.post('/api/admin/samples/'+sid,dict(action='approve',shikigami_id=self.item['id'])).status_code,200)
        stored=self.samples.image(sid,'portrait');self.assertEqual(stored[:8],b'\x89PNG\r\n\x1a\n')
        matcher=PortraitMatcher([(self.item['id'],stored)]);self.assertGreater(matcher.match(stored)[0][1],.99)
        self.assertEqual(self.client.get('/api/admin/samples/'+sid+'/image').status_code,200)
        self.samples.review(self.player,sid,dict(action='reject'))
        self.assertEqual(self.conn.execute('SELECT status FROM onmyoji_shards.portrait_samples WHERE id=%s',(sid,)).fetchone()[0],'rejected')
        self.samples.review(self.player,sid,dict(action='delete'))
        with self.assertRaises(DrawError):self.samples.image(sid,'portrait')

    def test_invalid_manual_batches_are_atomic(self):
        body=dict(game_account_id=self.account['id'],items=[dict(shikigami_id=self.item['id'],target='offers',quantity=2),dict(shikigami_id=self.item['id'],target='wants',quantity=-1)])
        self.assertEqual(self.post('/api/fragments',body).status_code,400)
        self.assertEqual(self.fragments.search(mine=self.player),[])
        body['items'][1]=dict(body['items'][0]);self.assertEqual(self.post('/api/fragments',body).status_code,400)

    def test_approved_portraits_skip_new_duplicates_and_hide_old_pending_copies(self):
        image=Image.fromarray(np.random.default_rng(77).integers(0,250,(45,60,3),dtype=np.uint8))
        row=dict(index=1,crop=image_data(image),portrait=image_data(image),raw_name='raw',shikigami_id=self.item['id'])
        jobs=[str(uuid.uuid4()) for _ in range(5)]
        self.samples.capture(self.player,jobs[0],[row]);self.samples.capture(self.player,jobs[1],[row])
        sid=str(self.conn.execute('SELECT id FROM onmyoji_shards.portrait_samples WHERE job_id=%s',(jobs[0],)).fetchone()[0])
        pending=str(self.conn.execute('SELECT id FROM onmyoji_shards.portrait_samples WHERE job_id=%s',(jobs[1],)).fetchone()[0])
        self.samples.review(self.player,sid,dict(action='approve',shikigami_id=self.item['id']))
        self.samples.capture(self.player,jobs[2],[row])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM onmyoji_shards.portrait_samples WHERE job_id=%s',(jobs[2],)).fetchone()[0],0)
        self.assertNotIn(pending,[r['id'] for r in self.samples.listing()['items']])
        self.assertIsNotNone(self.conn.execute('SELECT id FROM onmyoji_shards.portrait_samples WHERE id=%s',(pending,)).fetchone())
        changed=Image.fromarray(np.random.default_rng(88).integers(0,250,(45,60,3),dtype=np.uint8))
        self.samples.capture(self.player,jobs[3],[dict(row,portrait=image_data(changed))])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM onmyoji_shards.portrait_samples WHERE job_id=%s',(jobs[3],)).fetchone()[0],1)
        other=str(self.conn.execute('SELECT id FROM onmyoji_shards.shikigami WHERE is_active AND id<>%s LIMIT 1',(self.item['id'],)).fetchone()[0])
        self.samples.capture(self.player,jobs[4],[dict(row,shikigami_id=other)])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM onmyoji_shards.portrait_samples WHERE job_id=%s',(jobs[4],)).fetchone()[0],1)
        self.samples.review(self.player,sid,dict(action='reject'))
        self.assertIn(pending,[r['id'] for r in self.samples.listing()['items']])


if __name__=='__main__':unittest.main()
