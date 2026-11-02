"""Offline startup timing summaries from allowlisted provider metadata."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone

from . import batch_experiment, batch_runtime, gpu_monitor

_WORKER_BOOT_PATTERN = re.compile(
    r"Booting worker with pid: ([1-9][0-9]{0,9})\s*\Z")
_LISTENING_PATTERN = re.compile(
    r"Listening at: https?://\S+(?:\s+\(([1-9][0-9]{0,9})\))?\s*\Z")
_SYSTEM_EVENTS = {
    "ReplicaCreated": "replica_created",
    "Scheduled": "scheduled",
    "Created": "container_created",
    "Started": "container_started",
    "Pulling": "pulling",
    "Pulled": "pulled",
}
_SYSTEM_EVENT_ORDER = (
    "replica_created",
    "scheduled",
    "container_created",
    "container_started",
)
_PULL_EVENT_ORDER = ("pulling", "pulled")
_SYSTEM_EVENT_SEQUENCE = (*_SYSTEM_EVENT_ORDER, *_PULL_EVENT_ORDER)
_MULTI_CONTAINER_EVENTS = frozenset({
    "container_created",
    "container_started",
    "pulling",
    "pulled",
})
_SYSTEM_EVENT_UNAVAILABLE = {
    "replica_created": "provider_replica_created_unavailable",
    "scheduled": "provider_scheduled_unavailable",
    "container_created": "provider_container_created_unavailable",
    "container_started": "provider_container_started_unavailable",
    "pulling": "provider_pulling_unavailable",
    "pulled": "provider_pulled_unavailable",
}
_LOG_TEXT_FIELDS = ("message", "log", "text", "line")
_TIMESTAMP_FIELDS = ("timestamp", "_timestamp")
_REPLICA_FIELDS = ("replica", "_replica")


class StartupError(ValueError):
    pass


def _normalize_utc(value: object, field: str) -> tuple[datetime, str]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip() == value:
        text = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            raise StartupError(f"{field}_invalid") from None
    else:
        raise StartupError(f"{field}_invalid")
    try:
        offset = parsed.utcoffset()
    except (OverflowError, ValueError):
        raise StartupError(f"{field}_invalid") from None
    if parsed.tzinfo is None or offset != timedelta(0):
        raise StartupError(f"{field}_must_be_utc")
    normalized = parsed.astimezone(timezone.utc)
    return normalized, normalized.isoformat(timespec="microseconds").replace(
        "+00:00", "Z")


def _timestamp_from_row(row: Mapping[str, object]) -> tuple[datetime, str]:
    try:
        raw = batch_experiment._row_metadata(
            row, _TIMESTAMP_FIELDS, "timestamp")
    except batch_experiment.ExperimentError:
        raise StartupError("provider_timestamp_invalid") from None
    return _normalize_utc(raw, "provider_timestamp")


def _finite_duration(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StartupError("warmup_duration_invalid")
    try:
        duration = float(value)
    except (OverflowError, ValueError):
        raise StartupError("warmup_duration_invalid") from None
    if not math.isfinite(duration) or duration < 0:
        raise StartupError("warmup_duration_invalid")
    return duration


def _duration(
    start: datetime | None,
    end: datetime | None,
    unavailable_reason: str,
    *,
    start_reason: str | None = None,
    end_reason: str | None = None,
) -> dict[str, object]:
    if start is None:
        return {"seconds": None,
                "unknown_reason": start_reason or unavailable_reason}
    if end is None:
        return {"seconds": None,
                "unknown_reason": end_reason or unavailable_reason}
    seconds = (end - start).total_seconds()
    if not math.isfinite(seconds) or seconds < 0:
        raise StartupError("timestamp_order_invalid")
    return {"seconds": seconds, "unknown_reason": None}


def _line_text(row: object) -> tuple[Mapping[str, object], str] | None:
    if not isinstance(row, Mapping):
        return None
    fields = [field for field in _LOG_TEXT_FIELDS if field in row]
    if len(fields) != 1 or not isinstance(row[fields[0]], str):
        return None
    return row, row[fields[0]].rstrip("\r\n")


def _gunicorn_event_rows(
    raw_log_rows: Sequence[object], pod: str, ready_pids: set[int]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    boot_by_pid: dict[int, tuple[datetime, str]] = {}
    listening: dict[tuple[int | None, str], dict[str, object]] = {}
    for row in raw_log_rows:
        parts = _line_text(row)
        if parts is None:
            continue
        metadata, line = parts
        boot_match = _WORKER_BOOT_PATTERN.search(line)
        listening_match = _LISTENING_PATTERN.search(line)
        if boot_match is None and listening_match is None:
            continue
        try:
            if batch_experiment._row_metadata(
                    metadata, _REPLICA_FIELDS, "replica") != pod:
                raise StartupError("provider_replica_mismatch")
            timestamp, timestamp_text = _timestamp_from_row(metadata)
        except batch_experiment.ExperimentError:
            raise StartupError("provider_replica_mismatch") from None
        if boot_match is not None:
            pid = int(boot_match.group(1))
            if pid not in ready_pids:
                raise StartupError("gunicorn_worker_churn")
            prior = boot_by_pid.get(pid)
            if prior is not None and prior[0] != timestamp:
                raise StartupError("gunicorn_worker_churn")
            boot_by_pid[pid] = (timestamp, timestamp_text)
        else:
            pid_text = listening_match.group(1)
            pid = int(pid_text) if pid_text is not None else None
            listening[(pid, timestamp_text)] = {
                "pid": pid,
                "timestamp_utc": timestamp_text,
            }
    boot_events = [
        {"pid": pid, "timestamp_utc": timestamp_text}
        for pid, (_timestamp, timestamp_text) in sorted(
            boot_by_pid.items(), key=lambda item: (item[1][0], item[0]))
    ]
    listening_events = sorted(
        listening.values(), key=lambda event: (event["timestamp_utc"], event["pid"] or 0)
    )
    return boot_events, listening_events


def _system_utc(value: object, field: str) -> tuple[datetime, str]:
    if type(value) is int or type(value) is float:
        epoch = float(value)
        if not math.isfinite(epoch):
            raise StartupError(f"{field}_invalid")
        try:
            parsed = datetime.fromtimestamp(epoch, timezone.utc)
        except (OverflowError, OSError, ValueError):
            raise StartupError(f"{field}_invalid") from None
        return parsed, parsed.isoformat(timespec="microseconds").replace(
            "+00:00", "Z")
    return _normalize_utc(value, field)


def _system_event_timestamp(
    row: Mapping[str, object], event: str | None = None
) -> tuple[datetime | None, str | None]:
    count = row.get("count")
    value = row.get("timestamp")
    if value is None and event == "replica_created":
        value = row.get("created_at")
    moment = None
    if value is not None:
        moment = _system_utc(value, "system_timestamp")[0]
    first = row.get("first_timestamp")
    last = row.get("last_timestamp")
    first_moment = None
    last_moment = None
    if first is not None:
        first_moment = _system_utc(first, "system_first_timestamp")[0]
    if last is not None:
        last_moment = _system_utc(last, "system_last_timestamp")[0]
    if type(count) is int and count > 1:
        return None, "provider_timestamp_ambiguous"
    if moment is not None:
        return moment, None
    if first_moment is None or last_moment is None:
        return None, "provider_timestamp_unavailable"
    if type(count) is int and count == 1 and first_moment == last_moment:
        return first_moment, None
    return None, "provider_timestamp_ambiguous"


def _unknown_reason(
    fields: Mapping[str, Mapping[str, object]], event: str
) -> str | None:
    reason = fields[event]["unknown_reason"]
    return reason if isinstance(reason, str) else None


def _system_lifecycle(
    system_metadata: object, pod: str
) -> tuple[dict[str, dict[str, object]], dict[str, datetime | None]]:
    if not isinstance(system_metadata, list):
        raise StartupError("system_metadata_invalid")
    exact: dict[str, set[datetime]] = {
        event: set() for event in _SYSTEM_EVENT_SEQUENCE}
    unknown_reasons: dict[str, set[str]] = {
        event: set() for event in _SYSTEM_EVENT_SEQUENCE}
    mismatched: set[str] = set()
    for row in system_metadata:
        if not isinstance(row, Mapping):
            raise StartupError("system_metadata_invalid")
        reason = row.get("reason")
        if not isinstance(reason, str) or reason not in _SYSTEM_EVENTS:
            continue
        event = _SYSTEM_EVENTS[reason]
        if row.get("involved_object") != pod:
            mismatched.add(event)
            continue
        timestamp, timestamp_reason = _system_event_timestamp(row, event)
        if timestamp is None:
            unknown_reasons[event].add(
                timestamp_reason or "provider_timestamp_unavailable")
        else:
            exact[event].add(timestamp)
    timestamps: dict[str, datetime | None] = {}
    fields: dict[str, dict[str, object]] = {}
    for event in _SYSTEM_EVENT_SEQUENCE:
        values = exact[event]
        if len(values) > 1:
            if event not in _MULTI_CONTAINER_EVENTS:
                raise StartupError("system_event_duplicate_mismatch")
            unknown_reasons[event].add("provider_multiple_container_events")
            known = None
        else:
            known = min(values) if values else None
        unknown = unknown_reasons[event]
        if unknown:
            timestamp = None
            reason = (
                "provider_timestamp_ambiguous"
                if "provider_timestamp_ambiguous" in unknown
                else sorted(unknown)[0])
        elif known is not None:
            timestamp = known
            reason = None
        else:
            timestamp = None
            reason = (
                "provider_object_not_exact_pod" if event in mismatched
                else _SYSTEM_EVENT_UNAVAILABLE[event])
        timestamps[event] = timestamp
        fields[event] = {
            "timestamp_utc": (
                timestamp.astimezone(timezone.utc).isoformat(
                    timespec="microseconds").replace("+00:00", "Z")
                if timestamp is not None else None
            ),
            "unknown_reason": reason,
        }
    known_times: list[datetime] = []
    for event in _SYSTEM_EVENT_ORDER:
        timestamp = timestamps[event]
        if timestamp is not None:
            known_times.append(timestamp)
    for earlier, later in zip(known_times, known_times[1:]):
        if later < earlier:
            raise StartupError("timestamp_order_invalid")
    return fields, timestamps


def _warmup_timing(warmup_metadata: object) -> tuple[
    dict[str, object], datetime | None, datetime | None, bool
]:
    if warmup_metadata is None:
        return {
            "status": None,
            "oracle_ok": None,
            "transport_started_at_utc": None,
            "transport_ended_at_utc": None,
            "elapsed_monotonic_seconds": None,
            "unknown_reason": "warmup_metadata_unavailable",
            "first_valid_response_unknown_reason": "warmup_metadata_unavailable",
        }, None, None, False
    if not isinstance(warmup_metadata, Mapping):
        raise StartupError("warmup_metadata_invalid")
    status = warmup_metadata.get("status")
    oracle_ok = warmup_metadata.get("oracle_ok")
    excluded = warmup_metadata.get("excluded")
    if ((status is not None and (type(status) is not int or not 100 <= status <= 599))
            or type(oracle_ok) is not bool or excluded is not True
            or oracle_ok and status != 200):
        raise StartupError("warmup_metadata_invalid")
    started_value = warmup_metadata.get("transport_started_at_utc")
    ended_value = warmup_metadata.get("transport_ended_at_utc")
    elapsed_value = warmup_metadata.get("elapsed_monotonic_seconds")
    if started_value is None or ended_value is None or elapsed_value is None:
        return {
            "status": status,
            "oracle_ok": oracle_ok,
            "transport_started_at_utc": None,
            "transport_ended_at_utc": None,
            "elapsed_monotonic_seconds": None,
            "unknown_reason": "warmup_timing_unavailable",
            "first_valid_response_unknown_reason": "warmup_timing_unavailable",
        }, None, None, False
    started, started_text = _normalize_utc(started_value, "warmup_start")
    ended, ended_text = _normalize_utc(ended_value, "warmup_end")
    elapsed = _finite_duration(elapsed_value)
    if ended < started:
        raise StartupError("timestamp_order_invalid")
    valid_response = status == 200 and oracle_ok is True
    timing = {
        "status": status,
        "oracle_ok": oracle_ok,
        "transport_started_at_utc": started_text,
        "transport_ended_at_utc": ended_text,
        "elapsed_monotonic_seconds": elapsed,
        "unknown_reason": None,
        "first_valid_response_unknown_reason": (
            None if valid_response else "first_valid_response_unobserved"),
    }
    return timing, started, ended, valid_response


def summarize_startup(
    raw_log_rows: object,
    system_metadata: object,
    profile: Mapping[str, object],
    pod: str,
    *,
    client_resume_requested_at_utc: object,
    client_resume_accepted_at_utc: object,
    client_ready_observed_at_utc: object,
    warmup_metadata: Mapping[str, object] | None = None,
    trusted_image_cache: bool | None = None,
) -> dict[str, object]:
    """Validate startup evidence and return only safe timestamps and durations."""
    if not isinstance(pod, str) or not pod:
        raise StartupError("pod_identity_invalid")
    requested, requested_text = _normalize_utc(
        client_resume_requested_at_utc, "resume_requested")
    accepted, accepted_text = _normalize_utc(
        client_resume_accepted_at_utc, "resume_accepted")
    observed, observed_text = _normalize_utc(
        client_ready_observed_at_utc, "ready_observed")
    if accepted < requested or observed < accepted:
        raise StartupError("timestamp_order_invalid")
    if trusted_image_cache is not None and type(trusted_image_cache) is not bool:
        raise StartupError("trusted_cache_metadata_invalid")
    try:
        run_id, batch_size, workers, _hashes = batch_experiment._profile_expectations(profile)
        readiness = batch_experiment.readiness_gate(
            raw_log_rows, profile=profile, pod=pod,
            expected_image=batch_experiment.EXPECTED_IMAGE,
            observed_image=batch_experiment.EXPECTED_IMAGE,
            expected_workers=workers)
        if readiness["run_id"] != run_id or readiness["batch_size"] != batch_size:
            raise StartupError("startup_profile_identity_invalid")
        ready_pids = set(readiness["pids"])
        base_times: dict[int, datetime] = {}
        batch_times: dict[int, datetime] = {}
        for row in raw_log_rows:
            provider_events = list(batch_experiment._provider_events([row], pod))
            if not provider_events:
                continue
            prefix, _timestamp_ms, line = provider_events[0]
            if prefix == gpu_monitor.PROFILE_PREFIX:
                continue
            if prefix == "VERDAEXPERIMENT ":
                payload = batch_experiment._event_payload(line, prefix)
                if payload.get("run_id") == run_id and payload.get("event") == "ready":
                    _timestamp, _timestamp_text = _timestamp_from_row(row)
                    previous = base_times.get(payload["pid"])
                    if previous is not None and previous != _timestamp:
                        raise StartupError("startup_readiness_duplicate_mismatch")
                    base_times[payload["pid"]] = _timestamp
            elif prefix == batch_runtime.EVENT_PREFIX:
                payload = batch_experiment._event_payload(line, prefix)
                if payload.get("run_id") == run_id and payload.get("event") == "ready":
                    _timestamp, _timestamp_text = _timestamp_from_row(row)
                    previous = batch_times.get(payload["pid"])
                    if previous is not None and previous != _timestamp:
                        raise StartupError("startup_readiness_duplicate_mismatch")
                    batch_times[payload["pid"]] = _timestamp
    except StartupError:
        raise
    except (batch_experiment.ExperimentError, TypeError, ValueError, KeyError):
        raise StartupError("startup_readiness_invalid") from None
    if set(base_times) != ready_pids or set(batch_times) != ready_pids:
        raise StartupError("startup_readiness_cardinality_invalid")
    all_ready_times = [*base_times.values(), *batch_times.values()]
    first_ready = min(all_ready_times)
    last_ready = max(all_ready_times)
    if first_ready < accepted:
        raise StartupError("timestamp_order_invalid")
    boot_events, listening_events = _gunicorn_event_rows(
        raw_log_rows, pod, ready_pids)
    boot_times: dict[int, datetime] = {}
    for event in boot_events:
        booted_at = _normalize_utc(
            event["timestamp_utc"], "gunicorn_boot_timestamp")[0]
        if booted_at > base_times[event["pid"]]:
            raise StartupError("timestamp_order_invalid")
        boot_times[event["pid"]] = booted_at
    first_boot_at = min(boot_times.values()) if boot_times else None
    first_listening_at = (
        _normalize_utc(
            listening_events[0]["timestamp_utc"],
            "gunicorn_listening_timestamp")[0]
        if listening_events else None)
    lifecycle, lifecycle_times = _system_lifecycle(system_metadata, pod)
    lifecycle_reasons = {
        event: _unknown_reason(lifecycle, event)
        for event in _SYSTEM_EVENT_SEQUENCE}
    container_started = lifecycle_times["container_started"]
    if container_started is not None and container_started > last_ready:
        raise StartupError("timestamp_order_invalid")
    warmup, warmup_started, warmup_ended, first_valid_response = _warmup_timing(
        warmup_metadata)
    if warmup_started is not None and warmup_started < observed:
        raise StartupError("timestamp_order_invalid")
    if warmup_ended is not None and warmup_ended < accepted:
        raise StartupError("timestamp_order_invalid")
    if trusted_image_cache is None:
        image_cache = {
            "status": "unknown",
            "unknown_reason": "trusted_cache_metadata_unavailable",
        }
    else:
        image_cache = {
            "status": "cached" if trusted_image_cache else "not_cached",
            "unknown_reason": None,
        }
    durations = {
        "resume_requested_to_accepted": _duration(
            requested, accepted, "client_resume_acceptance_unavailable"),
        "resume_requested_to_last_ready_event": _duration(
            requested, last_ready, "provider_readiness_unavailable"),
        "resume_accepted_to_last_ready_event": _duration(
            accepted, last_ready, "provider_readiness_unavailable"),
        "resume_requested_to_ready_observed": _duration(
            requested, observed, "client_readiness_observation_unavailable"),
        "resume_accepted_to_ready_observed": _duration(
            accepted, observed, "client_readiness_observation_unavailable"),
        "first_worker_boot_to_all_ready": _duration(
            first_boot_at, last_ready, "gunicorn_boot_unavailable"),
        "first_gunicorn_listening_to_all_ready": _duration(
            first_listening_at, last_ready, "gunicorn_listening_unavailable"),
        "replica_created_to_scheduled": _duration(
            lifecycle_times["replica_created"],
            lifecycle_times["scheduled"],
            "system_replica_lifecycle_unavailable",
            start_reason=lifecycle_reasons["replica_created"],
            end_reason=lifecycle_reasons["scheduled"]),
        "scheduled_to_container_created": _duration(
            lifecycle_times["scheduled"],
            lifecycle_times["container_created"],
            "system_scheduled_or_created_unavailable",
            start_reason=lifecycle_reasons["scheduled"],
            end_reason=lifecycle_reasons["container_created"]),
        "container_created_to_started": _duration(
            lifecycle_times["container_created"],
            lifecycle_times["container_started"],
            "system_created_or_started_unavailable",
            start_reason=lifecycle_reasons["container_created"],
            end_reason=lifecycle_reasons["container_started"]),
        "container_started_to_all_ready": _duration(
            container_started, last_ready, "system_started_unavailable",
            start_reason=lifecycle_reasons["container_started"]),
        "provider_pull_phase": _duration(
            lifecycle_times["pulling"], lifecycle_times["pulled"],
            "provider_pull_phase_unavailable",
            start_reason=lifecycle_reasons["pulling"],
            end_reason=lifecycle_reasons["pulled"]),
        "warmup_transport": {
            "seconds": warmup["elapsed_monotonic_seconds"],
            "unknown_reason": warmup["unknown_reason"],
        },
        "resume_requested_to_first_valid_response": _duration(
            requested, warmup_ended if first_valid_response else None,
            str(warmup["first_valid_response_unknown_reason"])),
        "resume_accepted_to_first_valid_response": _duration(
            accepted, warmup_ended if first_valid_response else None,
            str(warmup["first_valid_response_unknown_reason"])),

    }
    return {
        "workers": workers,
        "observation_count": 1,
        "client_timestamps": {
            "resume_requested_at_utc": requested_text,
            "resume_accepted_at_utc": accepted_text,
            "ready_observed_at_utc": observed_text,
        },
        "readiness": {
            "base_ready_count": len(base_times),
            "batch_ready_count": len(batch_times),
            "first_ready_at_utc": min(
                all_ready_times).astimezone(timezone.utc).isoformat(
                    timespec="microseconds").replace("+00:00", "Z"),
            "last_ready_at_utc": last_ready.astimezone(timezone.utc).isoformat(
                timespec="microseconds").replace("+00:00", "Z"),
            "base_first_ready_at_utc": min(base_times.values()).astimezone(
                timezone.utc).isoformat(timespec="microseconds").replace(
                    "+00:00", "Z"),
            "base_last_ready_at_utc": max(base_times.values()).astimezone(
                timezone.utc).isoformat(timespec="microseconds").replace(
                    "+00:00", "Z"),
            "batch_first_ready_at_utc": min(batch_times.values()).astimezone(
                timezone.utc).isoformat(timespec="microseconds").replace(
                    "+00:00", "Z"),
            "batch_last_ready_at_utc": max(batch_times.values()).astimezone(
                timezone.utc).isoformat(timespec="microseconds").replace(
                    "+00:00", "Z"),
        },
        "system_lifecycle": lifecycle,
        "gunicorn": {
            "booting_workers": boot_events,
            "listening_events": listening_events,
        },
        "warmup": warmup,
        "image_cache": image_cache,
        "durations_seconds": durations,
        "limitations": {
            "cross_clock_uncertainty_seconds": None,
            "cross_clock_uncertainty_reason": "provider_client_clock_offset_unmeasured",
            "container_started_to_all_ready": (
                "includes application and model initialization, CUDA "
                "initialization, HTTP warmup, and the readiness barrier; "
                "not pure weight loading"
            ),
            "first_worker_boot_to_all_ready": (
                "native same-pod timestamps from the first expected worker "
                "boot to the last all-worker readiness event; includes "
                "application and model initialization, CUDA initialization, "
                "HTTP warmup, and the readiness barrier; not pure weight "
                "loading"
            ),
            "first_gunicorn_listening_to_all_ready": (
                "native same-pod timestamps from the first Gunicorn listening "
                "event to the last all-worker readiness event; includes "
                "application and model initialization, CUDA initialization, "
                "HTTP warmup, and the readiness barrier; not pure weight "
                "loading"
            ),
            "resume_requested_to_last_ready_event": (
                "provider event timestamps for the last all-worker ready "
                "event; not the client readiness observation"
            ),
            "provider_pull_phase": (
                "provider event timestamps from the Pulling event to the "
                "Pulled event for the exact pod; may include image "
                "verification, checksum validation, scheduling, and pull; "
                "not guaranteed pure download bytes and not a cold-cache "
                "measurement"
            ),
            "resume_requested_to_ready_observed": (
                "client timestamps; includes provider ingestion and polling "
                "latency, not the provider ready event time"
            ),
            "observation": "one observation per worker count; not causal proof or an SLA",
        },
    }
