"""Bounded wrapper for the exact original public reference fetch script."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import sys
import time

HERE = Path(__file__).resolve().parent


def source_bytes(path):
    path = Path(path)
    cap = 64 * 1024**2
    if (not path.is_absolute() or not path.is_file() or path.is_symlink()
            or '..' in path.parts or any(item.is_symlink() for item in path.parents) or path.stat().st_size > cap):
        raise ValueError('ordinary bounded source before read')
    chunks, count = [], 0
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024**2), b''):
            count += len(chunk)
            if count > cap:raise ValueError('streamed source hard bound')
            chunks.append(chunk)
    if count != path.stat().st_size:raise ValueError('complete stable source byte count')
    return b''.join(chunks)


def main():
    parser=argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    freeze=json.loads(source_bytes(HERE/'HYDRATION_SOURCE_FREEZE.json'))
    hydration_source=HERE/'hydrate_base_draft_v1.py'
    data=source_bytes(hydration_source)
    if (len(data)!=hydration_source.stat().st_size or len(data)>64*1024**2 or freeze.get('ready_for_linux') is not True or freeze.get('reviewed') is not True
            or {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}!=freeze['files']['hydrate_base_draft_v1.py']):
        raise ValueError('exact reviewed hydration module bytes before inert import')
    spec=importlib.util.spec_from_file_location('t3_hydration_no_main',HERE/'hydrate_base_draft_v1.py')
    hydration=importlib.util.module_from_spec(spec);spec.loader.exec_module(hydration)
    hydration.validate_source_freeze()
    root,out=hydration.ordinary(args.root),hydration.ordinary(args.out)
    path=root/'payload-v2/host/fetch_evaluation.py'
    wanted=hydration.read(root/'payload-v2/STRUCTURAL_MANIFEST.json')['files']['host/fetch_evaluation.py']
    hydration.require(hydration.pin(path)==wanted and not out.exists(), 'exact original public fetch source and fresh evaluation')
    hydration.DEADLINE=time.monotonic()+2400
    signal.signal(signal.SIGINT,hydration.cancellation);signal.signal(signal.SIGTERM,hydration.cancellation)
    process=hydration.saved_process([sys.executable,'-B',str(path),'--out',str(out)],root,'official-reference-fetch',2400,hydration.DEADLINE)
    hydration.write(root/'REFERENCE_FETCH_PROCESS.json',process)


if __name__=='__main__':main()
