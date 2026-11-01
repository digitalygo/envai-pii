"""Server-side chunk batching for the guardrail model adapter.

The batch size comes only from the server environment and is resolved once at
startup. Grouping and result validation stay request-local: a batch never crosses
an adapter invocation, a protected gap, a request, or a file.
"""

import operator
import os
from collections.abc import Mapping
from math import isfinite

BATCH_SIZE_ENV = "PII_MODEL_BATCH_SIZE"
DEFAULT_BATCH_SIZE = 1
SUPPORTED_BATCH_SIZES = (1, 4, 8, 16)
_BATCH_SIZE_VALUES = {str(size): size for size in SUPPORTED_BATCH_SIZES}
RESULT_ERROR_MESSAGE = "invalid model batch result"


class ModelBatchResultError(RuntimeError):
    """Raised when a batched pipeline result does not match its input chunks."""

    def __init__(self):
        super().__init__(RESULT_ERROR_MESSAGE)


def resolve_model_batch_size(environ=None):
    """Resolve the server batch size from the environment.

    Surrounding whitespace is stripped before a canonical supported value is
    matched, so padded values such as ``" 4 "`` are accepted. Unsupported or
    malformed values mean 1.
    """
    source = os.environ if environ is None else environ
    raw = source.get(BATCH_SIZE_ENV)
    if isinstance(raw, bool) or not isinstance(raw, str):
        return DEFAULT_BATCH_SIZE
    return _BATCH_SIZE_VALUES.get(raw.strip(), DEFAULT_BATCH_SIZE)


def chunk_groups(chunks, batch_size):
    """Yield consecutive groups of at most ``batch_size`` chunks in input order."""
    size = batch_size if batch_size in SUPPORTED_BATCH_SIZES else DEFAULT_BATCH_SIZE
    for start in range(0, len(chunks), size):
        yield chunks[start:start + size]


def _exact_index(value):
    if isinstance(value, bool):
        raise TypeError("boolean entity bounds are not indexes")
    return operator.index(value)


def _entity_values(entity):
    try:
        return (entity["entity_group"], _exact_index(entity["start"]),
                _exact_index(entity["end"]), float(entity["score"]))
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _normalize_entity(entity, chunk):
    if not isinstance(entity, Mapping):
        raise ModelBatchResultError()
    values = _entity_values(entity)
    if values is None:
        raise ModelBatchResultError()
    label, start, end, score = values
    if not isinstance(label, str) or not label:
        raise ModelBatchResultError()
    if not isfinite(score):
        raise ModelBatchResultError()
    if start < 0 or end <= start or end > len(chunk):
        raise ModelBatchResultError()
    return {"label": label, "start": start, "end": end, "score": score}


def normalize_batch_results(results, chunks):
    """Validate exactly one nested entity row per input chunk.

    Empty rows are valid. Flat, ambiguous, missing, extra, generator, or malformed
    rows fail closed instead of being silently truncated.
    """
    if not isinstance(results, (list, tuple)):
        raise ModelBatchResultError()
    if len(results) != len(chunks):
        raise ModelBatchResultError()
    rows = []
    for index, chunk in enumerate(chunks):
        row = results[index]
        if isinstance(row, dict) or not isinstance(row, (list, tuple)):
            raise ModelBatchResultError()
        rows.append([_normalize_entity(entity, chunk) for entity in row])
    return rows
