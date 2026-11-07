import copy
import importlib.util
import io
import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, session

from lottery import DrawError
from shards.catalog import MockCatalog


def create_blueprint(root=None, inspector=None):
    bp = Blueprint('shards', __name__)
    root = Path(root) if root else Path(__file__).resolve().parents[1] / 'instance' / 'shards'
    catalog = MockCatalog(root)
    jobs, lock = {}, threading.RLock()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='shards-ocr')

    def admin():
        if session.get('shards_role', 'user') != 'admin':
            raise DrawError('请先切换到 Admin 演示身分，再管理式神图鉴。', 403)

    def owned(job_id):
        with lock:
            job = jobs.get(job_id)
            if not job or job['owner'] != session['csrf']:
                raise DrawError('这次识别不存在或已过期，请重新上传。', 404)
            return job

    def public(job):
        result = copy.deepcopy({k: v for k, v in job.items() if k not in ('owner', 'image', 'image_mime', '_time')})
        result['image_url'] = f'/api/shards/jobs/{job["id"]}/image'
        return result

    @bp.before_request
    def limits():
        request.max_content_length = 12 * 1024 * 1024

    @bp.get('/shards')
    def page():
        return render_template('shards.html', csrf=session['csrf'])

    @bp.get('/api/shards/session')
    def info():
        return jsonify(role=session.get('shards_role', 'user'), mock=True, database_written=False,
                       ocr_installed=bool(importlib.util.find_spec('rapidocr') and importlib.util.find_spec('onnxruntime')))

    @bp.post('/api/shards/role')
    def role():
        payload = request.get_json()
        if not isinstance(payload, dict) or payload.get('role') not in ('user', 'admin'):
            raise DrawError('演示身分只能是 user 或 admin。')
        session['shards_role'] = payload['role']
        return jsonify(role=payload['role'], mock=True)

    @bp.get('/api/shards/catalog')
    def list_catalog():
        return jsonify(catalog.list())

    @bp.post('/api/shards/catalog')
    def add_catalog():
        admin()
        return jsonify(catalog.save(request.get_json())), 201

    @bp.post('/api/shards/catalog/<item_id>')
    def edit_catalog(item_id):
        admin()
        return jsonify(catalog.save(request.get_json(), item_id))

    @bp.post('/api/shards/catalog/<item_id>/delete')
    def delete_catalog(item_id):
        admin()
        catalog.delete(item_id)
        return jsonify(deleted=True)

    @bp.post('/api/shards/portraits')
    def portrait():
        admin()
        from shards.vision import load_image
        file = request.files.get('image')
        if not file:
            raise DrawError('请选择一张头像图片。')
        image = load_image(file.read(), min_side=16)
        image.thumbnail((512, 512))
        directory = root / 'portraits'
        directory.mkdir(parents=True, exist_ok=True)
        item_id = str(uuid.uuid4())
        image.save(directory / f'{item_id}.webp', format='WEBP', quality=90)
        return jsonify(image=f'/api/shards/portraits/{item_id}')

    @bp.get('/api/shards/portraits/<item_id>')
    def portrait_image(item_id):
        if not re.fullmatch(r'[a-f0-9-]{36}', item_id):
            raise DrawError('找不到头像。', 404)
        path = root / 'portraits' / f'{item_id}.webp'
        if not path.is_file():
            raise DrawError('找不到头像。', 404)
        return send_file(path, mimetype='image/webp')

    def new_job(image, filename, source='upload', original_bytes=None):
        with lock:
            now = time.monotonic()
            # 同一浏览器只保留最近一次识别；全站限制避免 Mock 占用无限内存。
            expired = [key for key, item in jobs.items() if (item['owner'] == session['csrf'] or now - item['_time'] > 3600) and item['status'] not in ('queued', 'processing')]
            for key in expired:
                del jobs[key]
            if len(jobs) >= 12:
                raise DrawError('识别任务已满，请稍后再试。', 429)
            if any(item['owner'] == session['csrf'] and item['status'] in ('queued', 'processing') for item in jobs.values()):
                raise DrawError('已有识别正在进行，请等待这次完成。', 409)
            if original_bytes is None:
                stream = io.BytesIO()
                image.save(stream, format='WEBP', quality=92)
                original_bytes = stream.getvalue()
            mime = 'image/png' if original_bytes.startswith(b'\x89PNG') else 'image/jpeg' if original_bytes.startswith(b'\xff\xd8') else 'image/webp'
            job = dict(id=str(uuid.uuid4()), owner=session['csrf'], _time=now, source=source,
                       filename=filename[:120], width=image.width, height=image.height, status='queued',
                       progress=0, total=0, rows=[], warning='', image=original_bytes, image_mime=mime, database_written=False)
            jobs[job['id']] = job
            return job

    def process(job, manual, snapshot):
        from shards.vision import inspect_image, load_image
        try:
            with lock:
                job['status'] = 'processing'
            image = load_image(job['image'])
            def progress(done, total):
                with lock:
                    job.update(progress=done, total=total)
            rows, warning = (inspector or inspect_image)(image, snapshot, manual, progress)
            with lock:
                job.update(status='done', rows=rows, warning=warning, progress=len(rows), total=len(rows))
        except Exception as error:
            with lock:
                job.update(status='failed', warning=str(error) if isinstance(error, DrawError) else '图片处理失败，请检查图片格式、识别依赖或重新调整切格。')

    @bp.post('/api/shards/uploads')
    def upload():
        from shards.vision import load_image
        file = request.files.get('image')
        if not file:
            raise DrawError('请上传从游戏导出的碎片长图。')
        original_bytes = file.read()
        image = load_image(original_bytes)
        manual = None
        if request.form.get('manual') == '1':
            try:
                manual = {key: float(request.form[key]) for key in ('left', 'top', 'right', 'bottom')}
                manual.update(columns=int(request.form['columns']), rows=int(request.form['rows']))
                if not (2 <= manual['columns'] <= 8 and 1 <= manual['rows'] <= 50 and manual['rows'] * manual['columns'] <= 200
                        and 0 <= manual['left'] < manual['right'] <= 100 and 0 <= manual['top'] < manual['bottom'] <= 100):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise DrawError('切格范围应在 0–100%，列数 2–8、行数 1–50，且不超过 200 格。')
        job = new_job(image, file.filename or '碎片长图', original_bytes=original_bytes)
        executor.submit(process, job, manual, catalog.list())
        return jsonify(public(job)), 202

    @bp.post('/api/shards/demo')
    def demo():
        from PIL import Image, ImageDraw
        from shards.vision import image_data, match_name
        image = Image.new('RGB', (500, 720), '#302b21')
        painter = ImageDraw.Draw(image)
        rows = []
        records = catalog.list()
        for index, (name, quantity) in enumerate([('不知火', '23'), ('玉藻前', '54'), ('茨木童子', '1?'), ('花鳥卷', '18'), ('一目連', '73'), ('未知式神', '6')]):
            x, y = 35 + index % 2 * 235, 50 + index // 2 * 220
            painter.rounded_rectangle((x, y, x + 185, y + 180), radius=12, fill=['#574459', '#3e4f50', '#68543b'][index % 3], outline='#c6a66b', width=3)
            painter.text((x + 28, y + 43), f'DEMO {index+1:02}', fill='#eee4cf', font_size=22)
            painter.text((x + 112, y + 124), quantity, fill='#ffffff', font_size=28)
            matched, suggestions = match_name(name, records)
            rows.append(dict(id=str(uuid.uuid4()), index=index + 1, bbox=[x, y, x + 185, y + 180],
                crop=image_data(image.crop((x, y, x + 185, y + 180))), raw_name=name, raw_quantity=quantity,
                name_confidence=.98 if matched else .53, quantity_confidence=.96 if quantity.isdigit() else .4,
                shikigami_id=matched, quantity=int(quantity) if quantity.isdigit() else None, suggestions=suggestions,
                included=True, confirmed=False, needs_review=not matched or not quantity.isdigit()))
        job = new_job(image, '流程演示 · 非真实 OCR 结果', 'demo')
        job.update(status='done', rows=rows, total=len(rows), progress=len(rows), warning='这些是预设演示资料，用来体验核对流程；不代表对你上传图片的识别结果。')
        return jsonify(public(job)), 201

    @bp.get('/api/shards/jobs/<job_id>')
    def job_detail(job_id):
        return jsonify(public(owned(job_id)))

    @bp.get('/api/shards/jobs/<job_id>/image')
    def job_image(job_id):
        job = owned(job_id)
        return send_file(io.BytesIO(job['image']), mimetype=job['image_mime'])

    @bp.post('/api/shards/jobs/<job_id>/rows/<row_id>')
    def review(job_id, row_id):
        payload = request.get_json()
        if not isinstance(payload, dict):
            raise DrawError('核对资料格式不正确。')
        with lock:
            job = owned(job_id)
            if job['status'] != 'done':
                raise DrawError('请等待识别完成。', 409)
            row = next((item for item in job['rows'] if item['id'] == row_id), None)
            if not row:
                raise DrawError('找不到这条识别结果。', 404)
            included, confirmed = payload.get('included', True), payload.get('confirmed', False)
            if type(included) is not bool or type(confirmed) is not bool:
                raise DrawError('核对状态格式不正确。')
            item_id, quantity = payload.get('shikigami_id'), payload.get('quantity')
            if included:
                if (item_id is not None or confirmed) and not any(item['id'] == item_id for item in catalog.list()):
                    raise DrawError('请先选择图鉴内的式神。')
                if (quantity is not None or confirmed) and (type(quantity) is not int or not 0 <= quantity <= 99999):
                    raise DrawError('碎片数量应为 0–99999 的整数。')
            row.update(shikigami_id=item_id, quantity=quantity, included=included, confirmed=confirmed if included else False)
            return jsonify(copy.deepcopy(row))

    @bp.get('/api/shards/jobs/<job_id>/export')
    def export(job_id):
        with lock:
            job = owned(job_id)
            rows = [row for row in job['rows'] if row['included']]
            if job['status'] != 'done' or not rows or any(not row['confirmed'] for row in rows):
                raise DrawError('请先核对并确认所有要汇出的记录，或排除不需要的条目。', 409)
            records = {item['id']: item for item in catalog.list()}
            items, seen = [], set()
            for row in rows:
                item = records.get(row['shikigami_id'])
                if not item:
                    raise DrawError('图鉴有式神被删除，请重新核对。', 409)
                if item['id'] in seen:
                    raise DrawError(f'「{item["name"]}」重复了，请更正或排除重复条目，不会自动累加数量。', 409)
                seen.add(item['id'])
                items.append(dict(shikigami_id=item['id'], name=item['name'], rarity=item['rarity'], quantity=row['quantity']))
            payload = dict(version=1, generated_at=datetime.now(timezone.utc).isoformat(), source=job['source'],
                           database_written=False, items=items)
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
        return send_file(io.BytesIO(body), mimetype='application/json', as_attachment=True, download_name='shards-reviewed.json')

    return bp
