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


def unpack(archive, folder):
    folder.parent.mkdir(parents=True, exist_ok=True)
    if folder.exists() and not (folder / 'people-index.json').exists():
        raise ValueError('Refusing to replace extraction directory without pipeline index')
    with tempfile.TemporaryDirectory(prefix='people-unpack-', dir=folder.parent) as temporary:
        staging = Path(temporary) / 'content'
        staging.mkdir()
        with zipfile.ZipFile(archive) as zipped:
            entries = zipped.infolist()
            if sum(item.file_size for item in entries) > 20 * 1024 ** 3:
                raise ValueError('Archive exceeds 20 GiB extraction limit')
            paths = []
            for item in entries:
                target = safe_path(staging, item.filename.rstrip('/'))
                if stat.S_ISLNK(item.external_attr >> 16):
                    raise ValueError('Archive symlinks are not supported')
                if target in paths:
                    raise ValueError('Duplicate archive paths')
                paths.append(target)
            for item, target in zip(entries, paths):
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(item) as source, target.open('wb') as destination:
                    shutil.copyfileobj(source, destination)
        models = [str(path.relative_to(staging)) for path in sorted(staging.rglob('*'))
                  if path.suffix.lower() in ('.glb', '.gltf', '.blend', '.fbx', '.obj')]
        if not models:
            raise ValueError('No Blender-supported models in archive; choose GLB/Blender/FBX/OBJ format')
        write_json(staging / 'people-index.json', {'archive_sha256': digest(archive, 'sha256'), 'models': models})
        if folder.exists(): shutil.rmtree(folder)
        staging.replace(folder)
    return models


def main(argv=None):
    parser = argparse.ArgumentParser(description='Download Renderpeople sample or supplied Humano3D ZIP')
    parser.add_argument('--provider', choices=['renderpeople', 'humano3d'], default='renderpeople')
    parser.add_argument('--id', help='Unique asset ID for an additional archive; avoids replacing prior samples')
    parser.add_argument('--url', help='Actual authorized ZIP download URL, not product page')
    parser.add_argument('--archive', type=Path, help='Already downloaded local ZIP')
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--insecure', action='store_true')
    parser.add_argument('--ca-bundle', type=Path)
    args = parser.parse_args(argv)
    if args.url and args.archive:
        parser.error('Choose --url or --archive')
    if args.provider == 'humano3d' and not (args.url or args.archive):
        parser.error('Humano3D requires a ZIP URL or archive obtained from its free-sample checkout')
    root = args.root.resolve()
    asset_id = args.id or args.provider + '_free_posed'
    if not re.fullmatch(r'[A-Za-z0-9_-]+', asset_id):
        parser.error('--id must contain only letters, digits, underscores or hyphens')
    folder = root / 'people' / 'direct' / asset_id
    if args.archive:
        archive = args.archive.resolve()
        if not archive.is_file(): parser.error('Archive does not exist')
    else:
        url = args.url or RENDERPEOPLE
        manifest = {'version': 1, 'assets': [{'provider': 'direct', 'kind': 'people', 'id': asset_id,
            'source_url': 'https://renderpeople.com/free-3d-people/' if args.provider == 'renderpeople' else 'https://humano3d.com/free-sample/',
            'license': 'Vendor license; see source website and terms packaged with download. Not CC0.',
            'files': [{'url': url, 'path': 'sample.zip'}]}]}
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / 'people.json'
            write_json(config, manifest)
            flags = ['download', '--manifest', str(config), '--root', str(root), '--workers', '1']
            if args.insecure: flags.append('--insecure')
            if args.ca_bundle: flags.extend(['--ca-bundle', str(args.ca_bundle)])
            if assets_main(flags): return 1
        archive = folder / 'sample.zip'
    models = unpack(archive, folder / 'extracted')
    write_json(folder / 'people-source.json', {'provider': args.provider, 'source_archive': str(archive),
        'source_url': 'https://renderpeople.com/free-3d-people/' if args.provider == 'renderpeople' else 'https://humano3d.com/free-sample/',
        'license': 'Vendor license, not CC0', 'archive_sha256': digest(archive, 'sha256')})
    print('Models ready for --model:')
    for model in models: print(folder / 'extracted' / model)
    return 0


if __name__ == '__main__': raise SystemExit(main())
