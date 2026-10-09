"""Inventory, review, expansion manifests, and resumable render job planning."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import random
import re
import subprocess
import sys
from .assets import DEFAULT_ROOT, api, build_manifest, digest, safe_path, verify, write_json

EXTENSIONS = {'.blend': 0, '.glb': 1, '.fbx': 2, '.obj': 3, '.gltf': 4}


def inventory(root, previous=None):
    catalog = {'version': 1, 'root': str(root), 'objects': [], 'people': [], 'scenes': [], 'backgrounds': []}
    old = {category: {entry['id']: entry for entry in (previous or {}).get(category, [])} for category in catalog if category not in ('version', 'root')}
    def add(category, entry):
        entry.update({key: value for key, value in old[category].get(entry['id'], {}).items()
                      if key in ('enabled', 'review', 'notes', 'heading', 'position', 'size', 'chest', 'knee', 'identity')})
        entry.setdefault('enabled', True)
        entry.setdefault('review', 'pending')
        catalog[category].append(entry)
    for metadata in sorted((root / 'models').glob('*/*/asset.json')):
        data = json.loads(metadata.read_text())
        paths = [safe_path(metadata.parent, spec['path']) for spec in data['files']]
        if not all(verify(path, spec) for path, spec in zip(paths, data['files'])): continue
        models = sorted((p for p in paths if p.suffix.lower() in EXTENSIONS), key=lambda p: EXTENSIONS[p.suffix.lower()])
        if models:
            add('objects', {'id': data['asset']['id'], 'path': str(models[0]), 'sha256': digest(models[0], 'sha256')})
    for category, directory, suffixes in [('people', 'people', set(EXTENSIONS)), ('scenes', 'scenes', {'.blend'}), ('backgrounds', 'hdris', {'.hdr', '.exr'})]:
        seen_hashes, seen_names = set(), set()
        files = sorted((p for p in (root / directory).rglob('*') if p.suffix.lower() in suffixes), key=lambda p: (EXTENSIONS.get(p.suffix.lower(), 0), str(p)))
        for path in files:
            fingerprint = digest(path, 'sha256')
            # Group common LOD/color/file-format variants conservatively, then let user review identities.
            name = re.sub(r'(?i)([_-]LOD\d+.*|[_-](1k|2k|4k|8k))$', '', path.stem)
            key = (str(path.parent), name)
            if fingerprint in seen_hashes or key in seen_names: continue
            seen_hashes.add(fingerprint); seen_names.add(key)
            identifier = name + '_' + hashlib.sha256(str(path.relative_to(root)).encode()).hexdigest()[:8]
            add(category, {'id': identifier, 'path': str(path.resolve()), 'sha256': fingerprint})
    for index in range(12):
        add('scenes', {'id': f'courtyard_{index:02d}', 'environment': 'courtyard', 'preset': index,
                       'origin': 'procedural courtyard layout/palette variant; not a downloaded scene'})
    # Retain manually registered external assets outside the default directories.
    for category in old:
        discovered = {entry['id'] for entry in catalog[category]}
        for identifier, entry in old[category].items():
            if identifier not in discovered and entry.get('path') and Path(entry['path']).is_file():
                catalog[category].append(entry)
    return catalog


def check_catalog(catalog, minimum):
    counts = {}
    for category in ('objects', 'people', 'scenes', 'backgrounds'):
        entries = [entry for entry in catalog[category] if entry.get('enabled', True)]
        ready = [entry for entry in entries if not entry.get('path') or Path(entry['path']).is_file()]
        counts[category] = {'enabled': len(entries), 'ready': len(ready), 'unique_identities': len({entry.get('identity', entry['id']) for entry in ready}), 'missing': max(0, minimum - len({entry.get('identity', entry['id']) for entry in ready})),
            'approved': sum(entry.get('review') == 'approved' for entry in ready),
            'procedural': sum('preset' in entry for entry in ready),
            'external': sum('path' in entry for entry in ready)}
    return {'minimum': minimum, 'counts': counts, 'quantity_ok': all(item['missing'] == 0 for item in counts.values()),
            'note': 'Counts are candidate assets, not certified unique people or visual quality. Scene presets are variants of one procedural courtyard. Review catalog, disable duplicates, and approve checked entries.'}


def plan_jobs(catalog, output, seed=42, combinations=1, all_combinations=False, approved_only=False):
    def usable(category):
        return [entry for entry in catalog[category] if entry.get('enabled', True)
                and (not approved_only or entry.get('review') == 'approved')
                and (not entry.get('path') or Path(entry['path']).is_file())]
    subjects = [('object', item) for item in usable('objects')] + [('person', item) for item in usable('people')]
    scenes, backgrounds = usable('scenes'), usable('backgrounds')
    if not subjects or not scenes or not backgrounds:
        raise ValueError('Need at least one enabled subject, scene, and background')
    if combinations < 1: raise ValueError('combinations must be >= 1')
    rng = random.Random(seed)
    jobs = []
    for kind, subject in subjects:
        indices = range(len(scenes) * len(backgrounds)) if all_combinations else rng.sample(range(len(scenes) * len(backgrounds)), min(combinations, len(scenes) * len(backgrounds)))
        for index in indices:
            scene, background = scenes[index // len(backgrounds)], backgrounds[index % len(backgrounds)]
            for shot, orientation in itertools.product(('near', 'medium', 'far'), ('landscape', 'portrait')):
                identity = f"{kind}_{subject['id']}__{scene['id']}__{background['id']}__{shot}__{orientation}"
                job_id = re.sub(r'[^a-zA-Z0-9_.-]', '_', identity)
                jobs.append({'id': job_id, 'kind': kind, 'subject': subject, 'scene': scene, 'background': background,
                             'shot': shot, 'orientation': orientation, 'seed': seed, 'output': str((output / job_id).resolve())})
    return {'version': 1, 'root': catalog['root'], 'settings': {'frames': 121, 'theta': 30, 'phi': 5, 'samples': 32, 'radius': 4.5}, 'jobs': jobs}


def command_for(job, settings, blender, root):
    subject, scene = job['subject'], job['scene']
    command = [sys.executable, '-m', 'data_generation_server.render', '--root', root, '--blender', blender,
        '--model', subject['path'], '--hdri', job['background']['path'], '--subject-kind', job['kind'],
        '--shot', job['shot'], '--orientation', job['orientation'], '--trajectory', 'figure8',
        '--width', '1280', '--height', '720', '--output', job['output'], '--seed', str(job['seed']),
        '--subject-heading', str(subject.get('heading', 0)), '--subject-size', str(subject.get('size', 2)),
        '--person-chest', str(subject.get('chest', 0.65)), '--person-knee', str(subject.get('knee', 0.28)),
        '--subject-position', *map(str, scene.get('position', [0, 0, 0]))]
    for key in ('frames', 'theta', 'phi', 'samples', 'radius'):
        command.extend(['--' + key, str(settings[key])])
    if scene.get('path'): command.extend(['--scene', scene['path']])
    else: command.extend(['--environment', scene['environment'], '--scene-preset', str(scene['preset'])])
    return command


def job_complete(job, settings):
    output = Path(job['output'])
    success, config = output / 'SUCCESS.json', output / 'render-config.json'
    if not success.is_file() or not config.is_file() or not (output / 'video.mp4').is_file(): return False
    try:
        done, cfg = json.loads(success.read_text()), json.loads(config.read_text())
        return (done.get('video_encoded') and done.get('frames') == settings['frames']
                and all(cfg.get(key) == value for key, value in settings.items())
                and cfg.get('model') == job['subject']['path'] and cfg.get('hdri') == job['background']['path']
                and cfg.get('shot') == job['shot'] and cfg.get('selected_orientation') == job['orientation']
                and cfg.get('subject_heading') == job['subject'].get('heading', 0)
                and cfg.get('subject_size') == job['subject'].get('size', 2)
                and cfg.get('person_chest') == job['subject'].get('chest', 0.65)
                and cfg.get('person_knee') == job['subject'].get('knee', 0.28)
                and cfg.get('seed') == job['seed']
                and cfg.get('scene') == job['scene'].get('path')
                and cfg.get('scene_preset') == job['scene'].get('preset', 0)
                and cfg.get('subject_position') == job['scene'].get('position', [0, 0, 0]))
    except (ValueError, OSError): return False


def main(argv=None):
    parser = argparse.ArgumentParser(description='Dataset coverage checks and render job orchestration')
    sub = parser.add_subparsers(dest='action', required=True)
    scan = sub.add_parser('inventory')
    scan.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    scan.add_argument('--catalog', type=Path)
    scan.add_argument('--minimum', type=int, default=11)
    plan = sub.add_parser('plan')
    plan.add_argument('--catalog', type=Path, required=True)
    plan.add_argument('--output', type=Path, required=True)
    plan.add_argument('--render-root', type=Path)
    plan.add_argument('--seed', type=int, default=42)
    plan.add_argument('--combinations-per-subject', type=int, default=1)
    plan.add_argument('--all-combinations', action='store_true')
    plan.add_argument('--approved-only', action='store_true')
    run = sub.add_parser('run')
    run.add_argument('--plan', type=Path, required=True)
    run.add_argument('--blender', required=True)
    run.add_argument('--limit', type=int, default=0, help='0 = all jobs; positive = next N jobs')
    run.add_argument('--retry-incomplete', action='store_true', help='Replace only pipeline outputs for incomplete/changed jobs')
    args = parser.parse_args(argv)
    if args.action == 'inventory':
        catalog_path = args.catalog or args.root / 'catalog.json'
        previous = json.loads(catalog_path.read_text()) if catalog_path.exists() else None
        catalog = inventory(args.root.resolve(), previous)
        write_json(catalog_path, catalog)
        report = check_catalog(catalog, args.minimum)
        write_json(catalog_path.with_name('coverage-report.json'), report)
        print(json.dumps(report, indent=2))
        print('Review/edit:', catalog_path)
        return 0 if report['quantity_ok'] else 1
    if args.action == 'plan':
        catalog = json.loads(args.catalog.read_text())
        result = plan_jobs(catalog, args.render_root or Path(catalog['root']) / 'renders/batch', args.seed,
                           args.combinations_per_subject, args.all_combinations, args.approved_only)
        write_json(args.output, result)
        print(f"Planned {len(result['jobs'])} videos; six per subject/scene/background combination")
        return 0
    if args.limit < 0: parser.error('--limit must be >= 0')
    plan = json.loads(args.plan.read_text())
    report_path = args.plan.with_name(args.plan.stem + '.run-report.json')
    results, attempted = [], 0
    for job in plan['jobs']:
        if job_complete(job, plan['settings']):
            results.append({'id': job['id'], 'status': 'skipped'}); continue
        if args.limit and attempted >= args.limit: break
        command = command_for(job, plan['settings'], args.blender, plan['root'])
        if args.retry_incomplete: command.append('--overwrite')
        attempted += 1
        try:
            print(f"[{attempted}] {job['id']}", flush=True)
            subprocess.run(command, check=True)
            if not job_complete(job, plan['settings']): raise RuntimeError('Missing or mismatched success outputs')
            results.append({'id': job['id'], 'status': 'ok'})
        except Exception as exc:
            results.append({'id': job['id'], 'status': 'failed', 'error': str(exc)})
        write_json(report_path, {'results': results})
    write_json(report_path, {'results': results})
    return 1 if any(item['status'] == 'failed' for item in results) else 0


if __name__ == '__main__': raise SystemExit(main())
