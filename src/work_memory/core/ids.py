"""Time-ordered UUIDv7 identifiers and UTC timestamp helpers."""

from __future__ import annotations

import secrets
import threading
import time
import uuid
from datetime import UTC, datetime

_lock = threading.Lock()
_last_ms = 0
_last_rand_a = 0


def new_id() -> str:
    """Return a monotonically increasing RFC 9562 UUIDv7 string using stdlib only."""
    global _last_ms, _last_rand_a

    with _lock:
        ts_ms = time.time_ns() // 1_000_000
        if ts_ms > _last_ms:
            _last_ms = ts_ms
            # Leave headroom in the 12-bit sequence field for rapid same-ms calls.
            _last_rand_a = secrets.randbits(10)
        else:
            _last_rand_a += 1
            if _last_rand_a > 0x0FFF:
                _last_ms += 1
                _last_rand_a = secrets.randbits(10)
        ms = _last_ms
        rand_a = _last_rand_a

    rand_b = secrets.randbits(62)
    value = (
        ((ms & 0xFFFFFFFFFFFF) << 80)
        | (0x7 << 76)
        | ((rand_a & 0x0FFF) << 64)
        | (0b10 << 62)
        | (rand_b & 0x3FFFFFFFFFFFFFFF)
    )
    return str(uuid.UUID(int=value))


def utc_now_iso() -> str:
    """Return the current UTC timestamp formatted as YYYY-MM-DDTHH:MM:SSZ."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
