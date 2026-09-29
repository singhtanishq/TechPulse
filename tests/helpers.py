"""
TechPulse — Test Utilities

Loads project scripts as importable modules for isolated tests.

Several collector files share the basename ``collect.py``. Loading them
through importlib with explicit, unique module names avoids normal import
name collisions while preserving the project's real source-file layout.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def load_module(name: str, relative_path: str) -> ModuleType:
    """Load a project script under a unique module name."""
    if not name or not name.strip():
        raise ValueError("Module name must not be empty.")

    if not relative_path or not relative_path.strip():
        raise ValueError("Relative path must not be empty.")

    path = (SCRIPTS_DIR / relative_path).resolve()

    try:
        path.relative_to(SCRIPTS_DIR.resolve())
    except ValueError as exc:
        raise ValueError(
            f"Module path must remain inside {SCRIPTS_DIR}: {relative_path}"
        ) from exc

    if not path.is_file():
        raise FileNotFoundError(
            f"Cannot load module {name}: file does not exist: {path}"
        )

    spec = importlib.util.spec_from_file_location(
        name,
        path,
    )

    if spec is None or spec.loader is None:
        raise ImportError(
            f"Cannot load module {name} from {path}"
        )

    module = importlib.util.module_from_spec(spec)

    # Register before execution so modules that inspect sys.modules during
    # import behave like normally imported modules.
    sys.modules[name] = module

    try:
        spec.loader.exec_module(module)
    except Exception:
        # Do not leave a partially initialized module behind after a
        # failed import.
        sys.modules.pop(name, None)
        raise

    return module


def load_processors_utils() -> ModuleType:
    """Load scripts/processors/utils.py."""
    return load_module(
        "techpulse_processors_utils",
        "processors/utils.py",
    )
