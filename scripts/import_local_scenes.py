#!/usr/bin/env python3
"""Organize uploaded .blend scenes, preserve originals, and render 11-view checks.
Default source: dataset/scenes/blenderkit. After ALL imports succeed, archive the
whole upload tree (including textures) to dataset/scene-sources/blenderkit-TIME.
Failed imports leave the upload tree untouched. Successful packed scenes live
in dataset/scenes/direct/local_NAME_HASH/environment.blend. Never permanently
deletes source assets. Re-run resumes the saved import report and valid renders.
"""
import argparse
import concurrent.futures
from datetime import datetime
import hashlib
import html
import importlib.util
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading

from data_generation_server.assets import digest, write_json

spec=importlib.util.spec_from_file_location('bk_import',Path(__file__).with_name('download_blenderkit_scenes.py'))
bk=importlib.util.module_from_spec(spec);spec.loader.exec_module(bk)


def identifier(path,fingerprint):
    name=re.sub(r'^\d{8}_\d{6}_','',path.stem)
    slug=re.sub(r'[^a-zA-Z0-9_-]+','_',name).strip('_')[:64] or 'scene'
    return 'local_'+slug+'_'+fingerprint[:12]


def import_one(source,root,blender):
    fingerprint=digest(source,'sha256')
    uid=identifier(source,fingerprint)
    folder=root/'scenes/direct'/uid
    destination=folder/'environment.blend'
    registration=folder/'scene-registration.json'
    if registration.is_file():
        old=json.loads(registration.read_text())
        if (old.get('source_sha256')==fingerprint and destination.is_file()
                and old.get('blend_sha256')==digest(destination,'sha256')):
            print('[skip import]',source.name,flush=True)
            return old
    folder.mkdir(parents=True,exist_ok=True)
    temporary=folder/'environment.importing.blend'
    logfile=folder/'import.log'
    print('[import]',source.name,flush=True)
    try:
        with logfile.open('w') as log:
            subprocess.run([blender,'--background','--factory-startup','--disable-autoexec',
                '--python-exit-code','1','--python-expr',bk.CHECK,'--',str(source),str(temporary)],
                stdout=log,stderr=subprocess.STDOUT,check=True)
        if not temporary.is_file(): raise RuntimeError('Blender did not save packed scene')
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    record={'id':uid,'identity':'local_'+fingerprint,'name':source.stem,'path':str(destination),
        'source_original':str(source),'source_sha256':fingerprint,
        'blend_sha256':digest(destination,'sha256'),'position':[0,0,0],'enabled':True,'review':'pending',
        'notes':'Locally uploaded scene; dependencies checked and packed. Preview before production.'}
    if registration.exists():
        old=json.loads(registration.read_text())
        record.update({key:old[key] for key in ('position','enabled','review','notes') if key in old})
    write_json(registration,record)
    return record


def render_command(scene,args,output):
    cmd=[sys.executable,'-m','data_generation_server.render','--root',str(args.root),
        '--scene',scene['path'],'--auto-place','--model-id',args.model_id,
        '--blender',args.blender,'--frames',str(args.frames),'--width','1280','--height','720',
        '--orientation','landscape','--samples',str(args.samples),'--no-video',
        '--no-save-scene','--output',str(output),'--overwrite']
    # No --hdri: standalone external scenes keep their own world lighting.
    return cmd


def complete(output,args,scene):
    try:
        success=json.loads((output/'SUCCESS.json').read_text())
        config=json.loads((output/'render-config.json').read_text())
        stamp=json.loads((output/'local-scene-check.json').read_text())
        return (success.get('frames')==args.frames and config.get('samples')==args.samples
            and config.get('scene')==scene['path'] and config.get('model_id')==args.model_id
            and stamp.get('blend_sha256')==scene['blend_sha256']
            and all((output/'rgb'/('rgb_%04d.png'%i)).is_file()
                    and (output/'mask'/('mask_%04d.png'%i)).is_file() for i in range(1,args.frames+1)))
    except (OSError,ValueError):return False


def gallery(folder,results,frames):
    cards=[]
    for item in sorted(results,key=lambda x:x['name']):
        uid=item['id'];status=item['status']
        images=''.join('<a href="{0}/rgb/rgb_{1:04d}.png"><img loading="lazy" width="240" src="{0}/rgb/rgb_{1:04d}.png"></a>'.format(html.escape(uid),i)
            for i in range(1,frames+1)) if status in ('ok','skipped') else ''
        cards.append('<section><h2>'+html.escape(item['name'])+' — '+html.escape(status)+'</h2><p>'+html.escape(item.get('error',''))+'</p><a href="'+html.escape(uid)+'/render.log">render log</a> | <a href="'+html.escape(uid)+'/mask/">masks</a><div>'+images+'</div></section>')
    (folder/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Uploaded scene checks</title><style>body{font:16px sans-serif;margin:24px;background:#eee}section{background:white;padding:16px;margin:16px 0}img{margin:4px}a{color:#246}</style><h1>Uploaded scene checks</h1><p>11 frames sample the trajectory keypoints; repeated center views are expected. Inspect RGB, masks, scale and lighting.</p>'+''.join(cards),encoding='utf-8')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('dataset'))
    p.add_argument('--source',type=Path)
    p.add_argument('--blender',required=True)
    p.add_argument('--model-id',default='chinese_cabinet')
    p.add_argument('--gpus',default='0,1,2,3')
    p.add_argument('--workers-per-gpu',type=int,default=1)
    p.add_argument('--frames',type=int,default=11)
    p.add_argument('--samples',type=int,default=16)
    p.add_argument('--import-only',action='store_true')
    a=p.parse_args(argv)
    a.root=a.root.expanduser().resolve()
    source=(a.source or a.root/'scenes/blenderkit').expanduser().resolve()
    # Archival moves a whole directory; scope it strictly to this designated upload folder.
    if source!=a.root/'scenes/blenderkit':p.error('--source must be ROOT/scenes/blenderkit')
    if min(a.frames,a.samples,a.workers_per_gpu)<1:p.error('Frames, samples and workers must be positive')
    a.blender=shutil.which(a.blender)
    if not a.blender:p.error('Blender executable not found')
    gpus=[v.strip() for v in a.gpus.split(',')]
    if not gpus or any(not v.isdigit() for v in gpus) or len(set(gpus))!=len(gpus):p.error('GPU IDs must be distinct comma-separated integers')
    report_path=a.root/'local-scenes-import-report.json'
    history=json.loads(report_path.read_text()) if report_path.exists() else {'scenes':[],'failures':[]}
    imported={r['id']:r for r in history['scenes'] if Path(r['path']).is_file()
              and r.get('blend_sha256')==digest(Path(r['path']),'sha256')}
    failed=[]
    files=sorted(source.rglob('*.blend')) if source.is_dir() else []
    fingerprints={r.get('source_sha256') for r in imported.values()}
    for path in files:
        if path.is_symlink():
            failed.append({'source':str(path),'error':'Symlink source requires manual review'});continue
        try:
            fp=digest(path,'sha256')
            if fp in fingerprints:
                print('[duplicate/previous]',path.name,flush=True);continue
            record=import_one(path,a.root,a.blender)
            imported[record['id']]=record;fingerprints.add(fp)
        except Exception as exc:
            failed.append({'source':str(path),'error':str(exc)})
            print('[failed import]',path.name,'see scene import.log',flush=True)
        write_json(report_path,{'scenes':list(imported.values()),'failures':failed})
    if files and not failed:
        backup=a.root/'scene-sources'/('blenderkit-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.parent.mkdir(parents=True,exist_ok=True)
        shutil.move(str(source),str(backup))
        print('[archived originals]',backup,flush=True)
        for record in imported.values():
            old=Path(record.get('source_original',''))
            if old.is_relative_to(source) and (backup/old.relative_to(source)).is_file():
                record['source_archive']=str(backup/old.relative_to(source))
                write_json(Path(record['path']).parent/'scene-registration.json',record)
    write_json(report_path,{'scenes':list(imported.values()),'failures':failed})
    if not imported:p.error('No imported scenes; check upload path and import logs')
    # Only rebuild full inventory after successful archival: raw failed files must not
    # accidentally become additional enabled scene entries.
    if not failed:
        from data_generation_server.dataset import inventory
        cp=a.root/'catalog.json'
        prior=json.loads(cp.read_text()) if cp.exists() else None
        write_json(cp,inventory(a.root,prior))
    if a.import_only:return int(bool(failed))
    output=a.root/'renders/local-scene-checks';output.mkdir(parents=True,exist_ok=True)
    jobs=queue.Queue()
    for record in imported.values():jobs.put(record)
    results=[];lock=threading.Lock()
    def worker(gpu):
        while True:
            try:scene=jobs.get_nowait()
            except queue.Empty:return
            folder=output/scene['id'];folder.mkdir(parents=True,exist_ok=True)
            item={'id':scene['id'],'name':scene.get('name',scene['id']),'gpu':gpu,'output':str(folder)}
            if complete(folder,a,scene):item['status']='skipped'
            else:
                print('[render GPU '+gpu+']',item['name'],flush=True)
                try:
                    env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']=gpu
                    with (folder/'render.log').open('w') as log:
                        subprocess.run(render_command(scene,a,folder),env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
                    write_json(folder/'local-scene-check.json',{'blend_sha256':scene['blend_sha256']})
                    if not complete(folder,a,scene):raise RuntimeError('Render outputs incomplete')
                    item['status']='ok'
                except Exception as exc:item.update(status='failed',error=str(exc))
            with lock:
                results.append(item)
                write_json(output/'report.json',{'results':results,'import_failures':failed})
                gallery(output,results,a.frames)
                print('['+item['status']+']',item['name'],flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(gpus)*a.workers_per_gpu) as pool:
        futures=[pool.submit(worker,gpu) for gpu in gpus for _ in range(a.workers_per_gpu)]
        for f in futures:f.result()
    print('[gallery]',output/'index.html',flush=True)
    return int(bool(failed) or any(r['status']=='failed' for r in results))


if __name__=='__main__':raise SystemExit(main())
