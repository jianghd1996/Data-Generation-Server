"""Launch Blender and encode the rendered RGB sequence."""
import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
from .assets import DEFAULT_ROOT
from .trajectory import camera_angles, orientation_size


def orbit_positions(frames, radius, elevation, start, sweep, target):
    if frames < 2 or radius <= 0:
        raise ValueError('frames >= 2 and radius > 0 required')
    elevation = math.radians(elevation)
    for index in range(frames):
        angle = math.radians(start + sweep * index / (frames - 1))
        yield (target[0] + radius * math.cos(elevation) * math.cos(angle),
               target[1] + radius * math.cos(elevation) * math.sin(angle),
               target[2] + radius * math.sin(elevation))


def asset_file(root, kind, asset_id, suffixes):
    metadata = root / kind / 'polyhaven' / asset_id / 'asset.json'
    if not metadata.exists():
        raise ValueError(f'Asset metadata missing: {metadata}; supply --model/--hdri explicitly if stored elsewhere')
    data = json.loads(metadata.read_text())
    for record in data['files']:
        relative = Path(record['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe path in asset metadata')
        path = (metadata.parent / relative).resolve()
        if metadata.parent.resolve() not in path.parents:
            raise ValueError('Asset path escapes directory')
        if path.suffix.lower() in suffixes and path.is_file():
            return path
    raise ValueError(f'No supported file found in {metadata}')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Single static subject camera orbit using Blender Cycles')
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--model', type=Path)
    parser.add_argument('--hdri', type=Path)
    parser.add_argument('--scene', type=Path, help='Complete .blend environment; retains world and lights')
    parser.add_argument('--environment', choices=['studio', 'courtyard'], default='studio')
    parser.add_argument('--subject-position', type=float, nargs=3, default=[0, 0, 0], metavar=('X', 'Y', 'Z'))
    parser.add_argument('--auto-place', action='store_true', help='Find nearby floor and unobstructed camera views in external scene')
    parser.add_argument('--subject-heading', type=float, default=0)
    parser.add_argument('--model-id', default='horse_statue_01')
    parser.add_argument('--hdri-id', default='abandoned_factory_canteen_01')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--blender', default='blender')
    parser.add_argument('--device', choices=['CUDA', 'OPTIX', 'CPU'], default='CUDA')
    parser.add_argument('--frames', type=int, default=121)
    parser.add_argument('--trajectory', choices=['figure8', 'orbit'], default='figure8')
    parser.add_argument('--theta', type=float, default=30)
    parser.add_argument('--phi', type=float, default=5)
    parser.add_argument('--orientation', choices=['random', 'landscape', 'portrait', 'keep'], default='random')
    parser.add_argument('--fps', type=int, default=24)
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--samples', type=int, default=32)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--subject-kind', choices=['object', 'person'], default='object')
    parser.add_argument('--shot', choices=['manual', 'near', 'medium', 'far'], default='manual')
    parser.add_argument('--person-chest', type=float, default=0.65)
    parser.add_argument('--person-knee', type=float, default=0.28)
    parser.add_argument('--scene-preset', type=int, default=0)
    parser.add_argument('--subject-size', type=float, default=2.0)
    parser.add_argument('--radius', type=float, default=4.5)
    parser.add_argument('--elevation', type=float, default=12.0)
    parser.add_argument('--start-angle', type=float, default=-90)
    parser.add_argument('--sweep', type=float, default=90)
    parser.add_argument('--focal-mm', type=float, default=35)
    parser.add_argument('--hdri-strength', type=float, default=1)
    parser.add_argument('--no-video', action='store_true')
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args(argv)
    if args.frames < 2 or min(args.width, args.height, args.samples, args.fps) <= 0:
        parser.error('frames >= 2 and positive resolution/samples/fps required')
    if args.width % 2 or args.height % 2:
        parser.error('width and height must be even')
    if min(args.radius, args.subject_size, args.focal_mm) <= 0 or not -89 < args.elevation < 89:
        parser.error('positive radius/size/focal length and elevation between -89 and 89 required')
    try:
        angles = camera_angles(args.trajectory, args.frames, args.start_angle, args.elevation, args.sweep, args.theta, args.phi)
    except ValueError as exc:
        parser.error(str(exc))
    args.width, args.height, selected_orientation = orientation_size(args.orientation, args.width, args.height, args.seed)
    if not 0 <= args.person_knee < args.person_chest < 1:
        parser.error('Require 0 <= knee < chest < 1')
    root = args.root.resolve()
    scene_file = args.scene.resolve() if args.scene else None
    if scene_file and (not scene_file.is_file() or scene_file.suffix.lower() != '.blend'):
        parser.error('--scene must point to an existing .blend file')
    model = args.model.resolve() if args.model else asset_file(root, 'models', args.model_id, {'.blend', '.glb', '.gltf', '.fbx', '.obj'})
    hdri = args.hdri.resolve() if args.hdri else (None if scene_file else asset_file(root, 'hdris', args.hdri_id, {'.hdr', '.exr'}))
    for path in (model, hdri, scene_file):
        if path is None: continue
        if not path.is_file():
            parser.error(f'File missing: {path}')
    blender = shutil.which(args.blender)
    if not blender:
        parser.error('Blender executable not found; install Blender 4.x or supply --blender /path/to/blender')
    ffmpeg = shutil.which('ffmpeg') if not args.no_video else None
    if not args.no_video and not ffmpeg:
        parser.error('ffmpeg not found; install ffmpeg or use --no-video')
    output = (args.output or root / 'renders' / 'horse_orbit_demo').resolve()
    for source in (model, hdri, scene_file):
        if source is None: continue
        if output == source.parent or output in source.parents:
            parser.error('Output must not contain source asset files')
    if output.exists() and any(output.iterdir()):
        if not args.overwrite:
            parser.error(f'Output is not empty: {output}; choose a new --output or use --overwrite')
        # Refuse to remove unknown content. Only remove files/directories owned by this pipeline.
        for name in ('rgb', 'mask', 'depth', 'video.mp4', 'image.jpg', 'scene.blend', 'scene.blend1', 'cameras.json', 'render-report.json', 'render-config.json', 'prompt.txt', 'SUCCESS.json'):
            target = output / name
            if target.is_dir(): shutil.rmtree(target)
            elif target.exists(): target.unlink()
    output.mkdir(parents=True, exist_ok=True)
    config = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    config.update(model=str(model), hdri=str(hdri) if hdri else None, scene=str(scene_file) if scene_file else None, output=str(output))
    config['camera_angles'] = angles
    config['selected_orientation'] = selected_orientation
    config_path = output / 'render-config.json'
    config_path.write_text(json.dumps(config, indent=2))
    script = Path(__file__).with_name('blender_orbit.py')
    command = [blender, '--background', '--factory-startup', '--python-exit-code', '1', '--python', str(script), '--', '--config', str(config_path)]
    print(f'Rendering {args.trajectory}: {args.width}x{args.height}, {args.frames} frames into {output}', flush=True)
    subprocess.run(command, check=True)
    for folder in ('rgb', 'mask', 'depth'):
        suffix = '.exr' if folder == 'depth' else '.png'
        missing = [i for i in range(1, args.frames + 1) if not (output / folder / f'{folder}_{i:04d}{suffix}').is_file()]
        if missing:
            raise RuntimeError(f'Missing {folder} frames: {missing}')
    if ffmpeg:
        subprocess.run([ffmpeg, '-y', '-framerate', str(args.fps), '-start_number', '1', '-i', str(output / 'rgb/rgb_%04d.png'), '-frames:v', str(args.frames), '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', str(output / 'video.mp4')], check=True)
        subprocess.run([ffmpeg, '-y', '-i', str(output / 'rgb/rgb_0001.png'), '-frames:v', '1', str(output / 'image.jpg')], check=True)
    (output / 'SUCCESS.json').write_text(json.dumps({'frames': args.frames, 'video_encoded': bool(ffmpeg)}, indent=2))
    print('DONE:', output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
