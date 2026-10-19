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
                self.assertEqual(m.main(['--root',str(root),'--blender','blender','--import-only']),1)
            self.assertTrue(original.is_file())
            self.assertFalse((root/'catalog.json').exists())

    def test_render_11_frames_keeps_world(self):
        a=SimpleNamespace(root=Path('/data'),model_id='chinese_cabinet',blender='/bin/blender',frames=11,samples=16)
        command=m.render_command({'path':'/data/forest.blend'},a,Path('/data/output'))
        self.assertEqual(command[command.index('--frames')+1],'11')
        self.assertNotIn('--hdri',command)
        self.assertIn('--auto-place',command)

    def test_fixed_position_command(self):
        a=SimpleNamespace(root=Path('/data'),model_id='chinese_cabinet',blender='/bin/blender',frames=11,samples=16)
        command=m.render_command({'path':'/data/forest.blend','auto_place':False,'position':[1,2,3]},a,Path('/data/output'))
        self.assertNotIn('--auto-place',command)
        i=command.index('--subject-position')
        self.assertEqual(command[i+1:i+4],['1','2','3'])

    def test_current_pool_excludes_disabled_duplicates_and_archives(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);records=[]
            for name in ('pavilion','local','disabled','scene-sources/old','scenes/blenderkit/raw'):
                path=root/(name+'.blend');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(name.encode())
                records.append({'id':name,'path':str(path),'enabled':name!='disabled'})
            records.append(dict(records[0],id='duplicate'))
            result=m.current_scenes({'scenes':records},root)
            self.assertEqual([s['id'] for s in result],['pavilion','local'])

    def test_reuse_valid_fixed_position_and_invalidate_change(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);scene=root/'scene.blend';scene.write_bytes(b'scene')
            output=root/'old-preview';output.mkdir()
            for folder in ('rgb','mask'):
                (output/folder).mkdir();(output/folder/(folder+'_0001.png')).write_bytes(b'image')
            from data_generation_server.assets import digest
            data={'path':str(scene),'blend_sha256':digest(scene,'sha256'),'auto_place':False,'position':[1,2,3]}
            (output/'SUCCESS.json').write_text(json.dumps({'frames':1}))
            (output/'local-scene-check.json').write_text(json.dumps({'blend_sha256':data['blend_sha256']}))
            (output/'render-config.json').write_text(json.dumps({'scene':str(scene),'model_id':'chinese_cabinet','samples':16,'width':1280,'height':720,'auto_place':True}))
            (output/'render-report.json').write_text(json.dumps({'subject_position':[1,2,3]}))
            a=SimpleNamespace(frames=11,samples=16,model_id='chinese_cabinet')
            self.assertTrue(m.complete(output,a,data))
            dest=root/'unified';dest.mkdir();m.reuse_preview(output,dest)
            self.assertTrue(m.complete(dest,a,data))
            data['position']=[4,5,6];self.assertFalse(m.complete(dest,a,data))

    def test_inventory_does_not_restore_archived_source_entries(self):
        from data_generation_server.dataset import inventory
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);archive=root/'scene-sources/old.blend';archive.parent.mkdir();archive.write_bytes(b'old')
            upload=root/'scenes/blenderkit/raw.blend';upload.parent.mkdir(parents=True);upload.write_bytes(b'raw')
            old={'objects':[],'people':[],'backgrounds':[],'scenes':[{'id':'raw','path':str(archive)}]}
            result=inventory(root,old)
            self.assertFalse(any(s.get('path') for s in result['scenes']))
