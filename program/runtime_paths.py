from __future__ import annotations

import sys
from pathlib import Path


def get_bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def get_workspace_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_runtime_program_dir() -> Path:
    if getattr(sys, "frozen", False):
        runtime_dir = get_workspace_dir() / "program_runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return runtime_dir
    return Path(__file__).resolve().parent
