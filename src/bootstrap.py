"""Locate only this attempt's vendored simulator and local dependency directory."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def activate() -> None:
    paths = [ROOT / ".runtime", ROOT,
             ROOT / "vendor/abides/abides-core",
             ROOT / "vendor/abides/abides-markets"]
    for path in reversed(paths):
        if path.exists():
            sys.path.insert(0, str(path))
