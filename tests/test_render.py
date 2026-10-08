import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from data_generation_server.render import orbit_positions, asset_file, main


class RenderTests(unittest.TestCase):
    def test_orbit_constant_radius_and_endpoints(self):
        target = (0, 0, 1)
        positions = list(orbit_positions(81, 4.5, 12, -90, 90, target))
        self.assertEqual(len(positions), 81)
        for point in positions:
            self.assertAlmostEqual(math.dist(point, target), 4.5)
        self.assertAlmostEqual(positions[0][0], 0)
        self.assertAlmostEqual(positions[-1][1], 0)
        steps = [math.dist(a, b) for a, b in zip(positions, positions[1:])]
        self.assertAlmostEqual(min(steps), max(steps))

    def test_legacy_asset_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            asset = root / 'models/polyhaven/test'
            asset.mkdir(parents=True)
            (asset / 'mesh.blend').write_bytes(b'blend')
            (asset / 'asset.json').write_text(json.dumps({'files': [{'path': 'mesh.blend'}]}))
            self.assertEqual(asset_file(root, 'models', 'test', {'.blend'}), asset / 'mesh.blend')
            (asset / 'asset.json').write_text(json.dumps({'files': [{'path': '../bad.blend'}]}))
            with self.assertRaises(ValueError): asset_file(root, 'models', 'test', {'.blend'})

    def test_scene_does_not_require_hdri(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model, scene = root / 'model.blend', root / 'environment.blend'
            model.touch(); scene.touch()
            output = root / 'out'
            args = ['--model', str(model), '--scene', str(scene), '--output', str(output), '--frames', '3', '--no-video', '--subject-position', '2', '3', '4']
            with patch('data_generation_server.render.shutil.which', return_value='/bin/blender'), patch('data_generation_server.render.subprocess.run'):
                with self.assertRaises(RuntimeError): main(args)
            config = json.loads((output / 'render-config.json').read_text())
            self.assertIsNone(config['hdri'])
            self.assertEqual(config['scene'], str(scene))
            self.assertEqual(config['subject_position'], [2, 3, 4])

    def test_launcher_checks_outputs_before_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model, hdri = root / 'mesh.blend', root / 'light.hdr'
            model.touch(); hdri.touch()
            output = root / 'render'
            args = ['--model', str(model), '--hdri', str(hdri), '--output', str(output), '--frames', '3', '--no-video']
            with patch('data_generation_server.render.shutil.which', return_value='/bin/blender'), patch('data_generation_server.render.subprocess.run'):
                with self.assertRaises(RuntimeError): main(args)
            self.assertFalse((output / 'SUCCESS.json').exists())
            def rendered(command, **kwargs):
                self.assertIn('--python-exit-code', command)
                for kind in ('rgb', 'mask', 'depth'):
                    (output / kind).mkdir(exist_ok=True)
                    for frame in range(1, 4):
                        suffix = 'exr' if kind == 'depth' else 'png'
                        (output / kind / f'{kind}_{frame:04d}.{suffix}').touch()
            with patch('data_generation_server.render.shutil.which', return_value='/bin/blender'), patch('data_generation_server.render.subprocess.run', side_effect=rendered):
                self.assertEqual(main(args + ['--overwrite']), 0)
            self.assertTrue((output / 'SUCCESS.json').exists())


if __name__ == '__main__': unittest.main()
