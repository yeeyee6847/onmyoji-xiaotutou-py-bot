import base64
import io

from lottery import DrawError
from shards.accounts import account_id
from storage import PostgresStore


def portrait_descriptor(data):
    import cv2
    import numpy as np
    from PIL import Image
    im=Image.open(io.BytesIO(data)).convert('RGB').resize((40,40))
    rgb=np.asarray(im).astype('float32')/255
    gray=cv2.cvtColor(np.asarray(im),cv2.COLOR_RGB2GRAY)
    edges=cv2.Sobel(gray,cv2.CV_32F,1,0)+cv2.Sobel(gray,cv2.CV_32F,0,1)
    return rgb,edges


class PortraitMatcher:
    def __init__(self,references):
        self.references=[(identity,portrait_descriptor(data)) for identity,data in references]

    def match(self,data):
        import cv2
        import numpy as np
        descriptor=portrait_descriptor(data)
        scores={}
        for identity,other in self.references:
            # Compare normalized colors and edges; frame/number pixels are excluded in the crop.
            color=float(cv2.matchTemplate(descriptor[0],other[0],cv2.TM_CCOEFF_NORMED)[0,0])
            edge=float(cv2.matchTemplate(descriptor[1],other[1],cv2.TM_CCOEFF_NORMED)[0,0]) if min(np.std(descriptor[1]),np.std(other[1]))>.01 else 0.
            textured=min(np.std(other[0],axis=(0,1)).mean(),np.std(descriptor[0],axis=(0,1)).mean())>.02
            score=max(0.,min(1.,color*.75+edge*.25)) if textured else 0.
            scores[identity]=max(scores.get(identity,0),score)
        return sorted(scores.items(),key=lambda r:r[1],reverse=True)[:3]


class SampleLibrary:
    def __init__(self,store=None):self.store=store if store is not None else PostgresStore()

    def _approved(self,conn):
        return [(identity,portrait_descriptor(bytes(data))) for identity,data in conn.execute('''
         SELECT s.shikigami_id::text,s.portrait_png FROM onmyoji_shards.portrait_samples s
         JOIN onmyoji_shards.shikigami k ON k.id=s.shikigami_id WHERE s.status='approved' AND k.is_active''').fetchall()]

    @staticmethod
    def _duplicate(data,predicted,approved):
        import cv2
        import numpy as np
        if not approved:return False
        rgb,_=portrait_descriptor(data)
        for identity,(reference,_) in approved:
            # Keep OCR/portrait identity conflicts for review rather than hiding them.
            if predicted and predicted!=identity:continue
            if np.array_equal(rgb,reference):return True
            # Strict near-duplicate tolerance for compression/resizing; similarity alone is insufficient.
            if float(np.mean((rgb-reference)**2))<=.0005 and np.std(reference,axis=(0,1)).mean()>.02:
                score=float(cv2.matchTemplate(rgb,reference,cv2.TM_CCOEFF_NORMED)[0,0])
                if score>=.995:return True
        return False

    def references(self):
        with self.store.connection() as conn:
            rows=conn.execute('''SELECT s.shikigami_id::text,s.portrait_png FROM onmyoji_shards.portrait_samples s
             JOIN onmyoji_shards.shikigami k ON k.id=s.shikigami_id
             WHERE s.status='approved' AND k.is_active ORDER BY s.created_at DESC LIMIT 3000''').fetchall()
        return [(r[0],bytes(r[1])) for r in rows]

    def capture(self,player_id,job_id,rows):
        with self.store.connection() as conn:
            approved=self._approved(conn)
            for row in rows:
                if not row.get('portrait'):continue
                crop=base64.b64decode(row['crop'].split(',',1)[1],validate=True)
                portrait=base64.b64decode(row['portrait'].split(',',1)[1],validate=True)
                if max(len(crop),len(portrait))>262144:continue
                if self._duplicate(portrait,row.get('shikigami_id'),approved):continue
                conn.execute('''INSERT INTO onmyoji_shards.portrait_samples
                 (player_id,job_id,row_number,crop_png,portrait_png,raw_name,shikigami_id)
                 VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(job_id,row_number) DO NOTHING''',
                 (player_id,job_id,row['index'],crop,portrait,row['raw_name'],row['shikigami_id']))

    def listing(self,status='pending',page=1):
        if status not in ('pending','approved','rejected','all'):raise DrawError('无效的样本状态。')
        if type(page) is not int or not 1<=page<=10000:raise DrawError('无效页数。')
        where='' if status=='all' else ' WHERE x.status=%s'
        args=[] if status=='all' else [status]
        with self.store.connection() as conn:
            if status=='pending':
                approved=self._approved(conn)
                # Hide older queued duplicates too, including ones queued before approval.
                # Retain the records: disabling/deleting the reference makes them reviewable again.
                hidden=[str(identity) for identity,predicted,data in conn.execute(
                    "SELECT id,shikigami_id::text,portrait_png FROM onmyoji_shards.portrait_samples WHERE status='pending'").fetchall()
                    if self._duplicate(bytes(data),predicted,approved)] if approved else []
                if hidden:
                    where+=' AND NOT (x.id=ANY(%s::uuid[]))';args.append(hidden)
            total=conn.execute('SELECT count(*) FROM onmyoji_shards.portrait_samples x'+where,args).fetchone()[0]
            rows=conn.execute('''SELECT x.id::text,x.raw_name,x.shikigami_id::text,x.status,k.name
             FROM onmyoji_shards.portrait_samples x LEFT JOIN onmyoji_shards.shikigami k ON k.id=x.shikigami_id'''+where+
             ' ORDER BY x.created_at DESC,x.id LIMIT 40 OFFSET %s',args+[(page-1)*40]).fetchall()
        return dict(total=total,page=page,items=[dict(id=r[0],raw_name=r[1],shikigami_id=r[2],status=r[3],name=r[4]) for r in rows])

    def image(self,identity,kind):
        identity=account_id(identity)
        column='portrait_png' if kind=='portrait' else 'crop_png'
        with self.store.connection() as conn:
            row=conn.execute('SELECT '+column+' FROM onmyoji_shards.portrait_samples WHERE id=%s',(identity,)).fetchone()
        if not row:raise DrawError('找不到样本。',404)
        return bytes(row[0])

    def review(self,admin_id,identity,payload):
        identity=account_id(identity)
        if not isinstance(payload,dict) or payload.get('action') not in ('approve','reject','delete'):raise DrawError('无效的审核操作。')
        action=payload['action'];shikigami=account_id(payload.get('shikigami_id')) if action=='approve' else None
        with self.store.connection() as conn:
            if shikigami and not conn.execute('SELECT id FROM onmyoji_shards.shikigami WHERE id=%s AND is_active',(shikigami,)).fetchone():
                raise DrawError('请选择有效式神。')
            if action=='delete':result=conn.execute('DELETE FROM onmyoji_shards.portrait_samples WHERE id=%s',(identity,))
            else:result=conn.execute('''UPDATE onmyoji_shards.portrait_samples SET status=%s,shikigami_id=%s,
             reviewed_by=%s,reviewed_at=now() WHERE id=%s''',('approved' if action=='approve' else 'rejected',shikigami,admin_id,identity))
            if result.rowcount!=1:raise DrawError('找不到样本。',404)
        return dict(saved=True)
