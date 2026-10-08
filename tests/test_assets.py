import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from data_generation_server.assets import acquire, download, safe_path, validate_assets, main


class Response:
    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {'Content-Length': str(len(body)), 'ETag': 'v1'}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, size):
        result, self.body = self.body[:size], self.body[size:]
        return result


class Tests(unittest.TestCase):
    def test_tls_options(self):
        import ssl
        import data_generation_server.assets as module
        with patch.dict('os.environ', {}, clear=True), patch.object(module, 'api', return_value={}):
            main(['files', 'test'])
            self.assertEqual(module.TLS_CONTEXT.verify_mode, ssl.CERT_REQUIRED)
            main(['files', 'test', '--insecure'])
            self.assertEqual(module.TLS_CONTEXT.verify_mode, ssl.CERT_NONE)
        context = ssl.create_default_context()
        with patch.dict('os.environ', {}, clear=True), patch.object(module, 'api', return_value={}), patch.object(module.ssl, 'create_default_context', return_value=context) as factory:
            main(['files', 'test', '--ca-bundle', '/custom/ca.pem'])
            factory.assert_called_once_with(cafile='/custom/ca.pem')
        module.TLS_CONTEXT = None

    def test_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'mesh.glb'
            target.with_name('mesh.glb.part').write_bytes(b'abc')
            target.with_name('mesh.glb.part.json').write_text('{"url":"https://example.com/mesh","validator":"v1"}')
            spec = {'url': 'https://example.com/mesh', 'size': 6, 'sha256': hashlib.sha256(b'abcdef').hexdigest()}
            with patch('data_generation_server.assets.request', return_value=Response(b'def', 206, {'Content-Range': 'bytes 3-5/6', 'ETag': 'v1'})) as call:
                download(spec, target)
                self.assertEqual(call.call_args.args[1]['Range'], 'bytes=3-')
            self.assertEqual(target.read_bytes(), b'abcdef')
            with patch('data_generation_server.assets.request') as call:
                download(spec, target)
                call.assert_not_called()

    def test_ignored_range(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'mesh'
            target.with_name('mesh.part').write_bytes(b'bad')
            target.with_name('mesh.part.json').write_text('{"url":"https://example.com/mesh","validator":"v1"}')
            with patch('data_generation_server.assets.request', return_value=Response(b'abcdef')):
                download({'url': 'https://example.com/mesh', 'size': 6}, target)
            self.assertEqual(target.read_bytes(), b'abcdef')

    def test_bad_hash_never_published(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'mesh'
            with patch('data_generation_server.assets.request', side_effect=lambda *args: Response(b'bad')), patch('data_generation_server.assets.time.sleep'):
                with self.assertRaises(ValueError):
                    download({'url': 'https://example.com/mesh', 'md5': '0' * 32}, target)
            self.assertFalse(target.exists())

    def test_paths(self):
        for path in ('../escape', '/absolute', 'textures/../../escape', 'a\\b'):
            with self.assertRaises(ValueError): safe_path(Path('/tmp/assets'), path)

    def test_dependencies_and_dry_run(self):
        asset = {'provider': 'polyhaven', 'id': 'test', 'kind': 'models'}
        responses = [{'blend': {'2k': {'blend': {'url': 'https://example.com/model.blend', 'include': {'textures/color.png': {'url': 'https://example.com/color.png'}}}}}}, {'name': 'Test'}]
        with tempfile.TemporaryDirectory() as directory, patch('data_generation_server.assets.api', side_effect=responses):
            root = Path(directory) / 'new'
            result = acquire(asset, root, True)
            self.assertEqual(len(result['files']), 2)
            self.assertTrue(result['files'][1]['path'].endswith('textures/color.png'))
            self.assertFalse(root.exists())

    def test_duplicate_assets(self):
        asset = {'provider': 'direct', 'id': 'test', 'kind': 'people'}
        with self.assertRaises(ValueError): validate_assets([asset, asset])


if __name__ == '__main__': unittest.main()
