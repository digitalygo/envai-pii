import os
from dataclasses import dataclass


DEFAULT_SEED_ENTRIES = 10000
DEFAULT_ORIGINAL_CHARS = 4096
DEFAULT_AGGREGATE_CHARS = 1048576
DEFAULT_JSON_BODY_BYTES = 8388608
MAX_SEED_ENTRIES = 20000
MAX_ORIGINAL_CHARS = 65536
MAX_AGGREGATE_CHARS = 2097152
MAX_JSON_BODY_BYTES = 16777216

SEED_ENTRIES_ENV = "PII_MAX_SEED_ENTRIES"
ORIGINAL_CHARS_ENV = "PII_MAX_ORIGINAL_CHARS"
AGGREGATE_CHARS_ENV = "PII_MAX_AGGREGATE_CHARS"
JSON_BODY_BYTES_ENV = "PII_MAX_JSON_BODY_BYTES"


@dataclass(frozen=True, slots=True)
class RequestLimits:
    seed_entries: int
    original_chars: int
    aggregate_chars: int
    json_body_bytes: int


def _bounded_environment_integer(name, default, ceiling):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip(), 10)
    except (AttributeError, TypeError, ValueError):
        return default
    if value < 1:
        return default
    return min(value, ceiling)


def resolve_request_limits():
    return RequestLimits(
        seed_entries=_bounded_environment_integer(
            SEED_ENTRIES_ENV, DEFAULT_SEED_ENTRIES, MAX_SEED_ENTRIES),
        original_chars=_bounded_environment_integer(
            ORIGINAL_CHARS_ENV, DEFAULT_ORIGINAL_CHARS, MAX_ORIGINAL_CHARS),
        aggregate_chars=_bounded_environment_integer(
            AGGREGATE_CHARS_ENV, DEFAULT_AGGREGATE_CHARS, MAX_AGGREGATE_CHARS),
        json_body_bytes=_bounded_environment_integer(
            JSON_BODY_BYTES_ENV, DEFAULT_JSON_BODY_BYTES, MAX_JSON_BODY_BYTES),
    )
