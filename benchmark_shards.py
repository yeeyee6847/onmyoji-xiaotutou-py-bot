"""Run real OCR on the supplied screenshot, without writing to the database."""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import time

from shards.catalog import PostgresCatalog
from shards.vision import inspect_image, load_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', type=Path, default=Path('artifacts/shards-ocr'))
    args = parser.parse_args()
    data = args.image.read_bytes()
    reference = json.loads(Path('tests/shards_screenshot_reference.json').read_text(encoding='utf-8'))
    if hashlib.sha256(data).hexdigest() != reference['sha256']:
        parser.error('Reference labels apply only to the original 639x3110 screenshot.')
    image = load_image(data)
    catalog = PostgresCatalog().list()
    by_id = {item['id']: item for item in catalog}
    by_name = {item['name']: item for item in catalog}
    absent = {5: '两面佛', 138: '不相狐禅', 139: '洛天依', 140: '言和'}
    start = time.monotonic()
    rows, warning = inspect_image(image, catalog)
    elapsed = time.monotonic() - start
    orders = [v for row in reference['release_orders'] for v in row]
    quantities = [v for row in reference['quantities'] for v in row]
    if len(rows) != len(orders):
        raise RuntimeError('Detected count differs from reference; align boxes manually before scoring.')
    records = []
    for row, order, quantity, name in zip(rows, orders, quantities, reference['expected_names']):
        expected = by_name.get(name)
        actual = by_id.get(row['shikigami_id'])
        records.append(dict(index=row['index'], expected_name=expected['name'] if expected else absent.get(order, str(order)),
                            expected_order=order, expected_quantity=quantity,
                            raw_name=row['raw_name'], matched_name=actual['name'] if actual else '',
                            quantity=row['quantity'], name_correct=bool(actual and expected and actual['id'] == expected['id']),
                            quantity_correct=row['quantity'] == quantity,
                            catalog_missing=expected is None, crop=row['crop']))
    summary = dict(cards=len(rows), catalog_missing=sum(r['catalog_missing'] for r in records),
                   name_correct=sum(r['name_correct'] for r in records),
                   name_wrong=sum(bool(r['matched_name']) and not r['name_correct'] for r in records),
                   quantity_correct=sum(r['quantity_correct'] for r in records),
                   quantity_wrong=sum(r['quantity'] is not None and not r['quantity_correct'] for r in records),
                   quantity_blank=sum(r['quantity'] is None for r in records),
                   both_correct=sum(r['name_correct'] and r['quantity_correct'] for r in records),
                   elapsed_seconds=round(elapsed, 2), warning=warning, database_written=False,
                   limitation='Single manually transcribed development screenshot; not a general accuracy benchmark.')
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'results.json').write_text(json.dumps(dict(summary=summary, rows=rows, reference=records), ensure_ascii=False, indent=2), encoding='utf-8')
    with (args.output / 'results.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        fields = [k for k in records[0] if k != 'crop']
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(records)
    parts = ['<!doctype html><meta charset="utf-8"><title>碎片 OCR 实测</title>',
             '<style>body{font:14px sans-serif;margin:30px}table{border-collapse:collapse}td,th{padding:10px;border:1px solid #ccc}img{max-width:150px}.bad{background:#fff1df}</style>',
             '<h1>碎片 OCR 实测</h1><p>单张原图的人工对照，非通用准确率。所有结果仍需确认，未写入库存数据库。</p>',
             '<pre>' + html.escape(json.dumps(summary, ensure_ascii=False, indent=2)) + '</pre>',
             '<table><tr><th>格</th><th>原图</th><th>人工对照</th><th>自动配对</th><th>数量：识别 / 对照</th></tr>']
    for record in records:
        cls = '' if record['name_correct'] and record['quantity_correct'] else 'bad'
        parts.append(f'<tr class="{cls}"><td>{record["index"]}</td><td><img src="{record["crop"]}"></td>'
                     f'<td>{html.escape(record["expected_name"])}</td><td>{html.escape(record["matched_name"] or "待选")}'
                     f'<br>OCR: {html.escape(record["raw_name"])}</td><td>{record["quantity"]} / {record["expected_quantity"]}</td></tr>')
    (args.output / 'report.html').write_text('\n'.join(parts) + '</table>', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == '__main__':
    main()
