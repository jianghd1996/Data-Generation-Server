"""Official scene packages: download, unpack, register."""
import argparse
import json
import os
import ssl
from pathlib import Path
import tempfile
from .assets import DEFAULT_ROOT, main as assets_main, write_json
from .people import unpack
from . import assets

SCENES = ['moon', 'namaqualand', 'verdant_trail', 'hidden_alley', 'pine_forest', 'the_shed']


SMALL_SCENES = {
    'classroom': {'url': 'https://download.blender.org/demo/test/classroom.zip',
                  'license': 'CC0-1.0', 'author': 'Christophe Seux'},
    'barcelona_pavilion': {'url': 'https://download.blender.org/demo/test/pabellon_barcelona_v1.scene_.zip',
                          'license': 'CC-BY; see packaged terms and source page', 'author': 'Claudio Andres'},
}


def probe_size(url):
    # A one-byte range exposes full size when supported; otherwise close before reading the body.
    with assets.request(url, {'Range': 'bytes=0-0'}) as response:
        if response.status == 206:
            content_range = response.headers.get('Content-Range', '')
            total = content_range.rsplit('/', 1)[-1]
            if total.isdigit(): return int(total)
        elif response.headers.get('Content-Length'):
            return int(response.headers['Content-Length'])
    raise ValueError('Server did not report archive size; cannot enforce download limit')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Download official Poly Haven or smaller Blender demo scenes')
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--provider', choices=['polyhaven', 'blender'], default='polyhaven')
    parser.add_argument('--ids', nargs='+', choices=SCENES + list(SMALL_SCENES))
    parser.add_argument('--max-download-mib', type=int, help='Per-file limit; Blender defaults to 150 MiB; 0 disables')
    parser.add_argument('--max-unpacked-gib', type=int, default=100)
    parser.add_argument('--insecure', action='store_true')
    parser.add_argument('--ca-bundle', type=Path)
    args = parser.parse_args(argv)
    if args.max_unpacked_gib < 1: parser.error('--max-unpacked-gib must be positive')
    if args.insecure and args.ca_bundle: parser.error('Choose --insecure or --ca-bundle')
    ids = args.ids or (SCENES if args.provider == 'polyhaven' else list(SMALL_SCENES))
    allowed = SCENES if args.provider == 'polyhaven' else SMALL_SCENES
    if any(item not in allowed for item in ids): parser.error('Scene ID does not belong to selected provider')
    limit = args.max_download_mib if args.max_download_mib is not None else (150 if args.provider == 'blender' else 0)
    if limit < 0: parser.error('--max-download-mib must be nonnegative')
    ca = args.ca_bundle or os.environ.get('DGS_CA_BUNDLE') or os.environ.get('SSL_CERT_FILE')
    assets.TLS_CONTEXT = ssl._create_unverified_context() if args.insecure else ssl.create_default_context(cafile=str(ca) if ca else None)
    root = args.root.resolve()
    failures = []
    for scene_id in ids:
        asset_id = args.provider + '_' + scene_id
        info = SMALL_SCENES[scene_id] if args.provider == 'blender' else {'url': f'https://dl.polyhaven.org/file/ph-assets/Scenes/{scene_id}.zip', 'license': 'CC0-1.0'}
        source_url = 'https://www.blender.org/download/demo-files/' if args.provider == 'blender' else 'https://polyhaven.com/collections'
        folder = root / 'scenes/direct' / asset_id
        manifest = {'version': 1, 'assets': [{'provider': 'direct', 'kind': 'scenes', 'id': asset_id,
            'source_url': source_url, 'license': info['license'],
            'files': [{'url': info['url'], 'path': 'scene.zip'}]}]}
        print(f'[scene] {scene_id}', flush=True)
        try:
            if limit:
                archive_size = probe_size(info['url'])
                print(f'[size] {scene_id}: {archive_size / 1048576:.1f} MiB; limit {limit} MiB', flush=True)
                if archive_size > limit * 1048576:
                    raise ValueError('Archive exceeds download limit; skipped without downloading body')
                manifest['assets'][0]['files'][0].update(size=archive_size, max_bytes=limit * 1048576)
            with tempfile.TemporaryDirectory() as temporary:
                manifest_path = Path(temporary) / 'manifest.json'
                write_json(manifest_path, manifest)
                flags = ['download', '--manifest', str(manifest_path), '--root', str(root), '--workers', '1']
                if args.insecure: flags.append('--insecure')
                if args.ca_bundle: flags.extend(['--ca-bundle', str(args.ca_bundle)])
                if assets_main(flags): raise RuntimeError('Download failed; rerun to resume')
            archive = folder / 'scene.zip'
            index = folder / 'extracted/scene-index.json'
            # Successful extraction is reusable. Remove extracted dir to explicitly re-extract.
            from .assets import digest
            reusable = False
            if index.exists():
                previous = json.loads(index.read_text())
                reusable = previous['archive_sha256'] == digest(archive, 'sha256') and all((index.parent / p).is_file() for p in previous['models'])
            paths = previous['models'] if reusable else unpack(archive, folder / 'extracted', 'scene-index.json', args.max_unpacked_gib * 1024 ** 3)
            blends = sorted((Path(p) for p in paths if Path(p).suffix.lower() == '.blend'), key=lambda p: (len(p.parts), str(p)))
            if not blends: raise ValueError('Scene archive has no .blend')
            record = {'id': asset_id, 'path': str((folder / 'extracted' / blends[0]).resolve()),
                'identity': asset_id, 'source_url': source_url, 'license': info['license'], 'author': info.get('author'), 'position': [0, 0, 0], 'enabled': True, 'review': 'pending',
                'notes': 'Check Blender compatibility, choose main .blend, and set position to an open floor point before production.',
                'blend_candidates': [str(folder / 'extracted' / p) for p in blends]}
            registration = folder / 'scene-registration.json'
            if registration.exists():
                old = json.loads(registration.read_text())
                record.update({k: old[k] for k in ('position', 'enabled', 'review', 'notes') if k in old})
            write_json(registration, record)
            print('[ready]', record['path'], flush=True)
        except Exception as exc:
            failures.append({'id': scene_id, 'error': str(exc)})
            print(f'[failed] {scene_id}: {exc}', flush=True)
    write_json(root / 'scene-download-report.json', {'failures': failures})
    return 1 if failures else 0


if __name__ == '__main__': raise SystemExit(main())
