from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tools.verda_model_experiment import batch_experiment, batch_package
from tools.verda_model_experiment import batch_runtime, gpu_monitor, gpu_profile, runtime
from tools.verda_model_experiment.fixture import FIXTURE_BODY

POD = "envai-pii-test-pod-new"
RUN_ID = "verda-batch-experiment-test"
IMAGE = batch_experiment.EXPECTED_IMAGE
PIDS = tuple(range(810, 818))
RESPONSE_BODY = b'{"result":"synthetic"}'
RESPONSE_DIGEST = hashlib.sha256(RESPONSE_BODY).hexdigest()


def profile_for(batch_size=4, workers=8):
    return batch_package.build_batch_gpu_profile(
        RUN_ID, batch_size, workers=workers)


def utc_text(epoch=None):
    value = datetime.fromtimestamp(time.time() if epoch is None else epoch, timezone.utc)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def event_line(prefix, payload):
    return prefix + json.dumps(payload, sort_keys=True, separators=(",", ":"))


def provider_row(prefix, payload, *, timestamp=None, pod=POD):
    return {
        "timestamp": utc_text(timestamp),
        "container_name": "envai-pii-container",
        "replica": pod,
        "message": event_line(prefix, payload),
    }


def base_event(run_id, pid, event="ready", *, timestamp=None,
               workers=8, **changes):
    payload = {
        "run_id": run_id,
        "event": event,
        "pid": pid,
        "workers": workers,
        "source_app_ok": True,
        "source_config_ok": True,
        "source_execution_ok": True,
        "source_service_ok": True,
        "settings_ok": True,
        "auth_upstream": True,
        "analysis_timeout_seconds": 60,
        "max_concurrent_analyses": 16,
        "max_queued_analyses": 32,
        "queue_timeout_seconds": 30,
        "gunicorn_threads": runtime.EXPECTED_THREADS,
        "gpu_l40s": True,
        "gpu_device_count": 1,
        "gpu_reason": None,
        "cuda_allocated_bytes": 100,
        "cuda_allocated_reason": None,
        "cuda_free_bytes": 200,
        "cuda_free_reason": None,
        "cuda_total_bytes": 1000,
        "cuda_total_reason": None,
        "torch_max_allocated_bytes": 150,
        "torch_max_allocated_reason": None,
        "cgroup_memory_current_bytes": 800,
        "cgroup_memory_current_reason": None,
        "cgroup_memory_peak_bytes": 900,
        "cgroup_memory_peak_reason": None,
        "cgroup_memory_limit_bytes": 1000,
        "cgroup_memory_limit_reason": None,
        "cgroup_pids_current": 100,
        "cgroup_pids_current_reason": None,
        "cgroup_pids_limit": None,
        "cgroup_pids_limit_reason": "limit_unavailable",
        "cpu_quota_us": 100000,
        "cpu_quota_reason": None,
        "cpu_period_us": 100000,
        "cpu_period_reason": None,
        "cpu_affinity_count": 8,
        "cpu_affinity_reason": None,
    }
    payload.update({
        "parameter_bytes": 1_230_259_380,
        "buffer_bytes": 512,
        "model_dtypes": "float32",
        "model_metrics_reason": None,
    })
    if event == "sample":
        payload["request_count"] = 0
    payload.update(changes)
    return provider_row("VERDAEXPERIMENT ", payload, timestamp=timestamp)


def batch_event(profile, pid, *, timestamp=None, **changes):
    batch_size = profile["batch_size"]
    overlay = profile["overrides"]["batch_overlay"]
    payload = {
        "event": "ready",
        "run_id": profile["run_id"],
        "pid": pid,
        "workers": profile["workers"],
        "batch_size": batch_size,
        **{key: overlay[key] for key in batch_experiment._OVERLAY_HASH_FIELDS},
        "installed_code_ok": True,
        "installed_defaults_ok": True,
        "globals_ok": True,
        "legacy_ok": True,
        "binder_ok": True,
        "base_app_ok": True,
        "overlay_ok": True,
        "warm_calls": (63 + batch_size - 1) // batch_size,
        "warm_max_batch": batch_size,
        "warm_sum_batches": 63,
        "fixture_chunks": 63,
        "warm_ok": True,
    }
    payload.update(changes)
    return provider_row(batch_runtime.EVENT_PREFIX, payload, timestamp=timestamp)


def ready_logs(profile, *, pids=None, base_changes=None, batch_changes=None):
    if pids is None:
        pids = tuple(range(PIDS[0], PIDS[0] + profile["workers"]))
    now = time.time()
    rows = []
    base_changes = base_changes or {}
    batch_changes = batch_changes or {}
    for pid in pids:
        rows.append(base_event(
            profile["run_id"], pid, timestamp=now - 2,
            workers=profile["workers"], **base_changes))
    for pid in pids:
        rows.append(batch_event(profile, pid, timestamp=now - 1, **batch_changes))
    return rows


def payload_at(row, prefix):
    line = row["message"]
    if not line.startswith(prefix):
        return None
    return json.loads(line[len(prefix):])


def replace_payload(row, prefix, **changes):
    changed = copy.deepcopy(row)
    payload = payload_at(changed, prefix)
    payload.update(changes)
    changed["message"] = event_line(prefix, payload)
    return changed


def gpu_sample_row(run_id, owner_pid, *, timestamp=None, sample_ms=None,
                   workers=8, pod=POD, **changes):
    provider_seconds = time.time() if timestamp is None else timestamp
    provider_ms = int(provider_seconds * 1000)
    sample_ms = provider_ms - 500 if sample_ms is None else sample_ms
    monotonic_ms = 1000 + sample_ms - 1_700_000_000_000
    payload = {
        "run_id": run_id,
        "owner_pid": owner_pid,
        "workers": workers,
        "epoch_ms": sample_ms,
        "monotonic_ms": monotonic_ms,
        "read_duration_ms": 1000,
        "gpu_activity_percent": 50,
        "memory_controller_activity_percent": 40,
        "power_milliwatts": 150_000,
        "power_limit_milliwatts": 300_000,
        "gpu_activity_reason": None,
        "memory_controller_activity_reason": None,
        "power_reason": None,
        "power_limit_reason": None,
    }
    payload.update(changes)
    return provider_row(
        gpu_monitor.PROFILE_PREFIX, payload,
        timestamp=provider_seconds, pod=pod)


class RuntimeStop:
    def __init__(self):
        self.calls = 0

    def wait(self, timeout):
        self.calls += 1
        return self.calls > 1


class RuntimeTorch:
    class cuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 1

        @staticmethod
        def get_device_name(index):
            return "NVIDIA L40S"

        @staticmethod
        def memory_allocated(index):
            return 100

        @staticmethod
        def mem_get_info(index):
            return 200, 1000

        @staticmethod
        def max_memory_allocated(index):
            return 150


class FakeTransport:
    def __init__(self, pids=PIDS, *, workers=8, response_body=RESPONSE_BODY,
                 warmup_body=None, fail_measured_at=None,
                 telemetry_factory=None):
        self.pids = pids
        self.workers = workers
        self.response_body = response_body
        self.warmup_body = warmup_body
        self.fail_measured_at = fail_measured_at
        self.telemetry_factory = telemetry_factory
        self.posts = []
        self.log_queries = []
        self.final_queries = []

    def post_inference(self, body, timeout):
        self.posts.append((body, timeout))
        time.sleep(0.002)
        if len(self.posts) == 1 and self.warmup_body is not None:
            return 200, self.warmup_body
        measured_count = len(self.posts) - 1
        if measured_count == self.fail_measured_at:
            return 503, b"unavailable"
        return 200, self.response_body

    def get_logs(self, *, start, end, pod, limit=1000, order="asc"):
        self.log_queries.append((start, end, pod, limit, order))
        if len(self.posts) == gpu_profile.PLANNED_REQUESTS + 1:
            self.final_queries.append((start, end))
        if pod != POD or limit != 1000 or order != "asc" or end - start > 55.0001:
            raise AssertionError("log query contract mismatch")
        if self.telemetry_factory is not None:
            return self.telemetry_factory(start, end)
        now = time.time()
        rows = [base_event(
            RUN_ID, pid, "sample", timestamp=now, workers=self.workers)
                for pid in self.pids]
        latest_ms = int(now * 1000)
        earliest_ms = max(int(start * 1000), latest_ms - 250)
        earliest_ms -= earliest_ms % 5
        rows.extend(
            gpu_sample_row(RUN_ID, min(self.pids), timestamp=now,
                           sample_ms=sample_ms, workers=self.workers)
            for sample_ms in range(earliest_ms, latest_ms + 1, 5))
        return rows


def run_matrix_in_temp(profile, transport, ready=None, *, safety_check=None,
                       clock=time.perf_counter, pause=time.sleep,
                       log_finalization_seconds=30.0):
    temporary = tempfile.TemporaryDirectory()
    directory = Path(temporary.name) / "evidence"
    result = batch_experiment.run_matrix(
        transport, profile, POD,
        ready_logs(profile) if ready is None else ready,
        directory,
        expected_image=IMAGE,
        observed_image=IMAGE,
        safety_check=safety_check,
        clock=clock,
        pause=pause,
        log_finalization_seconds=log_finalization_seconds,
    )
    return temporary, directory, result


class ReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = profile_for(4)

    def test_gate_accepts_only_batches_four_eight_and_sixteen_with_exact_warm_counts(self):
        for batch_size in (4, 8, 16):
            profile = profile_for(batch_size)
            evidence = batch_experiment.readiness_gate(
                ready_logs(profile), profile=profile, pod=POD,
                expected_image=IMAGE, observed_image=IMAGE)
            expected_calls = (63 + batch_size - 1) // batch_size
            self.assertEqual(evidence["batch_size"], batch_size)
            self.assertTrue(all(
                item["warm_calls"] == expected_calls
                and item["warm_sum_batches"] == 63
                for item in evidence["batch_ready_by_pid"].values()))
        with self.assertRaises(batch_experiment.ExperimentError):
            batch_experiment._profile_expectations(profile_for(1))

    def test_gate_requires_eight_matching_workers_and_uses_lowest_owner(self):
        evidence = batch_experiment.readiness_gate(
            ready_logs(self.profile), profile=self.profile, pod=POD,
            expected_image=IMAGE, observed_image=IMAGE)
        self.assertEqual(evidence["pids"], PIDS)
        self.assertEqual(evidence["owner_pid"], min(PIDS))
        self.assertEqual(evidence["batch_size"], 4)
        self.assertTrue(evidence["source_verified"])
        self.assertTrue(evidence["settings_verified"])
        self.assertTrue(evidence["image_verified"])
        self.assertEqual(evidence["resource_guard"][0]["pids_experiment_budget"], 512)
        self.assertEqual(evidence["resource_guard"][0]["pids_guard"], 409)
        self.assertEqual(evidence["resource_guard"][0]["pids_limit_state"], "unbounded")
        self.assertEqual(
            evidence["resource_guard"][0]["pids_limit_reason"],
            "limit_unavailable")

    def test_gate_scales_readiness_to_exact_worker_count_and_rejects_worker_mismatch(self):
        for workers in (8, 12, 16):
            with self.subTest(workers=workers):
                profile = profile_for(8, workers)
                pids = tuple(range(810, 810 + workers))
                logs = ready_logs(profile, pids=pids)
                evidence = batch_experiment.readiness_gate(
                    logs, profile=profile, pod=POD,
                    expected_image=IMAGE, observed_image=IMAGE,
                    expected_workers=workers)
                self.assertEqual(evidence["workers"], workers)
                self.assertEqual(evidence["pids"], pids)
                self.assertEqual(evidence["owner_pid"], min(pids))
                self.assertEqual(len(evidence["base_ready_by_pid"]), workers)
                self.assertEqual(len(evidence["batch_ready_by_pid"]), workers)
                for invalid_workers in (True, 8.0, 4):
                    with self.subTest(invalid_expected_workers=invalid_workers):
                        with self.assertRaises(batch_experiment.ExperimentError):
                            batch_experiment.readiness_gate(
                                logs, profile=profile, pod=POD,
                                expected_image=IMAGE, observed_image=IMAGE,
                                expected_workers=invalid_workers)
                with self.assertRaises(batch_experiment.ExperimentError):
                    batch_experiment.readiness_gate(
                        logs[:-1], profile=profile, pod=POD,
                        expected_image=IMAGE, observed_image=IMAGE)
                with self.assertRaises(batch_experiment.ExperimentError):
                    batch_experiment.readiness_gate(
                        logs, profile=profile, pod=POD,
                        expected_image=IMAGE, observed_image=IMAGE,
                        expected_workers=8 if workers != 8 else 12)
                mismatched = replace_payload(
                    logs[0], "VERDAEXPERIMENT ", workers=8 if workers != 8 else 12)
                with self.assertRaisesRegex(
                        batch_experiment.ExperimentError,
                        "base event identity mismatch"):
                    batch_experiment.readiness_gate(
                        [mismatched, *logs[1:]], profile=profile, pod=POD,
                        expected_image=IMAGE, observed_image=IMAGE,
                        expected_workers=workers)

    def test_gate_rejects_cardinality_pid_churn_flags_hashes_image_and_schema(self):
        original = ready_logs(self.profile)
        wrong_pid = copy.deepcopy(original)
        wrong_payload = payload_at(wrong_pid[-1], batch_runtime.EVENT_PREFIX)
        wrong_pid[-1] = replace_payload(
            wrong_pid[-1], batch_runtime.EVENT_PREFIX, pid=9999)
        cases = (
            (original[:-1], IMAGE, IMAGE),
            (wrong_pid, IMAGE, IMAGE),
            ([replace_payload(original[0], "VERDAEXPERIMENT ", settings_ok=False),
              *original[1:]], IMAGE, IMAGE),
            ([*original[:-1], replace_payload(
                original[-1], batch_runtime.EVENT_PREFIX,
                manifest_sha256="0" * 64)], IMAGE, IMAGE),
            ([*original[:-1], replace_payload(
                original[-1], batch_runtime.EVENT_PREFIX,
                warm_calls=15)], IMAGE, IMAGE),
            (original, IMAGE, "ghcr.io/wrong@sha256:" + "b" * 64),
            (original, "ghcr.io/wrong@sha256:" + "b" * 64,
             "ghcr.io/wrong@sha256:" + "b" * 64),
            ([*original, provider_row(
                "VERDAEXPERIMENT ", {"run_id": RUN_ID, "event": "unknown"})],
             IMAGE, IMAGE),
        )
        for logs, expected, observed in cases:
            with self.subTest(log_count=len(logs), observed=observed):
                with self.assertRaises(batch_experiment.ExperimentError):
                    batch_experiment.readiness_gate(
                        logs, profile=self.profile, pod=POD,
                        expected_image=expected, observed_image=observed)
        self.assertEqual(wrong_payload["pid"], PIDS[-1])

    def test_gate_rejects_unknown_worker_and_invalid_steady_resource_values(self):
        extra_sample = base_event(self.profile["run_id"], 9999, "sample")
        with self.assertRaisesRegex(batch_experiment.ExperimentError, "unknown worker PID"):
            batch_experiment.readiness_gate(
                [*ready_logs(self.profile), extra_sample], profile=self.profile,
                pod=POD, expected_image=IMAGE, observed_image=IMAGE)
        for changes, reason in (
            ({"cgroup_memory_current_bytes": 801}, "memory_headroom_insufficient"),
            ({"cuda_free_bytes": 199}, "GPU_headroom_insufficient"),
            ({"cgroup_pids_current": 410}, "pid_headroom_insufficient"),
            ({"cgroup_pids_limit_reason": "cgroup_file_missing"}, "pids_limit_unknown"),
        ):
            logs = ready_logs(self.profile, base_changes=changes)
            with self.subTest(reason=reason), self.assertRaisesRegex(
                    batch_experiment.ExperimentError, reason):
                batch_experiment.readiness_gate(
                    logs, profile=self.profile, pod=POD,
                    expected_image=IMAGE, observed_image=IMAGE)

    def test_gate_accepts_runtime_sample_schema_and_rejects_missing_model_metrics(self):
        with tempfile.TemporaryDirectory() as temporary:
            cgroup = Path(temporary)
            (cgroup / "memory.current").write_text("800\n")
            (cgroup / "memory.max").write_text("1000\n")
            (cgroup / "pids.current").write_text("100\n")
            (cgroup / "pids.max").write_text("max\n")
            (cgroup / "cpu.max").write_text("100000 100000\n")
            original_metrics = runtime._resource_metrics

            def fixture_metrics(torch_module=None, cgroup_root=None,
                                affinity=os.sched_getaffinity):
                return original_metrics(torch_module, cgroup, affinity)

            def fake_event_metrics(torch_module, nlp=None):
                values = runtime._resource_metrics(torch_module)
                values.update({
                    "parameter_bytes": 1_230_259_380,
                    "buffer_bytes": 512,
                    "model_dtypes": "float32",
                    "model_metrics_reason": None,
                })
                return values

            emitted = []

            def fake_emit(event, run_id, pid, workers, **fields):
                emitted.append({
                    "run_id": run_id, "event": event, "pid": pid,
                    "workers": workers, **fields,
                })

            torch_module = RuntimeTorch()
            with mock.patch.object(runtime, "_resource_metrics", fixture_metrics), \
                    mock.patch.object(runtime, "_event_metrics", fake_event_metrics), \
                    mock.patch.object(
                        runtime, "verify_sources",
                        lambda root=None: dict.fromkeys(runtime.SOURCE_HASHES, True)), \
                    mock.patch.object(runtime, "_resolved_settings", lambda: True), \
                    mock.patch.object(runtime, "_ACTIVE_THREADS",
                                      runtime.EXPECTED_THREADS), \
                    mock.patch.object(
                        runtime, "_worker_module",
                        lambda worker: mock.Mock(nlp=object())), \
                    mock.patch.object(runtime, "emit_event", fake_emit), \
                    mock.patch.dict(os.environ, {"PII_AUTH_MODE": "upstream"}):
                runtime._telemetry_loop(
                    RuntimeStop(), object(), RUN_ID, 8, torch_module)
                ready_fields = runtime._ready_event_fields(
                    dict.fromkeys(runtime.SOURCE_HASHES, True), True,
                    (True, 1, True, None), object(), torch_module)
        self.assertEqual(len(emitted), 1)
        sample = emitted[0]
        self.assertEqual(sample["event"], "sample")
        self.assertEqual(set(sample), batch_experiment._BASE_SAMPLE_FIELDS)
        self.assertEqual(batch_experiment._BASE_SAMPLE_FIELDS,
                         batch_experiment._BASE_READY_FIELDS | {"request_count"})
        self.assertEqual({"run_id", "event", "pid", "workers", *ready_fields},
                         batch_experiment._BASE_READY_FIELDS)
        batch_experiment._validate_base_event(sample, event="sample", run_id=RUN_ID)
        logs = [*ready_logs(self.profile), provider_row(
            "VERDAEXPERIMENT ", dict(sample, pid=PIDS[0]),
            timestamp=time.time())]
        evidence = batch_experiment.readiness_gate(
            logs, profile=self.profile, pod=POD,
            expected_image=IMAGE, observed_image=IMAGE)
        self.assertEqual(evidence["pids"], PIDS)
        for field in ("parameter_bytes", "buffer_bytes", "model_dtypes",
                      "model_metrics_reason", "request_count"):
            incomplete = {key: value for key, value in sample.items()
                          if key != field}
            with self.subTest(missing=field), self.assertRaisesRegex(
                    batch_experiment.ExperimentError,
                    "base event schema mismatch"):
                batch_experiment._validate_base_event(
                    incomplete, event="sample", run_id=RUN_ID)
        for changes in (
            {"request_count": "0"},
            {"request_count": True},
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(
                    batch_experiment.ExperimentError,
                    "base sample request count invalid"):
                batch_experiment._validate_base_event(
                    dict(sample, **changes), event="sample", run_id=RUN_ID)
        for changes in (
            {"parameter_bytes": None,
             "model_metrics_reason": "model_metrics_unavailable"},
            {"parameter_bytes": 1},
            {"buffer_bytes": 513},
            {"model_dtypes": "float64"},
            {"model_metrics_reason": "model_metrics_unavailable"},
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(
                    batch_experiment.ExperimentError, "model metrics mismatch"):
                batch_experiment._validate_base_event(
                    dict(sample, **changes), event="sample", run_id=RUN_ID)

    def test_null_pids_limit_is_unbounded_only_for_limit_unavailable(self):
        logs = ready_logs(self.profile, base_changes={"cgroup_pids_current": 0})
        evidence = batch_experiment.readiness_gate(
            logs, profile=self.profile, pod=POD,
            expected_image=IMAGE, observed_image=IMAGE)
        self.assertEqual(evidence["resource_guard"][0]["pids_current"], 0)
        for bad_limit in (0, -1):
            logs = ready_logs(self.profile, base_changes={
                "cgroup_pids_limit": bad_limit,
                "cgroup_pids_limit_reason": None,
            })
            with self.subTest(bad_limit=bad_limit), self.assertRaises(
                    batch_experiment.ExperimentError):
                batch_experiment.readiness_gate(
                    logs, profile=self.profile, pod=POD,
                    expected_image=IMAGE, observed_image=IMAGE)


class GpuParserTests(unittest.TestCase):
    def test_numeric_gpu_parser_separates_provider_provenance(self):
        row = gpu_sample_row(RUN_ID, min(PIDS))
        parsed = batch_experiment.parse_gpu_samples(
            [row], pod=POD, run_id=RUN_ID, owner_pid=min(PIDS))
        self.assertEqual(len(parsed), 1)
        row_twelve = gpu_sample_row(RUN_ID, min(PIDS), workers=12)
        self.assertEqual(len(batch_experiment.parse_gpu_samples(
            [row_twelve], pod=POD, run_id=RUN_ID,
            owner_pid=min(PIDS), expected_workers=12)), 1)
        with self.assertRaisesRegex(
                batch_experiment.ExperimentError, "GPU sample identity mismatch"):
            batch_experiment.parse_gpu_samples(
                [row_twelve], pod=POD, run_id=RUN_ID,
                owner_pid=min(PIDS), expected_workers=8)
        self.assertEqual(set(parsed[0]), gpu_monitor.PROFILE_FIELDS)
        self.assertNotIn("_timestamp", parsed[0])
        self.assertNotIn("_replica", parsed[0])
        for workers in (True, 12.0, 4):
            with self.subTest(expected_workers=workers), self.assertRaises(
                    batch_experiment.ExperimentError):
                batch_experiment.parse_gpu_samples(
                    [], pod=POD, run_id=RUN_ID, owner_pid=min(PIDS),
                    expected_workers=workers)
        for bad_row, bad_pod, owner, run_id in (
            (row, "other-pod", min(PIDS), RUN_ID),
            (gpu_sample_row(RUN_ID, 999), POD, min(PIDS), RUN_ID),
            (gpu_sample_row("old-run", min(PIDS)), POD, min(PIDS), RUN_ID),
            (gpu_sample_row(RUN_ID, min(PIDS), epoch_ms=True), POD, min(PIDS), RUN_ID),
            ({**row, "timestamp": "not-a-time"}, POD, min(PIDS), RUN_ID),
        ):
            with self.subTest(bad_pod=bad_pod, owner=owner, run_id=run_id):
                with self.assertRaises(batch_experiment.ExperimentError):
                    batch_experiment.parse_gpu_samples(
                        [bad_row], pod=bad_pod, run_id=run_id, owner_pid=owner)


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = profile_for(4)

    def test_provider_envelope_accepts_real_fields_and_compatible_aliases(self):
        payload = {"run_id": RUN_ID, "event": "sample"}
        real = provider_row("VERDAEXPERIMENT ", payload)
        alias = {
            "_timestamp": real["timestamp"],
            "_replica": real["replica"],
            "log": real["message"],
        }
        mixed = {
            "timestamp": real["timestamp"],
            "_timestamp": real["timestamp"],
            "replica": real["replica"],
            "_replica": real["replica"],
            "text": real["message"],
        }
        for row in (real, alias, mixed):
            with self.subTest(row=row):
                events = list(batch_experiment._provider_events([row], POD))
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0][2], real["message"])
        for row in (
            {**real, "_timestamp": "2000-01-01T00:00:00Z"},
            {**real, "_replica": "other-pod"},
            {"message": real["message"]},
            {"timestamp": real["timestamp"], "message": real["message"]},
            {"replica": real["replica"], "message": real["message"]},
        ):
            with self.subTest(row=row), self.assertRaises(
                    batch_experiment.ExperimentError):
                list(batch_experiment._provider_events([row], POD))

    def test_worker_count_validators_reject_boolean_float_and_unknown_counts(self):
        base = payload_at(base_event(RUN_ID, PIDS[0]), "VERDAEXPERIMENT ")
        batch_profile = profile_for(8)
        batch = payload_at(batch_event(batch_profile, PIDS[0]), batch_runtime.EVENT_PREFIX)
        for workers in (True, 8.0, 4, 32):
            with self.subTest(expected_workers=workers):
                with self.assertRaises(batch_experiment.ExperimentError):
                    batch_experiment._validate_base_event(
                        base, event="ready", run_id=RUN_ID,
                        expected_workers=workers)
                with self.assertRaises(batch_experiment.ExperimentError):
                    batch_experiment._validate_batch_event(
                        batch, run_id=RUN_ID, batch_size=8,
                        expected_hashes={
                            key: batch_profile["overrides"]["batch_overlay"][key]
                            for key in batch_experiment._OVERLAY_HASH_FIELDS
                        },
                        expected_workers=workers)
                with self.assertRaises(batch_experiment.ExperimentError):
                    batch_experiment.parse_gpu_samples(
                        [], pod=POD, run_id=RUN_ID, owner_pid=PIDS[0],
                        expected_workers=workers)

    def test_gpu_evidence_requires_ten_active_per_case_and_zero_anomalies(self):
        def correlation():
            counts = {
                field: 0 for field in batch_experiment._CORRELATION_ANOMALY_FIELDS
            }
            return {
                "sample_counts": counts,
                "identity": {"consistent": True},
                "cases": [
                    {"case_index": index, "active_sample_count": 10}
                    for index in range(1, 7)
                ],
                "overall": {"gpu_quantitative_reason": None},
            }

        self.assertTrue(batch_experiment._gpu_evidence(correlation())["sufficient"])
        for mutate, reason in (
            (lambda value: value["sample_counts"].update(duplicate=1),
             "gpu_correlation_anomaly"),
            (lambda value: value["identity"].update(consistent=False),
             "gpu_correlation_anomaly"),
            (lambda value: value["cases"][2].update(active_sample_count=9),
             "gpu_case_samples_insufficient"),
            (lambda value: value["overall"].update(
                gpu_quantitative_reason="insufficient_active_samples"),
             "gpu_quantitative_insufficient"),
        ):
            value = correlation()
            mutate(value)
            with self.subTest(reason=reason):
                evidence = batch_experiment._gpu_evidence(value)
                self.assertFalse(evidence["sufficient"])
                self.assertEqual(evidence["reason"], reason)
        value = correlation()
        value["cases"][2]["active_sample_count"] = 9
        evidence = batch_experiment._gpu_evidence(value)
        self.assertEqual(evidence["insufficient_cases"], [3])
        self.assertEqual(evidence["minimum_case_active_samples"], 9)
        self.assertEqual(evidence["required_case_active_samples"], 10)

    def test_profile_log_envelope_and_event_json_reject_unknown_shapes(self):
        for mutate in (
            lambda item: item.update(batch_size=1),
            lambda item: item.update(source_hashes={}),
            lambda item: item.update(workers=8.0),
            lambda item: item["overrides"].update(workers=True),
            lambda item: item["overrides"].update(batch_size=8),
            lambda item: item["overrides"]["batch_overlay"].update(
                manifest_sha256="bad"),
        ):
            profile = copy.deepcopy(self.profile)
            mutate(profile)
            with self.subTest(profile=profile.get("batch_size")), self.assertRaises(
                    batch_experiment.ExperimentError):
                batch_experiment._profile_expectations(profile)
        with self.assertRaises(batch_experiment.ExperimentError):
            list(batch_experiment._provider_events(None, POD))
        for logs in ([None], [{"message": 12}],
                     [{"message": "unrelated", "log": "other"}],
                     [{"_timestamp": "bad", "_replica": POD,
                       "message": "VERDAEXPERIMENT {}"}],
                     [provider_row("VERDAEXPERIMENT ", {}, pod="other-pod")]):
            with self.subTest(logs=logs), self.assertRaises(
                    batch_experiment.ExperimentError):
                list(batch_experiment._provider_events(logs, POD))
        self.assertEqual(list(batch_experiment._provider_events(
            [{"message": "ordinary output"}], POD)), [])
        with self.assertRaisesRegex(batch_experiment.ExperimentError,
                                    "provider event prefix invalid"):
            list(batch_experiment._provider_events(
                [{"message": "VERDAEXPERIMENT"}], POD))
        for line in ("VERDAEXPERIMENT {", "VERDAEXPERIMENT []"):
            with self.subTest(line=line), self.assertRaises(
                    batch_experiment.ExperimentError):
                batch_experiment._event_payload(line, "VERDAEXPERIMENT ")

    def test_resource_guard_distinguishes_zero_from_unknown_and_enforces_limits(self):
        payload = base_event(RUN_ID, PIDS[0])
        payload = payload_at(payload, "VERDAEXPERIMENT ")
        zero = dict(payload, cgroup_pids_current=0)
        self.assertEqual(batch_experiment._resource_guard(zero)["pids_current"], 0)
        cases = (
            (dict(payload, cgroup_memory_limit_bytes=0), "memory_headroom_unknown"),
            (dict(payload, cgroup_memory_current_bytes=1001), "memory_headroom_unknown"),
            (dict(payload, cuda_free_bytes=None), "GPU_headroom_unknown"),
            (dict(payload, cuda_free_bytes=1001), "GPU_headroom_unknown"),
            (dict(payload, cgroup_pids_current=None), "pid_headroom_unknown"),
            (dict(payload, cgroup_pids_limit=None,
                  cgroup_pids_limit_reason="cgroup_file_missing"), "pids_limit_unknown"),
            (dict(payload, cgroup_pids_limit=0,
                  cgroup_pids_limit_reason=None), "pids_limit_invalid"),
            (dict(payload, cgroup_pids_limit=80,
                  cgroup_pids_limit_reason=None), "pid_headroom_insufficient"),
        )
        for item, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(
                    batch_experiment.ExperimentError, reason):
                batch_experiment._resource_guard(item)

    def test_duplicate_and_conflicting_gpu_samples_are_handled_closed(self):
        row = gpu_sample_row(RUN_ID, min(PIDS))
        parsed = batch_experiment.parse_gpu_samples(
            [row, copy.deepcopy(row)], pod=POD, run_id=RUN_ID,
            owner_pid=min(PIDS))
        self.assertEqual(len(parsed), 1)
        conflicting = copy.deepcopy(row)
        payload = payload_at(conflicting, gpu_monitor.PROFILE_PREFIX)
        payload["gpu_activity_percent"] = 60
        conflicting["message"] = event_line(gpu_monitor.PROFILE_PREFIX, payload)
        with self.assertRaisesRegex(batch_experiment.ExperimentError,
                                    "conflicting duplicate"):
            batch_experiment.parse_gpu_samples(
                [row, conflicting], pod=POD, run_id=RUN_ID,
                owner_pid=min(PIDS))
        for value in ("not-json", 4, [], b'{"value":NaN}', b'{"key":1,"key":2}'):
            raw = value if isinstance(value, bytes) else json.dumps(value).encode()
            with self.subTest(value=value), self.assertRaises(
                    batch_experiment.ExperimentError):
                batch_experiment._canonical_sha256(raw)
        self.assertEqual(batch_experiment._response(200, b"ok"), (200, b"ok"))
        for response in ((True, b"ok"), (200, "body")):
            with self.assertRaises(batch_experiment.ExperimentError):
                batch_experiment._response(*response)
        self.assertTrue(batch_experiment._invoke_safety(None))
        self.assertFalse(batch_experiment._invoke_safety(lambda: False))
        self.assertFalse(batch_experiment._invoke_safety(
            lambda: (_ for _ in ()).throw(RuntimeError())))

    def test_log_reader_overlaps_splits_capped_pages_and_has_bounds(self):
        class Logs:
            def __init__(self):
                self.calls = []

            def get_logs(self, **query):
                self.calls.append(query)
                return []

        logs = Logs()
        reader = batch_experiment._LogReader(logs, POD, lambda: 1.0, 10.0)
        reader.range(100.0, 200.0)
        self.assertEqual(len(logs.calls), 2)
        self.assertEqual(logs.calls[1]["start"], 150.0)
        self.assertTrue(all(call["end"] - call["start"] <= 55
                            for call in logs.calls))

        class CappedLogs:
            def __init__(self):
                self.calls = 0

            def get_logs(self, **query):
                self.calls += 1
                return [None] * 1000 if self.calls == 1 else []

        capped = CappedLogs()
        reader = batch_experiment._LogReader(capped, POD, lambda: 1.0, 10.0)
        self.assertEqual(reader.range(1.0, 2.0), [])
        self.assertEqual(capped.calls, 3)
        with self.assertRaisesRegex(batch_experiment.ExperimentError,
                                    "provider log page invalid"):
            batch_experiment._LogReader(
                type("BadLogs", (), {"get_logs": lambda self, **query: {}})(),
                POD, lambda: 1.0, 10.0).range(1.0, 2.0)
        with self.assertRaisesRegex(batch_experiment.ExperimentError,
                                    "log_collection_deadline"):
            batch_experiment._LogReader(logs, POD, lambda: 10.0, 10.0).range(1.0, 2.0)

    def test_artifact_store_create_exclusive_private_files_and_partial_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "evidence"
            store = batch_experiment._ArtifactStore(directory)
            store.write_jsonl("samples.jsonl", [{"sample": 0}])
            store.write_json("summary.json", {"status": "ok"})
            store.close()
            store.close()
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((directory / "summary.json").stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                batch_experiment._ArtifactStore(directory)
        writes = []

        def partial(descriptor, data):
            piece = bytes(data[:2])
            writes.append(piece)
            return len(piece)

        with mock.patch.object(batch_experiment.os, "write", side_effect=partial):
            batch_experiment._write_all(1, b"abcdef")
        self.assertEqual(b"".join(writes), b"abcdef")
        with mock.patch.object(batch_experiment.os, "write", return_value=0):
            with self.assertRaises(OSError):
                batch_experiment._write_all(1, b"x")
        with self.assertRaises(batch_experiment.ExperimentError):
            batch_experiment._summarize_profile({"bursts": None})


class MatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = profile_for(4)

    def test_full_profile_excludes_warmup_persists_private_bursts_and_summarizes_raw_rows(self):
        transport = FakeTransport()
        safety_calls = []
        with mock.patch.object(batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
            temporary, directory, result = run_matrix_in_temp(
                self.profile, transport,
                safety_check=lambda: safety_calls.append(True) or True)
        try:
            self.assertTrue(result["matrix_complete"])
            self.assertIsNone(result["stop_reason"])
            self.assertEqual(result["completed_bursts"], 81)
            self.assertEqual(result["completed_groups"], 27)
            self.assertEqual(result["attempts"], 402)
            self.assertEqual(result["success_count"], 402)
            self.assertEqual(len(transport.posts), 403)
            self.assertTrue(all(body == FIXTURE_BODY for body, _ in transport.posts))
            self.assertTrue(all(timeout == 90.0 for _, timeout in transport.posts))
            self.assertEqual(len(safety_calls), 83)
            self.assertEqual(
                [(case["case_index"], case["client_concurrency"])
                 for case in result["cases"]],
                [(1, 1), (2, 2), (3, 4), (4, 8), (5, 16), (6, 32)],
            )
            self.assertEqual([case["groups_completed"] for case in result["cases"]],
                             [10, 6, 4, 4, 2, 1])
            for summary, plan in zip(result["cases"], gpu_profile.CASE_PLAN):
                bursts = [record["burst"] for record in result["profile"]["bursts"]
                          if record["case_index"] == plan.case_index]
                raw_durations = [
                    row["duration_seconds"]
                    for burst in bursts for row in burst["requests"]
                    if row["failure_class"] is None and row["validation_ok"]
                ]
                self.assertEqual(summary["success_count"], len(raw_durations))
                self.assertAlmostEqual(summary["mean_seconds"],
                                       sum(raw_durations) / len(raw_durations))
                self.assertEqual(summary["p95_seconds"],
                                 sorted(raw_durations)[int((0.95 * len(raw_durations) + 0.999999)) - 1])
                self.assertAlmostEqual(summary["group_elapsed_seconds_sum"],
                                       sum(burst["group_elapsed_seconds"] for burst in bursts))
                self.assertGreater(summary["requests_per_second"], 0)
            self.assertGreater(result["gpu_sample_count"], 0)
            self.assertTrue(result["gpu_evidence_sufficient"])
            self.assertIsNone(result["gpu_evidence"]["reason"])
            self.assertEqual(result["base_sample_count"], 8)
            self.assertEqual(result["resource_guard"]["pids_limit_state"], "unbounded")
            self.assertEqual(
                result["resource_guard"]["pids_limit_reason"],
                "limit_unavailable")
            self.assertGreater(len(transport.log_queries), 81)
            self.assertTrue(all(query[2:] == (POD, 1000, "asc")
                                for query in transport.log_queries))
            self.assertTrue(all(query[1] - query[0] <= 55.0001
                                for query in transport.log_queries))
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            for artifact in directory.iterdir():
                self.assertEqual(stat.S_IMODE(artifact.stat().st_mode), 0o600)
            serialized = "\n".join(path.read_text() for path in directory.iterdir())
            self.assertNotIn(POD, serialized)
            self.assertNotIn(FIXTURE_BODY.decode("utf-8"), serialized)
            self.assertNotIn("dictionary_delta", serialized)
            self.assertNotIn("_replica", serialized)
            self.assertNotIn("container_name", serialized)
            self.assertNotIn("envai-pii-container", serialized)
            self.assertNotIn("Authorization", serialized)
            self.assertNotIn("carrier", serialized.lower())
            self.assertNotIn("uuid", serialized.lower())
            self.assertTrue((directory / "gpu-correlation.json").is_file())
            self.assertTrue((directory / "base-samples.jsonl").is_file())
            self.assertTrue((directory / "warmup.json").is_file())
            warmup = json.loads((directory / "warmup.json").read_text())
            self.assertEqual(warmup["status"], 200)
            self.assertTrue(warmup["oracle_ok"])
            self.assertTrue(warmup["transport_started_at_utc"].endswith("Z"))
            self.assertTrue(warmup["transport_ended_at_utc"].endswith("Z"))
            self.assertGreaterEqual(warmup["elapsed_monotonic_seconds"], 0)
            self.assertNotIn("body", warmup)
            self.assertNotIn(RESPONSE_BODY.decode(), json.dumps(warmup))
        finally:
            temporary.cleanup()

    def test_full_matrix_preserves_402_requests_for_each_profile_worker_count(self):
        for workers in (8, 12, 16):
            with self.subTest(workers=workers):
                profile = profile_for(8, workers)
                pids = tuple(range(810, 810 + workers))
                transport = FakeTransport(pids=pids, workers=workers)
                with mock.patch.object(
                        batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
                    temporary, directory, result = run_matrix_in_temp(
                        profile, transport)
                try:
                    self.assertTrue(result["matrix_complete"])
                    self.assertEqual(result["workers"], workers)
                    self.assertEqual(result["profile"]["workers"], workers)
                    self.assertEqual(result["success_count"], 402)
                    self.assertEqual(result["attempts"], 402)
                    self.assertEqual(result["completed_bursts"], 81)
                    self.assertEqual(len(transport.posts), 403)
                    self.assertEqual(result["readiness"]["pids"], pids)
                    self.assertEqual(result["readiness"]["owner_pid"], min(pids))
                    self.assertTrue(all(
                        record["workers"] == workers
                        and record["model_count"] == workers
                        for record in result["profile"]["bursts"]))
                finally:
                    temporary.cleanup()

    def test_pre_measured_safety_requires_eight_fresh_base_and_numeric_owner_nvml(self):
        def telemetry(*, drop_pid=None, base_age=0.0, gpu_age=0.5,
                      gpu_changes=None, provider_age=None):
            def factory(start, end):
                now = min(time.time(), end)
                rows = [
                    base_event(RUN_ID, pid, "sample", timestamp=now - base_age)
                    for pid in PIDS if pid != drop_pid
                ]
                sample_ms = int((now - gpu_age) * 1000)
                rows.append(gpu_sample_row(
                    RUN_ID, min(PIDS),
                    timestamp=now if provider_age is None else now - provider_age,
                    sample_ms=sample_ms, **(gpu_changes or {})))
                return rows
            return factory

        cases = (
            (telemetry(drop_pid=PIDS[3]), "resource_sample_missing"),
            (telemetry(base_age=20.0), "resource_sample_stale"),
            (telemetry(gpu_age=0.5, gpu_changes={
                "gpu_activity_percent": None,
                "gpu_activity_reason": "utilization_unavailable",
            }), "gpu_sample_unavailable"),
            (telemetry(gpu_age=20.0, provider_age=20.0), "gpu_sample_stale"),
            (telemetry(gpu_age=-12.0, provider_age=-3.0),
             "GPU sample timestamp is in the future"),
        )
        for factory, reason in cases:
            transport = FakeTransport(telemetry_factory=factory)
            with mock.patch.object(batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
                temporary, directory, result = run_matrix_in_temp(
                    self.profile, transport)
            try:
                with self.subTest(reason=reason):
                    self.assertEqual(result["stop_reason"], reason)
                    self.assertEqual(len(transport.posts), 1)
                    self.assertEqual(result["completed_bursts"], 0)
                    self.assertEqual(result["profile_stop_reason"], "safety_stop")
            finally:
                temporary.cleanup()

    def test_base_samples_persist_only_validated_deduplicated_payloads(self):
        transport = FakeTransport()
        with mock.patch.object(batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
            temporary, directory, result = run_matrix_in_temp(self.profile, transport)
        try:
            self.assertGreater(len(transport.log_queries), 82)
            lines = (directory / "base-samples.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 8)
            self.assertEqual(len(set(lines)), len(lines))
            records = [json.loads(line) for line in lines]
            self.assertEqual({record["pid"] for record in records}, set(PIDS))
            for record in records:
                self.assertEqual(set(record), batch_experiment._BASE_SAMPLE_FIELDS)
                self.assertEqual(record["event"], "sample")
                self.assertEqual(record["run_id"], RUN_ID)
            self.assertEqual(result["base_sample_count"], len(records))
        finally:
            temporary.cleanup()

    def test_http_matrix_complete_is_distinct_from_quantitative_gpu_evidence(self):
        def delayed_owner(start, end):
            now = time.time()
            rows = [base_event(RUN_ID, pid, "sample", timestamp=now)
                    for pid in PIDS]
            rows.append(gpu_sample_row(
                RUN_ID, min(PIDS), timestamp=now,
                sample_ms=int((now - 5.0) * 1000)))
            return rows

        transport = FakeTransport(telemetry_factory=delayed_owner)
        with mock.patch.object(batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
            temporary, directory, result = run_matrix_in_temp(self.profile, transport)
        try:
            self.assertTrue(result["matrix_complete"])
            self.assertEqual(result["completed_bursts"], 81)
            self.assertFalse(result["gpu_evidence_sufficient"])
            self.assertEqual(
                result["gpu_evidence"]["reason"], "gpu_case_samples_insufficient")
            self.assertEqual(result["stop_reason"], "gpu_evidence_insufficient")
        finally:
            temporary.cleanup()

    def test_final_history_passes_are_complete_bounded_and_paused(self):
        pauses = []
        transport = FakeTransport()
        with mock.patch.object(batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
            temporary, directory, result = run_matrix_in_temp(
                self.profile, transport, pause=pauses.append)
        try:
            self.assertEqual(batch_experiment.LOG_FINALIZATION_SECONDS, 30.0)
            lower = min(start for start, _ in transport.final_queries)
            passes = [query for query in transport.final_queries
                      if query[0] == lower]
            self.assertEqual(len(passes),
                             batch_experiment.LOG_FINALIZATION_PASSES)
            self.assertEqual(len(pauses),
                             batch_experiment.LOG_FINALIZATION_PASSES - 1)
            self.assertTrue(all(
                0 < seconds <= batch_experiment.LOG_SETTLE_SECONDS
                for seconds in pauses))
            self.assertLessEqual(
                sum(pauses), batch_experiment.LOG_FINALIZATION_SECONDS)
            ends = {end for _, end in passes}
            self.assertEqual(len(ends), 1)
            self.assertGreater(next(iter(ends)) - lower, 0.0)
            self.assertIsNone(result["stop_reason"])
        finally:
            temporary.cleanup()

    def test_finalization_budget_is_positive_finite_and_bounded(self):
        profile = profile_for(8, 8)
        logs = ready_logs(profile)
        for seconds in (0, True, float("nan"), 90.001):
            with self.subTest(seconds=seconds), tempfile.TemporaryDirectory() as temporary:
                transport = FakeTransport()
                output = Path(temporary) / "evidence"
                with self.assertRaises((TypeError, ValueError)):
                    batch_experiment.run_matrix(
                        transport, profile, POD, logs, output,
                        expected_image=IMAGE, observed_image=IMAGE,
                        log_finalization_seconds=seconds)
                self.assertEqual(transport.posts, [])
                self.assertFalse(output.exists())

    def test_warmup_timing_uses_fake_monotonic_clock_and_optional_finalizer_budget(self):
        class StepClock:
            def __init__(self):
                self.value = 0.0

            def __call__(self):
                value = self.value
                self.value += 0.25
                return value

        clock = StepClock()
        deadlines = []
        original_reader = batch_experiment._LogReader

        def record_reader(transport, pod, monotonic, deadline):
            deadlines.append((deadline, monotonic.value))
            return original_reader(transport, pod, monotonic, deadline)

        transport = FakeTransport()
        with mock.patch.object(
                batch_experiment, "_LogReader", side_effect=record_reader), \
                mock.patch.object(batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
            temporary, directory, result = run_matrix_in_temp(
                profile_for(8, 8), transport, clock=clock,
                pause=lambda _seconds: None, log_finalization_seconds=90.0)
        try:
            self.assertEqual(result["log_finalization_seconds"], 90.0)
            self.assertEqual(len(deadlines), 2)
            self.assertAlmostEqual(deadlines[1][0] - deadlines[1][1], 89.75)
            warmup = json.loads((directory / "warmup.json").read_text())
            self.assertEqual(warmup["elapsed_monotonic_seconds"], 0.25)
            self.assertTrue(warmup["oracle_ok"])
            self.assertEqual(set(warmup), {
                "excluded", "status", "oracle_ok",
                "transport_started_at_utc", "transport_ended_at_utc",
                "elapsed_monotonic_seconds",
            })
            self.assertNotIn(RESPONSE_BODY.decode(), json.dumps(warmup))
        finally:
            temporary.cleanup()

    def test_final_artifact_persist_failure_keeps_remaining_evidence(self):
        transport = FakeTransport()
        original_write = batch_experiment._ArtifactStore.write_jsonl

        def fail_base_write(store, name, records):
            if name == "base-samples.jsonl":
                raise OSError("disk full")
            return original_write(store, name, records)

        with mock.patch.object(
                batch_experiment._ArtifactStore, "write_jsonl", fail_base_write), \
                mock.patch.object(batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
            temporary, directory, result = run_matrix_in_temp(self.profile, transport)
        try:
            self.assertTrue(result["matrix_complete"])
            self.assertEqual(result["stop_reason"], "artifact_persist_failed")
            self.assertTrue((directory / "gpu-correlation.json").is_file())
            self.assertFalse((directory / "base-samples.jsonl").exists())
        finally:
            temporary.cleanup()
        transport = FakeTransport()
        original_json = batch_experiment._ArtifactStore.write_json

        def fail_correlation_write(store, name, value):
            if name == "gpu-correlation.json":
                raise OSError("disk full")
            return original_json(store, name, value)

        with mock.patch.object(
                batch_experiment._ArtifactStore, "write_json",
                fail_correlation_write), mock.patch.object(
                batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
            temporary, directory, result = run_matrix_in_temp(self.profile, transport)
        try:
            self.assertEqual(result["stop_reason"], "artifact_persist_failed")
            self.assertTrue((directory / "base-samples.jsonl").is_file())
            self.assertTrue((directory / "gpu-samples.jsonl").is_file())
            self.assertFalse((directory / "gpu-correlation.json").exists())
        finally:
            temporary.cleanup()

    def test_warmup_mismatch_or_measured_oracle_failure_never_replays(self):
        transport = FakeTransport(warmup_body=b'{"wrong":true}')
        temporary, directory, result = run_matrix_in_temp(self.profile, transport)
        try:
            self.assertEqual(result["stop_reason"], "warmup_failed")
            self.assertEqual(len(transport.posts), 1)
            self.assertFalse(result["matrix_complete"])
        finally:
            temporary.cleanup()
        transport = FakeTransport(
            response_body=b'{"wrong":true}', warmup_body=RESPONSE_BODY)
        with mock.patch.object(batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
            temporary, directory, result = run_matrix_in_temp(self.profile, transport)
        try:
            self.assertEqual(result["profile_stop_reason"], "fault_oracle")
            self.assertEqual(len(transport.posts), 2)
            self.assertEqual(result["completed_bursts"], 1)
        finally:
            temporary.cleanup()

    def test_serious_http_failure_persist_failure_and_deadline_stop_before_next_burst(self):
        transport = FakeTransport(fail_measured_at=2)
        with mock.patch.object(batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
            temporary, directory, result = run_matrix_in_temp(self.profile, transport)
        try:
            self.assertEqual(result["profile_stop_reason"], "fault_5xx")
            self.assertEqual(len(transport.posts), 3)
        finally:
            temporary.cleanup()
        transport = FakeTransport()
        with mock.patch.object(
                batch_experiment._ArtifactStore, "append_burst",
                side_effect=OSError("disk failure")), mock.patch.object(
                batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
            temporary, directory, result = run_matrix_in_temp(self.profile, transport)
        try:
            self.assertEqual(result["profile_stop_reason"], "persist_failed")
            self.assertEqual(len(transport.posts), 2)
        finally:
            temporary.cleanup()
        class MutableClock:
            value = 0.0

            def __call__(self):
                return self.value

        clock = MutableClock()
        transport = FakeTransport()
        original_post = transport.post_inference

        def expire_on_first_measured(body, timeout):
            response = original_post(body, timeout)
            if len(transport.posts) == 2:
                clock.value = 701.0
            return response

        transport.post_inference = expire_on_first_measured
        with mock.patch.object(batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
            temporary, directory, result = run_matrix_in_temp(
                self.profile, transport, clock=clock)
        try:
            self.assertEqual(result["profile_stop_reason"], "deadline")
            self.assertEqual(len(transport.posts), 2)
        finally:
            temporary.cleanup()

    def test_initial_safety_check_prevents_warmup_and_callback_runs_between_bursts(self):
        transport = FakeTransport()
        calls = []
        temporary, directory, result = run_matrix_in_temp(
            self.profile, transport,
            safety_check=lambda: calls.append(True) or False)
        try:
            self.assertEqual(result["stop_reason"], "safety_stop")
            self.assertEqual(transport.posts, [])
            self.assertEqual(calls, [True])
        finally:
            temporary.cleanup()
        transport = FakeTransport()
        calls = []

        def stop_after_first_burst():
            calls.append(True)
            return len(calls) < 2

        with mock.patch.object(batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
            temporary, directory, result = run_matrix_in_temp(
                self.profile, transport, safety_check=stop_after_first_burst)
        try:
            self.assertEqual(result["profile_stop_reason"], "safety_stop")
            self.assertEqual(len(transport.posts), 1)
            self.assertEqual(len(calls), 2)
            self.assertEqual(result["safety_failure"], "operator_safety_stop")
            self.assertEqual(result["completed_bursts"], 0)
        finally:
            temporary.cleanup()

    def test_worker_churn_or_headroom_failure_stops_without_another_burst(self):
        def low_headroom(start, end):
            now = min(time.time(), end)
            rows = [base_event(
                RUN_ID, pid, "sample", timestamp=now,
                cgroup_memory_current_bytes=900)
                for pid in PIDS]
            rows.append(gpu_sample_row(RUN_ID, min(PIDS), timestamp=now))
            return rows

        transport = FakeTransport(telemetry_factory=low_headroom)
        with mock.patch.object(batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
            temporary, directory, result = run_matrix_in_temp(self.profile, transport)
        try:
            self.assertEqual(result["profile_stop_reason"], "safety_stop")
            self.assertEqual(result["safety_failure"], "memory_headroom_insufficient")
            self.assertEqual(len(transport.posts), 1)
            self.assertEqual(result["completed_bursts"], 0)
        finally:
            temporary.cleanup()
        transport = FakeTransport()
        original_get = transport.get_logs
        calls = 0

        def logs_with_churn(*, start, end, pod, limit=1000, order="asc"):
            nonlocal calls
            calls += 1
            rows = original_get(start=start, end=end, pod=pod, limit=limit, order=order)
            if calls == 1:
                rows.append(provider_row("VERDAEXPERIMENT ", {
                    "run_id": RUN_ID, "event": "exit", "pid": PIDS[0],
                    "workers": 8, "request_count": 0,
                }, timestamp=end))
            return rows

        transport.get_logs = logs_with_churn
        with mock.patch.object(batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
            temporary, directory, result = run_matrix_in_temp(self.profile, transport)
        try:
            self.assertEqual(result["profile_stop_reason"], "safety_stop")
            self.assertEqual(len(transport.posts), 1)
        finally:
            temporary.cleanup()

    def test_final_log_failure_is_reported_after_preserving_measured_evidence(self):
        transport = FakeTransport()
        original_get = transport.get_logs

        seen = set()

        def fail_final_scan(*, start, end, pod, limit=1000, order="asc"):
            window = (start, end)
            if window in seen:
                return [{
                    "timestamp": utc_text(end),
                    "container_name": "envai-pii-container",
                    "replica": pod,
                    "message": "VERDAEXPERIMENT {",
                }]
            seen.add(window)
            return original_get(
                start=start, end=end, pod=pod, limit=limit, order=order)

        transport.get_logs = fail_final_scan
        with mock.patch.object(batch_experiment, "ORACLE_SHA256", RESPONSE_DIGEST):
            temporary, directory, result = run_matrix_in_temp(self.profile, transport)
        try:
            self.assertTrue(result["matrix_complete"])
            self.assertEqual(result["stop_reason"], "gpu_log_collection_failed")
            self.assertEqual(len(transport.posts), 403)
            self.assertTrue((directory / "bursts.jsonl").is_file())
            self.assertTrue((directory / "gpu-correlation.json").is_file())
        finally:
            temporary.cleanup()

    def test_artifact_directory_is_exclusive_and_oracle_is_pinned(self):
        self.assertEqual(
            batch_experiment.ORACLE_SHA256,
            "ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "exists"
            directory.mkdir()
            with self.assertRaises(FileExistsError):
                batch_experiment._ArtifactStore(directory)


if __name__ == "__main__":
    unittest.main()
