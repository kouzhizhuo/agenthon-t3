"""Official leading-verb entry for the unchanged exact classic runtime."""
from pathlib import Path
import runpy
import sys

SOURCE = Path('/opt/classic-native-kernels-v1/completion1009/candidates/classic_native_kernels_v1/production_cli.py')
if len(sys.argv) < 2 or sys.argv[1] not in ('simulate', 'simulate-batch'):
    raise SystemExit('expected simulate or simulate-batch')
if any(value in ('--arm', '--runtime', '--build', '--output-witness') or value.startswith(('--arm=', '--runtime=', '--build=', '--output-witness=')) for value in sys.argv[2:]):
    raise SystemExit('internal runtime options are not public CLI arguments')
sys.path.insert(0, str(SOURCE.parent))
sys.argv = [str(SOURCE), *sys.argv[1:], '--arm', 'light_dynamic']
runpy.run_path(str(SOURCE), run_name='__main__')
