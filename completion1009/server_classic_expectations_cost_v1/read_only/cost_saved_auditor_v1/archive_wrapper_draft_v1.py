"""Proposed saved-only archive wrapper; no driver/process/Docker execution.

Future workflow runs it after the actual driver. Complete existing bytes are
copied; missing markets and successful summaries are never synthesized.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import os

FILE_CAP=4*1024**3
TREE_CAP=64*1024**3
COUNT_CAP=40000


def require(ok,message):
    if not ok:raise ValueError(message)


def ordinary_absolute(path):
    path=Path(path)
    require(path.is_absolute() and '..' not in path.parts and all(not p.is_symlink() for p in (path,*path.parents)),
        'absolute nonsymlink ancestors required')
    return path


def pin(path):
    path=ordinary_absolute(path)
    require(path.is_file() and path.stat().st_size<=FILE_CAP,'finiteordinaryfile required')
    digest=hashlib.sha256();count=0
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024**2),b''):
            count+=len(chunk);require(count<=FILE_CAP,"streamedfilehardbound")
            digest.update(chunk)
    require(count==path.stat().st_size,"sourcefilestablewhilehashed")
    return {'bytes':path.stat().st_size,'sha256':digest.hexdigest()}


def snapshot(root):
    root=ordinary_absolute(root);require(root.is_dir(),'actualevidenceroot')
    result={};directories=[];total=0;members=0
    def walk(folder):
        nonlocal total,members
        entries=[]
        with os.scandir(folder) as scan:
            for entry in scan:
                members+=1;require(members<=COUNT_CAP-2,'finitefiles+dirs40000hardbound')
                entries.append(entry)
        for entry in sorted(entries,key=lambda e:e.name):
            path=ordinary_absolute(Path(entry.path));relative=path.relative_to(root)
            require(not any(s.startswith('._') or s in ('__MACOSX','__pycache__') for s in relative.parts)
                and ':' not in relative.as_posix() and '\\' not in relative.as_posix(),'ordinaryactualLinuxartifactonly')
            if entry.is_dir(follow_symlinks=False):
                directories.append(relative.as_posix());walk(path);continue
            require(entry.is_file(follow_symlinks=False),'regularactualfilesonly')
            result[relative.as_posix()]=pin(path);total+=result[relative.as_posix()]['bytes']
            require(total<=TREE_CAP,'finitewholeartifact bytecap')
    walk(root)
    require(result,'nonemptyactualevidence')
    return result,sorted(directories)


def inventory(root):
    return snapshot(root)[0]


def main():
    p=argparse.ArgumentParser(allow_abbrev=False)
    p.add_argument('--evidence',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--run-id',type=int,required=True);p.add_argument('--run-attempt',type=int,required=True)
    p.add_argument('--head',required=True);p.add_argument('--workflow',required=True);p.add_argument('--source-pins',type=Path,required=True)
    a=p.parse_args()
    evidence,out,sourcepins=map(ordinary_absolute,(a.evidence,a.out,a.source_pins))
    require(evidence.is_dir() and not out.exists() and evidence!=out and evidence not in out.parents and out not in evidence.parents,
        'distinctfresharchive outsideactualevidence')
    require(a.run_id>0 and a.run_attempt>0 and re.fullmatch('[0-9a-f]{40}',a.head)
        and re.fullmatch(r'\.github/workflows/t3-[a-z0-9-]+\.yml',a.workflow),'actualworkflow/run identity')
    carried=evidence/'authority-inputs/SOURCE_PINS.json'
    require(pin(carried)==pin(sourcepins) and carried.read_bytes()==sourcepins.read_bytes(),'actualcarriedsourcepins exactcompletebytes authority')
    pins=json.loads(sourcepins.read_bytes())
    require(pins.get('schema')=='t3-cost-host-source-pins-v1' and pins.get('reviewed') is pins.get('ready_for_linux') is True
        and pins.get('runtime_changed') is False and pins.get('active_workflow')==a.workflow,'finalreviewedactualsourcefreeze')
    before,directories=snapshot(evidence)
    require(inventory(evidence/'source-harness')==pins['files'],'entireactualexecuting sourceharness matchescarriedfreeze')
    out.mkdir(parents=True)
    copied=out/'evidence';copied.mkdir()
    for name in directories:(copied/name).mkdir(parents=True,exist_ok=True)
    for name,wanted in before.items():
        source,target=evidence/name,copied/name
        target.parent.mkdir(parents=True,exist_ok=True)
        digest=hashlib.sha256();count=0
        with source.open('rb') as left,target.open('xb') as right:
            for chunk in iter(lambda:left.read(1024**2),b''):
                count+=len(chunk);require(count<=wanted['bytes']<=FILE_CAP,'boundedcopy exactoriginalfile size')
                digest.update(chunk);right.write(chunk)
        require({'bytes':count,'sha256':digest.hexdigest()}==wanted,'fullcopy bytesmatchfrozenactualsource')
    require(snapshot(out/'evidence')==(before,directories)==snapshot(evidence),'fullactualcopy/sourcebyteanddirectoryequal')
    run={'schema':'t3-cost-actual-run-binding-v1','run_id':a.run_id,'run_attempt':a.run_attempt,'head':a.head,
        'workflow':a.workflow,'source_pins_sha256':pin(sourcepins)['sha256']}
    (out/'RUN_BINDING.json').write_text(json.dumps(run,sort_keys=True,indent=2)+'\n')
    files=inventory(out)
    report={'schema':'t3-cost-complete-artifact-manifest-v1','files':files,'rankable':False,
        'all_actual_output_bytes_retained':True,'missing_results_synthesized':False,'market_executed_by_wrapper':False,
        'driver_summary_present':(out/'evidence/SUMMARY.json').is_file()}
    (out/'ARTIFACT.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    require(len(files)+1<=COUNT_CAP and sum(v['bytes'] for v in files.values())+pin(out/'ARTIFACT.json')['bytes']<=TREE_CAP,
        'completearchive finalfinitebound')
    print(json.dumps({'actual_files':len(files),'driver_summary_present':report['driver_summary_present']}))


if __name__=='__main__':main()
