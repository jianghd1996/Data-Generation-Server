#!/usr/bin/env python3
"""Quarantine the five rejected objects and Classroom; report other clutter.
Run without --apply for a preview. Stop all render/download workers first.
No permanent deletion. Backups live outside dataset in dataset-cleanup-TIMESTAMP.
Other models, people (including Carla), scenes, backgrounds and videos are kept.
"""
import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess

OBJECTS = {'fir_sapling', 'mantel_clock_01', 'nettle_plant', 'searsia_lucida', 'shrub_sorrel_01'}
SCENE = 'blender_classroom'


def rejected(entry, category):
    uid = entry.get('id', '')
    return uid in OBJECTS if category == 'objects' else uid == SCENE if category == 'scenes' else False


def bad_job(job):
    return rejected(job.get('subject', {}), 'objects') or rejected(job.get('scene', {}), 'scenes')


def atomic_json(path, data):
    tmp = path.with_name(path.name + '.cleanup-tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('dataset'))
    p.add_argument('--apply', action='store_true')
    args = p.parse_args(argv)
    root = args.root.expanduser().resolve()
    catalog_path = root / 'catalog.json'
    catalog = json.loads(catalog_path.read_text())
    moves, edits = set(), {}
    updated = copy.deepcopy(catalog)
    for category in ('objects', 'scenes'):
        selected = [item for item in catalog[category] if rejected(item, category)]
        for item in selected:
            path = Path(item['path']).resolve()
            base = root / ('models' if category == 'objects' else 'scenes')
            marker = 'asset.json' if category == 'objects' else 'scene-registration.json'
            parents = [parent for parent in path.parents if parent.is_relative_to(base) and (parent / marker).is_file()]
            if not parents:
                raise ValueError('Cannot identify managed asset directory: ' + str(path))
            moves.add(parents[0])
            print('[asset]', category, item['id'], parents[0])
        updated[category] = [item for item in updated[category] if not rejected(item, category)]
    if updated != catalog:
        edits[catalog_path] = updated
    # Only edit top-level JSON files with an actual render-plan jobs list.
    # Reports and gallery indexes are left intact as historical evidence.
    for path in sorted(root.glob('*.json')):
        if path == catalog_path:
            continue
        try:
            data = json.loads(path.read_text())
        except (ValueError, OSError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get('jobs'), list):
            continue
        removed = [job for job in data['jobs'] if bad_job(job)]
        if not removed:
            continue
        modified = copy.deepcopy(data)
        modified['jobs'] = [job for job in data['jobs'] if not bad_job(job)]
        if 'subject_scene_pairs' in modified:
            modified['subject_scene_pairs'] = len(modified['jobs']) // 6
        edits[path] = modified
        print('[plan]', path.name, 'remove', len(removed), 'jobs')
        for job in removed:
            output = Path(job.get('output', '')).resolve()
            if output.is_relative_to(root / 'renders') and output != root / 'renders' and output.is_dir():
                moves.add(output)
            if data.get('video_dir'):
                video = (Path(data['video_dir']) / (job['id'] + '.mp4')).resolve()
                if video.is_relative_to(root / 'videos') and video.is_file():
                    moves.add(video)
    # Reject parent overlaps and symlink escape before any mutations.
    ordered = sorted(moves, key=lambda value: len(value.parts))
    moves = [path for i, path in enumerate(ordered) if not any(path.is_relative_to(parent) for parent in ordered[:i])]
    for path in moves:
        if not path.is_relative_to(root) or path == root or path.is_symlink():
            raise ValueError('Unsafe move: ' + str(path))
    print('[summary]', len(moves), 'paths to quarantine;', len(edits), 'JSON files to update')
    if args.apply and (moves or edits):
        backup = root.parent / (root.name + '-cleanup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir()
        journal = {'root': str(root), 'backups': [], 'moves': []}
        for path in edits:
            target = backup / 'json-backups' / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            journal['backups'].append({'original': str(path), 'backup': str(target)})
        atomic_json(backup / 'cleanup-journal.json', journal)
        # Prune plans before moving sources so rerunning these plans cannot use rejected assets.
        for path, data in edits.items():
            atomic_json(path, data)
        for path in moves:
            target = backup / 'quarantined' / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            journal['moves'].append({'original': str(path), 'quarantine': str(target), 'status': 'pending'})
            atomic_json(backup / 'cleanup-journal.json', journal)
            shutil.move(str(path), str(target))
            journal['moves'][-1]['status'] = 'done'
            atomic_json(backup / 'cleanup-journal.json', journal)
        print('[saved]', backup)
        print('Regenerate preview plan/gallery and batch plan. Historical indexes may reference quarantined files.')
    elif not args.apply:
        print('Preview only. Use --apply after stopping all render/download workers.')
    print('\n[top-level disk usage; other files are NOT deleted]')
    paths = sorted(root.iterdir())
    if paths:
        subprocess.run(['du', '-sh', '--', *map(str, paths)], check=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
