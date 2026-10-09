"""Small source-only pandas-free fixture screen contract."""
import hashlib
import json
from pathlib import Path, PurePosixPath

BASE = "ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb"
CANDIDATE = "completion1009/candidates/lightweight_canonical_buffers_v4"
BASELINE = "completion1009/candidates/lean_production_native_projection_v1/runtime"
SOURCE_RECEIPT_SHA256 = "5a7efb13de2aa4dd888480d235250e5f2b894a60a16900b29724ec8e3553fbf0"
GENERATOR = "completion1009/research/pandas_free_output_route_v1/prepare_schema_metadata_source_v1.py"
GENERATOR_SHA256 = "aa60cd24b919446e881a6b849a4039b363c14e684ccd58bbd0cf9ad55cffeafe"
MAX_FILES = 512
MAX_BYTES = 32 * 1024 ** 2
IMAGE_ROOT = "/opt/lightweight-canonical-fixtures-v4-1"
ENTRYPOINT = ["/usr/local/bin/python", "-B", IMAGE_ROOT + "/control/entry.py"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def safe_name(value):
    name = PurePosixPath(value)
    if (not value or name.is_absolute() or any(p in ("", ".", "..") for p in value.split("/"))
            or "\\" in value or "\x00" in value):
        raise ValueError("unsafe relative path")
    return name.as_posix()


def inventory(root):
    result = {}
    for path in sorted(Path(root).rglob("*")):
        if any(part.startswith("._") or part in ("__pycache__", ".DS_Store", "__MACOSX") for part in path.parts):
            continue
        if path.is_symlink():
            raise ValueError("source symlink prohibited")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {"bytes": path.stat().st_size, "sha256": sha(path)}
    return result


def verify_payload(root):
    root = Path(root)
    manifest = json.loads((root / "PAYLOAD_MANIFEST.json").read_text())
    actual = inventory(root)
    actual.pop("PAYLOAD_MANIFEST.json", None)
    actual.pop("MATERIALIZATION.json", None)
    if actual != manifest["files"]:
        raise ValueError("exact fixture payload inventory differs")
    return actual
