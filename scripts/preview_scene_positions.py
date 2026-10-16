#!/usr/bin/env python3
"""Render numbered floor candidates; select one with --select SCENE_ID NUMBER."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import html
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
from data_generation_server.assets import write_json


def select(root,uid,number):
    folder=root/'renders/placement-previews'/uid/('candidate_%02d'%number)
    result=json.loads((folder/'candidate.json').read_text())
    if result['status']!='ok':raise ValueError('Cannot select failed candidate')
    cp=root/'catalog.json';catalog=json.loads(cp.read_text())
    scene=next(s for s in catalog['scenes'] if s['id']==uid)
    if scene['path']!=result['scene_path'] or not Path(scene['path']).is_file():raise ValueError('Scene changed or missing')
    backup=root/'placement-backups'/datetime.now().strftime('%Y%m%d-%H%M%S-%f');backup.mkdir(parents=True)
    shutil.copy2(cp,backup/'catalog.json')
    registration=Path(scene['path']).parent/'scene-registration.json'
    if registration.exists():
        record=json.loads(registration.read_text());shutil.copy2(registration,backup/'scene-registration.json')
        record.update(position=result['position'],auto_place=False);write_json(registration,record)
    scene.update(position=result['position'],auto_place=False);write_json(cp,catalog)
    print('[selected]',uid,number,result['position'],'; regenerate plans before batch rendering')


def gallery(output):
    sections=[]
    for directory in sorted(p for p in output.iterdir() if p.is_dir()):
        cards=[]
        for record in sorted(directory.glob('candidate_*/candidate.json')):
            r=json.loads(record.read_text());rel=html.escape(str(record.parent.relative_to(output)))
            caption=html.escape('Candidate %s | %s | %s'%(r['number'],r['status'],r.get('position','see log')))
            img='<a href="{0}/rgb/rgb_0001.png"><img width="400" src="{0}/rgb/rgb_0001.png"></a>'.format(rel) if r['status']=='ok' else ''
            cards.append('<article><p>'+caption+'</p>'+img+'<p><a href="'+rel+'/render.log">log</a> | <a href="'+rel+'/mask/mask_0001.png">mask</a></p></article>')
        sections.append('<h2>'+html.escape(directory.name)+'</h2><div class="cards">'+''.join(cards)+'</div>')
    (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Floor candidates</title><style>body{font:16px sans-serif;margin:24px}.cards{display:flex;flex-wrap:wrap}article{width:420px;margin:8px;background:#eee}</style><h1>Floor candidates</h1><p>Choose scene ID + candidate number. Same starting view, different floor positions; geometry checks do not guarantee semantic placement.</p>'+''.join(sections),encoding='utf-8')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('dataset'));p.add_argument('--blender')
    p.add_argument('--scene-id',action='append');p.add_argument('--candidates',type=int,default=6)
    p.add_argument('--model-id',default='chinese_cabinet');p.add_argument('--gpus',default='0,1,2,3')
    p.add_argument('--select',nargs=2,metavar=('SCENE_ID','NUMBER'))
    a=p.parse_args(argv);root=a.root.expanduser().resolve()
    if a.select:
        uid,number=a.select
        if not re.fullmatch(r'[A-Za-z0-9_-]+',uid) or not number.isdigit() or int(number)<1:p.error('Invalid selection')
        select(root,uid,int(number));return 0
    if not a.blender or not shutil.which(a.blender):p.error('Provide --blender /path/to/blender')
    if not 1<=a.candidates<=24:p.error('--candidates must be 1..24')
    gpus=a.gpus.split(',')
    if any(not x.isdigit() for x in gpus) or len(set(gpus))!=len(gpus):p.error('Invalid GPU list')
    catalog=json.loads((root/'catalog.json').read_text())
    pool={s['id']:s for s in catalog['scenes'] if s.get('path') and s.get('enabled',True) and Path(s['path']).is_file()}
    if a.scene_id:
        if set(a.scene_id)-pool.keys():p.error('Unknown or disabled scene ID')
        pool={uid:pool[uid] for uid in dict.fromkeys(a.scene_id)}
    if not pool:p.error('No enabled external scenes')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+',uid) for uid in pool):p.error('Unsafe scene ID')
    output=root/'renders/placement-previews';output.mkdir(parents=True,exist_ok=True)
    jobs=queue.Queue()
    for scene in pool.values():
        for number in range(1,a.candidates+1):jobs.put((scene,number))
    lock=threading.Lock();failures=[]
    def worker(gpu):
        while True:
            try:scene,number=jobs.get_nowait()
            except queue.Empty:return
            folder=output/scene['id']/('candidate_%02d'%number);folder.mkdir(parents=True,exist_ok=True)
            result={'scene_id':scene['id'],'scene_path':scene['path'],'number':number,'model_id':a.model_id}
            cmd=[sys.executable,'-m','data_generation_server.render','--root',str(root),'--scene',scene['path'],
                '--model-id',a.model_id,'--auto-place','--placement-index',str(number-1),
                '--subject-position',*map(str,scene.get('position',[0,0,0])),
                '--blender',a.blender,'--frames','1','--width','1280','--height','720',
                '--orientation','landscape','--samples','16','--no-video','--no-save-scene','--overwrite','--output',str(folder)]
            print('[start GPU %s] %s candidate %d'%(gpu,scene['id'],number),flush=True)
            try:
                env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']=gpu
                with (folder/'render.log').open('w') as log:subprocess.run(cmd,check=True,env=env,stdout=log,stderr=subprocess.STDOUT)
                report=json.loads((folder/'render-report.json').read_text())
                if not (folder/'SUCCESS.json').exists():raise RuntimeError('Missing success marker')
                result.update(status='ok',position=report['subject_position'])
            except Exception as exc:result.update(status='failed',error=str(exc));failures.append(result)
            with lock:
                write_json(folder/'candidate.json',result);gallery(output)
                print('[%s] %s candidate %d %s'%(result['status'],scene['id'],number,result.get('position','see render.log')),flush=True)
    with ThreadPoolExecutor(max_workers=len(gpus)) as executor:
        tasks=[executor.submit(worker,gpu) for gpu in gpus]
        for task in tasks:task.result()
    print('[gallery]',output/'index.html');return int(bool(failures))


if __name__=='__main__':raise SystemExit(main())
