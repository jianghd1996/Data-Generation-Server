import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('bk',Path(__file__).parents[1]/'scripts/download_blenderkit_scenes.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
UID='23caa39b-e0f2-4cf3-bff7-cd77e70d82fb'

class BlenderKitTests(unittest.TestCase):
    def asset(self):
        return {'assetBaseId':UID,'id':'version-id','assetType':'scene','isFree':True,'sourceAppVersion':'4.4.1','displayName':'room','files':[{'fileType':'blend','fileUploadSize':20,'downloadUrl':m.API+'downloads/test/'}]}

    def test_filter_paid_newer_and_size(self):
        a=self.asset()
        self.assertIsNotNone(m.choose_file(a,20,'4.5.3'))
        self.assertIsNone(m.choose_file(a,19,'4.5.3'))
        a['sourceAppVersion']='5.0.0'
        self.assertIsNone(m.choose_file(a,20,'4.5.3'))
        a['sourceAppVersion']='4.4';a['isFree']=False
        self.assertIsNone(m.choose_file(a,20,'4.5.3'))

    def test_auth_api_host_validation(self):
        with self.assertRaises(ValueError):m.api_url('https://evil.example/api/v1/search/')
        with self.assertRaises(ValueError):m.api_url('http://www.blenderkit.com/api/v1/search/')

    def test_stream_oversize_removes_partial(self):
        class Response(io.BytesIO):headers={}
        with tempfile.TemporaryDirectory() as tmp,patch.object(m.urllib.request,'urlopen',return_value=Response(b'x'*30)):
            target=Path(tmp)/'scene.blend'
            with self.assertRaises(ValueError):m.stream('https://cdn.example/file',target,20,None,30)
            self.assertFalse(target.exists());self.assertFalse(target.with_suffix('.part').exists())

    def test_download_register_and_skip(self):
        a=self.asset()
        def stream(url,target,*args):target.write_bytes(b'BLENDER-fixture')
        def validate(cmd,**kwargs):Path(cmd[-1]).write_bytes(b'BLENDER-packed')
        with tempfile.TemporaryDirectory() as tmp:
            args=SimpleNamespace(root=Path(tmp),max_download_mib=150,blender='blender')
            with patch.object(m,'request_json',return_value={'filePath':'https://cdn.example/file?secret=SIGNED'}),patch.object(m,'stream',side_effect=stream),patch.object(m.subprocess,'run',side_effect=validate):
                self.assertEqual(m.download(a,a['files'][0],args,None),'ok')
            folder=Path(tmp)/'scenes/direct'/('blenderkit_'+UID)
            record=json.loads((folder/'scene-registration.json').read_text())
            self.assertEqual(record['review'],'pending')
            self.assertNotIn('SIGNED',(folder/'scene-source.json').read_text())
            from data_generation_server.dataset import inventory
            scenes=[x for x in inventory(Path(tmp))['scenes'] if x.get('path')]
            self.assertEqual(len(scenes),1)
            with patch.object(m,'request_json',side_effect=AssertionError('network')):
                self.assertEqual(m.download(a,a['files'][0],args,None),'skipped')
