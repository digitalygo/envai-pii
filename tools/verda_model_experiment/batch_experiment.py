"""Offline-first collector for the fixed Verda chunk-batching GPU matrix."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from . import batch_runtime, gpu_monitor, gpu_profile, runtime
from .fixture import FIXTURE_BODY

ORACLE_SHA256 = "ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40"
EXPECTED_IMAGE = (
    "ghcr.io/digitalygo/envai-pii@sha256:"
    "c1d9d9c089047f7c1e4b7b0815e91a12cd810c963ddb58ba1f0da1233e961714"
)
BATCH_CHOICES = (4, 8, 16)
MATRIX_DEADLINE_SECONDS = 700.0
LOG_WINDOW_SECONDS = 55.0
LOG_OVERLAP_SECONDS = 5.0
LOG_LIMIT = 1000
LOG_QUERY_LIMIT = 1024
LOG_FINALIZATION_SECONDS = 30.0
MAX_LOG_FINALIZATION_SECONDS = 90.0
LOG_FINALIZATION_PASSES = 3
LOG_SETTLE_SECONDS = 0.5
SAMPLE_MAX_AGE_SECONDS = 15.0
SAMPLE_CLOCK_TOLERANCE_MS = 10_000
EXPERIMENT_PIDS_BUDGET = 512
STEADY_PIDS_GUARD = 409
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_LOG_TEXT_FIELDS = ("message", "log", "text", "line")
_TIMESTAMP_FIELDS = ("timestamp", "_timestamp")
_REPLICA_FIELDS = ("replica", "_replica")
_GPU_NUMERIC_FIELDS = (
    "gpu_activity_percent", "memory_controller_activity_percent",
)
_CORRELATION_ANOMALY_FIELDS = (
    "schema_invalid", "run_mismatch", "crossworker", "worker_mismatch",
    "duplicate", "clock_anomaly",
)
_BASE_SOURCE_FIELDS = frozenset({
    "source_app_ok", "source_config_ok", "source_execution_ok",
    "source_service_ok",
})
_BASE_SETTINGS = {
    "settings_ok": True,
    "auth_upstream": True,
    "analysis_timeout_seconds": 60,
    "max_concurrent_analyses": 16,
    "max_queued_analyses": 32,
    "queue_timeout_seconds": 30,
    "gunicorn_threads": runtime.EXPECTED_THREADS,
}
_RESOURCE_FIELDS = {
    "cuda_allocated_bytes": "cuda_allocated_reason",
    "cuda_free_bytes": "cuda_free_reason",
    "cuda_total_bytes": "cuda_total_reason",
    "torch_max_allocated_bytes": "torch_max_allocated_reason",
    "cgroup_memory_current_bytes": "cgroup_memory_current_reason",
    "cgroup_memory_peak_bytes": "cgroup_memory_peak_reason",
    "cgroup_memory_limit_bytes": "cgroup_memory_limit_reason",
    "cgroup_pids_current": "cgroup_pids_current_reason",
    "cgroup_pids_limit": "cgroup_pids_limit_reason",
    "cpu_quota_us": "cpu_quota_reason",
    "cpu_period_us": "cpu_period_reason",
    "cpu_affinity_count": "cpu_affinity_reason",
}
_BASE_COMMON_FIELDS = frozenset({
    "run_id", "event", "pid", "workers", *_BASE_SOURCE_FIELDS,
    *_BASE_SETTINGS,
    "gpu_l40s", "gpu_device_count", "gpu_reason",
    *_RESOURCE_FIELDS, *_RESOURCE_FIELDS.values(),
})
_BASE_READY_FIELDS = _BASE_COMMON_FIELDS | frozenset({
    "parameter_bytes", "buffer_bytes", "model_dtypes", "model_metrics_reason",
})
_BASE_SAMPLE_FIELDS = _BASE_READY_FIELDS | frozenset({"request_count"})
_OVERLAY_HASH_FIELDS = frozenset({
    "base_app_sha256", "helper_sha256", "detector_source_sha256",
    "detector_code_sha256", "manifest_sha256",
})


class ExperimentTransport(Protocol):
    def post_inference(self, body: bytes, timeout: float) -> tuple[int, bytes]: ...

    def get_logs(self, *, start: float, end: float, pod: str,
                 limit: int = 1000, order: str = "asc") -> list[Any]: ...


class ExperimentError(ValueError):
    pass


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("artifact write failed")
        view = view[written:]


class _ArtifactStore:
    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        os.chmod(self.directory, 0o700, follow_symlinks=False)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
            raise OSError("private artifact directory unavailable")
        self._burst_fd = self._create("bursts.jsonl")

    def _create(self, name: str) -> int:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.directory / name, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise OSError("private artifact file unavailable")
        return descriptor

    def append_burst(self, record: Mapping[str, object]) -> None:
        data = _json_bytes(record) + b"\n"
        _write_all(self._burst_fd, data)
        os.fsync(self._burst_fd)

    def write_jsonl(self, name: str, records: Sequence[Mapping[str, object]]) -> None:
        descriptor = self._create(name)
        try:
            for record in records:
                _write_all(descriptor, _json_bytes(record) + b"\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def write_json(self, name: str, value: object) -> None:
        descriptor = self._create(name)
        try:
            _write_all(descriptor, _json_bytes(value) + b"\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def close(self) -> None:
        descriptor = self._burst_fd
        if descriptor is not None:
            self._burst_fd = None
            os.close(descriptor)


def _validate_expected_workers(value: object) -> int:
    if type(value) is not int or value not in gpu_profile.PROFILE_WORKER_CHOICES:
        raise ExperimentError("profile worker count invalid")
    return value


def _profile_expectations(
    profile: Mapping[str, object],
) -> tuple[str, int, int, dict[str, str]]:
    run_id = profile.get("run_id")
    runtime.validate_run_id(run_id)
    batch_size = profile.get("batch_size")
    if type(batch_size) is not int or batch_size not in BATCH_CHOICES:
        raise ExperimentError("batch size must be 4, 8, or 16")
    workers = _validate_expected_workers(profile.get("workers"))
    source_hashes = profile.get("source_hashes")
    if (not isinstance(source_hashes, Mapping)
            or dict(source_hashes) != runtime.SOURCE_HASHES):
        raise ExperimentError("base source profile mismatch")
    overrides = profile.get("overrides")
    if (not isinstance(overrides, Mapping)
            or type(overrides.get("workers")) is not int
            or overrides.get("workers") != workers
            or overrides.get("batch_size") != batch_size):
        raise ExperimentError("batch profile settings mismatch")
    overlay = overrides.get("batch_overlay")
    if (not isinstance(overlay, Mapping)
            or overlay.get("function") != batch_runtime.TARGET_FUNCTION
            or overlay.get("application") != "base+overlay"):
        raise ExperimentError("batch overlay profile missing")
    hashes = {key: overlay.get(key) for key in _OVERLAY_HASH_FIELDS}
    if (set(hashes) != _OVERLAY_HASH_FIELDS
            or any(not isinstance(value, str) or not _HASH_PATTERN.fullmatch(value)
                   for value in hashes.values())
            or hashes["base_app_sha256"] != runtime.SOURCE_HASHES["app.py"]):
        raise ExperimentError("batch overlay hashes invalid")
    return run_id, batch_size, workers, hashes


def _parse_utc(value: object) -> int:
    if not isinstance(value, str) or value.strip() != value:
        raise ExperimentError("provider timestamp invalid")
    text = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ExperimentError("provider timestamp invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ExperimentError("provider timestamp invalid")
    milliseconds = parsed.timestamp() * 1000
    if not math.isfinite(milliseconds):
        raise ExperimentError("provider timestamp invalid")
    return int(milliseconds)


def _event_payload(line: str, prefix: str) -> dict[str, object]:
    try:
        payload = json.loads(line[len(prefix):].strip())
    except (ValueError, TypeError):
        raise ExperimentError("provider event JSON invalid") from None
    if not isinstance(payload, dict):
        raise ExperimentError("provider event schema invalid")
    return payload


def _row_metadata(row: Mapping[str, object], fields: Sequence[str],
                  label: str) -> object:
    present = [field for field in fields if field in row]
    if not present:
        raise ExperimentError(f"provider {label} missing")
    value = row[present[0]]
    if any(row[field] != value for field in present[1:]):
        raise ExperimentError(f"provider {label} conflict")
    return value


def _provider_events(logs: object, pod: str):
    if not isinstance(logs, list):
        raise ExperimentError("provider logs must be a list")
    for row in logs:
        if not isinstance(row, Mapping):
            raise ExperimentError("provider log row invalid")
        text_fields = [field for field in _LOG_TEXT_FIELDS if field in row]
        if not text_fields:
            continue
        if len(text_fields) != 1 or not isinstance(row[text_fields[0]], str):
            raise ExperimentError("provider log message invalid")
        line = row[text_fields[0]].rstrip("\r\n")
        prefixes = (
            "VERDAEXPERIMENT ", batch_runtime.EVENT_PREFIX,
            gpu_monitor.PROFILE_PREFIX,
        )
        prefix = next((candidate for candidate in prefixes
                       if line.startswith(candidate)), None)
        if prefix is None:
            if any(line.startswith(candidate.rstrip()) for candidate in prefixes):
                raise ExperimentError("provider event prefix invalid")
            continue
        if _row_metadata(row, _REPLICA_FIELDS, "replica") != pod:
            raise ExperimentError("provider replica mismatch")
        timestamp_ms = _parse_utc(
            _row_metadata(row, _TIMESTAMP_FIELDS, "timestamp"))
        yield prefix, timestamp_ms, line


def _validate_base_event(payload: Mapping[str, object], *, event: str,
                         run_id: str, expected_workers: int = 8) -> None:
    expected_workers = _validate_expected_workers(expected_workers)
    fields = _BASE_READY_FIELDS if event == "ready" else _BASE_SAMPLE_FIELDS
    if set(payload) != fields or payload.get("event") != event:
        raise ExperimentError("base event schema mismatch")
    if event == "sample" and type(payload.get("request_count")) is not int:
        raise ExperimentError("base sample request count invalid")
    if (payload.get("run_id") != run_id or type(payload.get("pid")) is not int
            or payload["pid"] < 1 or type(payload.get("workers")) is not int
            or payload["workers"] != expected_workers):
        raise ExperimentError("base event identity mismatch")
    if any(payload.get(key) is not True for key in _BASE_SOURCE_FIELDS):
        raise ExperimentError("base source verification failed")
    if any(type(payload.get(key)) is not type(value)
           or payload.get(key) != value for key, value in _BASE_SETTINGS.items()):
        raise ExperimentError("base settings mismatch")
    if (payload.get("gpu_l40s") is not True
            or type(payload.get("gpu_device_count")) is not int
            or payload.get("gpu_device_count") != 1
            or payload.get("gpu_reason") is not None):
        raise ExperimentError("GPU readiness mismatch")
    for key, value in payload.items():
        if key not in runtime.EVENT_KEYS or not runtime._safe_event_value(key, value):
            raise ExperimentError("base event value invalid")
    for metric, reason_key in _RESOURCE_FIELDS.items():
        value = payload[metric]
        reason = payload[reason_key]
        if value is None:
            if not isinstance(reason, str) or reason not in runtime.REASON_CODES:
                raise ExperimentError("base resource metric reason invalid")
        elif type(value) is not int or value < 0 or reason is not None:
            raise ExperimentError("base resource metric invalid")
    required_metrics = (
        "cgroup_memory_current_bytes", "cgroup_memory_limit_bytes",
        "cgroup_pids_current", "cuda_free_bytes", "cuda_total_bytes",
    )
    if any(type(payload[key]) is not int for key in required_metrics):
        raise ExperimentError("base resource metric unavailable")
    if (type(payload.get("parameter_bytes")) is not int
            or payload["parameter_bytes"] != 1_230_259_380
            or type(payload.get("buffer_bytes")) is not int
            or payload["buffer_bytes"] != 512
            or payload.get("model_dtypes") != "float32"
            or payload.get("model_metrics_reason") is not None):
        raise ExperimentError("model metrics mismatch")


def _validate_batch_event(payload: Mapping[str, object], *, run_id: str,
                          batch_size: int,
                          expected_hashes: Mapping[str, str],
                          expected_workers: int = 8) -> None:
    expected_workers = _validate_expected_workers(expected_workers)
    if set(payload) != batch_runtime.READY_EVENT_FIELDS:
        raise ExperimentError("batch event schema mismatch")
    if (payload.get("event") != "ready" or payload.get("run_id") != run_id
            or type(payload.get("pid")) is not int or payload["pid"] < 1
            or type(payload.get("workers")) is not int
            or payload["workers"] != expected_workers
            or type(payload.get("batch_size")) is not int
            or payload["batch_size"] != batch_size):
        raise ExperimentError("batch readiness identity mismatch")
    if any(payload.get(key) != value for key, value in expected_hashes.items()):
        raise ExperimentError("batch overlay hash mismatch")
    if any(payload.get(key) is not True for key in batch_runtime.READY_BOOLEAN_FIELDS):
        raise ExperimentError("batch overlay readiness failed")
    expected_calls = (63 + batch_size - 1) // batch_size
    expected_values = {
        "warm_calls": expected_calls,
        "warm_max_batch": batch_size,
        "warm_sum_batches": 63,
        "fixture_chunks": 63,
    }
    if any(type(payload.get(key)) is not int or payload.get(key) != value
           for key, value in expected_values.items()):
        raise ExperimentError("batch warmup evidence mismatch")
    if any(not isinstance(payload.get(key), str)
           or not _HASH_PATTERN.fullmatch(payload[key])
           for key in _OVERLAY_HASH_FIELDS):
        raise ExperimentError("batch overlay hash invalid")


def _resource_guard(event: Mapping[str, object]) -> dict[str, object]:
    memory_current = event["cgroup_memory_current_bytes"]
    memory_limit = event["cgroup_memory_limit_bytes"]
    gpu_free = event["cuda_free_bytes"]
    gpu_total = event["cuda_total_bytes"]
    pids_current = event["cgroup_pids_current"]
    pids_limit = event["cgroup_pids_limit"]
    if (type(memory_current) is not int or type(memory_limit) is not int
            or memory_limit <= 0 or memory_current < 0
            or memory_current > memory_limit):
        raise ExperimentError("memory_headroom_unknown")
    if (type(gpu_free) is not int or type(gpu_total) is not int
            or gpu_total <= 0 or gpu_free < 0 or gpu_free > gpu_total):
        raise ExperimentError("GPU_headroom_unknown")
    if type(pids_current) is not int or pids_current < 0:
        raise ExperimentError("pid_headroom_unknown")
    free_memory = memory_limit - memory_current
    if free_memory * 5 < memory_limit:
        raise ExperimentError("memory_headroom_insufficient")
    if gpu_free * 5 < gpu_total:
        raise ExperimentError("GPU_headroom_insufficient")
    if pids_limit is None:
        if event.get("cgroup_pids_limit_reason") != "limit_unavailable":
            raise ExperimentError("pids_limit_unknown")
        effective_limit = EXPERIMENT_PIDS_BUDGET
    elif type(pids_limit) is int and pids_limit > 0:
        if event.get("cgroup_pids_limit_reason") is not None:
            raise ExperimentError("pids_limit_invalid")
        effective_limit = pids_limit
    else:
        raise ExperimentError("pids_limit_invalid")
    if pids_current > min(STEADY_PIDS_GUARD, effective_limit):
        raise ExperimentError("pid_headroom_insufficient")
    return {
        "ram_free_fraction": free_memory / memory_limit,
        "vram_free_fraction": gpu_free / gpu_total,
        "pids_current": pids_current,
        "pids_limit": pids_limit,
        "pids_limit_state": "unbounded" if pids_limit is None else "bounded",
        "pids_limit_reason": (
            "limit_unavailable" if pids_limit is None else None),
        "pids_effective_limit": effective_limit,
        "pids_experiment_budget": EXPERIMENT_PIDS_BUDGET,
        "pids_guard": STEADY_PIDS_GUARD,
    }


def readiness_gate(
    logs: list[Any], *, profile: Mapping[str, object], pod: str,
    expected_image: str, observed_image: str,
    expected_workers: int = 8,
) -> dict[str, object]:
    run_id, batch_size, workers, hashes = _profile_expectations(profile)
    expected_workers = _validate_expected_workers(expected_workers)
    if expected_workers != workers:
        raise ExperimentError("profile worker count mismatch")
    if not isinstance(pod, str) or not pod:
        raise ExperimentError("exact pod is required")
    if (expected_image != EXPECTED_IMAGE
            or not isinstance(observed_image, str)
            or observed_image != expected_image):
        raise ExperimentError("image expectation mismatch")
    base: dict[int, tuple[dict[str, object], int, str]] = {}
    batch: dict[int, tuple[dict[str, object], int, str]] = {}
    samples: list[tuple[dict[str, object], int]] = []
    for prefix, timestamp_ms, line in _provider_events(logs, pod):
        if prefix == gpu_monitor.PROFILE_PREFIX:
            continue
        if prefix == "VERDAEXPERIMENT ":
            payload = _event_payload(line, prefix)
            if payload.get("run_id") != run_id:
                continue
            event = payload.get("event")
            if event == "ready":
                _validate_base_event(
                    payload, event="ready", run_id=run_id,
                    expected_workers=workers)
                pid = payload["pid"]
                _resource_guard(payload)
                target = base
            elif event == "sample":
                _validate_base_event(
                    payload, event="sample", run_id=run_id,
                    expected_workers=workers)
                pid = payload["pid"]
                samples.append((payload, timestamp_ms))
                continue
            else:
                raise ExperimentError("base worker failure or churn")
        else:
            payload = _event_payload(line, prefix)
            if payload.get("run_id") != run_id:
                continue
            if payload.get("event") != "ready":
                raise ExperimentError("batch worker failure")
            _validate_batch_event(
                payload, run_id=run_id, batch_size=batch_size,
                expected_hashes=hashes, expected_workers=workers)
            pid = payload["pid"]
            target = batch
        prior = target.get(pid)
        current = (payload, timestamp_ms, line)
        if prior is not None and prior != current:
            raise ExperimentError("duplicate readiness event mismatch")
        target[pid] = current
    if len(base) != workers or len(batch) != workers or set(base) != set(batch):
        raise ExperimentError("readiness requires matching profile worker PIDs")
    pids = tuple(sorted(base))
    if any(batch[pid][1] < base[pid][1] for pid in pids):
        raise ExperimentError("batch readiness predates base readiness")
    if any(payload["pid"] not in base for payload, _ in samples):
        raise ExperimentError("unknown worker PID in readiness logs")
    resources = [_resource_guard(base[pid][0]) for pid in pids]
    return {
        "run_id": run_id,
        "batch_size": batch_size,
        "workers": workers,
        "pids": pids,
        "owner_pid": min(pids),
        "image_verified": True,
        "source_verified": True,
        "settings_verified": True,
        "overlay_hashes": dict(hashes),
        "base_ready_by_pid": {pid: base[pid][0] for pid in pids},
        "batch_ready_by_pid": {pid: batch[pid][0] for pid in pids},
        "resource_guard": resources,
    }


def _validated_gpu_sample(
    payload: Mapping[str, object], provider_ms: int, *,
    run_id: str, owner_pid: int, expected_workers: int = 8,
) -> dict[str, object]:
    expected_workers = _validate_expected_workers(expected_workers)
    if not gpu_monitor.validate_profile_record(payload):
        raise ExperimentError("GPU sample schema invalid")
    if (payload["run_id"] != run_id or payload["owner_pid"] != owner_pid
            or payload["workers"] != expected_workers):
        raise ExperimentError("GPU sample identity mismatch")
    if abs(provider_ms - payload["epoch_ms"]) > SAMPLE_CLOCK_TOLERANCE_MS:
        raise ExperimentError("GPU sample provenance timestamp mismatch")
    return dict(payload)


def _gpu_sample_failure(
        samples: Mapping[tuple[int, int], Mapping[str, object]],
        now_ms: int) -> str | None:
    if not samples:
        return "gpu_sample_missing"
    latest = max(samples.values(), key=lambda sample: sample["epoch_ms"])
    age_ms = now_ms - latest["epoch_ms"]
    if age_ms > SAMPLE_MAX_AGE_SECONDS * 1000:
        return "gpu_sample_stale"
    if age_ms < -SAMPLE_CLOCK_TOLERANCE_MS:
        raise ExperimentError("GPU sample timestamp is in the future")
    if any(type(latest[field]) is not int for field in _GPU_NUMERIC_FIELDS):
        return "gpu_sample_unavailable"
    return None


def parse_gpu_samples(
    logs: list[Any], *, pod: str, run_id: str, owner_pid: int,
    expected_workers: int = 8,
) -> list[dict[str, object]]:
    runtime.validate_run_id(run_id)
    expected_workers = _validate_expected_workers(expected_workers)
    if not isinstance(pod, str) or not pod or type(owner_pid) is not int or owner_pid < 1:
        raise ExperimentError("GPU sample identity invalid")
    samples: dict[tuple[int, int], dict[str, object]] = {}
    for prefix, provider_ms, line in _provider_events(logs, pod):
        if prefix != gpu_monitor.PROFILE_PREFIX:
            continue
        payload = _validated_gpu_sample(
            _event_payload(line, prefix), provider_ms,
            run_id=run_id, owner_pid=owner_pid,
            expected_workers=expected_workers)
        key = (payload["monotonic_ms"], payload["epoch_ms"])
        prior = samples.get(key)
        if prior is not None and prior != payload:
            raise ExperimentError("conflicting duplicate GPU sample")
        samples[key] = payload
    return [samples[key] for key in sorted(samples)]


class _LogReader:
    def __init__(self, transport: ExperimentTransport, pod: str,
                 monotonic: Callable[[], float], deadline: float) -> None:
        self.transport = transport
        self.pod = pod
        self.monotonic = monotonic
        self.deadline = deadline
        self.calls = 0

    def _window(self, start: float, end: float) -> list[Any]:
        if self.monotonic() >= self.deadline or self.calls >= LOG_QUERY_LIMIT:
            raise ExperimentError("log_collection_deadline")
        if end <= start or end - start > LOG_WINDOW_SECONDS:
            raise ExperimentError("log window invalid")
        self.calls += 1
        rows = self.transport.get_logs(
            start=start, end=end, pod=self.pod,
            limit=LOG_LIMIT, order="asc")
        if not isinstance(rows, list) or len(rows) > LOG_LIMIT:
            raise ExperimentError("provider log page invalid")
        if len(rows) < LOG_LIMIT:
            return rows
        midpoint = (start + end) / 2
        if midpoint <= start or midpoint >= end:
            raise ExperimentError("provider log page remains capped")
        return self._window(start, midpoint) + self._window(midpoint, end)

    def range(self, start: float, end: float) -> list[Any]:
        rows = []
        cursor = start
        while cursor < end:
            query_start = max(start, cursor - LOG_OVERLAP_SECONDS)
            window_end = min(end, query_start + LOG_WINDOW_SECONDS)
            rows.extend(self._window(query_start, window_end))
            if window_end >= end:
                break
            cursor = window_end
        return rows


def _validate_monitor_event(
    payload: Mapping[str, object], *, run_id: str, pids: set[int],
    expected_workers: int = 8,
) -> str:
    expected_workers = _validate_expected_workers(expected_workers)
    event = payload.get("event")
    if event in {"startup_failed", "exit", "child_exit"}:
        if payload.get("run_id") != run_id:
            return ""
        raise ExperimentError("worker churn or startup failure")
    if event not in {"ready", "sample"}:
        raise ExperimentError("unknown base event")
    if payload.get("run_id") != run_id:
        return ""
    if event == "ready":
        _validate_base_event(
            payload, event="ready", run_id=run_id,
            expected_workers=expected_workers)
        if payload["pid"] not in pids:
            raise ExperimentError("unknown worker PID")
        return "ready"
    _validate_base_event(
        payload, event="sample", run_id=run_id,
        expected_workers=expected_workers)
    pid = payload["pid"]
    if pid not in pids:
        raise ExperimentError("unknown worker PID")
    return "sample"


def _summarize_resource_guards(guards: Sequence[Mapping[str, object]]) -> dict[str, object]:
    limits = {guard.get("pids_limit") for guard in guards}
    limit_reasons = {guard.get("pids_limit_reason") for guard in guards}
    limit_state = (
        "unbounded" if limits == {None}
        else "bounded" if len(limits) == 1 and None not in limits
        else "mixed"
    )
    limit_reason = (
        "mixed" if limit_state == "mixed"
        else next(iter(limit_reasons)) if len(limit_reasons) == 1
        else "mixed")
    return {
        "minimum_ram_free_fraction": min(
            float(guard["ram_free_fraction"]) for guard in guards),
        "minimum_vram_free_fraction": min(
            float(guard["vram_free_fraction"]) for guard in guards),
        "maximum_pids_current": max(int(guard["pids_current"]) for guard in guards),
        "pids_limit": next(iter(limits)) if len(limits) == 1 else "mixed",
        "pids_limit_state": limit_state,
        "pids_limit_reason": limit_reason,
        "pids_experiment_budget": EXPERIMENT_PIDS_BUDGET,
        "pids_guard": STEADY_PIDS_GUARD,
    }


def _summarize_profile(profile_result: Mapping[str, object]) -> list[dict[str, object]]:
    cases = []
    records = profile_result.get("bursts")
    if not isinstance(records, list):
        raise ExperimentError("profile burst records missing")
    for plan in gpu_profile.CASE_PLAN:
        case_records = [
            record for record in records
            if isinstance(record, Mapping)
            and record.get("case_index") == plan.case_index
        ]
        durations = []
        elapsed = []
        groups: dict[int, set[int]] = {}
        successes = 0
        attempts = 0
        for record in case_records:
            group_index = record.get("group_index")
            burst = record.get("burst")
            if type(group_index) is int:
                groups.setdefault(group_index, set())
            if not isinstance(burst, Mapping):
                continue
            burst_index = burst.get("burst_index")
            if type(group_index) is int and type(burst_index) is int:
                groups[group_index].add(burst_index)
            group_elapsed = burst.get("group_elapsed_seconds")
            if isinstance(group_elapsed, (int, float)) and not isinstance(group_elapsed, bool):
                if math.isfinite(float(group_elapsed)) and group_elapsed >= 0:
                    elapsed.append(float(group_elapsed))
            requests = burst.get("requests")
            if not isinstance(requests, list):
                continue
            for row in requests:
                if not isinstance(row, Mapping):
                    continue
                if row.get("started") is True:
                    attempts += 1
                if (row.get("failure_class") is None
                        and row.get("validation_ok") is True
                        and row.get("timing_complete") is True
                        and isinstance(row.get("duration_seconds"), (int, float))
                        and not isinstance(row.get("duration_seconds"), bool)
                        and math.isfinite(float(row["duration_seconds"]))):
                    successes += 1
                    durations.append(float(row["duration_seconds"]))
        ordered = sorted(durations)
        elapsed_sum = math.fsum(elapsed)
        cases.append({
            "case_index": plan.case_index,
            "client_concurrency": plan.client_concurrency,
            "groups_completed": sum(1 for indices in groups.values() if indices == {1, 2, 3}),
            "bursts_completed": sum(1 for record in case_records
                                     if isinstance(record.get("burst"), Mapping)),
            "attempts": attempts,
            "success_count": successes,
            "mean_seconds": math.fsum(ordered) / len(ordered) if ordered else None,
            "p95_seconds": ordered[math.ceil(0.95 * len(ordered)) - 1] if ordered else None,
            "group_elapsed_seconds_sum": elapsed_sum,
            "requests_per_second": successes / elapsed_sum if elapsed_sum > 0 else None,
        })
    return cases


def _gpu_evidence(correlation: Mapping[str, object]) -> dict[str, object]:
    counts = correlation["sample_counts"]
    anomalies = sum(counts[field] for field in _CORRELATION_ANOMALY_FIELDS)
    cases = correlation["cases"]
    insufficient = [
        case["case_index"] for case in cases
        if case["active_sample_count"] < gpu_profile.MIN_QUANTITATIVE_SAMPLES
    ]
    identity_ok = correlation["identity"]["consistent"] is True
    overall_ok = correlation["overall"]["gpu_quantitative_reason"] is None
    reason = None
    if not identity_ok or anomalies:
        reason = "gpu_correlation_anomaly"
    elif insufficient:
        reason = "gpu_case_samples_insufficient"
    elif not overall_ok:
        reason = "gpu_quantitative_insufficient"
    return {
        "sufficient": reason is None,
        "reason": reason,
        "correlation_anomalies": anomalies,
        "insufficient_cases": insufficient,
        "minimum_case_active_samples": min(
            (case["active_sample_count"] for case in cases), default=0),
        "required_case_active_samples": gpu_profile.MIN_QUANTITATIVE_SAMPLES,
    }


def _canonical_sha256(response_body: bytes) -> str:
    def unique_pairs(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    def reject_constant(value):
        raise ValueError("non-standard JSON number")

    try:
        parsed = json.loads(
            response_body.decode("utf-8"), object_pairs_hook=unique_pairs,
            parse_constant=reject_constant)
        if not isinstance(parsed, dict):
            raise ValueError("response is not an object")
        canonical = _json_bytes(parsed)
    except (UnicodeDecodeError, ValueError, TypeError, OverflowError):
        raise ExperimentError("response JSON invalid") from None
    return hashlib.sha256(canonical).hexdigest()


def _response(status: object, body: object) -> tuple[int, bytes]:
    if type(status) is not int or not isinstance(body, bytes):
        raise ExperimentError("transport response invalid")
    return status, body


def _invoke_safety(callback: Callable[[], object] | None) -> bool:
    if callback is None:
        return True
    try:
        return callback() is not False
    except Exception:
        return False


def _positive_duration(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite positive number")
    try:
        normalized = float(value)
    except (OverflowError, ValueError):
        raise ValueError(f"{name} must be a finite positive number") from None
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return normalized


def _finite_clock_sample(clock: Callable[[], float]) -> float | None:
    try:
        value = clock()
        if isinstance(value, bool):
            return None
        sampled = float(value)
    except Exception:
        return None
    return sampled if math.isfinite(sampled) else None


def _utc_timestamp(epoch_seconds: object) -> str | None:
    if isinstance(epoch_seconds, bool) or not isinstance(epoch_seconds, (int, float)):
        return None
    try:
        epoch = float(epoch_seconds)
        if not math.isfinite(epoch):
            return None
        value = datetime.fromtimestamp(epoch, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def run_matrix(
    transport: ExperimentTransport,
    profile: Mapping[str, object],
    pod: str,
    ready_logs: list[Any],
    output_dir: str | os.PathLike[str],
    *,
    expected_image: str,
    observed_image: str,
    safety_check: Callable[[], object] | None = None,
    clock: Callable[[], float] = time.perf_counter,
    pause: Callable[[float], None] = time.sleep,
    log_finalization_seconds: float = LOG_FINALIZATION_SECONDS,
) -> dict[str, object]:
    run_id, batch_size, workers, _ = _profile_expectations(profile)
    log_finalization_seconds = _positive_duration(
        log_finalization_seconds, "log_finalization_seconds")
    if log_finalization_seconds > MAX_LOG_FINALIZATION_SECONDS:
        raise ValueError("log_finalization_seconds exceeds the bounded maximum")
    readiness = readiness_gate(
        ready_logs, profile=profile, pod=pod,
        expected_image=expected_image, observed_image=observed_image,
        expected_workers=workers)
    if safety_check is not None and not callable(safety_check):
        raise TypeError("safety_check must be callable")
    if not callable(clock):
        raise TypeError("clock must be callable")
    if not callable(pause):
        raise TypeError("pause must be callable")
    store = _ArtifactStore(output_dir)
    try:
        initial_safe = _invoke_safety(safety_check)
        if not initial_safe:
            evidence = {
                "run_id": run_id, "batch_size": batch_size,
                "workers": workers,
                "owner_pid": readiness["owner_pid"],
                "stop_reason": "safety_stop", "warmup_excluded": False,
                "matrix_complete": False, "cases": [],
            }
            store.write_json("result.json", evidence)
            return {**evidence, "readiness": readiness}
        warm_started_clock = _finite_clock_sample(clock)
        warm_started_utc = _utc_timestamp(time.time())
        try:
            warm_status, warm_body = _response(
                *transport.post_inference(FIXTURE_BODY, gpu_profile.TRANSPORT_TIMEOUT_SECONDS))
            warm_digest = _canonical_sha256(warm_body) if warm_status == 200 else None
        except Exception:
            warm_status = None
            warm_digest = None
        warm_ended_clock = _finite_clock_sample(clock)
        warm_ended_utc = _utc_timestamp(time.time())
        if warm_started_clock is not None and warm_ended_clock is not None:
            elapsed_candidate = warm_ended_clock - warm_started_clock
            warm_elapsed = (
                elapsed_candidate
                if math.isfinite(elapsed_candidate) and elapsed_candidate >= 0
                else None
            )
        else:
            warm_elapsed = None
        warmup_ok = warm_status == 200 and warm_digest == ORACLE_SHA256
        store.write_json("warmup.json", {
            "excluded": True,
            "status": warm_status,
            "oracle_ok": warmup_ok,
            "transport_started_at_utc": warm_started_utc,
            "transport_ended_at_utc": warm_ended_utc,
            "elapsed_monotonic_seconds": warm_elapsed,
        })
        if not warmup_ok:
            evidence = {
                "run_id": run_id, "batch_size": batch_size,
                "workers": workers,
                "owner_pid": readiness["owner_pid"],
                "stop_reason": "warmup_failed", "warmup_excluded": True,
                "warmup_status": warm_status, "matrix_complete": False,
                "cases": [],
            }
            store.write_json("result.json", evidence)
            return {**evidence, "readiness": readiness}
        matrix_started = clock()
        matrix_started_utc = time.time()
        matrix_deadline = matrix_started + MATRIX_DEADLINE_SECONDS
        log_reader = _LogReader(
            transport, pod, clock, matrix_deadline + log_finalization_seconds)
        known_pids = set(readiness["pids"])
        resource_checks = list(readiness["resource_guard"])
        latest_samples: dict[int, tuple[dict[str, object], int]] = {}
        base_samples: dict[bytes, dict[str, object]] = {}
        gpu_samples: dict[tuple[int, int], dict[str, object]] = {}
        last_query_end = matrix_started_utc
        safety_failure: str | None = None

        def inspect_logs(rows: list[Any], now_ms: int) -> None:
            nonlocal safety_failure
            for prefix, provider_ms, line in _provider_events(rows, pod):
                payload = _event_payload(line, prefix)
                if prefix == "VERDAEXPERIMENT ":
                    if payload.get("run_id") != run_id:
                        continue
                    result = _validate_monitor_event(
                        payload, run_id=run_id, pids=known_pids,
                        expected_workers=workers)
                    if result in {"ready", "sample"}:
                        resource_checks.append(_resource_guard(payload))
                    if result == "sample":
                        pid = payload["pid"]
                        previous = latest_samples.get(pid)
                        if previous is None or provider_ms >= previous[1]:
                            latest_samples[pid] = (payload, provider_ms)
                        base_samples[_json_bytes(payload)] = dict(payload)
                elif prefix == batch_runtime.EVENT_PREFIX:
                    if payload.get("run_id") != run_id:
                        continue
                    _validate_batch_event(
                        payload, run_id=run_id, batch_size=batch_size,
                        expected_hashes=readiness["overlay_hashes"],
                        expected_workers=workers)
                    if payload["pid"] not in known_pids:
                        raise ExperimentError("unknown worker PID")
                elif prefix == gpu_monitor.PROFILE_PREFIX:
                    sample = _validated_gpu_sample(
                        payload, provider_ms, run_id=run_id,
                        owner_pid=readiness["owner_pid"],
                        expected_workers=workers)
                    key = (sample["monotonic_ms"], sample["epoch_ms"])
                    previous = gpu_samples.get(key)
                    if previous is not None and previous != sample:
                        raise ExperimentError("conflicting duplicate GPU sample")
                    gpu_samples[key] = sample
            if latest_samples:
                for pid, (sample, timestamp_ms) in latest_samples.items():
                    if timestamp_ms > now_ms + SAMPLE_CLOCK_TOLERANCE_MS:
                        raise ExperimentError("provider sample timestamp is in the future")
                    _resource_guard(sample)

        def safe_between_bursts() -> bool:
            nonlocal last_query_end, safety_failure
            if not _invoke_safety(safety_check):
                safety_failure = "operator_safety_stop"
                return False
            now_clock = clock()
            if now_clock >= matrix_deadline:
                safety_failure = "deadline"
                return False
            now_epoch = time.time()
            start = max(
                0.0,
                matrix_started_utc - 15.0 if not latest_samples
                else last_query_end - LOG_OVERLAP_SECONDS,
            )
            try:
                rows = log_reader.range(start, now_epoch)
                inspect_logs(rows, int(now_epoch * 1000))
            except ExperimentError as error:
                safety_failure = str(error)
                return False
            except Exception:
                safety_failure = "safety_check_failed"
                return False
            last_query_end = now_epoch
            now_ms = int(now_epoch * 1000)
            if set(latest_samples) != known_pids:
                safety_failure = "resource_sample_missing"
                return False
            if any((now_ms - timestamp_ms) / 1000 > SAMPLE_MAX_AGE_SECONDS
                   for _, timestamp_ms in latest_samples.values()):
                safety_failure = "resource_sample_stale"
                return False
            try:
                gpu_failure = _gpu_sample_failure(gpu_samples, now_ms)
            except ExperimentError as error:
                safety_failure = str(error)
                return False
            if gpu_failure is not None:
                safety_failure = gpu_failure
                return False
            return True

        def sender_factory(concurrency: int):
            def sender(body: bytes, timeout: float):
                status, response_body = _response(
                    *transport.post_inference(body, timeout))
                return type("Response", (), {"status": status, "body": response_body})()
            return [sender for _ in range(concurrency)]

        def validate_response(body: bytes) -> str:
            digest = _canonical_sha256(body)
            if digest != ORACLE_SHA256:
                raise ExperimentError("oracle mismatch")
            return digest

        profile_result = (
            gpu_profile.run_gpu_profile(
                sender_factory, validate_response, store.append_burst,
                run_id=run_id, owner_pid=readiness["owner_pid"],
                deadline_seconds=MATRIX_DEADLINE_SECONDS,
                safety_check=safe_between_bursts, clock=clock,
                workers=workers)
            if safe_between_bursts()
            else gpu_profile._build_profile_result(
                run_id, readiness["owner_pid"], [], "safety_stop",
                matrix_started, clock, MATRIX_DEADLINE_SECONDS,
                workers=workers)
        )
        matrix_ended = clock()
        matrix_ended_utc = time.time()
        final_logs_error: str | None = None
        lower = max(0.0, matrix_started_utc - LOG_OVERLAP_SECONDS)
        upper = matrix_ended_utc + LOG_OVERLAP_SECONDS
        try:
            final_reader = _LogReader(
                transport, pod, clock,
                matrix_ended + log_finalization_seconds)
            for pass_index in range(LOG_FINALIZATION_PASSES):
                rows = final_reader.range(lower, upper)
                inspect_logs(rows, int(time.time() * 1000))
                if pass_index + 1 >= LOG_FINALIZATION_PASSES:
                    break
                remaining = matrix_ended + log_finalization_seconds - clock()
                if remaining <= 0:
                    break
                pause(min(LOG_SETTLE_SECONDS, remaining))
        except Exception:
            final_logs_error = "gpu_log_collection_failed"
        ordered_gpu = [gpu_samples[key] for key in sorted(gpu_samples)]
        base_records = list(base_samples.values())
        correlation = gpu_profile.correlate_gpu_profile(
            profile_result, ordered_gpu, expected_run_id=run_id,
            expected_owner_pid=readiness["owner_pid"],
            expected_workers=workers)
        try:
            store.write_jsonl("base-samples.jsonl", base_records)
        except Exception:
            final_logs_error = final_logs_error or "artifact_persist_failed"
        try:
            store.write_jsonl("gpu-samples.jsonl", ordered_gpu)
            store.write_json("gpu-correlation.json", correlation)
        except Exception:
            final_logs_error = final_logs_error or "artifact_persist_failed"
        summaries = _summarize_profile(profile_result)
        gpu_evidence = _gpu_evidence(correlation)
        expected_successes = gpu_profile.PLANNED_REQUESTS
        matrix_complete = (
            profile_result["stop_reason"] is None
            and profile_result["completed_bursts"] == gpu_profile.PLANNED_BURSTS
            and profile_result["success_count"] == expected_successes
        )
        stop_reason = final_logs_error or safety_failure or profile_result["stop_reason"]
        if stop_reason is None and not matrix_complete:
            stop_reason = "matrix_incomplete"
        elif stop_reason is None and not gpu_evidence["sufficient"]:
            stop_reason = "gpu_evidence_insufficient"
        evidence = {
            "run_id": run_id,
            "batch_size": batch_size,
            "workers": workers,
            "log_finalization_seconds": log_finalization_seconds,
            "owner_pid": readiness["owner_pid"],
            "image_verified": True,
            "resource_guard": _summarize_resource_guards(resource_checks),
            "warmup_excluded": True,
            "warmup_status": 200,
            "matrix_complete": matrix_complete,
            "stop_reason": stop_reason,
            "profile_stop_reason": profile_result["stop_reason"],
            "safety_failure": safety_failure,
            "completed_bursts": profile_result["completed_bursts"],
            "completed_groups": profile_result["completed_groups"],
            "attempts": profile_result["attempts"],
            "success_count": profile_result["success_count"],
            "cases": summaries,
            "gpu_sample_count": len(ordered_gpu),
            "gpu_evidence_sufficient": gpu_evidence["sufficient"],
            "gpu_evidence": gpu_evidence,
            "base_sample_count": len(base_records),
            "correlation_file": "gpu-correlation.json",
            "gpu_samples_file": "gpu-samples.jsonl",
            "base_samples_file": "base-samples.jsonl",
            "burst_file": "bursts.jsonl",
        }
        store.write_json("result.json", evidence)
        return {
            **evidence,
            "readiness": readiness,
            "profile": profile_result,
            "gpu_samples": ordered_gpu,
            "correlation": correlation,
        }
    finally:
        store.close()
