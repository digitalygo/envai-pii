from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timezone

from tools.verda_model_experiment import (
    batch_experiment,
    batch_package,
    batch_runtime,
    startup,
)

POD = "envai-pii-test-startup"
RUN_ID = "verda-startup-unit"
REQUESTED = "2026-10-29T10:00:00.000000Z"
ACCEPTED = "2026-10-29T10:00:01.000000Z"
OBSERVED = "2026-10-29T10:00:06.000000Z"


def utc_text(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(
        timespec="microseconds").replace("+00:00", "Z")


def provider_row(prefix, payload, timestamp, *, pod=POD):
    return {
        "timestamp": timestamp,
        "replica": pod,
        "message": prefix + json.dumps(payload, sort_keys=True, separators=(",", ":")),
    }


def profile_for(workers):
    return batch_package.build_batch_gpu_profile(RUN_ID, 8, workers=workers)


def plain_log(message, timestamp, *, pod=POD):
    return {"timestamp": timestamp, "replica": pod, "message": message}


def base_ready(profile, pid, timestamp, *, workers=None, **changes):
    workers = profile["workers"] if workers is None else workers
    payload = {
        "run_id": profile["run_id"],
        "event": "ready",
        "pid": pid,
        "workers": workers,
        **batch_experiment._BASE_SETTINGS,
        **dict.fromkeys(batch_experiment._BASE_SOURCE_FIELDS, True),
        "gpu_l40s": True,
        "gpu_device_count": 1,
        "gpu_reason": None,
        "parameter_bytes": 1_230_259_380,
        "buffer_bytes": 512,
        "model_dtypes": "float32",
        "model_metrics_reason": None,
    }
    values = {
        "cuda_allocated_bytes": 100,
        "cuda_free_bytes": 200,
        "cuda_total_bytes": 1_000,
        "torch_max_allocated_bytes": 150,
        "cgroup_memory_current_bytes": 800,
        "cgroup_memory_peak_bytes": 900,
        "cgroup_memory_limit_bytes": 1_000,
        "cgroup_pids_current": 100,
        "cgroup_pids_limit": None,
        "cpu_quota_us": 100_000,
        "cpu_period_us": 100_000,
        "cpu_affinity_count": 8,
    }
    for metric, reason in batch_experiment._RESOURCE_FIELDS.items():
        payload[metric] = values[metric]
        payload[reason] = "limit_unavailable" if metric == "cgroup_pids_limit" else None
    payload.update(changes)
    return provider_row("VERDAEXPERIMENT ", payload, timestamp)


def batch_ready(profile, pid, timestamp, **changes):
    batch_size = profile["batch_size"]
    payload = {
        "event": "ready",
        "run_id": profile["run_id"],
        "pid": pid,
        "workers": profile["workers"],
        "batch_size": batch_size,
        **{key: profile["overrides"]["batch_overlay"][key]
           for key in batch_experiment._OVERLAY_HASH_FIELDS},
        **dict.fromkeys(batch_runtime.READY_BOOLEAN_FIELDS, True),
        "warm_calls": (63 + batch_size - 1) // batch_size,
        "warm_max_batch": batch_size,
        "warm_sum_batches": 63,
        "fixture_chunks": 63,
    }
    payload.update(changes)
    return provider_row(batch_runtime.EVENT_PREFIX, payload, timestamp)


def readiness_logs(profile, offset_seconds=0):
    pids = tuple(range(810, 810 + profile["workers"]))
    anchor = 1_793_268_000 + offset_seconds
    base = [
        base_ready(profile, pid, utc_text(anchor + 2 + index / 1000))
        for index, pid in enumerate(pids)
    ]
    batch = [
        batch_ready(profile, pid, utc_text(anchor + 3 + index / 1000))
        for index, pid in enumerate(pids)
    ]
    gunicorn = [
        plain_log(
            f"[INFO] Booting worker with pid: {pid}",
            utc_text(anchor + 1.7 + index / 1000))
        for index, pid in enumerate(pids)
    ]
    gunicorn.extend((
        plain_log(
            "[INFO] Listening at: http://0.0.0.0:5005 (700)",
            utc_text(anchor + 1.9)),
        plain_log(
            "[INFO] Listening at: http://0.0.0.0:5005",
            utc_text(anchor + 1.95)),
    ))
    return [*gunicorn, *base, *batch], pids


def system_metadata(*, scheduled_object=POD):
    return [
        {"reason": "Scheduled", "involved_object": scheduled_object,
         "timestamp": "2026-10-29T10:00:00.500735Z", "count": 1},
        {"reason": "Created", "involved_object": POD,
         "timestamp": "2026-10-29T10:00:01.500000Z", "count": 2},
        {"reason": "Started", "involved_object": POD,
         "timestamp": "2026-10-29T10:00:01.900000Z", "count": 2},
    ]


def exact_system_metadata():
    return [
        {"reason": "Scheduled", "involved_object": POD,
         "timestamp": "2026-10-29T10:00:00.500000Z", "count": 1},
        {"reason": "Created", "involved_object": POD,
         "timestamp": "2026-10-29T10:00:01.000000Z", "count": 1},
        {"reason": "Started", "involved_object": POD,
         "timestamp": "2026-10-29T10:00:01.500000Z", "count": 1},
    ]


def multi_container_system_metadata():
    return [
        {"reason": "ReplicaCreated", "involved_object": POD,
         "timestamp": "2026-10-29T10:16:58.900000Z", "count": 1},
        {"reason": "Scheduled", "involved_object": POD,
         "timestamp": "2026-10-29T10:16:59.074492Z", "count": 1},
        {"reason": "Created", "involved_object": POD,
         "timestamp": "2026-10-29T10:17:00.000000Z", "count": 1},
        {"reason": "Started", "involved_object": POD,
         "timestamp": "2026-10-29T10:17:00.000000Z", "count": 1},
        {"reason": "Pulling", "involved_object": POD,
         "timestamp": "2026-10-29T10:17:01.000000Z", "count": 1},
        {"reason": "Created", "involved_object": POD,
         "timestamp": "2026-10-29T10:20:18.000000Z", "count": 1},
        {"reason": "Pulled", "involved_object": POD,
         "timestamp": "2026-10-29T10:20:18.000000Z", "count": 1},
        {"reason": "Started", "involved_object": POD,
         "timestamp": "2026-10-29T10:20:19.000000Z", "count": 1},
    ]


def multi_container_warmup():
    return {
        "excluded": True,
        "status": 200,
        "oracle_ok": True,
        "transport_started_at_utc": "2026-10-29T10:20:47.500000Z",
        "transport_ended_at_utc": "2026-10-29T10:20:47.900000Z",
        "elapsed_monotonic_seconds": 0.4,
    }


def multi_container_client_times():
    return {
        "requested": "2026-10-29T10:16:54.751000Z",
        "accepted": "2026-10-29T10:16:55.077000Z",
        "observed": "2026-10-29T10:20:47.459000Z",
    }


def warmup_metadata(*, status=200, oracle_ok=True):
    return {
        "excluded": True,
        "status": status,
        "oracle_ok": oracle_ok,
        "transport_started_at_utc": "2026-10-29T10:00:06.200000Z",
        "transport_ended_at_utc": "2026-10-29T10:00:06.600000Z",
        "elapsed_monotonic_seconds": 0.4,
    }


def summarize(logs, metadata, profile, *, warmup=None, cache=None,
              requested=REQUESTED, accepted=ACCEPTED, observed=OBSERVED):
    return startup.summarize_startup(
        logs, metadata, profile, POD,
        client_resume_requested_at_utc=requested,
        client_resume_accepted_at_utc=accepted,
        client_ready_observed_at_utc=observed,
        warmup_metadata=warmup,
        trusted_image_cache=cache)


class StartupSummaryTests(unittest.TestCase):
    def test_internal_timestamp_and_metadata_validators_reject_untrusted_shapes(self):
        for value in (None, 1, "", "not-a-time", "2026-10-29T10:00:00"):
            with self.subTest(timestamp=value), self.assertRaises(startup.StartupError):
                startup._normalize_utc(value, "sample")
        for value in (True, "1", -1, float("nan"), float("inf")):
            with self.subTest(duration=value), self.assertRaises(startup.StartupError):
                startup._finite_duration(value)
        with self.assertRaisesRegex(startup.StartupError, "timestamp_order_invalid"):
            startup._duration(
                datetime(2026, 10, 29, 10, 0, 1, tzinfo=timezone.utc),
                datetime(2026, 10, 29, 10, 0, 0, tzinfo=timezone.utc),
                "unavailable")
        self.assertEqual(
            startup._duration(None, None, "fallback", start_reason="start_missing"), {
                "seconds": None, "unknown_reason": "start_missing",
            })
        self.assertEqual(
            startup._duration(None, None, "fallback", end_reason="end_missing"), {
                "seconds": None, "unknown_reason": "fallback",
            })
        for row in (None, {}, {"message": 1}, {"message": "a", "log": "b"}):
            self.assertIsNone(startup._line_text(row))
        with self.assertRaises(startup.StartupError):
            startup._system_utc(float("inf"), "sample")
        with self.assertRaises(startup.StartupError):
            startup._system_utc(1e100, "sample")
        self.assertEqual(
            startup._normalize_utc(
                datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc),
                "sample")[1],
            "2026-10-29T10:00:00.000000Z")
        with self.assertRaises(startup.StartupError):
            startup._timestamp_from_row({})
        self.assertEqual(
            startup._system_event_timestamp({}),
            (None, "provider_timestamp_unavailable"))
        self.assertEqual(
            startup._system_event_timestamp({
                "timestamp": "2026-10-29T10:00:00Z",
                "count": 2,
            }),
            (None, "provider_timestamp_ambiguous"))
        self.assertEqual(
            startup._system_event_timestamp({
                "first_timestamp": "2026-10-29T10:00:00Z",
                "last_timestamp": "2026-10-29T10:00:01Z",
                "count": True,
            }),
            (None, "provider_timestamp_ambiguous"))
        replica_created, replica_reason = startup._system_event_timestamp(
            {"created_at": "2026-10-29T10:00:00.200000Z", "count": 1},
            "replica_created")
        self.assertEqual(replica_created, datetime(
            2026, 10, 29, 10, 0, 0, 200000, tzinfo=timezone.utc))
        self.assertIsNone(replica_reason)
        for metadata in (None, [None]):
            with self.subTest(metadata=metadata), self.assertRaises(startup.StartupError):
                startup._system_lifecycle(metadata, POD)
        with self.assertRaises(startup.StartupError):
            startup._warmup_timing("invalid")
        for changes in (
            {"status": 99},
            {"status": 503, "oracle_ok": True},
            {"excluded": False},
        ):
            value = warmup_metadata()
            value.update(changes)
            with self.subTest(changes=changes), self.assertRaises(startup.StartupError):
                startup._warmup_timing(value)
        incomplete = warmup_metadata()
        incomplete.pop("transport_ended_at_utc")
        timing, started, ended, valid = startup._warmup_timing(incomplete)
        self.assertEqual(timing["unknown_reason"], "warmup_timing_unavailable")
        self.assertIsNone(started)
        self.assertIsNone(ended)
        self.assertFalse(valid)
        reversed_warmup = warmup_metadata()
        reversed_warmup["transport_started_at_utc"] = "2026-10-29T10:00:07Z"
        with self.assertRaises(startup.StartupError):
            startup._warmup_timing(reversed_warmup)

    def test_native_scheduled_before_container_events_does_not_block_ready_startup(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        summary = summarize(
            logs, system_metadata(), profile, warmup=warmup_metadata())
        lifecycle = summary["system_lifecycle"]
        self.assertEqual(
            lifecycle["scheduled"]["timestamp_utc"],
            "2026-10-29T10:00:00.500735Z")
        self.assertEqual(lifecycle["container_created"], {
            "timestamp_utc": None,
            "unknown_reason": "provider_timestamp_ambiguous",
        })
        self.assertEqual(lifecycle["container_started"], {
            "timestamp_utc": None,
            "unknown_reason": "provider_timestamp_ambiguous",
        })
        self.assertEqual(lifecycle["replica_created"], {
            "timestamp_utc": None,
            "unknown_reason": "provider_replica_created_unavailable",
        })
        self.assertEqual(
            summary["durations_seconds"]["scheduled_to_container_created"], {
                "seconds": None,
                "unknown_reason": "provider_timestamp_ambiguous",
            })
        self.assertEqual(
            summary["durations_seconds"]["container_started_to_all_ready"], {
                "seconds": None,
                "unknown_reason": "provider_timestamp_ambiguous",
            })
        self.assertEqual(
            summary["readiness"]["base_ready_count"], profile["workers"])
        self.assertEqual(
            summary["readiness"]["batch_ready_count"], profile["workers"])
        self.assertEqual(summary["image_cache"]["status"], "unknown")

    def test_validates_all_readiness_workers_and_keeps_actual_counts(self):
        for workers in (8, 12, 16):
            with self.subTest(workers=workers):
                profile = profile_for(workers)
                logs, pids = readiness_logs(profile)
                summary = summarize(
                    logs, system_metadata(), profile,
                    warmup=warmup_metadata())
                self.assertEqual(summary["workers"], workers)
                self.assertEqual(summary["observation_count"], 1)
                self.assertEqual(summary["readiness"]["base_ready_count"], workers)
                self.assertEqual(summary["readiness"]["batch_ready_count"], workers)
                self.assertEqual(
                    summary["readiness"]["base_first_ready_at_utc"],
                    utc_text(1_793_268_002))
                self.assertEqual(
                    summary["readiness"]["batch_last_ready_at_utc"],
                    utc_text(1_793_268_003 + (workers - 1) / 1000))
                self.assertEqual(
                    [event["pid"] for event in summary["gunicorn"]["booting_workers"]],
                    list(pids))
                self.assertEqual(
                    summary["image_cache"]["unknown_reason"],
                    "trusted_cache_metadata_unavailable")
                durations = summary["durations_seconds"]
                self.assertEqual(
                    durations["resume_accepted_to_last_ready_event"]["seconds"],
                    2.0 + (workers - 1) / 1000)
                self.assertEqual(
                    durations["resume_accepted_to_ready_observed"]["seconds"], 5.0)
                self.assertAlmostEqual(
                    durations["first_worker_boot_to_all_ready"]["seconds"],
                    1.3 + (workers - 1) / 1000)
                self.assertAlmostEqual(
                    durations["first_gunicorn_listening_to_all_ready"]["seconds"],
                    1.1 + (workers - 1) / 1000)
                self.assertEqual(
                    durations["resume_requested_to_first_valid_response"]["seconds"],
                    6.6)
                self.assertEqual(
                    durations["resume_accepted_to_first_valid_response"]["seconds"],
                    5.6)
                self.assertEqual(
                    summary["warmup"]["elapsed_monotonic_seconds"], 0.4)
                self.assertIsNone(
                    summary["limitations"]["cross_clock_uncertainty_seconds"])
                self.assertIn("clock_offset_unmeasured", json.dumps(summary))
                for label in (
                    "first_worker_boot_to_all_ready",
                    "first_gunicorn_listening_to_all_ready",
                ):
                    limitation = summary["limitations"][label]
                    for expected in (
                        "model", "CUDA", "warmup", "barrier",
                        "not pure weight loading",
                    ):
                        self.assertIn(expected, limitation)

    def test_exact_container_lifecycle_uses_scheduled_created_started_order(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        summary = summarize(
            logs, exact_system_metadata(), profile,
            warmup=warmup_metadata())
        lifecycle = summary["system_lifecycle"]
        self.assertEqual(
            lifecycle["scheduled"]["timestamp_utc"],
            "2026-10-29T10:00:00.500000Z")
        self.assertEqual(
            lifecycle["container_created"]["timestamp_utc"],
            "2026-10-29T10:00:01.000000Z")
        self.assertEqual(
            lifecycle["container_started"]["timestamp_utc"],
            "2026-10-29T10:00:01.500000Z")
        self.assertIsNone(lifecycle["container_created"]["unknown_reason"])
        durations = summary["durations_seconds"]
        self.assertEqual(
            durations["scheduled_to_container_created"], {
                "seconds": 0.5, "unknown_reason": None,
            })
        self.assertEqual(
            durations["container_created_to_started"], {
                "seconds": 0.5, "unknown_reason": None,
            })
        self.assertEqual(
            durations["container_started_to_all_ready"]["seconds"],
            1.5 + 7 / 1000)
        self.assertEqual(
            durations["replica_created_to_scheduled"], {
                "seconds": None,
                "unknown_reason": "provider_replica_created_unavailable",
            })

    def test_replica_created_is_distinguished_from_container_created(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        for field in ("created_at", "timestamp"):
            with self.subTest(field=field):
                metadata = exact_system_metadata()
                metadata.insert(0, {
                    "reason": "ReplicaCreated", "involved_object": POD,
                    field: "2026-10-29T10:00:00.200000Z", "count": 1,
                })
                summary = summarize(
                    logs, metadata, profile, warmup=warmup_metadata())
                lifecycle = summary["system_lifecycle"]
                self.assertEqual(
                    lifecycle["replica_created"]["timestamp_utc"],
                    "2026-10-29T10:00:00.200000Z")
                self.assertEqual(
                    lifecycle["container_created"]["timestamp_utc"],
                    "2026-10-29T10:00:01.000000Z")
                self.assertEqual(
                    summary["durations_seconds"]["replica_created_to_scheduled"], {
                        "seconds": 0.3, "unknown_reason": None,
                    })

    def test_container_lifecycle_order_violations_are_rejected(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        for index, timestamp in ((0, "2026-10-29T10:00:01.100000Z"),
                                 (1, "2026-10-29T10:00:01.600000Z"),
                                 (2, "2026-10-29T10:00:00.400000Z")):
            with self.subTest(index=index, timestamp=timestamp):
                metadata = exact_system_metadata()
                metadata[index]["timestamp"] = timestamp
                with self.assertRaisesRegex(
                        startup.StartupError, "timestamp_order_invalid"):
                    summarize(logs, metadata, profile)
        for timestamp in ("2026-10-29T10:00:00.600000Z",
                          "2026-10-29T10:00:02.000000Z"):
            with self.subTest(replica_created=timestamp):
                metadata = exact_system_metadata()
                metadata.insert(0, {
                    "reason": "ReplicaCreated", "involved_object": POD,
                    "timestamp": timestamp, "count": 1,
                })
                with self.assertRaisesRegex(
                        startup.StartupError, "timestamp_order_invalid"):
                    summarize(logs, metadata, profile)
        equal = exact_system_metadata()
        for row in equal:
            row["timestamp"] = "2026-10-29T10:00:01.500000Z"
        summary = summarize(logs, equal, profile)
        self.assertEqual(
            summary["durations_seconds"]["scheduled_to_container_created"], {
                "seconds": 0.0, "unknown_reason": None,
            })

    def test_duplicate_overlapping_container_event_windows_remain_unknown(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        metadata = system_metadata()
        metadata.append({
            "reason": "Created", "involved_object": POD,
            "first_timestamp": "2026-10-29T10:00:01.400000Z",
            "last_timestamp": "2026-10-29T10:00:01.600000Z",
            "count": 2,
        })
        metadata.append({
            "reason": "Started", "involved_object": POD,
            "first_timestamp": "2026-10-29T10:00:01.800000Z",
            "last_timestamp": "2026-10-29T10:00:02.000000Z",
            "count": 2,
        })
        summary = summarize(logs, metadata, profile)
        self.assertEqual(
            summary["system_lifecycle"]["container_created"], {
                "timestamp_utc": None,
                "unknown_reason": "provider_timestamp_ambiguous",
            })
        self.assertEqual(
            summary["system_lifecycle"]["container_started"], {
                "timestamp_utc": None,
                "unknown_reason": "provider_timestamp_ambiguous",
            })
        duplicated = system_metadata()
        duplicated.append(copy.deepcopy(system_metadata()[1]))
        summarize(logs, duplicated, profile)
        conflicting = exact_system_metadata()
        conflicting.append({
            "reason": "Started", "involved_object": POD,
            "timestamp": "2026-10-29T10:00:01.900000Z", "count": 1,
        })
        summary = summarize(logs, conflicting, profile)
        self.assertEqual(
            summary["system_lifecycle"]["container_started"], {
                "timestamp_utc": None,
                "unknown_reason": "provider_multiple_container_events",
            })
        self.assertEqual(
            summary["durations_seconds"]["container_created_to_started"], {
                "seconds": None,
                "unknown_reason": "provider_multiple_container_events",
            })
        self.assertEqual(
            summary["readiness"]["batch_ready_count"], profile["workers"])
        stable = exact_system_metadata()
        stable.append(copy.deepcopy(exact_system_metadata()[2]))
        self.assertEqual(
            summarize(logs, stable, profile)[
                "system_lifecycle"]["container_started"]["timestamp_utc"],
            "2026-10-29T10:00:01.500000Z")

    def test_aggregated_container_events_with_explicit_count_remain_unknown(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        metadata = exact_system_metadata()
        metadata[1].update({
            "first_timestamp": "2026-10-29T10:00:01.000000Z",
            "last_timestamp": "2026-10-29T10:00:01.000000Z",
            "count": 2,
        })
        metadata[1].pop("timestamp")
        summary = summarize(logs, metadata, profile)
        self.assertEqual(
            summary["system_lifecycle"]["container_created"], {
                "timestamp_utc": None,
                "unknown_reason": "provider_timestamp_ambiguous",
            })
        self.assertEqual(
            summary["system_lifecycle"]["container_started"]["timestamp_utc"],
            "2026-10-29T10:00:01.500000Z")
        scheduled = exact_system_metadata()
        scheduled[0]["count"] = 2
        summary = summarize(logs, scheduled, profile)
        self.assertEqual(
            summary["system_lifecycle"]["scheduled"], {
                "timestamp_utc": None,
                "unknown_reason": "provider_timestamp_ambiguous",
            })
        self.assertEqual(
            summary["durations_seconds"]["scheduled_to_container_created"], {
                "seconds": None,
                "unknown_reason": "provider_timestamp_ambiguous",
            })

    def test_outputs_only_allowlisted_metadata_and_marks_cache_only_when_trusted(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        logs.append(copy.deepcopy(logs[0]))
        logs.append(provider_row(
            "", {"message": "API_KEY=private carrier=secret body=private"},
            utc_text(1_793_268_004)))
        metadata = [*system_metadata(), {
            "reason": "Created", "involved_object": POD,
            "timestamp": "2026-10-29T10:00:01.500000Z", "count": 2,
            "message": "raw system message must not be copied",
        }, {
            "reason": "Pulling", "involved_object": POD,
            "timestamp": "2026-10-29T10:00:00.900000Z",
        }, {
            "reason": 5, "involved_object": POD,
        }]
        summary = summarize(
            logs, metadata, profile, warmup=warmup_metadata(), cache=True)
        serialized = json.dumps(summary)
        for forbidden in (
            RUN_ID, POD, "API_KEY", "private", "carrier", "raw system message",
            "dictionary_delta", "Authorization", "uuid",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)
        self.assertEqual(summary["image_cache"], {
            "status": "cached", "unknown_reason": None,
        })
        self.assertEqual(
            summary["system_lifecycle"]["scheduled"]["timestamp_utc"],
            "2026-10-29T10:00:00.500735Z")
        self.assertEqual(
            summary["system_lifecycle"]["container_created"]["unknown_reason"],
            "provider_timestamp_ambiguous")
        uncached = summarize(logs, metadata, profile, cache=False)
        self.assertEqual(uncached["image_cache"], {
            "status": "not_cached", "unknown_reason": None,
        })
        self.assertEqual(summary["gunicorn"]["listening_events"], [
            {"pid": 700, "timestamp_utc": utc_text(1_793_268_001.9)},
            {"pid": None, "timestamp_utc": utc_text(1_793_268_001.95)},
        ])

    def test_provider_system_events_require_exact_pod_identity_and_do_not_guess(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        summary = summarize(
            logs, system_metadata(scheduled_object=POD + "-replicaset"), profile)
        scheduled = summary["system_lifecycle"]["scheduled"]
        self.assertIsNone(scheduled["timestamp_utc"])
        self.assertEqual(scheduled["unknown_reason"], "provider_object_not_exact_pod")
        self.assertEqual(
            summary["durations_seconds"]["scheduled_to_container_created"], {
                "seconds": None,
                "unknown_reason": "provider_object_not_exact_pod",
            })

    def test_system_metadata_accepts_safe_epoch_and_single_occurrence_timestamps(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        metadata = exact_system_metadata()
        created = datetime.fromisoformat(
            metadata[1].pop("timestamp").replace("Z", "+00:00"))
        metadata[1]["timestamp"] = created.timestamp()
        scheduled = metadata[0].pop("timestamp")
        metadata[0].update({
            "first_timestamp": scheduled,
            "last_timestamp": scheduled,
            "count": 1,
        })
        summary = summarize(logs, metadata, profile)
        self.assertEqual(
            summary["system_lifecycle"]["scheduled"]["timestamp_utc"],
            "2026-10-29T10:00:00.500000Z")
        self.assertEqual(
            summary["system_lifecycle"]["container_created"]["timestamp_utc"],
            "2026-10-29T10:00:01.000000Z")

    def test_failed_warmup_timing_is_known_but_first_valid_response_is_not(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        summary = summarize(
            logs, system_metadata(), profile,
            warmup=warmup_metadata(oracle_ok=False))
        self.assertEqual(
            summary["durations_seconds"]["warmup_transport"], {
                "seconds": 0.4, "unknown_reason": None,
            })
        self.assertEqual(
            summary["durations_seconds"]["resume_accepted_to_first_valid_response"], {
                "seconds": None,
                "unknown_reason": "first_valid_response_unobserved",
            })

    def test_provider_worker_boot_duplicates_must_be_stable(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        first_boot = logs[0]
        logs.append(plain_log(
            first_boot["message"], "2026-10-29T10:00:01.800000Z"))
        with self.assertRaisesRegex(startup.StartupError, "gunicorn_worker_churn"):
            summarize(logs, system_metadata(), profile)

    def test_missing_optional_provider_timestamps_are_unknown_not_zero(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        summary = summarize(logs, [], profile)
        self.assertEqual(summary["system_lifecycle"], {
            "replica_created": {
                "timestamp_utc": None,
                "unknown_reason": "provider_replica_created_unavailable",
            },
            "scheduled": {
                "timestamp_utc": None,
                "unknown_reason": "provider_scheduled_unavailable",
            },
            "container_created": {
                "timestamp_utc": None,
                "unknown_reason": "provider_container_created_unavailable",
            },
            "container_started": {
                "timestamp_utc": None,
                "unknown_reason": "provider_container_started_unavailable",
            },
            "pulling": {
                "timestamp_utc": None,
                "unknown_reason": "provider_pulling_unavailable",
            },
            "pulled": {
                "timestamp_utc": None,
                "unknown_reason": "provider_pulled_unavailable",
            },
        })
        for field in summary["system_lifecycle"].values():
            if field["timestamp_utc"] is None:
                self.assertIsNotNone(field["unknown_reason"])
            else:
                self.assertIsNone(field["unknown_reason"])
        self.assertEqual(
            summary["durations_seconds"]["container_started_to_all_ready"], {
                "seconds": None,
                "unknown_reason": "provider_container_started_unavailable",
            })
        self.assertEqual(
            summary["durations_seconds"]["scheduled_to_container_created"], {
                "seconds": None,
                "unknown_reason": "provider_scheduled_unavailable",
            })
        self.assertEqual(
            summary["durations_seconds"]["provider_pull_phase"], {
                "seconds": None,
                "unknown_reason": "provider_pulling_unavailable",
            })
        self.assertEqual(
            summary["durations_seconds"]["warmup_transport"], {
                "seconds": None, "unknown_reason": "warmup_metadata_unavailable",
            })
        self.assertEqual(
            summary["durations_seconds"]["resume_accepted_to_first_valid_response"], {
                "seconds": None, "unknown_reason": "warmup_metadata_unavailable",
            })
        self.assertEqual(
            summary["durations_seconds"]["resume_requested_to_first_valid_response"], {
                "seconds": None, "unknown_reason": "warmup_metadata_unavailable",
            })

    def test_missing_gunicorn_events_only_leave_loading_proxies_unknown(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        logs = [
            row for row in logs
            if not row["message"].startswith(
                ("[INFO] Booting worker", "[INFO] Listening at:"))
        ]
        summary = summarize(logs, exact_system_metadata(), profile)
        self.assertEqual(
            summary["durations_seconds"]["first_worker_boot_to_all_ready"], {
                "seconds": None, "unknown_reason": "gunicorn_boot_unavailable",
            })
        self.assertEqual(
            summary["durations_seconds"]["first_gunicorn_listening_to_all_ready"], {
                "seconds": None,
                "unknown_reason": "gunicorn_listening_unavailable",
            })
        self.assertEqual(
            summary["durations_seconds"]["container_started_to_all_ready"][
                "seconds"], 1.5 + 7 / 1000)

    def test_gunicorn_listening_after_all_ready_is_rejected(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        logs = [
            row for row in logs
            if not row["message"].startswith("[INFO] Listening at:")
        ]
        logs.append(plain_log(
            "[INFO] Listening at: http://0.0.0.0:5005 (700)",
            utc_text(1_793_268_005)))
        with self.assertRaisesRegex(startup.StartupError, "timestamp_order_invalid"):
            summarize(logs, exact_system_metadata(), profile)

    def test_boot_after_worker_ready_and_container_start_after_all_ready_are_rejected(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        for row in logs:
            if row["message"].startswith("[INFO] Booting worker with pid: 810"):
                row["timestamp"] = utc_text(1_793_268_002.5)
                break
        with self.assertRaisesRegex(startup.StartupError, "timestamp_order_invalid"):
            summarize(logs, exact_system_metadata(), profile)
        logs, _pids = readiness_logs(profile)
        metadata = exact_system_metadata()
        metadata[2]["timestamp"] = "2026-10-29T10:00:04.000000Z"
        with self.assertRaisesRegex(startup.StartupError, "timestamp_order_invalid"):
            summarize(logs, metadata, profile)

    def test_warmup_start_before_ready_observation_is_rejected(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        warmup = warmup_metadata()
        warmup["transport_started_at_utc"] = "2026-10-29T10:00:05.000000Z"
        with self.assertRaisesRegex(startup.StartupError, "timestamp_order_invalid"):
            summarize(logs, exact_system_metadata(), profile, warmup=warmup)

    def test_rejects_bad_client_order_timezone_worker_count_hash_and_missing_ready(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile)
        bad_inputs = (
            {
                "client_resume_requested_at_utc": ACCEPTED,
                "client_resume_accepted_at_utc": REQUESTED,
                "client_ready_observed_at_utc": OBSERVED,
            },
            {
                "client_resume_requested_at_utc": "2026-10-29T10:00:00",
                "client_resume_accepted_at_utc": ACCEPTED,
                "client_ready_observed_at_utc": OBSERVED,
            },
            {
                "client_resume_requested_at_utc": REQUESTED,
                "client_resume_accepted_at_utc": ACCEPTED,
                "client_ready_observed_at_utc": "2026-10-29T12:00:06+02:00",
            },
        )
        for arguments in bad_inputs:
            with self.subTest(arguments=arguments), self.assertRaises(startup.StartupError):
                startup.summarize_startup(logs, system_metadata(), profile, POD,
                                          **arguments)
        invalid_system_time = system_metadata()
        invalid_system_time[1]["timestamp"] = "2026-10-29T12:00:01+02:00"
        with self.assertRaises(startup.StartupError):
            summarize(logs, invalid_system_time, profile)
        with self.assertRaisesRegex(startup.StartupError, "timestamp_order_invalid"):
            summarize(
                logs, system_metadata(), profile,
                requested=OBSERVED, accepted=OBSERVED,
                observed="2026-10-29T10:00:07Z")
        with self.assertRaises(startup.StartupError):
            summarize(logs[:-1], system_metadata(), profile)
        corrupt_hash = copy.deepcopy(logs)
        payload = json.loads(corrupt_hash[-1]["message"][len(batch_runtime.EVENT_PREFIX):])
        payload["manifest_sha256"] = "0" * 64
        corrupt_hash[-1]["message"] = batch_runtime.EVENT_PREFIX + json.dumps(payload)
        with self.assertRaises(startup.StartupError):
            summarize(corrupt_hash, system_metadata(), profile)
        worker_mismatch = copy.deepcopy(logs)
        base_index = next(
            index for index, row in enumerate(worker_mismatch)
            if row["message"].startswith("VERDAEXPERIMENT "))
        payload = json.loads(worker_mismatch[base_index]["message"][
            len("VERDAEXPERIMENT "):])
        payload["workers"] = 12
        worker_mismatch[base_index]["message"] = (
            "VERDAEXPERIMENT " + json.dumps(payload))
        with self.assertRaises(startup.StartupError):
            summarize(worker_mismatch, system_metadata(), profile)

    def test_rejects_worker_churn_and_invalid_warmup_metadata(self):
        profile = profile_for(8)
        logs, pids = readiness_logs(profile)
        logs.append(provider_row(
            "VERDAEXPERIMENT ", {
                "run_id": profile["run_id"], "event": "exit", "pid": pids[0],
                "workers": 8, "request_count": 0,
            }, utc_text(1_793_268_004)))
        with self.assertRaises(startup.StartupError):
            summarize(logs, system_metadata(), profile)
        logs, pids = readiness_logs(profile)
        logs.append(plain_log(
            "[INFO] Booting worker with pid: 9999",
            utc_text(1_793_268_001.8)))
        with self.assertRaisesRegex(startup.StartupError, "gunicorn_worker_churn"):
            summarize(logs, system_metadata(), profile)
        bad_warmup = warmup_metadata()
        bad_warmup["elapsed_monotonic_seconds"] = float("nan")
        logs, _pids = readiness_logs(profile)
        with self.assertRaises(startup.StartupError):
            summarize(logs, system_metadata(), profile, warmup=bad_warmup)
        with self.assertRaises(startup.StartupError):
            summarize(logs, system_metadata(), profile, cache=1)

    def test_multi_container_init_and_main_events_are_ambiguous_not_picked(self):
        profile = profile_for(8)
        logs, pids = readiness_logs(profile, offset_seconds=1218)
        summary = summarize(
            logs, multi_container_system_metadata(), profile,
            warmup=multi_container_warmup(),
            **multi_container_client_times())
        lifecycle = summary["system_lifecycle"]
        self.assertEqual(
            lifecycle["replica_created"]["timestamp_utc"],
            "2026-10-29T10:16:58.900000Z")
        self.assertEqual(
            lifecycle["scheduled"]["timestamp_utc"],
            "2026-10-29T10:16:59.074492Z")
        self.assertEqual(lifecycle["container_created"], {
            "timestamp_utc": None,
            "unknown_reason": "provider_multiple_container_events",
        })
        self.assertEqual(lifecycle["container_started"], {
            "timestamp_utc": None,
            "unknown_reason": "provider_multiple_container_events",
        })
        self.assertEqual(
            lifecycle["pulling"]["timestamp_utc"],
            "2026-10-29T10:17:01.000000Z")
        self.assertEqual(
            lifecycle["pulled"]["timestamp_utc"],
            "2026-10-29T10:20:18.000000Z")
        durations = summary["durations_seconds"]
        self.assertEqual(durations["provider_pull_phase"], {
            "seconds": 197.0,
            "unknown_reason": None,
        })
        for label in (
            "scheduled_to_container_created",
            "container_created_to_started",
            "container_started_to_all_ready",
        ):
            with self.subTest(label=label):
                self.assertEqual(durations[label], {
                    "seconds": None,
                    "unknown_reason": "provider_multiple_container_events",
                })
        self.assertAlmostEqual(
            durations["replica_created_to_scheduled"]["seconds"], 0.174492)
        self.assertAlmostEqual(
            durations["first_worker_boot_to_all_ready"]["seconds"], 1.307)
        self.assertEqual(summary["readiness"]["base_ready_count"], 8)
        self.assertEqual(summary["readiness"]["batch_ready_count"], 8)
        self.assertEqual(
            [event["pid"] for event in summary["gunicorn"]["booting_workers"]],
            list(pids))
        self.assertIsNone(summary["warmup"]["unknown_reason"])
        self.assertEqual(summary["image_cache"], {
            "status": "unknown",
            "unknown_reason": "trusted_cache_metadata_unavailable",
        })
        limitation = summary["limitations"]["provider_pull_phase"]
        for expected in (
            "Pulling", "Pulled",
            "not guaranteed pure download bytes",
            "not a cold-cache measurement",
        ):
            self.assertIn(expected, limitation)
        serialized = json.dumps(summary)
        self.assertNotIn(POD, serialized)
        self.assertNotIn(RUN_ID, serialized)

    def test_ambiguous_or_missing_pull_metadata_keeps_summary_and_conflicts_raise(self):
        profile = profile_for(8)
        logs, _pids = readiness_logs(profile, offset_seconds=1218)
        arguments = {
            "warmup": multi_container_warmup(),
            **multi_container_client_times(),
        }
        missing = [
            row for row in multi_container_system_metadata()
            if row["reason"] not in ("Pulling", "Pulled")]
        summary = summarize(logs, missing, profile, **arguments)
        self.assertEqual(
            summary["durations_seconds"]["provider_pull_phase"], {
                "seconds": None,
                "unknown_reason": "provider_pulling_unavailable",
            })
        self.assertEqual(summary["readiness"]["batch_ready_count"], 8)
        partial = [
            row for row in multi_container_system_metadata()
            if row["reason"] != "Pulled"]
        self.assertEqual(
            summarize(logs, partial, profile, **arguments)[
                "durations_seconds"]["provider_pull_phase"], {
                "seconds": None,
                "unknown_reason": "provider_pulled_unavailable",
            })
        aggregated = multi_container_system_metadata()
        aggregated.append({
            "reason": "Pulling", "involved_object": POD,
            "timestamp": "2026-10-29T10:17:01.000000Z", "count": 2,
        })
        summary = summarize(logs, aggregated, profile, **arguments)
        self.assertEqual(summary["system_lifecycle"]["pulling"], {
            "timestamp_utc": None,
            "unknown_reason": "provider_timestamp_ambiguous",
        })
        self.assertEqual(
            summary["durations_seconds"]["provider_pull_phase"], {
                "seconds": None,
                "unknown_reason": "provider_timestamp_ambiguous",
            })
        duplicated = multi_container_system_metadata()
        duplicated.append({
            "reason": "Pulled", "involved_object": POD,
            "timestamp": "2026-10-29T10:20:18.000000Z", "count": 1,
        })
        self.assertEqual(
            summarize(logs, duplicated, profile, **arguments)[
                "durations_seconds"]["provider_pull_phase"], {
                "seconds": 197.0,
                "unknown_reason": None,
            })
        conflicting_pull = multi_container_system_metadata()
        conflicting_pull.append({
            "reason": "Pulling", "involved_object": POD,
            "timestamp": "2026-10-29T10:18:00.000000Z", "count": 1,
        })
        summary = summarize(logs, conflicting_pull, profile, **arguments)
        self.assertEqual(summary["system_lifecycle"]["pulling"], {
            "timestamp_utc": None,
            "unknown_reason": "provider_multiple_container_events",
        })
        self.assertEqual(
            summary["durations_seconds"]["provider_pull_phase"], {
                "seconds": None,
                "unknown_reason": "provider_multiple_container_events",
            })
        self.assertEqual(summary["readiness"]["base_ready_count"], 8)
        reversed_pull = multi_container_system_metadata()
        for row in reversed_pull:
            if row["reason"] == "Pulled":
                row["timestamp"] = "2026-10-29T10:17:00.500000Z"
        with self.assertRaisesRegex(
                startup.StartupError, "timestamp_order_invalid"):
            summarize(logs, reversed_pull, profile, **arguments)
        for reason, timestamp in (
            ("Scheduled", "2026-10-29T10:17:30.000000Z"),
            ("ReplicaCreated", "2026-10-29T10:17:00.500000Z"),
        ):
            with self.subTest(reason=reason):
                conflicting = multi_container_system_metadata()
                conflicting.append({
                    "reason": reason, "involved_object": POD,
                    "timestamp": timestamp, "count": 1,
                })
                with self.assertRaisesRegex(
                        startup.StartupError,
                        "system_event_duplicate_mismatch"):
                    summarize(logs, conflicting, profile, **arguments)


if __name__ == "__main__":
    unittest.main()
