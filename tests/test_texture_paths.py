import tempfile
import unittest
from pathlib import Path
from data_generation_server.texture_paths import TextureResolver


class TextureTests(unittest.TestCase):
    def test_package_root_windows_case_and_spacing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scene-index.json').write_text('{}')
            (root / '3d').mkdir()
            blend = root / '3d/scene.blend'
            blend.touch()
            (root / 'Textures').mkdir()
            texture = root / 'Textures/Water_Bump.JPG'
            texture.touch()
            resolver = TextureResolver(blend)
            self.assertEqual(resolver.find('//textures/water bump.jpg'), texture)
            self.assertEqual(resolver.find(r'C:\old\textures\Water_Bump.JPG'), texture)
            self.assertIsNone(resolver.find('//textures/missing.jpg'))

    def test_ambiguous_names_not_chosen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blend = root / 'scene.blend'
            blend.touch()
            for name in ('a', 'b'):
                folder = root / name
                folder.mkdir()
                (folder / 'color.jpg').touch()
            self.assertIsNone(TextureResolver(blend).find('//absent/color.jpg'))
