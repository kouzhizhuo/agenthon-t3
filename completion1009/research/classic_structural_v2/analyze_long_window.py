"""Analyze saved paired timing only; no simulator imports or execution."""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import random
import statistics as st

ARMS = ('parent', 'expectations', 'price_index')


def analyze(rows, draws=10000):
    cells = {}
    for row in rows:
        if not row['timing_included']:
            continue
        key = row['unit'], row['repeat'], row['direct_arm']
        n, t = row['actual_events'], row['settled_container_runtime_sec']
        if key in cells or key[2] not in ARMS or type(n) is not int or n <= 0 or not math.isfinite(t) or t <= 0:
            raise ValueError('unique finite actual timing required')
        if abs(n/t - row['EPS']) > 1e-9 * max(1, row['EPS']):
            raise ValueError('saved EPS is not actual N divided by actual T')
        cells[key] = (n/t, n, tuple(row['order']))
    units = sorted({key[0] for key in cells})
    repeats = sorted({key[1] for key in cells})
    if len(units) != 6 or repeats != list(range(2,18)) or len(cells) != 288:
        raise ValueError('six units and sixteen measured three-arm pairs required')
    for unit in units:
        orders = collections.Counter()
        for repeat in repeats:
            records = [cells[unit, repeat, arm] for arm in ARMS]
            if any(record[1:] != records[0][1:] for record in records):
                raise ValueError('same-round N and requested order must agree across arms')
            orders[records[0][2]] += 1
        if orders != {ARMS: 8, tuple(reversed(ARMS)): 8}:
            raise ValueError('eight forward and eight reverse orders per unit required')

    def score(indices):
        values = {arm: st.mean(st.median(cells[unit, repeat, arm][0] for repeat in indices) for unit in units) for arm in ARMS}
        return values, {arm: values[arm]/values['parent'] for arm in ARMS[1:]}

    means, ratios = score(repeats)
    blocks = [repeats[i:i+2] for i in range(0,16,2)]
    rng = random.Random(20261010)
    sampled = {arm: [] for arm in ARMS[1:]}
    for _ in range(draws):
        indices = [repeat for _ in blocks for repeat in rng.choice(blocks)]
        _, trial = score(indices)
        for arm in sampled:
            sampled[arm].append(trial[arm])
    interval = {arm: [sorted(values)[int((draws-1)*q)] for q in (.025,.975)] for arm, values in sampled.items()}
    per_unit = []
    for unit in units:
        medians = {arm: st.median(cells[unit, repeat, arm][0] for repeat in repeats) for arm in ARMS}
        halves = {arm: [st.median(cells[unit, repeat, arm][0] for repeat in subset) for subset in (repeats[:8], repeats[8:])] for arm in ARMS}
        per_unit.append({'unit': unit, 'median_EPS': medians,
            'candidate_vs_parent': {arm: medians[arm]/medians['parent'] for arm in ARMS[1:]},
            'first_second_half_median_EPS': halves,
            'median_absolute_deviation': {arm: st.median(abs(cells[unit, repeat, arm][0]-medians[arm]) for repeat in repeats) for arm in ARMS},
            'paired_ratio_by_order': {arm: {'/'.join(order): st.median(cells[unit, repeat, arm][0]/cells[unit, repeat, 'parent'][0]
                for repeat in repeats if cells[unit, repeat, arm][2] == order) for order in (ARMS, tuple(reversed(ARMS)))} for arm in ARMS[1:]}})
    return {'mean_of_unit_median_EPS': means, 'candidate_vs_parent': ratios,
        'two_round_block_percentile_interval': interval, 'positive_lower_bound': {arm: value[0] > 1 for arm, value in interval.items()},
        'per_unit': per_unit, 'draws': draws, 'seed': 20261010, 'blocks': blocks,
        'interpretation': 'Descriptive paired six-unit development screen. Two adjacent rounds are approximately exchangeable; the interval is conditional on this runner and these public workloads. Drift beyond two rounds can invalidate its coverage. A positive bound is an admission to full71 verification, not an official score or 232000 guarantee.',
        'full71': False, 'rankable': False, 'official_submission': False, 'simulator_executed': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw-results', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError('fresh analysis output required')
    data = args.raw_results.read_bytes()
    report = analyze(json.loads(data))
    report['raw_results_sha256'] = hashlib.sha256(data).hexdigest()
    args.out.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False)+'\n')
    print(json.dumps({key: report[key] for key in ('candidate_vs_parent', 'two_round_block_percentile_interval', 'positive_lower_bound')}))


if __name__ == '__main__':
    main()
