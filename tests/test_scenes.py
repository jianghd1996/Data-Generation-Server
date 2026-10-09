import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from data_generation_server.scenes import main, probe_size


class Response:
    status = 206
    headers = {'Content-Range': 'bytes 0-0/123456'}
    def __enter__(self): return self
    def __exit__(self, *args): pass


class SceneTests(unittest.TestCase):
    def test_probe_uses_total_range_size(self):
        with patch('data_generation_server.assets.request', return_value=Response()) as request:
            self.assertEqual(probe_size('https://example.org/scene.zip'), 123456)
            request.assert_called_once_with('https://example.org/scene.zip', {'Range': 'bytes=0-0'})

    def test_oversize_skipped_before_download(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('data_generation_server.scenes.probe_size', return_value=200 * 1048576), patch('data_generation_server.scenes.assets_main') as download:
                self.assertEqual(main(['--provider', 'blender', '--ids', 'classroom', '--root', directory]), 1)
                download.assert_not_called()

    def test_scene_registration_and_repeat_preserves_position(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'scenes/direct/blender_classroom/scene.zip'
            archive.parent.mkdir(parents=True)
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('classroom.blend', b'mocked blend')
                zipped.writestr('textures/paint.png', b'texture')
            flags = ['--provider', 'blender', '--ids', 'classroom', '--root', directory]
            with patch('data_generation_server.scenes.probe_size', return_value=archive.stat().st_size), patch('data_generation_server.scenes.assets_main', return_value=0):
                self.assertEqual(main(flags), 0)
                registration = archive.parent / 'scene-registration.json'
                record = json.loads(registration.read_text())
                record['position'] = [1, 2, 3]
                registration.write_text(json.dumps(record))
                self.assertEqual(main(flags), 0)
                self.assertEqual(json.loads(registration.read_text())['position'], [1, 2, 3])
                self.assertTrue((archive.parent / 'extracted/textures/paint.png').is_file())
