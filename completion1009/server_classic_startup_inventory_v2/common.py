"""Finite source and diagnostic JSON helpers; no participant dependency."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENT = 'ghcr.io/kouzhizhuo/agenthon-t3-classic@sha256:c1b3c9f2aec8d5a761b4814cfddf7b79b76eb6afd09ca6bd4558661e2ce046ba'
PREFIX = 'T3_SYSTEM_STARTUP_INVENTORY_V3 '
SOURCE_FILE_CAP = 64 * 1024**2
LOG_CAP = 16 * 1024**2


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def pin(path):
    path = Path(path)
    require(not path.is_symlink() and path.is_file() and path.stat().st_size <= SOURCE_FILE_CAP, 'ordinary finite source/log file required')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            digest.update(chunk)
    return {'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def inventory(root):
    files = {}
    for path in sorted(Path(root).rglob('*')):
        if any(part.startswith('._') or part in ('__MACOSX', '__pycache__', 'anonymous-docker-config') for part in path.parts):
            continue
        require(not path.is_symlink(), 'diagnostic/source symlink refused')
        if path.is_file():
            files[path.relative_to(root).as_posix()] = pin(path)
    return files


def verify_sources():
    pins = read(HERE / 'SOURCE_PINS.json')
    for name, expected in pins['files'].items():
        require(pin(HERE / name) == expected, 'frozen source bytes changed: ' + name)
    lock = read(HERE / 'SOURCE_LOCK.json')
    require(lock['parent_image'] == PARENT and pin(HERE / 'startupinventory.py') == lock['inventory_source'], 'exact reviewed inventory and public digest required')
    require({name: pin(HERE / 'host' / name) for name in ('verify_public.py', 'verify_linux.py')} == lock['unchanged_host_sources'], 'unchanged bounded host2 required')
    return lock
