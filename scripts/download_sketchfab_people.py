#!/usr/bin/env python3
"""Download Sketchfab people into the DGS inventory (standard library only).

Usage (from repository root, after pip install -e .):
  python scripts/download_sketchfab_people.py --search 'scanned person' --limit 10
  read -rsp 'Sketchfab API token: ' SKETCHFAB_API_TOKEN; echo
  export SKETCHFAB_API_TOKEN
  python scripts/download_sketchfab_people.py --batch --root "$PWD/dataset"
  dgs-dataset inventory --root "$PWD/dataset"

API token from your Sketchfab account settings, or SKETCHFAB_OAUTH_TOKEN for
OAuth. Tokens are read from environment only, never saved. --search lists
candidates; it does NOT download or certify full bodies/texture quality.
--model accepts a UID or Sketchfab model URL; repeat for multiple models.
--batch tries three publicly listed full-body/character scan candidates.
No MetaHuman assets are downloaded by this script.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from data_generation_server.assets import DEFAULT_ROOT, digest, safe_path, write_json
from data_generation_server.people import unpack

API = 'https://api.sketchfab.com/v3/'
CANDIDATES = [
    'c312f5a687f148edb6b3366c88e841b1',  # Human Male Full Body 3D Scan in Color
    '73e467dfc8a04914bb314a9410077858',  # Human scanned with iPhone X
    'e62179794eae4e74b06a8f8f5153c0cc',  # Character Scan Photogrammetry
]


def model_uid(value):
    if re.fullmatch(r'[0-9a-f]{32}', value):
        return value
    url = urllib.parse.urlsplit(value)
    if url.scheme != 'https' or url.hostname not in ('sketchfab.com', 'www.sketchfab.com'):
        raise ValueError('Expected Sketchfab HTTPS model URL or 32-character UID')
    match = re.search(r'(?:-|/)([0-9a-f]{32})/?$', url.path)
    if not match:
        raise ValueError('No model UID in URL')
    return match[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward API credentials to a redirect target.


def get_json(endpoint, context, authorization=None):
    request = urllib.request.Request(API + endpoint, headers={'User-Agent': 'DGS-Asset-Downloader/1.0'})
    if authorization:
        request.add_header('Authorization', authorization)
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
    for attempt in range(3):
        try:
            with opener.open(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                print('[retry] API HTTP', exc.code, flush=True)
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError('Sketchfab API HTTP %s; check token, model availability and account permissions' % exc.code) from None
        except urllib.error.URLError:
            if attempt == 2:
                raise RuntimeError('API connection failed; check network/TLS or use --ca-bundle') from None
            time.sleep(2 ** attempt)


def download_archive(url, target, maximum, context):
    if urllib.parse.urlsplit(url).scheme != 'https':
        raise ValueError('Download API returned a non-HTTPS URL')
    partial = target.with_suffix('.zip.part')
    try:
        # Deliberately no Authorization header on signed asset downloads.
        with urllib.request.urlopen(url, context=context, timeout=120) as response, partial.open('wb') as output:
            length = int(response.headers.get('Content-Length', '0'))
            if length > maximum:
                raise ValueError('Archive exceeds size limit')
            size, last = 0, time.monotonic()
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > maximum:
                    raise ValueError('Archive exceeds size limit while downloading')
                output.write(chunk)
                if time.monotonic() - last >= 2:
                    print('[download] %.1f / %s MiB' % (size / 1048576, '%.1f' % (length / 1048576) if length else '?'), flush=True)
                    last = time.monotonic()
            if not size or (length and size != length):
                raise ValueError('Incomplete archive')
        with zipfile.ZipFile(partial) as archive:
            if archive.testzip() is not None:
                raise ValueError('Archive CRC validation failed')
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def ready(folder):
    archive, index = folder / 'sample.zip', folder / 'extracted/people-index.json'
    if not archive.is_file() or not index.is_file() or not (folder / 'people-source.json').is_file():
        return False
    try:
        data = json.loads(index.read_text())
        return (data['archive_sha256'] == digest(archive, 'sha256') and bool(data['models'])
                and all(safe_path(folder / 'extracted', name).is_file() for name in data['models']))
    except (OSError, ValueError, KeyError):
        return False


def download(uid, root, maximum, unpack_limit, context, authorization):
    folder = root / 'people/direct' / ('sketchfab_' + uid)
    if ready(folder):
        print('[skip]', uid, 'already verified', flush=True)
        return 'skipped'
    metadata = get_json('models/' + uid, context, authorization)
    if not metadata.get('isDownloadable'):
        raise ValueError('Model is not currently downloadable')
    info = get_json('models/' + uid + '/download', context, authorization)
    package = info.get('gltf') or info.get('glb')
    if not package or not package.get('url'):
        raise ValueError('No glTF/GLB archive available through API')
    if package.get('size', 0) > maximum:
        raise ValueError('Archive exceeds configured size limit')
    print('[model]', uid, metadata.get('name'), flush=True)
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / 'sample.zip'
    download_archive(package['url'], archive, maximum, context)
    unpack(archive, folder / 'extracted', max_bytes=unpack_limit)
    author = metadata.get('user') or {}
    # Keep attribution and license; signed download URLs and credentials are excluded.
    write_json(folder / 'people-source.json', {
        'provider': 'sketchfab', 'uid': uid, 'name': metadata.get('name'),
        'source_url': metadata.get('viewerUrl') or 'https://sketchfab.com/models/' + uid,
        'author': {key: author.get(key) for key in ('username', 'displayName', 'profileUrl')},
        'license': metadata.get('license'), 'source_archive': str(archive),
        'archive_sha256': digest(archive, 'sha256'), 'review': 'pending',
    })
    print('[ready]', folder / 'extracted', flush=True)
    return 'ok'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--batch', action='store_true')
    choice.add_argument('--model', action='append', help='Repeat UID or Sketchfab model URL')
    choice.add_argument('--search', help='List downloadable candidates; does not download')
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--max-download-mib', type=float, default=150)
    parser.add_argument('--max-unpack-mib', type=float, default=2048)
    parser.add_argument('--ca-bundle')
    parser.add_argument('--insecure', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 24:
        parser.error('--limit must be 1..24')
    if any(not math.isfinite(v) or v <= 0 for v in (args.max_download_mib, args.max_unpack_mib)):
        parser.error('Size limits must be positive finite numbers')
    context = ssl.create_default_context(cafile=args.ca_bundle)
    if args.insecure:
        print('WARNING: TLS certificate verification disabled.', flush=True)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    oauth = os.environ.get('SKETCHFAB_OAUTH_TOKEN', '').strip()
    token = os.environ.get('SKETCHFAB_API_TOKEN', '').strip()
    authorization = 'Bearer ' + oauth if oauth else ('Token ' + token if token else None)
    if args.search:
        query = urllib.parse.urlencode({'type': 'models', 'q': args.search, 'downloadable': 'true', 'count': args.limit})
        data = get_json('search?' + query, context, authorization)
        for model in data.get('results', [])[:args.limit]:
            print(json.dumps({key: model.get(key) for key in ('uid', 'name', 'viewerUrl', 'license', 'faceCount')}, ensure_ascii=False))
        return 0
    if not authorization:
        parser.error('Set SKETCHFAB_API_TOKEN or SKETCHFAB_OAUTH_TOKEN in your shell; do not send it in chat')
    uids = list(dict.fromkeys(CANDIDATES if args.batch else [model_uid(v) for v in args.model]))
    root, results = args.root.expanduser().resolve(), []
    for uid in uids:
        try:
            status = download(uid, root, int(args.max_download_mib * 1048576), int(args.max_unpack_mib * 1048576), context, authorization)
            results.append({'uid': uid, 'status': status})
        except Exception as exc:
            # Do not print exception URLs: signed query parameters may contain credentials.
            message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
            print('[failed]', uid, message, flush=True)
            results.append({'uid': uid, 'status': 'failed', 'error': message})
        write_json(root / 'sketchfab-people-report.json', {'results': results})
    print('Run dgs-dataset inventory --root', root)
    print('Review previews and people-source.json attribution/license before batch use.')
    return int(any(item['status'] == 'failed' for item in results))


if __name__ == '__main__':
    raise SystemExit(main())
