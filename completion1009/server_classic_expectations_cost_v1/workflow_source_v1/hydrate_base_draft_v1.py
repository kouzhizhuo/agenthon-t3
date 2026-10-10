"""Proposed remote saved-data hydration. No participant/image/native execution.

Main is blocked until a future independent hydration source freeze is present.
No network call runs while importing or inspecting this draft.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
DATA = HERE / 'bound_data'
REPO = 'kouzhizhuo/agenthon-t3'
RUN = 38072276259
HEAD = '2164738b7508d9554cb6bd0a37ec46375cee8199'
ARTIFACT_ID = 11678266765
ARTIFACT_NAME = 't3-classic-expectations-delivery-v2-evidence'
ZIP_PIN = {'bytes': 460347550, 'sha256': '0a508bd785f6e369cef32a96fb5c138976b3ef63cebfc1ca93fbabb7f60f96f3'}
V2_PREFIX = 'completion1009/server_classic_expectations_delivery_v2/'
V7_HEAD = '9e2d6d27e1773c564346d2b137c7b06d3ae3fd1c'
V7_PREFIX = 'completion1009/server_classic_structural_v3/'
IMAGE = 'ghcr.io/kouzhizhuo/agenthon-t3-classic@sha256:4a4c10b274a54312d5e17d69a45d30052787f523813bd5e2c27a5f1a9ba34ec9'
IMAGE_ID = 'sha256:4deb411785eb962b62d1f1cf644f9349bc20cdb69d3f31832151721f0e3584b1'
SOURCE_CAP = 64 * 1024**2
LOG_CAP = 16 * 1024**2
MAX_MEMBERS = 40000
MAX_EXTRACTED = 64 * 1024**3
API = 'https://api.github.com/repos/' + REPO + '/actions/artifacts/' + str(ARTIFACT_ID)
RAW = 'https://raw.githubusercontent.com/' + REPO + '/'
DEADLINE = None
CANCELLED = None


def check_budget():
    if CANCELLED is not None:raise InterruptedError('hydration cancelled')
    require(DEADLINE is None or time.monotonic() < DEADLINE, 'finite hydration phase deadline')


def cancellation(number, frame):
    global CANCELLED
    CANCELLED = number
    raise InterruptedError('hydration signal ' + str(number))


def require(value, message):
    if not value:
        raise ValueError(message)


def read(path):
    def pairs(rows):
        value = {}
        for key, item in rows:
            require(key not in value, 'duplicate JSON key')
            value[key] = item
        return value
    return json.loads(Path(path).read_bytes(), object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def pin(path, cap=SOURCE_CAP):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and 0 <= path.stat().st_size <= cap, 'bounded regular file')
    digest, count = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            count += len(block);require(count <= cap, 'bounded full file stream')
            digest.update(block)
    require(count == path.stat().st_size, 'full stable file size')
    return {'bytes': count, 'sha256': digest.hexdigest()}


def validate_source_freeze():
    """One closure for both CLIs and each saved manager import."""
    path = HERE / 'HYDRATION_SOURCE_FREEZE.json'
    require(path.is_file(), 'draft blocked: final independent hydration source freeze absent')
    freeze = read(path)
    required = {'hydrate_base_draft_v1.py', 'saved_process_copy_v1.py', 'run_fetch_evaluation_draft_v1.py',
        'validate_reference_hydration_draft_v1.py', 'validate_evaluator_hydration_v1.py',
        't3-cost-diagnostic-hydration-draft-v1.yml', 'bound_data/COPIED_DATA_PINS_v1.json'}
    files = freeze.get('files')
    require(type(files) is dict and required.issubset(files)
        and freeze.get('reviewed') is freeze.get('ready_for_linux') is True, 'complete independently frozen hydration source')
    for name, wanted in files.items():
        relative = PurePosixPath(name)
        require(type(name) is str and relative.as_posix() == name and not relative.is_absolute() and '..' not in relative.parts
            and '\\' not in name and ':' not in name and '\x00' not in name
            and not any(part.startswith('._') or part in ('__MACOSX', '__pycache__') for part in relative.parts)
            and type(wanted) is dict and set(wanted) == {'bytes', 'sha256'} and type(wanted['bytes']) is int
            and 0 <= wanted['bytes'] <= SOURCE_CAP and type(wanted['sha256']) is str
            and re.fullmatch('[0-9a-f]{64}', wanted['sha256']), 'safe typed final hydration member')
        require(pin(ordinary(HERE / name)) == wanted, 'every final hydration member exact bytes')
    data_pins = read(HERE / 'bound_data/COPIED_DATA_PINS_v1.json')['files']
    require({'ORIGINAL_REFERENCE_PLAN.json', 'V2_ORIGINAL_FULL_AUDIT.json', 'V2_REMOTE_SOURCE_READBACK.json',
        'V2_SOURCE_PINS.json', 'V7_SOURCE_PINS.json', 'V7_REMOTE_SOURCE_READBACK.json', 'V2_EVALUATOR_FREEZE.txt',
        'V2_ORIGINAL_REGISTRY_READBACK.json'} == set(data_pins)
        and all(files.get('bound_data/' + name) == {key: wanted[key] for key in ('bytes', 'sha256')}
            for name, wanted in data_pins.items()), 'all8 original copied data files in the same source freeze')
    return freeze


def write(path, value):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as output:output.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def ordinary(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts and all(not item.is_symlink() for item in (path, *path.parents)),
        'absolute ordinary path without symlink ancestors')
    return path


def url_allowed(url):
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == 'https' and parsed.username is parsed.password is None and parsed.port in (None, 443)
        and not parsed.fragment,
        'HTTPS ordinary network endpoint')
    return parsed


class ArtifactRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        parsed = url_allowed(url)
        require(parsed.hostname in ('api.github.com', 'objects.githubusercontent.com') or re.fullmatch(
            r'productionresultssa[0-9]+\.blob\.core\.windows\.net', parsed.hostname or ''), 'explicit GitHub artifact redirect host')
        redirected = super().redirect_request(request, fp, code, message, headers, url)
        if urllib.parse.urlsplit(request.full_url).netloc != parsed.netloc:
            redirected.remove_header('Authorization')
        return redirected


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        raise ValueError('immutable raw source redirects refused')


def download(opener, url, target, wanted, headers=None, cap=SOURCE_CAP):
    """Bounded complete fresh file, token/URL never persisted or printed."""
    url_allowed(url)
    target = ordinary(target)
    require(not target.exists() and not target.is_symlink() and target.parent.is_dir()
        and wanted['bytes'] <= cap, 'fresh bounded network destination')
    record = {'completed': False, 'expected': wanted, 'token_saved_or_printed': False, 'signed_url_saved_or_printed': False}
    digest, count = hashlib.sha256(), 0
    try:
        check_budget()
        with opener.open(urllib.request.Request(url, headers=headers or {}), timeout=60) as response, target.open('xb') as output:
            require(response.status == 200 and (response.headers.get('Content-Length') is None
                or int(response.headers['Content-Length']) == wanted['bytes']), 'exact200 declared complete file size')
            for block in iter(lambda: response.read(1024**2), b''):
                check_budget()
                count += len(block);require(count <= wanted['bytes'] <= cap, 'finite streamed network bytes')
                digest.update(block);output.write(block)
            record.update(status=response.status, final_host=urllib.parse.urlsplit(response.url).hostname)
        require({'bytes': count, 'sha256': digest.hexdigest()} == pin(target, cap) == wanted, 'whole received file exact pinned bytes')
        record.update(completed=True, actual=wanted)
        return record
    except BaseException as error:
        # HTTP exception text/context can contain a signed redirect URL.
        raise RuntimeError('Hydration download did not pass; retained bytes; details suppressed (' + type(error).__name__ + ')') from None


def api_metadata(opener, token):
    try:
        check_budget()
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
        with opener.open(urllib.request.Request(API, headers=headers), timeout=60) as response:
            require(response.status == 200, 'actual artifact metadata200')
            data = response.read(1024**2 + 1);require(len(data) <= 1024**2, 'bounded metadata JSON')
        value = json.loads(data)
        require(value['id'] == ARTIFACT_ID and type(value['id']) is int and value['name'] == ARTIFACT_NAME
            and value['expired'] is False and value['workflow_run']['id'] == RUN and type(value['workflow_run']['id']) is int
            and value['size_in_bytes'] == ZIP_PIN['bytes'] and type(value['size_in_bytes']) is int
            and value['workflow_run']['head_sha'] == HEAD and value.get('digest') == 'sha256:' + ZIP_PIN['sha256'],
            'actual GitHub artifact id/run/head/digest metadata exact')
        return {key: value[key] for key in ('id', 'name', 'expired', 'digest')} | {'run_id': RUN, 'head': HEAD}
    except BaseException as error:
        raise RuntimeError('Artifact metadata authority failed (' + type(error).__name__ + '); details suppressed') from None


def safe_zip_member(item):
    path = PurePosixPath(item.filename)
    require(item.filename and not path.is_absolute() and '..' not in path.parts and '\\' not in item.filename
        and '\x00' not in item.filename and ':' not in item.filename and path.as_posix() == item.filename.rstrip('/')
        and not any(part.startswith('._') or part in ('__MACOSX', '__pycache__') for part in path.parts), 'safe ordinary ZIP member name')
    mode = item.external_attr >> 16;kind = stat.S_IFMT(mode)
    require(kind in (0, stat.S_IFREG, stat.S_IFDIR) and not mode & (stat.S_ISUID | stat.S_ISGID)
        and ((item.is_dir() and kind in (0, stat.S_IFDIR)) or (not item.is_dir() and kind in (0, stat.S_IFREG)))
        and not item.flag_bits & 1 and (not item.is_dir() or item.file_size == 0), 'ordinary ZIP member type/no encryption')
    return path


def extract_zip(path, destination):
    require(pin(path, 8 * 1024**3) == ZIP_PIN and not destination.exists(), 'exact full original ZIP and fresh extraction')
    records, total = {}, 0
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist();names = [safe_zip_member(item).as_posix() for item in members]
        require(len(members) == 4953 and len(names) == len(set(names))
            and all(type(item.file_size) is int and 0 <= item.file_size <= 4 * 1024**3 for item in members)
            and sum(item.file_size for item in members) <= MAX_EXTRACTED
            and archive.testzip() is None, 'actual complete4953 ZIP roster/CRC/64GiBcap')
        files = {name for name, item in zip(names, members) if not item.is_dir()}
        require(all(not any(parent.as_posix() in files for parent in PurePosixPath(name).parents) for name in names), 'no file-as-parent ZIP collision')
        destination.mkdir()
        for item, name in zip(members, names):
            target = destination / name
            if item.is_dir():target.mkdir(parents=True, exist_ok=True);continue
            target.parent.mkdir(parents=True, exist_ok=True)
            digest, size = hashlib.sha256(), 0
            with archive.open(item) as source, target.open('xb') as output:
                for block in iter(lambda: source.read(1024**2), b''):
                    size += len(block);total += len(block)
                    require(size <= item.file_size <= 4 * 1024**3 and total <= MAX_EXTRACTED, 'bounded decoded original member')
                    digest.update(block);output.write(block)
            require(pin(target, 4 * 1024**3) == {'bytes': size, 'sha256': digest.hexdigest()} and size == item.file_size,
                'complete extracted member byte equality')
            records[name] = {'bytes': size, 'sha256': digest.hexdigest()}
    return records


def source_tree(root, head, prefix, pins_name, remote_name):
    require((head, prefix, pins_name, remote_name) in (
        (HEAD, V2_PREFIX, 'V2_SOURCE_PINS.json', 'V2_REMOTE_SOURCE_READBACK.json'),
        (V7_HEAD, V7_PREFIX, 'V7_SOURCE_PINS.json', 'V7_REMOTE_SOURCE_READBACK.json')),
        'only two explicit genuine source/head/pin/readback combinations')
    source = root / ('server_classic_expectations_delivery_v2' if head == HEAD else 'server_classic_structural_v3')
    source.mkdir()
    pins = read(DATA / pins_name)
    require(len(pins['files']) == (22 if head == HEAD else 18), 'entire exact frozen HERE source file roster')
    raw = urllib.request.build_opener(NoRedirect())
    checks = []
    expected = dict(pins['files']);expected['SOURCE_PINS.json'] = pin(DATA / pins_name)
    for name, wanted in expected.items():
        check_budget()
        relative = PurePosixPath(name)
        require(type(name) is str and not relative.is_absolute() and '..' not in relative.parts and relative.as_posix() == name
            and '\\' not in name and ':' not in name and '\x00' not in name
            and not any(part.startswith('._') or part in ('__MACOSX', '__pycache__') for part in relative.parts)
            and type(wanted) is dict and set(wanted) == {'bytes', 'sha256'} and type(wanted['bytes']) is int
            and 0 <= wanted['bytes'] <= SOURCE_CAP and re.fullmatch('[0-9a-f]{64}', wanted['sha256']), 'safe typed frozen HERE source member')
        target = source / name;target.parent.mkdir(parents=True, exist_ok=True)
        row = download(raw, RAW + head + '/' + prefix + name, target, wanted)
        checks.append({'path': prefix + name, 'expected': wanted, 'actual': row['actual'], 'passed': True})
    workflow = [name for name in pins['files'] if name.endswith('.yml')]
    require(len(workflow) == 1, 'single pinned independent active workflow')
    active = root / (head + '-active.yml')
    row = download(raw, RAW + head + '/.github/workflows/' + workflow[0], active, pins['files'][workflow[0]])
    checks.append({'path': '.github/workflows/' + workflow[0], 'expected': row['expected'], 'actual': row['actual'], 'passed': True})
    write(source / 'FRESH_REMOTE_READBACK.json', {'head': head, 'all_passed': True, 'checks': checks,
        'participant_imported': False, 'remote_writes': False, 'workflow_dispatch': False})
    shutil.copyfile(DATA / remote_name, source / 'ORIGINAL_REMOTE_READBACK.json')
    require(read(source / 'ORIGINAL_REMOTE_READBACK.json')['head'] == head, 'carried original exact remote readback head')
    return source


def materialize(archive_path, output, expected_files, wanted):
    """Read inert source tar with the original source manifest contract."""
    require(pin(archive_path) == wanted and not output.exists(), 'full pinned source archive before fresh materialization')
    with tarfile.open(archive_path, 'r:xz') as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        require(len(members) <= 768 and sum(member.size for member in members) <= 48 * 1024**2
            and len(names) == len(set(names)), 'finite complete source tar roster')
        for member in members:
            name = PurePosixPath(member.name)
            require(member.isfile() and not name.is_absolute() and '..' not in name.parts and name.as_posix() == member.name
                and '\\' not in member.name and ':' not in member.name and '\x00' not in member.name
                and not any(part.startswith('._') or part in ('__MACOSX', '__pycache__') for part in name.parts)
                and not member.mode & (stat.S_ISUID | stat.S_ISGID)
                and type(member.size) is int and 0 <= member.size <= SOURCE_CAP, 'ordinary bounded tar source member')
        require(not any(any(parent.as_posix() in names for parent in PurePosixPath(name).parents) for name in names), 'source tar file parent collision')
        output.mkdir()
        for member in members:
            target = output / member.name;target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open('xb') as dest:
                shutil.copyfileobj(source, dest, 1024**2)
            require(target.stat().st_size == member.size, 'complete source member size')
    actual = {path.relative_to(output).as_posix(): pin(path) for path in output.rglob('*') if path.is_file()}
    manifest = read(output / 'STRUCTURAL_MANIFEST.json')['files'];actual.pop('STRUCTURAL_MANIFEST.json')
    require(len(actual) == expected_files and actual == manifest, 'entire source materialization equals frozen manifest')
    return actual


def audit_command(root, host, registry, out):
    return [sys.executable, '-B', str(host / 'read_only/frozen_saved_auditor_v1/audit_saved_delivery_v1.py'),
        '--artifact', str(root / 'extracted'), '--zip', str(root / 'artifact.zip'), '--expected-zip-sha256', ZIP_PIN['sha256'],
        '--expected-zip-bytes', str(ZIP_PIN['bytes']), '--source', str(root / 'sources/server_classic_expectations_delivery_v2'),
        '--expected-source-pins-sha256', pin(DATA / 'V2_SOURCE_PINS.json')['sha256'], '--expected-head', HEAD,
        '--expected-workflow', 't3-classic-expectations-delivery-v2.yml', '--remote-readback',
        str(root / 'sources/server_classic_expectations_delivery_v2/FRESH_REMOTE_READBACK.json'),
        '--frozen-payload', str(root / 'payload-v2'), '--baseline-payload', str(root / 'payload-v7'),
        '--baseline-reference-plan', str(root / 'ORIGINAL_REFERENCE_PLAN.json'), '--expected-run-id', str(RUN),
        '--expected-run-attempt', '1', '--remote-evidence-marker', 'expectations-delivery-evidence/',
        '--registry-readback', str(registry), '--out', str(out)]


def saved_process(command, root, label, seconds, deadline):
    """Use the separately pinned unchanged reviewed host manager body."""
    require(sys.platform.startswith('linux'), 'actual Linux saved process only')
    freeze = validate_source_freeze()
    manager = HERE / 'saved_process_copy_v1.py'
    require(pin(manager) == freeze['files']['saved_process_copy_v1.py'], 'manager exact pin immediately before inert module load')
    spec = importlib.util.spec_from_file_location('t3_inert_saved_process_manager_v1', manager)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    class Cancellation:
        @staticmethod
        def check_cancelled():
            check_budget()
    from types import SimpleNamespace
    args = SimpleNamespace(evidence=root, deadline=deadline)
    return module.run_saved_process(args, Cancellation, command, label, seconds, cap=LOG_CAP)


def main():
    global DEADLINE
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--host', type=Path, required=True)
    parser.add_argument('--phase', choices=('download-sources', 'registry-and-authority'), required=True)
    args = parser.parse_args()
    root, host = ordinary(args.root), ordinary(args.host)
    deadline = time.monotonic() + 5400
    DEADLINE = deadline
    signal.signal(signal.SIGINT, cancellation);signal.signal(signal.SIGTERM, cancellation)
    freeze = validate_source_freeze()
    original_freeze = host / 'read_only/frozen_saved_auditor_v1/AUDITOR_FREEZE_v1.json'
    require(pin(original_freeze) == {'bytes': 2399, 'sha256': 'be949e80178c57c0dc0fb261244fb0927231d13dceeb68d426b2380040fda807'},
        'original independent saved auditor freeze byte authority')
    frozen = read(original_freeze)
    require(all(pin(host / 'read_only/frozen_saved_auditor_v1' / name) == wanted for name, wanted in frozen['files'].items()),
        'all original frozen saved auditor source bytes')
    if args.phase == 'download-sources':
        require(not root.exists() and root.parent.is_dir(), 'fresh actual remote hydration root')
        root.mkdir()
        token = os.environ.get('GITHUB_TOKEN', '')
        require(bool(token) and '\n' not in token and '\r' not in token, 'environment-only Actions read token required')
        opener = urllib.request.build_opener(ArtifactRedirect())
        metadata = api_metadata(opener, token)
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
        row = download(opener, API + '/zip', root / 'artifact.zip', ZIP_PIN, headers, 8 * 1024**3)
        del token, headers
        files = extract_zip(root / 'artifact.zip', root / 'extracted')
        sources = root / 'sources';sources.mkdir()
        v2 = source_tree(sources, HEAD, V2_PREFIX, 'V2_SOURCE_PINS.json', 'V2_REMOTE_SOURCE_READBACK.json')
        v7 = source_tree(sources, V7_HEAD, V7_PREFIX, 'V7_SOURCE_PINS.json', 'V7_REMOTE_SOURCE_READBACK.json')
        require(pin(v2 / 'DELIVERY_PAYLOAD_v3.tar.xz') == {'bytes': 193928, 'sha256': '1af7ba6d1b79f1934599ad7c385ee3d4f1d0d46138fb0e5137a9eec06e49bf73'}, 'actual small v2 payload exact')
        materialize(v2 / 'DELIVERY_PAYLOAD_v3.tar.xz', root / 'payload-v2', 193,
            read(DATA / 'V2_SOURCE_PINS.json')['files']['DELIVERY_PAYLOAD_v3.tar.xz'])
        materialize(v7 / 'SCREEN_PAYLOAD_v7.tar.xz', root / 'payload-v7', 305,
            read(DATA / 'V7_SOURCE_PINS.json')['files']['SCREEN_PAYLOAD_v7.tar.xz'])
        for name in ('ORIGINAL_REFERENCE_PLAN.json', 'V2_ORIGINAL_FULL_AUDIT.json', 'V2_ORIGINAL_REGISTRY_READBACK.json'):
            shutil.copyfile(DATA / name, root / name)
        write(root / 'HYDRATION_DOWNLOAD.json', {'schema': 't3-cost-genuine-base-hydration-v1', 'metadata': metadata,
            'archive': row, 'archive_member_count': len(files), 'base_run': RUN, 'base_head': HEAD,
            'cost_run_id': None, 'cost_head': None, 'participant_imported': False, 'native_compiled': False,
            'token_saved_or_printed': False, 'signed_url_saved_or_printed': False})
    else:
        require(pin(root / 'artifact.zip', 8 * 1024**3) == ZIP_PIN and read(root / 'HYDRATION_DOWNLOAD.json')['base_head'] == HEAD,
            'complete actual hydrated artifact before registry authority')
        # Original frozen registry reader obtains an anonymous pull-scope token,
        # strips credentials on redirects, and retains all20layers/18unique blobs.
        reader = host / 'read_only/frozen_saved_auditor_v1/read_public_registry_bytes_v1.py'
        require(pin(reader) == {'bytes': 10916, 'sha256': '1bbce2cb72fc2dcd0feee6e1221038a83e918e2812f50e217ca33c3f5cdf2dc5'}, 'original frozen registry reader exact')
        registry_process = saved_process([sys.executable, '-B', str(reader), '--image', IMAGE,
            '--tested-image-id', IMAGE_ID, '--out-dir', str(root / 'registry')], root, 'registry-byte-reader', 2400, deadline)
        registry = root / 'registry/REGISTRY_BYTE_READBACK_v1.json'
        value = read(registry)
        require(value['all_passed'] is True and value['anonymous'] is True and value['image'] == IMAGE
            and value['tested_image_id'] == IMAGE_ID and len(value['layers']) == 20
            and len({layer['sha256'] for layer in value['layers']}) == 18, 'complete exact actual manifest layer roster')
        fresh = root / 'FRESH_FULL_AUDIT.json'
        audit_process = saved_process(audit_command(root, host, registry, fresh), root, 'full-base-audit', 2400, deadline)
        report = read(fresh)
        require(report['all_passed'] is report['all_execution_checks_passed'] is report['publication_passed'] is True
            and report['failures'] == report['pending'] == [] and report['authority']['public_image'] == IMAGE
            and report['authority']['artifact'] == ZIP_PIN, 'fresh complete frozen original saved replay')
        def bound(path):return {'path': str(path), **pin(path, 8 * 1024**3)}
        document = {'schema': 't3-cost-actual-base-authority-v1', 'ready_for_linux': True, 'run_id': RUN, 'run_attempt': 1,
            'head': HEAD, 'workflow': 't3-classic-expectations-delivery-v2.yml', 'sourcepins_sha256': pin(DATA / 'V2_SOURCE_PINS.json')['sha256'],
            'base_image_id': IMAGE_ID, 'public_digest': IMAGE, 'artifact_zip': bound(root / 'artifact.zip'),
            'artifact_root': str(root / 'extracted'), 'source_root': str(root / 'sources/server_classic_expectations_delivery_v2'),
            'saved_audit': bound(fresh), 'anonymous_registry': bound(registry),
            'remote_source_readback': bound(root / 'sources/server_classic_expectations_delivery_v2/FRESH_REMOTE_READBACK.json'),
            'frozen_payload': str(root / 'payload-v2'), 'baseline_payload': str(root / 'payload-v7'),
            'baseline_reference_plan': bound(root / 'ORIGINAL_REFERENCE_PLAN.json')}
        write(root / 'REMOTE_BASE_AUTHORITY.json', document)
        write(root / 'FRESH_HYDRATION_CHECKS.json', {'schema': 't3-cost-fresh-hydration-namespace-checks-v1',
            'fresh_full_audit': bound(fresh), 'fresh_remote_source_readback': bound(root / 'sources/server_classic_expectations_delivery_v2/FRESH_REMOTE_READBACK.json'),
            'original_public_receipts_preserved': True, 'fresh_registry_receipt_has_new_request_times': True,
            'fresh_registry_report_pin_equals_original_report': False, 'same_manifest_config_and_all_layer_bytes_required': True,
            'cost_run_id': None, 'cost_head': None, 'cost_dispatch_allowed': False})
        write(root / 'SAVED_HYDRATION_PROCESSES.json', {'registry': registry_process, 'audit': audit_process,
            'cost_diagnostic_executed': False, 'native_compiled': False, 'participant_executed': False})
    print(json.dumps({'phase': args.phase, 'base_run': RUN, 'base_head': HEAD, 'cost_ready': False,
        'participant_imported': False, 'native_compiled': False}))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        # A source/network failure never turns into a fabricated completed base.
        try:
            arguments = sys.argv[1:]
            index = arguments.index('--root')
            folder = ordinary(Path(arguments[index + 1]))
            if folder.is_dir() and not (folder / 'HYDRATION_FAILURE.json').exists():
                retained = []
                for name in ('artifact.zip', 'HYDRATION_DOWNLOAD.json', 'FRESH_FULL_AUDIT.json'):
                    path = folder / name
                    if path.is_file() and not path.is_symlink():retained.append({'path': name, **pin(path, 8 * 1024**3)})
                write(folder / 'HYDRATION_FAILURE.json', {'schema': 't3-cost-hydration-failure-v1',
                    'failure_type': type(error).__name__, 'message': 'Source/base hydration did not complete; retained bytes require independent audit.',
                    'cancelled': CANCELLED is not None or isinstance(error, (InterruptedError, KeyboardInterrupt)), 'retained': retained,
                    'base_run': RUN, 'base_head': HEAD, 'cost_run_id': None, 'cost_head': None,
                    'source': pin(Path(__file__)), 'token_saved_or_printed': False, 'signed_url_saved_or_printed': False,
                    'native_compiled': False, 'participant_executed': False, 'all_passed': False})
        except BaseException:
            pass
        raise RuntimeError('Hydration incomplete (' + type(error).__name__ + '); details suppressed') from None
