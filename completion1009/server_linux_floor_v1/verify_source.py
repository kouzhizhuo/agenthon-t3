"""Verify uploaded source/payload pins before any Linux build or simulation."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPLETION = HERE.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    manifest = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    for relative, row in manifest["files"].items():
        path = HERE / relative
        if path.is_symlink() or not path.is_file() or path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise ValueError("exact frozen diagnostic source differs: " + relative)
    payload = COMPLETION / "server_observer_startup_v1/SCREEN_PAYLOAD.tar.xz"
    expected = manifest["observer_startup_payload"]
    if payload.stat().st_size != expected["bytes"] or sha(payload) != expected["sha256"]:
        raise ValueError("exact existing source payload differs")
    print(json.dumps({"source_frozen_passed": True, "payload_sha256": expected["sha256"], "source_only": True,
                      "compilation_or_simulation_executed": False}))
