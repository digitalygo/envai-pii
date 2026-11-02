"""Transport-injected burst measurements for controlled Verda experiments."""

from __future__ import annotations

import hashlib
import math
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Protocol


CONCURRENCY_CHOICES = (1, 2, 4, 8, 16, 32)
MODEL_COUNT_CHOICES = (1, 2, 4, 8, 12, 16)
BURSTS_PER_CASE = 3
_FAILURE_CLASSES = frozenset({
    "http_status",
    "invalid_200",
    "measurement_error",
    "not_started",
    "timeout",
    "transport_error",
})
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class HttpResponseLike(Protocol):
    status: int
    body: bytes


Sender = Callable[[bytes, float], HttpResponseLike]
Validator = Callable[[bytes], str]
Clock = Callable[[], float]


def run_burst(
    senders: Sequence[Sender],
    body: bytes,
    validate: Validator,
    timeout: float = 330.0,
    *,
    model_count: int | None = None,
    burst_index: int | None = None,
    clock: Clock = time.perf_counter,
) -> dict[str, object]:
    """Run one simultaneous burst with one opaque body per sender.

    Each sender must perform exactly one bounded transport call using the supplied
    timeout. The timeout is a transport precondition, not a cancellation guarantee.
    """
    normalized_timeout = _validate_inputs(senders, body, validate, timeout, model_count, clock)
    if burst_index is not None and (
        type(burst_index) is not int or burst_index not in (1, 2, 3)
    ):
        raise ValueError("burst_index must be 1, 2, or 3")
    concurrency = len(senders)
    body_digest = hashlib.sha256(body).hexdigest()
    rows = [_new_row(request_id) for request_id in range(1, concurrency + 1)]
    release: dict[str, object] = {"clock": None, "utc": None}

    def release_barrier() -> None:
        release_clock = _sample_clock(clock)
        if release_clock is None:
            raise RuntimeError
        release["clock"] = release_clock
        release["utc"] = datetime.now(timezone.utc)

    barrier = threading.Barrier(concurrency + 1, action=release_barrier)

    def send_one(index: int) -> None:
        row = rows[index]
        try:
            barrier.wait()
        except BaseException:
            barrier.abort()
            return

        release_clock = release["clock"]
        release_utc = release["utc"]
        if not isinstance(release_clock, float) or not isinstance(release_utc, datetime):
            return
        row["started"] = True
        row["body_sent_sha256"] = body_digest
        start_clock = _sample_clock(clock)
        try:
            response = senders[index](body, normalized_timeout)
        except TimeoutError:
            _finish_transport_failure(
                row, clock, release_clock, release_utc, start_clock, "timeout"
            )
            return
        except BaseException:
            _finish_transport_failure(
                row, clock, release_clock, release_utc, start_clock, "transport_error"
            )
            return

        end_clock = _sample_clock(clock)
        timing_complete = _set_timing(
            row, start_clock, end_clock, release_clock, release_utc
        )
        status = _read_status(response)
        row["status"] = status
        if status is None:
            row["failure_class"] = "transport_error"
            row["timing_complete"] = timing_complete
            return
        if status != 200:
            row["failure_class"] = "http_status"
            row["timing_complete"] = timing_complete
            return

        response_body = _read_body(response)
        if response_body is None:
            row["failure_class"] = "invalid_200"
            row["timing_complete"] = timing_complete
            return
        try:
            canonical_digest = validate(response_body)
        except BaseException:
            row["failure_class"] = "invalid_200"
            row["timing_complete"] = timing_complete
            return
        if not isinstance(canonical_digest, str) or not _SHA256_PATTERN.fullmatch(
            canonical_digest
        ):
            row["failure_class"] = "invalid_200"
            row["timing_complete"] = timing_complete
            return

        row["validation_ok"] = True
        row["canonical_response_sha256"] = canonical_digest
        row["failure_class"] = None if timing_complete else "measurement_error"
        row["timing_complete"] = timing_complete

    threads: list[threading.Thread] = []
    try:
        threads = [
            threading.Thread(target=send_one, args=(index,), name=f"verda-burst-{index + 1}")
            for index in range(concurrency)
        ]
    except BaseException:
        return _build_burst(rows, model_count, True, None, body_digest, burst_index)

    started_threads: list[threading.Thread] = []
    preparation_failed = False
    for thread in threads:
        try:
            thread.start()
            started_threads.append(thread)
        except BaseException:
            preparation_failed = True
            barrier.abort()
            break

    if not preparation_failed:
        try:
            barrier.wait()
        except BaseException:
            preparation_failed = True
            barrier.abort()

    for thread in started_threads:
        thread.join()

    if preparation_failed:
        for row in rows:
            if not row["started"]:
                row["failure_class"] = "not_started"

    release_utc = release["utc"]
    release_utc_text = _format_utc(release_utc) if isinstance(release_utc, datetime) else None
    return _build_burst(
        rows, model_count, preparation_failed, release_utc_text, body_digest, burst_index
    )


def run_rounds(
    senders: Sequence[Sender],
    body: bytes,
    validate: Validator,
    timeout: float = 330.0,
    *,
    model_count: int | None = None,
    clock: Clock = time.perf_counter,
) -> dict[str, object]:
    """Run and summarize the three predeclared bursts for one case."""
    _validate_inputs(senders, body, validate, timeout, model_count, clock)
    rounds = [
        run_burst(
            senders,
            body,
            validate,
            timeout,
            model_count=model_count,
            burst_index=burst_index,
            clock=clock,
        )
        for burst_index in range(1, BURSTS_PER_CASE + 1)
    ]
    return summarize_rounds(rounds)


def summarize_rounds(rounds: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Aggregate exactly three bursts with the same concurrency and model count."""
    if not isinstance(rounds, Sequence) or isinstance(rounds, (str, bytes)):
        raise TypeError("rounds must be a sequence")
    if len(rounds) != BURSTS_PER_CASE:
        raise ValueError("exactly three bursts are required")

    normalized_rounds = [_validate_burst(round_result) for round_result in rounds]
    concurrency = normalized_rounds[0]["client_concurrency"]
    model_count = normalized_rounds[0]["model_count"]
    if any(
        result["client_concurrency"] != concurrency
        or result["model_count"] != model_count
        or result["body_sha256"] != normalized_rounds[0]["body_sha256"]
        for result in normalized_rounds[1:]
    ):
        raise ValueError("bursts must use the same body, concurrency, and model count")

    burst_indices = [result["burst_index"] for result in normalized_rounds]
    if any(index is not None for index in burst_indices) and burst_indices != [1, 2, 3]:
        raise ValueError("indexed bursts must be ordered 1, 2, 3")

    rows = [row for result in normalized_rounds for row in result["requests"]]
    successes = [
        row for row in rows
        if row["failure_class"] is None and row["validation_ok"]
    ]
    started_rows = [row for row in rows if row["started"]]
    timed_rows = [row for row in started_rows if row["timing_complete"]]
    all_timing_complete = len(timed_rows) == len(started_rows)
    all_latencies = [float(row["duration_seconds"]) for row in timed_rows]
    success_latencies = [float(row["duration_seconds"]) for row in successes]
    all_started_statistics = (
        _latency_statistics(all_latencies) if all_timing_complete else None
    )
    burst_elapsed = [result["group_elapsed_seconds"] for result in normalized_rounds]
    processing_elapsed = (
        math.fsum(float(value) for value in burst_elapsed)
        if all(value is not None for value in burst_elapsed)
        else None
    )
    successes_per_second = (
        len(successes) / processing_elapsed
        if processing_elapsed is not None and processing_elapsed > 0
        else None
    )

    return {
        "client_concurrency": concurrency,
        "model_count": model_count,
        "body_sha256": normalized_rounds[0]["body_sha256"],
        "round_count": BURSTS_PER_CASE,
        "planned_count": len(rows),
        "attempts": len(started_rows),
        "started_count": len(started_rows),
        "timing_incomplete_count": len(started_rows) - len(timed_rows),
        "not_started_count": len(rows) - len(started_rows),
        "success_count": len(successes),
        "failure_counts": _count_failures(rows),
        "status_counts": _count_statuses(rows),
        "mean_success_latency_seconds": _latency_statistics(success_latencies)["mean"],
        "mean_all_latency_seconds": (
            all_started_statistics["mean"] if all_started_statistics is not None else None
        ),
        "success_latency_seconds": _latency_statistics(success_latencies),
        "all_started_latency_seconds": all_started_statistics,
        "burst_elapsed_seconds": burst_elapsed,
        "launch_spread_seconds": [result["launch_spread_seconds"] for result in normalized_rounds],
        "peak_client_overlap": [result["peak_client_overlap"] for result in normalized_rounds],
        "processing_elapsed_seconds_sum": processing_elapsed,
        "successes_per_processing_second": successes_per_second,
        "rounds": normalized_rounds,
    }


def _validate_inputs(
    senders: Sequence[Sender],
    body: bytes,
    validate: Validator,
    timeout: float,
    model_count: int | None,
    clock: Clock,
) -> float:
    if not isinstance(senders, Sequence) or isinstance(senders, (str, bytes)):
        raise TypeError("senders must be a sequence")
    if len(senders) not in CONCURRENCY_CHOICES:
        raise ValueError("sender count must be one of the supported concurrency choices")
    if any(not callable(sender) for sender in senders):
        raise TypeError("every sender must be callable")
    if not isinstance(body, bytes):
        raise TypeError("body must be bytes")
    if not callable(validate):
        raise TypeError("validate must be callable")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError("timeout must be a finite positive number")
    try:
        normalized_timeout = float(timeout)
    except (OverflowError, ValueError):
        raise ValueError("timeout must be a finite positive number") from None
    if not math.isfinite(normalized_timeout) or normalized_timeout <= 0:
        raise ValueError("timeout must be a finite positive number")
    if model_count is not None and (
        type(model_count) is not int or model_count not in MODEL_COUNT_CHOICES
    ):
        raise ValueError("model_count must be one of the supported model counts")
    if not callable(clock):
        raise TypeError("clock must be callable")
    return normalized_timeout


def _new_row(request_id: int) -> dict[str, object]:
    return {
        "request_id": request_id,
        "started": False,
        "request_started_at_utc": None,
        "transport_ended_at_utc": None,
        "start_offset_seconds": None,
        "end_offset_seconds": None,
        "duration_seconds": None,
        "timing_complete": False,
        "status": None,
        "failure_class": "not_started",
        "validation_ok": False,
        "body_sent_sha256": None,
        "canonical_response_sha256": None,
    }


def _sample_clock(clock: Clock) -> float | None:
    try:
        value = clock()
        if isinstance(value, bool):
            return None
        sampled = float(value)
    except BaseException:
        return None
    return sampled if math.isfinite(sampled) else None


def _finish_transport_failure(
    row: dict[str, object],
    clock: Clock,
    release_clock: object,
    release_utc: object,
    start_clock: float | None,
    failure_class: str,
) -> None:
    end_clock = _sample_clock(clock)
    timing_complete = _set_timing(
        row, start_clock, end_clock, release_clock, release_utc
    )
    row["failure_class"] = failure_class
    row["timing_complete"] = timing_complete


def _set_timing(
    row: dict[str, object],
    start_clock: float | None,
    end_clock: float | None,
    release_clock: object,
    release_utc: object,
) -> bool:
    if (
        start_clock is None
        or end_clock is None
        or not isinstance(release_clock, float)
        or not isinstance(release_utc, datetime)
        or end_clock < start_clock
    ):
        return False
    start_offset = start_clock - release_clock
    end_offset = end_clock - release_clock
    duration = end_clock - start_clock
    if (
        not math.isfinite(start_offset)
        or not math.isfinite(end_offset)
        or not math.isfinite(duration)
        or start_offset < 0
        or end_offset < 0
    ):
        return False
    try:
        started_at = _format_utc(release_utc + timedelta(seconds=start_offset))
        ended_at = _format_utc(release_utc + timedelta(seconds=end_offset))
    except (OverflowError, ValueError):
        return False
    if started_at is None or ended_at is None:
        return False
    row["request_started_at_utc"] = started_at
    row["transport_ended_at_utc"] = ended_at
    row["start_offset_seconds"] = start_offset
    row["end_offset_seconds"] = end_offset
    row["duration_seconds"] = duration
    return True


def _read_status(response: object) -> int | None:
    try:
        status = response.status
    except BaseException:
        return None
    return status if type(status) is int else None


def _read_body(response: object) -> bytes | None:
    try:
        response_body = response.body
    except BaseException:
        return None
    return response_body if isinstance(response_body, bytes) else None


def _format_utc(value: object) -> str | None:
    if not isinstance(value, datetime):
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _build_burst(
    rows: list[dict[str, object]],
    model_count: int | None,
    preparation_failed: bool,
    barrier_released_at_utc: str | None,
    body_digest: str | None,
    burst_index: int | None,
) -> dict[str, object]:
    started_rows = [row for row in rows if row["started"]]
    timed_rows = [row for row in started_rows if row["timing_complete"]]
    starts = [float(row["start_offset_seconds"]) for row in timed_rows]
    ends = [float(row["end_offset_seconds"]) for row in timed_rows]
    intervals = [
        (float(row["start_offset_seconds"]), float(row["end_offset_seconds"]))
        for row in timed_rows
    ]
    group_elapsed = max(ends) if ends else None
    launch_spread = max(starts) - min(starts) if starts else None
    overlap_peak = _overlap_peak(intervals)
    successes = [
        row for row in rows
        if row["failure_class"] is None and row["validation_ok"]
    ]
    all_latencies = [float(row["duration_seconds"]) for row in timed_rows]
    success_latencies = [float(row["duration_seconds"]) for row in successes]
    all_timing_complete = len(timed_rows) == len(started_rows)
    all_started_statistics = (
        _latency_statistics(all_latencies) if all_timing_complete else None
    )
    return {
        "client_concurrency": len(rows),
        "model_count": model_count,
        "burst_index": burst_index,
        "preparation_failed": preparation_failed,
        "barrier_released_at_utc": barrier_released_at_utc,
        "body_sha256": body_digest,
        "planned_count": len(rows),
        "attempts": len(started_rows),
        "started_count": len(started_rows),
        "not_started_count": len(rows) - len(started_rows),
        "success_count": len(successes),
        "failure_counts": _count_failures(rows),
        "status_counts": _count_statuses(rows),
        "mean_success_latency_seconds": _latency_statistics(success_latencies)["mean"],
        "mean_all_latency_seconds": (
            all_started_statistics["mean"] if all_started_statistics is not None else None
        ),
        "success_latency_seconds": _latency_statistics(success_latencies),
        "all_started_latency_seconds": all_started_statistics,
        "group_elapsed_seconds": group_elapsed if len(timed_rows) == len(started_rows) else None,
        "launch_spread_seconds": launch_spread if len(timed_rows) == len(started_rows) else None,
        "peak_client_overlap": overlap_peak if len(timed_rows) == len(started_rows) else None,
        "timing_incomplete_count": len(started_rows) - len(timed_rows),
        "requests": rows,
    }


def _overlap_peak(intervals: Sequence[tuple[float, float]]) -> int:
    events: list[tuple[float, int]] = []
    for start, end in intervals:
        if end > start:
            events.append((start, 1))
            events.append((end, -1))
    active = 0
    peak = 0
    for _, change in sorted(events, key=lambda event: (event[0], event[1])):
        active += change
        peak = max(peak, active)
    return peak


def _latency_statistics(values: Sequence[float]) -> dict[str, int | float | None]:
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None, "min": None, "max": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "mean": math.fsum(ordered) / len(ordered),
        "p50": _nearest_rank(ordered, 0.50),
        "p95": _nearest_rank(ordered, 0.95),
        "min": ordered[0],
        "max": ordered[-1],
    }


def _nearest_rank(ordered: Sequence[float], percentile: float) -> float:
    return ordered[math.ceil(percentile * len(ordered)) - 1]


def _count_failures(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    counts = Counter(
        row["failure_class"] for row in rows if row["failure_class"] is not None
    )
    return {key: counts[key] for key in sorted(counts)}


def _count_statuses(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    counts = Counter(str(row["status"]) for row in rows if row["status"] is not None)
    return {key: counts[key] for key in sorted(counts, key=int)}


def _validate_burst(burst: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(burst, Mapping):
        raise TypeError("each burst must be a mapping")
    concurrency = burst.get("client_concurrency")
    model_count = burst.get("model_count")
    if type(concurrency) is not int or concurrency not in CONCURRENCY_CHOICES:
        raise ValueError("burst has an invalid client_concurrency")
    if model_count is not None and (
        type(model_count) is not int or model_count not in MODEL_COUNT_CHOICES
    ):
        raise ValueError("burst has an invalid model_count")
    raw_rows = burst.get("requests")
    if not isinstance(raw_rows, list) or len(raw_rows) != concurrency:
        raise ValueError("burst must retain one request row per sender")

    rows = [_validate_row(row) for row in raw_rows]
    if [row["request_id"] for row in rows] != list(range(1, concurrency + 1)):
        raise ValueError("request ids must be local and contiguous")
    burst_index = burst.get("burst_index")
    if burst_index is not None and (type(burst_index) is not int or burst_index not in (1, 2, 3)):
        raise ValueError("burst_index must be 1, 2, or 3")
    body_digest = burst.get("body_sha256")
    if not isinstance(body_digest, str) or not _SHA256_PATTERN.fullmatch(body_digest):
        raise ValueError("burst has an invalid body digest")
    if any(
        row["started"] and row["body_sent_sha256"] != body_digest for row in rows
    ):
        raise ValueError("request body digests do not match the burst body")
    preparation_failed = burst.get("preparation_failed", False)
    if type(preparation_failed) is not bool:
        raise ValueError("preparation_failed must be boolean")
    barrier_utc = burst.get("barrier_released_at_utc")
    if barrier_utc is not None and not _is_utc_timestamp(barrier_utc):
        raise ValueError("barrier release timestamp is invalid")

    started_rows = [row for row in rows if row["started"]]
    timed_rows = [row for row in started_rows if row["timing_complete"]]
    timing_complete = len(timed_rows) == len(started_rows)
    successes = [
        row for row in rows
        if row["failure_class"] is None and row["validation_ok"]
    ]
    all_latencies = [float(row["duration_seconds"]) for row in timed_rows]
    success_latencies = [float(row["duration_seconds"]) for row in successes]
    all_started_statistics = (
        _latency_statistics(all_latencies) if timing_complete else None
    )
    end_offsets = [float(row["end_offset_seconds"]) for row in timed_rows]
    start_offsets = [float(row["start_offset_seconds"]) for row in timed_rows]
    group_elapsed = max(end_offsets) if end_offsets and timing_complete else None
    reported_group_elapsed = _optional_finite_nonnegative(
        burst.get("group_elapsed_seconds"), "group_elapsed_seconds"
    )
    if reported_group_elapsed != group_elapsed:
        raise ValueError("reported group elapsed does not match request timings")
    intervals = [
        (float(row["start_offset_seconds"]), float(row["end_offset_seconds"]))
        for row in timed_rows
    ]
    return {
        "client_concurrency": concurrency,
        "model_count": model_count,
        "burst_index": burst_index,
        "body_sha256": body_digest,
        "preparation_failed": preparation_failed,
        "barrier_released_at_utc": barrier_utc,
        "planned_count": len(rows),
        "attempts": len(started_rows),
        "started_count": len(started_rows),
        "not_started_count": len(rows) - len(started_rows),
        "timing_incomplete_count": len(started_rows) - len(timed_rows),
        "success_count": len(successes),
        "failure_counts": _count_failures(rows),
        "status_counts": _count_statuses(rows),
        "mean_success_latency_seconds": _latency_statistics(success_latencies)["mean"],
        "mean_all_latency_seconds": (
            all_started_statistics["mean"] if all_started_statistics is not None else None
        ),
        "success_latency_seconds": _latency_statistics(success_latencies),
        "all_started_latency_seconds": all_started_statistics,
        "group_elapsed_seconds": group_elapsed,
        "launch_spread_seconds": (
            max(start_offsets) - min(start_offsets)
            if start_offsets and timing_complete
            else None
        ),
        "peak_client_overlap": _overlap_peak(intervals) if timing_complete else None,
        "requests": rows,
    }


def _validate_row(row: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(row, Mapping):
        raise TypeError("each request row must be a mapping")
    request_id = row.get("request_id")
    if type(request_id) is not int or request_id < 1:
        raise ValueError("request_id must be a positive integer")
    started = row.get("started")
    if type(started) is not bool:
        raise ValueError("started must be boolean")
    failure_class = row.get("failure_class")
    if failure_class is not None and (
        not isinstance(failure_class, str) or failure_class not in _FAILURE_CLASSES
    ):
        raise ValueError("failure_class is not recognized")
    validation_ok = row.get("validation_ok")
    if type(validation_ok) is not bool:
        raise ValueError("validation_ok must be boolean")
    status = row.get("status")
    if status is not None and type(status) is not int:
        raise ValueError("status must be an integer or null")
    timing_complete = row.get("timing_complete")
    if type(timing_complete) is not bool:
        raise ValueError("timing_complete must be boolean")
    start_offset = _optional_finite_nonnegative(
        row.get("start_offset_seconds"), "start_offset_seconds"
    )
    end_offset = _optional_finite_nonnegative(
        row.get("end_offset_seconds"), "end_offset_seconds"
    )
    duration = _optional_finite_nonnegative(row.get("duration_seconds"), "duration_seconds")
    started_at = row.get("request_started_at_utc")
    ended_at = row.get("transport_ended_at_utc")
    body_digest = row.get("body_sent_sha256")
    response_digest = row.get("canonical_response_sha256")
    if started:
        if failure_class == "not_started":
            raise ValueError("started request cannot use the not_started failure class")
        if timing_complete:
            if start_offset is None or not _is_utc_timestamp(started_at):
                raise ValueError("started request lacks a valid start sample")
            if not _is_utc_timestamp(ended_at):
                raise ValueError("started request lacks a valid end timestamp")
            if end_offset is None or duration is None:
                raise ValueError("started request lacks complete timing samples")
            if end_offset < start_offset:
                raise ValueError("response end precedes request start")
            if not math.isclose(
                duration, end_offset - start_offset, rel_tol=1e-9, abs_tol=1e-9
            ):
                raise ValueError("request duration does not match its offsets")
        elif any(
            value is not None
            for value in (start_offset, end_offset, duration, started_at, ended_at)
        ):
            raise ValueError("incomplete timing cannot include partial samples")
        if body_digest is None or not isinstance(body_digest, str) or not _SHA256_PATTERN.fullmatch(body_digest):
            raise ValueError("started request lacks a body digest")
        if status is None and failure_class not in ("timeout", "transport_error"):
            raise ValueError("request without an HTTP status has an invalid failure class")
        if status is not None and status != 200 and failure_class != "http_status":
            raise ValueError("non-200 status has an invalid failure class")
        if status == 200 and not validation_ok and failure_class != "invalid_200":
            raise ValueError("unvalidated 200 response has an invalid failure class")
    else:
        if any(value is not None for value in (start_offset, end_offset, duration, started_at, ended_at, body_digest, response_digest)):
            raise ValueError("not-started request contains transport data")
        if failure_class != "not_started":
            raise ValueError("not-started request must use the not_started failure class")
    if validation_ok:
        if status != 200 or failure_class not in (None, "measurement_error"):
            raise ValueError("validated requests must have status 200")
        if not isinstance(response_digest, str) or not _SHA256_PATTERN.fullmatch(response_digest):
            raise ValueError("validated request lacks a canonical response digest")
    elif response_digest is not None:
        raise ValueError("unvalidated request cannot include a canonical response digest")
    if failure_class is None and (
        not started or not validation_ok or status != 200 or not timing_complete
    ):
        raise ValueError("successful request fields are inconsistent")
    return {
        "request_id": request_id,
        "started": started,
        "request_started_at_utc": started_at,
        "transport_ended_at_utc": ended_at,
        "start_offset_seconds": start_offset,
        "end_offset_seconds": end_offset,
        "duration_seconds": duration,
        "timing_complete": timing_complete,
        "status": status,
        "failure_class": failure_class,
        "validation_ok": validation_ok,
        "body_sent_sha256": body_digest,
        "canonical_response_sha256": response_digest,
    }


def _is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def _optional_finite_nonnegative(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite nonnegative number or null")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be a finite nonnegative number or null")
    return normalized
