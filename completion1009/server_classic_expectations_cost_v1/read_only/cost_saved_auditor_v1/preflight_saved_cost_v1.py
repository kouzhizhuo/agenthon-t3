"""Inert saved-auditor source and actual saved-data controls; no process launch."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import zipfile

HERE=Path(__file__).resolve().parent


def main():
    spec=importlib.util.spec_from_file_location('cost_saved_auditor_draft',HERE/'audit_cost_saved_v1.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    base,graph,delivery,parser=module.load_references()
    results=[]
    def case(name,fn,reject=False):
        try:fn();passed=not reject
        except (ValueError,KeyError,FileNotFoundError):passed=reject
        results.append({'case':name,'passed':passed,'expected_reject':reject})
    case('exact_refs15_fullbytes',lambda:module.require(len(module.inventory(HERE/'references'))==15,'referencecount'))
    case('typed_bool_not_int',lambda:module.exact(True,1),True)
    case('typed_nested_reject',lambda:module.exact({'a':[1]},{'a':[True]}),True)
    with tempfile.TemporaryDirectory(prefix='t3-cost-saved-inert-') as temp:
        root=Path(temp);artifact=root/'artifact';artifact.mkdir();evidence=artifact/'evidence';evidence.mkdir()
        (evidence/'retained.txt').write_bytes(b'actual saved synthetic data, no market execution')
        (artifact/'RUN_BINDING.json').write_text(json.dumps({'synthetic':True}))
        files=module.inventory(artifact)
        (artifact/'ARTIFACT.json').write_text(json.dumps({'schema':'t3-cost-complete-artifact-manifest-v1','files':files,
            'rankable':False,'all_actual_output_bytes_retained':True}))
        zip_path=root/'actual.zip'
        with zipfile.ZipFile(zip_path,'w') as out:
            for name in module.inventory(artifact):out.write(artifact/name,name)
        obj=module.Audit.__new__(module.Audit);obj.artifact=artifact.resolve();obj.evidence=evidence.resolve();obj.remote_root=module.PurePosixPath('/runner/cost-evidence')
        obj.args=SimpleNamespace(zip=zip_path,expected_zip_bytes=module.pin(zip_path)['bytes'],expected_zip_sha256=module.pin(zip_path)['sha256'])
        obj.hashes={};obj.report={'counts':{}}
        case('fullzip_manifest_positive_inert',obj.zip_complete)
        case('exact_path_mapping',lambda:module.require(obj.path('/runner/cost-evidence/retained.txt').resolve()==(evidence/'retained.txt').resolve(),'path'))
        for name,path in [('outside','/runner/other/retained.txt'),('parent','/runner/cost-evidence/../retained.txt'),('relative','cost-evidence/retained.txt'),('windows','/runner/cost-evidence/a\\b')]:
            case('path_'+name,lambda path=path:obj.path(path),True)
        (evidence/'retained.txt').write_bytes(b'mutated')
        obj.hashes={}
        case('zip_extracted_mutation',obj.zip_complete,True)
        badzip=root/'duplicate.zip'
        with zipfile.ZipFile(badzip,'w') as out:
            out.writestr('a',b'x');out.writestr('a',b'x')
        obj.args=SimpleNamespace(zip=badzip,expected_zip_bytes=module.pin(badzip)['bytes'],expected_zip_sha256=module.pin(badzip)['sha256'])
        (artifact/'a').write_bytes(b'x');obj.hashes={}
        case('zip_duplicate_member',obj.zip_complete,True)
        unsafe=root/'unsafe.zip'
        with zipfile.ZipFile(unsafe,'w') as out:out.writestr('../evil',b'x')
        obj.args=SimpleNamespace(zip=unsafe,expected_zip_bytes=module.pin(unsafe)['bytes'],expected_zip_sha256=module.pin(unsafe)['sha256'])
        case('zip_unsafe_member',obj.zip_complete,True)
        for label,name in [('metadata','._source'),('normalized','a//b'),('parent_collision','a/b')]:
            wrong=root/(label+'.zip')
            with zipfile.ZipFile(wrong,'w') as out:
                if label=='parent_collision':out.writestr('a',b'x')
                out.writestr(name,b'x')
            obj.args=SimpleNamespace(zip=wrong,expected_zip_bytes=module.pin(wrong)['bytes'],expected_zip_sha256=module.pin(wrong)['sha256'])
            case('zip_'+label,obj.zip_complete,True)
        for label,names in [('file_dir_collision',['a','a/']),('dir_file_collision',['a/','a']),('directory_under_file',['a','a/b/']),('reverse_under_file',['a/b/','a'])]:
            wrong=root/(label+'.zip')
            with zipfile.ZipFile(wrong,'w') as out:
                for name in names:out.writestr(name,b'' if name.endswith('/') else b'x')
            obj.args=SimpleNamespace(zip=wrong,expected_zip_bytes=module.pin(wrong)['bytes'],expected_zip_sha256=module.pin(wrong)['sha256'])
            case('zip_'+label,obj.zip_complete,True)
        huge=root/'huge.zip';huge.write_bytes(b'noarchive')
        obj.args=SimpleNamespace(zip=huge,expected_zip_bytes=8*1024**3+1,expected_zip_sha256=module.pin(huge)['sha256'])
        case('archive_compressed_cap',obj.zip_complete,True)
        case('image_stage_callable_no_property_shadow',lambda:module.require(callable(module.Audit.image),'callable'))
        missing=module.Audit.__new__(module.Audit);missing.evidence=root/'missing'
        case('absentactualparentauthority_reject',missing.parent,True)
    # Use existing real saved STATE and complete Parquet data. This failed-v1
    # reference validates decoder compatibility only; it is no delivery pass.
    reference=HERE.parent/'host_draft_v1/INDEPENDENT_HOST_SOURCE_REVIEW_v1.json'
    old=json.loads(reference.read_bytes())
    def find(value,key):
        if type(value) is dict:
            if key in value:return value[key]
            for child in value.values():
                answer=find(child,key)
                if answer is not None:return answer
        elif type(value) is list:
            for child in value:
                answer=find(child,key)
                if answer is not None:return answer
        return None
    witness=find(old,'saved_actual_graph_parser_compatibility')
    gpath=Path(witness['saved_graph']['path']);g=module.read(gpath)
    decoded=graph.GraphAudit().audit(g)
    case('real_saved_full_graph_MT624_alias_compatibility',lambda:module.require(decoded['RandomState_full624_count']==8 and decoded['all_backward_aliases_valid'] is True and decoded['global_MT19937_full624_state'] is True,'graph'))
    # GraphAudit actually executed above on entire saved3715485byte typedgraph.
    raw=base.BaseAudit();raw.decoded={};raw.filepin=module.pin
    import pyarrow.parquet as pq
    for kind in ('saved_trace','saved_ledger'):
        path=Path(witness[kind]['path']);rows=pq.ParquetFile(path).metadata.num_rows
        case('actual_saved_allrowgroups_'+kind,lambda path=path,rows=rows:raw.decode_parquet(path,{'candidate_rows':rows,'reference_rows':rows}))
    tree=ast.parse((HERE/'audit_cost_saved_v1.py').read_bytes())
    imports=[x.name for n in ast.walk(tree) if isinstance(n,ast.Import) for x in n.names]+[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    case('no_native_participant_driver_worker_or_process_imports',lambda:module.require(not any(n and any(k in n for k in ('subprocess','docker','native','production_cli','worker','driver','requests','urllib')) for n in imports),'imports'))
    compile((HERE/'audit_cost_saved_v1.py').read_bytes(),str(HERE/'audit_cost_saved_v1.py'),'exec')
    report={'schema':'t3-cost-saved-auditor-inert-source-preflight-v1','all_source_checks_passed':all(r['passed'] for r in results),
        'all_passed':False,'ready_for_linux':False,'actual_cost_artifact_accepted':False,'case_count':len(results),'cases':results,
        'source':module.pin(HERE/'audit_cost_saved_v1.py'),'references':module.pin(HERE/'REFERENCE_PINS_v1.json'),
        'saved_graph':witness['saved_graph'],'saved_graph_decoded':decoded,'fully_decoded_parquets':raw.decoded,
        'participant_imported':False,'native_compiled':False,'market_executed':False,'process_launched':False,'Docker_executed':False,
        'network_used':False,'independent_review':False,'failed_v1_reference_is_deliverypass':False}
    (HERE/'SOURCE_PREFLIGHT_SAVED_COST_v1.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'all_source_checks_passed':report['all_source_checks_passed'],'case_count':len(results),'actual_cost_artifact_accepted':False}))
    return 0 if report['all_source_checks_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
