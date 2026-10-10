"""Explicit runtime bound for metadata clients with no requests timeout.

This changes transport, not framework stages, prompts, search queries or science.
It must be recorded in the run contract; existing explicit deadlines are preserved.
"""

from contextlib import contextmanager
from functools import wraps
from math import isfinite


@contextmanager
def bound_unconfigured_requests(seconds: float | None):
    """Bound each connect/read operation, not total search or retry duration."""
    if seconds is None:
        yield
        return
    if not isfinite(seconds) or seconds <= 0:
        raise ValueError("Metadata transport timeout must be positive and finite")
    import requests

    original = requests.sessions.Session.request

    @wraps(original)
    def bounded(session, method, url, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = seconds
        return original(session, method, url, **kwargs)

    requests.sessions.Session.request = bounded
    try:
        yield
    finally:
        requests.sessions.Session.request = original
