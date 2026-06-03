"""Single shared SlowAPI Limiter for the app.

Importing from a single module ensures all routes count against the same
key store (otherwise per-module Limiter() instances would each maintain
independent counters).
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, headers_enabled=True)
