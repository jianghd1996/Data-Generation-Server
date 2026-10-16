import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('sf', Path(__file__).parents[1] / 'scripts/download_sketchfab_people.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class DownloadTests(unittest.TestCase):
    def test_urls(self):
        uid = m.CANDIDATES[0]
        self.assertEqual(m.model_uid('https://sketchfab.com/3d-models/person-' + uid), uid)
        with self.assertRaises(ValueError):
            m.model_uid('https://example.com/' + uid)

    def test_download_inventory_skip(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, 'w') as z:
            z.writestr('scene.gltf', '{"asset":{"version":"2.0"}}')
            z.writestr('textures/color.png', b'texture')
        class Response(io.BytesIO):
            headers = {'Content-Length': str(len(payload.getvalue()))}
        meta = {'isDownloadable': True, 'name': 'Test', 'license': {'label': 'CC BY'}, 'user': {'username': 'artist'}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(m, 'get_json', side_effect=[meta, {'gltf': {'url': 'https://example.com/archive'}}]), patch.object(m.urllib.request, 'urlopen', return_value=Response(payload.getvalue())):
                self.assertEqual(m.download(m.CANDIDATES[0], root, 4096, 4096, None, 'Token SECRET'), 'ok')
            folder = root / 'people/direct' / ('sketchfab_' + m.CANDIDATES[0])
            self.assertTrue(m.ready(folder))
            self.assertNotIn('SECRET', (folder / 'people-source.json').read_text())
            with patch.object(m, 'get_json', side_effect=AssertionError('network')):
                self.assertEqual(m.download(m.CANDIDATES[0], root, 4096, 4096, None, None), 'skipped')
            from data_generation_server.dataset import inventory
            self.assertEqual(len(inventory(root)['people']), 1)
            (folder / 'extracted/scene.gltf').unlink()
            self.assertFalse(m.ready(folder))

    def test_stream_limit(self):
        class Response(io.BytesIO):
            headers = {}
        with tempfile.TemporaryDirectory() as tmp, patch.object(m.urllib.request, 'urlopen', return_value=Response(b'x' * 20)):
            target = Path(tmp) / 'sample.zip'
            with self.assertRaises(ValueError):
                m.download_archive('https://example.com/file', target, 10, None)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix('.zip.part').exists())

    def test_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(m, 'get_json', return_value={'isDownloadable': False}):
            with self.assertRaises(ValueError):
                m.download(m.CANDIDATES[0], Path(tmp), 100, 100, None, None)
