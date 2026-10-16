import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from data_generation_server.scene_placement import find_placement
from data_generation_server.dataset import inventory,grid_plan

spec=importlib.util.spec_from_file_location('positions',Path(__file__).parents[1]/'scripts/preview_scene_positions.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class PositionCandidatesTests(unittest.TestCase):
    def test_candidates_are_distinct_and_first_unchanged(self):
        def ray(origin,direction,distance):
            if direction==(0,0,-1):return ((origin[0],origin[1],0),(0,0,1))
            return None
        args=((0,0,0),1,4.5,[(-90,12)],2,ray)
        points=[find_placement(*args,candidate_index=i) for i in range(6)]
        self.assertEqual(points[0],find_placement(*args))
        self.assertEqual(len(set(points)),6)

    def test_selection_persists_manual_mode(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);scene_dir=root/'scenes/direct/test';scene_dir.mkdir(parents=True)
            scene=scene_dir/'environment.blend';scene.write_bytes(b'test')
            record={'id':'test','path':str(scene),'identity':'test','enabled':True}
            (scene_dir/'scene-registration.json').write_text(json.dumps(record))
            catalog={'root':str(root),'objects':[],'people':[],'scenes':[record],'backgrounds':[]}
            (root/'catalog.json').write_text(json.dumps(catalog))
            output=root/'renders/placement-previews/test/candidate_02';output.mkdir(parents=True)
            (output/'candidate.json').write_text(json.dumps({'status':'ok','position':[1,2,3],'scene_path':str(scene)}))
            m.select(root,'test',2)
            previous=json.loads((root/'catalog.json').read_text())
            updated=inventory(root,previous)
            chosen=next(x for x in updated['scenes'] if x['id']=='test')
            self.assertEqual(chosen['position'],[1,2,3]);self.assertFalse(chosen['auto_place'])
            self.assertTrue(list((root/'placement-backups').iterdir()))
