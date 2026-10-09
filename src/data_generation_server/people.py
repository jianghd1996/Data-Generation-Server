"""Download and unpack official posed-human samples."""
import argparse
import json
import re
from pathlib import Path
import shutil
import stat
import tempfile
import zipfile
from .assets import DEFAULT_ROOT, main as assets_main, digest, safe_path, write_json

RENDERPEOPLE = 'https://renderpeople.com/sample/free/rp_posed_00178_29_GLB.zip'


def unpack(archive, folder, index_name='people-index.json', max_bytes=20 * 1024 ** 3, expand_nested=False):
    folder.parent.mkdir(parents=True, exist_ok=True)
    if folder.exists() and not (folder / index_name).exists():
        raise ValueError('Refusing to replace extraction directory without pipeline index')
    with tempfile.TemporaryDirectory(prefix='people-unpack-', dir=folder.parent) as temporary:
        staging = Path(temporary) / 'content'
        staging.mkdir()
        queue = [(archive, staging, 0)]
        expanded_bytes = 0
        while queue:
            current_archive, destination_root, depth = queue.pop(0)
            with zipfile.ZipFile(current_archive) as zipped:
                entries = zipped.infolist()
                expanded_bytes += sum(item.file_size for item in entries)
                if expanded_bytes > max_bytes:
                    raise ValueError('Archive exceeds configured extraction limit (including nested ZIPs)')
                paths = set()
                for item in entries:
                    target = safe_path(destination_root, item.filename.rstrip('/'))
                    if stat.S_ISLNK(item.external_attr >> 16):
                        raise ValueError('Archive symlinks are not supported')
                    if target in paths or (target.exists() and not item.is_dir()):
                        raise ValueError('Duplicate archive paths')
                    paths.add(target)
                    if item.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zipped.open(item) as source, target.open('wb') as destination:
                        shutil.copyfileobj(source, destination)
                    if expand_nested and target.suffix.lower() == '.zip':
                        if depth >= 4:
                            raise ValueError('Nested ZIP depth exceeds 4')
                        nested_root = target.with_name(target.name + '_unpacked')
                        if nested_root.exists():
                            raise ValueError('Nested ZIP output path already exists')
                        nested_root.mkdir()
                        queue.append((target, nested_root, depth + 1))
        models = [str(path.relative_to(staging)) for path in sorted(staging.rglob('*'))
                  if path.suffix.lower() in ('.glb', '.gltf', '.blend', '.fbx', '.obj')]
        if not models:
            raise ValueError('No Blender-supported models in archive; choose GLB/Blender/FBX/OBJ format')
        write_json(staging / index_name, {'archive_sha256': digest(archive, 'sha256'), 'models': models})
        if folder.exists(): shutil.rmtree(folder)
        staging.replace(folder)
    return models


def main(argv=None):
    parser = argparse.ArgumentParser(description='Download Renderpeople sample or supplied Humano3D ZIP')
    parser.add_argument('--batch', action='store_true', help='Download official new and classic posed packs')
    parser.add_argument('--manifest', type=Path, help='Batch JSON: assets with id, provider, url or archive')
    parser.add_argument('--archive-dir', type=Path, help='Import all ZIPs in a directory')
    parser.add_argument('--source-url', help='Source page for supplied archives')
    parser.add_argument('--license', default='Vendor license, not CC0')
    parser.add_argument('--provider', choices=['renderpeople', 'humano3d'], default='renderpeople')
    parser.add_argument('--id', help='Unique asset ID for an additional archive; avoids replacing prior samples')
    parser.add_argument('--url', help='Actual authorized ZIP download URL, not product page')
    parser.add_argument('--archive', type=Path, help='Already downloaded local ZIP')
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--insecure', action='store_true')
    parser.add_argument('--ca-bundle', type=Path)
    args = parser.parse_args(argv)
    if args.batch or args.manifest or args.archive_dir:
        if sum(bool(x) for x in (args.batch, args.manifest, args.archive_dir)) != 1 or args.url or args.archive or args.id:
            parser.error('Choose one batch input; do not combine with --url/--archive/--id')
        return batch(args)
    if args.url and args.archive:
        parser.error('Choose --url or --archive')
    if args.provider == 'humano3d' and not (args.url or args.archive):
        parser.error('Humano3D requires a ZIP URL or archive obtained from its free-sample checkout')
    root = args.root.resolve()
    asset_id = args.id or args.provider + '_free_posed'
    if not re.fullmatch(r'[A-Za-z0-9_-]+', asset_id):
        parser.error('--id must contain only letters, digits, underscores or hyphens')
    source_url = args.source_url or ('https://renderpeople.com/free-3d-people/' if args.provider == 'renderpeople' else 'https://humano3d.com/free-sample/')
    folder = root / 'people' / 'direct' / asset_id
    if args.archive:
        archive = args.archive.resolve()
        if not archive.is_file(): parser.error('Archive does not exist')
    else:
        url = args.url or RENDERPEOPLE
        manifest = {'version': 1, 'assets': [{'provider': 'direct', 'kind': 'people', 'id': asset_id,
            'source_url': source_url,
            'license': args.license,
            'files': [{'url': url, 'path': 'sample.zip'}]}]}
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / 'people.json'
            write_json(config, manifest)
            flags = ['download', '--manifest', str(config), '--root', str(root), '--workers', '1']
            if args.insecure: flags.append('--insecure')
            if args.ca_bundle: flags.extend(['--ca-bundle', str(args.ca_bundle)])
            if assets_main(flags): return 1
        archive = folder / 'sample.zip'
    extracted = folder / 'extracted'
    index = extracted / 'people-index.json'
    previous = json.loads(index.read_text()) if index.exists() else {}
    if previous.get('archive_sha256') == digest(archive, 'sha256') and previous.get('models') and all(safe_path(extracted, m).is_file() for m in previous['models']):
        models = previous['models']
        print(f'[skip] {asset_id}: already extracted')
    else:
        models = unpack(archive, extracted, expand_nested=True)
    write_json(folder / 'people-source.json', {'provider': args.provider, 'source_archive': str(archive),
        'source_url': source_url,
        'license': args.license, 'archive_sha256': digest(archive, 'sha256')})
    print('Models ready for --model:')
    for model in models: print(folder / 'extracted' / model)
    return 0


def batch(args):
    if args.batch:
        entries = [
            {'id': 'renderpeople_free_posed', 'provider': 'renderpeople', 'url': RENDERPEOPLE},
            {'id': 'renderpeople_classic_posed', 'provider': 'renderpeople',
             'url': 'https://renderpeople.com/sample/free/renderpeople_free_posed_people_OBJ.zip'},
        ]
    elif args.manifest:
        data = json.loads(args.manifest.read_text())
        entries = data['assets']
        for entry in entries:
            if entry.get('archive'):
                entry['archive'] = str((args.manifest.resolve().parent / entry['archive']).resolve())
    else:
        if not args.archive_dir.is_dir():
            raise ValueError('Archive directory does not exist')
        entries = [{'id': 'local_' + re.sub(r'[^A-Za-z0-9_-]', '_', path.stem),
                    'provider': args.provider, 'archive': str(path.resolve())}
                   for path in sorted(args.archive_dir.iterdir()) if path.suffix.lower() == '.zip']
    if not entries:
        raise ValueError('No people archives specified')
    ids = [entry['id'] for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate archive IDs; give each archive a unique ID')
    for entry in entries:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', entry['id']):
            raise ValueError('Invalid archive ID')
        if bool(entry.get('url')) == bool(entry.get('archive')):
            raise ValueError('Each entry needs exactly one URL or archive')
        if entry.get('provider', args.provider) not in ('renderpeople', 'humano3d'):
            raise ValueError('Unsupported provider')
    results = []
    root = args.root.resolve()
    for entry in entries:
        flags = ['--root', str(root), '--provider', entry.get('provider', args.provider), '--id', entry['id']]
        for key in ('url', 'archive', 'source_url', 'license'):
            if entry.get(key): flags.extend(['--' + key.replace('_', '-'), str(entry[key])])
        if args.source_url and not entry.get('source_url'): flags.extend(['--source-url', args.source_url])
        if not entry.get('license'): flags.extend(['--license', args.license])
        if args.insecure: flags.append('--insecure')
        if args.ca_bundle: flags.extend(['--ca-bundle', str(args.ca_bundle)])
        try:
            code = main(flags)
            if code: raise RuntimeError('Archive download failed')
            result = {'id': entry['id'], 'status': 'ok'}
        except Exception as exc:
            result = {'id': entry['id'], 'status': 'failed', 'error': str(exc)}
            print(f"FAILED {entry['id']}: {exc}")
        results.append(result)
        write_json(root / 'people-batch-report.json', {'results': results, 'archive_count': len(entries)})
    print('Run dgs-dataset inventory, ; archive/model file counts are not unique person counts.')
    return int(any(result['status'] == 'failed' for result in results))


if __name__ == '__main__': raise SystemExit(main())
