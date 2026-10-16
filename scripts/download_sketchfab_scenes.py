#!/usr/bin/env python3
"""Download environment candidates and convert glTF to packed .blend scenes.
Requires Sketchfab token env (same as people downloader) and Blender.
These are environment geometry candidates, NOT certified complete lit scenes.
Run preview/auto-place before production. 150 MiB per archive by default.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile

from data_generation_server.assets import digest, write_json

spec = importlib.util.spec_from_file_location('sf_people', Path(__file__).with_name('download_sketchfab_people.py'))
sf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sf)
CANDIDATES = [
    '6c6d15c2d3ec423b854c3623b9122c0d',  # Building scan interior
    '34090cc0cef74099a4d48c1e7541ffcb',  # Empty building interior
    '7fb5d8645766499388f6c2068abe3cc7',  # Factory hall
    '8b44a0291d1b436ebe35fff1c139099e',  # The Courtyard
    'faa5ef70eb5f4bb39caae051266574a8',  # Castle Courtyard
    '305a4bee5d574118befc320f83144d5f',  # House with courtyard
]
CONVERT = '''
import bpy,sys
from pathlib import Path
source,destination=sys.argv[sys.argv.index('--')+1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=source)
scene=bpy.context.scene
if not any(o.type=='MESH' for o in scene.objects):
    raise RuntimeError('No environment geometry imported')
for obj in scene.objects:
    obj.animation_data_clear()
# These exports have no certified original lighting. Use an explicit HDRI later.
scene.world=bpy.data.worlds.new('EnvironmentWorld')
scene.world.use_nodes=True
scene.world.node_tree.nodes.get('Background').inputs['Strength'].default_value=0.3
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=destination)
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--batch', action='store_true')
    group.add_argument('--model', action='append')
    group.add_argument('--search')
    p.add_argument('--blender', default='blender')
    p.add_argument('--root', type=Path, default=Path('dataset'))
    p.add_argument('--max-download-mib', type=int, default=150)
    p.add_argument('--insecure', action='store_true')
    p.add_argument('--ca-bundle')
    a=p.parse_args()
    if a.search:
        return sf.main(['--search',a.search]+(['--insecure'] if a.insecure else [])+(['--ca-bundle',a.ca_bundle] if a.ca_bundle else []))
    if a.max_download_mib<=0: p.error('Size limit must be positive')
    oauth=os.environ.get('SKETCHFAB_OAUTH_TOKEN','').strip()
    token=os.environ.get('SKETCHFAB_API_TOKEN','').strip()
    auth='Bearer '+oauth if oauth else ('Token '+token if token else None)
    if not auth: p.error('Set SKETCHFAB_API_TOKEN or SKETCHFAB_OAUTH_TOKEN')
    context=ssl.create_default_context(cafile=a.ca_bundle)
    if a.insecure:
        print('WARNING: TLS certificate verification disabled.',flush=True)
        context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
    root=a.root.expanduser().resolve()
    root.mkdir(parents=True,exist_ok=True)
    results=[]
    for uid in dict.fromkeys(CANDIDATES if a.batch else [sf.model_uid(v) for v in a.model]):
        folder=root/'scenes/direct'/('sketchfab_'+uid)
        registration=folder/'scene-registration.json'
        try:
            if registration.exists():
                old=json.loads(registration.read_text())
                if Path(old['path']).is_file() and old.get('blend_sha256')==digest(Path(old['path']),'sha256'):
                    print('[skip]',uid,'already converted',flush=True)
                    results.append({'uid':uid,'status':'skipped'});continue
            metadata=sf.get_json('models/'+uid,context,auth)
            # Do not include explicitly NoAI-tagged assets in this training workflow.
            tags=[str(t.get('name','')).lower() for t in metadata.get('tags',[]) if isinstance(t,dict)]
            if metadata.get('isNoAi') or metadata.get('isNoAI') or 'noai' in tags:
                raise ValueError('NoAI model excluded from dataset candidates')
            with tempfile.TemporaryDirectory(prefix='dgs-scene-') as temp:
                staging=Path(temp)
                sf.download(uid,staging,a.max_download_mib*1048576,2048*1048576,context,auth)
                downloaded=staging/'people/direct'/('sketchfab_'+uid)
                source=json.loads((downloaded/'people-source.json').read_text())
                models=json.loads((downloaded/'extracted/people-index.json').read_text())['models']
                gltfs=[downloaded/'extracted'/name for name in models if Path(name).suffix.lower() in ('.gltf','.glb')]
                if len(gltfs)!=1: raise ValueError('Expected one main glTF/GLB; manual selection required')
                folder.mkdir(parents=True,exist_ok=True)
                destination=folder/'environment.blend'
                # Save conversion to a temporary file first; never overwrite a registered scene on failure.
                converted=staging/'environment.blend'
                logfile=folder/'conversion.log'
                with logfile.open('w') as log:
                    subprocess.run([a.blender,'--background','--factory-startup','--python-exit-code','1',
                        '--python-expr',CONVERT,'--',str(gltfs[0]),str(converted)],stdout=log,stderr=subprocess.STDOUT,check=True)
                import shutil
                shutil.copy2(converted,destination)
                write_json(folder/'scene-source.json',source)
                record={'id':'sketchfab_'+uid,'identity':'sketchfab_'+uid,'path':str(destination),
                    'blend_sha256':digest(destination,'sha256'),'source_url':source['source_url'],
                    'license':source['license'],'author':source['author'],'position':[0,0,0],
                    'enabled':True,'review':'pending','environment_mode':'hdri',
                    'notes':'Environment mesh candidate, glTF materials and baked lighting may differ. Preview with auto-place; verify scale, textures, coverage and source terms.'}
                write_json(registration,record)
                print('[ready]',destination,flush=True)
                results.append({'uid':uid,'status':'ok'})
        except Exception as exc:
            message=str(exc) if isinstance(exc,(ValueError,RuntimeError)) else type(exc).__name__
            print('[failed]',uid,message,'(see conversion.log if present)',flush=True)
            results.append({'uid':uid,'status':'failed','error':message})
        finally:
            write_json(root/'sketchfab-scenes-report.json',{'results':results})
    print('Run dgs-dataset inventory, then regenerate preview. Old render plans still contain old courtyard jobs; regenerate them before running.')
    return int(any(r['status']=='failed' for r in results))


if __name__=='__main__': raise SystemExit(main())
