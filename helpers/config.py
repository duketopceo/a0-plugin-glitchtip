"""Plugin config: framework get_plugin_config merged over shipped defaults.

a0's `helpers.plugins.get_plugin_config` already falls back to the plugin's
`default_config.yaml` then merges user settings — so the only layer this
module adds is `DEFAULTS`, the code-level fallback for non-a0 runtimes
(tests, a future Hermes port). Keep DEFAULTS, `default_config.yaml`, and the
README settings table in sync — adding a key means touching all three.
"""

from __future__ import annotations

import math
from typing import Any

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "dsn": "",
    "environment": "local",
    "release": "",
    "api_error_events": True,
    "breadcrumbs_max": 50,
    "send_timeout_s": 5,
}


def get_config() -> dict[str, Any]:
    """DEFAULTS < user plugin config (which itself sits over
    default_config.yaml via a0's own fallback). Never raises."""
    cfg = dict(DEFAULTS)
    try:
        from helpers.plugins import get_plugin_config  # type: ignore

        user = get_plugin_config("glitchtip")
        if isinstance(user, dict):
            cfg.update(user)
    except Exception:
        pass
    return cfg


def truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "on"}
    return bool(v)


def num(v: Any, default: float) -> float:
    """Safe numeric coercion for config values — a bad setting must not
    break plugin init. Non-finite results (nan/inf would raise again on
    int()) fall back to the default."""
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError, OverflowError):
        return default
