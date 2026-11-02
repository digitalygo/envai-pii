import hashlib
import json
from datetime import datetime, timezone
import time
import unittest
from unittest import mock

from tools.verda_model_experiment import gpu_monitor, gpu_profile, measure
from tools.verda_model_experiment.fixture import FIXTURE_BODY


BASE_EPOCH_MS = 1_700_000_000_000
BASE_MONOTONIC_MS = 1_000
CASE_WINDOWS = (
    (1_000, 20_000),
    (61_000, 80_000),
    (121_000, 140_000),
    (181_000, 200_000),
    (241_000, 260_000),
    (301_000, 320_000),
)


class Response:
    def __init__(self, status=200, body=b"canonical"):
        self.status = status
        self.body = body


def canonical_validator(body):
    if body != b"canonical":
        raise ValueError("oracle mismatch")
    return hashlib.sha256(body).hexdigest()


class CallLog:
    def __init__(self):
        self.calls = []

    def sender(self, status=200, body=b"canonical", error=None):
        def send(request_body, timeout):
            self.calls.append((request_body, timeout))
            if error is not None:
                raise error
            return Response(status, body)
        return send


class SequenceClock:
    def __init__(self, values):
        self.values = list(values)

    def __call__(self):
        if not self.values:
            return 1_000_000.0
        return self.values.pop(0)


class MutableClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value


def collect_persist():
    records = []

    def persist(record):
        records.append(record)

    return records, persist


def utc_text(epoch_ms):
    value = datetime.fromtimestamp(epoch_ms / 1000, timezone.utc)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def gpu_sample(monotonic_offset, *, run_id="gpu-run", owner_pid=123,
               workers=8, gpu=0, memory=60, power=50_000, power_reason=None,
               gpu_reason=None, memory_reason=None, read_duration_ms=0):
    return {
        "run_id": run_id,
        "owner_pid": owner_pid,
        "workers": workers,
        "epoch_ms": BASE_EPOCH_MS + monotonic_offset,
        "monotonic_ms": BASE_MONOTONIC_MS + monotonic_offset,
        "read_duration_ms": read_duration_ms,
        "gpu_activity_percent": gpu,
        "memory_controller_activity_percent": memory,
        "power_milliwatts": power,
        "power_limit_milliwatts": 350_000,
        "gpu_activity_reason": gpu_reason,
        "memory_controller_activity_reason": memory_reason,
        "power_reason": power_reason,
        "power_limit_reason": None,
    }


def synthetic_profile_result():
    cases = []
    bursts = []
    for case in gpu_profile.CASE_PLAN:
        start, end = CASE_WINDOWS[case.case_index - 1]
        cases.append({
            "case_index": case.case_index,
            "client_concurrency": case.client_concurrency,
            "workers": 8,
            "model_count": 8,
            "groups_planned": case.groups,
            "groups_completed": 1,
            "bursts_completed": 1,
            "latency": {
                "model_count": 8,
                "planned_count": case.client_concurrency * 3 * case.groups,
                "attempts": case.client_concurrency,
                "success_count": case.client_concurrency,
                "marker": case.case_index,
            },
        })
        rows = [{
            "started": True,
            "timing_complete": True,
            "request_started_at_utc": utc_text(BASE_EPOCH_MS + start),
            "transport_ended_at_utc": utc_text(BASE_EPOCH_MS + end),
        } for _ in range(case.client_concurrency)]
        bursts.append({
            "case_index": case.case_index,
            "case_concurrency": case.client_concurrency,
            "group_index": 1,
            "workers": 8,
            "model_count": 8,
            "burst": {
                "client_concurrency": case.client_concurrency,
                "model_count": 8,
                "requests": rows,
            },
            "error_class": None,
            "fault": None,
        })
    return {
        "run_id": "gpu-run",
        "owner_pid": 123,
        "workers": 8,
        "model_count": 8,
        "scope": "device_global",
        "planned_requests": gpu_profile.PLANNED_REQUESTS,
        "bursts": bursts,
        "cases": cases,
    }


def synthetic_samples():
    samples = []
    gpu_values = [0, 100] * 6
    offsets = (2_000, 3_000, 4_000, 6_000, 7_000, 8_000,
               9_000, 10_000, 11_000, 12_000, 12_500, 13_000)
    for index, (offset, value) in enumerate(zip(offsets, gpu_values)):
        if index == 5:
            samples.append(gpu_sample(
                offset, gpu=value, power=None,
                power_reason="power_unavailable"))
        else:
            samples.append(gpu_sample(offset, gpu=value))
    samples.append(gpu_sample(
        5_000,
        gpu=None,
        memory=None,
        gpu_reason="utilization_unavailable",
        memory_reason="utilization_unavailable",
    ))
    samples.sort(key=lambda sample: sample["monotonic_ms"])
    samples.append(gpu_sample(13_000, gpu=100))
    samples.append(gpu_sample(15_000, gpu=50))
    samples[-1]["epoch_ms"] = BASE_EPOCH_MS + 5_000
    samples.append(gpu_sample(16_000, gpu=101))
    samples.append(gpu_sample(25_000, gpu=100))
    samples.append(gpu_sample(30_000, gpu=100, owner_pid=999))
    samples.append(gpu_sample(35_000, gpu=100, run_id="other-run"))
    samples.append(gpu_sample(40_000, gpu=100))
    for index in range(12):
        samples.append(gpu_sample(62_000 + index * 1_000, gpu=100))
    samples.append(gpu_sample(122_000, gpu=100))
    samples.append(gpu_sample(123_000, gpu=0))
    return samples


class ProfilePlanTests(unittest.TestCase):
    def test_fixed_case_plan_covers_exactly_402_requests(self):
        self.assertEqual(gpu_profile.CASE_PLAN, (
            (1, 1, 10), (2, 2, 6), (3, 4, 4),
            (4, 8, 4), (5, 16, 2), (6, 32, 1),
        ))
        self.assertEqual(gpu_profile.PLANNED_GROUPS, 27)
        self.assertEqual(gpu_profile.PLANNED_BURSTS, 81)
        self.assertEqual(gpu_profile.PLANNED_REQUESTS, 402)
        self.assertEqual(gpu_profile.TRANSPORT_TIMEOUT_SECONDS, 90.0)
        self.assertEqual(gpu_profile.MODEL_COUNT, 8)
        self.assertEqual(gpu_profile.PROFILE_WORKER_CHOICES, (8, 12, 16))

    def test_run_validation_is_strict_and_deadline_is_mandatory(self):
        sender = CallLog().sender()
        _, persist = collect_persist()
        for deadline in (None, 0, -1, float("nan"), float("inf"), True):
            with self.subTest(deadline=deadline), self.assertRaises(
                    (TypeError, ValueError)):
                gpu_profile.run_gpu_profile(
                    lambda concurrency: [sender],
                    canonical_validator,
                    persist,
                    run_id="gpu-run",
                    owner_pid=123,
                    deadline_seconds=deadline,
                )
        for run_id in ("", "../bad", "bad/run", "x" * 65, None):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                gpu_profile.run_gpu_profile(
                    lambda concurrency: [sender],
                    canonical_validator,
                    persist,
                    run_id=run_id,
                    owner_pid=123,
                    deadline_seconds=10,
                )
        for owner_pid in (0, -1, "1", True):
            with self.subTest(owner_pid=owner_pid), self.assertRaises(ValueError):
                gpu_profile.run_gpu_profile(
                    lambda concurrency: [sender],
                    canonical_validator,
                    persist,
                    run_id="gpu-run",
                    owner_pid=owner_pid,
                    deadline_seconds=10,
                )
        for workers in (1, 4, 12.0, True, "12"):
            with self.subTest(workers=workers), self.assertRaises(ValueError):
                gpu_profile.run_gpu_profile(
                    lambda concurrency: [sender], canonical_validator, persist,
                    run_id="gpu-run", owner_pid=123, deadline_seconds=10,
                    workers=workers)
        with self.assertRaises(TypeError):
            gpu_profile.run_gpu_profile(
                None, canonical_validator, persist,
                run_id="gpu-run", owner_pid=1, deadline_seconds=10)
        with self.assertRaises(TypeError):
            gpu_profile.run_gpu_profile(
                lambda concurrency: [sender], None, persist,
                run_id="gpu-run", owner_pid=1, deadline_seconds=10)
        with self.assertRaises(TypeError):
            gpu_profile.run_gpu_profile(
                lambda concurrency: [sender], canonical_validator, None,
                run_id="gpu-run", owner_pid=1, deadline_seconds=10)
        with self.assertRaises(TypeError):
            gpu_profile.run_gpu_profile(
                lambda concurrency: [sender], canonical_validator, persist,
                run_id="gpu-run", owner_pid=1, deadline_seconds=10,
                safety_check=object())


class ProfileExecutionTests(unittest.TestCase):
    def test_all_402_requests_persist_each_burst_without_retry(self):
        call_log = CallLog()
        persist_records, persist = collect_persist()
        factory_calls = []

        def factory(concurrency):
            factory_calls.append(concurrency)
            return [call_log.sender() for _ in range(concurrency)]

        result = gpu_profile.run_gpu_profile(
            factory,
            canonical_validator,
            persist,
            run_id="gpu-run",
            owner_pid=123,
            deadline_seconds=600,
        )
        self.assertEqual(factory_calls, [1, 2, 4, 8, 16, 32])
        self.assertEqual(len(call_log.calls), 402)
        self.assertTrue(all(body == FIXTURE_BODY for body, timeout in call_log.calls))
        self.assertTrue(all(timeout == 90.0 for body, timeout in call_log.calls))
        self.assertEqual(len(persist_records), 81)
        self.assertEqual(result["planned_requests"], 402)
        self.assertEqual(result["completed_bursts"], 81)
        self.assertEqual(result["completed_groups"], 27)
        self.assertEqual(result["attempts"], 402)
        self.assertEqual(result["success_count"], 402)
        self.assertIsNone(result["stop_reason"])
        self.assertEqual(len(result["bursts"]), 81)
        self.assertEqual(
            [case["groups_completed"] for case in result["cases"]],
            [10, 6, 4, 4, 2, 1],
        )
        for case in result["cases"]:
            plan = gpu_profile.CASE_PLAN[case["case_index"] - 1]
            self.assertEqual(case["groups_planned"], plan.groups)
            self.assertEqual(len(case["latency"]["group_summaries"]),
                             plan.groups)
            group_indices = [
                summary["group_index"]
                for summary in case["latency"]["group_summaries"]
            ]
            self.assertEqual(group_indices, list(range(1, plan.groups + 1)))
            for summary in case["latency"]["group_summaries"]:
                self.assertEqual(
                    summary["summary"]["planned_count"],
                    plan.client_concurrency * 3,
                )
                self.assertEqual(
                    summary["summary"]["success_count"],
                    plan.client_concurrency * 3,
                )
        for record in persist_records:
            self.assertIn("case_index", record)
            self.assertIn("group_index", record)
            self.assertEqual(record["model_count"], 8)
            self.assertIsNone(record["error_class"])

    def test_all_supported_worker_counts_keep_identity_across_402_fake_requests(self):
        for workers in gpu_profile.PROFILE_WORKER_CHOICES:
            with self.subTest(workers=workers):
                call_log = CallLog()
                records, persist = collect_persist()
                result = gpu_profile.run_gpu_profile(
                    lambda concurrency: [call_log.sender() for _ in range(concurrency)],
                    canonical_validator, persist, run_id="gpu-run",
                    owner_pid=123, deadline_seconds=600, workers=workers)
                self.assertEqual(len(call_log.calls), 402)
                self.assertEqual(len(records), 81)
                self.assertEqual(result["workers"], workers)
                self.assertEqual(result["model_count"], workers)
                self.assertEqual(result["planned_requests"], 402)
                self.assertTrue(all(
                    record["workers"] == workers
                    and record["model_count"] == workers
                    and record["burst"]["model_count"] == workers
                    for record in records))
                self.assertTrue(all(
                    case["workers"] == workers
                    and case["model_count"] == workers
                    and case["latency"]["model_count"] == workers
                    for case in result["cases"]))

    def test_expected_http_failures_are_retained_and_do_not_hide_latency(self):
        call_log = CallLog()
        persist_records, persist = collect_persist()
        result = gpu_profile.run_gpu_profile(
            lambda concurrency: [
                call_log.sender(status=429) for _ in range(concurrency)
            ],
            canonical_validator,
            persist,
            run_id="gpu-run",
            owner_pid=123,
            deadline_seconds=600,
        )
        self.assertEqual(len(call_log.calls), 402)
        self.assertEqual(len(persist_records), 81)
        self.assertIsNone(result["stop_reason"])
        self.assertEqual(result["success_count"], 0)
        self.assertEqual(result["attempts"], 402)
        self.assertEqual(result["cases"][0]["latency"]["failure_counts"],
                         {"http_status": 30})
        self.assertEqual(result["cases"][0]["latency"]["status_counts"],
                         {"429": 30})
        self.assertIsNotNone(
            result["cases"][0]["latency"]["group_summaries"][0]["summary"][
                "processing_elapsed_seconds_sum"],
        )

    def test_timeouts_are_expected_and_do_not_stop_later_bursts(self):
        call_log = CallLog()
        _, persist = collect_persist()
        result = gpu_profile.run_gpu_profile(
            lambda concurrency: [
                call_log.sender(error=TimeoutError()) for _ in range(concurrency)
            ],
            canonical_validator,
            persist,
            run_id="gpu-run",
            owner_pid=123,
            deadline_seconds=600,
        )
        self.assertEqual(len(call_log.calls), 402)
        self.assertIsNone(result["stop_reason"])
        self.assertEqual(result["attempts"], 402)
        self.assertEqual(result["cases"][0]["latency"]["failure_counts"],
                         {"timeout": 30})

    def test_5xx_stops_subsequent_calls_with_prior_rows_retained(self):
        call_log = CallLog()
        persist_records, persist = collect_persist()
        result = gpu_profile.run_gpu_profile(
            lambda concurrency: [call_log.sender(status=503)],
            canonical_validator,
            persist,
            run_id="gpu-run",
            owner_pid=123,
            deadline_seconds=600,
        )
        self.assertEqual(len(call_log.calls), 1)
        self.assertEqual(len(persist_records), 1)
        self.assertEqual(result["stop_reason"], "fault_5xx")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["cases"][0]["latency"]["status_counts"],
                         {"503": 1})
        self.assertEqual(persist_records[0]["fault"], "fault_5xx")

    def test_oracle_and_runtime_faults_stop_and_keep_the_prior_row(self):
        for name, sender, reason, failure in (
            ("oracle", CallLog().sender(body=b"wrong"), "fault_oracle",
             "invalid_200"),
            ("runtime", CallLog().sender(error=RuntimeError()), "fault_runtime",
             "transport_error"),
        ):
            with self.subTest(case=name):
                persist_records, persist = collect_persist()
                result = gpu_profile.run_gpu_profile(
                    lambda concurrency, sender=sender: [sender],
                    canonical_validator,
                    persist,
                    run_id="gpu-run",
                    owner_pid=123,
                    deadline_seconds=600,
                )
                self.assertEqual(result["stop_reason"], reason)
                self.assertEqual(len(persist_records), 1)
                self.assertEqual(result["attempts"], 1)
                self.assertEqual(
                    result["bursts"][0]["burst"]["failure_counts"],
                    {failure: 1},
                )

    def test_safety_check_between_bursts_stops_without_replay(self):
        call_log = CallLog()
        persist_records, persist = collect_persist()
        safety_calls = []

        def safety():
            safety_calls.append(1)
            if len(safety_calls) == 2:
                raise RuntimeError("unsafe")

        result = gpu_profile.run_gpu_profile(
            lambda concurrency: [call_log.sender()],
            canonical_validator,
            persist,
            run_id="gpu-run",
            owner_pid=123,
            deadline_seconds=600,
            safety_check=safety,
        )
        self.assertEqual(result["stop_reason"], "safety_stop")
        self.assertEqual(len(persist_records), 2)
        self.assertEqual(len(call_log.calls), 2)
        self.assertEqual(len(safety_calls), 2)
        self.assertEqual(result["attempts"], 2)

    def test_false_safety_check_also_stops(self):
        call_log = CallLog()
        persist_records, persist = collect_persist()
        result = gpu_profile.run_gpu_profile(
            lambda concurrency: [call_log.sender()],
            canonical_validator,
            persist,
            run_id="gpu-run",
            owner_pid=123,
            deadline_seconds=600,
            safety_check=lambda: False,
        )
        self.assertEqual(result["stop_reason"], "safety_stop")
        self.assertEqual(len(persist_records), 1)
        self.assertEqual(len(call_log.calls), 1)

    def test_external_deadline_stops_before_the_next_burst(self):
        clock = MutableClock(0.0)
        persist_records, persist = collect_persist()
        result = gpu_profile.run_gpu_profile(
            lambda concurrency: [CallLog().sender()],
            canonical_validator,
            persist,
            run_id="gpu-run",
            owner_pid=123,
            deadline_seconds=5,
            clock=clock,
            safety_check=lambda: clock.__setattr__("value", 10.0),
        )
        self.assertEqual(result["stop_reason"], "deadline")
        self.assertEqual(len(persist_records), 1)
        self.assertEqual(result["completed_bursts"], 1)

    def test_expired_deadline_stops_before_creating_senders(self):
        factory_calls = []
        persist_records, persist = collect_persist()
        result = gpu_profile.run_gpu_profile(
            lambda concurrency: factory_calls.append(concurrency) or [],
            canonical_validator,
            persist,
            run_id="gpu-run",
            owner_pid=123,
            deadline_seconds=5,
            clock=SequenceClock([0.0, 100.0]),
        )
        self.assertEqual(result["stop_reason"], "deadline")
        self.assertEqual(factory_calls, [])
        self.assertEqual(persist_records, [])

    def test_persist_failure_keeps_in_memory_rows_and_stops(self):
        call_log = CallLog()
        records = []

        def persist(record):
            records.append(record)
            if len(records) == 2:
                raise OSError("disk")

        result = gpu_profile.run_gpu_profile(
            lambda concurrency: [call_log.sender()],
            canonical_validator,
            persist,
            run_id="gpu-run",
            owner_pid=123,
            deadline_seconds=600,
        )
        self.assertEqual(result["stop_reason"], "persist_failed")
        self.assertEqual(len(records), 2)
        self.assertEqual(len(result["bursts"]), 2)
        self.assertEqual(len(call_log.calls), 2)

    def test_runner_exception_is_retained_as_a_bounded_record(self):
        persist_records, persist = collect_persist()
        with mock.patch.object(
                gpu_profile.measure, "run_burst",
                side_effect=RuntimeError("raw runner text")):
            result = gpu_profile.run_gpu_profile(
                lambda concurrency: [CallLog().sender()],
                canonical_validator,
                persist,
                run_id="gpu-run",
                owner_pid=123,
                deadline_seconds=600,
            )
        self.assertEqual(result["stop_reason"], "runner_error")
        self.assertEqual(len(persist_records), 1)
        self.assertEqual(persist_records[0]["error_class"], "runner_error")
        self.assertEqual(persist_records[0]["fault"], "fault_runtime")
        self.assertIsNone(persist_records[0]["burst"])
        self.assertNotIn("raw runner text", json.dumps(result))
        self.assertEqual(result["completed_bursts"], 0)

    def test_sender_factory_failure_stops_before_any_call(self):
        persist_records, persist = collect_persist()
        result = gpu_profile.run_gpu_profile(
            lambda concurrency: (_ for _ in ()).throw(RuntimeError("factory")),
            canonical_validator,
            persist,
            run_id="gpu-run",
            owner_pid=123,
            deadline_seconds=600,
        )
        self.assertEqual(result["stop_reason"], "runner_error")
        self.assertEqual(persist_records, [])
        self.assertEqual(result["completed_bursts"], 0)


class CorrelationTests(unittest.TestCase):
    def test_correlation_uses_only_owner_samples_inside_transport_windows(self):
        result = synthetic_profile_result()
        correlation = gpu_profile.correlate_gpu_profile(
            result,
            synthetic_samples(),
            expected_run_id="gpu-run",
            expected_owner_pid=123,
        )
        counts = correlation["sample_counts"]
        self.assertEqual(counts["received"], 34)
        self.assertEqual(counts["schema_invalid"], 1)
        self.assertEqual(counts["run_mismatch"], 1)
        self.assertEqual(counts["crossworker"], 1)
        self.assertEqual(counts["duplicate"], 1)
        self.assertEqual(counts["clock_anomaly"], 1)
        self.assertEqual(counts["accepted"], 29)
        self.assertEqual(counts["unavailable"], 1)
        self.assertEqual(counts["usable"], 28)
        self.assertEqual(counts["active"], 26)
        self.assertEqual(counts["inactive"], 2)
        self.assertEqual(correlation["scope"], "device_global")
        self.assertEqual(correlation["workers"], 8)
        self.assertFalse(correlation["identity"]["consistent"])
        self.assertEqual(correlation["identity"]["crossworker_count"], 1)
        case_one, case_two, case_three, case_four = correlation["cases"][:4]
        self.assertEqual(case_one["active_sample_count"], 12)
        self.assertEqual(case_one["overlapping_sample_count"], 13)
        self.assertEqual(case_one["transport_duration_seconds"], 19.0)
        self.assertEqual(case_one["expected_sample_count_at_one_hz"], 19)
        self.assertAlmostEqual(case_one["coverage_fraction"], 12 / 19)
        self.assertEqual(case_one["gpu_activity_percent"]["count"], 12)
        self.assertEqual(case_one["gpu_activity_percent"]["mean"], 50.0)
        self.assertEqual(case_one["gpu_activity_percent"]["min"], 0)
        self.assertEqual(case_one["gpu_activity_percent"]["max"], 100)
        self.assertEqual(
            case_one["memory_controller_activity_percent"]["mean"], 60.0)
        self.assertEqual(case_one["power_milliwatts"]["count"], 11)
        self.assertEqual(case_two["gpu_activity_percent"]["count"], 12)
        self.assertEqual(case_two["gpu_activity_percent"]["mean"], 100.0)
        self.assertEqual(case_three["active_sample_count"], 2)
        self.assertIsNone(case_three["gpu_activity_percent"])
        self.assertIsNone(case_three["power_milliwatts"])
        self.assertEqual(case_three["gpu_quantitative_reason"],
                         "insufficient_active_samples")
        self.assertEqual(case_four["active_sample_count"], 0)
        self.assertIsNone(case_four["gpu_activity_percent"])
        self.assertEqual(case_one["latency"]["marker"], 1)
        self.assertEqual(case_four["latency"]["marker"], 4)
        overall = correlation["overall"]
        self.assertEqual(overall["active_sample_count"], 26)
        self.assertEqual(overall["gpu_activity_percent"]["count"], 26)
        self.assertIn("sampler_interval_is_not_nvml_averaging_window",
                      correlation["limitations"])
        self.assertIn("samples_are_device_global_not_per_worker",
                      correlation["limitations"])

    def test_raw_gpu_worker_identity_must_match_profile_before_correlation(self):
        result = synthetic_profile_result()
        mismatched = gpu_sample(2_000, workers=12)
        correlation = gpu_profile.correlate_gpu_profile(
            result, [mismatched], expected_run_id="gpu-run",
            expected_owner_pid=123, expected_workers=8)
        self.assertEqual(correlation["sample_counts"]["worker_mismatch"], 1)
        self.assertEqual(correlation["sample_counts"]["accepted"], 0)
        self.assertFalse(correlation["identity"]["consistent"])
        with self.assertRaisesRegex(ValueError, "profile identity mismatch"):
            gpu_profile.correlate_gpu_profile(
                result, [], expected_run_id="gpu-run", expected_owner_pid=123,
                expected_workers=12)

    def test_insufficient_or_absent_samples_leave_gpu_unavailable_not_zero(self):
        result = synthetic_profile_result()
        correlation = gpu_profile.correlate_gpu_profile(
            result,
            [],
            expected_run_id="gpu-run",
            expected_owner_pid=123,
        )
        self.assertEqual(correlation["sample_counts"]["active"], 0)
        self.assertIsNone(correlation["overall"]["gpu_activity_percent"])
        self.assertEqual(
            correlation["overall"]["gpu_quantitative_reason"],
            "insufficient_active_samples",
        )
        for case in correlation["cases"]:
            self.assertIsNone(case["gpu_activity_percent"])
            self.assertIsNone(
                case["memory_controller_activity_percent"])
            self.assertIn("latency", case)
        self.assertEqual(correlation["cases"][0]["latency"]["marker"], 1)

    def test_profile_identity_and_structure_are_validated(self):
        result = synthetic_profile_result()
        for run_id, owner_pid in (("other-run", 123), ("gpu-run", 999)):
            with self.subTest(run_id=run_id, owner_pid=owner_pid):
                with self.assertRaisesRegex(ValueError, "profile identity mismatch"):
                    gpu_profile.correlate_gpu_profile(
                        result,
                        [],
                        expected_run_id=run_id,
                        expected_owner_pid=owner_pid,
                    )
        broken = dict(result)
        broken["workers"] = 8.0
        with self.assertRaisesRegex(ValueError, "profile identity mismatch"):
            gpu_profile.correlate_gpu_profile(
                broken, [], expected_run_id="gpu-run", expected_owner_pid=123)
        broken = dict(result)
        broken["cases"] = list(result["cases"])
        broken["cases"][0] = dict(broken["cases"][0], workers=8.0)
        with self.assertRaisesRegex(ValueError, "profile case plan"):
            gpu_profile.correlate_gpu_profile(
                broken, [], expected_run_id="gpu-run", expected_owner_pid=123)
        broken = dict(result)
        broken["cases"] = list(result["cases"])
        latency = dict(broken["cases"][0]["latency"], model_count=8.0)
        broken["cases"][0] = dict(broken["cases"][0], latency=latency)
        with self.assertRaisesRegex(ValueError, "profile case latency worker identity"):
            gpu_profile.correlate_gpu_profile(
                broken, [], expected_run_id="gpu-run", expected_owner_pid=123)
        broken = dict(result)
        broken["cases"] = list(result["cases"])[:2]
        with self.assertRaisesRegex(ValueError, "fixed case plan"):
            gpu_profile.correlate_gpu_profile(
                broken, [], expected_run_id="gpu-run", expected_owner_pid=123)
        broken = dict(result)
        broken["bursts"] = [{
            "case_index": 1,
            "case_concurrency": 2,
            "burst": {"client_concurrency": 2, "requests": []},
        }]
        with self.assertRaisesRegex(ValueError, "burst case identity mismatch"):
            gpu_profile.correlate_gpu_profile(
                broken, [], expected_run_id="gpu-run", expected_owner_pid=123)
        for run_id in ("", "../bad", "bad/run"):
            with self.assertRaises(ValueError):
                gpu_profile.correlate_gpu_profile(
                    result, [], expected_run_id=run_id, expected_owner_pid=123)
        with self.assertRaises(ValueError):
            gpu_profile.correlate_gpu_profile(
                result, [], expected_run_id="gpu-run", expected_owner_pid=0)
        for workers in (1, 12.0, True, "8"):
            with self.subTest(expected_workers=workers), self.assertRaises(ValueError):
                gpu_profile.correlate_gpu_profile(
                    result, [], expected_run_id="gpu-run", expected_owner_pid=123,
                    expected_workers=workers)
        with self.assertRaises(TypeError):
            gpu_profile.correlate_gpu_profile(
                [], [], expected_run_id="gpu-run", expected_owner_pid=123)

    def test_line_parser_counts_noise_and_invalid_prefix_lines(self):
        writes = []
        for sample in synthetic_samples()[:3]:
            gpu_monitor.emit_profile_record(
                sample, write=lambda descriptor, line: writes.append(line.decode()))
        parsed = gpu_profile.parse_gpu_profile_lines([
            "unrelated service output\n",
            *writes,
            gpu_monitor.PROFILE_PREFIX + "{\n",
        ])
        self.assertEqual(parsed["ignored_line_count"], 1)
        self.assertEqual(parsed["invalid_line_count"], 1)
        self.assertEqual(len(parsed["samples"]), 3)
        result = synthetic_profile_result()
        correlation = gpu_profile.correlate_gpu_profile(
            result,
            parsed,
            expected_run_id="gpu-run",
            expected_owner_pid=123,
        )
        self.assertEqual(correlation["sample_counts"]["invalid_line_count"], 1)
        self.assertEqual(correlation["sample_counts"]["ignored_line_count"], 1)
        raw_correlation = gpu_profile.correlate_gpu_profile(
            result,
            writes,
            expected_run_id="gpu-run",
            expected_owner_pid=123,
        )
        self.assertEqual(raw_correlation["sample_counts"]["received"], 3)
        self.assertEqual(raw_correlation["sample_counts"]["accepted"], 3)
        parsed_mismatch = gpu_profile.parse_gpu_profile_lines(
            writes, expected_workers=12)
        self.assertEqual(parsed_mismatch["samples"], [])
        self.assertEqual(parsed_mismatch["invalid_line_count"], 3)
        for workers in (4, 8.0, True, "8"):
            with self.subTest(expected_workers=workers), self.assertRaises(ValueError):
                gpu_profile.parse_gpu_profile_lines(writes, expected_workers=workers)

    def test_burst_classifier_keeps_expected_classes_and_marks_serious_faults(self):
        def burst(rows):
            return {"client_concurrency": len(rows), "requests": rows}

        self.assertIsNone(gpu_profile._burst_fault(burst([
            {"status": 429, "failure_class": "http_status"},
        ])))
        self.assertIsNone(gpu_profile._burst_fault(burst([
            {"status": None, "failure_class": "timeout"},
        ])))
        self.assertEqual(gpu_profile._burst_fault(burst([
            {"status": 503, "failure_class": "http_status"},
        ])), "fault_5xx")
        self.assertEqual(gpu_profile._burst_fault(burst([
            {"status": 200, "failure_class": "invalid_200"},
        ])), "fault_oracle")
        self.assertEqual(gpu_profile._burst_fault(burst([
            {"status": 200, "failure_class": "measurement_error"},
        ])), "fault_runtime")
        self.assertEqual(gpu_profile._burst_fault(burst([
            {"status": None, "failure_class": "not_started"},
        ])), "fault_runtime")
        self.assertEqual(gpu_profile._burst_fault({}), "fault_runtime")


if __name__ == "__main__":
    unittest.main()
