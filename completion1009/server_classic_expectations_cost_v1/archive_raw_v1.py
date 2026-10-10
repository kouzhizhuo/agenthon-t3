"""Preserve actual final/partial hydration bytes at one bound artifact root.

Saved files only; no participant, subprocess, simulation, or native imports.
The main immutable wrapper completes first. Moving completed directories avoids
duplicating multi-GiB saved evidence and preserves all bytes on failure.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
HELPER = 'read_only/cost_saved_auditor_v1/archive_wrapper_draft_v1.py'
HELPER_SHA = '27fe5bb234cd5991e1a0c6c006779f987e72e48f7927d4b728514c62a1ebab63'
ACTIVE = '.github/workflows/t3-classic-expectations-cost-v1.yml'


def require(value, message):
    if not value: raise ValueError(message)


def ordinary(path):
    path=Path(path)
    require(path.is_absolute() and '..' not in path.parts
        and all(not p.is_symlink() for p in (path,*path.parents)), 'ordinary absolute artifact path')
    return path


def write(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')


def main():
    parser=argparse.ArgumentParser(allow_abbrev=False)
    for name in ('base','evaluation','logs','evidence','main-artifact','out','source-pins'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--run-id',type=int,required=True)
    parser.add_argument('--run-attempt',type=int,required=True)
    parser.add_argument('--head',required=True)
    args=parser.parse_args()
    require(args.run_id>0 and args.run_attempt>0 and re.fullmatch('[0-9a-f]{40}',args.head), 'actual run identity')
    sourcepins=ordinary(args.source_pins)
    require(sourcepins==HERE/'SOURCE_PINS.json', 'literal finalized source authority filename')
    data=(HERE/HELPER).read_bytes()
    require(len(data)==5931 and hashlib.sha256(data).hexdigest()==HELPER_SHA, 'unchanged reviewed saved wrapper source')
    freeze=json.loads(sourcepins.read_bytes())
    require(freeze.get('reviewed') is freeze.get('ready_for_linux') is True
        and freeze.get('active_workflow')==ACTIVE and freeze.get('runtime_changed') is False,
        'final whole source freeze')
    own=Path(__file__).read_bytes()
    require(freeze['files'].get('archive_raw_v1.py')=={'bytes':len(own),'sha256':hashlib.sha256(own).hexdigest()}, 'exact raw wrapper in executing freeze')
    require(freeze['files'].get(HELPER)=={'bytes':len(data),'sha256':HELPER_SHA}, 'same frozen snapshot helper')
    spec=importlib.util.spec_from_file_location('t3_raw_saved_snapshot_v1',HERE/HELPER)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    out=ordinary(args.out)
    sources={name:ordinary(getattr(args,name)) for name in ('base','evaluation','logs','evidence')}
    require(not out.exists() and out.parent.is_dir() and len(set(sources.values()))==4
        and all(p!=out and p not in out.parents and out not in p.parents for p in sources.values())
        and not any(a in b.parents for a in sources.values() for b in sources.values() if a!=b),
        'fresh distinct nonnested single-root raw archive')
    main_binding=ordinary(args.main_artifact)/'RUN_BINDING.json'
    main_pin=None
    if main_binding.is_file():
        main=json.loads(main_binding.read_bytes())
        require(main.get('run_id')==args.run_id and main.get('run_attempt')==args.run_attempt and main.get('head')==args.head
            and main.get('workflow')==ACTIVE and main.get('source_pins_sha256')==helper.pin(sourcepins)['sha256'], 'main/raw actual identity equal')
        main_pin=helper.pin(main_binding)
    out.mkdir()
    write(out/'RAW_RUN_BINDING.json',{'schema':'t3-cost-actual-raw-run-binding-v1','run_id':args.run_id,
        'run_attempt':args.run_attempt,'head':args.head,'workflow':ACTIVE,'artifact_name':'t3-cost-hydration-raw-partial-v1',
        'source_pins':helper.pin(sourcepins),'main_run_binding':main_pin,'partial_allowed':True,
        'participant_imported':False,'native_compiled':False,'market_executed_by_wrapper':False})
    moved=[]
    for name,source in sources.items():
        if not source.exists():
            moved.append({'name':name,'present':False});continue
        require(source.is_dir(), 'actual raw input directory')
        require(source.stat().st_dev==out.stat().st_dev, 'same filesystem atomic saved directory move')
        before=helper.snapshot(source)
        os.rename(source,out/name)
        require(helper.snapshot(out/name)==before, 'all moved actual files and directories byte equal')
        moved.append({'name':name,'present':True,'original_root':str(source),'files':len(before[0]),'directories':len(before[1])})
        write(out/('MOVE_'+name+'.json'),moved[-1])
    files,directories=helper.snapshot(out)
    write(out/'RAW_MANIFEST.json',{'schema':'t3-cost-complete-raw-manifest-v1','files':files,'directories':directories,
        'inputs':moved,'all_saved_bytes_retained':True,'missing_inputs_synthesized':False,'rankable':False,
        'performance_usable':False,'participant_imported':False,'market_executed_by_wrapper':False})
    require(len(files)+len(directories)+1<=helper.COUNT_CAP
        and sum(v['bytes'] for v in files.values())+helper.pin(out/'RAW_MANIFEST.json')['bytes']<=helper.TREE_CAP,
        'complete raw artifact finite final bounds')
    print(json.dumps({'saved_files':len(files),'present_inputs':[r['name'] for r in moved if r['present']],
        'main_binding_present':main_pin is not None,'ordinary_runs':0}))


if __name__=='__main__':
    try:
        main()
    except BaseException as error:
        # Rejected data remain unaccepted. The always fallback upload retains
        # moved and unmoved inputs independently, plus this bounded failure.
        try:
            import sys
            position=sys.argv.index('--logs')
            logs=ordinary(Path(sys.argv[position+1]))
            logs.mkdir(parents=True,exist_ok=True)
            failure=logs/'RAW_PACK_FAILURE.json'
            if not failure.exists():
                write(failure,{'schema':'t3-raw-pack-rejected-v1','failure_type':type(error).__name__,
                    'all_passed':False,'manifest_accepted':False,'fallback_upload_required':True,
                    'participant_imported':False,'market_executed_by_wrapper':False})
        except BaseException:
            pass
        raise RuntimeError('Raw pack rejected; preserve fallback bytes ('+type(error).__name__+')') from None
