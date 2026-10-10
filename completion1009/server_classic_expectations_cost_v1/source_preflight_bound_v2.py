"""Inert actual-base binding check. No participant/driver/helper imports."""
import ast
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
OLD=HERE.parent/'host_draft_v1'


def pin(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024**2),b''):digest.update(chunk)
    return {'bytes':Path(path).stat().st_size,'sha256':digest.hexdigest()}


def read(path):return json.loads(Path(path).read_bytes())


def inv(root):
    return {p.relative_to(root).as_posix():pin(p) for p in sorted(Path(root).rglob('*')) if p.is_file()
        and not any(s.startswith('._') or s in ('__pycache__','__MACOSX') for s in p.parts)}


def main():
    doc=read(HERE/'ACTUAL_BASE_AUTHORITY_v2.json');binding=read(HERE/'overlay/IMAGE_BINDING.json')
    cases=[]
    def check(name,value):
        cases.append({'case':name,'passed':bool(value)})
    copied=read(HERE/'COPIED_REVIEWED_HOST_SOURCE_v1.json')['files']
    check('all31originalcopiedfiles_exceptnewDockerfile',all(pin(HERE/n)==pin(OLD/n)==p for n,p in copied.items() if n!='Dockerfile'))
    check('oldrevieweddriver_unchanged',pin(HERE/'driver.py')==pin(OLD/'driver.py')=={'bytes':46282,'sha256':'c9fb7fa76ac017715c386b2f3d452e9df22acdcf75d7853637a7824d538208cf'})
    for field in ('artifact_zip','saved_audit','anonymous_registry','remote_source_readback','baseline_reference_plan'):
        row=doc[field];check('actualbound_'+field,pin(Path(row['path']))=={k:row[k] for k in ('bytes','sha256')})
    audit=read(doc['saved_audit']['path']);check('actualindependentfullv2passing',audit['all_passed'] is audit['all_execution_checks_passed'] is audit['publication_passed'] is True and not audit['failures'] and not audit['pending'])
    check('exactbase_publicdigest',binding['actual_final_public_digest']==doc['public_digest']==audit['authority']['public_image'])
    root=Path(doc['artifact_root'])/'evidence';meta=read(root/'published-metadata/IMAGE.json')
    check('actualbaseimageid',meta['Id']==doc['base_image_id']==binding['actual_final_image_id'])
    mapping={'native':'installed','harness':'installed-harness','licenses':'installed-licenses'}
    check('fullbase_beforeafterinventories',binding['base_source_inventory']=={k:inv(root/n) for k,n in mapping.items()}=={k:inv(root/(n+'-after')) for k,n in mapping.items()})
    check('botharms_fullactualsource',binding['candidate_source_files']=={n:inv(root/'installed/completion1009/candidates'/n) for n in ('classic_native_kernels_v1','classic_build_expectations_v1')})
    check('exactentry_frozenunmodified',pin(HERE/'overlay/cost_entry_draft_v1.py')==pin(HERE.parent/'cost_entry_draft_v1.py'))
    check('oneFROM_oneCOPYonly',(HERE/'Dockerfile').read_text()=='FROM '+doc['public_digest']+'\nCOPY --chown=0:0 --chmod=0444 overlay/ /opt/t3-classic-structural-v2/cost-diagnostic-v1/\n')
    check('exacttwo_overlayfiles',set(inv(HERE/'overlay'))=={'cost_entry_draft_v1.py','IMAGE_BINDING.json'})
    status=read(HERE/'STATUS.json');check('noLinux_dispatch_freeze',status['ready_for_linux'] is status['dispatch_allowed'] is status['source_frozen'] is False and status['remote_head'] is status['run_id'] is status['derived_diagnostic_image_id'] is None)
    for name in ('driver.py','worker.py','parser.py'):ast.parse((HERE/name).read_bytes())
    report={'schema':'t3-cost-bound-source-inert-preflight-v2','cases':cases,'case_count':len(cases),
        'all_source_checks_passed':all(c['passed'] for c in cases),'all_passed':False,'ready_for_linux':False,'source_frozen':False,
        'actual_base_binding_complete':True,'remote_binding_generated':False,'Docker_executed':False,'participant_imported':False,
        'native_compiled':False,'market_executed':False,'driver_executed':False,'source':{'base_authority':pin(HERE/'ACTUAL_BASE_AUTHORITY_v2.json'),
            'binding':pin(HERE/'overlay/IMAGE_BINDING.json'),'Dockerfile':pin(HERE/'Dockerfile')}}
    (HERE/'SOURCE_PREFLIGHT_BOUND_v2.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'all_source_checks_passed':report['all_source_checks_passed'],'case_count':len(cases),'ready_for_linux':False}))
    return 0 if report['all_source_checks_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
