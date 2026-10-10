"""Symmetric leading-verb comparison entry; not the official submission entry."""
from pathlib import Path
import runpy
import sys

ROOT = Path('/opt/classic-native-kernels-v1/completion1009/candidates')
ARMS = {'parent': 'classic_native_kernels_v1', 'expectations': 'classic_build_expectations_v1',
        'price_index': 'classic_price_index_v2'}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('simulate', 'simulate-batch'):
        raise ValueError('leading production verb required')
    options = list(sys.argv[1:])
    if options.count('--mode') != 1:
        raise ValueError('one internal comparison mode required')
    position = options.index('--mode')
    if position + 1 != len(options) - 1 or options[position + 1] not in ARMS:
        raise ValueError('trailing exact comparison mode required')
    arm = options[position + 1]
    options = options[:position]
    if any(value.split('=', 1)[0] in ('--arm', '--runtime', '--build', '--output-witness') for value in options[1:]):
        raise ValueError('production measurement cannot request diagnostic options')
    source = ROOT / ARMS[arm] / 'production_cli.py'
    sys.path.insert(0, str(source.parent))
    sys.argv = [str(source), *options, '--arm', 'light_dynamic']
    runpy.run_path(str(source), run_name='__main__')


if __name__ == '__main__':
    main()
