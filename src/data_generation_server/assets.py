"""Asset acquisition CLI; Python standard library only."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import ssl
from pathlib import Path
import re
import random
import time
import sys
import threading
from urllib.parse import urlencode, urlparse, unquote
from urllib.request import Request, urlopen
from urllib.error import HTTPError

API = 'https://api.polyhaven.com'
TLS_CONTEXT = None
DEFAULT_ROOT = Path('/mnt/DataPart/jianghongda/related_work/Data-Generation-Server/dataset')

PROGRESS_LOCK = threading.Lock()


def show_progress(target, done, total, started, transferred):
    elapsed = max(time.monotonic() - started, 0.001)
    percent = f'{done / total * 100:5.1f}%' if total else '  ? %'
    filled = min(20, int(done / total * 20)) if total else 0
    bar = '█' * filled + '░' * (20 - filled)
    size = f'{done / 1048576:.1f}' + (f'/{total / 1048576:.1f}' if total else '') + ' MiB'
    with PROGRESS_LOCK:
        print(f'[download] {target.name}: {bar} {percent} | {size} | {transferred / elapsed / 1048576:.2f} MiB/s', file=sys.stderr, flush=True)


UA = 'Data-Generation-Server/0.1 (https://github.com/jianghd1996/Data-Generation-Server)'


def request(url, headers=None):
    if urlparse(url).scheme not in ('http', 'https'):
        raise ValueError('Only HTTP(S) download URLs are supported')
    return urlopen(Request(url, headers={'User-Agent': UA, 'Accept-Encoding': 'identity', **(headers or {})}), timeout=60, context=TLS_CONTEXT)


def api(path):
    for attempt in range(4):
        try:
            with request(API + path) as response:
                return json.load(response)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def safe_path(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or '\\' in str(relative):
        raise ValueError(f'Unsafe relative path: {relative}')
    target = (root / rel).resolve()
    if target == root.resolve() or root.resolve() not in target.parents:
        raise ValueError(f'Path escapes asset directory: {relative}')
    return target


def digest(path, algorithm):
    h = hashlib.new(algorithm)
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify(path, spec):
    if not path.is_file():
        return False
    if spec.get('size') is not None and path.stat().st_size != spec['size']:
        return False
    for algorithm in ('sha256', 'md5'):
        if spec.get(algorithm) and digest(path, algorithm) != spec[algorithm].lower():
            return False
    return True


def download(spec, target):
    """Resume verified files; bind partial bytes to URL and server validator."""
    target.parent.mkdir(parents=True, exist_ok=True)
    receipt = target.with_name(target.name + '.receipt.json')
    if receipt.exists() and target.exists():
        old = json.loads(receipt.read_text())
        if old.get('url') == spec['url'] and verify(target, spec) and digest(target, 'sha256') == old.get('sha256'):
            with PROGRESS_LOCK:
                print(f'[skip] {target.name}: already verified', file=sys.stderr, flush=True)
            return old
    partial = target.with_name(target.name + '.part')
    state = target.with_name(target.name + '.part.json')
    for attempt in range(4):
        try:
            previous = json.loads(state.read_text()) if state.exists() else {}
            offset = partial.stat().st_size if partial.exists() and previous.get('url') == spec['url'] and previous.get('validator') else 0
            headers = {'Range': f'bytes={offset}-', 'If-Range': previous['validator']} if offset else {}
            with PROGRESS_LOCK:
                print(f'[connect] {target.name}: waiting for response (timeout 60s, attempt {attempt + 1}/4)', file=sys.stderr, flush=True)
            with request(spec['url'], headers) as response:
                resumed = offset and response.status == 206
                if response.status == 206:
                    match = re.match(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                    if not match or int(match[1]) != offset:
                        raise ValueError('Invalid Content-Range')
                    expected = int(match[3])
                else:
                    expected = int(response.headers['Content-Length']) if response.headers.get('Content-Length') else None
                if spec.get('max_bytes') and expected is not None and expected > spec['max_bytes']:
                    raise ValueError('Download exceeds configured size limit')
                write_json(state, {'url': spec['url'], 'validator': response.headers.get('ETag') or response.headers.get('Last-Modified')})
                total = spec.get('size') or expected
                done = offset if resumed else 0
                transferred = 0
                started = time.monotonic()
                last_update = started
                show_progress(target, done, total, started, transferred)
                with partial.open('ab' if resumed else 'wb') as out:
                    while block := (getattr(response, 'read1', response.read))(64 * 1024):
                        if spec.get('max_bytes') and done + len(block) > spec['max_bytes']:
                            raise ValueError('Download exceeds configured size limit')
                        out.write(block)
                        done += len(block)
                        transferred += len(block)
                        if time.monotonic() - last_update >= 1:
                            show_progress(target, done, total, started, transferred)
                            last_update = time.monotonic()
                show_progress(target, done, total, started, transferred)
            if expected is not None and partial.stat().st_size != expected:
                raise ValueError('Incomplete response')
            if not verify(partial, spec):
                partial.unlink(missing_ok=True)
                state.unlink(missing_ok=True)
                raise ValueError('Size or checksum mismatch')
            partial.replace(target)
            state.unlink(missing_ok=True)
            result = {'url': spec['url'], 'size': target.stat().st_size, 'sha256': digest(target, 'sha256')}
            write_json(receipt, result)
            return result
        except Exception as exc:
            with PROGRESS_LOCK:
                print(f'[retry] {target.name}: attempt {attempt + 1}/4 failed: {exc}', file=sys.stderr, flush=True)
            if attempt == 3:
                raise
            if isinstance(exc, HTTPError) and exc.code == 416:
                partial.unlink(missing_ok=True)
                state.unlink(missing_ok=True)
            # A fully received partial may yield HTTP 416 on retry: restart it.
            if partial.exists() and spec.get('size') == partial.stat().st_size:
                partial.unlink()
                state.unlink(missing_ok=True)
            time.sleep(2 ** attempt)


def resolve(asset):
    if asset['provider'] == 'direct':
        if not asset.get('license') or not asset.get('source_url'):
            raise ValueError('Direct assets require license and source_url')
        files = asset['files']
        return {'source_url': asset['source_url'], 'license': asset['license']}, files
    if asset['provider'] != 'polyhaven':
        raise ValueError('Unknown provider')
    slug = asset['id']
    tree = api('/files/' + slug)
    info = api('/info/' + slug)
    resolution = asset.get('resolution', '2k')
    kind = asset['kind']
    fmt = asset.get('format', 'hdr' if kind == 'hdris' else 'blend')
    key = 'hdri' if kind == 'hdris' else fmt
    try:
        selected = tree[key][resolution][fmt]
    except KeyError:
        raise ValueError(f'{slug}: unavailable {key}/{resolution}/{fmt}; inspect with files command') from None
    name = unquote(Path(urlparse(selected['url']).path).name)
    files = [{'path': name, **{k: v for k, v in selected.items() if k != 'include'}}]
    for relative, dependency in selected.get('include', {}).items():
        files.append({'path': relative, **dependency})
    return {'source_url': 'https://polyhaven.com/a/' + slug, 'license': 'CC0-1.0', 'info': info}, files


def validate_assets(assets):
    seen = set()
    for asset in assets:
        if asset['provider'] not in ('polyhaven', 'direct'):
            raise ValueError('Unknown provider')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', asset['id']):
            raise ValueError('Asset IDs must contain only letters, digits, _ and -')
        if asset['kind'] not in ('models', 'hdris', 'textures', 'scenes', 'people'):
            raise ValueError('Invalid asset kind')
        key = (asset['provider'], asset['kind'], asset['id'])
        if key in seen:
            raise ValueError(f'Duplicate asset: {key}')
        seen.add(key)


def acquire(asset, root, dry_run=False):
    folder = root / asset['kind'] / asset['provider'] / asset['id']
    metadata, files = resolve(asset)
    if not files:
        raise ValueError('Asset has no files')
    paths = [safe_path(folder, f['path']) for f in files]
    if len(paths) != len(set(paths)):
        raise ValueError('Duplicate download paths')
    result = {'asset': asset, **metadata, 'files': []}
    for spec, path in zip(files, paths):
        record = {**spec, 'path': str(path.relative_to(folder)), 'dataset_path': str(path.relative_to(root))}
        if not dry_run:
            record.update(download(spec, path))
        result['files'].append(record)
    if not dry_run:
        write_json(folder / 'asset.json', result)
    return result



def build_manifest(catalog, kind, query='', limit=20, seed=0, resolution='2k', fmt=None):
    if limit < 1:
        raise ValueError('limit must be positive')
    candidates = [slug for slug, info in sorted(catalog.items())
                  if info.get('date_published', 0) <= time.time()
                  and (not query or query.lower() in (slug + ' ' + json.dumps(info, ensure_ascii=False)).lower())]
    random.Random(seed).shuffle(candidates)
    assets = [{'provider': 'polyhaven', 'id': slug, 'kind': kind,
               'resolution': resolution, 'format': fmt or ('hdr' if kind == 'hdris' else 'blend')}
              for slug in candidates[:limit]]
    if not assets:
        raise ValueError('No matching published assets')
    return {'version': 1, 'selection': {'query': query, 'seed': seed, 'requested': limit,
                                      'matched': len(candidates)}, 'assets': assets}


def audit(root):
    results = []
    for metadata in sorted(root.glob('*/*/*/asset.json')):
        errors = []
        try:
            data = json.loads(metadata.read_text())
            files = data['files']
            if not files:
                errors.append('No files recorded')
            for spec in files:
                path = safe_path(metadata.parent, spec['path'])
                if not verify(path, spec):
                    errors.append(f"Missing or corrupt: {spec['path']}")
            results.append({'metadata': str(metadata.relative_to(root)), 'asset': data['asset'],
                            'ok': not errors, 'errors': errors})
        except Exception as exc:
            results.append({'metadata': str(metadata.relative_to(root)), 'ok': False, 'errors': [str(exc)]})
    partials = [str(p.relative_to(root)) for p in sorted(root.rglob('*.part'))]
    return {'version': 1, 'scope': 'download integrity only; not Blender load/render validation',
            'assets': results, 'partials': partials, 'ok': bool(results) and all(r['ok'] for r in results) and not partials}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Asset downloads — Powered by Poly Haven')
    sub = parser.add_subparsers(dest='command', required=True)
    search = sub.add_parser('search', help='List Poly Haven assets, optionally filter keywords')
    search.add_argument('--type', choices=['models', 'hdris', 'textures'], default='models')
    search.add_argument('--query', default='')
    search.add_argument('--limit', type=int, default=20)
    search.add_argument('--output', type=Path)
    inspect = sub.add_parser('files', help='Inspect available Poly Haven resolutions/formats')
    inspect.add_argument('id')
    fetch = sub.add_parser('download')
    fetch.add_argument('--manifest', type=Path, required=True)
    fetch.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    fetch.add_argument('--workers', type=int, default=2)
    fetch.add_argument('--dry-run', action='store_true')
    batch = sub.add_parser('manifest', help='Generate a reproducible Poly Haven batch manifest')
    batch.add_argument('--type', choices=['models', 'hdris', 'textures'], default='models')
    batch.add_argument('--query', default='')
    batch.add_argument('--limit', type=int, default=20)
    batch.add_argument('--seed', type=int, default=0)
    batch.add_argument('--resolution', default='2k')
    batch.add_argument('--format')
    batch.add_argument('--output', type=Path, required=True)
    check = sub.add_parser('verify', help='Offline audit of completed assets and partial downloads')
    check.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    check.add_argument('--output', type=Path)
    for command_parser in (search, inspect, fetch, batch):
        command_parser.add_argument('--ca-bundle', type=Path, help='PEM CA bundle; defaults to DGS_CA_BUNDLE or SSL_CERT_FILE')
        command_parser.add_argument('--insecure', action='store_true', help='Disable TLS verification for this invocation')
    args = parser.parse_args(argv)
    if args.command == 'verify':
        report = audit(args.root.resolve())
        write_json(args.output or args.root / 'verification-report.json', report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['ok'] else 1
    global TLS_CONTEXT
    ca_bundle = args.ca_bundle or os.environ.get('DGS_CA_BUNDLE') or os.environ.get('SSL_CERT_FILE')
    if args.insecure and ca_bundle:
        parser.error('--insecure cannot be combined with a CA bundle')
    TLS_CONTEXT = ssl._create_unverified_context() if args.insecure else ssl.create_default_context(cafile=str(ca_bundle) if ca_bundle else None)
    if args.insecure:
        print('WARNING: TLS certificate verification is disabled for this invocation.')
    if args.command == 'manifest':
        catalog = api('/assets?' + urlencode({'type': args.type}))
        manifest = build_manifest(catalog, args.type, args.query, args.limit, args.seed, args.resolution, args.format)
        write_json(args.output, manifest)
        print(f"Wrote {len(manifest['assets'])} assets to {args.output}")
        return 0
    if args.command == 'files':
        print(json.dumps(api('/files/' + args.id), indent=2)); return 0
    if args.command == 'search':
        catalog = api('/assets?' + urlencode({'type': args.type}))
        query = args.query.lower()
        rows = [{'id': slug, **info} for slug, info in sorted(catalog.items()) if query in json.dumps(info, ensure_ascii=False).lower() or query in slug.lower()][:max(0, args.limit)]
        if args.output:
            write_json(args.output, rows)
        print(json.dumps(rows, ensure_ascii=False, indent=2)); return 0
    if args.workers < 1 or args.workers > 16:
        parser.error('--workers must be between 1 and 16')
    manifest = json.loads(args.manifest.read_text())
    if manifest.get('version') != 1:
        raise ValueError('Manifest version must be 1')
    assets = manifest['assets']
    validate_assets(assets)
    root = args.root.resolve()
    results, errors = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(acquire, a, root, args.dry_run): a for a in assets}
        for job in concurrent.futures.as_completed(jobs):
            asset = jobs[job]
            try:
                results.append(job.result())
                print(f"OK {asset['id']}")
            except Exception as exc:
                message = str(exc)
                if 'CERTIFICATE_VERIFY_FAILED' in message:
                    message += '; Supply your server/proxy CA with --ca-bundle /path/to/ca.pem (or DGS_CA_BUNDLE). Temporary diagnostic fallback: --insecure.'
                errors.append({'asset': asset, 'error': message})
                print(f"FAILED {asset['id']}: {message}")
    report = {'version': 1, 'dry_run': args.dry_run, 'results': sorted(results, key=lambda x: x['asset']['id']), 'errors': errors}
    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        write_json(root / 'download-report.json', report)
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
