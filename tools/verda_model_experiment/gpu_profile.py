"""Local transport-injected GPU correlation helper for worker-count profiles."""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple

from . import gpu_monitor, measure
from .fixture import FIXTURE_BODY
from .runtime import validate_run_id

MODEL_COUNT = 8
PROFILE_WORKER_CHOICES = gpu_monitor.PROFILE_WORKER_CHOICES
TRANSPORT_TIMEOUT_SECONDS = 90.0
MIN_QUANTITATIVE_SAMPLES = 10
SAMPLE_SPACING_SECONDS = 1.0
MAX_CLOCK_DRIFT_MILLISECONDS = 5_000
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
STOP_REASONS = frozenset({
    "deadline",
    "fault_5xx",
    "fault_oracle",
    "fault_runtime",
    "persist_failed",
    "runner_error",
    "safety_stop",
})
FAULT_REASONS = frozenset({
    "fault_5xx",
    "fault_oracle",
    "fault_runtime",
})
LIMITATIONS = (
    "nvml_gpu_activity_is_not_sm_occupancy_or_flops",
    "nvml_memory_controller_activity_is_not_bandwidth_bytes",
    "sampler_interval_is_not_nvml_averaging_window",
    "samples_are_device_global_not_per_worker",
    "coverage_uses_expected_one_hz_opportunities",
    "quantitative_gpu_requires_ten_active_samples",
)


class GpuProfileCase(NamedTuple):
    case_index: int
    client_concurrency: int
    groups: int


CASE_PLAN = (
    GpuProfileCase(1, 1, 10),
    GpuProfileCase(2, 2, 6),
    GpuProfileCase(3, 4, 4),
    GpuProfileCase(4, 8, 4),
    GpuProfileCase(5, 16, 2),
    GpuProfileCase(6, 32, 1),
)
PLANNED_GROUPS = sum(case.groups for case in CASE_PLAN)
PLANNED_BURSTS = PLANNED_GROUPS * measure.BURSTS_PER_CASE
PLANNED_REQUESTS = sum(
    case.client_concurrency * measure.BURSTS_PER_CASE * case.groups
    for case in CASE_PLAN
)
_CASE_BY_INDEX = {case.case_index: case for case in CASE_PLAN}


def _validate_workers(value: object) -> int:
    if type(value) is not int or value not in PROFILE_WORKER_CHOICES:
        raise ValueError("workers must be one of the supported profile worker counts")
    return value


def _validate_positive_deadline(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("deadline_seconds must be a finite positive number")
    try:
        normalized = float(value)
    except (OverflowError, ValueError):
        raise ValueError("deadline_seconds must be a finite positive number") from None
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError("deadline_seconds must be a finite positive number")
    return normalized


def _read_clock(clock: Callable[[], float]) -> float | None:
    try:
        value = clock()
        if isinstance(value, bool):
            return None
        sampled = float(value)
    except Exception:
        return None
    return sampled if math.isfinite(sampled) else None


def _sender_tuple(sender_factory: Callable[[int], Sequence[Any]],
                  concurrency: int) -> tuple[Any, ...]:
    senders = sender_factory(concurrency)
    if not isinstance(senders, Sequence) or isinstance(senders, (str, bytes)):
        raise ValueError("sender factory must return a sequence")
    if len(senders) != concurrency:
        raise ValueError("sender factory returned the wrong sender count")
    normalized = tuple(senders)
    if any(not callable(sender) for sender in normalized):
        raise ValueError("every sender must be callable")
    return normalized


def _burst_fault(burst: Mapping[str, object]) -> str | None:
    rows = burst.get("requests")
    if not isinstance(rows, list):
        return "fault_runtime"
    statuses = [
        row.get("status") for row in rows
        if isinstance(row, Mapping) and type(row.get("status")) is int
    ]
    if any(status >= 500 for status in statuses):
        return "fault_5xx"
    failure_classes = {
        row.get("failure_class") for row in rows if isinstance(row, Mapping)
    }
    if "invalid_200" in failure_classes:
        return "fault_oracle"
    if failure_classes & {"measurement_error", "not_started", "transport_error"}:
        return "fault_runtime"
    return None


def _burst_record(case: GpuProfileCase, group_index: int,
                  burst: Mapping[str, object] | None,
                  error_class: str | None = None,
                  workers: int = MODEL_COUNT) -> dict[str, object]:
    workers = _validate_workers(workers)
    return {
        "case_index": case.case_index,
        "case_concurrency": case.client_concurrency,
        "group_index": group_index,
        "workers": workers,
        "model_count": workers,
        "burst": burst,
        "error_class": error_class,
        "fault": _burst_fault(burst) if burst is not None else "fault_runtime",
    }


def _deliver(persist: Callable[[Mapping[str, object]], object],
             record: Mapping[str, object]) -> bool:
    try:
        persist(record)
    except Exception:
        return False
    return True


def _case_latency(case: GpuProfileCase,
                  records: Sequence[Mapping[str, object]],
                  workers: int = MODEL_COUNT) -> dict[str, object]:
    workers = _validate_workers(workers)
    if any(
        type(record.get("workers")) is not int
        or record.get("workers") != workers
        or type(record.get("model_count")) is not int
        or record.get("model_count") != workers
        for record in records
    ):
        raise ValueError("burst worker identity mismatch")
    bursts = [
        record["burst"] for record in records
        if record.get("case_index") == case.case_index
        and isinstance(record.get("burst"), Mapping)
    ]
    rows = []
    for burst in bursts:
        requests = burst.get("requests")
        if isinstance(requests, list):
            rows.extend(requests)
    group_summaries = []
    group_indices = sorted({
        int(record["group_index"]) for record in records
        if record.get("case_index") == case.case_index
        and type(record.get("group_index")) is int
    })
    for group_index in group_indices:
        group_bursts = [
            record["burst"] for record in records
            if record.get("case_index") == case.case_index
            and record.get("group_index") == group_index
            and isinstance(record.get("burst"), Mapping)
        ]
        if len(group_bursts) != measure.BURSTS_PER_CASE:
            continue
        try:
            summary = measure.summarize_rounds(group_bursts)
        except (TypeError, ValueError):
            continue
        group_summaries.append({
            "group_index": group_index,
            "summary": summary,
        })
    successes = [
        row for row in rows
        if row.get("failure_class") is None and row.get("validation_ok") is True
    ]
    failures = Counter(
        str(row["failure_class"]) for row in rows
        if row.get("failure_class") is not None
    )
    statuses = Counter(
        str(row["status"]) for row in rows
        if type(row.get("status")) is int
    )
    return {
        "model_count": workers,
        "planned_count": case.client_concurrency * measure.BURSTS_PER_CASE * case.groups,
        "attempts": sum(
            int(burst.get("attempts", 0)) for burst in bursts
            if type(burst.get("attempts")) is int
        ),
        "success_count": len(successes),
        "failure_counts": {key: failures[key] for key in sorted(failures)},
        "status_counts": {
            key: statuses[key] for key in sorted(statuses, key=int)
        },
        "group_summaries": group_summaries,
    }


def _build_profile_result(run_id: str, owner_pid: int,
                          records: Sequence[Mapping[str, object]],
                          stop_reason: str | None, started: float,
                          clock: Callable[[], float],
                          deadline_seconds: float,
                          workers: int = MODEL_COUNT) -> dict[str, object]:
    workers = _validate_workers(workers)
    completed_bursts = sum(
        1 for record in records if isinstance(record.get("burst"), Mapping))
    cases = []
    for case in CASE_PLAN:
        case_records = [
            record for record in records
            if record.get("case_index") == case.case_index
        ]
        latency = _case_latency(case, case_records, workers)
        cases.append({
            "case_index": case.case_index,
            "workers": workers,
            "model_count": workers,
            "client_concurrency": case.client_concurrency,
            "groups_planned": case.groups,
            "groups_completed": len(latency["group_summaries"]),
            "bursts_completed": sum(
                1 for record in case_records
                if isinstance(record.get("burst"), Mapping)
            ),
            "latency": latency,
        })
    completed_groups = sum(case["groups_completed"] for case in cases)
    success_count = sum(case["latency"]["success_count"] for case in cases)
    attempts = sum(case["latency"]["attempts"] for case in cases)
    finished = _read_clock(clock)
    return {
        "run_id": run_id,
        "owner_pid": owner_pid,
        "workers": workers,
        "model_count": workers,
        "scope": "device_global",
        "planned_requests": PLANNED_REQUESTS,
        "planned_bursts": PLANNED_BURSTS,
        "planned_groups": PLANNED_GROUPS,
        "completed_bursts": completed_bursts,
        "completed_groups": completed_groups,
        "attempts": attempts,
        "success_count": success_count,
        "stop_reason": stop_reason,
        "deadline_seconds": deadline_seconds,
        "elapsed_seconds": (
            finished - started if finished is not None else None
        ),
        "cases": cases,
        "bursts": list(records),
    }


def run_gpu_profile(
    sender_factory: Callable[[int], Sequence[measure.Sender]],
    validate: measure.Validator,
    persist: Callable[[Mapping[str, object]], object],
    *,
    run_id: str,
    owner_pid: int,
    deadline_seconds: float,
    safety_check: Callable[[], object] | None = None,
    clock: Callable[[], float] = time.perf_counter,
    workers: int = MODEL_COUNT,
) -> dict[str, object]:
    """Run the fixed 402-request GPU profile with injected transport and callbacks."""
    validate_run_id(run_id)
    workers = _validate_workers(workers)
    if type(owner_pid) is not int or owner_pid < 1:
        raise ValueError("owner_pid must be a positive integer")
    if not callable(sender_factory):
        raise TypeError("sender_factory must be callable")
    if not callable(validate):
        raise TypeError("validate must be callable")
    if not callable(persist):
        raise TypeError("persist must be callable")
    if safety_check is not None and not callable(safety_check):
        raise TypeError("safety_check must be callable")
    if not callable(clock):
        raise TypeError("clock must be callable")
    deadline = _validate_positive_deadline(deadline_seconds)
    started = _read_clock(clock)
    if started is None:
        raise ValueError("clock must return finite numbers")
    records: list[dict[str, object]] = []
    stop_reason: str | None = None
    for case in CASE_PLAN:
        if stop_reason is not None:
            break
        now = _read_clock(clock)
        if now is None:
            stop_reason = "runner_error"
            break
        if now - started >= deadline:
            stop_reason = "deadline"
            break
        try:
            senders = _sender_tuple(sender_factory, case.client_concurrency)
        except Exception:
            stop_reason = "runner_error"
            break
        for group_index in range(1, case.groups + 1):
            if stop_reason is not None:
                break
            for burst_index in range(1, measure.BURSTS_PER_CASE + 1):
                now = _read_clock(clock)
                if now is None:
                    stop_reason = "runner_error"
                    break
                if now - started >= deadline:
                    stop_reason = "deadline"
                    break
                try:
                    burst = measure.run_burst(
                        senders,
                        FIXTURE_BODY,
                        validate,
                        TRANSPORT_TIMEOUT_SECONDS,
                        model_count=workers,
                        burst_index=burst_index,
                        clock=clock,
                    )
                except Exception:
                    record = _burst_record(
                        case, group_index, None, error_class="runner_error",
                        workers=workers)
                    records.append(record)
                    stop_reason = (
                        "persist_failed"
                        if not _deliver(persist, record)
                        else "runner_error"
                    )
                    break
                record = _burst_record(case, group_index, burst, workers=workers)
                records.append(record)
                if not _deliver(persist, record):
                    stop_reason = "persist_failed"
                    break
                fault = record["fault"]
                if isinstance(fault, str) and fault in FAULT_REASONS:
                    stop_reason = fault
                    break
                now = _read_clock(clock)
                if now is None:
                    stop_reason = "runner_error"
                    break
                if now - started >= deadline:
                    stop_reason = "deadline"
                    break
                if safety_check is not None:
                    try:
                        outcome = safety_check()
                    except Exception:
                        stop_reason = "safety_stop"
                        break
                    if outcome is False:
                        stop_reason = "safety_stop"
                        break
    return _build_profile_result(
        run_id, owner_pid, records, stop_reason, started, clock, deadline,
        workers=workers)


def parse_gpu_profile_lines(
    lines: Iterable[str], *, expected_workers: int = MODEL_COUNT
) -> dict[str, object]:
    expected_workers = _validate_workers(expected_workers)
    samples = []
    ignored_lines = 0
    invalid_lines = 0
    for line in lines:
        if not isinstance(line, str) or not line.startswith(gpu_monitor.PROFILE_PREFIX):
            ignored_lines += 1
            continue
        try:
            sample = gpu_monitor.parse_profile_line(line)
            if sample is not None and sample.get("workers") != expected_workers:
                raise ValueError("gpu profile worker identity mismatch")
        except ValueError:
            invalid_lines += 1
            continue
        if sample is not None:
            samples.append(sample)
    return {
        "samples": samples,
        "ignored_line_count": ignored_lines,
        "invalid_line_count": invalid_lines,
    }


def _bounded_stop_reason(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) and value in STOP_REASONS else "runner_error"


def _parse_utc_milliseconds(value: object) -> float:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("invalid transport timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ValueError("invalid transport timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("invalid transport timestamp")
    return parsed.timestamp() * 1000.0


def _profile_cases(
    profile_result: Mapping[str, object], expected_workers: int
) -> dict[int, Mapping[str, object]]:
    raw_cases = profile_result.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != len(CASE_PLAN):
        raise ValueError("profile result must contain the fixed case plan")
    cases = {}
    for case, raw_case in zip(CASE_PLAN, raw_cases):
        if not isinstance(raw_case, Mapping):
            raise ValueError("profile case must be a mapping")
        if (raw_case.get("case_index") != case.case_index
                or raw_case.get("client_concurrency") != case.client_concurrency
                or type(raw_case.get("workers")) is not int
                or raw_case.get("workers") != expected_workers
                or type(raw_case.get("model_count")) is not int
                or raw_case.get("model_count") != expected_workers):
            raise ValueError("profile case plan or worker identity mismatch")
        latency = raw_case.get("latency")
        if not isinstance(latency, Mapping):
            raise ValueError("profile case latency missing")
        if (type(latency.get("model_count")) is not int
                or latency.get("model_count") != expected_workers):
            raise ValueError("profile case latency worker identity mismatch")
        cases[case.case_index] = raw_case
    return cases


def _merge_windows(windows: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    merged = []
    for start, end in sorted(windows):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end
    return [(start, end) for start, end in merged]


def _case_windows(
    profile_result: Mapping[str, object], expected_workers: int
) -> dict[int, list[tuple[float, float]]]:
    raw_bursts = profile_result.get("bursts")
    if not isinstance(raw_bursts, list):
        raise ValueError("profile bursts missing")
    windows: dict[int, list[tuple[float, float]]] = {
        case.case_index: [] for case in CASE_PLAN
    }
    for record in raw_bursts:
        if not isinstance(record, Mapping):
            raise ValueError("burst record must be a mapping")
        case_index = record.get("case_index")
        case = _CASE_BY_INDEX.get(case_index)
        if case is None or record.get("case_concurrency") != case.client_concurrency:
            raise ValueError("burst case identity mismatch")
        if (type(record.get("workers")) is not int
                or record.get("workers") != expected_workers
                or type(record.get("model_count")) is not int
                or record.get("model_count") != expected_workers):
            raise ValueError("burst worker identity mismatch")
        burst = record.get("burst")
        if burst is None:
            continue
        if not isinstance(burst, Mapping):
            raise ValueError("burst must be a mapping")
        if (type(burst.get("model_count")) is not int
                or burst.get("model_count") != expected_workers):
            raise ValueError("burst model count identity mismatch")
        if burst.get("client_concurrency") != case.client_concurrency:
            raise ValueError("burst concurrency mismatch")
        rows = burst.get("requests")
        if not isinstance(rows, list) or len(rows) != case.client_concurrency:
            raise ValueError("burst request rows missing")
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("burst request row must be a mapping")
            started = row.get("started")
            timing_complete = row.get("timing_complete")
            if type(started) is not bool or type(timing_complete) is not bool:
                raise ValueError("burst request timing flags invalid")
            if not started or not timing_complete:
                continue
            start = _parse_utc_milliseconds(row.get("request_started_at_utc"))
            end = _parse_utc_milliseconds(row.get("transport_ended_at_utc"))
            if end < start:
                raise ValueError("transport window is reversed")
            windows[case_index].append((start, end))
    return {
        case_index: _merge_windows(case_windows)
        for case_index, case_windows in windows.items()
    }


def _sample_interval(sample: Mapping[str, object]) -> tuple[float, float]:
    start = float(sample["epoch_ms"])
    return start, start + float(sample["read_duration_ms"])


def _overlaps(sample: Mapping[str, object],
              windows: Sequence[tuple[float, float]]) -> bool:
    start, end = _sample_interval(sample)
    return any(start <= window_end and end >= window_start
               for window_start, window_end in windows)


def _statistics(values: Sequence[int]) -> dict[str, int | float | None]:
    ordered = sorted(values)
    count = len(ordered)
    return {
        "count": count,
        "mean": math.fsum(ordered) / count,
        "p50": ordered[math.ceil(0.50 * count) - 1],
        "p95": ordered[math.ceil(0.95 * count) - 1],
        "min": ordered[0],
        "max": ordered[-1],
    }


def _quantitative(values: Sequence[int]) -> dict[str, int | float | None] | None:
    if len(values) < MIN_QUANTITATIVE_SAMPLES:
        return None
    return _statistics(values)


def _gpu_fields(active: Sequence[Mapping[str, object]],
                transport_duration: float,
                overlapping_count: int) -> dict[str, object]:
    gpu_values = [
        int(sample["gpu_activity_percent"]) for sample in active
        if type(sample.get("gpu_activity_percent")) is int
    ]
    memory_values = [
        int(sample["memory_controller_activity_percent"]) for sample in active
        if type(sample.get("memory_controller_activity_percent")) is int
    ]
    power_values = [
        int(sample["power_milliwatts"]) for sample in active
        if type(sample.get("power_milliwatts")) is int
    ]
    expected = (
        max(1, math.ceil(transport_duration / SAMPLE_SPACING_SECONDS))
        if transport_duration > 0 else 0
    )
    quantitative = len(active) >= MIN_QUANTITATIVE_SAMPLES
    return {
        "transport_duration_seconds": transport_duration,
        "overlapping_sample_count": overlapping_count,
        "active_sample_count": len(active),
        "expected_sample_count_at_one_hz": expected,
        "coverage_fraction": (
            min(1.0, len(active) / expected) if expected else None
        ),
        "gpu_activity_percent": _quantitative(gpu_values),
        "memory_controller_activity_percent": _quantitative(memory_values),
        "power_milliwatts": (
            _quantitative(power_values) if quantitative else None
        ),
        "gpu_quantitative_reason": (
            None if quantitative else "insufficient_active_samples"
        ),
        "power_unavailable_reason": (
            "insufficient_active_samples" if not quantitative
            else "insufficient_power_samples"
            if len(power_values) < MIN_QUANTITATIVE_SAMPLES else None
        ),
    }


def correlate_gpu_profile(
    profile_result: Mapping[str, object],
    gpu_samples: object,
    *,
    expected_run_id: str,
    expected_owner_pid: int,
    expected_workers: int = MODEL_COUNT,
) -> dict[str, object]:
    """Correlate owner samples with completed transport windows without network access."""
    validate_run_id(expected_run_id)
    expected_workers = _validate_workers(expected_workers)
    if type(expected_owner_pid) is not int or expected_owner_pid < 1:
        raise ValueError("expected_owner_pid must be a positive integer")
    if not isinstance(profile_result, Mapping):
        raise TypeError("profile_result must be a mapping")
    if (profile_result.get("run_id") != expected_run_id
            or profile_result.get("owner_pid") != expected_owner_pid
            or type(profile_result.get("workers")) is not int
            or profile_result.get("workers") != expected_workers
            or type(profile_result.get("model_count")) is not int
            or profile_result.get("model_count") != expected_workers):
        raise ValueError("profile identity mismatch")
    cases = _profile_cases(profile_result, expected_workers)
    windows = _case_windows(profile_result, expected_workers)
    invalid_line_count = 0
    ignored_line_count = 0
    if isinstance(gpu_samples, Mapping) and "samples" in gpu_samples:
        raw_samples = gpu_samples.get("samples")
        invalid_line_count = gpu_samples.get("invalid_line_count", 0)
        ignored_line_count = gpu_samples.get("ignored_line_count", 0)
        if type(invalid_line_count) is not int or invalid_line_count < 0:
            invalid_line_count = 0
        if type(ignored_line_count) is not int or ignored_line_count < 0:
            ignored_line_count = 0
    elif isinstance(gpu_samples, Sequence) and not isinstance(
            gpu_samples, (str, bytes)):
        raw_samples = gpu_samples
    else:
        raise TypeError("gpu_samples must be a sample sequence or parse result")
    if not isinstance(raw_samples, Sequence) or isinstance(raw_samples, (str, bytes)):
        raise TypeError("gpu samples must be a sequence")
    counts = {
        "received": len(raw_samples),
        "invalid_line_count": invalid_line_count,
        "ignored_line_count": ignored_line_count,
        "schema_invalid": 0,
        "run_mismatch": 0,
        "crossworker": 0,
        "worker_mismatch": 0,
        "duplicate": 0,
        "clock_anomaly": 0,
        "accepted": 0,
        "unavailable": 0,
        "usable": 0,
        "active": 0,
        "inactive": 0,
    }
    accepted = []
    last_sample = None
    for raw_sample in raw_samples:
        if isinstance(raw_sample, str):
            try:
                raw_sample = gpu_monitor.parse_profile_line(raw_sample)
            except ValueError:
                counts["invalid_line_count"] += 1
                continue
            if raw_sample is None:
                counts["ignored_line_count"] += 1
                continue
        if not isinstance(raw_sample, Mapping) or not gpu_monitor.validate_profile_record(
                raw_sample):
            counts["schema_invalid"] += 1
            continue
        if raw_sample.get("run_id") != expected_run_id:
            counts["run_mismatch"] += 1
            continue
        if raw_sample.get("owner_pid") != expected_owner_pid:
            counts["crossworker"] += 1
            continue
        if raw_sample.get("workers") != expected_workers:
            counts["worker_mismatch"] += 1
            continue
        monotonic_ms = int(raw_sample["monotonic_ms"])
        epoch_ms = int(raw_sample["epoch_ms"])
        if last_sample is not None:
            last_monotonic = int(last_sample["monotonic_ms"])
            last_epoch = int(last_sample["epoch_ms"])
            if monotonic_ms == last_monotonic or epoch_ms == last_epoch:
                counts["duplicate"] += 1
                continue
            monotonic_delta = monotonic_ms - last_monotonic
            epoch_delta = epoch_ms - last_epoch
            if (monotonic_delta < 0 or epoch_delta < 0
                    or abs(monotonic_delta - epoch_delta)
                    > MAX_CLOCK_DRIFT_MILLISECONDS):
                counts["clock_anomaly"] += 1
                continue
        last_sample = raw_sample
        accepted.append(raw_sample)
    counts["accepted"] = len(accepted)
    usable = []
    for sample in accepted:
        if (type(sample.get("gpu_activity_percent")) is int
                and type(sample.get("memory_controller_activity_percent")) is int):
            usable.append(sample)
        else:
            counts["unavailable"] += 1
    counts["usable"] = len(usable)
    case_results = []
    active_keys = set()
    for case in CASE_PLAN:
        case_windows = windows[case.case_index]
        duration = sum(end - start for start, end in case_windows) / 1000.0
        overlapping = [
            sample for sample in accepted if _overlaps(sample, case_windows)
        ]
        active = [
            sample for sample in usable if _overlaps(sample, case_windows)
        ]
        active_keys.update(
            (sample["monotonic_ms"], sample["epoch_ms"]) for sample in active
        )
        fields = _gpu_fields(active, duration, len(overlapping))
        case_results.append({
            "case_index": case.case_index,
            "client_concurrency": case.client_concurrency,
            "latency": dict(cases[case.case_index]["latency"]),
            **fields,
        })
    counts["active"] = len(active_keys)
    counts["inactive"] = counts["usable"] - counts["active"]
    all_windows = _merge_windows([
        window for case_windows in windows.values() for window in case_windows
    ])
    overall_duration = sum(end - start for start, end in all_windows) / 1000.0
    overall_active = [
        sample for sample in usable
        if (sample["monotonic_ms"], sample["epoch_ms"]) in active_keys
    ]
    overall_fields = _gpu_fields(
        overall_active, overall_duration, len(overall_active))
    return {
        "run_id": expected_run_id,
        "owner_pid": expected_owner_pid,
        "workers": expected_workers,
        "model_count": expected_workers,
        "scope": "device_global",
        "planned_requests": PLANNED_REQUESTS,
        "profile_stop_reason": _bounded_stop_reason(
            profile_result.get("stop_reason")),
        "completed_bursts": sum(
            1 for record in profile_result.get("bursts", [])
            if isinstance(record, Mapping)
            and isinstance(record.get("burst"), Mapping)
        ),
        "sample_counts": counts,
        "identity": {
            "run_id": expected_run_id,
            "owner_pid": expected_owner_pid,
            "workers": expected_workers,
            "run_mismatch_count": counts["run_mismatch"],
            "crossworker_count": counts["crossworker"],
            "worker_mismatch_count": counts["worker_mismatch"],
            "consistent": (
                counts["run_mismatch"] == 0
                and counts["crossworker"] == 0
                and counts["worker_mismatch"] == 0
            ),
        },
        "cases": case_results,
        "overall": overall_fields,
        "limitations": list(LIMITATIONS),
    }
