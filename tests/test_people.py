import tempfile
import unittest
import zipfile
from pathlib import Path
from data_generation_server.people import unpack


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

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'sample.zip'
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('../escape.glb', b'model')
            with self.assertRaises(ValueError): unpack(archive, root / 'extracted')
            self.assertFalse((root / 'escape.glb').exists())


if __name__ == '__main__': unittest.main()
