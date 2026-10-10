"""Read the complete frozen cost sources and independent workflow at one head."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import re
import time
import urllib.request

HERE = Path(__file__).resolve().parent
RAW = 'https://raw.githubusercontent.com/kouzhizhuo/agenthon-t3/'
CAP = 64 * 1024**2


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        raise ValueError('immutable raw source redirects refused')


def source_bytes(path):
    path = Path(path)
    if (not path.is_absolute() or '..' in path.parts
            or any(item.is_symlink() for item in (path, *path.parents)) or not path.is_file()):
        raise ValueError('ordinary source input before host import')
    before = path.stat()
    if not 0 <= before.st_size <= CAP:
        raise ValueError('source input size before host import')
    chunks, size = [], 0
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024**2), b''):
            size += len(block)
            if size > CAP:
                raise ValueError('host source input stream hard cap')
            chunks.append(block)
    after = path.stat()
    if (size != before.st_size or size != after.st_size
            or (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns)):
        raise ValueError('complete stable host source input')
    return b''.join(chunks)


def read(path):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError('duplicate source freeze JSON key')
            result[key] = value
        return result
    return json.loads(source_bytes(path), object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite source freeze JSON')))


def fetch(opener, head, path, wanted, deadline):
    if type(head) is not str or re.fullmatch('[0-9a-f]{40}', head) is None or type(path) is not str:
        raise ValueError('exact committed head and ordinary raw source path')
    relative = PurePosixPath(path)
    if (not relative.parts or relative.is_absolute() or '..' in relative.parts or relative.as_posix() != path
            or any(character in path for character in ('\\', ':', '\x00', '%', '?', '#'))
            or any(ord(character) < 32 or ord(character) == 127 for character in path)
            or any(part.startswith('._') or part in ('__MACOSX', '__pycache__') for part in relative.parts)):
        raise ValueError('canonical ordinary raw source path')
    if (type(wanted) is not dict or set(wanted) != {'bytes', 'sha256'} or type(wanted['bytes']) is not int
            or not 0 <= wanted['bytes'] <= CAP or type(wanted['sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}', wanted['sha256']) is None
            or type(deadline) not in (int, float) or not math.isfinite(deadline)):
        raise ValueError('typed finite exact source pin and deadline')
    if time.monotonic() >= deadline:
        raise ValueError('whole source readback deadline')
    digest, count = hashlib.sha256(), 0
    url = RAW + head + '/' + path
    with opener.open(url, timeout=min(60, max(0.001, deadline - time.monotonic()))) as response:
        if (response.status != 200 or response.geturl() != url
                or (response.headers.get('Content-Length') is not None
                    and int(response.headers['Content-Length']) != wanted['bytes'])):
            raise ValueError('raw source HTTP200 required')
        for block in iter(lambda: response.read(1024**2), b''):
            count += len(block)
            if count > wanted['bytes'] or count > CAP or time.monotonic() >= deadline:
                raise ValueError('bounded complete raw source stream')
            digest.update(block)
        if time.monotonic() >= deadline:
            raise ValueError('whole source readback deadline after EOF')
    actual = {'bytes': count, 'sha256': digest.hexdigest()}
    if actual != wanted:
        raise ValueError('remote exact source bytes differ: ' + path)
    return actual


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--head', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if (not re.fullmatch('[0-9a-f]{40}', args.head) or not args.out.is_absolute()
            or '..' in args.out.parts or args.out.exists() or not args.out.parent.is_dir()
            or any(item.is_symlink() for item in (args.out, *args.out.parents))):
        raise ValueError('one exact committed head and fresh ordinary output required')
    # The verifier is host-only; no participant or runtime imports occur.
    data = source_bytes(HERE / 'verify_source.py')
    freeze = read(HERE / 'SOURCE_PINS.json')
    if {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()} != freeze['files']['verify_source.py']:
        raise ValueError('exact frozen source verifier required before inert host import')
    spec = importlib.util.spec_from_file_location('t3_cost_source_verifier', HERE / 'verify_source.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    document = verifier.verify()
    expected = {document['remote_prefix'] + name: wanted for name, wanted in document['files'].items()}
    expected[document['remote_prefix'] + 'SOURCE_PINS.json'] = verifier.pin(HERE / 'SOURCE_PINS.json')
    expected[document['active_workflow']] = document['files'][document['workflow_source']]
    report = {'schema': 't3-complete-cost-same-head-readback-v1', 'head': args.head, 'all_passed': False,
        'checks': [], 'remote_writes': False, 'workflow_dispatch': False, 'participant_imported': False}
    try:
        opener = urllib.request.build_opener(NoRedirect())
        deadline = time.monotonic() + 1800
        for path, wanted in expected.items():
            actual = fetch(opener, args.head, path, wanted, deadline)
            report['checks'].append({'path': path, 'expected': wanted, 'actual': actual, 'passed': True})
        report['all_passed'] = True
    except BaseException as error:
        report['failure'] = {'type': type(error).__name__, 'message': 'Complete immutable raw source readback failed; retained passing rows; no dispatch'}
    finally:
        with args.out.open('x') as output:
            output.write(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n')
    if not report['all_passed']:
        raise ValueError('complete exact one-head readback failed; no dispatch')
    print('EVERY COST HERE PATH PLUS DISTINCT ACTIVE WORKFLOW VERIFIED AT ONE HEAD')


if __name__ == '__main__':
    main()
