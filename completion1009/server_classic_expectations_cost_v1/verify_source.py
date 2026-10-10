"""Verify the complete cost host source freeze without participant imports."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

HERE = Path(__file__).resolve().parent
CAP = 64 * 1024**2
PREFIX = 'completion1009/server_classic_expectations_cost_v1/'
ACTIVE = '.github/workflows/t3-classic-expectations-cost-v1.yml'
WORKFLOW_SOURCE = 'workflow_source_v1/t3-cost-diagnostic-hydration-draft-v1.yml'


def require(value, message):
    if not value:
        raise ValueError(message)


def source_bytes(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts
        and all(not item.is_symlink() for item in (path, *path.parents))
        and path.is_file(), 'ordinary source input before reading')
    before = path.stat()
    require(0 <= before.st_size <= CAP, 'source input size before reading')
    chunks, size = [], 0
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024**2), b''):
            size += len(block)
            require(size <= CAP, 'source input stream hard cap')
            chunks.append(block)
    after = path.stat()
    require(size == before.st_size == after.st_size
        and (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns)
        == (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns),
        'complete stable source input')
    return b''.join(chunks)


def read(path):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(source_bytes(path), object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def relative(name):
    require(type(name) is str and name, 'nonempty source path')
    path = PurePosixPath(name)
    require(path.parts and not path.is_absolute() and '..' not in path.parts and path.as_posix() == name
        and '\\' not in name and ':' not in name and '\x00' not in name
        and not any(character in name for character in ('%', '?', '#'))
        and all(ord(character) >= 32 and ord(character) != 127 for character in name)
        and not any(part.startswith('._') or part in ('__MACOSX', '__pycache__') for part in path.parts),
        'ordinary relative source path')
    return path


def pin(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts
        and all(not item.is_symlink() for item in (path, *path.parents))
        and path.is_file() and path.stat().st_size <= CAP, 'bounded ordinary source file')
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024**2), b''):
            size += len(block)
            require(size <= CAP, 'source stream hard cap')
            digest.update(block)
    require(size == path.stat().st_size, 'complete stable source size')
    return {'bytes': size, 'sha256': digest.hexdigest()}


def verify():
    document = read(HERE / 'SOURCE_PINS.json')
    require(document.get('schema') == 't3-cost-host-source-pins-v1'
        and document.get('reviewed') is document.get('ready_for_linux') is True
        and document.get('runtime_changed') is False
        and document.get('remote_prefix') == PREFIX and document.get('active_workflow') == ACTIVE
        and document.get('workflow_source') == WORKFLOW_SOURCE,
        'independent final whole source freeze required')
    files = document['files']
    require(type(files) is dict and 10 <= len(files) <= 512
        and document['workflow_source'] in files and 'SOURCE_PINS.json' not in files,
        'finite complete executing source roster')
    required = {'archive_raw_v1.py', 'INDEPENDENT_HOST_SOURCE_REVIEW_v1.json', 'driver.py', 'worker.py', 'parser.py', 'Dockerfile', 'verify_source.py', 'verify_remote_source.py',
        'overlay/cost_entry_draft_v1.py', 'overlay/IMAGE_BINDING.json', 'READ_ONLY_SOURCE_PINS_v1.json',
        'read_only/cost_saved_auditor_v1/audit_cost_saved_v1.py',
        'read_only/cost_saved_auditor_v1/archive_wrapper_draft_v1.py',
        'workflow_source_v1/hydrate_base_draft_v1.py', 'workflow_source_v1/saved_process_copy_v1.py',
        'workflow_source_v1/run_fetch_evaluation_draft_v1.py',
        'workflow_source_v1/validate_reference_hydration_draft_v1.py',
        'workflow_source_v1/validate_evaluator_hydration_v1.py',
        'workflow_source_v1/HYDRATION_SOURCE_FREEZE.json'}
    require(required <= set(files), 'all host hydration archive and audit executables must be frozen')
    for name, wanted in files.items():
        relative(name)
        require(type(wanted) is dict and set(wanted) == {'bytes', 'sha256'}
            and type(wanted['bytes']) is int and 0 <= wanted['bytes'] <= CAP
            and type(wanted['sha256']) is str and re.fullmatch('[0-9a-f]{64}', wanted['sha256']),
            'typed complete source byte pin')
        require(pin(HERE / name) == wanted, 'actual frozen source differs: ' + name)
    helpers = read(HERE / 'READ_ONLY_SOURCE_PINS_v1.json')['files']
    require(type(helpers) is dict and len(helpers) == 17
        and all(files.get(name) == wanted for name, wanted in helpers.items()),
        'all original seventeen immutable host helpers included')
    return document


if __name__ == '__main__':
    document = verify()
    require(pin(HERE.parent.parent / ACTIVE) == document['files'][document['workflow_source']],
        'independently located active workflow equals frozen HERE workflow')
    print('COMPLETE COST SOURCE FREEZE VERIFIED; NO PARTICIPANT EXECUTION')
