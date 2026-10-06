"""Path helpers — framework shim with a cwd fallback (standalone test runs)."""

from __future__ import annotations

from pathlib import Path


def plugin_root() -> Path:
    """Absolute path of usr/plugins/glitchtip/ — the directory holding this
    file's parent (helpers/) is the plugin root."""
    return Path(__file__).resolve().parent.parent


def abs_path(*parts: str) -> Path:
    """A0-rooted path when the framework helper exists, else plugin-rooted."""
    try:
        from helpers import files  # type: ignore

        return Path(files.get_abs_path(*parts))
    except Exception:
        return plugin_root().joinpath(*parts)
