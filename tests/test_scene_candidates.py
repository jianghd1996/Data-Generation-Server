import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('scene_candidates',Path(__file__).parents[1]/'scripts/download_sketchfab_scenes.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class CandidateTests(unittest.TestCase):
    def test_conversion_registration_and_skip(self):
        uid=m.CANDIDATES[0]
        def fake_download(uid,root,*args):
            folder=root/'people/direct'/('sketchfab_'+uid)
            (folder/'extracted').mkdir(parents=True)
            (folder/'extracted/scene.gltf').write_text('{}')
            (folder/'extracted/people-index.json').write_text(json.dumps({'models':['scene.gltf']}))
            (folder/'people-source.json').write_text(json.dumps({'source_url':'https://sketchfab.com/models/'+uid,'license':{'label':'CC BY'},'author':{'username':'artist'}}))
        def convert(cmd,**kwargs):
            Path(cmd[-1]).write_bytes(b'fixture blend')
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ,{'SKETCHFAB_API_TOKEN':'test'}), patch.object(sys,'argv',['script','--model',uid,'--root',t]), patch.object(m.sf,'get_json',return_value={}), patch.object(m.sf,'download',side_effect=fake_download), patch.object(m.subprocess,'run',side_effect=convert):
            self.assertEqual(m.main(),0)
            rec=json.loads((Path(t)/'scenes/direct'/('sketchfab_'+uid)/'scene-registration.json').read_text())
            self.assertTrue(Path(rec['path']).is_file())
            self.assertEqual(rec['review'],'pending')
            with patch.object(m.sf,'get_json',side_effect=AssertionError('network on rerun')):
                self.assertEqual(m.main(),0)

    def test_inventory_disables_old_courtyards(self):
        from data_generation_server.dataset import inventory
        with tempfile.TemporaryDirectory() as t:
            old={'objects':[],'people':[],'backgrounds':[],'scenes':[{'id':'courtyard_00','enabled':True}]}
            result=inventory(Path(t),old)
            courtyards=[s for s in result['scenes'] if s['identity']=='procedural_courtyard']
            self.assertEqual(len(courtyards),12)
            self.assertEqual([s['id'] for s in courtyards if s['enabled']],['courtyard_00'])
