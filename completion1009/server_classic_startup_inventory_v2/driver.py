"""Pull one immutable public image and run one separate startup inventory."""
import argparse
import os
from pathlib import Path
import platform
import signal
import sys
import uuid

from common import HERE, LOG_CAP, PARENT, read, require, verify_sources, write


def stock(args, linux):
    commands = linux.DockerCommands(args.docker, args.evidence / 'parent-pull-commands', LOG_CAP)
    anonymous = args.evidence / 'anonymous-docker-config'
    anonymous.mkdir()
    previous = os.environ.get('DOCKER_CONFIG')
    os.environ['DOCKER_CONFIG'] = str(anonymous)
    try:
        pulled = commands.call(['pull', '--platform', 'linux/amd64', PARENT], 'anonymous-parent-pull', 900)
    finally:
        if previous is None:
            os.environ.pop('DOCKER_CONFIG', None)
        else:
            os.environ['DOCKER_CONFIG'] = previous
    require(pulled['succeeded'] is True, 'complete anonymous public digest pull required')
    parent = linux.image_metadata(args, PARENT, args.evidence / 'parent-metadata')
    write(args.evidence / 'PARENT_METADATA.json', parent)
    require(PARENT in parent['inspection']['RepoDigests'], 'actual image bound to exact published digest')
    write(args.evidence / 'STOCK_READY.json', {'schema': 't3-fixed-stock-startup-ready-v2', 'image_id': parent['id'],
        'digest': PARENT, 'parent_metadata': parent, 'stock_image_unchanged': True,
        'market_executed': False, 'participant_imported': False, 'native_compiled': False, 'timing_included': False, 'rankable': False})


def startup(args, linux):
    ready = read(args.evidence / 'STOCK_READY.json')
    require(ready['digest'] == PARENT, 'one exact published stock image')
    image = ready['image_id']
    before = linux.image_metadata(args, image, args.evidence / 'stock-before-startup')
    write(args.evidence / 'BEFORE_METADATA.json', before)
    request = args.evidence / 'requests/stock-startup.json'
    result = args.evidence / 'worker-results/stock-startup.json'
    write(request, {'image_id': image, 'input_path': str(HERE / 'startupinventory.py'),
        'owner': uuid.uuid4().hex, 'folder': str(args.evidence / 'stock-startup')})
    # The unchanged bounded host runner anchors/reaps this exact worker group,
    # writes independent16MiB logs and delivers cancellation to group cleanup.
    executed = linux.run_command([sys.executable, '-B', str(HERE / 'worker.py'),
        '--evidence', str(args.evidence), '--request', str(request), '--result', str(result)],
        args.evidence / 'worker-logs/stock-startup', 900, LOG_CAP)
    write(args.evidence / 'WORKER_EXECUTION.json', executed)
    if not executed['succeeded']:
        # The exact worker may have been terminated between Docker create and
        # its own finally. The random owned name is known before launch; use
        # the original bounded settle path even after host cancellation.
        owner = read(request)['owner']
        commands = linux.DockerCommands(args.docker, args.evidence / 'failed-worker-cleanup-commands', LOG_CAP)
        cleanup = linux.settle_container(commands, 't3v-' + owner[:12] + '-stock-startup', owner, image, creation_uncertain=True)
        write(args.evidence / 'FAILED_WORKER_CLEANUP.json', {'cleanup': cleanup, 'commands': commands.rows,
            'exact_owned_name_only': True, 'rankable': False, 'timing_included': False})
        require(cleanup['settled'] is cleanup['final_absent'] is True and cleanup['errors'] == [], 'failed worker exact settlement/absence required')
    after = linux.image_metadata(args, image, args.evidence / 'stock-after-startup')
    write(args.evidence / 'AFTER_METADATA.json', after)
    row = read(result) if result.is_file() else None
    immutable = before['inspection'] == after['inspection']
    passed = executed['succeeded'] is True and row is not None and row['passed'] is True and immutable
    write(args.evidence / 'STARTUP_INVENTORY.json', {'schema': 't3-fixed-stock-startup-summary-v2', 'all_passed': passed,
        'worker_execution': executed, 'startup_result': row, 'stock_image_immutable': immutable,
        'startup_pins_updated': False, 'FIFO_domain_certified': False,
        'participant_imported': False, 'market_executed': False, 'native_compiled': False,
        'timing_included': False, 'rankable': False, 'ordinary_performance_measured': False,
        'eligible_for_official_submission': False, 'threshold_232000_verified': False})
    require(passed, 'complete exact stock startup-only diagnostic required')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('stock', 'startup'))
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    require(platform.system() == 'Linux' and platform.machine() == 'x86_64', 'Linux amd64 diagnostic only; no local execution')
    verify_sources()
    args.evidence = args.evidence.resolve()
    args.evidence.mkdir(parents=True, exist_ok=True)
    args.docker, args.log_cap_bytes = 'docker', LOG_CAP
    sys.path.insert(0, str(HERE / 'host'))
    import verify_linux as linux
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, linux.cancellation)
    (stock if args.stage == 'stock' else startup)(args, linux)


if __name__ == '__main__':
    main()
