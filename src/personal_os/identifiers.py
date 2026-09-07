import secrets
import time
import uuid
from collections.abc import Callable
from typing import cast
from uuid import UUID


def new_uuid7() -> UUID:
    standard_uuid7 = cast(
        Callable[[], UUID] | None,
        getattr(uuid, "uuid7", None),
    )
    if standard_uuid7 is not None:
        return standard_uuid7()

    timestamp_ms = time.time_ns() // 1_000_000
    random_a = secrets.randbits(12)
    random_b = secrets.randbits(62)
    value = (
        (timestamp_ms & ((1 << 48) - 1)) << 80
        | 0x7 << 76
        | random_a << 64
        | 0b10 << 62
        | random_b
    )
    return UUID(int=value)
