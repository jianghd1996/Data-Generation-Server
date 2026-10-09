"""Static paginated preview gallery; opens locally without external dependencies."""
import json
import os
from pathlib import Path
from urllib.parse import quote


def write_gallery(plan, root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for job in plan['jobs']:
        output = Path(job['output'])
        relative = quote(os.path.relpath(output, root).replace(os.sep, '/'), safe='/')
        records.append({'id': job['id'], 'kind': job['kind'], 'subject': job['subject']['id'],
                        'scene': job['scene']['id'], 'background': job['background']['id'], 'folder': relative})
    data = json.dumps(records, ensure_ascii=False).replace('<', '\\u003c')
    html = '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>DGS 素材组合检查</title>
<style>body{font:15px system-ui;background:#f3f4f6;margin:24px;color:#222}header{position:sticky;top:0;background:#f3f4f6;padding:12px 0}select,input,button{padding:8px;margin:4px}#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}article{background:white;padding:12px;border-radius:8px;overflow-wrap:anywhere}img{width:100%;aspect-ratio:16/9;object-fit:contain;background:#ddd}p{margin:6px 0}a{margin-right:12px}</style>
<h1>素材组合检查</h1><p>每个启用的物体/人物 × 场景 × 背景，一张 720P 横屏远景图。图片未生成时显示“待生成或失败”，具体错误见批次日志。</p>
<header><select id="kind"><option value="">全部主体</option><option>object</option><option>person</option></select><select id="scene"></select><select id="background"></select><input id="search" placeholder="搜索主体名称"><button id="prev">上一页</button><button id="next">下一页</button><span id="count"></span></header><main id="grid"></main>
<script>const rows=__DATA__;let page=0;const size=48;const get=id=>document.getElementById(id);
for(const key of ['scene','background']){const all=new Option('全部'+(key==='scene'?'场景':'背景'),'');get(key).add(all);[...new Set(rows.map(r=>r[key]))].sort().forEach(v=>get(key).add(new Option(v,v)));}
function show(){const filtered=rows.filter(r=>(!get('kind').value||r.kind===get('kind').value)&&(!get('scene').value||r.scene===get('scene').value)&&(!get('background').value||r.background===get('background').value)&&r.subject.toLowerCase().includes(get('search').value.toLowerCase()));const pages=Math.max(1,Math.ceil(filtered.length/size));page=Math.min(page,pages-1);get('count').textContent=`${filtered.length} / ${rows.length} 组合 · ${page+1}/${pages} 页`;get('grid').replaceChildren();for(const r of filtered.slice(page*size,(page+1)*size)){const card=document.createElement('article');const img=document.createElement('img');img.loading='lazy';img.src=r.folder+'/rgb/rgb_0001.png';img.alt=r.subject;const state=document.createElement('p');state.textContent='加载中';img.onload=()=>state.textContent='RGB 已生成（请同时检查 mask）';img.onerror=()=>state.textContent='待生成或失败';card.append(img,state);for(const text of [r.kind+' · '+r.subject,'场景：'+r.scene,'背景：'+r.background]){const p=document.createElement('p');p.textContent=text;card.append(p);}for(const [label,file] of [['RGB','rgb/rgb_0001.png'],['mask','mask/mask_0001.png'],['报告','render-report.json']]){const a=document.createElement('a');a.textContent=label;a.href=r.folder+'/'+file;a.target='_blank';card.append(a);}get('grid').append(card);}get('prev').disabled=page===0;get('next').disabled=page>=pages-1;}
for(const id of ['kind','scene','background','search'])get(id).addEventListener('input',()=>{page=0;show();});get('prev').onclick=()=>{page--;show();};get('next').onclick=()=>{page++;show();};show();</script></html>'''
    path = root / 'index.html'
    path.write_text(html.replace('__DATA__', data), encoding='utf-8')
    return path
