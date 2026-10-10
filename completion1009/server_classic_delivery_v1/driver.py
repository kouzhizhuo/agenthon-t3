"""Actual Linux build, final default-entry checks and publication evidence."""
import argparse
import calendar
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import uuid

HERE=Path(__file__).resolve().parent
ENTRY=['/usr/local/bin/python','-B','/opt/classic-native-kernels-v1/delivery_entry.py']
FIVE=('t3-s001-price-time-priority','t3-as06-throughput-fast','t3-mp01-stp-newest-baseline','t3-ra01-fundamental-shock-mid','t3-gbatch-hetero-mix')
VOLATILE={'wall_clock_sec','events_per_sec','peak_memory_bytes','gpu_seconds'}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
def write(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():raise ValueError('fresh evidence required')
    p.write_text(json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n')
def inventory(root):
    return {p.relative_to(root).as_posix():{'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(root.rglob('*')) if p.is_file() and not any(x.startswith('._') or x in ('__pycache__','__MACOSX') for x in p.parts)}
def command(argv,out,seconds=600):
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('xb') as stream:p=subprocess.run(argv,stdout=stream,stderr=subprocess.STDOUT,timeout=seconds)
    write(out.with_suffix('.json'),{'command':argv,'returncode':p.returncode,'sha256':sha(out)})
    if p.returncode:raise ValueError('command failed: '+out.name)
def timestamp_ns(v):
    if not v.endswith('Z'):raise ValueError('UTC daemon timestamp required')
    b,d,f=v[:-1].partition('.')
    if d and (not f.isdigit() or len(f)>9):raise ValueError('invalid fraction')
    return calendar.timegm(datetime.strptime(b,'%Y-%m-%dT%H:%M:%S').timetuple())*10**9+(int(f.ljust(9,'0')) if d else 0)
def pair(a,b):
    ia,ib=inventory(a),inventory(b)
    if set(ia)!=set(ib):raise ValueError('output roster differs')
    for n in ia:
        if n.endswith('.parquet'):
            if (a/n).read_bytes()!=(b/n).read_bytes():raise ValueError('full Parquet differs')
        else:
            if {k:v for k,v in read(a/n).items() if k not in VOLATILE}!={k:v for k,v in read(b/n).items() if k not in VOLATILE}:raise ValueError('stable sidecar differs')
    return {'passed':True,'file_count':len(ia)}

def main():
    p=argparse.ArgumentParser();p.add_argument('stage',choices=('build','screen','publication','artifact'));p.add_argument('--payload',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--reference-root',type=Path,required=True);p.add_argument('--gate-kit',type=Path,required=True);p.add_argument('--artifact',type=Path);p.add_argument('--tag');args=p.parse_args()
    if platform.system()!='Linux' or platform.machine()!='x86_64':raise ValueError('real Linux only')
    args.payload=args.payload.resolve();args.evidence=args.evidence.resolve();args.reference_root=args.reference_root.resolve();args.gate_kit=args.gate_kit.resolve();args.evidence.mkdir(parents=True,exist_ok=True)
    args.docker='docker';args.timeout=300;args.log_cap_bytes=16*1024**2;args.gate_python=sys.executable;args.owner=uuid.uuid4().hex
    sys.path.insert(0,str(args.payload/'control'));sys.path.insert(0,str(args.payload/'host'))
    import controller as ctl
    import verify_linux as linux
    import verify_public as public
    import common
    plan=common.verify_payload(args.payload)
    if args.stage=='artifact':
        shutil.copytree(args.evidence,args.artifact/'evidence',ignore=shutil.ignore_patterns('anonymous-docker-config','registry-config'))
        shutil.copytree(HERE,args.artifact/'delivery-source',ignore=shutil.ignore_patterns('._*','__pycache__'))
        shutil.copytree(args.payload,args.artifact/'frozen-payload')
        write(args.artifact/'ARTIFACT.json',{'files':inventory(args.artifact),'rankable':False});return
    if args.stage=='build':
        original=args.evidence/'original';original.mkdir();args.evidence=original;ctl.build(args,plan);ready=read(original/'BUILD_READY.json')
        # Finish original controls in a fresh process; no mutation of reviewed controller.
        request=original/'controls-request.json';write(request,{'owner':args.owner});result=original/'controls-result.json'
        command([sys.executable,'-B',str(HERE/'worker.py'),'controls','--payload',str(args.payload),'--evidence',str(original),'--reference-root',str(args.reference_root),'--gate-kit',str(args.gate_kit),'--gate-python',sys.executable,'--request',str(request),'--result',str(result)],original/'controls-process.log',3900)
        args.evidence=original.parent
        context=args.evidence/'delivery-context';context.mkdir();base_tag='t3-classic-verified:'+uuid.uuid4().hex
        command(['docker','tag',ready['image_id'],base_tag],args.evidence/'base-tag.log')
        for n in ('delivery_entry.py','LICENSE-SUBMISSION'):shutil.copyfile(HERE/n,context/n)
        df=(HERE/'Dockerfile').read_text().replace('FROM TESTED_SCREEN AS tested_screen','FROM '+base_tag+' AS tested_screen');(context/'Dockerfile').write_text(df)
        tag='t3-classic-delivery:'+uuid.uuid4().hex
        command(['docker','build','--platform','linux/amd64','--pull=false','--progress=plain','-t',tag,str(context)],args.evidence/'delivery-build.log',900)
        meta=linux.image_metadata(args,tag,args.evidence/'delivery-metadata');image=meta['inspection']
        if image['Config'].get('Entrypoint')!=ENTRY or image['Config'].get('Volumes') or image['Config'].get('User')!='65534:65534' or image['Config']['Labels'].get('qfbench2.interface_version')!='2.0':raise ValueError('final image contract mismatch')
        # Extraction never starts this container; inspect ownership and cleanup.
        name='t3-delivery-source-'+uuid.uuid4().hex;dc=linux.DockerCommands('docker',args.evidence/'delivery-copy-commands',args.log_cap_bytes);copied=args.evidence/'delivery-installed';made=False
        try:
            made=dc.call(['create','--name',name,'--label',linux.OWNER_LABEL+'='+args.owner,'--pull','never',meta['id']],'create')['succeeded']
            if not made:raise ValueError('copy container creation failed')
            inf,_=dc.inspect(name,cleanup=True);linux.require_owned(inf,name,args.owner,meta['id'])
            if not dc.call(['cp',name+':/opt/classic-native-kernels-v1/completion1009/candidates/classic_native_kernels_v1',str(copied)],'copy',90)['succeeded']:raise ValueError('source copy failed')
        finally:
            clean=linux.settle_container(dc,name,args.owner,meta['id'],creation_uncertain=True);write(args.evidence/'DELIVERY_COPY.json',{'commands':dc.rows,'cleanup':clean})
        if not clean['settled'] or not clean['removed'] or not clean['final_absent'] or clean['errors']:raise ValueError('source cleanup failure')
        installed_public={}
        name='t3-delivery-public-'+uuid.uuid4().hex;dc=linux.DockerCommands('docker',args.evidence/'delivery-public-commands',args.log_cap_bytes)
        try:
            if not dc.call(['create','--name',name,'--label',linux.OWNER_LABEL+'='+args.owner,'--pull','never',meta['id']],'create')['succeeded']:raise ValueError('public-file copy container failed')
            inf,_=dc.inspect(name,cleanup=True);linux.require_owned(inf,name,args.owner,meta['id'])
            for n,remote in (('delivery_entry.py','/opt/classic-native-kernels-v1/delivery_entry.py'),('LICENSE-SUBMISSION','/licenses/LICENSE-SUBMISSION')):
                target=args.evidence/('installed-'+n)
                if not dc.call(['cp',name+':'+remote,str(target)],n,90)['succeeded'] or target.read_bytes()!=(HERE/n).read_bytes():raise ValueError('installed public file differs: '+n)
                installed_public[n]=sha(target)
        finally:
            clean=linux.settle_container(dc,name,args.owner,meta['id'],creation_uncertain=True);write(args.evidence/'DELIVERY_PUBLIC_COPY.json',{'commands':dc.rows,'cleanup':clean})
        if not clean['settled'] or not clean['removed'] or not clean['final_absent'] or clean['errors']:raise ValueError('public source cleanup failure')
        previous=original/'installed'/common.CANDIDATE
        if inventory(copied)!=inventory(previous):raise ValueError('final source/native bytes differ from tested image')
        write(args.evidence/'DELIVERY_READY.json',{'image_id':meta['id'],'metadata':meta,'all_source_build_native_bytes_equal':True,'original_full_controls_passed':True,'copied_files':inventory(copied),'installed_public_files':installed_public,'entry_sha256':sha(HERE/'delivery_entry.py'),'licence_sha256':sha(HERE/'LICENSE-SUBMISSION'),'official_submission':False});return
    ready=read(args.evidence/'DELIVERY_READY.json');image=ready['image_id']
    if args.stage=='publication':
        if not read(args.evidence/'SUMMARY.json')['all_passed']:raise ValueError('delivery tests must pass before publication')
        # Workflow handles authenticated push; this stage verifies public pull only.
        prior=os.environ.get('DOCKER_CONFIG');anon=args.evidence/'anonymous-published-config';anon.mkdir();os.environ['DOCKER_CONFIG']=str(anon)
        try:
            command(['docker','pull','--platform','linux/amd64',args.tag],args.evidence/'anonymous-published-pull.log',900)
            meta=linux.image_metadata(args,args.tag,args.evidence/'published-metadata')
        finally:
            if prior is None:os.environ.pop('DOCKER_CONFIG',None)
            else:os.environ['DOCKER_CONFIG']=prior
        if meta['id']!=image:raise ValueError('published image bytes differ')
        refs=[r for r in meta['inspection']['RepoDigests'] if r.startswith('ghcr.io/kouzhizhuo/agenthon-t3@sha256:')]
        if len(set(refs))!=1:raise ValueError('one immutable published digest required')
        write(args.evidence/'PUBLICATION.json',{'image':refs[0],'digest':refs[0].split('@')[1],'image_id':image,'anonymous_pull_passed':True,'tested_image_id_equal':True,'official_submission':False});return
    class Strict(ctl.StrictCommands.__bases__[0]):
        def call(self,arguments,label,seconds=30,cleanup=False):
            if arguments and arguments[0]=='create':arguments=[arguments[0],'--env','PYTHONHASHSEED=0','--ulimit','nproc=256:256','--ulimit','fsize=268435456:268435456',*arguments[1:]]
            return super().call(arguments,label,seconds,cleanup)
        def inspect(self,name,cleanup=False,seconds=30):
            inf,rec=super().inspect(name,cleanup,seconds)
            if inf is not None and not cleanup:
                if inf['Config']['Entrypoint']!=ENTRY or '--mode' in inf['Config']['Cmd']:raise ValueError('official default entry differs')
                environment=dict(v.split('=',1) for v in inf['Config'].get('Env',[]) if '=' in v)
                expected={'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1','PYTHONHASHSEED':'0','PYTHONDONTWRITEBYTECODE':'1'}
                if any(environment.get(k)!=v for k,v in expected.items()):raise ValueError('final environment mismatch')
                binds=[m for m in inf['Mounts'] if m['Type']=='bind']
                if len(binds)!=2 or {m['Destination']:m['RW'] for m in binds}!={'/input':False,'/output':True}:raise ValueError('final bind envelope mismatch')
                limits={r['Name']:(r['Soft'],r['Hard']) for r in inf['HostConfig']['Ulimits']}
                if limits!={'nofile':(1024,1024),'nproc':(256,256),'fsize':(268435456,268435456)}:raise ValueError('limits mismatch')
            return inf,rec
    linux.DockerCommands=Strict
    roster=public.collect_plan(args.reference_root,None);items={x['unit']:x for x in roster['units']}
    if len(items)!=71 or roster['reference_frame_count']!=190:raise ValueError('full71 roster required')
    write(args.evidence/'REFERENCE_PLAN.json',roster);rows=[];pairs=[];first={}
    schedule=[(0,u) for u in sorted(items)]+[(r,u) for r in range(1,5) for u in FIVE]
    failure=None
    try:
        for i,(r,u) in enumerate(schedule):
            folder=args.evidence/'final-runs'/str(r)/u
            ex,out=linux.run_container(args,image,'original',items[u],folder,args.owner,str(i))
            if not ex['succeeded']:raise ValueError('final default entry execution failed: '+u)
            ref=public.verify_outputs(args.reference_root/u,out,items[u]);g=linux.gate(args,args.reference_root/u,out,folder)
            if not ref['passed'] or not g['admissible']:raise ValueError('official reference/gate rejected '+u)
            n=ref['actual_events'];t=(timestamp_ns(ex['state']['FinishedAt'])-timestamp_ns(ex['state']['StartedAt']))/10**9
            if t<=0:raise ValueError('positive daemon runtime required')
            previous=first.setdefault(u,out);pairs.append({'unit':u,'repeat':r,**pair(out,previous)})
            row={'unit':u,'repeat':r,'actual_events':n,'settled_container_runtime_sec':t,'EPS':n/t,'execution':ex,'output':str(out),'reference_checks':ref,'developer_verifier':g,'passed':True}
            rows.append(row);write(folder/'RUN_RESULT.json',row);print(i,u,r,'PASS',flush=True)
    except BaseException as e:failure={'type':type(e).__name__,'message':str(e)}
    write(args.evidence/'RAW_RESULTS.json',rows);write(args.evidence/'PAIRS.json',pairs)
    gates=sum(v['passed'] is True for row in rows for v in row['developer_verifier']['verdict']['gate_results'].values())
    unchanged=all(public.sha256(args.reference_root/x['unit']/name)==dig for x in roster['units'] for mapping in (x['input_sha256'],x['reference_sha256']) for name,dig in mapping.items())
    summary={'all_passed':failure is None and len(rows)==91 and gates==364 and unchanged,'failure':failure,'runs':len(rows),'gates':gates,'full71':len(first)==71,'public_references_unchanged':unchanged,'repeat_units':{u:{'repeats':5,'warmup_discarded':1,'median_EPS':statistics.median(row['EPS'] for row in rows if row['unit']==u and row['repeat']>0)} for u in FIVE if len([row for row in rows if row['unit']==u])==5},'rankable':False,'official_submission':False}
    write(args.evidence/'SUMMARY.json',summary)
    if not summary['all_passed']:raise ValueError('final delivery tests failed')
if __name__=='__main__':main()
