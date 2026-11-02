import ctypes
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
import uuid

from tools.verda_model_experiment import gpu_monitor, gpu_runtime


FIRST_UUID = "GPU-11111111-1111-1111-1111-111111111111"
SECOND_UUID = "GPU-22222222-2222-2222-2222-222222222222"
THIRD_UUID = "GPU-33333333-3333-3333-3333-333333333333"


class FakeFunction:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *arguments):
        return self.callback(*arguments)


class FakeClock:
    def __init__(self, value=1.0, step=0.001):
        self.value = value
        self.step = step

    def __call__(self):
        current = self.value
        self.value += self.step
        return current


class FakeNvml:
    def __init__(self, uuids=(FIRST_UUID, SECOND_UUID, THIRD_UUID), *,
                 gpu=0, memory=100, power=50000, power_limit=350000,
                 init_code=0, count_code=0, handle_code=0, uuid_code=0,
                 utilization_code=0, power_code=0, power_limit_code=0,
                 count_override=None, null_handle=False):
        self.uuids = tuple(uuids)
        self.gpu = gpu
        self.memory = memory
        self.power = power
        self.power_limit = power_limit
        self.init_code = init_code
        self.count_code = count_code
        self.handle_code = handle_code
        self.uuid_code = uuid_code
        self.utilization_code = utilization_code
        self.power_code = power_code
        self.power_limit_code = power_limit_code
        self.count_override = count_override
        self.null_handle = null_handle
        self.init_calls = 0
        self.shutdown_calls = 0
        self.uuid_calls = 0
        self.nvmlInit_v2 = FakeFunction(self._init)
        self.nvmlShutdown = FakeFunction(self._shutdown)
        self.nvmlDeviceGetCount_v2 = FakeFunction(self._count)
        self.nvmlDeviceGetHandleByIndex_v2 = FakeFunction(self._handle)
        self.nvmlDeviceGetUUID = FakeFunction(self._uuid)
        self.nvmlDeviceGetUtilizationRates = FakeFunction(self._utilization)
        self.nvmlDeviceGetPowerUsage = FakeFunction(self._power)
        self.nvmlDeviceGetPowerManagementLimit = FakeFunction(self._power_limit)

    def _init(self):
        self.init_calls += 1
        return self.init_code

    def _shutdown(self):
        self.shutdown_calls += 1
        return 0

    def _count(self, pointer):
        pointer._obj.value = (
            len(self.uuids) if self.count_override is None else self.count_override)
        return self.count_code

    def _handle(self, index, pointer):
        pointer._obj.value = 0 if self.null_handle else 1000 + int(index.value)
        return self.handle_code

    def _uuid(self, handle, buffer, length):
        self.uuid_calls += 1
        if self.uuid_code:
            return self.uuid_code
        index = int(getattr(handle, "value", handle)) - 1000
        raw = self.uuids[index]
        if raw is None:
            return 1
        if isinstance(raw, str):
            raw = raw.encode("ascii")
        buffer.value = raw[:max(0, int(getattr(length, "value", length)) - 1)]
        return 0

    def _utilization(self, handle, pointer):
        if self.utilization_code:
            return self.utilization_code
        pointer._obj.gpu = self.gpu
        pointer._obj.memory = self.memory
        return 0

    def _power(self, handle, pointer):
        if self.power_code:
            return self.power_code
        pointer._obj.value = self.power
        return 0

    def _power_limit(self, handle, pointer):
        if self.power_limit_code:
            return self.power_limit_code
        pointer._obj.value = self.power_limit
        return 0


def make_sampler(library, requested_uuid=THIRD_UUID, *,
                 clock=None, wall_clock=None):
    return gpu_monitor.NvmlSampler(
        requested_uuid,
        library_factory=lambda name: library,
        clock=clock or FakeClock(step=0.01),
        wall_clock=wall_clock or (lambda: 1_700_000_000.123),
    )


def sample_payload(**overrides):
    payload = {
        "run_id": "gpu-run",
        "owner_pid": 123,
        "workers": 8,
        "epoch_ms": 1_700_000_000_000,
        "monotonic_ms": 1_000,
        "read_duration_ms": 1,
        "gpu_activity_percent": 0,
        "memory_controller_activity_percent": 100,
        "power_milliwatts": 50_000,
        "power_limit_milliwatts": 350_000,
        "gpu_activity_reason": None,
        "memory_controller_activity_reason": None,
        "power_reason": None,
        "power_limit_reason": None,
    }
    payload.update(overrides)
    return payload


def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class FakeCudaUuid:
    def __init__(self, octets):
        self._octets = octets

    @property
    def bytes(self):
        return self._octets


class RaisingCudaUuid:
    @property
    def bytes(self):
        raise RuntimeError("unreadable")


class ForgedStringCudaUuid:
    def __str__(self):
        return THIRD_UUID


class UuidTests(unittest.TestCase):
    def test_uuid_forms_normalize_to_one_canonical_gpu_identity(self):
        expected = THIRD_UUID
        candidates = (
            THIRD_UUID,
            THIRD_UUID.removeprefix("GPU-"),
            THIRD_UUID.lower(),
            THIRD_UUID.removeprefix("GPU-").upper(),
            THIRD_UUID.encode("ascii"),
            uuid.UUID(THIRD_UUID.removeprefix("GPU-")),
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                self.assertEqual(gpu_monitor.normalize_uuid(candidate), expected)

    def test_uuid_rejects_missing_mig_malformed_and_non_text_values(self):
        for candidate in (
            None,
            "",
            "MIG-GPU-11111111-1111-1111-1111-111111111111",
            "GPU-not-a-uuid",
            "{" + THIRD_UUID + "}",
            123,
            object(),
            b"\xff",
        ):
            with self.subTest(candidate=candidate):
                self.assertIsNone(gpu_monitor.normalize_uuid(candidate))

    def test_cuda_uuid_bytes_roundtrip_to_canonical_gpu_identity(self):
        expected = THIRD_UUID
        raw = uuid.UUID(THIRD_UUID.removeprefix("GPU-")).bytes
        candidates = (
            FakeCudaUuid(list(raw)),
            FakeCudaUuid(tuple(raw)),
            FakeCudaUuid(raw),
            FakeCudaUuid(bytearray(raw)),
            raw,
            bytearray(raw),
        )
        for candidate in candidates:
            with self.subTest(candidate=type(candidate).__name__):
                self.assertEqual(gpu_monitor.normalize_uuid(candidate), expected)

    def test_cuda_uuid_raw_bytes_preserve_zero_full_and_high_bit_values(self):
        cases = (
            (bytes(16), "GPU-00000000-0000-0000-0000-000000000000"),
            (b"\xff" * 16, "GPU-FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"),
            (bytes.fromhex("800102030405060708090a0b0c0d0e0f"),
             "GPU-80010203-0405-0607-0809-0A0B0C0D0E0F"),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw.hex()):
                self.assertEqual(gpu_monitor.normalize_uuid(raw), expected)
                self.assertEqual(
                    gpu_monitor.normalize_uuid(FakeCudaUuid(list(raw))),
                    expected,
                )

    def test_cuda_uuid_rejects_malformed_bytes_and_forged_strings(self):
        valid = list(uuid.UUID(THIRD_UUID.removeprefix("GPU-")).bytes)
        for index, candidate in enumerate((
            FakeCudaUuid(valid[:-1]),
            FakeCudaUuid(valid + [0]),
            FakeCudaUuid([str(item) for item in valid]),
            FakeCudaUuid([*valid[:-1], 1.0]),
            FakeCudaUuid([*valid[:-1], True]),
            FakeCudaUuid([*valid[:-1], -1]),
            FakeCudaUuid([*valid[:-1], 256]),
            FakeCudaUuid(THIRD_UUID),
            valid,
            ForgedStringCudaUuid(),
            RaisingCudaUuid(),
            b"\x00" * 15,
            b"\x00" * 17,
            bytearray(b"\x00" * 15),
        )):
            with self.subTest(case=index):
                self.assertIsNone(gpu_monitor.normalize_uuid(candidate))


class SamplerOpenTests(unittest.TestCase):
    def test_sampler_resolves_cuda_zero_uuid_not_host_index_zero(self):
        library = FakeNvml()
        sampler = make_sampler(library)
        self.assertIsNone(sampler.open())
        self.assertEqual(sampler._handle, 1002)
        self.assertIs(library.nvmlDeviceGetCount_v2.restype, ctypes.c_int)
        self.assertEqual(
            library.nvmlDeviceGetUtilizationRates.argtypes,
            [ctypes.c_void_p, ctypes.POINTER(gpu_monitor.NvmlUtilization)],
        )
        self.assertIs(
            library.nvmlDeviceGetUtilizationRates.restype, ctypes.c_int)
        self.assertEqual(library.nvmlDeviceGetUUID.argtypes, [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_char), ctypes.c_uint,
        ])

    def test_open_failures_are_bounded_and_release_initialized_library(self):
        def missing(name):
            library = FakeNvml()
            delattr(library, name)
            return library

        def unavailable_library(name):
            raise OSError()

        cases = (
            ("library", None, unavailable_library, "library_unavailable", 0),
            ("init-code", FakeNvml(init_code=1), None, "init_failed", 0),
            ("init-missing", missing("nvmlInit_v2"), None,
             "function_unsupported", 0),
            ("count-missing", missing("nvmlDeviceGetCount_v2"), None,
             "function_unsupported", 1),
            ("handle-missing", missing("nvmlDeviceGetHandleByIndex_v2"), None,
             "function_unsupported", 1),
            ("uuid-missing", missing("nvmlDeviceGetUUID"), None,
             "function_unsupported", 1),
            ("util-missing", missing("nvmlDeviceGetUtilizationRates"), None,
             "utilization_unavailable", 1),
            ("count-code", FakeNvml(count_code=1), None,
             "device_unavailable", 1),
            ("count-zero", FakeNvml(count_override=0), None,
             "device_unavailable", 1),
            ("count-large", FakeNvml(count_override=300), None,
             "device_unavailable", 1),
            ("null-handle", FakeNvml(null_handle=True), None,
             "uuid_unavailable", 1),
            ("uuid-code", FakeNvml(uuid_code=1), None,
             "uuid_unavailable", 1),
            ("uuid-unreadable", FakeNvml(uuids=(None, "bad")), None,
             "uuid_unavailable", 1),
            ("uuid-mismatch", FakeNvml(uuids=(FIRST_UUID, SECOND_UUID)), None,
             "uuid_mismatch", 1),
        )
        for name, library, factory, reason, shutdown_calls in cases:
            with self.subTest(case=name):
                sampler = gpu_monitor.NvmlSampler(
                    THIRD_UUID,
                    library_factory=(
                        factory or (lambda library_name, value=library: value)
                    ),
                )
                self.assertEqual(sampler.open(), reason)
                if library is not None:
                    self.assertEqual(library.shutdown_calls, shutdown_calls)
                sampler.close()

    def test_sampler_matches_cuda_uuid_bytes_at_remapped_nonzero_index(self):
        library = FakeNvml()
        sampler = make_sampler(
            library,
            requested_uuid=FakeCudaUuid(
                list(uuid.UUID(SECOND_UUID.removeprefix("GPU-")).bytes)),
        )
        self.assertIsNone(sampler.open())
        self.assertEqual(sampler._handle, 1001)
        sampler.close()

    def test_sampler_cuda_uuid_bytes_mismatch_and_unavailable_stay_explicit(self):
        requested = FakeCudaUuid(
            list(uuid.UUID(THIRD_UUID.removeprefix("GPU-")).bytes))
        sampler = make_sampler(
            FakeNvml(uuids=(FIRST_UUID, SECOND_UUID)),
            requested_uuid=requested,
        )
        self.assertEqual(sampler.open(), "uuid_mismatch")
        sampler.close()
        sampler = make_sampler(
            FakeNvml(uuids=(None, None)),
            requested_uuid=requested,
        )
        self.assertEqual(sampler.open(), "uuid_unavailable")
        sampler.close()

    def test_missing_requested_uuid_is_not_a_device_lookup(self):
        library = FakeNvml()
        sampler = make_sampler(library, requested_uuid=None)
        self.assertEqual(sampler.open(), "uuid_unavailable")
        self.assertEqual(library.init_calls, 0)
        sampler = make_sampler(library, requested_uuid="not-a-uuid")
        self.assertEqual(sampler.open(), "uuid_invalid")
        self.assertEqual(library.init_calls, 0)

    def test_open_is_idempotent_and_close_is_safe_without_shutdown(self):
        library = FakeNvml()
        sampler = make_sampler(library)
        self.assertIsNone(sampler.open())
        self.assertIsNone(sampler.open())
        self.assertEqual(library.init_calls, 1)
        sampler.close()
        sampler.close()
        self.assertEqual(library.shutdown_calls, 1)
        library = FakeNvml()
        del library.nvmlShutdown
        sampler = make_sampler(library)
        self.assertIsNone(sampler.open())
        sampler.close()
        library = FakeNvml()
        shutdown_calls = []

        def failing_shutdown():
            shutdown_calls.append(1)
            raise RuntimeError("driver")

        library.nvmlShutdown = FakeFunction(failing_shutdown)
        sampler = make_sampler(library)
        self.assertIsNone(sampler.open())
        sampler.close()
        self.assertEqual(shutdown_calls, [1])


class SamplerValueTests(unittest.TestCase):
    def test_genuine_zero_and_hundred_are_numeric_not_unavailable(self):
        library = FakeNvml(gpu=0, memory=100)
        sampler = make_sampler(library)
        self.assertIsNone(sampler.open())
        sample = sampler.sample()
        self.assertEqual(sample["gpu_activity_percent"], 0)
        self.assertEqual(sample["memory_controller_activity_percent"], 100)
        self.assertIsNone(sample["gpu_activity_reason"])
        self.assertIsNone(sample["memory_controller_activity_reason"])
        self.assertEqual(sample["epoch_ms"], 1_700_000_000_123)
        self.assertEqual(sample["monotonic_ms"], 1_000)
        self.assertEqual(sample["read_duration_ms"], 10)
        self.assertEqual(sample["power_milliwatts"], 50_000)
        self.assertEqual(sample["power_limit_milliwatts"], 350_000)

    def test_utilization_errors_and_out_of_bounds_are_explicit_null(self):
        library = FakeNvml(utilization_code=1)
        sampler = make_sampler(library)
        self.assertIsNone(sampler.open())
        sample = sampler.sample()
        self.assertIsNone(sample["gpu_activity_percent"])
        self.assertIsNone(sample["memory_controller_activity_percent"])
        self.assertEqual(sample["gpu_activity_reason"], "utilization_unavailable")
        self.assertEqual(
            sample["memory_controller_activity_reason"],
            "utilization_unavailable",
        )
        library = FakeNvml(gpu=101, memory=50)
        sampler = make_sampler(library)
        self.assertIsNone(sampler.open())
        sample = sampler.sample()
        self.assertIsNone(sample["gpu_activity_percent"])
        self.assertEqual(sample["gpu_activity_reason"], "utilization_invalid")
        self.assertEqual(sample["memory_controller_activity_percent"], 50)
        self.assertIsNone(sample["memory_controller_activity_reason"])

    def test_power_failures_are_separate_from_required_activity(self):
        library = FakeNvml(power_code=1, power_limit_code=1)
        sampler = make_sampler(library)
        self.assertIsNone(sampler.open())
        sample = sampler.sample()
        self.assertEqual(sample["gpu_activity_percent"], 0)
        self.assertEqual(sample["memory_controller_activity_percent"], 100)
        self.assertIsNone(sample["power_milliwatts"])
        self.assertEqual(sample["power_reason"], "power_unavailable")
        self.assertIsNone(sample["power_limit_milliwatts"])
        self.assertEqual(sample["power_limit_reason"], "power_limit_unavailable")
        library = FakeNvml()
        del library.nvmlDeviceGetPowerUsage
        del library.nvmlDeviceGetPowerManagementLimit
        sampler = make_sampler(library)
        self.assertIsNone(sampler.open())
        sample = sampler.sample()
        self.assertIsNone(sample["power_milliwatts"])
        self.assertIsNone(sample["power_limit_milliwatts"])
        self.assertEqual(sample["power_reason"], "power_unavailable")

    def test_unopened_sampler_returns_no_measurement(self):
        sampler = gpu_monitor.NvmlSampler(THIRD_UUID)
        self.assertIsNone(sampler.sample())


class SchemaTests(unittest.TestCase):
    def test_emitter_writes_only_the_closed_numeric_schema(self):
        writes = []
        self.assertTrue(gpu_monitor.emit_profile_record(
            sample_payload(),
            write=lambda descriptor, line: writes.append((descriptor, line)),
        ))
        self.assertEqual(len(writes), 1)
        descriptor, line = writes[0]
        self.assertEqual(descriptor, 1)
        text = line.decode("ascii")
        self.assertTrue(text.startswith(gpu_monitor.PROFILE_PREFIX))
        payload = json.loads(text.removeprefix(gpu_monitor.PROFILE_PREFIX))
        self.assertEqual(set(payload), gpu_monitor.PROFILE_FIELDS)
        self.assertEqual(payload["gpu_activity_percent"], 0)
        for forbidden in (
            "body", "headers", "request", "response", "env", "url",
            "exception", "secret", "environment",
        ):
            self.assertNotIn(forbidden, payload)

    def test_profile_worker_choices_keep_eight_as_default(self):
        self.assertEqual(gpu_monitor.PROFILE_WORKERS, 8)
        self.assertEqual(gpu_monitor.PROFILE_WORKER_CHOICES, (8, 12, 16))
        for workers in (8, 12, 16):
            with self.subTest(workers=workers):
                self.assertTrue(gpu_monitor.validate_profile_record(
                    sample_payload(workers=workers)))
        for workers in (0, 1, 2, 4, 7, 9, 11, 13, 15, 17, True, 8.0, "8", None):
            with self.subTest(rejected=workers):
                self.assertFalse(gpu_monitor.validate_profile_record(
                    sample_payload(workers=workers)))

    def test_emitter_rejects_extra_missing_unsafe_and_out_of_bounds_values(self):
        invalid = (
            sample_payload(body="secret"),
            sample_payload(gpu_activity_percent=101),
            sample_payload(gpu_activity_percent=None),
            sample_payload(gpu_activity_reason="raw exception text"),
            sample_payload(power_milliwatts=-1),
            sample_payload(workers=4),
            sample_payload(owner_pid=0),
            sample_payload(run_id="../run"),
            sample_payload(read_duration_ms=True),
            {key: value for key, value in sample_payload().items()
             if key != "run_id"},
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                writes = []
                self.assertFalse(gpu_monitor.emit_profile_record(
                    payload,
                    write=lambda descriptor, line: writes.append(line),
                ))
                self.assertEqual(writes, [])

    def test_parser_accepts_only_prefixed_valid_profile_lines(self):
        line = (gpu_monitor.PROFILE_PREFIX + json.dumps(
            sample_payload(), sort_keys=True, separators=(",", ":")) + "\n")
        self.assertEqual(
            gpu_monitor.parse_profile_line(line), sample_payload())
        self.assertIsNone(gpu_monitor.parse_profile_line("VERDA other\n"))
        for malformed in (
            gpu_monitor.PROFILE_PREFIX + "{",
            gpu_monitor.PROFILE_PREFIX + "[]",
            gpu_monitor.PROFILE_PREFIX + '{"run_id":"x"}',
            gpu_monitor.PROFILE_PREFIX + "x" * gpu_monitor.MAX_PROFILE_LINE_BYTES,
        ):
            with self.subTest(malformed=malformed[:60]):
                with self.assertRaisesRegex(ValueError, "invalid gpu profile line"):
                    gpu_monitor.parse_profile_line(malformed)


class FakeSampler:
    def __init__(self, samples=(), *, open_reason=None, block_event=None):
        self._samples = list(samples)
        self.open_reason = open_reason
        self.block_event = block_event
        self.open_calls = 0
        self.sample_calls = 0
        self.close_calls = 0
        self.entered = threading.Event()

    def open(self):
        self.open_calls += 1
        return self.open_reason

    def sample(self):
        self.sample_calls += 1
        if self.block_event is not None:
            self.entered.set()
            self.block_event.wait(2)
        if not self._samples:
            return {
                "epoch_ms": 1_700_000_000_000 + self.sample_calls,
                "monotonic_ms": 1_000 + self.sample_calls,
                "read_duration_ms": 1,
                "gpu_activity_percent": 0,
                "memory_controller_activity_percent": 100,
                "power_milliwatts": None,
                "power_limit_milliwatts": None,
                "gpu_activity_reason": None,
                "memory_controller_activity_reason": None,
                "power_reason": "power_unavailable",
                "power_limit_reason": "power_limit_unavailable",
            }
        return self._samples.pop(0)

    def close(self):
        self.close_calls += 1


class MonitorTests(unittest.TestCase):
    def test_monitor_emits_owner_scoped_samples_then_closes_once(self):
        sampler = FakeSampler()
        emitted = []
        first = threading.Event()

        def emit(payload):
            emitted.append(payload)
            first.set()

        monitor = gpu_monitor.GpuMonitor(
            run_id="gpu-run",
            owner_pid=321,
            cuda_uuid=THIRD_UUID,
            sampler_factory=lambda cuda_uuid: sampler,
            emit=emit,
            interval_seconds=0.01,
        )
        self.assertTrue(monitor.start())
        self.assertFalse(monitor.start())
        self.assertTrue(first.wait(1))
        self.assertTrue(monitor.stop())
        self.assertFalse(monitor.is_alive())
        self.assertEqual(sampler.open_calls, 1)
        self.assertEqual(sampler.close_calls, 1)
        self.assertEqual(emitted[0]["run_id"], "gpu-run")
        self.assertEqual(emitted[0]["owner_pid"], 321)
        self.assertEqual(emitted[0]["workers"], 8)

    def test_monitor_emits_the_real_worker_count_for_each_choice(self):
        for workers in (8, 12, 16):
            with self.subTest(workers=workers):
                sampler = FakeSampler()
                emitted = []
                first = threading.Event()

                def emit(payload):
                    emitted.append(payload)
                    first.set()

                monitor = gpu_monitor.GpuMonitor(
                    run_id="gpu-run",
                    owner_pid=321,
                    cuda_uuid=THIRD_UUID,
                    workers=workers,
                    sampler_factory=lambda cuda_uuid: sampler,
                    emit=emit,
                    interval_seconds=0.01,
                )
                self.assertTrue(monitor.start())
                self.assertTrue(first.wait(1))
                self.assertTrue(monitor.stop())
                self.assertEqual(emitted[0]["workers"], workers)
                self.assertEqual(sampler.close_calls, 1)

    def test_open_failure_emits_one_null_reason_and_stops(self):
        sampler = FakeSampler(open_reason="library_unavailable")
        emitted = []
        monitor = gpu_monitor.GpuMonitor(
            run_id="gpu-run",
            owner_pid=321,
            cuda_uuid=THIRD_UUID,
            sampler_factory=lambda cuda_uuid: sampler,
            emit=lambda payload: emitted.append(payload),
            interval_seconds=0.01,
        )
        monitor.start()
        self.assertTrue(wait_until(lambda: not monitor.is_alive()))
        self.assertEqual(len(emitted), 1)
        payload = emitted[0]
        self.assertIsNone(payload["gpu_activity_percent"])
        self.assertIsNone(payload["memory_controller_activity_percent"])
        self.assertEqual(payload["gpu_activity_reason"], "library_unavailable")
        self.assertEqual(payload["power_reason"], "library_unavailable")
        self.assertEqual(sampler.sample_calls, 0)
        self.assertEqual(sampler.close_calls, 1)

    def test_unknown_open_failure_reason_is_bounded(self):
        sampler = FakeSampler(open_reason="driver exception with secret")
        emitted = []
        monitor = gpu_monitor.GpuMonitor(
            run_id="gpu-run",
            owner_pid=321,
            cuda_uuid=THIRD_UUID,
            sampler_factory=lambda cuda_uuid: sampler,
            emit=lambda payload: emitted.append(payload),
            interval_seconds=0.01,
        )
        monitor.start()
        self.assertTrue(wait_until(lambda: not monitor.is_alive()))
        self.assertEqual(emitted[0]["gpu_activity_reason"], "function_unsupported")
        self.assertNotIn("secret", json.dumps(emitted[0]))

    def test_inactive_owner_never_opens_nvml(self):
        created = []
        monitor = gpu_monitor.GpuMonitor(
            run_id="gpu-run",
            owner_pid=321,
            cuda_uuid=THIRD_UUID,
            sampler_factory=lambda cuda_uuid: created.append(cuda_uuid) or FakeSampler(),
            emit=lambda payload: None,
            active=lambda: False,
        )
        monitor.start()
        self.assertTrue(monitor.stop())
        self.assertEqual(created, [])

    def test_owner_loss_stops_after_the_last_observed_sample(self):
        state = {"active": True}
        sampler = FakeSampler()
        emitted = []

        def emit(payload):
            emitted.append(payload)
            state["active"] = False

        monitor = gpu_monitor.GpuMonitor(
            run_id="gpu-run",
            owner_pid=321,
            cuda_uuid=THIRD_UUID,
            sampler_factory=lambda cuda_uuid: sampler,
            emit=emit,
            interval_seconds=0.01,
            active=lambda: state["active"],
        )
        monitor.start()
        self.assertTrue(wait_until(lambda: not monitor.is_alive()))
        self.assertEqual(sampler.sample_calls, 1)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(sampler.close_calls, 1)

    def test_stop_does_not_close_while_a_driver_call_is_active(self):
        release = threading.Event()
        sampler = FakeSampler(block_event=release)
        emitted = []
        monitor = gpu_monitor.GpuMonitor(
            run_id="gpu-run",
            owner_pid=321,
            cuda_uuid=THIRD_UUID,
            sampler_factory=lambda cuda_uuid: sampler,
            emit=lambda payload: emitted.append(payload),
            interval_seconds=0.01,
        )
        monitor.start()
        self.assertTrue(sampler.entered.wait(1))
        self.assertFalse(monitor.stop(timeout=0.05))
        self.assertEqual(sampler.close_calls, 0)
        release.set()
        self.assertTrue(wait_until(lambda: sampler.close_calls == 1))
        self.assertFalse(monitor.is_alive())

    def test_emit_failure_stops_the_monitor_and_closes(self):
        sampler = FakeSampler()
        monitor = gpu_monitor.GpuMonitor(
            run_id="gpu-run",
            owner_pid=321,
            cuda_uuid=THIRD_UUID,
            sampler_factory=lambda cuda_uuid: sampler,
            emit=lambda payload: False,
            interval_seconds=0.01,
        )
        monitor.start()
        self.assertTrue(wait_until(lambda: not monitor.is_alive()))
        self.assertEqual(sampler.close_calls, 1)

    def test_monitor_constructor_rejects_profile_drift(self):
        for arguments in (
            {"run_id": "../bad", "owner_pid": 1},
            {"run_id": "run", "owner_pid": 0},
            {"run_id": "run", "owner_pid": 1, "workers": 4},
            {"run_id": "run", "owner_pid": 1, "workers": 9},
            {"run_id": "run", "owner_pid": 1, "workers": 13},
            {"run_id": "run", "owner_pid": 1, "workers": True},
            {"run_id": "run", "owner_pid": 1, "interval_seconds": 0},
            {"run_id": "run", "owner_pid": 1, "interval_seconds": float("nan")},
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    gpu_monitor.GpuMonitor(
                        cuda_uuid=THIRD_UUID,
                        sampler_factory=lambda cuda_uuid: FakeSampler(),
                        emit=lambda payload: None,
                        **arguments,
                    )
        for workers in (8, 12, 16):
            with self.subTest(workers=workers):
                monitor = gpu_monitor.GpuMonitor(
                    run_id="run",
                    owner_pid=1,
                    cuda_uuid=THIRD_UUID,
                    workers=workers,
                    sampler_factory=lambda cuda_uuid: FakeSampler(),
                    emit=lambda payload: None,
                )
                self.assertEqual(monitor.workers, workers)
                self.assertTrue(monitor.stop())


if __name__ == "__main__":
    unittest.main()


class FakeTorchProperties:
    def __init__(self, value):
        self.uuid = value


class FakeCuda:
    def __init__(self, value=THIRD_UUID, fail=False):
        self.value = value
        self.fail = fail
        self.synchronize_calls = 0

    def get_device_properties(self, index):
        if self.fail:
            raise RuntimeError("cuda unavailable")
        return FakeTorchProperties(self.value)

    def synchronize(self, index):
        self.synchronize_calls += 1
        raise AssertionError("measurement must not synchronize")


class FakeTorch:
    def __init__(self, value=THIRD_UUID, fail=False):
        self.cuda = FakeCuda(value, fail)


class FakeMonitor:
    instances = []

    def __init__(self, **arguments):
        self.arguments = arguments
        self.started = 0
        self.stopped = 0
        self.stop_error = None
        FakeMonitor.instances.append(self)

    def start(self):
        self.started += 1
        return True

    def stop(self):
        self.stopped += 1
        if self.stop_error is not None:
            raise self.stop_error
        return True


class GpuRuntimeTests(unittest.TestCase):
    def setUp(self):
        FakeMonitor.instances = []
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run_path = self.root / "run-gpu-run"
        self.run_path.mkdir(mode=0o700)

    def tearDown(self):
        self.temporary.cleanup()

    def _globals(self, workers=8, run_id="gpu-run"):
        return mock.patch.multiple(
            gpu_runtime.runtime,
            _ACTIVE_RUN_ID=run_id,
            _ACTIVE_WORKERS=workers,
            _ACTIVE_RUNTIME_ROOT=self.root,
        )

    def test_wrapper_preserves_base_hooks_and_wraps_only_owned_hooks(self):
        base_hooks = {
            "post_worker_init": mock.Mock(),
            "post_request": mock.Mock(),
            "worker_exit": mock.Mock(),
            "child_exit": mock.Mock(),
        }
        base_config = {
            "workers": 8,
            "worker_class": "gthread",
            "threads": 50,
            "preload_app": False,
            "post_worker_init": base_hooks["post_worker_init"],
            "post_request": base_hooks["post_request"],
            "worker_exit": base_hooks["worker_exit"],
            "child_exit": base_hooks["child_exit"],
        }
        worker = type("Worker", (), {})()
        with mock.patch.object(
                gpu_runtime.runtime, "load_gunicorn_config",
                return_value=dict(base_config)) as base_loader, \
                mock.patch.object(gpu_runtime, "_start_worker_monitor") as start, \
                mock.patch.object(gpu_runtime, "_stop_worker_monitor") as stop:
            config = gpu_runtime.load_gunicorn_config(
                app_root=Path("/app"), runtime_root=Path("/tmp/runtime"))
            base_loader.assert_called_once_with(
                app_root=Path("/app"), runtime_root=Path("/tmp/runtime"))
            self.assertEqual(config["workers"], 8)
            self.assertFalse(config["preload_app"])
            self.assertIs(config["post_request"], base_hooks["post_request"])
            self.assertIs(config["child_exit"], base_hooks["child_exit"])
            self.assertIsNot(config["post_worker_init"],
                             base_hooks["post_worker_init"])
            self.assertIsNot(config["worker_exit"], base_hooks["worker_exit"])
            base_hooks["post_worker_init"].assert_not_called()
            config["post_worker_init"](worker)
            base_hooks["post_worker_init"].assert_called_once_with(worker)
            start.assert_called_once_with(worker)
            config["worker_exit"](object(), worker)
            stop.assert_called_once_with(worker)
            base_hooks["worker_exit"].assert_called_once()

    def test_wrapper_requires_supported_worker_counts_and_callable_base_hooks(self):
        for workers in (12, 16):
            with self.subTest(workers=workers), mock.patch.object(
                    gpu_runtime.runtime, "load_gunicorn_config",
                    return_value={
                        "workers": workers,
                        "post_worker_init": lambda worker: None,
                        "worker_exit": lambda server, worker: None,
                    }):
                config = gpu_runtime.load_gunicorn_config()
                self.assertEqual(config["workers"], workers)
        for workers in (1, 2, 4, 9, 13, None):
            with self.subTest(workers=workers), mock.patch.object(
                    gpu_runtime.runtime, "load_gunicorn_config",
                    return_value={
                        "workers": workers,
                        "post_worker_init": lambda worker: None,
                        "worker_exit": lambda server, worker: None,
                    }):
                with self.assertRaisesRegex(
                        RuntimeError, "gpu profile requires a supported worker count"):
                    gpu_runtime.load_gunicorn_config()
        with mock.patch.object(
                gpu_runtime.runtime, "load_gunicorn_config",
                return_value={"workers": 8, "post_worker_init": None,
                              "worker_exit": None}):
            with self.assertRaisesRegex(
                    RuntimeError, "base gunicorn hooks unavailable"):
                gpu_runtime.load_gunicorn_config()

    def test_wrapped_post_hook_does_not_break_serving_when_monitor_start_fails(self):
        base_hook = mock.Mock()
        worker = type("Worker", (), {})()
        wrapped = gpu_runtime._wrap_post_worker_init(base_hook)
        with mock.patch.object(
                gpu_runtime, "_start_worker_monitor",
                side_effect=RuntimeError("nvml unavailable")):
            wrapped(worker)
        base_hook.assert_called_once_with(worker)

    def test_wrapped_exit_stops_monitor_even_if_base_hook_fails(self):
        worker = type("Worker", (), {"_verda_gpu_monitor": FakeMonitor()})()
        base_hook = mock.Mock(side_effect=RuntimeError("base failure"))
        wrapped = gpu_runtime._wrap_worker_exit(base_hook)
        with self.assertRaisesRegex(RuntimeError, "base failure"):
            wrapped(object(), worker)
        self.assertEqual(worker._verda_gpu_monitor, None)

    def test_cuda_zero_uuid_uses_properties_without_synchronizing(self):
        torch_module = FakeTorch(THIRD_UUID)
        self.assertEqual(gpu_runtime.cuda0_uuid(torch_module), THIRD_UUID)
        self.assertEqual(torch_module.cuda.synchronize_calls, 0)
        self.assertIsNone(gpu_runtime.cuda0_uuid(None))
        self.assertIsNone(gpu_runtime.cuda0_uuid(FakeTorch(fail=True)))
        self.assertIsNone(gpu_runtime.cuda0_uuid(object()))

    def test_owner_claim_requires_lowest_live_pid_and_never_takes_over(self):
        with mock.patch.object(
                gpu_runtime.runtime, "_read_live_markers",
                return_value={500, 700}):
            self.assertFalse(gpu_runtime._claim_gpu_owner(
                self.run_path, "gpu-run", 700))
        twelve = set(range(500, 512))
        with mock.patch.object(
                gpu_runtime.runtime, "_read_live_markers",
                return_value=twelve):
            self.assertFalse(gpu_runtime._claim_gpu_owner(
                self.run_path, "gpu-run", 501))
            self.assertTrue(gpu_runtime._claim_gpu_owner(
                self.run_path, "gpu-run", 500))
        (self.run_path / gpu_runtime.OWNER_FILE_NAME).unlink()
        with mock.patch.object(
                gpu_runtime.runtime, "_read_live_markers",
                return_value={700}):
            self.assertTrue(gpu_runtime._claim_gpu_owner(
                self.run_path, "gpu-run", 700))
            self.assertFalse(gpu_runtime._claim_gpu_owner(
                self.run_path, "gpu-run", 700))
            self.assertTrue(gpu_runtime._owner_still_active(
                self.run_path, "gpu-run", 700))
            owner = self.run_path / gpu_runtime.OWNER_FILE_NAME
            self.assertEqual(owner.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(owner.read_text(encoding="ascii")), {
                "run_id": "gpu-run", "pid": 700})
        with mock.patch.object(
                gpu_runtime.runtime, "_read_live_markers", return_value=set()):
            self.assertFalse(gpu_runtime._owner_still_active(
                self.run_path, "gpu-run", 700))
        owner = self.run_path / gpu_runtime.OWNER_FILE_NAME
        owner.write_text('{"run_id":"gpu-run","pid":701}', encoding="ascii")
        with mock.patch.object(
                gpu_runtime.runtime, "_read_live_markers", return_value={700}):
            self.assertFalse(gpu_runtime._owner_still_active(
                self.run_path, "gpu-run", 700))
        owner.chmod(0o644)
        with mock.patch.object(
                gpu_runtime.runtime, "_read_live_markers", return_value={700}):
            self.assertFalse(gpu_runtime._owner_still_active(
                self.run_path, "gpu-run", 700))

    def test_owner_claim_rejects_missing_live_set_and_symlink_owner(self):
        with mock.patch.object(
                gpu_runtime.runtime, "_read_live_markers", return_value=set()):
            self.assertFalse(gpu_runtime._claim_gpu_owner(
                self.run_path, "gpu-run", 700))
        target = self.root / "target"
        target.write_text("data", encoding="ascii")
        (self.run_path / gpu_runtime.OWNER_FILE_NAME).symlink_to(target)
        with mock.patch.object(
                gpu_runtime.runtime, "_read_live_markers", return_value={700}):
            self.assertFalse(gpu_runtime._claim_gpu_owner(
                self.run_path, "gpu-run", 700))
            self.assertFalse(gpu_runtime._owner_still_active(
                self.run_path, "gpu-run", 700))

    def test_worker_monitor_starts_only_for_supported_counts_and_lowest_owner(self):
        for workers in (8, 12, 16):
            with self.subTest(workers=workers):
                FakeMonitor.instances = []
                worker = type("Worker", (), {})()
                torch_module = FakeTorch(THIRD_UUID)
                with self._globals(workers=workers), \
                        mock.patch.object(gpu_runtime, "_claim_gpu_owner",
                                          return_value=True), \
                        mock.patch.object(gpu_runtime, "_owner_still_active",
                                          return_value=True), \
                        mock.patch.object(gpu_runtime, "_load_torch",
                                          return_value=torch_module), \
                        mock.patch.object(gpu_runtime.gpu_monitor, "GpuMonitor",
                                          FakeMonitor):
                    gpu_runtime._start_worker_monitor(worker)
                self.assertEqual(len(FakeMonitor.instances), 1)
                monitor = FakeMonitor.instances[0]
                self.assertEqual(monitor.arguments["run_id"], "gpu-run")
                self.assertEqual(monitor.arguments["owner_pid"], os.getpid())
                self.assertEqual(monitor.arguments["workers"], workers)
                self.assertEqual(monitor.arguments["cuda_uuid"], THIRD_UUID)
                self.assertEqual(torch_module.cuda.synchronize_calls, 0)
                self.assertIs(worker._verda_gpu_monitor, monitor)
                self.assertEqual(monitor.started, 1)
        FakeMonitor.instances = []
        for workers in (4, 9, 13):
            with self.subTest(rejected=workers):
                worker = type("Worker", (), {})()
                with self._globals(workers=workers), \
                        mock.patch.object(gpu_runtime, "_claim_gpu_owner") as claim, \
                        mock.patch.object(gpu_runtime.gpu_monitor, "GpuMonitor",
                                          FakeMonitor):
                    gpu_runtime._start_worker_monitor(worker)
                claim.assert_not_called()
                self.assertEqual(FakeMonitor.instances, [])
        worker = type("Worker", (), {})()
        with self._globals(), \
                mock.patch.object(gpu_runtime, "_claim_gpu_owner",
                                  return_value=False), \
                mock.patch.object(gpu_runtime.gpu_monitor, "GpuMonitor",
                                  FakeMonitor):
            gpu_runtime._start_worker_monitor(worker)
        self.assertEqual(FakeMonitor.instances, [])

    def test_worker_monitor_handles_missing_torch_without_synchronizing(self):
        worker = type("Worker", (), {})()
        with self._globals(), \
                mock.patch.object(gpu_runtime, "_claim_gpu_owner",
                                  return_value=True), \
                mock.patch.object(gpu_runtime, "_load_torch",
                                  return_value=None), \
                mock.patch.object(gpu_runtime.gpu_monitor, "GpuMonitor",
                                  FakeMonitor):
            gpu_runtime._start_worker_monitor(worker)
        self.assertIsNone(FakeMonitor.instances[0].arguments["cuda_uuid"])
        self.assertEqual(FakeMonitor.instances[0].started, 1)

    def test_monitor_stop_failure_does_not_escape_worker_exit(self):
        monitor = FakeMonitor()
        monitor.stop_error = RuntimeError("stop failed")
        worker = type("Worker", (), {"_verda_gpu_monitor": monitor})()
        base_hook = mock.Mock()
        gpu_runtime._wrap_worker_exit(base_hook)(object(), worker)
        self.assertEqual(monitor.stopped, 1)
        base_hook.assert_called_once()
