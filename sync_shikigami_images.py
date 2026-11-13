"""Match existing Storage filenames to catalogue names; dry run unless --apply.

One-off dependency: python -m pip install pypinyin
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from itertools import product
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from pypinyin import Style, pinyin

from storage import PostgresStore


def match_images(rows, files, base):
    matches, skipped = [], []
    for item_id, name, rarity, previous in rows:
        syllables = pinyin(name, style=Style.NORMAL, heteronym=True, errors=lambda value: [''])
        keys = {re.sub('[^a-z]', '', ''.join(parts)) for parts in product(*syllables)}
        candidates = [f for f in files if len(f.split('/')) == 3
                      and f.split('/')[1] == rarity
                      and PurePosixPath(f).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')
                      and re.sub('[^a-z]', '', PurePosixPath(f).stem.lower()) in keys]
        if len(candidates) != 1:
            skipped.append(dict(id=item_id, name=name, rarity=rarity, candidates=candidates))
            continue
        matches.append(dict(id=item_id, name=name, rarity=rarity, object_path=candidates[0],
                            previous=previous, image_path=base + quote(candidates[0], safe='/')))
    paths = [item['object_path'] for item in matches]
    if len(paths) != len(set(paths)):
        raise RuntimeError('Multiple shikigami matched the same image; no changes made.')
    return matches, skipped


def verify_image(item):
    request = Request(item['image_path'], method='HEAD')
    with urlopen(request, timeout=30) as response:
        if response.status != 200 or not response.headers.get('Content-Type', '').startswith('image/'):
            raise RuntimeError('Invalid image response: ' + item['object_path'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-url', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--make-public', action='store_true', help='Explicit permission to publish the whole onmyoji bucket')
    args = parser.parse_args()
    url = urlsplit(args.project_url)
    if url.scheme != 'https' or not re.fullmatch(r'[a-z0-9]+\.supabase\.co', url.netloc) or url.path not in ('', '/'):
        parser.error('Use the HTTPS Supabase project origin.')
    store = PostgresStore()
    base = args.project_url.rstrip('/') + '/storage/v1/object/public/onmyoji/'
    with store.connection() as conn:
        bucket = conn.execute('SELECT public FROM storage.buckets WHERE id=%s', ('onmyoji',)).fetchone()
        if bucket is None:
            raise RuntimeError('Bucket not found.')
        files = [r[0] for r in conn.execute(
            "SELECT name FROM storage.objects WHERE bucket_id=%s AND name LIKE 'shikigami/%%'", ('onmyoji',)).fetchall()]
        rows = conn.execute('SELECT id::text,name,rarity,image_path FROM onmyoji_shards.shikigami ORDER BY rarity,name').fetchall()
    matches, skipped = match_images(rows, files, base)
    print(json.dumps(dict(matched=len(matches), skipped=skipped, apply=args.apply), ensure_ascii=True))
    if not args.apply:
        return
    report = Path(__file__).parent / 'instance' / ('image-sync-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    report.parent.mkdir(exist_ok=True)
    snapshot = dict(bucket_was_public=bucket[0], matches=matches, skipped=skipped, applied=False)
    report.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
    if not bucket[0]:
        if not args.make_public:
            raise RuntimeError('Bucket is private; explicit --make-public required.')
        with store.connection() as conn:
            conn.execute('UPDATE storage.buckets SET public=true WHERE id=%s', ('onmyoji',))
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(verify_image, matches))
    with store.connection() as conn:
        for item in matches:
            result = conn.execute('''UPDATE onmyoji_shards.shikigami SET image_path=%s
                WHERE id=%s AND name=%s AND rarity=%s AND image_path IS NOT DISTINCT FROM %s''',
                (item['image_path'], item['id'], item['name'], item['rarity'], item['previous']))
            if result.rowcount != 1:
                raise RuntimeError('Catalogue changed during sync; transaction rolled back.')
    snapshot['applied'] = True
    report.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(updated=len(matches), verified_images=len(matches), backup=str(report))))


if __name__ == '__main__':
    main()
