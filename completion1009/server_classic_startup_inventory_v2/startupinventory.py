"""Fresh Linux-only fixed Python startup-source inventory; never a market run.

This script is prepared as source only. It reads the fixed /usr/local Python tree,
never imports participant code or invokes a finder, and emits no environment
values, user file contents, credentials or arbitrary paths.
"""
import hashlib
import json
from pathlib import Path
import platform
import sys
import types

SYSTEM_PREFIX = Path('/usr/local')
STDLIB = SYSTEM_PREFIX / 'lib/python3.11'
SITE = STDLIB / 'site-packages'
PREFIX = 'T3_SYSTEM_STARTUP_INVENTORY_V3 '
FILE_CAP = 1024**2
PTH_CAP = 64 * 1024
TOTAL_CAP = 4 * 1024**2
OUTPUT_CAP = 8 * 1024**2
_FILES = {}
_UNIQUE_BYTES = 0
_REQUESTED_BYTES = 0
_REQUESTS = 0


def _bounded_path(path):
    # Reject the lexical boundary before any filesystem metadata operation.
    if (type(path) is not type(STDLIB) or not path.is_absolute()
            or not path.is_relative_to(STDLIB) or '..' in path.parts):
        raise ValueError('canonical fixed system startup path required')
    for parent in (path,) + tuple(path.parents):
        if parent.is_symlink():
            raise ValueError('startup source symlink refused')
        if parent == STDLIB:
            break
    if path.resolve() != path:
        raise ValueError('canonical fixed system startup path required')


def system_file(path, cap=FILE_CAP, content=False):
    global _UNIQUE_BYTES, _REQUESTED_BYTES, _REQUESTS
    _bounded_path(path)
    _REQUESTS += 1
    key = str(path)
    cached = _FILES.get(key)
    if cached is None:
        if not path.is_file():
            cached = ({'path': key, 'exists': False}, b'')
        else:
            size = path.stat().st_size
            if size > cap or _UNIQUE_BYTES + size > TOTAL_CAP:
                raise ValueError('bounded aggregate startup source required')
            with path.open('rb') as stream:
                data = stream.read(cap + 1)
            if len(data) > cap or len(data) != size or _UNIQUE_BYTES + len(data) > TOTAL_CAP:
                raise ValueError('bounded stable startup source required')
            cached = ({'path': key, 'exists': True, 'bytes': len(data),
                'sha256': hashlib.sha256(data).hexdigest()}, data)
            _UNIQUE_BYTES += len(data)
        _FILES[key] = cached
    base, data = cached
    if len(data) > cap:
        raise ValueError('cached startup source exceeds requested bound')
    _REQUESTED_BYTES += len(data)
    row = dict(base)
    if content and row['exists']:
        row['source_utf8'] = data.decode('utf-8')
    return row


def loaded_system_module(name):
    if type(sys.modules) is not dict:
        raise ValueError('exact startup module registry required')
    module = sys.modules.get(name)
    row = {'module': name, 'loaded': module is not None}
    if module is None:
        return row
    if type(module) is not types.ModuleType:
        row['unknown_module_type'] = True
        return row
    namespace = object.__getattribute__(module, '__dict__')
    if type(namespace) is not dict:
        row['unknown_module_namespace'] = True
        return row
    source = namespace.get('__file__')
    if type(source) is str:
        path = Path(source)
        inside = path.is_absolute() and path.is_relative_to(STDLIB) and '..' not in path.parts
        row['loaded_from_fixed_system_tree'] = inside
        if inside:
            row['actual_loaded_source'] = system_file(path)
        else:
            row['loaded_outside_fixed_system_tree'] = True
    else:
        row['source_path_absent'] = True
    return row


def loaded_customization(name):
    row = loaded_system_module(name)
    row['name'] = name
    row['fixed_system_candidates'] = [system_file(directory / (name + extension))
        for directory in (STDLIB, SITE) for extension in ('.py', '.pyc')]
    return row


def meta_path_inventory():
    if type(sys.meta_path) is not list or len(sys.meta_path) > 32:
        raise ValueError('finite exact Python meta_path list required')
    # Invoke only the original built-in type storage descriptors, never an
    # arbitrary finder/metaclass getter, repr, import or finder method.
    module_descriptor = type.__dict__['__module__']
    name_descriptor = type.__dict__['__qualname__']
    mro_descriptor = type.__dict__['__mro__']
    rows = []
    for position, finder in enumerate(sys.meta_path):
        kind = type(finder)
        kind_mro = mro_descriptor.__get__(kind, type)
        row = {'position': position}
        if type(kind_mro) is not tuple or len(kind_mro) > 64:
            row['unknown_type_mro'] = True
            rows.append(row)
            continue
        is_class = any(base is type for base in kind_mro)
        cls = finder if is_class else kind
        row['kind'] = 'class' if is_class else 'instance'
        if type(cls) is not type:
            row['unknown_metaclass'] = True
            rows.append(row)
            continue
        module = module_descriptor.__get__(cls, type)
        name = name_descriptor.__get__(cls, type)
        if type(module) is not str or type(name) is not str:
            row['unknown_class_descriptor'] = True
            rows.append(row)
            continue
        row.update({'class_module': module, 'class_qualname': name,
            'loaded_module': loaded_system_module(module)})
        rows.append(row)
    return rows


def main():
    if (platform.system() != 'Linux' or platform.machine() != 'x86_64'
            or sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 11, 17)
            or Path(sys.prefix) != SYSTEM_PREFIX or Path(sys.base_prefix) != SYSTEM_PREFIX
            or Path(sys.executable) != SYSTEM_PREFIX / 'bin/python'
            or Path.cwd() != Path('/output') or type(sys.modules) is not dict):
        raise ValueError('fresh exact published Linux startup CLI required; no local execution')
    _bounded_path(STDLIB)
    _bounded_path(SITE)
    if not SITE.is_dir():
        raise ValueError('fixed system Python source directory required')
    paths = sorted(SITE.glob('*.pth'))
    if len(paths) > 128:
        raise ValueError('finite startup pth roster exceeded')
    pth_rows = []
    for path in paths:
        row = system_file(path, PTH_CAP, content=True)
        lines = row['source_utf8'].splitlines()
        row['executable_import_lines'] = [{'line_one_based': index + 1, 'text': line}
            for index, line in enumerate(lines) if line.startswith(('import ', 'import\t'))]
        row['active_path_lines'] = [{'line_one_based': index + 1, 'text': line}
            for index, line in enumerate(lines) if line and not line.startswith('#')
            and not line.startswith(('import ', 'import\t'))]
        pth_rows.append(row)
    directories = sorted(SITE.glob('setuptools-*.dist-info'))
    if len(directories) > 2:
        raise ValueError('unexpected multiple setuptools distributions')
    packages = []
    for directory in directories:
        _bounded_path(directory)
        if not directory.is_dir():
            raise ValueError('ordinary fixed setuptools metadata required')
        meta_path = directory / 'METADATA'
        meta = system_file(meta_path, content=True)
        if not meta['exists']:
            raise ValueError('actual setuptools metadata absent')
        headers = {}
        for line in meta.pop('source_utf8').splitlines():
            if not line:
                break
            name, colon, value = line.partition(':')
            if colon and name in ('Name', 'Version'):
                if name in headers:
                    raise ValueError('duplicate setuptools metadata header')
                headers[name] = value.strip()
        if headers.get('Name', '').lower() != 'setuptools' or 'Version' not in headers:
            raise ValueError('actual setuptools name/version metadata required')
        packages.append({'distribution': headers, 'metadata': meta})
    sources = [system_file(STDLIB / 'site.py', content=True)] + [system_file(SITE / relative, content=True) for relative in (
        '_distutils_hack/__init__.py', '_distutils_hack/override.py', 'setuptools/__init__.py')]
    flags = {name: getattr(sys.flags, name) for name in ('debug', 'inspect', 'interactive', 'optimize',
        'dont_write_bytecode', 'no_user_site', 'no_site', 'ignore_environment', 'verbose', 'isolated',
        'dev_mode', 'utf8_mode', 'safe_path')}
    row = {'schema': 't3-fixed-system-startup-inventory-v3',
        'python': {'executable': sys.executable, 'version': list(sys.version_info[:3]),
            'implementation': sys.implementation.name, 'prefix': sys.prefix, 'base_prefix': sys.base_prefix,
            'flags': flags, 'fixed_system_site_packages': str(SITE)},
        'pth_files': pth_rows, 'setuptools_distributions': packages,
        'sys_meta_path': meta_path_inventory(),
        'system_site': loaded_system_module('site'),
        'system_distutils_hack': loaded_system_module('_distutils_hack'),
        'fixed_startup_sources': sources,
        'customizations': [loaded_customization(name) for name in ('sitecustomize', 'usercustomize')],
        'loaded_distutils_hack': '_distutils_hack' in sys.modules,
        'loaded_setuptools': 'setuptools' in sys.modules,
        'setprofile_absent': sys.getprofile() is None, 'settrace_absent': sys.gettrace() is None,
        'participant_modules_loaded': any(name in sys.modules for name in ('production_cli', 'abides_core', 'dynamic_arena_chain')),
        'environment_values_emitted': False, 'user_files_read': False,
        'participant_imported_by_diagnostic': False, 'market_executed': False, 'native_compiled': False,
        'rankable': False, 'timing_included': False,
        'scope': 'fixed Python startup source and ordered meta_path evidence; no finder invocation or market measurement'}
    # This ledger includes every fixed, metadata, customization and finder
    # source, including repeated requests without repeating physical reads.
    if _UNIQUE_BYTES > TOTAL_CAP:
        raise ValueError('finite aggregate startup inventory exceeded')
    row['source_byte_ledger'] = {'unique_file_bytes': _UNIQUE_BYTES,
        'requested_source_bytes': _REQUESTED_BYTES, 'file_requests': _REQUESTS,
        'unique_files': len(_FILES), 'unique_source_cap': TOTAL_CAP,
        'files': [base for base, data in _FILES.values()]}
    if row['participant_modules_loaded']:
        raise ValueError('startup diagnostic must not inherit a market process')
    encoded = json.dumps(row, sort_keys=True, allow_nan=False)
    if len((PREFIX + encoded + '\n').encode('utf-8')) > OUTPUT_CAP:
        raise ValueError('finite startup inventory stdout exceeded')
    print(PREFIX + encoded, flush=True)


if __name__ == '__main__':
    main()
