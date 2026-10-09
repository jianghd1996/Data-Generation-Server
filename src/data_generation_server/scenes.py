"""Official complete Poly Haven scene packages: download, unpack, register."""
import argparse
import json
from pathlib import Path
import tempfile
from .assets import DEFAULT_ROOT, main as assets_main, write_json
from .people import unpack

SCENES = ['moon', 'namaqualand', 'verdant_trail', 'hidden_alley', 'pine_forest', 'the_shed']


def main(argv=None):
    parser = argparse.ArgumentParser(description='Download complete official Poly Haven scenes')
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--ids', nargs='+', choices=SCENES, default=SCENES)
    parser.add_argument('--max-unpacked-gib', type=int, default=100)
    parser.add_argument('--insecure', action='store_true')
    parser.add_argument('--ca-bundle', type=Path)
    args = parser.parse_args(argv)
    if args.max_unpacked_gib < 1: parser.error('--max-unpacked-gib must be positive')
    root = args.root.resolve()
    failures = []
    for scene_id in args.ids:
        asset_id = 'polyhaven_' + scene_id
        folder = root / 'scenes/direct' / asset_id
        manifest = {'version': 1, 'assets': [{'provider': 'direct', 'kind': 'scenes', 'id': asset_id,
            'source_url': 'https://polyhaven.com/collections', 'license': 'CC0-1.0',
            'files': [{'url': f'https://dl.polyhaven.org/file/ph-assets/Scenes/{scene_id}.zip', 'path': 'scene.zip'}]}]}
        print(f'[scene] {scene_id}: complete archive may be several GiB', flush=True)
        try:
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
                'identity': asset_id, 'position': [0, 0, 0], 'enabled': True, 'review': 'pending',
                'notes': 'Check Blender compatibility, choose main .blend, and set position to an open floor point before production.',
                'blend_candidates': [str(folder / 'extracted' / p) for p in blends]}
            write_json(folder / 'scene-registration.json', record)
            print('[ready]', record['path'], flush=True)
        except Exception as exc:
            failures.append({'id': scene_id, 'error': str(exc)})
            print(f'[failed] {scene_id}: {exc}', flush=True)
    write_json(root / 'scene-download-report.json', {'failures': failures})
    return 1 if failures else 0


if __name__ == '__main__': raise SystemExit(main())
