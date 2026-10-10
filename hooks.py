"""Plugin lifecycle hooks — install()/uninstall() called by a0's plugin
manager. Nothing to provision or clean up: the plugin is stdlib-only and
lazily activates when a DSN is configured.

Imports are lazy — the plugin loader's module import is unguarded upstream,
so a module-level failure here could abort the hook sweep.
"""

from __future__ import annotations

import logging
import os


def install() -> bool:
    try:
        from usr.plugins.glitchtip.helpers import ENV_DSN, LOG_NAME

        logging.getLogger(LOG_NAME).info(
            "a0-plugin-glitchtip installed (dsn_env=%s)",
            bool((os.environ.get(ENV_DSN) or "").strip()),
        )
    except Exception:
        pass  # never block install
    return True


def uninstall() -> bool:
    try:
        from usr.plugins.glitchtip.helpers import LOG_NAME, runtime

        runtime._reset()  # client, latch, cooldown, redactor, crumbs, trace
        logging.getLogger(LOG_NAME).info("a0-plugin-glitchtip uninstalled")
    except Exception:
        pass  # never block uninstall
    return True
