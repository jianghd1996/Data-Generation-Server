import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from data_generation_server.people import unpack, main


class PeopleTests(unittest.TestCase):
    def test_unpack_and_model_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'sample.zip'
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('person/mesh.glb', b'model')
                zipped.writestr('person/textures/color.png', b'texture')
            models = unpack(archive, root / 'extracted')
            self.assertEqual(models, ['person/mesh.glb'])
            self.assertTrue((root / 'extracted/person/textures/color.png').exists())
            self.assertEqual(unpack(archive, root / 'extracted'), models)

    def test_batch_continues_failure_and_reuses_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archives = root / 'archives'
            archives.mkdir()
            (archives / 'bad.zip').write_bytes(b'broken zip')
            with zipfile.ZipFile(archives / 'good.zip', 'w') as zipped:
                zipped.writestr('person.glb', b'model')
            args = ['--archive-dir', str(archives), '--root', str(root / 'dataset')]
            self.assertEqual(main(args), 1)
            report = json.loads((root / 'dataset/people-batch-report.json').read_text())
            self.assertEqual([x['status'] for x in report['results']], ['failed', 'ok'])
            model = root / 'dataset/people/direct/local_good/extracted/person.glb'
            timestamp = model.stat().st_mtime_ns
            self.assertEqual(main(args), 1)
            self.assertEqual(model.stat().st_mtime_ns, timestamp)

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'sample.zip'
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('../escape.glb', b'model')
            with self.assertRaises(ValueError): unpack(archive, root / 'extracted')
            self.assertFalse((root / 'escape.glb').exists())


if __name__ == '__main__': unittest.main()
