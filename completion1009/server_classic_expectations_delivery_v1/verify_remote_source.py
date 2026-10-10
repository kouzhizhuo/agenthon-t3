"""Read back every HERE source plus distinct active workflow at one exact head."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.request

HERE = Path(__file__).resolve().parent
REMOTE = 'https://raw.githubusercontent.com/kouzhizhuo/agenthon-t3/'
DIRECTORY = 'completion1009/server_classic_expectations_delivery_v1/'
WORKFLOW = 't3-classic-expectations-delivery-v1.yml'


def fetch(head, path):
    with urllib.request.urlopen(REMOTE + head + '/' + path, timeout=60) as response:
        return response.read(64 * 1024**2 + 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--head', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if re.fullmatch(r'[0-9a-f]{40}', args.head) is None or args.out.exists():
        raise ValueError('one exact committed Git head and fresh review output required')
    pins = json.loads((HERE / 'SOURCE_PINS.json').read_bytes())
    report = {'head': args.head, 'all_passed': False, 'checks': [], 'remote_writes': False,
        'workflow_dispatch': False, 'participant_imported': False}
    try:
        # Enumerate every original HERE path first. Never map/alias the pinned
        # workflow into .github; it exists independently at both locations.
        expected = dict(pins['files'])
        data = (HERE / 'SOURCE_PINS.json').read_bytes()
        expected['SOURCE_PINS.json'] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        for name, pin in expected.items():
            path = DIRECTORY + name
            actual = fetch(args.head, path)
            observed = {'bytes': len(actual), 'sha256': hashlib.sha256(actual).hexdigest()}
            report['checks'].append({'path': path, 'expected': pin, 'actual': observed, 'passed': observed == pin})
            if observed != pin:
                raise ValueError('remote exact HERE source differs: ' + path)
        active = '.github/workflows/' + WORKFLOW
        actual = fetch(args.head, active)
        observed = {'bytes': len(actual), 'sha256': hashlib.sha256(actual).hexdigest()}
        report['checks'].append({'path': active, 'expected': pins['files'][WORKFLOW],
            'actual': observed, 'passed': observed == pins['files'][WORKFLOW]})
        if observed != pins['files'][WORKFLOW]:
            raise ValueError('distinct active workflow must also match HERE pin')
        report['all_passed'] = True
    except BaseException as error:
        report['failure'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        args.out.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    if not report['all_passed']:
        raise ValueError('complete one-head remote readback failed; no dispatch')
    print('EVERY HERE PATH PLUS DISTINCT ACTIVE WORKFLOW VERIFIED AT ONE COMMITTED HEAD; no dispatch')


if __name__ == '__main__':
    main()
