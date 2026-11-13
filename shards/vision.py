"""本地 OpenCV 分格 + 可选 RapidOCR；不包含数据库或 Discord 依赖。"""
import base64
import io
import re
import threading
import uuid
import warnings
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache
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


@lru_cache(maxsize=1)
def name_converter():
    from opencc import OpenCC
    return OpenCC('t2s')


def recognition_name(value):
    return normalized(name_converter().convert(value))


class NameMatcher:
    """Build one catalogue index per import; fuzzy matches stay suggestions."""

    def __init__(self, catalog):
        self.records, self.exact = [], {}
        for item in catalog:
            variants = {recognition_name(value) for value in
                        [item['name'], item.get('name_simplified'), *item.get('aliases', [])] if value}
            variants.discard('')
            self.records.append((item, variants))
            for word in variants:
                self.exact.setdefault(word, {})[item['id']] = item

    def match(self, raw):
        word = recognition_name(raw)
        if not word:
            return None, []
        exact = self.exact.get(word, {})
        if len(exact) == 1:
            item = next(iter(exact.values()))
            return item['id'], [dict(id=item['id'], name=item['name'], score=1.0)]
        suggestions = []
        for item, variants in self.records:
            score = max((SequenceMatcher(None, word, variant).ratio() for variant in variants), default=0)
            suggestions.append(dict(id=item['id'], name=item['name'], score=round(score, 3)))
        suggestions.sort(key=lambda candidate: candidate['score'], reverse=True)
        return None, [s for s in suggestions[:3] if s['score'] >= .45]


def match_name(raw, catalog):
    return NameMatcher(catalog).match(raw)


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


def quantity_consensus(readings):
    """Require agreement of at least two high-confidence crop readings."""
    counts = Counter(parse_quantity(raw) for raw, score in readings
                     if score >= .9 and parse_quantity(raw) is not None)
    ranked = counts.most_common()
    if not ranked or ranked[0][1] < 2 or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
        return None, 0.0
    value = ranked[0][0]
    score = min(score for raw, score in readings if parse_quantity(raw) == value and score >= .9)
    return value, score


def card_section_bands(boxes):
    """Large vertical breaks are section boundaries, not fixed image coordinates."""
    from statistics import median
    if not boxes:
        return []
    ordered = sorted(boxes, key=lambda b: (b[1], b[0]))
    side = median(b[3] for b in ordered)
    row_tops = []
    for _, y, _, _ in ordered:
        if not row_tops or y - row_tops[-1] > side * .5:
            row_tops.append(y)
    breaks = [(0, row_tops[0])]
    for before, after in zip(row_tops, row_tops[1:]):
        if after - before > side * 2.35:
            breaks.append((int(before + side * 1.35), after))
    return breaks


def recognize_section(image, top, bottom):
    """Read heading strips without requiring the large detection OCR model."""
    height = max(28, round(image.width * .075))
    found = []
    for y in range(max(0, top), max(top+1, bottom-height+1), max(12, height//2)):
        crop = image.crop((int(image.width*.22), y, int(image.width*.78), min(bottom,y+height)))
        raw, _ = recognize_line(crop)
        word = recognition_name(raw)
        if any(w in word for w in ('想要', '需要', '需求')):
            found.append('wants')
        elif '提供' in word:
            found.append('offers')
    # A manually cropped grid can begin in the second panel; use the heading nearest its cards.
    return found[-1] if found else None


def inspect_image(image, catalog, manual=None, progress=None, references=None):
    import importlib.util
    boxes = detect_cards(image, manual)
    if not boxes:
        raise DrawError('没有定位到式神卡片。可以展开「调整切格」，指定列数、行数和图内范围后重试。')
    ready = bool(importlib.util.find_spec('rapidocr') and importlib.util.find_spec('onnxruntime'))
    rows, engine_error = [], ''
    matcher = NameMatcher(catalog)
    from shards.samples import PortraitMatcher
    visual=PortraitMatcher(references or [])
    names={item['id']:item['name'] for item in catalog}
    if progress:
        progress(0, len(boxes))
    with _engine_lock:
        sections = []
        for band_index, (top, bottom) in enumerate(card_section_bands(boxes)):
            target = None
            if ready:
                try:
                    target = recognize_section(image, top, bottom)
                except Exception:
                    pass
            # Never silently classify a second, unreadable section as offered fragments.
            sections.append((bottom, target or ('offers' if band_index == 0 else 'unknown')))
        for index, (x, y, w, h) in enumerate(boxes):
            target = next((value for start, value in reversed(sections) if y >= start), 'unknown')
            bounds = (max(0, int(x - w * .23)), y, min(image.width, int(x + w * 1.23)), min(image.height, int(y + h * 1.4)))
            crop = image.crop(bounds)
            portrait=image.crop((int(x+w*.10),int(y+h*.10),int(x+w*.90),int(y+h*.64)))
            raw_name, raw_quantity, name_score, quantity_score = '', '', 0.0, 0.0
            quantity_readings = []
            if ready:
                try:
                    name_crop = image.crop((bounds[0], int(y + h * .99), bounds[2], bounds[3]))
                    # 四位数可能横跨整个头像底部，不能只裁右下角而丢掉前导数字。
                    quantity_crop = image.crop((max(0, int(x + w * .02)), int(y + h * .65), min(image.width, int(x + w * 1.05)), int(y + h * 1.06)))
                    raw_name, name_score = recognize_line(name_crop)
                    raw_quantity, quantity_score = recognize_line(quantity_crop)
                    quantity_readings.append((raw_quantity, quantity_score))
                    for left, top, right, bottom in ((.02,.72,.98,.98), (.43,.72,.98,.98),
                                                     (.35,.68,1.,1.), (.02,.70,1.,1.)):
                        patch = image.crop((int(x+w*left),int(y+h*top),int(x+w*right),int(y+h*bottom)))
                        quantity_readings.append(recognize_line(patch))
                    # Retry name crops only when the first reading cannot be matched exactly.
                    if not matcher.match(raw_name)[0]:
                        alternatives = []
                        for left, top, right, bottom, gray in ((-.23,1.02,1.23,1.26,False),
                                                             (-.23,1.,1.23,1.35,True),
                                                             (-.32,1.,1.32,1.30,False)):
                            patch = image.crop((max(0,int(x+w*left)),int(y+h*top),min(image.width,int(x+w*right)),int(y+h*bottom)))
                            if gray:
                                from PIL import ImageOps
                                patch = ImageOps.autocontrast(ImageOps.grayscale(patch)).convert('RGB')
                            text, score = recognize_line(patch)
                            identity, _ = matcher.match(text)
                            if identity:
                                alternatives.append((identity, text, score))
                        if alternatives and len({a[0] for a in alternatives}) == 1:
                            _, raw_name, name_score = max(alternatives, key=lambda a: a[2])
                except Exception:
                    # 继续提供切格与人工核对，不把未识别的内容冒充为 OCR 结果。
                    engine_error = 'OCR 引擎暂时不可用（依赖或模型尚未就绪），已保留切格结果，请人工选择名字和填写数量。'
                    ready = False
            matched_id, suggestions = matcher.match(raw_name)
            portrait_stream=io.BytesIO();portrait.save(portrait_stream,format='PNG')
            visual_candidates=visual.match(portrait_stream.getvalue()) if visual.references else []
            visual_candidates=[(identity,score) for identity,score in visual_candidates if identity in names]
            visual_conflict=False
            if visual_candidates:
                identity,score=visual_candidates[0]
                strong=score>=.95 and (len(visual_candidates)==1 or score-visual_candidates[1][1]>=.08)
                visual_conflict=bool(strong and matched_id and matched_id!=identity)
                if strong and not matched_id:matched_id=identity
                if not matched_id or visual_conflict:
                    suggestions=[dict(id=i,name=names[i],score=round(s,3)) for i,s in visual_candidates]+suggestions
            quantity, quantity_score = quantity_consensus(quantity_readings)
            rows.append(dict(id=str(uuid.uuid4()), index=index + 1, bbox=list(bounds), crop=image_data(crop),
                             target=target,
                             portrait=image_data(portrait),visual_candidates=[dict(id=i,score=round(s,3)) for i,s in visual_candidates],
                             visual_conflict=visual_conflict,
                             raw_name=raw_name, raw_quantity=raw_quantity, name_confidence=round(name_score, 3),
                             quantity_confidence=round(quantity_score, 3), shikigami_id=matched_id, quantity=quantity,
                             quantity_readings=[dict(raw=text, score=round(score, 3)) for text, score in quantity_readings],
                             suggestions=suggestions, included=True, confirmed=False,
                             needs_review=visual_conflict or target == 'unknown' or not matched_id or quantity is None or min(name_score, quantity_score) < .85))
            if progress:
                progress(index + 1, len(boxes))
    return rows, engine_error or ('' if ready else '尚未安装可选 OCR 引擎。切格已完成，可以人工核对；安装 requirements-ocr.txt 后可启用自动识别。')
