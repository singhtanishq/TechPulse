"""
TechPulse — Test Utilities

Loads collector scripts as importable modules. Collector files share
the basename collect.py, so plain imports collide; importlib with
unique module names avoids this.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def load_module(name: str, relative_path: str):
    """Import a project script as a module under the given name."""
    path = SCRIPTS_DIR / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_processors_utils():
    """Load scripts/processors/utils.py (dependency-free)."""
    return load_module("techpulse_processors_utils", "processors/utils.py")
