"""Executed inside Blender, not the server's regular Python interpreter."""
import argparse
import json
import math
from pathlib import Path
import sys
import time
import random

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shots import shot_setup
from texture_paths import TextureResolver
from render_passes import make_render_layers
import bpy
from mathutils import Matrix, Vector


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2))



def surface(name, color):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Roughness'].default_value = 0.8
    return material


def cube(name, location, dimensions, material):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    bevel = obj.modifiers.new('Soft edges', 'BEVEL')
    bevel.width = 0.03
    bevel.segments = 2
    return obj


def make_courtyard(origin, preset=0):
    """Small deterministic geometric environment; no extra asset download required."""
    rng = random.Random(preset)
    tint = rng.uniform(-0.08, 0.08)
    half_width = 10 + preset % 4
    half_depth = 10 + (preset // 4) % 3
    stone = surface('CourtyardStone', (0.44 + tint, 0.40 + tint, 0.34 + tint))
    plaster = surface('CourtyardPlaster', (0.68, 0.61, 0.49))
    dark = surface('CourtyardTrim', (0.14, 0.18, 0.18))
    cube('CourtyardBase', origin + Vector((0, 0, -0.14)), (28, 28, 0.25), stone)
    tiles = [surface(f'Paving{i}', (0.27 + i * 0.025, 0.29 + i * 0.025, 0.27 + i * 0.025)) for i in range(5)]
    for x in range(-10, 11):
        for y in range(-10, 11):
            cube(f'Paver_{x}_{y}', origin + Vector((x, y, -0.035)), (0.98, 0.98, 0.05), tiles[(x * 7 + y * 3) % 5])
    for y in (-half_depth, half_depth):
        cube('CourtyardWall', origin + Vector((0, y, 2)), (2 * half_width + 1, 0.3, 4), plaster)
        cube('WallCap', origin + Vector((0, y, 4.05)), (2 * half_width + 1.2, 0.45, 0.15), stone)
        for x in (-9, -6, -3, 0, 3, 6, 9):
            cube('WallPillar', origin + Vector((x, y - (0.22 if y > 0 else -0.22), 2)), (0.4, 0.6, 4.1), stone)
            cube('WallPanel', origin + Vector((x + 1.1, y - (0.18 if y > 0 else -0.18), 2)), (1.3, 0.08, 1.8), dark)
    for x in (-half_width, half_width):
        cube('SideWall', origin + Vector((x, 0, 1.2)), (0.3, 2 * half_depth, 2.4), plaster)
    for x, y in [(-8, -7), (8, -7), (-8, 7), (8, 7)]:
        cube('Planter', origin + Vector((x, y, 0.4)), (1.4, 1.4, 0.8), stone)
        for i in range(5):
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.65, location=origin + Vector((x + 0.3 * math.cos(i * 2), y + 0.3 * math.sin(i * 2), 1 + i * 0.18)))
            bpy.context.object.name = 'GeometricShrub'
            bpy.context.object.data.materials.append(surface(f'Leaf_{x}_{y}_{i}', (0.08 + i * 0.015, 0.18 + i * 0.015, 0.055)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if bpy.app.version < (4, 2, 0) or bpy.app.version >= (5, 0, 0):
        raise RuntimeError('Use Blender 4.2–4.5; compositor API in Blender 5 is not supported yet')
    cfg = json.loads(args.config.read_text())
    output = Path(cfg['output'])
    for folder in ('rgb', 'mask', 'depth'):
        (output / folder).mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    if cfg.get('scene'):
        bpy.ops.wm.open_mainfile(filepath=cfg['scene'])
    else:
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
    environment_objects = list(bpy.context.scene.objects)
    for obj in environment_objects:
        obj.animation_data_clear()
        obj.pass_index = 0
    bpy.context.scene.frame_set(1)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = cfg['samples']
    scene.cycles.use_denoising = True
    scene.cycles.seed = cfg['seed']
    devices = []
    if cfg['device'] != 'CPU':
        preferences = bpy.context.preferences.addons['cycles'].preferences
        preferences.compute_device_type = cfg['device']
        preferences.get_devices()
        for device in preferences.devices:
            device.use = device.type == cfg['device']
            if device.use: devices.append(device.name)
        if not devices:
            raise RuntimeError(f"No {cfg['device']} device detected; check Blender/driver or explicitly use --device CPU")
        scene.cycles.device = 'GPU'
    else:
        scene.cycles.device = 'CPU'
        devices = ['CPU']
    scene.render.resolution_x = cfg['width']
    scene.render.resolution_y = cfg['height']
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = '8'
    scene.render.fps = cfg['fps']
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.exposure = 0
    scene.render.use_motion_blur = False
    scene.frame_start = 1
    scene.frame_end = cfg['frames']

    original = Path(cfg['model'])
    before_images = set(bpy.data.images)
    before_objects = set(bpy.data.objects)
    if original.suffix.lower() == '.blend':
        with bpy.data.libraries.load(str(original), link=False) as (source, destination):
            destination.objects = source.objects
        for obj in destination.objects:
            if obj and not obj.users_collection: scene.collection.objects.link(obj)
    elif original.suffix.lower() in ('.glb', '.gltf'):
        bpy.ops.import_scene.gltf(filepath=str(original))
    elif original.suffix.lower() == '.fbx':
        bpy.ops.import_scene.fbx(filepath=str(original))
    elif original.suffix.lower() == '.obj':
        bpy.ops.wm.obj_import(filepath=str(original))
    else:
        raise ValueError('Unsupported model format')
    imported = set(bpy.data.objects) - before_objects
    geometry = [obj for obj in imported if obj.type in ('MESH', 'CURVE', 'SURFACE', 'FONT', 'META')]
    if not geometry:
        raise RuntimeError('No renderable subject geometry found')
    for obj in imported:
        obj.animation_data_clear()
        obj.hide_render = obj.type in ('LIGHT', 'CAMERA')
        obj.hide_viewport = False
    missing_images = []
    subject_textures = TextureResolver(original)
    for image in set(bpy.data.images) - before_images:
        if image.packed_file or image.source != 'FILE': continue
        found = subject_textures.find(image.filepath, bpy.path.abspath(image.filepath))
        if found:
            image.filepath = str(found.resolve())
            image.reload()
        else:
            missing_images.append(image.filepath)
    if missing_images:
        save_json(output / 'render-report.json', {'ok': False, 'missing_textures': missing_images})
        raise RuntimeError(f'Missing textures: {missing_images}')
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    corners = [obj.matrix_world @ Vector(corner) for obj in (o.evaluated_get(depsgraph) for o in geometry) for corner in obj.bound_box]
    lower = Vector([min(point[i] for point in corners) for i in range(3)])
    upper = Vector([max(point[i] for point in corners) for i in range(3)])
    size = upper - lower
    if max(size) < 1e-6:
        raise RuntimeError('Degenerate subject bounds')
    scale = cfg['subject_size'] / max(size)
    center = Vector(((lower.x + upper.x) / 2, (lower.y + upper.y) / 2, lower.z))
    normalizer = bpy.data.objects.new('SubjectNormalizer', None)
    scene.collection.objects.link(normalizer)
    for obj in imported:
        if obj.parent not in imported:
            world = obj.matrix_world.copy()
            obj.parent = normalizer
            obj.matrix_world = world
    normalizer.scale = (scale,) * 3
    heading = math.radians(cfg.get('subject_heading', 0))
    rotation = Matrix.Rotation(heading, 3, 'Z')
    normalizer.rotation_euler.z = heading
    placement = Vector(cfg.get('subject_position', [0, 0, 0]))
    normalizer.location = placement - rotation @ (center * scale)
    for obj in geometry: obj.pass_index = 1
    bpy.context.view_layer.update()
    target_height, effective_radius = shot_setup(cfg.get('subject_kind', 'object'), cfg.get('shot', 'manual'), size.z * scale, max(size.x, size.y) * scale, cfg['width'], cfg['height'], cfg['focal_mm'], cfg['radius'], cfg['elevation'], cfg['phi'], cfg.get('person_chest', 0.65), cfg.get('person_knee', 0.28))
    target = placement + Vector((0, 0, target_height))
    framing = {'shot': cfg.get('shot', 'manual'), 'subject_kind': cfg.get('subject_kind', 'object'), 'target': list(target), 'effective_radius': effective_radius, 'method': 'bounding-box approximation; review anatomical framing'}
    print('[framing]', framing, flush=True)

    if not cfg.get('scene'):
        if cfg.get('environment') == 'courtyard':
            make_courtyard(placement, cfg.get('scene_preset', 0))
        else:
            bpy.ops.mesh.primitive_plane_add(size=200, location=placement + Vector((0, 0, -0.005)))
            ground = bpy.context.object
            ground.name = 'Ground'
            ground.data.materials.append(surface('GroundMaterial', (0.18, 0.18, 0.18)))
    if cfg.get('hdri'):
        world = bpy.data.worlds.new('HDRIWorld')
        scene.world = world
        world.use_nodes = True
        nodes = world.node_tree.nodes
        nodes.clear()
        env = nodes.new('ShaderNodeTexEnvironment')
        env.image = bpy.data.images.load(cfg['hdri'], check_existing=True)
        background = nodes.new('ShaderNodeBackground')
        background.inputs['Strength'].default_value = cfg['hdri_strength']
        world_output = nodes.new('ShaderNodeOutputWorld')
        world.node_tree.links.new(env.outputs['Color'], background.inputs['Color'])
        world.node_tree.links.new(background.outputs['Background'], world_output.inputs['Surface'])
    # Relink external scene images after ZIP extraction, before validating them.
    scene_missing = []
    scene_textures = TextureResolver(cfg['scene']) if cfg.get('scene') else None
    for image in bpy.data.images:
        if image.source != 'FILE' or image.packed_file: continue
        resolved = bpy.path.abspath(image.filepath)
        if Path(resolved).is_file(): continue
        found = scene_textures.find(image.filepath, resolved) if scene_textures else None
        if found:
            print(f'[texture] {image.filepath} -> {found}', flush=True)
            image.filepath = str(found)
            image.reload()
        else:
            scene_missing.append(image.filepath)
    if scene_missing:
        save_json(output / 'render-report.json', {'ok': False, 'missing_textures': scene_missing})
        raise RuntimeError(f'Missing scene textures: {scene_missing}')

    bpy.ops.object.camera_add()
    camera = bpy.context.object
    scene.camera = camera
    # Preserve field of view on the short image axis when orientation changes.
    camera.data.lens = cfg['focal_mm'] * min(cfg['width'], cfg['height']) / cfg['width'] * (1280 / 720)
    camera.data.sensor_width = 36
    camera.data.sensor_fit = 'HORIZONTAL'
    camera.data.clip_start = 0.01
    camera.data.clip_end = 1000
    camera.data.dof.use_dof = False
    scene.render.use_sequencer = False
    layer = bpy.context.view_layer
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    render = make_render_layers(scene, layer, tree)
    composite = tree.nodes.new('CompositorNodeComposite')
    tree.links.new(render.outputs['Image'], composite.inputs['Image'])
    mask = tree.nodes.new('CompositorNodeIDMask')
    mask.index = 1
    mask.use_antialiasing = True
    tree.links.new(render.outputs['IndexOB'], mask.inputs[0])
    for folder, socket, fmt in [('mask', mask.outputs[0], 'PNG'), ('depth', render.outputs['Depth'], 'OPEN_EXR')]:
        file_output = tree.nodes.new('CompositorNodeOutputFile')
        file_output.base_path = str(output / folder)
        file_output.file_slots[0].path = folder + '_'
        file_output.format.file_format = fmt
        file_output.format.color_mode = 'BW'
        file_output.format.color_depth = '32' if fmt == 'OPEN_EXR' else '8'
        tree.links.new(socket, file_output.inputs[0])
    scene.render.use_compositing = True
    fx = camera.data.lens / 36 * cfg['width']
    cv_axis = Matrix.Diagonal((1, -1, -1, 1))
    cameras = {'width': cfg['width'], 'height': cfg['height'], 'fps': cfg['fps'],
               'K': [[fx, 0, cfg['width'] / 2], [0, fx, cfg['height'] / 2], [0, 0, 1]],
               'world_axes': 'Blender: Z up', 'camera_axes': 'OpenCV: X right, Y down, Z forward',
               'depth': 'Blender Z pass: camera-to-surface distance in normalized scene units; background may be very large',
               'mask': 'white subject, black background; antialiased boundaries', 'framing': framing, 'frames': []}
    for index in range(cfg['frames']):
        frame = index + 1
        azimuth_deg, elevation_deg = cfg['camera_angles'][index]
        angle = math.radians(azimuth_deg)
        elevation = math.radians(elevation_deg)
        camera.location = target + Vector((effective_radius * math.cos(elevation) * math.cos(angle), effective_radius * math.cos(elevation) * math.sin(angle), effective_radius * math.sin(elevation)))
        camera.rotation_euler = (target - camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        c2w = camera.matrix_world @ cv_axis
        cameras['frames'].append({'frame': frame, 'azimuth_deg': azimuth_deg, 'elevation_deg': elevation_deg, 'time': index / cfg['fps'], 'rgb': f'rgb/rgb_{frame:04d}.png',
                                  'mask': f'mask/mask_{frame:04d}.png', 'depth': f'depth/depth_{frame:04d}.exr',
                                  'c2w': [list(row) for row in c2w], 'w2c': [list(row) for row in c2w.inverted()]})
        scene.render.filepath = str(output / 'rgb' / f'rgb_{frame:04d}.png')
        print(f'[orbit] frame {frame}/{cfg["frames"]}', flush=True)
        bpy.ops.render.render(write_still=True)
    save_json(output / 'cameras.json', cameras)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / 'scene.blend'))
    environment_label = 'a 3D environment' if cfg.get('scene') or cfg.get('environment') == 'courtyard' else 'a flat ground plane'
    (output / 'prompt.txt').write_text(f'A static subject in {environment_label}. The camera follows a smooth spherical trajectory around the subject.\n')
    save_json(output / 'render-report.json', {'ok': True, 'devices': devices, 'blender': bpy.app.version_string,
        'framing': framing, 'frames': cfg['frames'], 'elapsed_seconds': time.monotonic() - started, 'missing_textures': [],
        'source_model': cfg['model'], 'source_hdri': cfg['hdri'], 'source_scene': cfg.get('scene'),
        'environment': cfg.get('environment'), 'subject_position': list(placement), 'subject_heading': cfg.get('subject_heading', 0), 'normalization_scale': scale,
        'source_bounds': [list(lower), list(upper)], 'geometry_objects': [obj.name for obj in geometry]})


if __name__ == '__main__': main()
