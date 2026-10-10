"""Untimed observation of unchanged frozen admission controls on Linux only."""
import hashlib
import json
from pathlib import Path
import runpy
import sys

ROOT = Path('/opt/light-typed-noise-latency-market-controls-v1/completion1009/candidates/light_typed_noise_latency_market_v1')
TARGET = ROOT / 'latency_admission_controls.py'
EXPECTED = '0728f9ec5590026fae31f340eafc38dde1359c052308403718639d9553062fbf'
OUT = Path('/output')
if sys.platform != 'linux':
    raise RuntimeError('Linux-only participant diagnostic')
receipt_bytes = (ROOT / 'SOURCE_PREPARATION_RECEIPT_v1.json').read_bytes()
if hashlib.sha256(receipt_bytes).hexdigest() != EXPECTED:
    raise ValueError('unchanged frozen127 source receipt required')
receipt = json.loads(receipt_bytes)
for row in receipt['files']:
    data = (ROOT / row['path']).read_bytes()
    if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
        raise ValueError('unchanged actual participant source required')
record = {'source_receipt_sha256': EXPECTED, 'rankable': False, 'performance_claim': False,
          'participant_sources_modified': False, 'trace_observation_only': True,
          'exceptions': [], 'failed_assertion': None}
selected = {'state_mapper.py', 'noise_admission.py', 'latency_admission.py', 'chain_episode_boundary.py',
            'episode_boundary.py', 'latency_admission_controls.py'}
def trace(frame, event, value):
    filename = Path(frame.f_code.co_filename)
    if filename.parent != ROOT or filename.name not in selected:
        return None
    if event == 'exception' and len(record['exceptions']) < 512:
        kind, error, tb = value
        record['exceptions'].append({'file': filename.name, 'function': frame.f_code.co_name,
            'line': frame.f_lineno, 'type': kind.__module__ + '.' + kind.__qualname__, 'message': str(error)})
        if filename == TARGET and frame.f_code.co_name == 'main' and frame.f_locals.get('mode', '').startswith('migration-'):
            record['failed_assertion'] = {name: frame.f_locals.get(name) for name in
                ('mode', 'phase', 'outcome', 'expected_message', 'before', 'before_state')}
    return trace
sys.path.insert(0, str(ROOT))
sys.argv = [str(TARGET), '--runtime', str(ROOT / 'runtime'), '--build', str(ROOT / 'build'),
            '--out', str(OUT / 'UNCHANGED_LATENCY_ADMISSION_CONTROLS.json')]
sys.settrace(trace)
try:
    runpy.run_path(str(TARGET), run_name='__main__')
    record['returned'] = True
except BaseException as error:
    record['returned'] = False
    record['terminal_error'] = {'type': type(error).__module__ + '.' + type(error).__qualname__, 'message': str(error)}
    raise
finally:
    sys.settrace(None)
    (OUT / 'FAILURE_OBSERVATION.json').write_text(json.dumps(record, sort_keys=True, indent=2, allow_nan=False)+'\n')
