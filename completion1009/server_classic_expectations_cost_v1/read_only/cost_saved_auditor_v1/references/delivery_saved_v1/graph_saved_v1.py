"""Decode the inert control_graph JSON format without reconstructing live objects."""
from collections import Counter
from datetime import datetime
import math
import re
import struct

from saved_base_v1 import require

ROOT_KEYS = ('agents', 'oracle', 'kernel_rng', 'latency', 'global_rng', 'ttl_messages',
    'deliver_seq', 'deliver_seq_by_key', 'current_time', 'current_causal_uid',
    'agent_current_times', 'agent_computation_delays', 'current_agent_additional_delay',
    'ledger', 'queue', 'observer', 'summary_log', 'mean_result_by_agent_type',
    'agent_count_by_type', 'custom_state', 'message_counter', 'order_counter')
DTYPE_BYTES = {'bool': 1, 'int8': 1, 'uint8': 1, 'int16': 2, 'uint16': 2,
    'int32': 4, 'uint32': 4, 'int64': 8, 'uint64': 8, 'float32': 4, 'float64': 8}
OBJECT_CLASSES = {
    'abides_fork.agents': {'NoiseTrader', 'ValueTrader', 'MarketMaker', 'MomentumTrader'},
    'abides_fork.config': {'ScenarioLatencyModel'},
    'abides_markets.agents.exchange_agent': {'ExchangeAgent', 'MetricTracker'},
    'abides_markets.oracles.sparse_mean_reverting_oracle': {'SparseMeanRevertingOracle'},
    'abides_markets.orders': {'LimitOrder', 'MarketOrder'},
    'original_mapping': {'OrderBook', 'PriceLevel'},
    'abides_core.message': {'WakeupMsg'},
    'abides_markets.messages.market': {'MarketClosePriceRequestMsg', 'MarketHoursRequestMsg', 'MarketHoursMsg', 'MarketClosePriceMsg', 'MarketClosedMsg'},
    'abides_markets.messages.query': {'QuerySpreadMsg', 'QuerySpreadResponseMsg'},
    'abides_markets.messages.order': {'LimitOrderMsg', 'CancelOrderMsg'},
    'abides_markets.messages.orderbook': {'OrderAcceptedMsg', 'OrderExecutedMsg', 'OrderCancelledMsg'},
}


class GraphAudit:
    def __init__(self):
        self.definitions, self.references, self.tags, self.random_states = {}, 0, Counter(), []

    def define(self, serial, node):
        require(type(serial) is int and serial == len(self.definitions), 'ordered unique graph definition serial')
        self.definitions[serial] = node

    def hex_bytes(self, value):
        require(type(value) is str and len(value) % 2 == 0 and re.fullmatch('[0-9a-f]*', value) is not None,
            'exact lowercase graph byte encoding')
        return bytes.fromhex(value)

    def visit(self, node):
        require(type(node) is list and node and type(node[0]) is str, 'tagged graph node required')
        tag = node[0]
        self.tags[tag] += 1
        if tag == 'ref':
            require(len(node) == 2 and type(node[1]) is int and node[1] in self.definitions, 'every graph alias resolves backward')
            self.references += 1
        elif tag in ('NoneType', 'str', 'int', 'bool'):
            wanted = {'NoneType': type(None), 'str': str, 'int': int, 'bool': bool}[tag]
            require(len(node) == 2 and type(node[1]) is wanted, 'exact original scalar type: ' + tag)
        elif tag == 'float':
            require(len(node) == 2 and type(node[1]) is str, 'exact graph float hex')
            value = float.fromhex(node[1])
            require(value.hex() == node[1], 'canonical scalar float representation')
        elif tag == 'bytes':
            require(len(node) == 2, 'bytes arity')
            self.hex_bytes(node[1])
        elif tag == 'Side':
            require(len(node) == 2 and node[1] in ('BID', 'ASK'), 'original Side enum value')
        elif tag == 'datetime':
            require(len(node) == 2 and type(node[1]) is str and datetime.fromisoformat(node[1]).isoformat() == node[1], 'exact datetime ISO')
        elif tag == 'timedelta':
            require(len(node) == 4 and all(type(v) is int for v in node[1:]) and 0 <= node[2] < 86400
                and 0 <= node[3] < 1000000, 'exact normalized timedelta')
        elif tag == 'binding':
            require(node == ['binding', 'builtins', 'list'], 'only inert admitted defaultdict list binding')
        elif tag == 'RandomState':
            require(len(node) == 3, 'RandomState node arity')
            self.define(node[1], node)
            self.visit(node[2])
            self.random_states.append(node[2])
        elif tag == 'ndarray':
            require(len(node) == 5 and type(node[2]) is str and type(node[3]) is list
                and all(type(v) is int and v >= 0 for v in node[3]), 'exact ndarray shape/dtype')
            self.define(node[1], node)
            if 'object' in node[2]:
                self.visit(node[4])
            else:
                count = math.prod(node[3])
                dtype = node[2]
                width = DTYPE_BYTES.get(dtype)
                if width is None:
                    match = re.fullmatch(r'([<>=|]?)([biuf])([1248])', dtype)
                    require(match is not None, 'finite admitted numeric ndarray dtype: ' + dtype)
                    width = int(match[3])
                require(len(self.hex_bytes(node[4])) == count * width, 'all exact ndarray cells retained')
        elif tag in ('list', 'tuple', 'deque', 'set', 'frozenset'):
            require(len(node) == 3 and type(node[2]) is list, 'original sequence arity')
            self.define(node[1], node)
            for child in node[2]:
                self.visit(child)
        elif tag in ('dict', 'defaultdict'):
            require(len(node) == (4 if tag == 'defaultdict' else 3), 'original mapping arity')
            self.define(node[1], node)
            if tag == 'defaultdict':
                self.visit(node[2])
            pairs = node[-1]
            require(type(pairs) is list, 'mapping ordered pairs')
            for pair in pairs:
                require(type(pair) is list and len(pair) == 2, 'mapping pair arity')
                self.visit(pair[0])
                self.visit(pair[1])
        elif re.fullmatch(r'(?:u?int(?:8|16|32|64)|float(?:16|32|64)|bool_)', tag):
            require(len(node) == 2, 'NumPy scalar arity')
            self.visit(node[1])
            base = self.resolve(node[1])
            require(base[0] == ('float' if tag.startswith('float') else 'bool' if tag == 'bool_' else 'int'), 'NumPy scalar exact primitive')
            if 'int' in tag:
                match = re.fullmatch(r'(u?)int(8|16|32|64)', tag)
                bits, unsigned = int(match[2]), bool(match[1])
                require((0 if unsigned else -(1 << (bits - 1))) <= base[1] < (1 << (bits if unsigned else bits - 1)), 'NumPy integer range')
        else:
            require(len(node) == 4 and tag in OBJECT_CLASSES and node[1] in OBJECT_CLASSES[tag]
                and type(node[3]) is list, 'original source-bound finite object encoding: ' + tag)
            self.define(node[2], node)
            names = []
            for pair in node[3]:
                require(type(pair) is list and len(pair) == 2 and type(pair[0]) is str and pair[0] != 'kernel', 'original object attributes')
                names.append(pair[0])
                self.visit(pair[1])
            require(names == sorted(set(names)), 'exact sorted unique object fields')

    def resolve(self, node):
        while node[0] == 'ref':
            node = self.definitions[node[1]]
        return node

    def number(self, node):
        node = self.resolve(node)
        if node[0] in ('int64', 'int32', 'uint32', 'float64', 'float32'):
            return self.number(node[1])
        require(node[0] in ('int', 'float'), 'exact numeric graph node')
        return float.fromhex(node[1]) if node[0] == 'float' else node[1]

    def integer(self, node, nullable=False, low=-(1 << 63), high=(1 << 63) - 1):
        node = self.resolve(node)
        if nullable and node == ['NoneType', None]:
            return None
        value = self.number(node)
        require(type(value) is int and low <= value <= high, 'exact integer graph field/range')
        return value

    def sequence(self, node, tag=None):
        node = self.resolve(node)
        require(node[0] in ((tag,) if tag else ('list', 'tuple', 'deque')), 'expected original graph sequence')
        return node[2]

    def mt19937(self, node):
        values = self.sequence(node, 'tuple')
        require(len(values) == 5 and self.resolve(values[0]) == ['str', 'MT19937'], 'original MT19937 five-item state')
        array = self.resolve(values[1])
        require(array[0] == 'ndarray' and array[2] == 'uint32' and array[3] == [624], 'all624MT19937uint32 words')
        words = struct.unpack('<624I', self.hex_bytes(array[4]))
        require(len(words) == 624, 'complete MT19937 words decoded')
        position, gaussian = self.number(values[2]), self.number(values[3])
        cache = self.number(values[4])
        require(type(position) is int and 0 <= position <= 624 and type(gaussian) is int and gaussian in (0, 1)
            and type(cache) is float and math.isfinite(cache), 'MT position/Gaussian-cache flag/value retained')

    def audit(self, graph):
        self.visit(graph)
        require(graph[:2] == ['dict', 0], 'original roots mapping serial0')
        roots = {}
        for key, value in graph[2]:
            require(key[0] == 'str' and key[1] not in roots, 'unique literal original root keys')
            roots[key[1]] = value
        require(tuple(roots) == ROOT_KEYS, 'exact22original graph root keys and order')
        expected_types = {'agents': 'list', 'global_rng': 'tuple', 'deliver_seq_by_key': 'dict', 'agent_current_times': 'list',
            'agent_computation_delays': 'list', 'ledger': 'list', 'queue': 'list', 'observer': 'dict', 'summary_log': 'list',
            'mean_result_by_agent_type': 'dict', 'agent_count_by_type': 'dict', 'custom_state': 'dict', 'kernel_rng': 'RandomState'}
        for field, tag in expected_types.items():
            require(self.resolve(roots[field])[0] == tag, 'exact original root type: ' + field)
        require(self.resolve(roots['latency'])[:2] == ['abides_fork.config', 'ScenarioLatencyModel']
            and self.resolve(roots['oracle'])[:2] == ['abides_markets.oracles.sparse_mean_reverting_oracle', 'SparseMeanRevertingOracle'], 'actual original latency/oracle class identity')
        for state in self.random_states:
            self.mt19937(state)
        self.mt19937(roots['global_rng'])
        require(self.resolve(roots['kernel_rng'])[0] == 'RandomState' and self.random_states, 'actual kernel RNG and finite original RNG states')
        ledger = self.sequence(roots['ledger'], 'list')
        for record in ledger:
            fields = self.sequence(record, 'tuple')
            require(len(fields) == 9, 'all complete nine-field original ledger rows')
            self.integer(fields[0], low=0)
            self.integer(fields[1], low=0, high=(1 << 31) - 1)
            self.integer(fields[2], low=0, high=(1 << 31) - 1)
            sent = self.integer(fields[3], nullable=True)
            received = self.integer(fields[4])
            latency = self.integer(fields[5], low=0)
            message_type = self.resolve(fields[6])
            require(message_type[0] == 'str' and message_type[1], 'exact original ledger message type')
            self.integer(fields[7], nullable=True, low=0)
            self.integer(fields[8], nullable=True, low=0)
            require((message_type[1] == 'AGENT_WAKEUP' and sent is None and latency == 0)
                or (message_type[1] != 'AGENT_WAKEUP' and sent is not None and received - sent == latency), 'original ledger time/latency relationship')
        queue = self.sequence(roots['queue'], 'list')
        for record in queue:
            fields = self.sequence(record, 'tuple')
            require(len(fields) == 4, 'complete original flattened queue record')
            self.integer(fields[0])
            self.integer(fields[1], low=0, high=(1 << 31) - 1)
            self.integer(fields[2], low=0, high=(1 << 31) - 1)
            message = self.resolve(fields[3])
            require(len(message) == 4 and (message[0] == 'abides_core.message' or message[0].startswith('abides_markets.messages.')), 'actual original queue message object')
            attrs = dict(message[3])
            require('message_id' in attrs, 'queued message complete original ID')
            self.integer(attrs['message_id'], low=0)
        agents = self.sequence(roots['agents'], 'list')
        require(all(self.resolve(agent)[:2] == ['abides_markets.agents.exchange_agent', 'ExchangeAgent']
            or (self.resolve(agent)[0] == 'abides_fork.agents' and self.resolve(agent)[1] in OBJECT_CLASSES['abides_fork.agents']) for agent in agents), 'actual finite source-bound original agent classes')
        self.integer(roots['current_causal_uid'], nullable=True, low=0)
        for field in ('agent_current_times', 'agent_computation_delays'):
            require(len(self.sequence(roots[field], 'list')) == len(agents), 'complete per-agent original clock/delay list')
            for value in self.sequence(roots[field], 'list'):
                self.integer(value)
        require(agents and self.resolve(roots['observer'])[0] == 'dict' and self.resolve(roots['custom_state'])[0] == 'dict', 'actual agents/observer/custom state roots')
        message_counter, order_counter = self.number(roots['message_counter']), self.number(roots['order_counter'])
        require(type(message_counter) is int and message_counter >= 0 and type(order_counter) is int and order_counter >= 0, 'exact nonnegative original ID counters')
        for field in ('deliver_seq', 'ttl_messages', 'current_time', 'current_agent_additional_delay'):
            require(type(self.number(roots[field])) is int, 'integer original clock/counter root: ' + field)
        return {'definitions': len(self.definitions), 'references': self.references, 'root_keys': list(roots),
            'encoded_tag_counts': dict(sorted(self.tags.items())), 'RandomState_full624_count': len(self.random_states),
            'global_MT19937_full624_state': True, 'ledger_rows': len(ledger), 'queue_rows': len(queue),
            'message_counter': message_counter, 'order_counter': order_counter, 'agents': len(agents),
            'summary_rows': len(self.sequence(roots['summary_log'], 'list')), 'all_backward_aliases_valid': True}
