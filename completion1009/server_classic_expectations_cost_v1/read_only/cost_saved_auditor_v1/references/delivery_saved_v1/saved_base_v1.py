"""Vendored saved-data primitives from the independently reviewed v7 auditor.
Original source SHA 8d308ada5b1c80a7653e3e3646edf48e36de89c53d485d0457a9e1bc6bb7c79a.
No participant imports, native compilation, Docker calls, or market execution.
"""
import base64
import calendar
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import time
import zipfile
import zlib

ARMS = ('parent', 'expectations')
UNITS = ('t3-s001-price-time-priority', 't3-as06-throughput-fast', 't3-mp01-stp-newest-baseline',
    't3-ra01-fundamental-shock-mid', 't3-mr-deep-book-state-size', 't3-gbatch-hetero-mix')
ENTRY = ['/usr/local/bin/python', '-B', '/opt/classic-native-kernels-v1/delivery_entry.py']
GATES = {'g0_integrity', 'g1_schema', 'g2_cutoff_resource', 'g3_domain_semantics'}
DROP = {'wall_clock_sec', 'events_per_sec', 'peak_memory_bytes', 'gpu_seconds'}
BLOCK = 'T3_STRUCTURAL_STATE_BLOCK_V2 '
META = 'T3_STRUCTURAL_STATE_V2 '
WITNESS = 'T3_STRUCTURAL_DIAGNOSTIC_V2 '

def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON constant: ' + value)))


def pin(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            digest.update(block)
    return {'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def ordinary(path):
    return not any(part.startswith('._') or part in ('__MACOSX', '__pycache__') for part in path.parts)


def inventory(root):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        if ordinary(path):
            require(not path.is_symlink(), 'saved symlink refused: ' + str(path))
            if path.is_file():
                result[path.relative_to(root).as_posix()] = pin(path)
    return result


def ns(value):
    match = re.fullmatch(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z', value)
    require(match is not None, 'exact UTC Docker timestamp required')
    return calendar.timegm(time.strptime(match[1], '%Y-%m-%dT%H:%M:%S')) * 10**9 + int((match[2] or '').ljust(9, '0') or 0)


class BaseAudit:
    def command(self, row, success=True):
        require(row['creator_reaped'] is True and row['timed_out'] is False and row['cancelled'] is False
            and row['error'] is None, 'complete finite raw command receipt')
        if success:
            require(row['returncode'] == 0 and row['succeeded'] is True, 'successful raw command required')
        require(row['rankable'] is False and type(row['per_log_file_hard_bytes']) is int
            and 0 < row['per_log_file_hard_bytes'] <= 256 * 1024**2, 'finite independent raw-log cap')
        for name in ('stdout', 'stderr'):
            saved = row[name]
            require(self.filepin(self.path(saved['path'])) == {key: saved[key] for key in ('bytes', 'sha256')}
                and saved['bytes'] < row['per_log_file_hard_bytes'] and saved['hard_limit_reached'] is False, 'full raw command stream pin/cap')
    def execution(self, row, image, stage):
        require(row['succeeded'] is True and row['exit_code'] == 0 and row['OOMKilled'] is False,
            'successful actual container required')
        require(row['error'] is None and row['rankable'] is False and row['state']['ExitCode'] == 0
            and row['state']['OOMKilled'] is False and row['state']['Pid'] == 0, 'actual stopped exit0/noOOM process')
        cleanup = row['cleanup']
        require(cleanup['settled'] is cleanup['removed'] is cleanup['final_absent'] is True and cleanup['errors'] == [],
            'exact settled/removed/absent container required')
        require(row['image_id'] == image and row['state'] == cleanup['state_before_remove'], 'actual image/terminal-state binding')
        config = row['effective_config']['Config']
        host = row['effective_config']['HostConfig']
        require(config['User'] == '65534:65534' and config['WorkingDir'] == '/output'
            and host['NanoCpus'] == 4 * 10**9 and host['Memory'] == host['MemorySwap'] == 16 * 1024**3
            and host['PidsLimit'] == 256 and host['ReadonlyRootfs'] is True and host['NetworkMode'] == 'none'
            and host['Runtime'] == 'runc' and 'ALL' in host['CapDrop']
            and host['Privileged'] is False and host['CapAdd'] in (None, [])
            and any(value.startswith('no-new-privileges') for value in host['SecurityOpt']), 'actual official resources')
        require(all(value in host['Tmpfs']['/tmp'] for value in ('noexec', 'nosuid', 'nodev', 'size=64m')), 'official64MiBnoexec tmpfs')
        limits = {value['Name']: (value['Soft'], value['Hard']) for value in host['Ulimits']}
        require(limits == {'nofile': (1024, 1024), 'nproc': (256, 256), 'fsize': (268435456, 268435456)}, 'actual finite ulimits')
        require(all(value['Type'] in ('bind', 'tmpfs') for value in row['effective_config']['Mounts']),
            'no additional persistent or unsupported mount types')
        mounts = [value for value in row['effective_config']['Mounts'] if value['Type'] == 'bind']
        require(len(mounts) == 2 and {value['Destination']: value['RW'] for value in mounts} == {'/input': False, '/output': True}, 'original input/output-only mounts')
        env = dict(value.split('=', 1) for value in config['Env'] if '=' in value)
        wanted = {'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
            'NUMEXPR_NUM_THREADS': '1', 'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
        require(all(env.get(key) == value for key, value in wanted.items()), 'actual deterministic scientific environment')
        expected_entry = ['/usr/local/bin/python'] if stage != 'one' else ENTRY
        require(config['Entrypoint'] == expected_entry, 'actual stage entry')
        for command in row['commands']:
            success = not (command['argv'][1] == 'inspect' and command['returncode'] == 1)
            self.command(command, success)
            if command['argv'][1] == 'inspect' and command['returncode'] == 0:
                values = read(self.path(command['stdout']['path']))
                require(len(values) == 1 and values[0]['Id'] == row['container_id'] and values[0]['Name'] == '/' + row['name']
                    and values[0]['Image'] == image and values[0]['Config']['Labels']['qfbench2.t3.verifier_owner'] == row['owner'], 'raw inspected owned identity')
                actual_config = {key: values[0][key] for key in ('Config', 'HostConfig', 'Mounts')}
                # Docker drops false OomKillDisable to null after the cgroup is
                # torn down. Actual OOMKilled/exit state and every enforced
                # resource field remain independently required.
                actual_config['HostConfig'] = dict(actual_config['HostConfig'])
                require(actual_config['HostConfig']['OomKillDisable'] in (False, None), 'OOM kill disable not enabled')
                actual_config['HostConfig']['OomKillDisable'] = False
                wanted_config = dict(row['effective_config'])
                actual_config['Mounts'] = sorted(actual_config['Mounts'], key=lambda value: value['Destination'])
                wanted_config['Mounts'] = sorted(wanted_config['Mounts'], key=lambda value: value['Destination'])
                require(actual_config == wanted_config, 'every raw inspected effective resource config unchanged')
                if values[0]['State']['Status'] == 'exited':
                    require(values[0]['State'] == row['state'], 'every raw final inspected state exact receipt')
        require(row['commands'][0]['argv'][1] == 'create' and self.path(row['commands'][0]['stdout']['path']).read_text() == row['container_id'] + '\n', 'raw Docker create identity')
        operations = [command['argv'][1] for command in row['commands']]
        require(operations.count('create') == operations.count('start') == operations.count('rm') == 1
            and set(operations).issubset({'create', 'inspect', 'start', 'wait', 'rm'}), 'exact onecreate/startattach/rm with no extra container execution')
        require(all(command['argv'][1:] == ['wait', row['name']] for command in row['commands'] if command['argv'][1] == 'wait'), 'wait only for exact owned container')
        require(row['attach'] in row['commands'] and row['attach']['argv'][1:] == ['start', '--attach', row['name']], 'one original attach')
        require(any(command['argv'][1:] == ['rm', row['name']] and command['returncode'] == 0 for command in row['commands']), 'raw exact removal')
        last = row['commands'][-1]
        require(last['argv'][1:] == ['inspect', row['name']] and last['returncode'] == 1
            and self.path(last['stdout']['path']).read_bytes() == b'[]\n'
            and self.path(last['stderr']['path']).read_text() == 'Error: No such object: ' + row['name'] + '\n', 'raw exact final absence')
        started, finished = ns(row['state']['StartedAt']), ns(row['state']['FinishedAt'])
        require(started < finished and not row['state']['Running'] and not row['state']['Restarting'], 'positive settled actual daemon interval')
        self.intervals.append((started, finished, row['name']))
        self.executions.append(row)
        return (finished - started) / 10**9
    def zip_manifest(self):
        require(pin(self.args.zip) == {'bytes': self.args.expected_zip_bytes, 'sha256': self.args.expected_zip_sha256}, 'complete downloaded ZIP bytes/SHA')
        expected = {}
        with zipfile.ZipFile(self.args.zip) as archive:
            require(archive.testzip() is None, 'all ZIP member CRC')
            for member in archive.infolist():
                path = PurePosixPath(member.filename)
                require(not path.is_absolute() and '..' not in path.parts and '\\' not in member.filename, 'safe ZIP path')
                if member.is_dir() or not ordinary(path):
                    continue
                require(member.filename not in expected, 'unique ZIP member')
                require((member.external_attr >> 16) & 0o170000 != 0o120000, 'ordinary ZIP file not symlink')
                actual = self.artifact / member.filename
                require(actual.is_file() and not actual.is_symlink(), 'complete extracted ordinary member')
                digest, size = hashlib.sha256(), 0
                with archive.open(member) as stream:
                    for chunk in iter(lambda: stream.read(1024**2), b''):
                        digest.update(chunk)
                        size += len(chunk)
                expected[member.filename] = {'bytes': size, 'sha256': digest.hexdigest()}
                require(expected[member.filename] == self.filepin(actual), 'full extracted bytes equal ZIP')
        require(expected == inventory(self.artifact), 'complete extracted ordinary roster')
        manifest = read(self.artifact / 'ARTIFACT.json')
        require(manifest['files'] == {name: value for name, value in expected.items() if name != 'ARTIFACT.json'}
            and manifest['rankable'] is False and manifest['all_actual_output_bytes_retained'] is True, 'complete ARTIFACT manifest')
        self.report['artifact_files'] = len(expected)
    def control_groups(self, saved_roster=ARMS, saved_admission_units=UNITS):
        import pyarrow.parquet as pq
        controls = read(self.evidence / 'CONTROLS.json')
        require(set(controls) == set(saved_roster), 'exact saved control roster')
        expected_admissions = []
        admission_items = {item['unit']: item for item in read(self.evidence / 'REFERENCE_PLAN.json')['units']}
        for unit in saved_admission_units:
            item = admission_items[unit]
            for path in item['scenario_paths']:
                relative = path.split('/references/' + item['unit'] + '/', 1)[1]
                expected_admissions.append({'unit': item['unit'] + ('/' + Path(path).stem if item['shape'] == 'batch' else ''),
                    'scenario_sha256': item['input_sha256'][relative], 'source_authenticated': True, 'native_admitted': True})
        names = ('original', 'light_canonical', 'light_dynamic', 'light_dynamic_repeat', 'decline_trace', 'decline_message_trace')
        native_states = []
        for arm in ARMS:
            require(controls[arm]['passed'] is True and controls[arm]['six_children'] == 6 and controls[arm]['admission_markets'] == 10, 'complete control audit receipt')
            self.execution(controls[arm]['execution'], self.image, 'controls')
            out = self.evidence / 'controls' / arm / 'output/controls'
            admissions = read(out / 'ADMISSION.json')
            require(len(admissions['cases']) == 10 and admissions['fresh_check_per_market'] is admissions['source_and_native_ELF_checked'] is True
                and admissions['market_executed'] is admissions['rankable'] is False
                and all(row['native_admitted'] is row['source_authenticated'] is True for row in admissions['cases']), 'ten fresh admissions per control arm')
            require(admissions['cases'] == expected_admissions, 'all fresh admission exact input SHA and scenario roster')
            fixture = read(out / 'native-fixtures/NATIVE_OUTPUT_FIXTURES.json')
            require(fixture['all_passed'] is True and fixture['actual_parquet_bytes_equal'] is fixture['actual_independent_pandas_readback_equal'] is True
                and fixture['market_executed'] is fixture['rankable'] is False, 'complete independent cold serializer fixture')
            fixture_cases = ('stable_cross_owner_ties', 'exact_timestamp_side_normalization', 'signed_trace_boundaries')
            for label in ('native', 'original'):
                child = read(out / 'native-fixtures' / label / 'FIXTURE_RECEIPT.json')
                require(child == fixture['children'][label] and child['arm'] == label and child['market_executed'] is False
                    and child['native_fixture_owners_initialized'] is False and tuple(row['trace_case'] for row in child['cases']) == fixture_cases,
                    'actual complete cold fixture child receipt')
                expected_files = {name + '/' + file for name in fixture_cases for file in ('trace.parquet', 'message_trace.parquet')}
                if label == 'native':
                    expected_files.update('retained_after_owner_destruction/' + file for file in ('trace.parquet', 'message_trace.parquet'))
                    require(child['forbidden_import_attempts'] == [] and set(child['boundary_cases']) == {
                        'nonstring_endstate_keys_decline_without_callbacks', 'ledger_alias_and_hostile_map', 'message_bool_range_and_string_declines',
                        'trace_signed53_bool_side_unknown_event_declines', 'sealed_immutable_native_descriptor_authority',
                        'immutable_buffers_survive_graph_owner_destruction'}, 'all finite cold owner/key/null/boundary/import controls')
                require({row['path'] for row in child['files']} == expected_files and len(child['files']) == len(expected_files)
                    and set(self.inventory(out / 'native-fixtures' / label)) == expected_files | {'FIXTURE_RECEIPT.json'}, 'complete exact cold fixture file roster')
                require(child['versions'] == ({'numpy': '1.26.4', 'pyarrow': '15.0.2'} if label == 'native'
                    else {'numpy': '1.26.4', 'pyarrow': '15.0.2', 'pandas': '1.5.3'}), 'original/native cold fixture exact library versions')
                for row in child['files']:
                    require(pin(out / 'native-fixtures' / label / row['path']) == {key: row[key] for key in ('bytes', 'sha256')}, 'every exact fixture file')
                if label == 'native':
                    for field, count in (('direct_clone_controls', 35), ('classic_latency_controls', 142), ('classic_source_controls', 8)):
                        checks = child[field]
                        require(checks['all_passed'] is True and checks['market_executed'] is False and len(checks['cases']) == count
                            and all(row['passed'] is True for row in checks['cases']), 'all original finite native controls: ' + field)
                    if arm == 'price_index':
                        checks = child['price_index_controls']
                        require(checks['all_passed'] is True and checks['market_executed'] is checks['rankable'] is False
                            and len(checks['cases']) == 308 and all(row['passed'] is True for row in checks['cases']), 'all308v3 price-index finite controls')
                        for field in ('bids', 'asks'):
                            for operation in ('setter', 'delete'):
                                require(any(row['case'] == 'book_' + field + '_' + operation + '_clears_both_maps' and row['passed'] for row in checks['cases']), 'retain diagnostic deletion/setter controls')
                for case in child['cases']:
                    for filename, expected in (('trace.parquet', case['expected_trace']), ('message_trace.parquet', case['expected_messages'])):
                        file = out / 'native-fixtures' / label / case['trace_case'] / filename
                        table = pq.ParquetFile(file).read(use_threads=False, use_pandas_metadata=False)
                        require(table.to_pydict() == expected, 'all explicit original/native cold fixture cells')
                        if label == 'native':
                            original = out / 'native-fixtures/original' / case['trace_case'] / filename
                            require(pin(file) == pin(original), 'all full native fixture Parquet bytes equal original')
            require(fixture['children']['original']['cases'] == fixture['children']['native']['cases'], 'all explicit fixture expectations original/native equal')
            for filename in ('trace.parquet', 'message_trace.parquet'):
                require(pin(out / 'native-fixtures/native/retained_after_owner_destruction' / filename)
                    == pin(out / 'native-fixtures/native/signed_trace_boundaries' / filename), 'full immutable buffers retained after owner destruction')
            children = out / 'children'
            bundle = read(children / 'CONTROLS.json')
            expected_cases = ('actual_required_owner_selection', 'trace.parquet', 'message_trace.parquet', 'STATE.json', 'complete_actual_event_counts',
                'cold_readonly_output_and_binding_controls', 'positive_actual_native_arena_and_repeat_equivalence', 'each_projector_complete_pair_fallback_without_rerun')
            require(bundle['all_passed'] is True and tuple(row['case'] for row in bundle['cases']) == expected_cases
                and all(row['passed'] is True for row in bundle['cases']), 'all original eight six-child complete-state gates')
            base = children / 'original'
            for name in names:
                child = children / name
                for filename in ('STATE.json', 'trace.parquet', 'message_trace.parquet'):
                    require(pin(child / filename) == pin(base / filename), 'full six-child original state/RNG/alias/trace/ledger equality')
                record = read(child / 'CONTROL_CHILD.json')
                require(record['actual_markets'] == 1 and record['graph_output_readonly'] is record['bindings_restored'] is record['observer_finished'] is True
                    and record['production_import_attempts'] == [], 'one actual readonly restored control episode')
                native = name not in ('original', 'light_canonical')
                selection = read(child / 'ARM_SELECTION.json')
                kernel = 'NativeOwnerKernel' if native else 'CanonicalKernel'
                require(selection['passed'] is True and selection['native_authority'] is native and selection['selected_kernel'] == kernel, 'exact native/canonical control selection')
                if name != 'original':
                    witness = read(child / 'OUTPUT_WITNESS.json')
                    declined = {'decline_trace': 'trace', 'decline_message_trace': 'message_trace'}.get(name)
                    mode = 'legacy-pandas' if declined else 'native-canonical-arrow-buffers' if native else 'canonical-arrow-buffers'
                    require(witness['source_authenticated'] is witness['observer_admitted'] is True and witness['market_rerun'] is False
                        and witness['native_admitted'] is native and witness['selected_kernel'] == kernel
                        and witness['projectors_admitted'] is (declined is None) and witness['output_mode'] == mode
                        and witness['native_output_pair'] is (native and declined is None)
                        and witness['declines'] == ({} if declined is None else {declined: 'control-forced-projector-decline'}), 'actual forced complete pair fallback without rerun')
                    require(witness['actual_trace_sha256'] == pin(child / 'trace.parquet')['sha256']
                        and witness['actual_trace_rows'] == read(child / 'events.json')['n_events'], 'full control witness/count/trace binding')
                if native:
                    arena = read(child / 'ARENA_DIAGNOSTICS.json')
                    require(arena['orders']['order_slots'] > 0 and arena['messages']['constructed_messages'] > 0, 'actual positive native order/message lifecycle')
            require(read(children / 'light_dynamic/ARENA_DIAGNOSTICS.json') == read(children / 'light_dynamic_repeat/ARENA_DIAGNOSTICS.json'), 'complete native arena lifecycle repeat equality')
            native_states.append(pin(children / 'light_dynamic/STATE.json'))
            if arm == 'expectations':
                checks = read(out / 'extra/BUILD_EXPECTATION_CONTROLS.json')
                require(checks['all_passed'] is True and len(checks['cases']) == 30 and all(row['passed'] is True for row in checks['cases']), 'all30expectations corruption/context controls')
            if arm == 'price_index':
                checks = read(out / 'PRICE_INDEX_CHECKS.json')
                require(checks == fixture['children']['native']['price_index_controls'], 'two independent all308price-index control executions exact result')
        require(all(value == native_states[0] for value in native_states), 'complete native control state equal across versions')
    def decode_parquet(self, file, frame):
        import pyarrow.parquet as pq
        digest = self.filepin(file)['sha256']
        if digest in self.decoded:
            require(self.decoded[digest]['rows'] == frame['candidate_rows'], 'repeated identical Parquet row binding')
            return
        table = pq.ParquetFile(file).read(use_threads=False, use_pandas_metadata=False)
        require(table.num_rows == frame['candidate_rows'] == frame['reference_rows'], 'allcolumn/allrowgroup decoded Parquet row count')
        names = ['t_ns', 'agent_id', 'msg_type', 'side', 'price', 'size', 'order_id'] if file.name == 'trace.parquet' else [
            'seq', 't_recv_ns', 't_send_ns', 'latency_ns', 'src_id', 'dst_id', 'message_id', 'msg_type', 'order_id', 'causal_parent']
        require(table.column_names == names and all(str(field.type) == ('int32' if field.name in ('agent_id', 'src_id', 'dst_id')
            else 'string' if field.name in ('msg_type', 'side') else 'int64') for field in table.schema), 'exact official Arrow physical schema/column order')
        self.decoded[digest] = {'rows': table.num_rows, 'kind': file.name, 'nulls': {name: table[name].null_count for name in names}}
    def output(self, row, item, *, diagnostic=False):
        require(type(diagnostic) is bool and (not diagnostic or row.get('stage') == 'diagnostic'), 'explicit exact diagnostic output route')
        gate_log_bytes = (256 if diagnostic else 16) * 1024**2
        out = self.path(row['output'])
        check = row['reference_checks']
        require(check['passed'] is True and check['output_tree']['passed'] is True and check['output_tree']['breaches'] == [], 'complete original output reference gates')
        actual = self.inventory(out)
        expected_files = {'trace.parquet', 'message_trace.parquet', 'events.json'} if item['shape'] == 'single' else {
            entry['sub'] + '/' + name for entry in item['subs'] for name in ('trace.parquet', 'message_trace.parquet', 'events.json')} | {'batch_events.json'}
        optional = {'profile.json'} if item['shape'] == 'single' else {entry['sub'] + '/profile.json' for entry in item['subs']}
        require(expected_files.issubset(actual) and set(actual).issubset(expected_files | optional)
            and len(actual) <= 256 and check['output_tree']['files'] == sorted(actual), 'complete actual official output file allowlist')
        require(sum(value['bytes'] for value in actual.values()) == check['output_tree']['total_bytes'] <= 256 * 1024**2, 'official256MiB complete output tree')
        frames = check['frames']
        event_files = []
        parquet_files = {name for name in expected_files if name.endswith('.parquet')}
        seen_candidates, seen_references = set(), set()
        require(len(frames) == len(parquet_files), 'every actual trace/ledger frame compared')
        for frame in frames:
            file = self.path(frame['candidate'])
            require(out in file.parents, 'every compared frame belongs to this actual output tree')
            relative = file.relative_to(out).as_posix()
            require(relative in parquet_files and relative not in seen_candidates, 'every actual output frame compared exactly once')
            seen_candidates.add(relative)
            reference = frame['reference'].split('/references/' + item['unit'] + '/', 1)[1]
            expected_reference = relative if item['shape'] == 'single' else 'checks/reference_data/' + relative
            require(reference == expected_reference and reference not in seen_references, 'exact corresponding original reference frame once')
            seen_references.add(reference)
            require(frame['passed'] is frame['byte_equal'] is True and frame['candidate_sha256'] == frame['reference_sha256']
                == self.filepin(file)['sha256'] == item['reference_sha256'][reference], 'every actual full Parquet copy exact official reference bytes')
            self.decode_parquet(file, frame)
            require(frame['candidate_dtypes'] == frame['reference_dtypes'], 'all exact candidate/reference dataframe dtypes')
            if file.name == 'trace.parquet':
                events = read(file.with_name('events.json'))
                require(events['n_events'] == frame['candidate_rows'] and events['trace_sha256'] == frame['candidate_sha256'], 'actual trace/sidecar fullcount/digest')
                event_files.append((file, events))
        require(seen_candidates == parquet_files and len(event_files) == (1 if item['shape'] == 'single' else len(item['subs'])), 'complete unique trace/ledger frame coverage')
        require(len(check['sidecars']) == len(event_files), 'complete single/batch sidecar verification roster')
        for (file, events), receipt in zip(event_files, check['sidecars']):
            require(receipt['passed'] is True and receipt['breaches'] == [] and receipt['events'] == events
                and receipt['actual_trace_sha256'] == self.filepin(file)['sha256'], 'full actual sidecar/raw reference receipt')
        count = sum(events['n_events'] for _, events in event_files)
        require(count == check['actual_events'], 'full ordinary output total events recomputed')
        if item['shape'] == 'batch':
            aggregate = check['aggregate']
            meta = read(out / 'batch_events.json')
            require(aggregate['passed'] is True and aggregate['breaches'] == [] and aggregate['events'] == meta
                and meta['n_scenarios'] == len(item['subs']) and meta['total_events'] == count
                and len(meta['per_scenario']) == len(item['subs']) and len({record['sub'] for record in meta['per_scenario']}) == len(item['subs'])
                and {record['sub']: record['n_events'] for record in meta['per_scenario']}
                    == {file.parent.name: events['n_events'] for file, events in event_files}, 'complete batch accounting exact per market')
        else:
            require(check['aggregate'] is None, 'single market no aggregate accounting')
        gate = row['developer_verifier']
        require(gate['admissible'] is True and gate['status'] == 'completed' and set(gate['verdict']['gate_results']) == GATES
            and all(value['passed'] is True for value in gate['verdict']['gate_results'].values()), 'all four unchanged official developer gates')
        self.command(gate['execution'])
        argv = gate['execution']['argv']
        require(len(argv) == 11 and argv[1].endswith('/host/verify_public.py') and argv[2] == '_gate'
            and argv[3] == '--unit' and argv[4].endswith('/references/' + item['unit'])
            and argv[5] == '--output' and self.path(argv[6]) == out and argv[7] == '--save'
            and self.path(argv[8]) == out.parent / 'developer_verdict.json' and argv[9] == '--gate-kit'
            and argv[10].endswith('/track3') and 0 < gate['execution']['timeout_sec'] <= 300
            and gate['execution']['per_log_file_hard_bytes'] == gate_log_bytes, 'actual frozen official gate route/options/stage bounds')
        require(read(self.path(gate['execution']['stdout']['path'])) == gate['verdict']
            == read(out.parent / 'developer_verdict.json'), 'official gate raw stdout/receipt correspondence')
        staged_names = set()
        for staged in row['execution']['staged_inputs']:
            file = self.path(staged['staged'])
            relative = file.relative_to(out.parent / 'input').as_posix()
            require(relative not in staged_names, 'every readonly staged input checked once')
            staged_names.add(relative)
            require(pin(file)['sha256'] == staged['sha256'] == item['input_sha256'][relative], 'all exact readonly staged input bytes')
        wanted_staged = {'scenario.json'} if item['shape'] == 'single' else {entry['scenario_file'] for entry in item['subs']}
        require(staged_names == wanted_staged, 'all actual staged scenario input coverage exact original roster')
        return out
    def diagnostic_stream(self, row):
        streams, metas, witnesses = {}, [], []
        path = self.path(row['execution']['attach']['stdout']['path'])
        with path.open() as source:
            for line in source:
                if line.startswith(WITNESS):
                    witnesses.append(json.loads(line[len(WITNESS):]))
                elif line.startswith(META):
                    metas.append(json.loads(line[len(META):]))
                elif line.startswith(BLOCK):
                    block = json.loads(line[len(BLOCK):])
                    key = block['arm'], block['scenario_id'], block['seed']
                    stream = streams.setdefault(key, {'decoder': zlib.decompressobj(), 'hash': hashlib.sha256(), 'size': 0, 'blocks': 0})
                    data = base64.b64decode(block['data_base64'], validate=True)
                    require(block['block_index'] == stream['blocks'] and len(data) == block['compressed_bytes'] <= 1024**2
                        and block['timing_included'] is block['rankable'] is False, 'ordered exact untimed1MiB compressed state block')
                    remaining = data
                    while remaining:
                        decoded = stream['decoder'].decompress(remaining, 1024**2)
                        remaining = stream['decoder'].unconsumed_tail
                        require(not stream['decoder'].unused_data and (decoded or not remaining), 'complete single zlib stream without trailing payload')
                        stream['hash'].update(decoded)
                        stream['size'] += len(decoded)
                        require(stream['size'] <= 4 * 1024**3, 'finite full-state decoded bytes')
                    stream['blocks'] += 1
        require(len(streams) == len(metas) == len(row['state_receipts']) and len(witnesses) == len(row['admission_witnesses']), 'complete rawstdout states/witnesses correspondence')
        for receipt in row['state_receipts']:
            raw = [value for value in metas if (value['arm'], value['scenario_id'], value['seed'])
                == (receipt['arm'], receipt['scenario_id'], receipt['seed'])]
            require(len(raw) == 1 and all(receipt[key] == value for key, value in raw[0].items()), 'one exact raw state-meta saved receipt')
            key = receipt['arm'], receipt['scenario_id'], receipt['seed']
            stream = streams.pop(key)
            require(stream['decoder'].eof and not stream['decoder'].unused_data and not stream['decoder'].unconsumed_tail
                and receipt['state_bytes'] == stream['size'] and receipt['state_blocks'] == stream['blocks']
                and receipt['state_sha256'] == stream['hash'].hexdigest(), 'complete actual zlib state EOF/fullSHA/count')
            require(pin(self.path(receipt['path'])) == {'bytes': stream['size'], 'sha256': stream['hash'].hexdigest()}, 'retained complete STATE equal stdoutstream bytes')
            require(all(receipt[field] is True for field in ('full_actual_STATE_bytes_retained', 'graph_output_readonly', 'observer_finished',
                'kernel_and_summary_bindings_restored', 'index_witness_recorded_before_business_alias_snapshot')), 'actual readonly fullstate and restored context')
        for raw, saved in zip(witnesses, row['admission_witnesses']):
            require(all(saved[key] == value for key, value in raw.items()), 'raw diagnostic witness exact saved receipt')
        require(not streams, 'all complete actual state streams claimed exactly once')
