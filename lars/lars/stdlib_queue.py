"""
Stdlib queue primitives (unpatched), even under gevent.

Gunicorn's gevent worker runs `gevent.monkey.patch_all()`, which monkey-patches
`queue.Queue` to gevent's cooperative implementation. That queue is *not*
safe to use from native OS threads, but LARS uses background threads for
fire-and-forget logging and other async tasks.

This module exposes the original stdlib `queue.Queue` + exceptions using
`gevent.monkey.get_original()` when available, falling back to the stdlib.
"""

from __future__ import annotations

try:
    from gevent.monkey import get_original  # type: ignore

    Queue, Empty, Full = get_original("queue", ("Queue", "Empty", "Full"))
except Exception:  # gevent not installed or not monkey-patched
    from queue import Empty, Full, Queue

__all__ = ["Queue", "Empty", "Full"]
