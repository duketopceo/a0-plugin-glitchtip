"""Plugin lifecycle hooks.

install(): nothing to provision — the plugin is stdlib-only and lazily
activates when a DSN is configured. We write a small probe note so the WebUI
can show "configured vs not" if it wants.
uninstall(): removes the probe note; there is no other plugin-owned state
(the plugin never writes to usr/).
"""

from __future__ import annotations

import json
import os
import logging

log = logging.getLogger("a0.glitchtip")

PROBE_FILE = ".glitchtip-probe.json"


def _probe_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), PROBE_FILE)


def install() -> bool:
    try:
        configured = bool((os.environ.get("GLITCHTIP_DSN") or "").strip())
        with open(_probe_path(), "w") as f:
            json.dump({"dsn_env_present": configured}, f)
        log.info("a0-plugin-glitchtip installed (dsn_env=%s)", configured)
    except Exception:
        pass  # probe is advisory; never block install
    return True


def uninstall() -> bool:
    try:
        os.remove(_probe_path())
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return True
