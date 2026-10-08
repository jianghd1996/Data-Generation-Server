"""Executed inside Blender, not the server's regular Python interpreter."""
import argparse
import json
import math
from pathlib import Path
import sys
import time
import bpy
from mathutils import Matrix, Vector


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2))


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
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
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
    for image in set(bpy.data.images) - before_images:
        if image.packed_file or image.source != 'FILE': continue
        candidates = [Path(bpy.path.abspath(image.filepath)), original.parent / image.filepath.removeprefix('//'), original.parent / 'textures' / Path(image.filepath).name]
        found = next((path for path in candidates if path.is_file()), None)
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
    normalizer.location = -center * scale
    for obj in geometry: obj.pass_index = 1
    bpy.context.view_layer.update()
    target = Vector((0, 0, size.z * scale / 2))

    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, -0.005))
    ground = bpy.context.object
    ground.name = 'Ground'
    material = bpy.data.materials.new('GroundMaterial')
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (0.18, 0.18, 0.18, 1)
    bsdf.inputs['Roughness'].default_value = 0.85
    ground.data.materials.append(material)
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

    bpy.ops.object.camera_add()
    camera = bpy.context.object
    scene.camera = camera
    camera.data.lens = cfg['focal_mm']
    camera.data.sensor_width = 36
    camera.data.sensor_fit = 'HORIZONTAL'
    camera.data.clip_start = 0.01
    camera.data.clip_end = 1000
    camera.data.dof.use_dof = False
    layer = bpy.context.view_layer
    layer.use_pass_object_index = True
    layer.use_pass_z = True
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    render = tree.nodes.new('CompositorNodeRLayers')
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
    fx = cfg['focal_mm'] / 36 * cfg['width']
    cv_axis = Matrix.Diagonal((1, -1, -1, 1))
    cameras = {'width': cfg['width'], 'height': cfg['height'], 'fps': cfg['fps'],
               'K': [[fx, 0, cfg['width'] / 2], [0, fx, cfg['height'] / 2], [0, 0, 1]],
               'world_axes': 'Blender: Z up', 'camera_axes': 'OpenCV: X right, Y down, Z forward',
               'depth': 'Blender Z pass: camera-to-surface distance in normalized scene units; background may be very large',
               'mask': 'white subject, black background; antialiased boundaries', 'frames': []}
    elevation = math.radians(cfg['elevation'])
    for index in range(cfg['frames']):
        frame = index + 1
        angle = math.radians(cfg['start_angle'] + cfg['sweep'] * index / (cfg['frames'] - 1))
        camera.location = target + Vector((cfg['radius'] * math.cos(elevation) * math.cos(angle), cfg['radius'] * math.cos(elevation) * math.sin(angle), cfg['radius'] * math.sin(elevation)))
        camera.rotation_euler = (target - camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        c2w = camera.matrix_world @ cv_axis
        cameras['frames'].append({'frame': frame, 'time': index / cfg['fps'], 'rgb': f'rgb/rgb_{frame:04d}.png',
                                  'mask': f'mask/mask_{frame:04d}.png', 'depth': f'depth/depth_{frame:04d}.exr',
                                  'c2w': [list(row) for row in c2w], 'w2c': [list(row) for row in c2w.inverted()]})
        scene.render.filepath = str(output / 'rgb' / f'rgb_{frame:04d}.png')
        print(f'[orbit] frame {frame}/{cfg["frames"]}', flush=True)
        bpy.ops.render.render(write_still=True)
    save_json(output / 'cameras.json', cameras)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / 'scene.blend'))
    (output / 'prompt.txt').write_text('A static subject on a flat ground plane. The camera smoothly orbits around the subject.\n')
    save_json(output / 'render-report.json', {'ok': True, 'devices': devices, 'blender': bpy.app.version_string,
        'frames': cfg['frames'], 'elapsed_seconds': time.monotonic() - started, 'missing_textures': [],
        'source_model': cfg['model'], 'source_hdri': cfg['hdri'], 'normalization_scale': scale,
        'source_bounds': [list(lower), list(upper)], 'geometry_objects': [obj.name for obj in geometry]})


if __name__ == '__main__': main()
