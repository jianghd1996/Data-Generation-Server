#!/usr/bin/env python3
"""Find/download free BlenderKit scene candidates for DGS, without the GUI add-on.
Default: up to 10 distinct scenes, <=150 MiB each, authored in Blender <=4.5.
Anonymous downloads are tried first. If required, set BLENDERKIT_API_KEY locally.
API follows the official Blendkit client: search -> downloadUrl + scene_uuid -> filePath.
Source: https://github.com/BlenderKit/bk_client/blob/main/client/download.go
This is a direct client integration, not an official BlenderKit command-line tool.
"""
import argparse
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from data_generation_server.assets import digest, write_json
API = 'https://www.blenderkit.com/api/v1/'
HOSTS = {'www.blenderkit.com','blenderkit.com','www.blendkit.com','blendkit.com'}
CHECK = '''
import bpy,sys
source,destination=sys.argv[sys.argv.index('--')+1:]
bpy.ops.wm.open_mainfile(filepath=source,load_ui=False)
if not any(o.type=='MESH' for o in bpy.context.scene.objects):
    raise RuntimeError('Active scene has no meshes')
missing=[]
for image in bpy.data.images:
    if image.source=='FILE' and not image.packed_file and not image.packed_files:
        import os
        if not os.path.isfile(bpy.path.abspath(image.filepath)):
            missing.append(image.filepath)
for library in bpy.data.libraries:
    import os
    if not os.path.isfile(bpy.path.abspath(library.filepath)):
        missing.append(library.filepath)
if missing: raise RuntimeError('Missing dependencies: '+str(missing))
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=destination)
'''


def api_url(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in HOSTS or not parsed.path.startswith('/api/v1/'):
        raise ValueError('Unexpected API endpoint')
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def request_json(url,context):
    api_url(url)
    headers={'User-Agent':'DGS-BlenderKit-Scene-Downloader/1.0','Accept':'application/json'}
    token=os.environ.get('BLENDERKIT_API_KEY','').strip()
    if token: headers['Authorization']='Bearer '+token
    opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=context))
    for attempt in range(3):
        try:
            with opener.open(urllib.request.Request(url,headers=headers),timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (429,500,502,503,504) and attempt<2:
                print('[retry] HTTP',exc.code,flush=True);time.sleep(2**attempt);continue
            raise RuntimeError('API HTTP %s; 401/403 may require BLENDERKIT_API_KEY; no paid assets are purchased'%exc.code) from None
        except urllib.error.URLError as exc:
            if attempt==2:
                raise RuntimeError('API connection failed: '+type(exc.reason).__name__) from None
            time.sleep(2**attempt)


def version(text):
    match=re.match(r'^(\d+)\.(\d+)',str(text))
    return tuple(map(int,match.groups())) if match else (999,999)


def choose_file(asset,maximum,blender_version):
    if asset.get('assetType')!='scene' or asset.get('isFree') is not True:
        return None
    if version(asset.get('sourceAppVersion'))>version(blender_version):
        return None
    # Original scene blend only: reduced model variants may omit scene-level data.
    files=[f for f in asset.get('files',[]) if f.get('fileType')=='blend'
           and 0<int(f.get('fileUploadSize') or 0)<=maximum]
    return min(files,key=lambda f:int(f['fileUploadSize'])) if files else None


class DownloadHTTPError(RuntimeError):
    def __init__(self,status,host):
        self.status=status
        super().__init__('Asset download HTTP %s from %s; Blender validation not started' % (status,host))


def stream(url,target,maximum,context,expected):
    if urllib.parse.urlsplit(url).scheme!='https': raise ValueError('Non-HTTPS asset URL')
    partial=target.with_suffix('.part')
    try:
        # Never send account headers to the asset CDN.
        request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; DGS-Scene-Downloader/1.0)','Accept':'*/*'})
        try:
            response=urllib.request.urlopen(request,context=context,timeout=120)
        except urllib.error.HTTPError as exc:
            raise DownloadHTTPError(exc.code,urllib.parse.urlsplit(exc.url).hostname) from None
        except urllib.error.URLError as exc:
            raise RuntimeError('Asset connection failed: '+type(exc.reason).__name__) from None
        with response,partial.open('wb') as output:
            length=int(response.headers.get('Content-Length') or 0)
            if length>maximum: raise ValueError('Server file exceeds size limit')
            total,last=0,time.monotonic()
            while True:
                chunk=response.read(1024*1024)
                if not chunk: break
                total+=len(chunk)
                if total>maximum: raise ValueError('Stream exceeds size limit')
                output.write(chunk)
                if time.monotonic()-last>=2:
                    print('[download] %.1f / %.1f MiB'%(total/1048576,expected/1048576),flush=True)
                    last=time.monotonic()
            if total==0 or (length and total!=length) or total!=expected:
                raise ValueError('File size differs from API/response; retry after refreshing metadata')
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def download(asset,file,args,context):
    uid=str(uuid.UUID(asset['assetBaseId']))
    folder=args.root/'scenes/direct'/('blenderkit_'+uid)
    registration=folder/'scene-registration.json'
    if registration.exists():
        old=json.loads(registration.read_text())
        path=Path(old['path'])
        if path.is_file() and old.get('blend_sha256')==digest(path,'sha256'):
            print('[skip]',asset.get('displayName'),flush=True);return 'skipped'
    print('[scene]',uid,asset.get('displayName'),'%.1f MiB'%(file['fileUploadSize']/1048576),flush=True)
    endpoint=api_url(file['downloadUrl'])
    parts=urllib.parse.urlsplit(endpoint)
    query=urllib.parse.parse_qsl(parts.query)+[('scene_uuid',str(uuid.uuid4()))]
    endpoint=urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
    signed=request_json(endpoint,context)
    if not signed.get('filePath'): raise ValueError('API did not authorize a file download')
    folder.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bk-scene-',dir=folder) as temp:
        temp=Path(temp)
        original=temp/'source.blend';packed=temp/'environment.blend'
        for attempt in range(3):
            try:
                stream(signed['filePath'],original,args.max_download_mib*1048576,context,int(file['fileUploadSize']))
                break
            except DownloadHTTPError as exc:
                if attempt==2 or exc.status not in (403,408,429,500,502,503,504): raise
                print('[retry] asset HTTP',exc.status,'; refreshing download authorization',flush=True)
                time.sleep(2**attempt)
                signed=request_json(endpoint,context)
                if not signed.get('filePath'): raise ValueError('API did not authorize retry')
        with (folder/'validation.log').open('w') as log:
            subprocess.run([args.blender,'--background','--factory-startup','--disable-autoexec',
                '--python-exit-code','1','--python-expr',CHECK,'--',str(original),str(packed)],
                stdout=log,stderr=subprocess.STDOUT,check=True)
        packed.replace(folder/'environment.blend')
    source={'provider':'blenderkit','id':asset['id'],'assetBaseId':uid,'name':asset.get('displayName'),
        'author':asset.get('author'),'license':asset.get('license'),'sourceAppVersion':asset.get('sourceAppVersion'),
        'source_url':'https://www.blenderkit.com/asset-gallery-detail/'+uid+'/',
        'download_size':file['fileUploadSize']}
    write_json(folder/'scene-source.json',source)
    write_json(registration,{'id':'blenderkit_'+uid,'identity':'blenderkit_'+uid,
        'path':str(folder/'environment.blend'),'blend_sha256':digest(folder/'environment.blend','sha256'),
        'source_url':source['source_url'],'license':source['license'],'author':source['author'],
        'position':[0,0,0],'enabled':True,'review':'pending',
        'notes':'Validated load and file dependencies only. Preview scale, placement, lighting and full camera trajectory; current renderer replaces world with HDRI.'})
    print('[ready]',folder/'environment.blend',flush=True)
    return 'ok'


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('dataset'))
    p.add_argument('--blender',default='blender')
    p.add_argument('--limit',type=int,default=10,help='Target success count, including already downloaded candidates')
    p.add_argument('--max-download-mib',type=int,default=150)
    p.add_argument('--blender-version',default='4.5.3')
    p.add_argument('--pages',type=int,default=5,help='Maximum search pages, 24 results each')
    p.add_argument('--max-failures',type=int,default=3,help='Stop after this many consecutive failures')
    p.add_argument('--query',default='',help='Optional scene keywords')
    p.add_argument('--list-only',action='store_true')
    p.add_argument('--insecure',action='store_true')
    p.add_argument('--ca-bundle')
    args=p.parse_args(argv)
    if min(args.limit,args.max_download_mib,args.pages,args.max_failures)<1: p.error('Limits must be positive')
    args.root=args.root.expanduser().resolve();args.root.mkdir(parents=True,exist_ok=True)
    context=ssl.create_default_context(cafile=args.ca_bundle)
    if args.insecure:
        print('WARNING: TLS certificate verification disabled.',flush=True)
        context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
    query='asset_type:scene is_free:true'+(' '+args.query if args.query else '')
    url=API+'search/?'+urllib.parse.urlencode({'query':query,'dict_parameters':1,'page_size':24,'blender_version':args.blender_version})
    seen,results,success=set(),[],0
    consecutive_failures=0
    for page in range(args.pages):
        print('[search] page',page+1,flush=True)
        data=request_json(url,context)
        for asset in data.get('results',[]):
            uid=asset.get('assetBaseId')
            if not uid or uid in seen: continue
            seen.add(uid)
            file=choose_file(asset,args.max_download_mib*1048576,args.blender_version)
            if not file: continue
            if args.list_only:
                print('[candidate]',uid,asset.get('displayName'),asset.get('sourceAppVersion'),round(file['fileUploadSize']/1048576,1),'MiB',flush=True)
                success+=1
            else:
                try:
                    status=download(asset,file,args,context)
                    results.append({'id':uid,'name':asset.get('displayName'),'status':status});success+=1
                    consecutive_failures=0
                except Exception as exc:
                    message=str(exc) if isinstance(exc,(ValueError,RuntimeError)) else type(exc).__name__
                    print('[failed]',uid,message,'see validation.log if present',flush=True)
                    results.append({'id':uid,'status':'failed','error':message})
                    consecutive_failures+=1
                write_json(args.root/'blenderkit-scenes-report.json',{'results':results,'success':success,'target':args.limit})
            if success>=args.limit or consecutive_failures>=args.max_failures: break
        if consecutive_failures>=args.max_failures:
            print('[stop] Repeated failures; inspect reported HTTP status before retrying.',flush=True)
            break
        if success>=args.limit or not data.get('next'): break
        url=api_url(data['next'])
    print('[summary]',success,'/',args.limit,'candidates' if args.list_only else 'downloaded/verified scenes',flush=True)
    print('Run dgs-dataset inventory; regenerate preview plans before batch rendering.')
    return int(success<args.limit)


if __name__=='__main__': raise SystemExit(main())
