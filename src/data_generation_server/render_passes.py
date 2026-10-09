"""Bind compositor passes to the same view layer selected for rendering."""


def make_render_layers(scene, layer, tree):
    for candidate in scene.view_layers:
        candidate.use = candidate.name == layer.name
    layer.use_pass_object_index = True
    layer.use_pass_z = True
    layer.update_render_passes()
    render = tree.nodes.new('CompositorNodeRLayers')
    render.scene = scene
    render.layer = layer.name
    layer.update_render_passes()
    required = ('Image', 'IndexOB', 'Depth')
    missing = [name for name in required if render.outputs.get(name) is None]
    if missing:
        raise RuntimeError(f'Render passes missing for scene {scene.name}, layer {layer.name}: {missing}; available: {[socket.name for socket in render.outputs]}')
    print(f'[passes] scene={scene.name}, layer={layer.name}: RGB, object index, depth', flush=True)
    return render
