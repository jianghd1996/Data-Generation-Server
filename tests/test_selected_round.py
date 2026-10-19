import importlib.util
from pathlib import Path
import tempfile
import unittest
from data_generation_server.dataset import command_for
s=importlib.util.spec_from_file_location('round_preview',Path(__file__).parents[1]/'scripts/preview_selected_round.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

class SelectedRoundTests(unittest.TestCase):
    def catalog(self,root,count):
        mesh=root/'mesh.glb';mesh.write_bytes(b'mesh')
        blend=root/'scene.blend';blend.write_bytes(b'blend')
        hdri=root/'light.hdr';hdri.write_bytes(b'hdr')
        scenes=[{'id':m.SCENES[0],'environment':'courtyard','preset':0}]+[{'id':uid,'path':str(blend),'auto_place':False,'position':[1,2,3]} for uid in m.SCENES[1:]]
        return {'root':str(root),'people':[{'id':'person','path':str(mesh)}],
                'objects':[{'id':'object_'+str(i),'path':str(mesh)} for i in range(count-1)],
                'scenes':scenes,'backgrounds':[{'id':'hdr'+str(i),'path':str(hdri)} for i in range(24)]}

    def test_max_coverage_and_lighting(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);plan,_=m.build_plan(self.catalog(root,9),root/'output')
            self.assertEqual(len(plan['jobs']),9)
            self.assertEqual(len({j['subject']['id'] for j in plan['jobs']}),9)
            self.assertEqual({j['scene']['id'] for j in plan['jobs']},set(m.SCENES))
            self.assertEqual(plan['jobs'][0]['kind'],'person')
            external=plan['jobs'][1]
            cmd=command_for(external,plan['settings'],'blender',str(root))
            self.assertNotIn('--hdri',cmd);self.assertNotIn('--auto-place',cmd)
            self.assertEqual(cmd[cmd.index('--subject-position')+1:cmd.index('--subject-position')+4],['1','2','3'])
            self.assertIn('--hdri',command_for(plan['jobs'][0],plan['settings'],'blender',str(root)))

    def test_scenes_larger_than_subjects(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);plan,_=m.build_plan(self.catalog(root,2),root/'output')
            self.assertEqual(len(plan['jobs']),6)
            self.assertEqual(len({j['subject']['id'] for j in plan['jobs']}),2)
            self.assertEqual(len({j['scene']['id'] for j in plan['jobs']}),6)

    def test_missing_selected_scene_is_error(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);catalog=self.catalog(root,2);catalog['scenes'].pop()
            with self.assertRaises(ValueError):m.build_plan(catalog,root/'output')
