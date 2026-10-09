import unittest
from types import SimpleNamespace
from data_generation_server.render_passes import make_render_layers


class RenderPassTests(unittest.TestCase):
    def test_selected_layer_bound_instead_of_default(self):
        class Layer:
            def __init__(self, name):
                self.name = name
                self.use = True
                self.use_pass_object_index = False
                self.use_pass_z = False
            def update_render_passes(self): pass
        layers = [Layer('Original'), Layer('Selected')]
        scene = SimpleNamespace(name='Legacy scene', view_layers=layers)
        class Node:
            layer = 'Original'
            scene = None
            @property
            def outputs(self):
                selected = next(x for x in self.scene.view_layers if x.name == self.layer)
                return {'Image': object(), **({'IndexOB': object()} if selected.use_pass_object_index else {}),
                        **({'Depth': object()} if selected.use_pass_z else {})}
        tree = SimpleNamespace(nodes=SimpleNamespace(new=lambda name: Node()))
        render = make_render_layers(scene, layers[1], tree)
        self.assertEqual(render.layer, 'Selected')
        self.assertIs(render.scene, scene)
        self.assertEqual([layer.use for layer in layers], [False, True])
        self.assertIn('IndexOB', render.outputs)
