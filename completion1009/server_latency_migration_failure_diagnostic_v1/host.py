"""One Linux diagnostic container; full resource, failure and cleanup evidence."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time
import uuid

HERE = Path(__file__).resolve().parent
EVIDENCE = Path('latency-migration-diagnostic-v1-evidence').resolve()
EVIDENCE.mkdir(exist_ok=True)
output = EVIDENCE / 'output'; output.mkdir(); output.chmod(0o777)
input_dir = EVIDENCE / 'input'; input_dir.mkdir()
image = json.loads((Path('latency-migration-diagnostic-v1-build/BUILD_READY.json')).read_bytes())['image_id']
name = 't3-latency-diag-' + uuid.uuid4().hex
owner = uuid.uuid4().hex
records = []
state = None
removed = absent = False
created = False
failure = None
if platform.system() != 'Linux' or platform.machine() != 'x86_64':
    raise ValueError('actual Linux amd64 required')
def call(argv, label, timeout=60, allow_failure=False):
    start = time.monotonic()
    with (EVIDENCE / (label + '.log')).open('xb') as log:
        result = subprocess.run(['docker', *argv], stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    data = (EVIDENCE / (label + '.log')).read_bytes()
    records.append({'argv': argv, 'label': label, 'returncode': result.returncode,
        'host_elapsed_sec': time.monotonic()-start, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    if result.returncode and not allow_failure:
        raise RuntimeError('docker command failed: ' + label)
    return result.returncode, data
try:
    call(['create', '--name', name, '--label', 't3.diagnostic.owner='+owner, '--pull', 'never',
        '--platform', 'linux/amd64', '--runtime', 'runc', '--network', 'none', '--cpus', '4',
        '--memory', '17179869184', '--memory-swap', '17179869184', '--pids-limit', '256',
        '--ulimit', 'nofile=1024:1024', '--ulimit', 'nproc=256:256', '--ulimit', 'fsize=268435456:268435456',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--read-only', '--user', '65534:65534',
        '--workdir', '/output', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m',
        '--mount', 'type=bind,src='+str(input_dir)+',dst=/input,readonly',
        '--mount', 'type=bind,src='+str(output)+',dst=/output',
        '--mount', 'type=bind,src='+str(HERE / 'diagnose.py')+',dst=/diagnose.py,readonly',
        '--env', 'PYTHONHASHSEED=0', '--env', 'PYTHONDONTWRITEBYTECODE=1',
        '--entrypoint', '/usr/local/bin/python', image, '-B', '/diagnose.py'], 'create')
    created = True
    _, data = call(['inspect', name], 'before')
    before = json.loads(data)[0]
    assert before['Image'] == image and before['Config']['Labels']['t3.diagnostic.owner'] == owner
    host = before['HostConfig']
    for field, value in {'NanoCpus':4000000000,'Memory':17179869184,'MemorySwap':17179869184,
                        'PidsLimit':256,'ReadonlyRootfs':True,'NetworkMode':'none','Runtime':'runc'}.items():
        assert host[field] == value, field
    assert before['Config']['User'] == '65534:65534' and 'ALL' in host['CapDrop']
    assert any(x.startswith('no-new-privileges') for x in host['SecurityOpt'])
    assert all(x in host['Tmpfs']['/tmp'] for x in ('noexec','nosuid','nodev','size=64m'))
    assert {x['Name']:(x['Soft'],x['Hard']) for x in host['Ulimits']} == {
        'nofile':(1024,1024),'nproc':(256,256),'fsize':(268435456,268435456)}
    mounts = {x['Destination']:x for x in before['Mounts']}
    assert not mounts['/input']['RW'] and not mounts['/diagnose.py']['RW'] and mounts['/output']['RW']
    call(['start', '--attach', name], 'start-attach', timeout=300, allow_failure=True)
    _, data = call(['inspect', name], 'after')
    after = json.loads(data)[0]; state = after['State']
    assert after['Image'] == image and after['Config']['Labels']['t3.diagnostic.owner'] == owner
    assert not state['Running'] and not state['Restarting'] and not state['OOMKilled'] and state['ExitCode'] == 1
    observation = json.loads((output / 'FAILURE_OBSERVATION.json').read_bytes())
    raw = json.loads((output / 'UNCHANGED_LATENCY_ADMISSION_CONTROLS.json').read_bytes())
    assert observation['participant_sources_modified'] is False and observation['returned'] is False
    assert observation['failed_assertion']['mode'] == 'migration-preflight-actors'
    assert len(raw['cases']) == 14 and not raw['all_passed'] and all(x['passed'] for x in raw['cases'])
    assert observation['failed_assertion']['outcome']['returned'] is False
    print(json.dumps(observation['failed_assertion']['outcome'], sort_keys=True), flush=True)
except BaseException as error:
    failure = {'type':type(error).__name__, 'message':str(error)}
    raise
finally:
    cleanup_error = None
    try:
        code, data = call(['inspect', name], 'cleanup-inspect', allow_failure=True)
        if code == 0:
            info = json.loads(data)[0]
            assert info['Image'] == image and info['Config']['Labels']['t3.diagnostic.owner'] == owner
            if info['State']['Running']:
                call(['kill', name], 'kill', allow_failure=True)
            call(['wait', name], 'wait', allow_failure=True)
            call(['rm', name], 'remove'); removed = True
        code, data = call(['inspect', name], 'absence', allow_failure=True)
        absent = code != 0 and b'No such object' in data
        assert absent
    except BaseException as error:
        cleanup_error = {'type':type(error).__name__, 'message':str(error)}
    report = {'rankable':False, 'performance_claim':False, 'image_id':image, 'name':name,'owner':owner,
              'failure':failure, 'state':state, 'created':created, 'removed':removed,'final_absent':absent,
              'cleanup_error':cleanup_error,'commands':records,
              'all_passed':failure is None and removed and absent and cleanup_error is None}
    (EVIDENCE / 'DIAGNOSTIC_RESULT.json').write_text(json.dumps(report, sort_keys=True, indent=2)+'\n')
    if cleanup_error:
        raise RuntimeError('diagnostic container cleanup failed')
