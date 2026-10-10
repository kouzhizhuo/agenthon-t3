"""Prepare a tiny reviewed startup package with unchanged bounded host2."""
import argparse
import ast
from pathlib import Path
import shutil

from common import HERE, PARENT, pin, read, require, write

ROOT = HERE.parent
EXPECTED_HOST = {'verify_linux.py': {'bytes': 31566, 'sha256': '601f91afb69fbb1fe95df041712a5fbb78edc5390812649d90fc5f50671d6b01'},
    'verify_public.py': {'bytes': 23491, 'sha256': 'a6814bb273da528b0c478b760cd4af6a9a116a046bb9e82b751ab4717bf082dc'}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--cold-review', type=Path, required=True)
    parser.add_argument('--root-review', type=Path, required=True)
    args = parser.parse_args()
    require(not (HERE / 'SOURCE_LOCK.json').exists() and not (HERE / 'startupinventory.py').exists(), 'fresh unprepared small startup package')
    inventory = args.inventory.resolve()
    source = pin(inventory)
    require(source['sha256'] == args.expected_sha256, 'exact independently reviewed inventory bytes')
    for review in (args.cold_review, args.root_review):
        record = read(review)
        require(record['source_sha256'] == source['sha256'] and record['all_passed'] is True
            and record['participant_imported'] is record['market_executed'] is record['native_compiled'] is False,
            'explicit cold/root source-only reviewed inventory authority required')
    ast.parse(inventory.read_bytes(), filename=str(inventory))
    host = HERE / 'host'
    host.mkdir()
    original = ROOT / 'server_classic_structural_v3/prepared_source_v7/host'
    for name, expected in EXPECTED_HOST.items():
        require(pin(original / name) == expected, 'unchanged original bounded host authority')
        shutil.copyfile(original / name, host / name)
    shutil.copyfile(inventory, HERE / 'startupinventory.py')
    source_text = inventory.read_text()
    require("PREFIX = 'T3_SYSTEM_STARTUP_INVENTORY_V3 '" in source_text
        and "'schema': 't3-fixed-system-startup-inventory-v3'" in source_text, 'reviewed patched inventory protocol exact')
    write(HERE / 'SOURCE_LOCK.json', {'schema': 't3-fixed-stock-startup-source-lock-v2', 'parent_image': PARENT,
        'inventory_source': source, 'inventory_source_path': str(inventory),
        'cold_review': pin(args.cold_review), 'root_review': pin(args.root_review),
        'unchanged_host_sources': EXPECTED_HOST, 'source_only': True,
        'participant_imported': False, 'native_compiled': False, 'market_executed': False,
        'startup_pins_updated': False, 'remote_writes': False, 'rankable': False})
    print('SMALL STARTUP SOURCE/HOST2 PREPARED; no participant execution or remote mutation')


if __name__ == '__main__':
    main()
