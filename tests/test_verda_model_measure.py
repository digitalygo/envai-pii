import copy
import json
import math
import threading
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from tools.verda_model_experiment import measure


BODY = b'{"fixed":"opaque synthetic body"}'
RESPONSE_BODY = b"canonicalized synthetic response"
RESPONSE_DIGEST = "a" * 64


class FakeResponse:
    def __init__(self, status=200, body=RESPONSE_BODY):
        self.status = status
        self.body = body


class CountingClock:
    def __init__(self, step=0.25):
        self._step = step
        self._value = 0.0
        self._lock = threading.Lock()
        self.calls = 0

    def __call__(self):
        with self._lock:
            value = self._value
            self._value += self._step
            self.calls += 1
            return value


class VerdaMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.validator_calls = []

    def validate(self, response_body):
        self.validator_calls.append(response_body)
        return RESPONSE_DIGEST

    def test_supported_concurrency_choices_call_exactly_once_with_same_body(self):
        for concurrency in measure.CONCURRENCY_CHOICES:
            with self.subTest(concurrency=concurrency):
                calls = []
                sender_list = [
                    lambda supplied_body, timeout, index=index: calls.append(
                        (index, supplied_body, timeout)
                    ) or FakeResponse()
                    for index in range(concurrency)
                ]
                result = measure.run_burst(
                    sender_list,
                    BODY,
                    self.validate,
                    timeout=12.5,
                    model_count=4,
                    clock=CountingClock(),
                )
                self.assertEqual(len(calls), concurrency)
                self.assertEqual({call[0] for call in calls}, set(range(concurrency)))
                self.assertTrue(all(call[1] is BODY for call in calls))
                self.assertEqual({call[2] for call in calls}, {12.5})
                self.assertEqual(result["client_concurrency"], concurrency)
                self.assertEqual(result["model_count"], 4)
                self.assertEqual(result["attempts"], concurrency)
                self.assertEqual(result["started_count"], concurrency)
                self.assertEqual(result["success_count"], concurrency)
                self.assertEqual(
                    [row["request_id"] for row in result["requests"]],
                    list(range(1, concurrency + 1)),
                )
                self.assertTrue(all(row["body_sent_sha256"] for row in result["requests"]))
                json.dumps(result, allow_nan=False)

    def test_all_senders_enter_before_any_response_and_overlap_is_measured(self):
        concurrency = 4
        all_entered = threading.Event()
        release = threading.Event()
        lock = threading.Lock()
        entered = []

        def sender(index):
            def send(_body, _timeout):
                with lock:
                    entered.append(index)
                    if len(entered) == concurrency:
                        all_entered.set()
                if not release.wait(3):
                    raise TimeoutError("opaque test timeout detail")
                return FakeResponse()
            return send

        def release_when_ready():
            if all_entered.wait(3):
                release.set()

        releaser = threading.Thread(target=release_when_ready)
        releaser.start()
        result = measure.run_burst(
            [sender(index) for index in range(concurrency)], BODY, self.validate
        )
        releaser.join(3)
        self.assertFalse(releaser.is_alive())
        self.assertEqual(len(entered), concurrency)
        self.assertEqual(result["peak_client_overlap"], concurrency)
        self.assertGreaterEqual(result["launch_spread_seconds"], 0.0)
        self.assertIsNotNone(result["group_elapsed_seconds"])
        self.assertEqual(result["success_count"], concurrency)
        self.assertFalse(any(thread.name.startswith("verda-burst-") for thread in threading.enumerate()))

    def test_group_elapsed_is_captured_before_validation(self):
        clock = CountingClock()

        def validating(response_body):
            self.validator_calls.append(response_body)
            clock()
            clock()
            return RESPONSE_DIGEST

        result = measure.run_burst(
            [lambda _body, _timeout: FakeResponse()], BODY, validating, clock=clock
        )
        self.assertEqual(clock.calls, 5)
        self.assertEqual(result["requests"][0]["duration_seconds"], 0.25)
        self.assertEqual(result["group_elapsed_seconds"], 0.5)

    def test_model_count_choices_are_independent_of_client_concurrency(self):
        self.assertEqual(measure.MODEL_COUNT_CHOICES, (1, 2, 4, 8, 12, 16))
        for model_count in measure.MODEL_COUNT_CHOICES:
            with self.subTest(model_count=model_count):
                result = measure.run_burst(
                    [lambda _body, _timeout: FakeResponse()],
                    BODY,
                    self.validate,
                    model_count=model_count,
                    clock=CountingClock(),
                )
                self.assertEqual(result["client_concurrency"], 1)
                self.assertEqual(result["model_count"], model_count)

    def test_non_200_statuses_are_retained_without_validation_or_retry(self):
        for status in (429, 503, 504):
            with self.subTest(status=status):
                calls = []
                result = measure.run_burst(
                    [lambda _body, _timeout, status=status: calls.append(status)
                     or FakeResponse(status, b"must not be stored")],
                    BODY,
                    self.validate,
                    clock=CountingClock(),
                )
                self.assertEqual(calls, [status])
                self.assertEqual(self.validator_calls, [])
                self.assertEqual(result["requests"][0]["status"], status)
                self.assertEqual(result["requests"][0]["failure_class"], "http_status")
                self.assertEqual(result["status_counts"], {str(status): 1})
                self.assertEqual(result["failure_counts"], {"http_status": 1})

    def test_success_and_all_started_latency_means_are_separate(self):
        result = measure.run_burst(
            [
                lambda _body, _timeout: FakeResponse(200),
                lambda _body, _timeout: FakeResponse(503),
            ],
            BODY,
            self.validate,
        )
        rows = result["requests"]
        successful = [row for row in rows if row["validation_ok"]]
        all_latencies = [row["duration_seconds"] for row in rows]
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["mean_success_latency_seconds"], successful[0]["duration_seconds"])
        self.assertAlmostEqual(
            result["mean_all_latency_seconds"], math.fsum(all_latencies) / len(all_latencies)
        )
        self.assertEqual(result["all_started_latency_seconds"]["count"], 2)

    def test_timeout_and_generic_sender_exceptions_are_fixed_and_not_retried(self):
        cases = (
            (TimeoutError("opaque credential-like timeout detail"), "timeout"),
            (RuntimeError("opaque response body detail"), "transport_error"),
        )
        for raised, failure_class in cases:
            with self.subTest(failure_class=failure_class):
                calls = []

                def sender(_body, _timeout):
                    calls.append(1)
                    raise raised

                result = measure.run_burst([sender], BODY, self.validate, clock=CountingClock())
                self.assertEqual(calls, [1])
                self.assertEqual(result["requests"][0]["failure_class"], failure_class)
                self.assertEqual(result["requests"][0]["status"], None)
                self.assertEqual(self.validator_calls, [])
                encoded = json.dumps(result, allow_nan=False)
                self.assertNotIn("opaque", encoded)
                self.assertNotIn("credential-like", encoded)

    def test_invalid_200_is_not_softened_or_logged(self):
        invalid_validators = (
            lambda _body: "not-a-digest",
            lambda _body: "A" * 64,
            lambda _body: (_ for _ in ()).throw(ValueError("secret response text")),
        )
        for validator in invalid_validators:
            with self.subTest(validator=validator):
                result = measure.run_burst(
                    [lambda _body, _timeout: FakeResponse(200, b"private plaintext")],
                    BODY,
                    validator,
                    clock=CountingClock(),
                )
                row = result["requests"][0]
                self.assertEqual(row["status"], 200)
                self.assertEqual(row["failure_class"], "invalid_200")
                self.assertFalse(row["validation_ok"])
                self.assertIsNone(row["canonical_response_sha256"])
                self.assertEqual(result["success_count"], 0)
                encoded = json.dumps(result, allow_nan=False)
                self.assertNotIn("private plaintext", encoded)
                self.assertNotIn("secret response text", encoded)

    def test_validator_hash_is_the_only_response_material_recorded(self):
        result = measure.run_burst(
            [lambda _body, _timeout: FakeResponse()], BODY, self.validate,
            clock=CountingClock(),
        )
        row = result["requests"][0]
        self.assertEqual(self.validator_calls, [RESPONSE_BODY])
        self.assertEqual(row["canonical_response_sha256"], RESPONSE_DIGEST)
        self.assertNotIn("canonicalized synthetic response", json.dumps(result))
        self.assertNotIn("authorization", json.dumps(result).lower())

    def test_run_rounds_aggregates_all_three_bursts_by_request_latency(self):
        clock_values = iter((0, 0, 1, 2, 2, 4, 5, 5, 8))
        clock = lambda: next(clock_values)
        calls = []

        def sender(_body, _timeout):
            calls.append(1)
            return FakeResponse()

        result = measure.run_rounds(
            [sender], BODY, self.validate, model_count=2, clock=clock
        )
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["round_count"], 3)
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(result["success_count"], 3)
        self.assertEqual(result["burst_elapsed_seconds"], [1.0, 2.0, 3.0])
        self.assertEqual(result["processing_elapsed_seconds_sum"], 6.0)
        self.assertEqual(result["mean_success_latency_seconds"], 2.0)
        self.assertEqual(result["mean_all_latency_seconds"], 2.0)
        self.assertEqual(result["successes_per_processing_second"], 0.5)
        self.assertEqual(result["model_count"], 2)
        self.assertEqual(len(result["rounds"]), 3)
        self.assertEqual([item["burst_index"] for item in result["rounds"]], [1, 2, 3])
        json.dumps(result, allow_nan=False)

    def test_round_summary_uses_peak_group_elapsed_not_summed_request_latency(self):
        rounds = []
        for _ in range(3):
            entered = threading.Event()
            both = 0
            both_lock = threading.Lock()
            per_round_gate = threading.Event()

            def build_sender():
                def send(_body, _timeout):
                    nonlocal both
                    with both_lock:
                        both += 1
                        if both == 2:
                            entered.set()
                    per_round_gate.wait(2)
                    return FakeResponse()
                return send

            per_round_senders = [build_sender(), build_sender()]
            releaser = threading.Thread(target=lambda: (entered.wait(2), per_round_gate.set()))
            releaser.start()
            rounds.append(measure.run_burst(per_round_senders, BODY, self.validate))
            releaser.join(2)
            self.assertFalse(releaser.is_alive())

        summary = measure.summarize_rounds(rounds)
        expected_mean = math.fsum(
            row["duration_seconds"]
            for burst in rounds
            for row in burst["requests"]
            if row["failure_class"] is None
        ) / summary["success_count"]
        expected_rps = summary["success_count"] / math.fsum(
            burst["group_elapsed_seconds"] for burst in rounds
        )
        self.assertAlmostEqual(summary["mean_success_latency_seconds"], expected_mean)
        self.assertAlmostEqual(summary["successes_per_processing_second"], expected_rps)
        self.assertGreater(summary["successes_per_processing_second"], 0)
        self.assertEqual(summary["attempts"], 6)

    def test_nearest_rank_percentiles_and_empty_samples(self):
        stats = measure._latency_statistics([1.0, 2.0, 3.0, 100.0])
        self.assertEqual(stats["p50"], 2.0)
        self.assertEqual(stats["p95"], 100.0)
        self.assertEqual(stats["min"], 1.0)
        self.assertEqual(stats["max"], 100.0)
        self.assertEqual(stats["mean"], 26.5)
        self.assertEqual(
            measure._latency_statistics([]),
            {"count": 0, "mean": None, "p50": None, "p95": None, "min": None, "max": None},
        )

    def test_preparation_failure_retains_every_not_started_row_without_calls(self):
        class UnstartableThread:
            def __init__(self, *args, **kwargs):
                self.name = kwargs.get("name", "unstartable")

            def start(self):
                raise RuntimeError("private setup detail")

        calls = []
        with patch.object(measure.threading, "Thread", UnstartableThread):
            result = measure.run_burst(
                [lambda _body, _timeout: calls.append(1) or FakeResponse()] * 2,
                BODY,
                self.validate,
                clock=CountingClock(),
            )
        self.assertTrue(result["preparation_failed"])
        self.assertEqual(calls, [])
        self.assertEqual(result["planned_count"], 2)
        self.assertEqual(result["attempts"], 0)
        self.assertEqual(result["not_started_count"], 2)
        self.assertEqual(result["failure_counts"], {"not_started": 2})
        self.assertEqual([row["request_id"] for row in result["requests"]], [1, 2])
        self.assertTrue(all(row["status"] is None for row in result["requests"]))

    def test_invalid_release_clock_marks_all_rows_not_started(self):
        calls = []
        result = measure.run_burst(
            [lambda _body, _timeout: calls.append(1) or FakeResponse()],
            BODY,
            self.validate,
            clock=lambda: math.nan,
        )
        self.assertEqual(calls, [])
        self.assertEqual(result["started_count"], 0)
        self.assertEqual(result["not_started_count"], 1)
        self.assertEqual(result["requests"][0]["failure_class"], "not_started")

    def test_input_validation_rejects_unsupported_cases_and_nonfinite_values(self):
        valid_sender = lambda _body, _timeout: FakeResponse()
        invalid_calls = (
            lambda: measure.run_burst([valid_sender] * 3, BODY, self.validate),
            lambda: measure.run_burst([valid_sender], "not-bytes", self.validate),
            lambda: measure.run_burst([None], BODY, self.validate),
            lambda: measure.run_burst([valid_sender], BODY, self.validate, timeout=0),
            lambda: measure.run_burst([valid_sender], BODY, self.validate, timeout=math.nan),
            lambda: measure.run_burst([valid_sender], BODY, self.validate, timeout=math.inf),
            lambda: measure.run_burst([valid_sender], BODY, self.validate, timeout=True),
            lambda: measure.run_burst([valid_sender], BODY, self.validate, model_count=3),
            lambda: measure.run_burst([valid_sender], BODY, self.validate, model_count=12.0),
            lambda: measure.run_burst([valid_sender], BODY, self.validate, model_count=True),
            lambda: measure.run_burst([valid_sender], BODY, None),
        )
        for operation in invalid_calls:
            with self.subTest(operation=operation):
                with self.assertRaises((TypeError, ValueError)):
                    operation()

    def test_summarizer_rejects_missing_rounds_mixed_cases_and_nan_rows(self):
        burst = measure.run_burst(
            [lambda _body, _timeout: FakeResponse()], BODY, self.validate,
            clock=CountingClock(),
        )
        with self.assertRaises(ValueError):
            measure.summarize_rounds([burst, burst])
        other_case = measure.run_burst(
            [lambda _body, _timeout: FakeResponse()] * 2, BODY, self.validate,
            clock=CountingClock(),
        )
        with self.assertRaises(ValueError):
            measure.summarize_rounds([burst, burst, other_case])
        malformed = dict(burst)
        malformed["requests"] = [dict(burst["requests"][0])]
        malformed["requests"][0]["duration_seconds"] = math.nan
        with self.assertRaises(ValueError):
            measure.summarize_rounds([malformed, burst, burst])

    def test_malformed_http_response_objects_are_classified_without_payload_access(self):
        class BrokenStatus:
            @property
            def status(self):
                raise RuntimeError("private status detail")

        class InvalidBody:
            status = 200
            body = "private response text"

        class BrokenBody:
            status = 200

            @property
            def body(self):
                raise RuntimeError("private body detail")

        for response, expected_status, failure_class in (
            (BrokenStatus(), None, "transport_error"),
            (FakeResponse("200"), None, "transport_error"),
            (InvalidBody(), 200, "invalid_200"),
            (BrokenBody(), 200, "invalid_200"),
        ):
            with self.subTest(failure_class=failure_class, expected_status=expected_status):
                result = measure.run_burst(
                    [lambda _body, _timeout, value=response: value],
                    BODY,
                    self.validate,
                    clock=CountingClock(),
                )
                self.assertEqual(result["requests"][0]["status"], expected_status)
                self.assertEqual(result["requests"][0]["failure_class"], failure_class)
                self.assertEqual(self.validator_calls, [])
                encoded = json.dumps(result, allow_nan=False)
                self.assertNotIn("private", encoded)

    def test_thread_constructor_failure_preserves_all_planned_rows(self):
        class UnconstructableThread:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("private thread setup detail")

        calls = []
        with patch.object(measure.threading, "Thread", UnconstructableThread):
            result = measure.run_burst(
                [lambda _body, _timeout: calls.append(1) or FakeResponse()],
                BODY,
                self.validate,
                clock=CountingClock(),
            )
        self.assertEqual(calls, [])
        self.assertTrue(result["preparation_failed"])
        self.assertEqual(result["planned_count"], 1)
        self.assertEqual(result["attempts"], 0)
        self.assertEqual(result["requests"][0]["failure_class"], "not_started")

    def test_bad_post_release_clock_keeps_the_started_outcome_unaggregated(self):
        samples = iter((0.0, math.nan, 1.0))
        calls = []

        def clock():
            return next(samples)

        result = measure.run_burst(
            [lambda _body, _timeout: calls.append(1) or FakeResponse()],
            BODY,
            self.validate,
            clock=clock,
        )
        row = result["requests"][0]
        self.assertEqual(calls, [1])
        self.assertTrue(row["started"])
        self.assertEqual(row["status"], 200)
        self.assertTrue(row["validation_ok"])
        self.assertEqual(row["failure_class"], "measurement_error")
        self.assertEqual(result["timing_incomplete_count"], 1)
        self.assertIsNone(result["mean_all_latency_seconds"])
        summary = measure.summarize_rounds([result, result, result])
        self.assertEqual(summary["attempts"], 3)
        self.assertEqual(summary["timing_incomplete_count"], 3)
        self.assertEqual(summary["success_count"], 0)
        self.assertIsNone(summary["processing_elapsed_seconds_sum"])
        self.assertEqual(len(summary["rounds"]), 3)

    def test_internal_validators_reject_inconsistent_records_and_bad_samples(self):
        burst = measure.run_burst(
            [lambda _body, _timeout: FakeResponse()],
            BODY,
            self.validate,
            clock=CountingClock(),
        )
        base_row = burst["requests"][0]
        bad_rows = []
        for field, value in (
            ("request_id", 0),
            ("started", 1),
            ("failure_class", ["invalid"]),
            ("failure_class", "not_started"),
            ("validation_ok", 1),
            ("status", "200"),
            ("timing_complete", 1),
            ("start_offset_seconds", math.nan),
            ("request_started_at_utc", "not-a-timestampZ"),
            ("transport_ended_at_utc", None),
            ("body_sent_sha256", "bad"),
            ("end_offset_seconds", -1),
            ("canonical_response_sha256", "bad"),
        ):
            row = copy.deepcopy(base_row)
            row[field] = value
            bad_rows.append(row)

        row = copy.deepcopy(base_row)
        row["status"] = None
        row["failure_class"] = "http_status"
        row["validation_ok"] = False
        row["canonical_response_sha256"] = None
        bad_rows.append(row)

        row = copy.deepcopy(base_row)
        row["status"] = 200
        row["failure_class"] = "transport_error"
        row["validation_ok"] = False
        row["canonical_response_sha256"] = None
        bad_rows.append(row)

        row = copy.deepcopy(base_row)
        row["failure_class"] = None
        row["status"] = 503
        bad_rows.append(row)

        row = copy.deepcopy(base_row)
        row["started"] = False
        row["failure_class"] = "http_status"
        bad_rows.append(row)

        for row in bad_rows:
            with self.subTest(row=row):
                with self.assertRaises((TypeError, ValueError)):
                    measure._validate_row(row)

        with self.assertRaises(TypeError):
            measure._validate_row(None)
        for invalid_timestamp in (None, "", "2026-10-27T00:00:00", "badZ"):
            self.assertFalse(measure._is_utc_timestamp(invalid_timestamp))
        self.assertTrue(measure._is_utc_timestamp("2026-10-27T00:00:00+00:00".replace("+00:00", "Z")))

    def test_burst_aggregator_rejects_dropped_or_mixed_data(self):
        burst = measure.run_burst(
            [lambda _body, _timeout: FakeResponse()], BODY, self.validate,
            clock=CountingClock(),
        )
        invalid_bursts = []
        for field, value in (
            ("client_concurrency", 3),
            ("model_count", 3),
            ("requests", ()),
            ("burst_index", 4),
            ("body_sha256", "bad"),
            ("preparation_failed", 1),
            ("group_elapsed_seconds", math.inf),
        ):
            invalid = copy.deepcopy(burst)
            invalid[field] = value
            invalid_bursts.append(invalid)

        invalid = copy.deepcopy(burst)
        invalid["requests"][0]["request_id"] = 2
        invalid_bursts.append(invalid)
        invalid = copy.deepcopy(burst)
        invalid["requests"][0]["body_sent_sha256"] = "b" * 64
        invalid_bursts.append(invalid)
        for invalid in invalid_bursts:
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    measure.summarize_rounds([invalid, burst, burst])

        with self.assertRaises(TypeError):
            measure.summarize_rounds([None, burst, burst])
        indexed = [copy.deepcopy(burst) for _ in range(3)]
        for index, item in enumerate(indexed, start=1):
            item["burst_index"] = index
        self.assertEqual(measure.summarize_rounds(indexed)["round_count"], 3)
        indexed[0]["burst_index"] = 2
        with self.assertRaises(ValueError):
            measure.summarize_rounds(indexed)

    def test_private_measurement_helpers_handle_invalid_samples(self):
        self.assertIsNone(measure._sample_clock(lambda: True))
        self.assertIsNone(measure._sample_clock(lambda: math.inf))
        self.assertIsNone(measure._sample_clock(lambda: (_ for _ in ()).throw(RuntimeError())))
        self.assertIsNone(measure._format_utc(None))
        self.assertTrue(measure._format_utc(datetime.now(timezone.utc)).endswith("Z"))
        self.assertEqual(measure._overlap_peak([]), 0)
        self.assertEqual(measure._overlap_peak([(1.0, 1.0)]), 0)
        self.assertEqual(measure._overlap_peak([(0.0, 2.0), (1.0, 3.0)]), 2)
        self.assertEqual(measure._count_failures([]), {})
        self.assertEqual(measure._count_statuses([]), {})
        for value in (True, "1", -1, math.nan):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    measure._optional_finite_nonnegative(value, "sample")

        row = measure._new_row(1)
        release_utc = datetime.now(timezone.utc)
        for args in (
            (None, 1.0, 0.0, release_utc),
            (0.0, None, 0.0, release_utc),
            (2.0, 1.0, 0.0, release_utc),
            (1.0, 2.0, None, release_utc),
            (1.0, 2.0, 0.0, None),
            (-1.0, 2.0, 0.0, release_utc),
            (1e20, 1e20, 0.0, release_utc),
        ):
            self.assertFalse(measure._set_timing(row, args[0], args[1], args[2], args[3]))

    def test_module_does_not_load_environment_or_http_clients(self):
        with open(measure.__file__, encoding="utf-8") as source_file:
            source = source_file.read()
        for forbidden in ("os.environ", "urllib", "httpx", "socket", "PII_API_TOKEN"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
