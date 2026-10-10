"""Finite inert hydration contracts/redirect/ZIP/tar controls; no network."""
import ast
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent


def main():
    source=HERE/'hydrate_base_draft_v1.py';ast.parse(source.read_bytes())
    spec=importlib.util.spec_from_file_location('inert_hydration_source',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    cases=[]
    def check(name,call,reject=False):
        try:call()
        except (ValueError,OSError,RuntimeError):assert reject,name
        else:assert not reject,name
        cases.append({'case':name,'passed':True,'expected_reject':reject})
    for url in ['http://api.github.com/x','https://user:password@api.github.com/x','https://api.github.com:444/x','https://api.github.com/x#secret']:
        check('unsafe_url_'+str(len(cases)),lambda url=url:module.url_allowed(url),True)
    check('HTTPS_expected_API',lambda:module.url_allowed('https://api.github.com/repos/kouzhizhuo/agenthon-t3/actions/artifacts/11678266765'))
    redirect=module.ArtifactRedirect()
    request=urllib.request.Request(module.API+'/zip',headers={'Authorization':'Bearer synthetic-notcredential'})
    target=redirect.redirect_request(request,None,302,'Found',{},'https://productionresultssa6.blob.core.windows.net/test?synthetic=x')
    assert not any(k.lower()=='authorization' for k in target.headers)
    cases.append({'case':'crosshostAuthorizationstripped','passed':True,'expected_reject':False})
    check('unknown_redirect_host',lambda:redirect.redirect_request(request,None,302,'Found',{},'https://unrelated.example/test'),True)
    check('raw_source_redirect_refused',lambda:module.NoRedirect().redirect_request(request,None,302,'Found',{},'https://raw.githubusercontent.com/other'),True)
    for name,mode in [('ordinary/file',stat.S_IFREG),('ordinary/',stat.S_IFDIR)]:
        item=zipfile.ZipInfo(name);item.external_attr=(mode|0o644)<<16
        check('safe_zip_'+name,lambda item=item:module.safe_zip_member(item))
    for name,mode in [('../escape',stat.S_IFREG),('/escape',stat.S_IFREG),('a//b',stat.S_IFREG),('a/./b',stat.S_IFREG),('a\\b',stat.S_IFREG),
        ('a:b',stat.S_IFREG),('._item',stat.S_IFREG),('__MACOSX/a',stat.S_IFREG),('item',stat.S_IFLNK),('item',stat.S_IFIFO),('item',stat.S_IFREG|stat.S_ISUID)]:
        item=zipfile.ZipInfo(name);item.external_attr=(mode|0o644)<<16
        check('bad_zip_'+str(len(cases)),lambda item=item:module.safe_zip_member(item),True)
    item=zipfile.ZipInfo('empty/');item.file_size=1
    check('nonempty_zip_directory',lambda:module.safe_zip_member(item),True)
    temp=Path(tempfile.mkdtemp(prefix='t3-hydration-inert-')).resolve()
    try:
        manifest={'files':{'source.py':{'bytes':4,'sha256':hashlib.sha256(b'data').hexdigest()}}}
        archive=temp/'safe.tar.xz'
        with tarfile.open(archive,'w:xz') as tar:
            for name,data in [('source.py',b'data'),('STRUCTURAL_MANIFEST.json',(json.dumps(manifest)+'\n').encode())]:
                row=tarfile.TarInfo(name);row.size=len(data);tar.addfile(row,io.BytesIO(data))
        check('full_pin_before_materialization',lambda:module.materialize(archive,temp/'safe-output',1,module.pin(archive)))
        check('wrong_archive_pin',lambda:module.materialize(archive,temp/'wrong-output',1,{'bytes':archive.stat().st_size,'sha256':'0'*64}),True)
        for name,kind in [('unsafe/../file',tarfile.REGTYPE),('__MACOSX/file',tarfile.REGTYPE),('link',tarfile.SYMTYPE)]:
            path=temp/('bad-'+str(len(cases))+'.tar.xz')
            with tarfile.open(path,'w:xz') as tar:
                row=tarfile.TarInfo(name);row.type=kind;row.size=0;tar.addfile(row,io.BytesIO(b''))
            check('unsafe_tar_'+str(len(cases)),lambda path=path:module.materialize(path,temp/('out-'+path.stem),0,module.pin(path)),True)
        # Construct only inert exact source closure; never run either CLI or manager.
        fake=temp/'freeze-source';fake.mkdir();shutil.copytree(HERE/'bound_data',fake/'bound_data',ignore=shutil.ignore_patterns('._*'))
        executing=['hydrate_base_draft_v1.py','saved_process_copy_v1.py','run_fetch_evaluation_draft_v1.py',
            'validate_reference_hydration_draft_v1.py','validate_evaluator_hydration_v1.py','t3-cost-diagnostic-hydration-draft-v1.yml']
        for name in executing:shutil.copyfile(HERE/name,fake/name)
        files={p.relative_to(fake).as_posix():module.pin(p) for p in fake.rglob('*') if p.is_file()}
        frozen={'files':files,'reviewed':True,'ready_for_linux':True}
        old_here=module.HERE;module.HERE=fake
        def fixture(value):
            (fake/'HYDRATION_SOURCE_FREEZE.json').write_text(json.dumps(value)+'\n')
            return module.validate_source_freeze()
        check('same_closure_positive_all_source_and8data',lambda:fixture(frozen))
        check('empty_reviewed_freeze_reject',lambda:fixture({'files':{},'reviewed':True,'ready_for_linux':True}),True)
        for missing in ['saved_process_copy_v1.py','validate_evaluator_hydration_v1.py','bound_data/V2_EVALUATOR_FREEZE.txt']:
            altered=dict(files);altered.pop(missing)
            check('missing_freeze_member_'+missing,lambda altered=altered:fixture(dict(frozen,files=altered)),True)
        altered=dict(files);altered['../escape']={'bytes':0,'sha256':'0'*64}
        check('freeze_path_traversal_reject',lambda:fixture(dict(frozen,files=altered)),True)
        altered=dict(files);altered['saved_process_copy_v1.py']=dict(files['saved_process_copy_v1.py'],sha256='0'*64)
        check('manager_full_bytes_mismatch_reject',lambda:fixture(dict(frozen,files=altered)),True)
        module.HERE=old_here
        eval_spec=importlib.util.spec_from_file_location('inert_evaluator_validator',HERE/'validate_evaluator_hydration_v1.py')
        evaluator=importlib.util.module_from_spec(eval_spec);eval_spec.loader.exec_module(evaluator)
        original_bytes=(HERE/'bound_data/V2_EVALUATOR_FREEZE.txt').read_bytes()
        oldpaths={n:Path(evaluator.OLD_ROOT)/r for n,r in evaluator.LOCAL.items()}
        baseline=evaluator.parse(original_bytes,oldpaths)
        assert len(baseline)==15
        cases.append({'case':'original15_evaluator_packages_exact','passed':True,'expected_reject':False})
        evalroot=temp/'evaluation';evalroot.mkdir()
        for relative in evaluator.LOCAL.values():(evalroot/relative).mkdir(parents=True)
        mapped=original_bytes.replace(evaluator.OLD_ROOT.encode(),str(evalroot).encode())
        (evalroot/'FETCH_RECEIPT.json').write_text(json.dumps({'track_ref':'bffb57227f796f9fa769a23d01fc364bee14a119',
            'toolkit_ref':'v2.5.1','public_units':71,'references':[{}]*190,'runtime_reference_access':False})+'\n')
        actual=temp/'actual-freeze.txt';actual.write_bytes(mapped)
        check('actual_evaluator_onlytwo_localpaths_mapped',lambda:evaluator.validate(actual,evalroot,HERE/'bound_data/V2_EVALUATOR_FREEZE.txt'))
        for label,invalid in [('changed_version',mapped.replace(b'numpy==2.2.6',b'numpy==2.2.7')),
            ('extra_package',mapped+b'extra-package==1.0\n'),('missing_package',mapped.replace(b'attrs==26.1.0\n',b'')),
            ('duplicate_name',mapped+b'jsonSchema==4.23.0\n'),('wrong_localpath',original_bytes),
            ('unknown_direct_reference',mapped+b'extra @ file:///tmp/unexpected\n'),
            ('local_version_unbound',mapped.replace(next(row for row in mapped.splitlines() if row.startswith(b'qfbench2-common @')),b'qfbench2-common==1.0'))]:
            actual.write_bytes(invalid)
            check('evaluator_'+label+'_reject',lambda:evaluator.validate(actual,evalroot,HERE/'bound_data/V2_EVALUATOR_FREEZE.txt'),True)
        original=ast.parse((HERE.parent/'host_draft_v1/driver.py').read_bytes())
        fn=next(x for x in original.body if isinstance(x,ast.FunctionDef) and x.name=='run_process')
        copied=ast.parse((HERE/'saved_process_copy_v1.py').read_bytes())
        cp=next(x for x in copied.body if isinstance(x,ast.FunctionDef) and x.name=='run_saved_process')
        cp.name=fn.name;assert ast.dump(fn,include_attributes=False)==ast.dump(cp,include_attributes=False)
        cases.append({'case':'reviewed_process_manager_ASTexact_renameonly','passed':True,'expected_reject':False})
        tree=ast.parse(source.read_bytes())
        assert not any(isinstance(x,(ast.Import,ast.ImportFrom)) and any(y.name in ('production_cli','observer','native_owner_kernel') for y in x.names) for x in ast.walk(tree))
        for p in HERE.glob('*.py'):
            if not p.name.startswith('._'):ast.parse(p.read_bytes())
        cases.append({'case':'allordinarydraft_ASTparse_no_participant_import','passed':True,'expected_reject':False})
        data=json.loads((HERE/'bound_data/COPIED_DATA_PINS_v1.json').read_bytes())
        assert all(module.pin(HERE/'bound_data'/name)=={k:wanted[k] for k in ('bytes','sha256')} for name,wanted in data['files'].items())
        cases.append({'case':'allcopiedoriginaldataexactpins','passed':True,'expected_reject':False})
        workflow=(HERE/'t3-cost-diagnostic-hydration-draft-v1.yml').read_text()
        assert 'if: ${{ false }}' in workflow and 'cancel-in-progress: false' in workflow and 'actions: read' in workflow
        cases.append({'case':'workflow_disabled_no_futureidentity_serialreadtoken','passed':True,'expected_reject':False})
        result={'schema':'t3-cost-hydration-source-preflight-v1','all_source_cases_passed':True,'cases':cases,'case_count':len(cases),
            'source':module.pin(source),'synthetic_data_only':True,'network_called':False,'process_launched':False,'participant_imported':False,
            'native_compiled':False,'simulation_executed':False,'github_written':False,'ready_for_linux':False}
        (HERE/'SOURCE_PREFLIGHT_HYDRATION_v1.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
        print(json.dumps({'passed':True,'cases':len(cases),'source':result['source']}))
    finally:shutil.rmtree(temp)


if __name__=='__main__':main()
