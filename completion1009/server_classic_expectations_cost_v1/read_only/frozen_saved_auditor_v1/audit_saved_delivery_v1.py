"""Independent saved full71 delivery audit. No participant or native execution."""
import argparse
import ast
import gzip
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import statistics
import sys

from graph_saved_v1 import GraphAudit, OBJECT_CLASSES, ROOT_KEYS
from saved_base_v1 import ARMS, BaseAudit, DROP, ENTRY, GATES, UNITS, inventory, ns, ordinary, pin, read, require

HERE = Path(__file__).resolve().parent
PARENT = 'ghcr.io/kouzhizhuo/agenthon-t3-classic@sha256:c1b3c9f2aec8d5a761b4814cfddf7b79b76eb6afd09ca6bd4558661e2ce046ba'
CANDIDATE_SHA = 'e3f4bb09be2fa809e443f78c38ed72cb30f1ff9a597fed8d932d6861aaa8ba34'
FIVE = (UNITS[0], UNITS[1], UNITS[2], UNITS[3], UNITS[-1])


class Audit(BaseAudit):
    def __init__(self, args):
        self.args, self.artifact = args, args.artifact.resolve()
        self.evidence, self.payload = self.artifact / 'evidence', self.artifact / 'source-payload'
        self.hash_cache, self.inventory_cache, self.decoded, self.intervals, self.executions = {}, {}, {}, [], []
        self.graph_cache = {}
        self.report = {'schema': 't3-independent-saved-expectations-delivery-report-v1', 'status': 'auditing',
            'all_passed': False, 'all_execution_checks_passed': False, 'publication_passed': False,
            'performance_usable': False, 'eligible_for_official_submission': False, 'official_score': None,
            'threshold_232000_verified': False, 'participant_imported': False, 'native_compiled': False,
            'market_executed': False, 'completed_stages': [], 'failures': [], 'pending': [], 'counts': {},
            'authority': {'plan': pin(HERE / 'COUNTED_AUDIT_PLAN_v1.json'), 'auditor': inventory(HERE),
                'artifact': None, 'harness_source_pins': None, 'remote_head': args.expected_head,
                'candidate_source_receipt': CANDIDATE_SHA, 'public_image': None},
            'performance': {'ordinary_daemon_time_only': True, 'measured_runs': 0, 'unit_medians': [],
                'five_unit_mean_of_median_EPS': None, 'official_score_is_separate': True},
            'STATE_graphs': [], 'limitations': [
                'Linux timing describes this runner and five representative units; it is not an official score.',
                'Official reference and gate bytes are bound through frozen unchanged verifier/source and actual retained raw verdicts.',
                'No diagnostic, control, construction, source-copy or publication elapsed time enters performance.',
                'Saved expectation code/default artifacts are opaque bytes and never loaded as executable objects.']}

    def path(self, remote):
        require(type(remote) is str and remote.count(self.args.remote_evidence_marker) == 1, 'one exact saved evidence marker')
        tail = PurePosixPath(remote.split(self.args.remote_evidence_marker, 1)[1])
        require(not tail.is_absolute() and '..' not in tail.parts and '\\' not in str(tail) and tail.as_posix() != '.', 'safe saved evidence path')
        result = self.evidence / tail.as_posix()
        for parent in (result, *result.parents):
            require(not parent.is_symlink(), 'all saved path ancestors non-symlink')
            if parent == self.artifact:
                break
        require(self.evidence.resolve() in result.resolve().parents, 'saved file remains in evidence root')
        return result

    def filepin(self, path):
        path = Path(path)
        if path not in self.hash_cache:
            require(path.is_file() and not path.is_symlink(), 'saved regular file required: ' + str(path))
            self.hash_cache[path] = pin(path)
        return self.hash_cache[path]

    def inventory(self, root):
        root = Path(root)
        if root not in self.inventory_cache:
            self.inventory_cache[root] = inventory(root)
        return self.inventory_cache[root]

    def graph(self, path, parent_equal):
        file = self.filepin(path)
        if file['sha256'] not in self.graph_cache:
            require(file['bytes'] <= 4 * 1024**3, 'finite complete STATE graph size')
            self.graph_cache[file['sha256']] = GraphAudit().audit(read(path))
        result = {'path': str(path.relative_to(self.artifact)), **file, **self.graph_cache[file['sha256']], 'parent_equal': parent_equal}
        self.report['STATE_graphs'].append(result)
        return result

    def source_build(self):
        source = self.args.source.resolve()
        local_pins = read(source / 'SOURCE_PINS.json')
        require(pin(source / 'SOURCE_PINS.json')['sha256'] == self.args.expected_source_pins_sha256,
            'explicit final harness source pins SHA')
        require(pin(self.artifact / 'SOURCE_PINS.json') == pin(source / 'SOURCE_PINS.json')
            and len(local_pins['files']) == 22, 'actual carried22final source pins')
        for name, wanted in local_pins['files'].items():
            require(pin(source / name) == pin(self.artifact / name) == wanted, 'every final local/carried source byte: ' + name)
            if name.endswith('.py'):
                ast.parse((self.artifact / name).read_bytes())
        remote = read(self.args.remote_readback)
        require(remote['head'] == self.args.expected_head and remote['all_passed'] is True and remote['participant_imported'] is False
            and all(row['passed'] is True and row['actual'] == row['expected'] for row in remote['checks']), 'root final remote source readback authority')
        expected_remote = {'completion1009/' + source.name + '/' + name: wanted for name, wanted in local_pins['files'].items()}
        expected_remote['completion1009/' + source.name + '/SOURCE_PINS.json'] = pin(source / 'SOURCE_PINS.json')
        workflow = self.args.expected_workflow
        require(re.fullmatch(r't3-classic-expectations-delivery-v[12]\.yml', workflow) is not None
            and [name for name in local_pins['files'] if name.endswith('.yml')] == [workflow], 'one explicit exact pinned active delivery workflow')
        expected_remote['.github/workflows/' + workflow] = local_pins['files'][workflow]
        checked = {row['path']: row['actual'] for row in remote['checks']}
        require(len(remote['checks']) == len(checked) == 24 and checked == expected_remote, 'exact remote24source/pin/activeworkflow roster')
        manifest = read(self.payload / 'STRUCTURAL_MANIFEST.json')
        actual = self.inventory(self.payload).copy()
        actual.pop('STRUCTURAL_MANIFEST.json')
        require(actual == manifest['files'] and len(actual) == 193, 'complete193source payload manifest')
        frozen_manifest = read(self.args.frozen_payload / 'STRUCTURAL_MANIFEST.json')
        require(manifest == frozen_manifest and actual == {k: v for k, v in self.inventory(self.args.frozen_payload).items()
            if k != 'STRUCTURAL_MANIFEST.json'}, 'actual payload equals reviewed frozen payload')
        for name, wanted in actual.items():
            require(wanted['bytes'] <= 64 * 1024**2, '64MiB source member boundary')
        #10host/control +65baseline files, including baseline root metadata.
        base_manifest = read(self.args.baseline_payload / 'STRUCTURAL_MANIFEST.json')['files']
        unchanged = {name: value for name, value in base_manifest.items() if name.startswith(('host/', 'control/',
            'completion1009/candidates/lean_production_native_projection_v1/'))}
        require(len(unchanged) == 75 and len([name for name in unchanged if name.startswith(('host/', 'control/'))]) == 10
            and all(actual.get(name) == value for name, value in unchanged.items()), 'unchanged10hostcontrol65baseline source bytes')
        ready = read(self.evidence / 'BUILD_READY.json')
        self.ready, self.image = ready, ready['image_id']
        installed = self.evidence / 'installed'
        require(self.inventory(installed) == ready['installed_inventory'] == read(self.evidence / 'ACTUAL_BUILD_INVENTORY.json'), 'all actual installed source/C/object/ELF bytes')
        parent_lock = read(self.payload / 'PARENT_SOURCE_LOCK.json')
        require(parent_lock['image'] == PARENT and len(parent_lock['candidate_files']) == 115
            and self.inventory(installed / 'completion1009/candidates/classic_native_kernels_v1') == parent_lock['candidate_files'], 'unchanged115parent source/native artifact bytes')
        for suffix in ('', '-after'):
            require(self.inventory(self.evidence / ('installed' + suffix)) == ready['installed_inventory']
                and self.inventory(self.evidence / ('installed-harness' + suffix)) == ready['harness_inventory']
                and self.inventory(self.evidence / ('installed-licenses' + suffix)) == ready['licenses_inventory'], 'actual beforeafter installed bytes immutable')
        require(self.inventory(self.evidence / 'installed-harness') == self.inventory(self.payload / 'harness')
            and pin(installed / 'delivery_entry.py') == pin(self.payload / 'harness/delivery_entry.py')
            and pin(self.evidence / 'installed-licenses/LICENSE-SUBMISSION') == pin(self.payload / 'harness/LICENSE-SUBMISSION'), 'actual final public entry/harness/BSD3grant source')
        before, after = read(self.evidence / 'before/IMAGE.json'), read(self.evidence / 'after/IMAGE.json')
        require(before == after and before['Id'] == self.image and before['Config']['Entrypoint'] == ENTRY
            and before['Config'].get('Cmd') in ([], None), 'beforeafter image/default ENTRY immutable')
        config = before['Config']
        require(config['User'] == '65534:65534' and config['WorkingDir'] == '/output' and not config.get('Volumes')
            and config['Labels']['qfbench2.interface_version'] == '2.0' and config['Labels']['qfbench2.license'] == 'BSD-3-Clause'
            and config['Labels']['org.opencontainers.image.licenses'] == 'BSD-3-Clause', 'actual submission image metadata contract')
        construction = read(installed / 'structural-v2-construction/CONSTRUCTION_RESULT.json')
        require(construction['all_passed'] is True and construction['participant_imported'] is construction['market_executed'] is False
            and [(row['arm'], row['label']) for row in construction['commands']] == [('expectations', 'translation'), ('expectations', 'native-build')], 'one translation and native build')
        for row in construction['commands']:
            log = installed / 'structural-v2-construction' / (row['arm'] + '-' + row['label'] + '.log')
            require(row['returncode'] == 0 and row['timed_out'] is False and pin(log) == row['log'] and log.stat().st_size < 16 * 1024**2, 'complete finite construction raw log')
        locks = read(self.payload / 'CANDIDATE_SOURCE_LOCK.json')['arms']
        require(set(locks) == {'expectations'} and locks['expectations']['source_receipt_sha256'] == CANDIDATE_SHA, 'one exact frozen expectations candidate')
        lock = locks['expectations']
        candidate = installed / 'completion1009/candidates' / lock['candidate']
        receipt = read(candidate / 'SOURCE_PREPARATION_RECEIPT_v1.json')
        require(pin(candidate / 'SOURCE_PREPARATION_RECEIPT_v1.json')['sha256'] == CANDIDATE_SHA and len(receipt['files']) == 107, 'actual107frozen candidate source authority')
        for row in receipt['files']:
            require(pin(candidate / row['path']) == {key: row[key] for key in ('bytes', 'sha256')}, 'all actual candidate source members')
        modules = {'abides_fork.agents': 'runtime/abides_fork/agents.py', 'abides_fork.config': 'runtime/abides_fork/config.py',
            'abides_markets.agents.exchange_agent': 'runtime/vendor/abides/abides-markets/abides_markets/agents/exchange_agent.py',
            'abides_markets.oracles.sparse_mean_reverting_oracle': 'runtime/vendor/abides/abides-markets/abides_markets/oracles/sparse_mean_reverting_oracle.py',
            'abides_markets.orders': 'runtime/vendor/abides/abides-markets/abides_markets/orders.py',
            'abides_core.message': 'runtime/vendor/abides/abides-core/abides_core/message.py'}
        for module in ('market', 'query', 'order', 'orderbook'):
            modules['abides_markets.messages.' + module] = 'runtime/vendor/abides/abides-markets/abides_markets/messages/' + module + '.py'
        for module, filename in modules.items():
            tree = ast.parse((candidate / filename).read_bytes())
            classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
            if module == 'abides_markets.agents.exchange_agent':
                exchange = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ExchangeAgent')
                classes.update(node.name for node in exchange.body if isinstance(node, ast.ClassDef))
            require(OBJECT_CLASSES[module].issubset(classes), 'finite graph original class roster bound to actual source: ' + module)
        spec, build, translation = [read(candidate / name) for name in ('compile_spec.json', 'build/BUILD_RECEIPT.json', 'translation/TRANSLATION_RECEIPT.json')]
        require(spec['compile_flags'] == ['-O2', '-fPIC', '-fno-fast-math', '-ffp-contract=off']
            and build['ABI'] == read(HERE / 'COUNTED_AUDIT_PLAN_v1.json')['envelope']['ABI']
            and build['build_succeeded'] is True and build['extension_build_count'] == 1 and translation['translation_succeeded'] is True, 'actual strict flags/ABI/one successful build')
        for report in (build, translation):
            require(report['source_receipt_sha256'] == CANDIDATE_SHA and report['runtime_pins_sha256'] == pin(candidate / 'RUNTIME_PINS.json')['sha256']
                and report['compile_spec_sha256'] == pin(candidate / 'compile_spec.json')['sha256'] and report['dependencies'] == spec['dependencies']
                and report['participant_imported'] is report['market_executed'] is False, 'actual build dependency/source/no-market authority')
        require(build['ambient_flags'] == construction['ambient_flags'] and not any(flag in value for value in build['ambient_flags'].values()
            for flag in ('-ffast-math', '-Ofast', '-funsafe-math-optimizations', '-ffinite-math-only', '-freciprocal-math', '-fassociative-math')), 'strict ambient numeric flags')
        for name in ('translation', 'build'):
            require(self.inventory(candidate / name) == construction['partial_artifacts']['expectations'][name], 'all actual generated C/object/ELF artifact bytes')
        require(self.inventory(candidate / 'build/objects') and len(build['extensions']) == 1, 'actual native compiler objects and extension')
        for ext in build['extensions']:
            elf = candidate / 'build' / ext['path']
            require(pin(elf) == {key: ext[key] for key in ('bytes', 'sha256')} and ext['module'] == 'dynamic_arena_chain', 'actual ELF source receipt')
            with elf.open('rb') as stream:
                header = stream.read(20)
            require(header[:6] == b'\x7fELF\x02\x01' and int.from_bytes(header[18:20], 'little') == 62, 'actual ELF64littleamd64')
        for generated in translation['generated_C']:
            file = candidate / 'translation' / generated['path']
            copies = list((candidate / 'build/generated').rglob(file.name))
            require(pin(file) == {key: generated[key] for key in ('bytes', 'sha256')} and len(copies) == 1 and pin(copies[0]) == pin(file), 'full translationC equals compilerC')
        expectation_pin = build['expectations']
        expectation_file = candidate / 'build' / expectation_pin['path']
        require(expectation_pin['source_count'] == 22 and expectation_pin['artifact_count'] == 45
            and pin(expectation_file) == {key: expectation_pin[key] for key in ('bytes', 'sha256')}, 'actual22source45artifact expectation manifest')
        expectations = read(expectation_file)
        require(expectations['participant_imported'] is expectations['market_executed'] is expectations['admission_cached'] is False
            and len(expectations['sources']) == 22, 'expectation byte artifacts do not store permanent live admission')
        artifacts = {'EXPECTATIONS.json'}
        for row in expectations['sources']:
            require(pin(candidate / 'runtime' / row['source']) == {'bytes': row['source_bytes'], 'sha256': row['source_sha256']}, 'expectation actual source pin')
            for name in ('code', 'defaults'):
                value = row[name]
                require(pin(expectation_file.parent / value['path']) == {key: value[key] for key in ('bytes', 'sha256')}, 'opaque generated expectation artifact bytes')
                artifacts.add(value['path'])
        require(set(self.inventory(expectation_file.parent)) == artifacts and len(artifacts) == 45, 'complete exact45expectation artifacts')
        tree = ast.parse((candidate / 'control_graph.py').read_bytes())
        snapshot = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'snapshot')
        roots = next(node.value for node in ast.walk(snapshot) if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == 'roots' for target in node.targets))
        keys = tuple(ast.literal_eval(key) for key in roots.keys)
        require(keys == ROOT_KEYS[:-2], 'source-bound original20initial graph roots')
        counters = tuple(ast.literal_eval(target.slice) for node in ast.walk(snapshot) if isinstance(node, ast.Assign)
            for target in node.targets if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id == 'roots')
        require(counters == ROOT_KEYS[-2:], 'source-bound original globalID counters')
        self.report['authority']['harness_source_pins'] = pin(source / 'SOURCE_PINS.json')
        self.report['counts'].update(candidate_source_files=107, unchanged_parent_files=115, unchanged_host_control_files=10,
            unchanged_baseline_files=65, payload_source_files=193, expectation_sources=22, expectation_artifacts=45, native_extension_builds=1)

    def copy_lifecycle(self):
        labels = [('installed-source-copy', '/opt/classic-native-kernels-v1'), ('harness-source-copy', '/opt/t3-classic-structural-v2'),
            ('licenses-source-copy', '/licenses'), ('installed-after-copy', '/opt/classic-native-kernels-v1'),
            ('harness-after-copy', '/opt/t3-classic-structural-v2'), ('licenses-after-copy', '/licenses')]
        identities = set()
        for label, remote in labels:
            row = read(self.evidence / (label + '.json'))
            cleanup = row['cleanup']
            require(row['container_never_started'] is True and row['timing_included'] is False and cleanup['settled'] is cleanup['removed'] is cleanup['final_absent'] is True
                and cleanup['errors'] == [], 'never-started owned copy exact cleanup')
            require(cleanup['container_id'] not in identities, 'unique owned source-copy container')
            identities.add(cleanup['container_id'])
            copies = []
            for command in row['commands']:
                self.command(command, not (command['argv'][1] == 'inspect' and command['returncode'] == 1))
                require(command['argv'][1] not in ('start', 'exec', 'restart'), 'source copy container never executed')
                if command['argv'][1] == 'cp':
                    copies.append(command)
                    require(command['argv'][2] == cleanup['name'] + ':' + remote and command['source_copy_only'] is True
                        and command['source_file_hard_bytes'] == 64 * 1024**2 and command['per_log_file_hard_bytes'] == 16 * 1024**2, 'actual exact source-copy roots and caps')
                if command['argv'][1] == 'inspect' and command['returncode'] == 0:
                    values = read(self.path(command['stdout']['path']))
                    require(len(values) == 1, 'one actual copy inspected identity')
                    value = values[0]
                    require(value['Id'] == cleanup['container_id'] and value['Image'] == self.image and value['Name'] == '/' + cleanup['name']
                        and value['Config']['Labels']['qfbench2.t3.verifier_owner'] == cleanup['owner'] and value['State']['Status'] == 'created'
                        and value['State']['Pid'] == 0 and value['State']['Running'] is False
                        and value['State']['StartedAt'] == value['State']['FinishedAt'] == '0001-01-01T00:00:00Z', 'raw actual owned copy never started')
            require(len(copies) == 1 and row['commands'][0]['argv'][1] == 'create', 'one actual create/copy each')
            first = row['commands'][0]
            require(first['argv'] == ['docker', 'create', '--name', cleanup['name'], '--label',
                'qfbench2.t3.verifier_owner=' + cleanup['owner'], '--pull', 'never', self.image]
                and self.path(first['stdout']['path']).read_text() == cleanup['container_id'] + '\n', 'actual exact owned source-copy creation')
            operations = [command['argv'][1] for command in row['commands']]
            require(operations.count('create') == operations.count('cp') == operations.count('rm') == 1
                and set(operations).issubset({'create', 'inspect', 'cp', 'rm'}), 'exact copy lifecycle with one creation/copy/removal')
            require(any(command['argv'][1:] == ['rm', cleanup['name']] and command['returncode'] == 0
                for command in row['commands']), 'actual exact owned source-copy removal')
            final = row['commands'][-1]
            require(final['argv'][1:] == ['inspect', cleanup['name']] and final['returncode'] == 1
                and self.path(final['stdout']['path']).read_bytes() == b'[]\n'
                and self.path(final['stderr']['path']).read_text() == 'Error: No such object: ' + cleanup['name'] + '\n', 'actual final copy absence')
        self.report['counts'].update(copy_containers=6, copy_containers_started=0)

    def controls(self):
        self.control_groups()
        rosters = read(HERE / 'CONTROL_CASE_ROSTERS_v1.json')
        candidate = self.evidence / 'installed/completion1009/candidates/classic_build_expectations_v1'
        require(rosters['source_receipt_sha256'] == CANDIDATE_SHA and all(pin(candidate / name) == value
            for name, value in rosters['source_files'].items()), 'saved case rosters tied to exact actual frozen source')
        for arm in ARMS:
            execution = read(self.evidence / 'CONTROLS.json')[arm]['execution']
            require(execution['effective_config']['Config']['Cmd'] == ['-B', '/opt/t3-classic-structural-v2/controls_entry.py',
                'simulate', '--config', '/input/scenario.json', '--out', '/output/trace.parquet'], 'actual exact controls entry and public arguments')
            require(0 < execution['attach']['timeout_sec'] <= 4800, 'actual finite control timeout')
            out = self.evidence / 'controls' / arm / 'output/controls'
            result = read(out / 'STRUCTURAL_CONTROL_RESULT.json')
            require(result['arm'] == arm and result['all_passed'] is True and result['timing_included'] is result['rankable'] is False, 'actual untimed control source execution result')
            candidate_name = 'classic_native_kernels_v1' if arm == 'parent' else 'classic_build_expectations_v1'
            remote = '/opt/classic-native-kernels-v1/completion1009/candidates/' + candidate_name
            baseline = '/opt/classic-native-kernels-v1/completion1009/candidates/lean_production_native_projection_v1/runtime'
            common = ['--baseline-runtime', baseline, '--runtime', remote + '/runtime', '--build', remote + '/build']
            commands = [('native-fixtures.log', ['/usr/local/bin/python', '-B', remote + '/controls/native_output_fixtures_v1.py', *common, '--out', '/output/controls/native-fixtures']),
                ('children.log', ['/usr/local/bin/python', '-B', remote + '/controls/controls.py', *common, '--config', '/output/controls/scenario.json', '--out', '/output/controls/children'])]
            if arm == 'expectations':
                commands.append(('extra.log', ['/usr/local/bin/python', '-B', remote + '/controls/build_expectation_controls_v1.py',
                    '--runtime', remote + '/runtime', '--build', remote + '/build', '--out', '/output/controls/extra']))
            require(len(result['commands']) == len(commands), 'complete exact untimed controller command count')
            for row, (log, wanted) in zip(result['commands'], commands):
                require(row['command'] == wanted and row['returncode'] == 0 and pin(out / log) == row['log'], 'actual full control source command/rawlog binding')
            fixture = read(out / 'native-fixtures/native/FIXTURE_RECEIPT.json')
            for field in ('direct_clone_controls', 'classic_latency_controls', 'classic_source_controls'):
                require([row['case'] for row in fixture[field]['cases']] == rosters['rosters'][field], 'complete exact finite control case roster: ' + field)
            if arm == 'expectations':
                extra = read(out / 'extra/BUILD_EXPECTATION_CONTROLS.json')
                require([row['case'] for row in extra['cases']] == rosters['rosters']['expectation_negative_controls'], 'complete exact30expectation negatives')
            saved = read(self.evidence / 'controls' / arm / 'RUN_RESULT.json')
            output = self.evidence / 'controls' / arm / 'output'
            require(saved['passed'] is True and saved['execution'] == execution and saved['control_result'] == result
                and saved['actual_output_directory_bytes'] == sum(value['bytes'] for value in self.inventory(output).values()) <= 256 * 1024**2, 'actual complete control output/lifecycle/result binding')
            children = self.evidence / 'controls' / arm / 'output/controls/children'
            for name in ('original', 'light_canonical', 'light_dynamic', 'light_dynamic_repeat', 'decline_trace', 'decline_message_trace'):
                self.graph(children / name / 'STATE.json', True)
        self.report['counts'].update(control_containers=2, control_children=12, control_gates=16, serializer_fixture_Parquets=28,
            clone_cases=70, latency_cases=284, source_cases=16, expectation_negative_cases=30)

    def diagnostic(self):
        self.plan = read(self.evidence / 'REFERENCE_PLAN.json')
        self.items = {item['unit']: item for item in self.plan['units']}
        require(len(self.items) == 71 and self.plan['all_roster_units'] == self.plan['selected_units'] == 71
            and self.plan['reference_frame_count'] == 190 and set(UNITS).issubset(self.items), 'exact full71original reference plan')
        original = read(self.args.baseline_reference_plan)
        original_items = {item['unit']: item for item in original['units']}
        require(set(original_items) == set(self.items) and original['reference_frame_count'] == 190, 'exact previously verified official71reference roster')
        for unit, item in self.items.items():
            require(all(item[key] == original_items[unit][key] for key in ('shape', 'subs', 'input_sha256', 'reference_sha256')), 'exact unchanged official input/reference unit content')
        rows = read(self.evidence / 'DIAGNOSTIC_RESULTS.json')
        require([(row['unit'], row['arm']) for row in rows] == [(unit, arm) for unit in UNITS for arm in ARMS], 'exact12diagnostic schedule')
        state_cells, frames, graphs = {}, 0, 0
        for row in rows:
            require(row['passed'] is True and row['stage'] == 'diagnostic' and row['timing_included'] is False and row['rankable'] is False, 'untimed diagnostic row')
            self.execution(row['execution'], self.image, 'diagnostic')
            verb = 'simulate' if self.items[row['unit']]['shape'] == 'single' else 'simulate-batch'
            public_args = [verb, '--config', '/input/scenario.json', '--out', '/output/trace.parquet'] if verb == 'simulate' else [verb, '--batch-dir', '/input/scenarios', '--out-dir', '/output']
            require(row['execution']['effective_config']['Config']['Cmd'] == ['-B', '/opt/t3-classic-structural-v2/diagnostic_entry.py',
                *public_args, '--mode', row['arm']], 'actual exact diagnostic route/publicargs/arm')
            require(0 < row['execution']['attach']['timeout_sec'] <= 3600 and row['execution']['total_with_cleanup_wall_sec'] < 3660, 'actual finite diagnostic timeout')
            self.output(row, self.items[row['unit']], diagnostic=True)
            self.diagnostic_stream(row)
            item = self.items[row['unit']]
            scenarios = {None: 'scenario.json'} if item['shape'] == 'single' else {entry['sub']: entry['scenario_file'] for entry in item['subs']}
            require({record['sub'] for record in row['state_receipts']} == {record['sub'] for record in row['admission_witnesses']} == set(scenarios), 'each actual complete diagnostic market')
            state_cells[row['arm'], row['unit']] = {record['sub']: pin(self.path(record['path'])) for record in row['state_receipts']}
            frames += len([name for name in self.inventory(self.path(row['output'])) if name.endswith('.parquet')])
            graphs += len(row['state_receipts'])
            for record in row['admission_witnesses']:
                relative = scenarios[record['sub']]
                staged = next(value for value in row['execution']['staged_inputs'] if value['staged'].endswith('/' + relative))
                scenario = read(self.path(staged['staged']))
                actual, witness = record['actual_execution'], record['witness']
                lock = read(self.payload / 'PARENT_SOURCE_LOCK.json')['candidate_files'] if row['arm'] == 'parent' else read(self.payload / 'CANDIDATE_SOURCE_LOCK.json')['arms'][row['arm']]['source_files']
                require(record['arm'] == row['arm'] and record['timing_included'] is record['market_rerun'] is False
                    and record['scenario_sha256'] == item['input_sha256'][relative] and record['production_source_sha256'] == lock['production_cli.py']['sha256'], 'actual diagnostic source/input/arm binding')
                require(actual['scenario_id'] == str(scenario['scenario_id']) and actual['seed'] == int(scenario['seed'])
                    and witness['selected_kernel'] == actual['actual_kernel'].rsplit('.', 1)[-1] and witness['native_admitted'] == actual['actual_authority_migration'], 'actual diagnostic engine/input selection')
                state = next(value for value in row['state_receipts'] if value['sub'] == record['sub'])
                require(state['scenario_id'] == actual['scenario_id'] and state['seed'] == actual['seed'] and state['arm'] == row['arm']
                    and all(state[key] is True for key in ('full_original_control_graph', 'full_actual_STATE_bytes_retained', 'graph_output_readonly',
                        'observer_finished', 'kernel_and_summary_bindings_restored', 'index_witness_recorded_before_business_alias_snapshot'))
                    and state['rankable'] is state['timing_included'] is False, 'source-bound complete readonly graph/restored episode')
                exchange = scenario['exchange_config']
                protocol = bool(exchange.get('protocol_enforcement', False))
                require(actual['actual_stp_policy'] == (str(exchange['stp_policy']) if protocol and exchange.get('stp_policy') else None)
                    and actual['actual_pipeline_delay'] == (int(exchange.get('ack_delay_ns', 0)) if protocol else 0)
                    and actual['actual_computation_delay'] == (int(exchange.get('compute_delay_ns', 0)) if protocol else 0), 'actual STP/protocol/delay contract')
                target = self.path(row['output']) if record['sub'] is None else self.path(row['output']) / record['sub']
                require(witness['actual_trace_sha256'] == pin(target / 'trace.parquet')['sha256'] and witness['actual_trace_rows'] == read(target / 'events.json')['n_events']
                    and all(witness[key] is True for key in ('source_authenticated', 'observer_admitted', 'native_admitted', 'projectors_admitted', 'native_output_pair'))
                    and witness['market_rerun'] is False and witness['selected_kernel'] == 'NativeOwnerKernel', 'actual full trace/source/native/output witness')
        require(graphs == 20 and frames == 40, 'all20complete diagnostic STATE graphs and40Parquets')
        for unit in UNITS:
            require(state_cells['parent', unit] == state_cells['expectations', unit], 'every full expectations market graph byte equals parent')
        for row in rows:
            for record in row['state_receipts']:
                self.graph(self.path(record['path']), True)
        self.report['counts'].update(diagnostic_containers=12, diagnostic_gates=48, diagnostic_Parquets=40, diagnostic_STATE_graphs=20)

    def ordinary_runs(self):
        rows = read(self.evidence / 'RAW_RESULTS.json')
        schedule = [(0, unit) for unit in sorted(self.items)] + [(repeat, unit) for repeat in range(1, 5) for unit in FIVE]
        require(len(rows) == 91 and [(row['repeat'], row['unit']) for row in rows] == schedule, 'exact91ordinary full71schedule')
        recorded = read(self.evidence / 'ORDINARY_SCHEDULE.json')
        require(recorded['public_entry'] == ENTRY and recorded['runs_count'] == 91 and recorded['expected_gates'] == 364
            and recorded['expected_actual_Parquet_copies'] == 262 and recorded['full71'] is True, 'original counted public schedule receipt')
        require(recorded['runs'] == [{'index': index, 'repeat': repeat, 'unit': unit, 'arm': 'expectations', 'internal_mode': False}
            for index, (repeat, unit) in enumerate(schedule)], 'every actual counted scheduled cell')
        first, cells, frames, verbs = {}, {}, 0, set()
        for index, row in enumerate(rows):
            repeat, unit = schedule[index]
            require(row['passed'] is True and row['stage'] == 'one' and row['arm'] == row['direct_arm'] == 'expectations'
                and row['actual_public_default_entry'] is True and row['order'] == index and row['warmup'] is (repeat == 0)
                and row['timing_included'] is (repeat > 0) and row['rankable'] is False, 'actual public ordinary labels')
            duration = self.execution(row['execution'], self.image, 'one')
            require(0 < row['execution']['attach']['timeout_sec'] <= 300 and duration <= 300
                and row['execution']['attach']['per_log_file_hard_bytes'] == 16 * 1024**2, 'actual300second ordinary timeout/log bound')
            out = self.output(row, self.items[unit])
            count = row['reference_checks']['actual_events']
            require(type(count) is int and count > 0 and row['actual_events'] == count and math.isfinite(row['EPS'])
                and abs(row['settled_container_runtime_sec'] - duration) < 1e-9 and abs(row['EPS'] - count / duration) <= 1e-9 * max(1, row['EPS']), 'ordinary daemon duration/full actual counts/EPS')
            config = row['execution']['effective_config']['Config']
            cmd = config['Cmd']
            verb = 'simulate' if self.items[unit]['shape'] == 'single' else 'simulate-batch'
            wanted = [verb, '--config', '/input/scenario.json', '--out', '/output/trace.parquet'] if verb == 'simulate' else [verb, '--batch-dir', '/input/scenarios', '--out-dir', '/output']
            require(cmd == wanted, 'actual exact canonical public option schema and no internal overrides')
            verbs.add(verb)
            require(row['actual_output_directory_bytes'] == sum(value['bytes'] for value in self.inventory(out).values()) <= 256 * 1024**2, 'actual finite ordinary output tree')
            previous = first.setdefault(unit, out)
            require(set(self.inventory(previous)) == set(self.inventory(out)), 'complete samearm repeat output roster')
            for name in self.inventory(out):
                if name.endswith('.parquet'):
                    require(pin(out / name) == pin(previous / name), 'full repeat Parquet byte equality')
                else:
                    require({k: v for k, v in read(out / name).items() if k not in DROP} == {k: v for k, v in read(previous / name).items() if k not in DROP}, 'full stable repeat sidecars')
            cells[unit, repeat] = row
            frames += len([name for name in self.inventory(out) if name.endswith('.parquet')])
        require(len(first) == 71 and frames == 262 and verbs == {'simulate', 'simulate-batch'}, 'full71/262Parquets/bothactual public verbs')
        pairs = read(self.evidence / 'PAIRS.json')
        require([(row['repeat'], row['unit']) for row in pairs] == schedule and all(row['same_arm_repeat']['passed'] is True for row in pairs), 'all91fullrepeat raw pair receipts')
        medians = [{'unit': unit, 'total_runs': 5, 'warmup_discarded': 1, 'measured_runs': 4,
            'median_EPS': statistics.median(cells[unit, repeat]['EPS'] for repeat in range(1, 5))} for unit in FIVE]
        mean = statistics.mean(row['median_EPS'] for row in medians)
        summary = read(self.evidence / 'SUMMARY.json')
        require(summary['all_passed'] is True and summary['failure'] is None and summary['ordinary_runs'] == 91
            and summary['ordinary_official_gate_passes'] == 364 and summary['ordinary_actual_Parquet_copies'] == 262
            and summary['full71'] is True and summary['untimed_diagnostic_runs'] == 12 and summary['untimed_diagnostic_gate_passes'] == 48
            and summary['untimed_complete_market_STATE_graphs'] == 20 and summary['untimed_control_containers'] == 2
            and summary['total_actual_executions'] == 105 and summary['both_actual_default_entry_public_verbs'] == sorted(verbs), 'all complete summary counts recomputed')
        require(all(summary[key] is True for key in ('public_references_unchanged', 'image_immutable', 'installed_artifacts_unchanged',
            'all_settled_removed', 'actual_serial_execution_intervals', 'diagnostic_control_and_construction_timings_excluded'))
            and summary['official_submission'] is summary['rankable'] is summary['threshold_232000_verified'] is False,
            'complete immutable/reference/lifecycle summary flags')
        require(summary['repeat_units'] == medians and summary['five_unit_mean_of_median_EPS'] == mean, 'sampled timing medians/mean from actual ordinary daemon intervals')
        self.report['counts'].update(official_units=71, ordinary_runs=91, ordinary_gates=364, ordinary_Parquets=262,
            ordinary_measured_runs=20, ordinary_first_pass_runs=71, unique_Parquet_contents_full_decoded=len(self.decoded))
        self.report['performance'].update(measured_runs=20, unit_medians=medians, five_unit_mean_of_median_EPS=mean)

    def timing_finish(self):
        self.intervals.sort()
        require(len(self.intervals) == 105 and len({row[2] for row in self.intervals}) == 105
            and all(left[1] < right[0] for left, right in zip(self.intervals, self.intervals[1:])), 'all105actual market container intervals serial')
        recorded = read(self.evidence / 'SERIAL_INTERVALS.json')
        require(recorded['intervals'] == [list(row) for row in self.intervals] and recorded['ordinary'] == 91
            and recorded['untimed_diagnostics'] == 12 and recorded['untimed_controls'] == 2
            and recorded['all_actual_execution_intervals_serial'] is recorded['source_copy_containers_never_started'] is True
            and recorded['rankable'] is False, 'saved full serial interval receipt actual correspondence')
        self.report['counts']['actual_market_containers'] = 105
        self.report['all_execution_checks_passed'] = self.report['performance_usable'] = True

    def publication(self):
        pub = read(self.evidence / 'PUBLICATION.json')
        require(re.fullmatch(r'ghcr\.io/kouzhizhuo/agenthon-t3-classic@sha256:[0-9a-f]{64}', pub['image']) is not None
            and pub['image_id'] == self.image and pub['anonymous_pull_passed'] is pub['tested_image_id_equal'] is True
            and pub['official_submission'] is False, 'actual anonymously pullable immutable tested classic repository image')
        self.report['authority']['public_image'] = pub['image']
        tag = 'ghcr.io/kouzhizhuo/agenthon-t3-classic:delivery-expectations-%d-%d' % (self.args.expected_run_id, self.args.expected_run_attempt)
        metadata = read(self.evidence / 'published-metadata/IMAGE.json')
        raw_meta = read(self.evidence / 'published-metadata/000-image-inspect.stdout.txt')
        require(raw_meta == [metadata] and metadata['Id'] == self.image and tag in metadata['RepoTags'] and pub['image'] in metadata['RepoDigests'], 'actual published raw metadata unique tag/tested digest binding')
        before = read(self.evidence / 'before/IMAGE.json')
        require(all(metadata[key] == before[key] for key in ('Id', 'Config', 'RootFS', 'Os', 'Architecture', 'Size')), 'actual published inspected image immutable tested config/rootfs')
        pull_out = self.evidence / 'publication-commands/000-anonymous-published-pull.stdout.txt'
        pull_err = self.evidence / 'publication-commands/000-anonymous-published-pull.stderr.txt'
        require(pull_out.stat().st_size < 16 * 1024**2 and pull_err.stat().st_size < 16 * 1024**2, 'actual complete finite anonymous pull streams')
        pull_text = pull_out.read_text() + pull_err.read_text()
        digest = pub['image'].rsplit('@', 1)[1]
        require('Digest: ' + digest in pull_text and ('Status: Downloaded newer image for ' + tag in pull_text
            or 'Status: Image is up to date for ' + tag in pull_text), 'actual anonymous pull raw success/digest/tag evidence')
        push_log = self.evidence / 'registry-push.log'
        require(push_log.is_file() and push_log.stat().st_size < 16 * 1024**2, 'actual registry push log retained')
        push_text = push_log.read_text()
        require('delivery-expectations-%d-%d: digest: %s' % (self.args.expected_run_id, self.args.expected_run_attempt, digest) in push_text,
            'actual unique runattempt tag push digest evidence')
        self.report['authority']['publication_streams'] = {str(path.relative_to(self.artifact)): pin(path) for path in
            (pull_out, pull_err, push_log, self.evidence / 'published-metadata/000-image-inspect.stdout.txt', self.evidence / 'published-metadata/000-image-inspect.stderr.txt')}
        self.report['limitations'].append('The frozen harness retains raw anonymous-pull/image-inspect streams and source-bound publication success, but does not save a separate per-command JSON returncode receipt for those publication calls.')
        if self.args.registry_readback is None:
            self.report['pending'].append('Actual anonymous registry manifest/config/layer saved byte readback')
            return
        registry = read(self.args.registry_readback)
        require(registry['schema'] == 't3-anonymous-registry-byte-readback-v1' and registry['image'] == pub['image']
            and registry['tested_image_id'] == self.image and registry['anonymous'] is registry['all_passed'] is True
            and registry['participant_executed'] is registry['native_compiled'] is False, 'explicit actual anonymous registry evidence binding')
        root = self.args.registry_readback.parent
        def content(row):
            path = PurePosixPath(row['path'])
            require(not path.is_absolute() and '..' not in path.parts and '\\' not in str(path), 'safe saved registry byte path')
            file = root / str(path)
            require(pin(file) == {key: row[key] for key in ('bytes', 'sha256')}, 'every actual registry byte digest/size')
            attempts = row['attempts_receipt']
            attempt_path = PurePosixPath(attempts['path'])
            require(not attempt_path.is_absolute() and '..' not in attempt_path.parts and '\\' not in str(attempt_path), 'safe saved registry attempts path')
            attempt_file = root / str(attempt_path)
            require(pin(attempt_file) == {key: attempts[key] for key in ('bytes', 'sha256')}
                and read(attempt_file) == row['requests'] and 1 <= len(row['requests']) <= 3, 'complete actual byte download attempts receipt')
            for index, request in enumerate(row['requests']):
                require(request['attempt'] == index + 1 and type(request['completed']) is bool, 'ordered actual download attempts')
            final = row['requests'][-1]
            require(final['completed'] is True and final['status'] == 200 and final['bytes'] == row['bytes'] and final['sha256'] == row['sha256'], 'actual complete public response200 bytes')
            return file
        manifest_file = content(registry['manifest'])
        require('sha256:' + pin(manifest_file)['sha256'] == pub['image'].rsplit('@', 1)[1], 'immutable manifest digest exact public reference')
        manifest = read(manifest_file)
        require(manifest['schemaVersion'] == 2 and 'config' in manifest and 'layers' in manifest, 'actual singleplatform distribution manifest')
        config_file = content(registry['config'])
        config = read(config_file)
        require(manifest['config']['digest'] == self.image == 'sha256:' + pin(config_file)['sha256']
            and manifest['config']['size'] == config_file.stat().st_size, 'actual manifest config equals tested image ID')
        require(len(registry['layers']) == len(manifest['layers']) and config['architecture'] == 'amd64' and config['os'] == 'linux', 'actual registry target platform/layer roster')
        image_config, raw_config = before['Config'], config['config']
        defaults = {'Hostname': '', 'Domainname': '', 'AttachStdin': False, 'AttachStdout': False, 'AttachStderr': False,
            'Tty': False, 'OpenStdin': False, 'StdinOnce': False, 'Image': ''}
        core = {'User', 'Env', 'Entrypoint', 'Cmd', 'Volumes', 'WorkingDir', 'Labels', 'OnBuild', 'ArgsEscaped', 'StopSignal', 'Healthcheck', 'Shell'}
        require(set(raw_config).issubset(core | set(defaults)) and set(image_config).issubset(core | set(defaults)), 'finite inspected/raw config schema; unknown fields refused')
        for key in set(raw_config) | set(image_config):
            if key in defaults:
                require(raw_config.get(key, defaults[key]) == image_config.get(key, defaults[key]) == defaults[key], 'explicit Docker default config field')
            else:
                left, right = raw_config.get(key), image_config.get(key)
                if key in ('Cmd', 'OnBuild', 'Volumes') and left in (None, []) and right in (None, []):
                    continue
                require(left == right, 'explicit raw registry/tested canonical config field: ' + key)
        diff_ids = []
        for descriptor, row in zip(manifest['layers'], registry['layers']):
            file = content(row)
            require(descriptor['digest'] == 'sha256:' + pin(file)['sha256'] and descriptor['size'] == file.stat().st_size, 'every actual complete registry layer digest/size')
            media_type = descriptor['mediaType']
            gzip_types = ('application/vnd.docker.image.rootfs.diff.tar.gzip', 'application/vnd.oci.image.layer.v1.tar+gzip')
            require(media_type in gzip_types + ('application/vnd.oci.image.layer.v1.tar',), 'finite inert supported layer compression')
            checksum, size = hashlib.sha256(), 0
            with (gzip.open(file, 'rb') if media_type in gzip_types else file.open('rb')) as stream:
                for block in iter(lambda: stream.read(1024**2), b''):
                    size += len(block)
                    require(size <= 16 * 1024**3, 'finite complete uncompressed layer byte boundary')
                    checksum.update(block)
            require(row['uncompressed'] == {'bytes': size, 'sha256': checksum.hexdigest()}, 'actual independently decoded complete layer diffID')
            diff_ids.append('sha256:' + checksum.hexdigest())
        require(config['rootfs']['type'] == 'layers' and config['rootfs']['diff_ids'] == diff_ids, 'allactual uncompressed layer chain exact config diffIDs')
        require(config['rootfs']['diff_ids'] == read(self.evidence / 'before/IMAGE.json')['RootFS']['Layers'], 'registry rootfs chain equals tested image rootfs')
        self.report['publication_passed'] = True


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--expected-zip-sha256', required=True)
    parser.add_argument('--expected-zip-bytes', type=int, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--expected-source-pins-sha256', required=True)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--expected-workflow', required=True)
    parser.add_argument('--remote-readback', type=Path, required=True)
    parser.add_argument('--frozen-payload', type=Path, required=True)
    parser.add_argument('--baseline-payload', type=Path, required=True)
    parser.add_argument('--baseline-reference-plan', type=Path, required=True)
    parser.add_argument('--expected-run-id', type=int, required=True)
    parser.add_argument('--expected-run-attempt', type=int, required=True)
    parser.add_argument('--remote-evidence-marker', default='expectations-delivery-evidence/')
    parser.add_argument('--registry-readback', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    require(sys.version_info >= (3, 9) and not args.out.exists() and args.out.parent.is_dir(), 'Python3.9plus and fresh explicit report output required')
    require(all(re.fullmatch('[0-9a-f]{64}', value) is not None for value in (args.expected_zip_sha256, args.expected_source_pins_sha256))
        and re.fullmatch('[0-9a-f]{40}', args.expected_head) is not None and args.expected_zip_bytes > 0, 'explicit final artifact/source/head authority')
    audit = Audit(args)
    stages = ('zip_manifest', 'source_build', 'copy_lifecycle', 'controls', 'diagnostic', 'ordinary_runs', 'timing_finish', 'publication')
    for stage in stages:
        try:
            getattr(audit, stage)()
            audit.report['completed_stages'].append(stage)
            print(stage, 'PASS' if stage != 'publication' or audit.report['publication_passed'] else 'PENDING', flush=True)
        except BaseException as error:
            audit.report['failures'].append({'stage': stage, 'type': type(error).__name__, 'message': str(error)})
            break
    audit.report['authority']['artifact'] = pin(args.zip)
    audit.report['all_passed'] = audit.report['all_execution_checks_passed'] and audit.report['publication_passed'] and not audit.report['failures'] and not audit.report['pending']
    audit.report['eligible_for_official_submission'] = audit.report['all_passed']
    audit.report['status'] = 'passed' if audit.report['all_passed'] else 'failed' if audit.report['failures'] else 'execution_pass_publication_pending'
    if audit.report['failures']:
        audit.report['performance_usable'] = False
    with args.out.open('x') as stream:
        stream.write(json.dumps(audit.report, sort_keys=True, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': audit.report['status'], 'all_passed': audit.report['all_passed'], 'counts': audit.report['counts'],
        'failures': audit.report['failures'], 'pending': audit.report['pending']}, sort_keys=True), flush=True)
    return 0 if audit.report['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
