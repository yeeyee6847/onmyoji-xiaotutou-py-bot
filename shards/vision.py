"""本地 OpenCV 分格 + 可选 RapidOCR；不包含数据库或 Discord 依赖。"""
import base64
import io
import re
import threading
import uuid
import warnings
from difflib import SequenceMatcher
from pathlib import Path

from lottery import DrawError
from shards.catalog import normalized

_engine = None
_engine_lock = threading.Lock()


def load_image(data, min_side=80):
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in ('PNG', 'JPEG', 'WEBP'):
                    raise DrawError('只支持 PNG、JPG 或 WebP 图片。')
                w, h = source.size
                if w < min_side or h < min_side or w > 6000 or h > 30000 or w * h > 30_000_000:
                    raise DrawError(f'图片尺寸需至少 {min_side}×{min_side}，宽不超过 6000、高不超过 30000，且不超过 3000 万像素。')
                source.load()
                return ImageOps.exif_transpose(source).convert('RGB')
    except DrawError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise DrawError('图片无法读取，请上传完整的游戏原始长图。') from None


def image_data(image):
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()


def detect_cards(image, manual=None):
    import cv2
    import numpy as np
    cv2.setNumThreads(2)
    width, height = image.size
    if not manual:
        scale = min(1.0, 1400 / width, (4_000_000 / (width * height)) ** .5)
        if scale < 1:
            small = image.resize((max(1, round(width * scale)), max(1, round(height * scale))))
            return [tuple(round(value / scale) for value in box) for box in detect_cards(small)]
    if manual:
        columns, rows = manual['columns'], manual['rows']
        left, top, right, bottom = [manual[k] / 100 for k in ('left', 'top', 'right', 'bottom')]
        cell_w = width * (right - left) / columns
        cell_h = height * (bottom - top) / rows
        boxes = []
        for row in range(rows):
            for col in range(columns):
                x = int(width * left + col * cell_w + cell_w * .13)
                y = int(height * top + row * cell_h)
                side = int(min(cell_w * .74, cell_h * .78))
                patch = np.asarray(image.crop((x, y, x + side, y + side)))
                hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
                if np.mean(hsv[:, :, 1] > 65) > .07:
                    boxes.append((x, y, side, side))
        return boxes
    rgb = np.asarray(image)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    # 游戏的红色 SP / 金色 SSR 边框；分类最终以图鉴为准。
    mask = (((hsv[:, :, 0] < 38) | (hsv[:, :, 0] > 167)) & (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 125)).astype('uint8') * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if width * .055 <= w <= width * .18 and .72 <= w / h <= 1.35 and height * .045 < y < height * .97:
            candidates.append((x, y, w, h))
    if not candidates:
        return []
    median = float(np.median([b[2] for b in candidates]))
    groups = []
    for box in sorted(candidates, key=lambda b: b[1]):
        center = box[1] + box[3] / 2
        group = next((g for g in groups if abs(g[0][1] + g[0][3] / 2 - center) < median * .5), None)
        if group is None:
            groups.append([box])
        else:
            group.append(box)
    substantial = [g for g in groups if len(g) >= 2]
    if not substantial:
        return []
    x_centers = [b[0] + b[2] / 2 for g in substantial for b in g]
    results = []
    for group in groups:
        for box in sorted(group):
            if any(abs(box[0] + box[2] / 2 - x) < median * .4 for x in x_centers):
                if not any(abs(box[0] - old[0]) < median * .4 and abs(box[1] - old[1]) < median * .4 for old in results):
                    results.append(box)
    return results[:200]


def match_name(raw, catalog):
    word = normalized(raw)
    suggestions = []
    if not word:
        return None, []
    for item in catalog:
        variants = [normalized(item['name']), *[normalized(a) for a in item['aliases']]]
        score = max(SequenceMatcher(None, word, variant).ratio() for variant in variants)
        suggestions.append({'id': item['id'], 'name': item['name'], 'score': round(score, 3)})
        if word in variants:
            return item['id'], [{'id': item['id'], 'name': item['name'], 'score': 1.0}]
    suggestions.sort(key=lambda candidate: candidate['score'], reverse=True)
    return None, [s for s in suggestions[:3] if s['score'] >= .45]


def parse_quantity(raw):
    raw = raw.strip()
    if re.fullmatch(r'\d{1,3}(,\d{3})+', raw):
        raw = raw.replace(',', '')
    if not re.fullmatch(r'[0-9]{1,5}', raw):
        return None
    return int(raw)


def get_engine():
    global _engine
    if _engine is None:
        from rapidocr import ModelType, OCRVersion, RapidOCR
        _engine = RapidOCR(params={'EngineConfig.onnxruntime.intra_op_num_threads': 2,
                                  'EngineConfig.onnxruntime.inter_op_num_threads': 1,
                                  'Rec.ocr_version': OCRVersion.PPOCRV4, 'Rec.model_type': ModelType.MOBILE,
                                  'Global.model_root_dir': str(Path(__file__).resolve().parents[1] / 'instance' / 'shards' / 'models')})
    return _engine


def recognize_line(image):
    import cv2
    import numpy as np
    frame = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    frame = cv2.resize(frame, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    result = get_engine()(frame, use_det=False, use_cls=False, use_rec=True)
    texts = getattr(result, 'txts', None)
    scores = getattr(result, 'scores', None)
    if texts is None or len(texts) == 0:
        return '', 0.0
    return ''.join(texts), float(min(scores)) if scores is not None and len(scores) else 0.0


def inspect_image(image, catalog, manual=None, progress=None):
    import importlib.util
    boxes = detect_cards(image, manual)
    if not boxes:
        raise DrawError('没有定位到式神卡片。可以展开「调整切格」，指定列数、行数和图内范围后重试。')
    ready = bool(importlib.util.find_spec('rapidocr') and importlib.util.find_spec('onnxruntime'))
    rows, engine_error = [], ''
    if progress:
        progress(0, len(boxes))
    with _engine_lock:
        for index, (x, y, w, h) in enumerate(boxes):
            bounds = (max(0, int(x - w * .23)), y, min(image.width, int(x + w * 1.23)), min(image.height, int(y + h * 1.4)))
            crop = image.crop(bounds)
            raw_name, raw_quantity, name_score, quantity_score = '', '', 0.0, 0.0
            if ready:
                try:
                    name_crop = image.crop((bounds[0], int(y + h * .99), bounds[2], bounds[3]))
                    # 四位数可能横跨整个头像底部，不能只裁右下角而丢掉前导数字。
                    quantity_crop = image.crop((max(0, int(x + w * .02)), int(y + h * .65), min(image.width, int(x + w * 1.05)), int(y + h * 1.06)))
                    raw_name, name_score = recognize_line(name_crop)
                    raw_quantity, quantity_score = recognize_line(quantity_crop)
                except Exception:
                    # 继续提供切格与人工核对，不把未识别的内容冒充为 OCR 结果。
                    engine_error = 'OCR 引擎暂时不可用（依赖或模型尚未就绪），已保留切格结果，请人工选择名字和填写数量。'
                    ready = False
            matched_id, suggestions = match_name(raw_name, catalog)
            quantity = parse_quantity(raw_quantity)
            rows.append(dict(id=str(uuid.uuid4()), index=index + 1, bbox=list(bounds), crop=image_data(crop),
                             raw_name=raw_name, raw_quantity=raw_quantity, name_confidence=round(name_score, 3),
                             quantity_confidence=round(quantity_score, 3), shikigami_id=matched_id, quantity=quantity,
                             suggestions=suggestions, included=True, confirmed=False,
                             needs_review=not matched_id or quantity is None or min(name_score, quantity_score) < .85))
            if progress:
                progress(index + 1, len(boxes))
    return rows, engine_error or ('' if ready else '尚未安装可选 OCR 引擎。切格已完成，可以人工核对；安装 requirements-ocr.txt 后可启用自动识别。')
