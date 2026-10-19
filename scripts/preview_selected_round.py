#!/usr/bin/env python3
"""Preview every active subject and six selected scenes using max(N,M) pairs.
People first; subjects and scenes cycle in stable order. Each pair renders one
720P landscape far shot. External scenes keep their world; courtyard uses HDRI.
This script generates an independent catalog/plan; it never starts full videos.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from data_generation_server.assets import write_json
from data_generation_server.dataset import run_jobs
from data_generation_server.preview_gallery import write_gallery

SCENES=[
 'courtyard_00',
 'blender_barcelona_pavilion',
 'green-forest-landscape_ac97dd90-8a40-4cb6-ad30-cb450f10381a_ae7e93f2',
 'local_Lakeside_Cabin_in_the_Mountains_4678f34bea50',
 'local_The_Eternal_Bloom_Mill_67e97b9d6687',
 'local_The_Lonely_Outpost_c33000883046',
]


def build_plan(catalog,output,samples=16):
    by_id={s['id']:s for s in catalog['scenes']}
    missing=[uid for uid in SCENES if uid not in by_id]
    if missing:raise ValueError('Selected scenes missing from catalog: '+', '.join(missing)+'; run inventory first')
    scenes=[]
    for uid in SCENES:
        scene=dict(by_id[uid],enabled=True)
        if scene.get('path') and not Path(scene['path']).is_file():raise ValueError('Scene file missing: '+scene['path'])
        scenes.append(scene)
    subjects=[]
    for kind,category in [('person','people'),('object','objects')]:
        for subject in catalog[category]:
            if not subject.get('enabled',True):continue
            if not subject.get('path') or not Path(subject['path']).is_file():
                print('[skip missing subject]',subject['id'],flush=True);continue
            subjects.append((kind,subject))
    if not subjects:raise ValueError('No enabled ready subjects')
    backgrounds=[b for b in catalog['backgrounds'] if b.get('enabled',True) and b.get('path') and Path(b['path']).is_file()]
    if not backgrounds:raise ValueError('Courtyard needs at least one ready HDRI')
    jobs=[]
    for i in range(max(len(subjects),len(scenes))):
        kind,subject=subjects[i%len(subjects)];scene=scenes[i%len(scenes)]
        background={'id':'scene_world','path':None} if scene.get('path') else backgrounds[i%len(backgrounds)]
        raw=f"{kind}_{subject['id']}__{scene['id']}"
        uid=re.sub(r'[^A-Za-z0-9_-]','_',raw)+'_'+hashlib.sha256(raw.encode()).hexdigest()[:8]
        jobs.append({'id':uid,'kind':kind,'subject':subject,'scene':scene,'background':background,
                     'auto_place':scene.get('auto_place',bool(scene.get('path'))),
                     'shot':'far','orientation':'landscape','seed':42,'output':str((output/uid).resolve())})
    plan={'version':1,'root':catalog['root'],'preview':True,'environment_sampling':'subject-scene-cyclic-coverage',
          'settings':{'frames':1,'theta':30,'phi':5,'samples':samples,'radius':4.5,'no_video':True,'no_save_scene':True},
          'jobs':jobs,'subject_count':len(subjects),'scene_count':len(scenes)}
    selected=dict(catalog,scenes=scenes)
    return plan,selected


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('dataset'))
    p.add_argument('--blender',required=True)
    p.add_argument('--gpus',default='0,1,2,3')
    p.add_argument('--samples',type=int,default=16)
    p.add_argument('--plan-only',action='store_true')
    a=p.parse_args(argv);root=a.root.expanduser().resolve()
    if a.samples<1:p.error('Samples must be positive')
    gpus=a.gpus.split(',')
    if any(not g.isdigit() for g in gpus) or len(set(gpus))!=len(gpus):p.error('Invalid GPU IDs')
    catalog=json.loads((root/'catalog.json').read_text())
    output=root/'renders/local-scene-checks/subject-scene-round'
    plan,selected=build_plan(catalog,output,a.samples)
    write_json(root/'selected-round-catalog.json',selected)
    write_json(root/'selected-round-preview-plan.json',plan)
    gallery=write_gallery(plan,output)
    # This batch covers subjects/scenes, not every HDRI.
    content=gallery.read_text().replace('每个启用的物体/人物、场景和背景至少出现一次','每个启用主体和指定场景至少出现一次；完整场景保留自身环境')
    gallery.write_text(content,encoding='utf-8')
    print('\n=== Scenes ===')
    for scene in selected['scenes']:print(scene['id'],'position=',scene.get('position',[0,0,0]),'mode=', 'auto' if scene.get('auto_place',bool(scene.get('path'))) else 'fixed')
    print('\n=== All preview pairs (people first) ===')
    for i,j in enumerate(plan['jobs'],1):print('%03d | %s | %s | %s'%(i,j['kind'],j['subject']['id'],j['scene']['id']))
    print('\n%d subjects, %d scenes -> %d images'%(plan['subject_count'],plan['scene_count'],len(plan['jobs'])))
    print('[gallery]',gallery,flush=True)
    if a.plan_only:return 0
    return run_jobs(plan,a.blender,root/'selected-round-preview.run-report.json',gpus=gpus,retry_incomplete=True)


if __name__=='__main__':raise SystemExit(main())
