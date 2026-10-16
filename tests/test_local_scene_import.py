import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('local_import',Path(__file__).parents[1]/'scripts/import_local_scenes.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class LocalSceneTests(unittest.TestCase):
    def test_organize_archive_and_resume(self):
        def blender(cmd,**kwargs):Path(cmd[-1]).write_bytes(b'packed blend')
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'dataset';upload=root/'scenes/blenderkit';upload.mkdir(parents=True)
            original=upload/'20261016_154227_The Lonely Outpost.blend';original.write_bytes(b'original blend')
            textures=upload/'textures';textures.mkdir();(textures/'tree.jpg').write_bytes(b'texture')
            with patch.object(m.shutil,'which',return_value='/bin/blender'),patch.object(m.subprocess,'run',side_effect=blender):
                self.assertEqual(m.main(['--root',str(root),'--blender','blender','--import-only']),0)
                self.assertEqual(m.main(['--root',str(root),'--blender','blender','--import-only']),0)
            self.assertFalse(upload.exists())
            history=json.loads((root/'local-scenes-import-report.json').read_text())
            scene=history['scenes'][0]
            self.assertTrue(Path(scene['source_archive']).is_file())
            self.assertTrue((Path(scene['source_archive']).parent/'textures/tree.jpg').is_file())
            catalog=json.loads((root/'catalog.json').read_text())
            self.assertEqual(len([x for x in catalog['scenes'] if x.get('path')]),1)
            self.assertTrue(all(not x['enabled'] for x in catalog['scenes'] if 'preset' in x))

    def test_failed_import_keeps_original_tree(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=root/'scenes/blenderkit';source.mkdir(parents=True)
            original=source/'bad.blend';original.write_bytes(b'bad')
            with patch.object(m.shutil,'which',return_value='/bin/blender'),patch.object(m.subprocess,'run',side_effect=RuntimeError('Missing texture')):
                with self.assertRaises(SystemExit):m.main(['--root',str(root),'--blender','blender','--import-only'])
            self.assertTrue(original.is_file())
            self.assertFalse((root/'catalog.json').exists())

    def test_render_11_frames_keeps_world(self):
        a=SimpleNamespace(root=Path('/data'),model_id='chinese_cabinet',blender='/bin/blender',frames=11,samples=16)
        command=m.render_command({'path':'/data/forest.blend'},a,Path('/data/output'))
        self.assertEqual(command[command.index('--frames')+1],'11')
        self.assertNotIn('--hdri',command)
        self.assertIn('--auto-place',command)
