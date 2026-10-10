"""Independent saved-only Stage 1 cost artifact auditor draft.

No participant import, simulation, native compile, Docker, network or subprocess.
Only a complete actual artifact plus complete external delivery/registry bytes
can pass. Missing actual inputs produce a failed report, never synthetic evidence.
"""
import argparse
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
REFERENCE = HERE / 'references'
DELIVERY = REFERENCE / 'delivery_saved_v1'
BASE_RUN = 38072276259
BASE_HEAD = '2164738b7508d9554cb6bd0a37ec46375cee8199'
BASE_PINS = 'b5cf9f49879ad5fe90b760831914e6e3e19f92186df2503c5b5ca2ff0bc34279'
ENTRY = '/opt/t3-classic-structural-v2/cost-diagnostic-v1/cost_entry_draft_v1.py'
PUBLIC_ENTRY = ['/usr/local/bin/python', '-B', '/opt/classic-native-kernels-v1/delivery_entry.py']
ARMS = {'parent': 'classic_native_kernels_v1', 'expectations': 'classic_build_expectations_v1'}
UNITS = ('t3-s001-price-time-priority', 't3-as06-throughput-fast', 't3-mp01-stp-newest-baseline',
    't3-ra01-fundamental-shock-mid', 't3-mr-deep-book-state-size', 't3-gbatch-hetero-mix')
ROOTS = {'native': '/opt/classic-native-kernels-v1', 'harness': '/opt/t3-classic-structural-v2', 'licenses': '/licenses'}
BASE_ROOTS = {'native': 'installed', 'harness': 'installed-harness', 'licenses': 'installed-licenses'}
DROP = {'wall_clock_sec', 'events_per_sec', 'peak_memory_bytes', 'gpu_seconds'}
LOG_CAP = 16 * 1024**2
COST_CAP = 256 * 1024**2
REFERENCE_SHA = {
    'references/cost_parser_v1.py': '18e8b63b5c80dc95331d64b8564be573777baeae1c10449a86cd2c5c06508db8',
    'references/delivery_saved_v1/audit_saved_delivery_v1.py': '4df3066d3e5c5940466d12357bc667e338f4db67578483bbe8b652e1e30a1c23',
    'references/delivery_saved_v1/saved_base_v1.py': 'c8d6dcd4c09b0b2dce8e53f8a3f9f89947d7eef0df71b768fa258a4befed3b3f',
    'references/delivery_saved_v1/graph_saved_v1.py': '35d289bd9f521fc3bfb8a65d7d49a49787420fc10e4c7cd138b8e1d63c675f63',
    'references/delivery_saved_v1/AUDITOR_FREEZE_v1.json': 'be949e80178c57c0dc0fb261244fb0927231d13dceeb68d426b2380040fda807'}


def require(value, message):
    if not value:
        raise ValueError(message)


def read(path):
    def pairs(values):
        answer = {}
        for key, value in values:
            require(key not in answer, 'duplicate JSON key')
            answer[key] = value
        return answer
    return json.loads(Path(path).read_bytes(), object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def pin(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'actual ordinary file required')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            digest.update(block)
    return {'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def inventory(root):
    answer = {}
    for path in sorted(Path(root).rglob('*')):
        if any(s.startswith('._') or s in ('__MACOSX', '__pycache__') for s in path.parts):
            continue
        require(not path.is_symlink(), 'saved symlink refused')
        if path.is_file():
            answer[path.relative_to(root).as_posix()] = pin(path)
    return answer


def exact(actual, expected):
    require(type(actual) is type(expected), 'exact typed value required')
    if type(expected) is dict:
        require(set(actual) == set(expected), 'exact dictionary keys')
        for key, value in expected.items():
            exact(actual[key], value)
    elif type(expected) is list:
        require(len(actual) == len(expected), 'exact listlength')
        for a, b in zip(actual, expected):
            exact(a, b)
    else:
        require(actual == expected, 'exact value differs')


def full_equal(left, right):
    if pin(left)['bytes'] != pin(right)['bytes']:
        return False
    with Path(left).open('rb') as a, Path(right).open('rb') as b:
        while True:
            x, y = a.read(1024**2), b.read(1024**2)
            if x != y:
                return False
            if not x:
                return True


def stable(value):
    if type(value) is dict:
        return {k: stable(v) for k, v in value.items() if k not in DROP}
    if type(value) is list:
        return [stable(v) for v in value]
    return value


def unit_core(row):
    return {k: row[k] for k in ('unit', 'shape', 'subs', 'input_sha256', 'reference_sha256')}


def load_references():
    expected = read(HERE / 'REFERENCE_PINS_v1.json')['files']
    require(type(expected) is dict and len(expected) == 15, 'exact15reference schema')
    actual = {str(PurePosixPath('references') / name): value for name, value in inventory(REFERENCE).items()}
    require(actual == expected, 'all exact15reference bytes')
    for name, sha in REFERENCE_SHA.items():
        require(pin(HERE / name)['sha256'] == sha, 'independently pinned executing reference byte')
    for name in ('saved_base_v1', 'graph_saved_v1', 'audit_saved_delivery_v1'):
        require(name not in sys.modules, 'fresh saved helper module namespace')
    old_path = sys.path[:]
    try:
        sys.path.insert(0, str(DELIVERY))
        import saved_base_v1 as base
        import graph_saved_v1 as graph
        import audit_saved_delivery_v1 as delivered
    finally:
        sys.path[:] = old_path
    spec = importlib.util.spec_from_file_location('t3_frozen_cost_saved_parser', REFERENCE / 'cost_parser_v1.py')
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    return base, graph, delivered, parser


class Audit:
    def __init__(self, args):
        self.args = args
        self.artifact = args.artifact.resolve()
        self.evidence = self.artifact / 'evidence'
        self.remote_root = PurePosixPath(args.remote_evidence_root)
        require(self.remote_root.is_absolute() and '..' not in self.remote_root.parts, 'explicit absolute exact remote evidence root')
        self.remote_source_root=PurePosixPath(args.remote_source_root)
        require(self.remote_source_root.is_absolute() and '..' not in self.remote_source_root.parts,'explicitabsolute actualexecutingsource root')
        self.report = {'schema': 't3-independent-cost-saved-artifact-audit-v1', 'all_passed': False,
            'ready_for_linux': False, 'rankable': False, 'official_submission_eligible': False,
            'performance_usable': False, 'market_executed': False, 'native_compiled': False,
            'participant_imported': False, 'Docker_executed': False, 'network_used': False, 'process_launched': False,
            'status': 'auditing', 'completed_stages': [], 'failures': [], 'counts': {}, 'limitations': [
                'Perturbed cost diagnostics certify equivalence and lifecycle only; they do not certify ordinaryEPS or232000.',
                'Complete parent deliveryZIP and anonymous registry compressed layers/diffIDs are mandatory saved inputs.',
                'Reviewed driver host-process receipts lack raw start/finish timestamps. Worker process seriality is source-bound; actual24daemon intervals are separately revalidated. Additional host chronology requires a new reviewed driver revision.',
                'Host image_metadata saves raw stdout/stderr and IMAGE JSON but no separate per-command returncode receipt. Matching complete rawmetadata bytes do not create absent returncode evidence.']}
        self.hashes, self.decoded, self.graphs = {}, {}, {}
        self.base, self.graph_module, self.delivery, self.parser = load_references()
        outer = self
        class Raw(outer.base.BaseAudit):
            def path(self, value):
                return outer.path(value)
            def filepin(self, value):
                return outer.filepin(value)
            def inventory(self, value):
                return inventory(value)
        self.raw = Raw()
        self.raw.intervals, self.raw.executions, self.raw.decoded = [], [], self.decoded

    def path(self, value):
        require(type(value) is str and '\\' not in value, 'typed exact saved remote path')
        remote = PurePosixPath(value)
        require(remote.is_absolute() and '..' not in remote.parts, 'safe absolute saved path')
        tail = remote.relative_to(self.remote_root)
        result = self.evidence / tail.as_posix()
        require(self.evidence.resolve() == result.resolve() or self.evidence.resolve() in result.resolve().parents,
            'saved path inside exact evidence root')
        require(not any(p.is_symlink() for p in (result, *result.parents)), 'saved path nonsymlink ancestors')
        return result

    def filepin(self, value):
        path = Path(value)
        if path not in self.hashes:
            self.hashes[path] = pin(path)
        return self.hashes[path]

    def zip_complete(self):
        expected = {}
        wanted = {'bytes': self.args.expected_zip_bytes, 'sha256': self.args.expected_zip_sha256}
        require(type(wanted['bytes']) is int and 0 < wanted['bytes'] <= 8 * 1024**3
            and re.fullmatch('[0-9a-f]{64}', wanted['sha256']), 'finiteactualcostZIP bound')
        require(pin(self.args.zip) == wanted, 'actual complete costZIP hash/size')
        names, files, decoded_total = set(), set(), 0
        with zipfile.ZipFile(self.args.zip) as archive:
            members=archive.infolist()
            require(0 < len(members) <= 40000, 'finitecostZIP40000member bound')
            types={}
            for member in members:
                path=PurePosixPath(member.filename)
                key=path.as_posix()
                require(key not in types,'normalizedZIP file/directory namecollision')
                types[key]=member.is_dir()
            for name,is_directory in types.items():
                require(all(types.get(parent.as_posix(),True) is True for parent in PurePosixPath(name).parents),
                    'completeZIP fileancestorcollision independentorder')
            for member in members:
                path = PurePosixPath(member.filename)
                normalized = path.as_posix() + ('/' if member.is_dir() else '')
                require(not path.is_absolute() and '..' not in path.parts and '\\' not in member.filename
                    and normalized == member.filename and ':' not in member.filename and '\x00' not in member.filename
                    and path.as_posix() not in ('','.','/')
                    and not any(s.startswith('._') or s in ('__MACOSX','__pycache__') for s in path.parts),
                    'exactordinarynormalizedcostZIPmember metadatarefused')
                require(member.filename not in names and not member.flag_bits & 1, 'uniqueunencryptedZIPmembers')
                names.add(member.filename)
                mode=(member.external_attr >> 16)
                require(not mode & 0o6000,'ZIP setuid/setgid modesrefused')
                kind=mode & 0o170000
                require(kind in (0,0o040000) if member.is_dir() else kind in (0,0o100000),'ZIPregularfile/directorytype only')
                if member.is_dir():
                    require(member.file_size==0,'emptydirectoryZIPentry')
                    continue
                require(member.file_size <= 4*1024**3,'4GiBcompleteSTATE memberhardbound')
                require(not any(parent.as_posix() in files for parent in path.parents),'ZIPfileancestorcollision')
                require(not any(existing.startswith(path.as_posix()+'/') for existing in names),'ZIPfiledescendantcollision')
                files.add(path.as_posix())
                decoded_total += member.file_size
                require(decoded_total <= 64*1024**3,'finite64GiBfulldecodedarchive')
                digest, size = hashlib.sha256(), 0
                with archive.open(member) as stream:
                    for block in iter(lambda: stream.read(1024**2), b''):
                        digest.update(block); size += len(block)
                        require(size<=member.file_size,'ZIPdeclaredsizebound')
                require(size==member.file_size,'completeZIPdeclaredmember')
                row = {'bytes': size, 'sha256': digest.hexdigest()}
                require((self.artifact/member.filename).stat().st_size==size,'exactsavedmember sizebeforehash')
                require(self.filepin(self.artifact / member.filename) == row, 'entireextracted file equals costZIP')
                expected[member.filename] = row
            require(archive.testzip() is None, 'full costZIP CRC')
        require(expected == inventory(self.artifact), 'complete costZIP extracted roster noextras')
        manifest = read(self.artifact / 'ARTIFACT.json')
        require(manifest.get('schema') == 't3-cost-complete-artifact-manifest-v1' and manifest.get('rankable') is False
            and manifest.get('all_actual_output_bytes_retained') is True
            and manifest['files'] == {k:v for k,v in expected.items() if k!='ARTIFACT.json'}, 'wholeactualartifactmanifest')
        self.report['counts']['artifact_files'] = len(expected)
        self.report['artifact'] = wanted

    def source(self):
        carried = self.evidence / 'source-harness'
        pins_path = self.evidence / 'authority-inputs/SOURCE_PINS.json'
        remote_path = self.evidence / 'authority-inputs/REMOTE_SOURCE_READBACK.json'
        require(pin(pins_path)['sha256'] == self.args.expected_source_pins_sha256, 'explicit active cost sourcefreezeSHA')
        pins = read(pins_path)
        require(pins.get('schema') == 't3-cost-host-source-pins-v1' and pins.get('reviewed') is pins.get('ready_for_linux') is True
            and pins.get('runtime_changed') is False, 'independently finalized actualcost sourcefreeze')
        require(inventory(carried) == pins['files'], 'entirecarriedsourceharness exactlyfreeze')
        require(all(pin(self.args.source/n)==v for n,v in pins['files'].items()), 'exact separately supplied independent source authority')
        require(pin(self.args.source_pins) == pin(pins_path), 'carried andindependentcost sourcepins equal')
        require(pin(carried/'INDEPENDENT_HOST_SOURCE_REVIEW_v1.json')['sha256']=='780aa8fafaf2980a381e5dc63c0766aa6426702ba170156893d165eccab363a7',
            'trustedindependenthostreview completebytes')
        reviewed=read(carried/'INDEPENDENT_HOST_SOURCE_REVIEW_v1.json')
        require(reviewed.get('source_scope_passed') is True and reviewed.get('source_blockers')==[], 'actualindependenthostsource review carried')
        for name in ('driver.py','worker.py','parser.py'):
            require(pin(carried/name)=={k:reviewed['source_files'][name][k] for k in ('bytes','sha256')},'independentreview exactcarriedsource binding')
        remote = read(remote_path)
        require(remote.get('all_passed') is True and remote.get('head') == self.args.expected_head
            and remote.get('participant_imported') is False, 'costsource samehead independentreadback')
        wanted = {pins['remote_prefix'] + name: value for name,value in pins['files'].items()}
        wanted[pins['remote_prefix'] + Path(self.args.source_pins).name] = pin(pins_path)
        wanted[pins['active_workflow']] = pins['files'][pins['workflow_source']]
        require(len(remote['checks'])==len(wanted) and {r['path']:r['actual'] for r in remote['checks']}==wanted
            and all(r.get('passed') is True and r['actual']==r['expected'] for r in remote['checks']), 'completeoneheadcostsource/workflow')
        require(pins['active_workflow']==self.args.expected_workflow and pins['workflow_source'] in pins['files'], 'explicitactualcostworkflow authority')
        run=read(self.artifact/'RUN_BINDING.json')
        exact(run, {'schema':'t3-cost-actual-run-binding-v1','run_id':self.args.expected_run_id,'run_attempt':self.args.expected_run_attempt,
            'head':self.args.expected_head,'workflow':self.args.expected_workflow,'source_pins_sha256':self.args.expected_source_pins_sha256})
        for name in ('driver.py','worker.py','parser.py','Dockerfile','overlay/cost_entry_draft_v1.py','overlay/IMAGE_BINDING.json',
            'READ_ONLY_SOURCE_PINS_v1.json','read_only/source_copy.py','read_only/host/verify_linux.py','read_only/host/verify_public.py'):
            require(name in pins['files'], 'allexecutingcarriedhostpaths frozen')
        require(pin(carried/'READ_ONLY_SOURCE_PINS_v1.json')['sha256']=='f05b92a93c2cbb5d88fcbb62611228c9bf0b13ad52ae1546edbbcad262d6b304',
            'trustedreadonly17completepinsreceipt')
        readonly=read(carried/'READ_ONLY_SOURCE_PINS_v1.json')['files']
        require(len(readonly)==17 and all(pins['files'].get(n)==v for n,v in readonly.items()),'all17unchangedhosthelpersfrozen')
        for name,sha in REFERENCE_SHA.items():
            if name.startswith('references/delivery_saved_v1/'):
                corresponding='read_only/frozen_saved_auditor_v1/'+name.rsplit('/',1)[1]
                require(pin(carried/corresponding)['sha256']==sha,'exactoriginalauditorhelper source')
        self.source_root, self.source_pins = carried, pins
        for name in ('driver.py','worker.py','parser.py'):
            ast.parse((carried/name).read_bytes())
        require(pin(carried/'parser.py') == pin(REFERENCE/'cost_parser_v1.py'), 'exact independently audited parsercopy')
        authority = read(self.evidence/'HOST_AUTHORITY.json')
        self.binding = read(self.evidence/'authority-inputs/IMAGE_BINDING.json')
        exact(authority['binding'], self.binding)
        require(self.binding.get('schema')=='t3-expectations-cost-image-binding-v1' and self.binding.get('ready_for_linux') is True
            and self.binding.get('runtime_changed') is False and self.binding.get('base_publication_authority') is True
            and self.binding.get('publication_authority') is False and self.binding.get('rankable') is False,
            'costbinding basepublished but diagnosticunpublished')
        require(self.binding==read(carried/'overlay/IMAGE_BINDING.json'), 'actualembeddedfrozenbinding')
        require(authority.get('schema')=='t3-cost-host-authority-v1' and authority.get('ready_for_linux') is authority.get('all_passed') is True
            and authority.get('base_publication_authority') is True and authority.get('publication_authority') is False
            and authority.get('runtime_changed') is authority.get('rankable') is False and authority['source_pins']==pin(pins_path),
            'actualhostauthorityschema/sourcebound')
        self.authority = authority
        self.image_id, self.digest = authority['overlay_image_id'], self.binding['actual_final_public_digest']
        require(re.fullmatch('sha256:[0-9a-f]{64}',self.image_id) and re.fullmatch(r'ghcr\.io/kouzhizhuo/agenthon-t3-classic@sha256:[0-9a-f]{64}',self.digest),
            'exact actualderived/baseimageidentities')
        dockerfile='FROM '+self.digest+'\nCOPY --chown=0:0 --chmod=0444 overlay/ /opt/t3-classic-structural-v2/cost-diagnostic-v1/\n'
        require((carried/'Dockerfile').read_text()==dockerfile, 'oneexactFROM oneCOPY noRUN/config/nativechange')
        require(inventory(carried/'overlay')==authority['overlay_files'] and set(authority['overlay_files'])=={'cost_entry_draft_v1.py','IMAGE_BINDING.json'},
            'exact twofile overlay')
        require(pin(self.evidence/'overlay-context/Dockerfile')==pin(carried/'Dockerfile')
            and inventory(self.evidence/'overlay-context/overlay')==authority['overlay_files'], 'actualbuildcontextsourceequal')

    def parent(self):
        doc=read(self.evidence/'authority-inputs/base-authority.json')
        require(doc.get('schema')=='t3-cost-actual-base-authority-v1' and doc.get('ready_for_linux') is True
            and doc.get('run_id')==BASE_RUN and type(doc.get('run_id')) is int and doc.get('run_attempt')==1
            and type(doc.get('run_attempt')) is int and doc.get('head')==BASE_HEAD and doc.get('sourcepins_sha256')==BASE_PINS
            and doc.get('workflow')=='t3-classic-expectations-delivery-v2.yml', 'genuine actualuniquev2baseauthority')
        for label,path in (('saved_audit',self.evidence/'authority-inputs/base-receipts/saved_audit.json'),
            ('anonymous_registry',self.args.registry_readback),('remote_source_readback',self.args.base_remote_readback),
            ('baseline_reference_plan',self.args.baseline_reference_plan)):
            require(pin(path)=={k:doc[label][k] for k in ('bytes','sha256')},'eachcarriedparentreceipt exactactualexternalbinding')
        require(pin(self.evidence/'authority-inputs/base-receipts/anonymous_registry.json')==pin(self.args.registry_readback)
            and pin(self.evidence/'authority-inputs/base-receipts/remote_source_readback.json')==pin(self.args.base_remote_readback)
            and pin(self.evidence/'authority-inputs/base-receipts/baseline_reference_plan.json')==pin(self.args.baseline_reference_plan),
            'allcarriedbaseauthorityreceiptbytes')
        require(doc['artifact_zip']['bytes']==self.args.base_zip_bytes and doc['artifact_zip']['sha256']==self.args.base_zip_sha256,
            'complete externalbaseZIP exactcarriedauthority')
        base_args=SimpleNamespace(artifact=self.args.base_artifact,zip=self.args.base_zip,expected_zip_bytes=self.args.base_zip_bytes,
            expected_zip_sha256=self.args.base_zip_sha256,source=self.args.base_source,expected_source_pins_sha256=BASE_PINS,
            expected_head=BASE_HEAD,expected_workflow='t3-classic-expectations-delivery-v2.yml',remote_readback=self.args.base_remote_readback,
            frozen_payload=self.args.frozen_payload,baseline_payload=self.args.baseline_payload,baseline_reference_plan=self.args.baseline_reference_plan,
            expected_run_id=BASE_RUN,expected_run_attempt=1,registry_readback=self.args.registry_readback,
            remote_evidence_marker='expectations-delivery-evidence/')
        saved=self.delivery.Audit(base_args)
        for stage in ('zip_manifest','source_build','copy_lifecycle','controls','diagnostic','ordinary_runs','timing_finish','publication'):
            getattr(saved,stage)();saved.report['completed_stages'].append(stage)
        require(saved.report['all_execution_checks_passed'] is True and saved.report['publication_passed'] is True
            and saved.report['pending']==saved.report['failures']==[], 'full externalparentZIP/publiclayers replay')
        self.parent_audit,self.parent_evidence=saved,self.args.base_artifact/'evidence'
        pub=read(self.parent_evidence/'PUBLICATION.json')
        require(pub['image']==self.digest and pub['image_id']==self.binding['actual_final_image_id']==doc['base_image_id'],
            'actualparentpublicationsamebasebinding')
        registry=read(self.args.registry_readback)
        require(pin(self.args.registry_readback)=={k:doc['anonymous_registry'][k] for k in ('bytes','sha256')}, 'externalanonymousreceipt exactbinding')
        base_inventory={k:inventory(self.parent_evidence/n) for k,n in BASE_ROOTS.items()}
        require(base_inventory==self.binding['base_source_inventory'], 'allactualbase C/object/ELF/licensesinventory')
        candidates={name:inventory(self.parent_evidence/'installed/completion1009/candidates'/name) for name in ARMS.values()}
        require(candidates==self.binding['candidate_source_files'], 'botharms actualsamebase completesources')
        self.base_inventory=base_inventory
        original_report=read(self.evidence/'authority-inputs/base-receipts/saved_audit.json')
        require(original_report['all_passed'] is original_report['publication_passed'] is original_report['all_execution_checks_passed'] is True
            and original_report['failures']==original_report['pending']==[] and original_report['authority']['artifact']==pin(self.args.base_zip)
            and original_report['authority']['public_image']==self.digest, 'carried genuinefullbaseaudit')
        replay=read(self.evidence/'base-audit-replay.json')
        require(replay['all_passed'] is replay['publication_passed'] is replay['all_execution_checks_passed'] is True
            and replay['failures']==replay['pending']==[] and replay['authority']['artifact']==pin(self.args.base_zip)
            and replay['authority']['public_image']==self.digest,'actualhostbaseauditreplay sameauthority')
        require(self.authority['base_pins']=={'saved_audit':pin(self.evidence/'authority-inputs/base-receipts/saved_audit.json'),
            'fresh_audit':pin(self.evidence/'base-audit-replay.json'),'registry':pin(self.args.registry_readback),'artifact':pin(self.args.base_zip)},
            'hostauthorityallbasepins independentlyverified')
        self.report['base_replay_counts']=saved.report['counts']

    def image(self):
        base=self.authority['base_metadata'];overlay=self.authority['overlay_metadata']
        actualbase=read(self.parent_evidence/'published-metadata/IMAGE.json')
        require(base==actualbase and base['Id']==self.binding['actual_final_image_id'] and self.digest in base['RepoDigests'], 'actualsavedpublishedbaseconfig')
        require(overlay['Id']==self.image_id and self.image_id!=base['Id'] and overlay['Os']==base['Os']=='linux'
            and overlay['Architecture']==base['Architecture']=='amd64' and overlay['Config']==base['Config'], 'derivedimage exactinheritedconfig')
        require(base['Config']['Entrypoint']==PUBLIC_ENTRY and base['Config'].get('Cmd') in (None,[]) and not base['Config'].get('Volumes')
            and not base['Config'].get('OnBuild') and base['Config']['User']=='65534:65534','publicconfig noONBUILD')
        require(overlay['RootFS']['Type']==base['RootFS']['Type']=='layers' and overlay['RootFS']['Layers'][:-1]==base['RootFS']['Layers']
            and len(overlay['RootFS']['Layers'])==len(base['RootFS']['Layers'])+1,'oneCOPY additiveRootFSprefix')
        require(overlay==read(self.evidence/'overlay-image-metadata/000-image-inspect.stdout.txt')[0]
            ==read(self.evidence/'overlay-image-metadata-after/000-image-inspect.stdout.txt')[0], 'actualrawbeforeafterderivedmetadata')
        require(read(self.evidence/'overlay-image-metadata/IMAGE.json')==read(self.evidence/'overlay-image-metadata-after/IMAGE.json')==overlay,
            'actualmetadatareceiptmatchesraw')
        inventories={k:inventory(self.evidence/('overlay-'+k+'-before')) for k in ROOTS}
        require(inventories=={k:inventory(self.evidence/('overlay-'+k+'-after')) for k in ROOTS}
            ==self.authority['verified_before_source_inventory'], 'exactderived3root beforeafter')
        expected=copy.deepcopy(self.base_inventory)
        for name,p in self.authority['overlay_files'].items():
            path='cost-diagnostic-v1/'+name
            require(path not in expected['harness'],'nooverlayoverwrite')
            expected['harness'][path]=p
        require(inventories==expected,'onlyexacttwofilesadded no C/object/ELF/licence/sourcechanges')
        require(self.authority['base_image_id']==base['Id'] and self.authority['public_digest']==self.digest,'hostactualbase identitybound')
        self.report['counts']['source_roots_before_after']=6
        for name,requested,image in (('base-image-metadata',self.digest,base['Id']),('overlay-image-metadata',None,self.image_id),
            ('overlay-image-metadata-after',self.image_id,self.image_id)):
            imagepath=self.evidence/name/'IMAGE.json'
            actual=read(imagepath)
            require(actual['Id']==image, 'actualhostmetadata target')
            if name=='base-image-metadata':
                require(all(actual[k]==base[k] for k in ('Id','Config','RootFS','Os','Architecture','Size'))
                    and self.digest in actual.get('RepoDigests',[]),'pulledbasecore+digest metadata exact')
            stdout=self.evidence/name/'000-image-inspect.stdout.txt';stderr=self.evidence/name/'000-image-inspect.stderr.txt'
            require(stdout.is_file() and stderr.is_file() and stdout.stat().st_size<LOG_CAP and stderr.stat().st_size<LOG_CAP
                and read(stdout)==[read(imagepath)], 'fullhostmetadata rawstream matchesreceipt')

    def command(self,row,success=True):
        self.raw.command(row,success)

    def source_copies(self):
        for side in ('before','after'):
            for key,remote in ROOTS.items():
                row=read(self.evidence/(key+'-'+side+'-copy.json'))
                require(row['container_never_started'] is row['copy_succeeded'] is True and row['rankable'] is row['timing_included'] is False
                    and row.get('failure') is None and row.get('secondary_errors')==[], 'successfulactualsourcecopy')
                commands=row['commands'];cleanup=row['cleanup'];name,owner=cleanup['name'],cleanup['owner']
                require(re.fullmatch('t3-structural-source-[0-9a-f]{32}',name) and re.fullmatch('[0-9a-f]{32}',owner), 'typedownedsourcecopy')
                operations=[]
                for cmd in commands:
                    success=not(cmd['argv'][1]=='inspect' and cmd['returncode']==1)
                    self.command(cmd,success);operations.append(cmd['argv'][1])
                    require(cmd['per_log_file_hard_bytes']==LOG_CAP, 'sourcecopy separate16MiBlog')
                    if cmd['argv'][1]=='inspect' and cmd['returncode']==0:
                        info=read(self.path(cmd['stdout']['path']))
                        require(len(info)==1 and info[0]['Name']=='/'+name and info[0]['Image']==self.image_id
                            and info[0]['Config']['Labels']['qfbench2.t3.verifier_owner']==owner, 'rawsourcecopy exactownedidentity')
                        state=info[0]['State']
                        require(state['Status']=='created' and state['Pid']==0 and state['Running'] is False
                            and state['StartedAt']==state['FinishedAt']=='0001-01-01T00:00:00Z','neverstarted rawsourcecopy')
                info=read(self.path(commands[1]['stdout']['path']))[0]
                require(self.path(commands[0]['stdout']['path']).read_text()==info['Id']+'\n'
                    and cleanup.get('container_id')==info['Id'],'rawcreatedsourcecopy exactID')
                require(any(c['argv']==['docker','rm',name] and c['returncode']==0 for c in commands),'rawsourcecopy removal')
                require(commands[0]['argv']==['docker','create','--name',name,'--label','qfbench2.t3.verifier_owner='+owner,'--pull','never',self.image_id],
                    'unspecialized originalsourcecopycreate')
                require(operations.count('create')==operations.count('cp')==operations.count('rm')==1
                    and set(operations)<={'create','cp','inspect','rm'},'noextrasourceexecution')
                cp=next(c for c in commands if c['argv'][1]=='cp')
                require(cp['argv']==['docker','cp',name+':'+remote,str(self.remote_root/('overlay-'+key+'-'+side))]
                    and cp['source_copy_only'] is True and cp['source_file_hard_bytes']==64*1024**2,'originalcopy roots64MiB')
                require(cleanup['settled'] is cleanup['removed'] is cleanup['final_absent'] is True and cleanup['errors']==[]
                    and cleanup['state_before_remove']==info['State'],'sourcecopycleanup exactterminalrawstate')
                last=commands[-1]
                require(last['argv']==['docker','inspect',name] and last['returncode']==1
                    and self.path(last['stdout']['path']).read_bytes()==b'[]\n'
                    and self.path(last['stderr']['path']).read_text()=='Error: No such object: '+name+'\n','rawfinalsourceabsence')
        self.report['counts']['neverstarted_sourcecopy_containers']=6

    def metadata_command(self,meta,image):
        require(meta['id']==image and meta['requested']==image and len(meta['commands'])==1,'oneownedimagemetadata')
        cmd=meta['commands'][0];self.command(cmd)
        require(cmd['argv']==['docker','image','inspect',image]
            and read(self.path(cmd['stdout']['path']))==[meta['inspection']],'rawmetadata exactimageconfig')

    def market_input_roster(self,item,execution,output):
        local=copy.deepcopy(execution)
        original=copy.deepcopy(item)
        paths=[]
        for record in local['staged_inputs']:
            source=PurePosixPath(record['source'])
            require(source.as_posix() in item['scenario_paths'],'originalsource belongs exactunit')
            relative=PurePosixPath(record['staged']).relative_to(self.remote_root)
            actual=self.evidence/relative.as_posix()
            record['staged']=str(actual)
            paths.append(record['source'])
        roster=self.parser.roster_from_execution(original,local,output)
        # Parse must retain original container namespace; only host staged paths
        # are local audit views. This mapping never changes saved result bytes.
        return roster

    def outputs(self,row,item,request):
        # BaseAudit.output is given an explicitly diagnostic local view and
        # canonical reference namespace. Original raw gate argv is checked first.
        out=self.path(row['output']);gate=row['developer_verifier'];argv=gate['execution']['argv']
        require(len(argv)==11 and argv[1].endswith('/read_only/host/verify_public.py'),'exactgate argv length/source')
        require(argv[2:4]==['_gate','--unit'] and argv[4]==request['reference_root']+'/'+item['unit']
            and argv[5]=='--output' and self.path(argv[6])==out and argv[7]=='--save'
            and self.path(argv[8])==out.parent/'developer_verdict.json' and argv[9]=='--gate-kit'
            and argv[10]==request['gate_kit'],'exactactualgateargv/unit/output/kit')
        require(argv[1]==str(self.remote_source_root/'read_only/host/verify_public.py'),'actualunchangedcopiedgate source')
        view=copy.deepcopy(row);view['stage']='diagnostic'
        view['developer_verifier']['execution']['argv'][4]='/references/'+item['unit']
        view['developer_verifier']['execution']['argv'][10]='/track3'
        for frame in view['reference_checks']['frames']:
            source=PurePosixPath(frame['reference']).relative_to(PurePosixPath(request['reference_root'])/item['unit'])
            frame['reference']='/references/'+item['unit']+'/'+source.as_posix()
        self.raw.output(view,item,diagnostic=True)
        require(read(self.path(argv[8]))==gate['verdict'],'actualrawsavedgateverdict')
        return out

    def pairs(self,left,right):
        a,b=inventory(left),inventory(right)
        require(set(a)==set(b),'completeoutputroster equal')
        for name in a:
            require(full_equal(left/name,right/name) if name.endswith('.parquet') else stable(read(left/name))==stable(read(right/name)),
                'completeoutputbytes/stablesidecars equal')

    def markets(self):
        plan=read(self.evidence/'REFERENCE_PLAN.json');base_plan=read(self.parent_evidence/'REFERENCE_PLAN.json')
        items={r['unit']:r for r in plan['units']}
        require(self.authority['full71_plan']==plan,'hostauthorityexactactualfullplan')
        hostpins={n:pin(self.source_root/'read_only/host'/n) for n in ('verify_linux.py','verify_public.py')}
        require(self.authority['host_pins']==hostpins,'hostauthorityexecutinghostpins')
        checks=self.authority['checks']
        require(set(checks)=={'base_saved_audit_passed','anonymous_registry_full_bytes_verified','base_manifest_config_bound',
            'base_source_C_object_ELF_licenses_verified','overlay_config_inherited_exactly','overlay_rootfs_additive',
            'overlay_before_inventory_exact','source_command_class_original','full71_roster_inputs_refs_bound'} and all(v is True for v in checks.values()),
            'authoritychecks agreeindependentstages')
        require(len(items)==len(plan['units'])==71 and plan['reference_frame_count']==190
            and {n:unit_core(r) for n,r in items.items()}=={r['unit']:unit_core(r) for r in base_plan['units']}
            and sum(1 if r['shape']=='single' else len(r['subs']) for r in items.values())==95,'exactactual71unit95marketreference')
        schedule=[{'label':'cost-%02d-%s-%s'%(i,arm,mode),'unit':unit,'arm':arm,'cost_mode':mode}
            for i,unit in enumerate(UNITS) for arm in ARMS for mode in ('state','cost')]
        recorded=read(self.evidence/'SCHEDULE.json')
        require(recorded['cells']==schedule and recorded['rankable'] is False,'actualfixed24costschedule')
        for field,wanted in {'diagnostic_containers':24,'complete_STATE_graphs':40,'official_gates':96,'Parquet_copies':80,
            'ordinary':0,'warmup':0,'controls':0}.items():exact(recorded[field],wanted)
        rows=read(self.evidence/'RAW_RESULTS.json');require(len(rows)==24,'24actualcompleteworkerreceipts')
        first={};graphs=parquets=gates=0;recomputed_comparisons=[]
        for cell,row in zip(schedule,rows):
            label=cell['label'];folder=self.evidence/'diagnostic'/label
            require(row==read(folder/'RUN_RESULT.json')==read(self.evidence/'worker-results'/(label+'.json')),'threeidenticalactualcellreceipts')
            require(row['schema']=='t3-cost-worker-result-v1' and row['passed'] is True and row['failure'] is None
                and row['rankable'] is row['timing_included'] is False and row['unit']==cell['unit'] and row['arm']==cell['arm']
                and row['cost_mode']==cell['cost_mode'],'exactsuccessuntimedcell')
            request_path=self.evidence/'worker-requests'/(label+'.json');request=read(request_path)
            exact(request['timeout_sec'],3600);exact(request['log_cap_bytes'],COST_CAP)
            require(request['schema']=='t3-cost-worker-request-v1' and request['reference_root']==self.args.remote_reference_root
                and request['gate_kit']==self.args.remote_gate_kit,'explicitactualreference/gate namespace')
            require(pin(request_path)==row['request'] and request['image_id']==self.image_id and request['arm']==cell['arm']
                and request['cost_mode']==cell['cost_mode'] and request['entry']==ENTRY and request['timeout_sec']==3600
                and request['log_cap_bytes']==COST_CAP and request['item']==items[cell['unit']]
                and request['binding']==self.binding and request['authority_pin']==pin(self.evidence/'HOST_AUTHORITY.json'), 'exactcellrequestsourceauthority')
            require(self.path(request['authority_path'])==self.evidence/'HOST_AUTHORITY.json','exacthostauthoritypath')
            self.metadata_command(row['metadata'],self.image_id)
            require(row['metadata']['inspection']==self.authority['overlay_metadata'],'percellactualimageimmutable')
            execution=row['execution'];self.raw.execution(execution,self.image_id,'diagnostic')
            verb='simulate' if items[cell['unit']]['shape']=='single' else 'simulate-batch'
            publicargs=[verb,'--config','/input/scenario.json','--out','/output/trace.parquet'] if verb=='simulate' else [verb,'--batch-dir','/input/scenarios','--out-dir','/output']
            require(execution['effective_config']['Config']['Cmd']==['-B',ENTRY,*publicargs,'--cost-arm',cell['arm'],'--cost-mode',cell['cost_mode']],
                'actualexactprivatecostroute')
            require(execution['owner']==request['owner'] and execution['image_id']==self.image_id,'actualcellownerrequest')
            createargv=execution['commands'][0]['argv']
            cut=createargv.index(self.image_id)
            require(createargv[1:10]==['create','--env','PYTHONHASHSEED=0','--ulimit','nproc=256:256','--ulimit','fsize=268435456:268435456',
                '--entrypoint','/usr/local/bin/python'] and createargv[cut+1:]==['-B',ENTRY,*publicargs,'--cost-arm',cell['arm'],'--cost-mode',cell['cost_mode']],
                'rawactualcostcreateprefix/sourceoptions')
            mounts={m['Destination']:m['Source'] for m in execution['effective_config']['Mounts'] if m['Type']=='bind'}
            require(self.path(mounts['/input'])==folder/'input' and self.path(mounts['/output'])==folder/'output', 'exactcellonlyreadonlyinput/outputbind')
            out=self.outputs(row,items[cell['unit']],request)
            roster=self.market_input_roster(items[cell['unit']],execution,out)
            require(len(roster)==len(row['scenario_mapping']),'exactsavedinputmapping length')
            for observed,recorded in zip(roster,row['scenario_mapping']):
                for field in ('sub','scenario_id','seed','scenario_path','scenario_source','actual_trace_output'):
                    exact(observed[field],recorded[field])
                require(self.path(recorded['staged_host_path'])==Path(observed['staged_host_path'])
                    and self.path(recorded['output_host_dir'])==Path(observed['output_host_dir']),'recordedhost/containernamespacebound')
            source=self.parent_evidence/'installed/completion1009/candidates'/ARMS[cell['arm']]/'production_cli.py'
            contract=self.parser.source_contract(source.read_bytes(),cell['arm'],pin(source))
            require(request['production_source_pin']==pin(source) and request['production_source_path']==self.authority['production_source_paths'][ARMS[cell['arm']]],
                'actualsamebasesourcecontract')
            local=copy.deepcopy(execution)
            for stream in ('stdout','stderr'):
                local['attach'][stream]['path']=str(self.path(execution['attach'][stream]['path']))
            parsed_folder=self.args.out.parent/'reparsed'/label
            require(not parsed_folder.exists(),'freshindependentreparsepath')
            parsed_folder.mkdir(parents=True)
            parsed=self.parser.parse_cost_stdout(local,parsed_folder,cell['arm'],cell['cost_mode'],roster,self.binding,pin(source),contract,
                graph_audit=lambda g:self.graph_module.GraphAudit().audit(g))
            require(parsed['passed'] is True and row['parsed']['passed'] is True and len(parsed['states'])==len(row['parsed']['states']), 'rawreparseallstates')
            for field in ('schema','passed','rankable','timing_included','observation','profile','source_contract','raw_stdout','raw_stderr','failure'):
                exact(parsed[field],row['parsed'][field])
            require(set(row['parsed'])==set(parsed),'allparse resultfields exact noextras')
            for flag in ('market_executed','participant_imported','native_compiled'):
                exact(parsed[flag],row['parsed'][flag])
            for field in set(parsed)-{'states'}:
                exact(parsed[field],row['parsed'][field])
            require(read(folder/'PARSE_RESULT.json')==row['parsed'],'actualparsefile/receipt fullbytecontent')
            recordedstates={tuple(r['key']):r for r in row['parsed']['states']};new={}
            for state in parsed['states']:
                key=tuple(state['key']);old=recordedstates[key]
                actualgraph=self.path(old['path'])
                relative=Path(state['path']).relative_to(parsed_folder)
                require(actualgraph==folder/relative,'eachSTATE exactoriginalcell parserpath')
                require(pin(actualgraph)==state['pin']==old['pin'] and full_equal(actualgraph,Path(state['path'])),'everyfullrawSTATE byteequalrecorded')
                exact(state['state'],old['state'])
                exact(state['compressed_bytes'],old['compressed_bytes'])
                exact(state['graph_audit'],old['graph_audit'])
                for field in ('sub','scenario_id','seed','scenario_path','scenario_source','actual_trace_output'):
                    exact(state['mapping'][field],old['mapping'][field])
                require(self.path(old['mapping']['staged_host_path'])==Path(state['mapping']['staged_host_path'])
                    and self.path(old['mapping']['output_host_dir'])==Path(state['mapping']['output_host_dir']),'stateexplicitmappedhostdirs')
                self.graph_module.GraphAudit().audit(read(actualgraph))
                new[state['mapping']['sub']]=actualgraph;graphs+=1
            base=read(self.parent_evidence/'diagnostic'/cell['arm']/cell['unit']/'RUN_RESULT.json')
            basestates={r['sub']:self.parent_audit.path(r['path']) for r in base['state_receipts']}
            require(set(new)==set(basestates) and all(full_equal(p,basestates[s]) for s,p in new.items()),'fullSTATE equalbaseacrossmodesarms')
            self.pairs(out,self.parent_evidence/'ordinary/0'/cell['unit']/'output')
            previous=first.setdefault(cell['unit'],(out,new))
            self.pairs(out,previous[0]);require(set(new)==set(previous[1]) and all(full_equal(p,previous[1][s]) for s,p in new.items()), 'STATEcost/statebotharm equality')
            pair_receipt={'passed':True,'files':len(inventory(out)),'volatile_fields':sorted(DROP),'full_trace_ledger_bytes_equal':True}
            recomputed_comparisons.append({'arm':cell['arm'],'cost_mode':cell['cost_mode'],'unit':cell['unit'],
                'pairs':{'successful_v2_ordinary':pair_receipt,'state_cost_crossarm_output':pair_receipt},
                'successful_base_STATE_equal':True,'state_cost_crossarm_STATE_equal':True,'timing_included':False})
            parquets+=sum(n.endswith('.parquet') for n in inventory(out));gates+=len(row['developer_verifier']['verdict']['gate_results'])
        intervals=sorted(self.raw.intervals)
        require(len(intervals)==24 and len({r[2] for r in intervals})==24 and all(a[1]<b[0] for a,b in zip(intervals,intervals[1:])), '24actualuniquepositive strictlyserial')
        require((graphs,parquets,gates)==(40,80,96),'recomputed40STATE80Parquet96gate')
        comparisons=read(self.evidence/'COMPLETE_COMPARISONS.json')
        require(len(comparisons)==24 and [(r['unit'],r['arm'],r['cost_mode']) for r in comparisons]
            ==[(r['unit'],r['arm'],r['cost_mode']) for r in schedule],'completeactualcomparisonroster')
        exact(comparisons,recomputed_comparisons)
        self.report['counts'].update(diagnostic_containers=24,complete_STATE_graphs=graphs,Parquet_copies=parquets,official_gates=gates,
            ordinary=0,warmup=0,controls=0,unique_fully_decoded_Parquets=len(self.decoded))

    def host_processes(self):
        receipts=sorted(p for p in (self.evidence/'host-processes').glob('*.json') if not p.name.startswith('._'))
        expected={'cost-%02d-%s-%s'%(i,arm,mode) for i,unit in enumerate(UNITS) for arm in ARMS for mode in ('state','cost')}
        expected|={'independent-complete-base-audit','anonymous-auditedbase-pull','one-additive-overlay-build'}
        require(len(receipts)==27 and {p.stem for p in receipts}==expected,'exact24freshworker3auxprocess roster')
        pids=set()
        for path in receipts:
            row=read(path)
            require(row['creator_reaped'] is row['succeeded'] is True and row['cancelled'] is row['timed_out'] is row['hard_limit_reached'] is False
                and row['returncode']==0 and row['error'] is None and row['secondary_cleanup_errors']==[] and row['rankable'] is row['timing_included'] is False,
                'boundedreapedactualhostprocess')
            require(type(row.get('pid')) is int and row['pid']>0 and row['pid'] not in pids,'positiveuniqueprocessPID')
            pids.add(row['pid'])
            require(row.get('cleanup_grace_sec')==90 and type(row.get('timeout_sec')) is int and row['timeout_sec']>0,'finiteparentprocess bounds')
            log=row['log'];require(self.filepin(self.path(log['path']))=={k:log[k] for k in ('bytes','sha256')}
                and log['bytes']<row['per_log_file_hard_bytes'],'completeparentprocesslogpin')
            label=path.stem;argv=row['argv']
            if re.fullmatch('cost-[0-9]{2}-(parent|expectations)-(state|cost)',label):
                require(row['timeout_sec']==3900 and row['cleanup_grace_sec']==90 and row['per_log_file_hard_bytes']==COST_CAP,
                    'finitefreshworker budget')
                require(len(argv)==11 and argv[1]=='-B' and argv[2]==str(self.remote_source_root/'worker.py') and argv[3]=='--host'
                    and argv[4]==str(self.remote_source_root/'read_only/host') and argv[5]=='--worker-args'
                    and self.path(argv[6])==self.evidence/'worker-requests'/(label+'.json') and argv[7]=='--evidence'
                    and PurePosixPath(argv[8])==self.remote_root and argv[9:]==['--label',label],'exactfreshworkerroutenoextraexecution')
            elif label=='anonymous-auditedbase-pull':
                require(row['timeout_sec']==900 and row['per_log_file_hard_bytes']==LOG_CAP,'basepull900sec16MiBlog')
                require(argv==['docker','pull','--platform','linux/amd64',self.digest],'actualanonymouspublicbasepull')
            elif label=='one-additive-overlay-build':
                require(row['timeout_sec']==900 and row['per_log_file_hard_bytes']==LOG_CAP,'overlaybuild900sec16MiBlog')
                require(argv[:6]==['docker','build','--platform','linux/amd64','--pull=false','--network=none']
                    and argv[6]=='--progress=plain' and argv[7]=='-t' and re.fullmatch('t3-expectations-cost-diagnostic:[0-9a-f]{32}',argv[8])
                    and argv[9]=='-f' and self.path(argv[10])==self.evidence/'overlay-context/Dockerfile'
                    and self.path(argv[11])==self.evidence/'overlay-context','oneactualoverlaybuildnoextra')
            else:
                doc=read(self.evidence/'authority-inputs/base-authority.json')
                expected=[argv[0],'-B',str(self.remote_source_root/'read_only/frozen_saved_auditor_v1/audit_saved_delivery_v1.py'),
                    '--artifact',doc['artifact_root'],'--zip',doc['artifact_zip']['path'],'--expected-zip-sha256',doc['artifact_zip']['sha256'],
                    '--expected-zip-bytes',str(doc['artifact_zip']['bytes']),'--source',doc['source_root'],'--expected-source-pins-sha256',BASE_PINS,
                    '--expected-head',BASE_HEAD,'--expected-workflow','t3-classic-expectations-delivery-v2.yml','--remote-readback',doc['remote_source_readback']['path'],
                    '--frozen-payload',doc['frozen_payload'],'--baseline-payload',doc['baseline_payload'],'--baseline-reference-plan',doc['baseline_reference_plan']['path'],
                    '--expected-run-id',str(BASE_RUN),'--expected-run-attempt','1','--remote-evidence-marker','expectations-delivery-evidence/',
                    '--registry-readback',doc['anonymous_registry']['path'],'--out',str(self.remote_root/'base-audit-replay.json')]
                require(label=='independent-complete-base-audit' and row['timeout_sec']==2400 and row['per_log_file_hard_bytes']==LOG_CAP
                    and argv==expected,'exactactualunchangedparentaudit allargs')
        self.report['counts']['reaped_host_processes']=len(receipts)
        identities={read(p)['argv'][0] for p in receipts if p.stem.startswith('cost-') or p.stem=='independent-complete-base-audit'}
        require(len(identities)==1 and all(type(v) is str and PurePosixPath(v).is_absolute() for v in identities),'oneactualhostpython executable route')

    def summary(self):
        s=read(self.evidence/'SUMMARY.json')
        require(s['schema']=='t3-cost-stage1-host-summary-v1','exactactualcostsummaryschema')
        for field,wanted in {'actual_diagnostic_containers':24,'actual_complete_STATE_graphs':40,'actual_official_gates':96,
            'actual_Parquet_copies':80,'ordinary':0,'warmup':0,'controls':0}.items():exact(s[field],wanted)
        require(s['actual_serial_intervals']==[list(r) for r in sorted(self.raw.intervals)],'summaryactualserialintervals recomputed')
        require(s['all_passed'] is True and s['failure'] is None and s['secondary_errors']==[]
            and (s['actual_diagnostic_containers'],s['actual_complete_STATE_graphs'],s['actual_official_gates'],s['actual_Parquet_copies'])==(24,40,96,80)
            and s['ordinary']==s['warmup']==s['controls']==0 and s['rankable'] is s['official_submission'] is s['performance_usable'] is False
            and s['threshold_232000_verified'] is False and s['before_after_source_equal'] is True,'actualsummary independentlymatchescompletecounts')


def main():
    p=argparse.ArgumentParser(allow_abbrev=False)
    for name in ('artifact','zip','source','source-pins','base-artifact','base-zip','base-source','base-remote-readback',
        'frozen-payload','baseline-payload','baseline-reference-plan','registry-readback','out'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--expected-run-id',type=int,required=True);p.add_argument('--expected-head',required=True)
    p.add_argument('--expected-run-attempt',type=int,required=True)
    p.add_argument('--expected-source-pins-sha256',required=True);p.add_argument('--expected-workflow',required=True)
    p.add_argument('--expected-zip-bytes',type=int,required=True);p.add_argument('--expected-zip-sha256',required=True)
    p.add_argument('--base-zip-bytes',type=int,required=True);p.add_argument('--base-zip-sha256',required=True)
    p.add_argument('--remote-evidence-root',required=True);p.add_argument('--remote-source-root',required=True)
    p.add_argument('--remote-reference-root',required=True);p.add_argument('--remote-gate-kit',required=True)
    args=p.parse_args()
    require(not args.out.exists() and args.out.parent.is_dir(),'freshauditreportpath')
    require(args.expected_run_id>0 and args.expected_run_attempt>0 and re.fullmatch('[0-9a-f]{40}',args.expected_head)
        and re.fullmatch('[0-9a-f]{64}',args.expected_source_pins_sha256) and re.fullmatch(r'\.github/workflows/t3-[a-z0-9-]+\.yml',args.expected_workflow),
        'explicitactualcostrun/head/source/workflow')
    report={'schema':'t3-independent-cost-saved-artifact-audit-v1','all_passed':False,'ready_for_linux':False,'status':'failed',
        'failures':[],'market_executed':False,'native_compiled':False,'participant_imported':False,'process_launched':False}
    try:
        audit=Audit(args);report=audit.report
        for stage in ('zip_complete','source','parent','image','source_copies','markets','host_processes','summary'):
            getattr(audit,stage)();report['completed_stages'].append(stage)
        report['all_passed']=True;report['status']='passed'
    except BaseException as error:
        report['failures'].append({'type':type(error).__name__,'message':str(error)})
        report['all_passed']=False;report['status']='failed'
    with args.out.open('x') as stream:
        stream.write(json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'all_passed':report['all_passed'],'status':report['status'],'report':str(args.out)}))
    return 0 if report['all_passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
