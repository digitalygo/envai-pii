"""Opt-in NVML device activity observation for GPU worker-count experiments."""

from __future__ import annotations

import ctypes
import json
import math
import os
import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from .runtime import validate_run_id

PROFILE_PREFIX = "VERDAGPUPROFILE "
PROFILE_WORKERS = 8
PROFILE_WORKER_CHOICES = (8, 12, 16)
NVML_LIBRARY = "libnvidia-ml.so.1"
MAX_PROFILE_LINE_BYTES = 4096
DEFAULT_INTERVAL_SECONDS = 1.0
MAX_EPOCH_MILLISECONDS = 9_000_000_000_000_000
MAX_MONOTONIC_MILLISECONDS = 9_000_000_000_000_000
MAX_READ_DURATION_MILLISECONDS = 600_000
MAX_POWER_MILLIWATTS = 2_147_483_647

REASON_CODES = frozenset({
    "device_unavailable",
    "function_unsupported",
    "init_failed",
    "library_unavailable",
    "power_invalid",
    "power_limit_invalid",
    "power_limit_unavailable",
    "power_unavailable",
    "utilization_invalid",
    "utilization_unavailable",
    "uuid_invalid",
    "uuid_mismatch",
    "uuid_unavailable",
})

PROFILE_FIELDS = frozenset({
    "run_id",
    "owner_pid",
    "workers",
    "epoch_ms",
    "monotonic_ms",
    "read_duration_ms",
    "gpu_activity_percent",
    "memory_controller_activity_percent",
    "power_milliwatts",
    "power_limit_milliwatts",
    "gpu_activity_reason",
    "memory_controller_activity_reason",
    "power_reason",
    "power_limit_reason",
})

_UUID_PATTERN = re.compile(
    r"(?:[Gg][Pp][Uu]-)?([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})\Z"
)
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")

NVML_SUCCESS = 0


class NvmlUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


def _canonical_gpu_uuid(value: uuid.UUID) -> str:
    return "GPU-" + str(value).upper()


def _raw_uuid_bytes(value: object) -> bytes | None:
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        return raw if len(raw) == 16 else None
    if not isinstance(value, (list, tuple)) or len(value) != 16:
        return None
    octets = []
    for item in value:
        if type(item) is not int or not 0 <= item <= 255:
            return None
        octets.append(item)
    return bytes(octets)


def normalize_uuid(value: object) -> str | None:
    if isinstance(value, uuid.UUID):
        return _canonical_gpu_uuid(value)
    if isinstance(value, bytes):
        if len(value) == 16:
            return _canonical_gpu_uuid(uuid.UUID(bytes=value))
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            return None
    elif isinstance(value, bytearray):
        raw = _raw_uuid_bytes(value)
        return None if raw is None else _canonical_gpu_uuid(uuid.UUID(bytes=raw))
    elif not isinstance(value, str):
        try:
            raw = _raw_uuid_bytes(getattr(value, "bytes"))
        except Exception:
            return None
        return None if raw is None else _canonical_gpu_uuid(uuid.UUID(bytes=raw))
    match = _UUID_PATTERN.fullmatch(value)
    if match is None:
        return None
    return "GPU-" + match.group(1).upper()


def _bind_function(library: Any, name: str, argtypes: list[Any],
                   restype: Any) -> Any:
    function = getattr(library, name)
    function.argtypes = argtypes
    function.restype = restype
    return function


def _bind_preferred(library: Any, names: tuple[str, ...], argtypes: list[Any],
                    restype: Any) -> Any | None:
    for name in names:
        try:
            return _bind_function(library, name, argtypes, restype)
        except Exception:
            continue
    return None


def _safe_milliseconds(clock: Callable[[], float]) -> int:
    try:
        sampled = float(clock())
    except Exception:
        return 0
    if not math.isfinite(sampled) or sampled < 0:
        return 0
    return min(int(sampled * 1000), MAX_EPOCH_MILLISECONDS)


def _valid_metric(value: object, reason: object, maximum: int) -> bool:
    if value is None:
        return isinstance(reason, str) and reason in REASON_CODES
    if type(value) is not int or not 0 <= value <= maximum:
        return False
    return reason is None


def validate_profile_record(payload: object) -> bool:
    if not isinstance(payload, Mapping) or set(payload) != PROFILE_FIELDS:
        return False
    run_id = payload.get("run_id")
    owner_pid = payload.get("owner_pid")
    workers = payload.get("workers")
    if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
        return False
    if type(owner_pid) is not int or owner_pid < 1:
        return False
    if type(workers) is not int or workers not in PROFILE_WORKER_CHOICES:
        return False
    epoch_ms = payload.get("epoch_ms")
    monotonic_ms = payload.get("monotonic_ms")
    read_duration_ms = payload.get("read_duration_ms")
    if (type(epoch_ms) is not int or not 0 <= epoch_ms <= MAX_EPOCH_MILLISECONDS
            or type(monotonic_ms) is not int
            or not 0 <= monotonic_ms <= MAX_MONOTONIC_MILLISECONDS
            or type(read_duration_ms) is not int
            or not 0 <= read_duration_ms <= MAX_READ_DURATION_MILLISECONDS):
        return False
    return (
        _valid_metric(payload.get("gpu_activity_percent"),
                      payload.get("gpu_activity_reason"), 100)
        and _valid_metric(payload.get("memory_controller_activity_percent"),
                          payload.get("memory_controller_activity_reason"), 100)
        and _valid_metric(payload.get("power_milliwatts"),
                          payload.get("power_reason"), MAX_POWER_MILLIWATTS)
        and _valid_metric(payload.get("power_limit_milliwatts"),
                          payload.get("power_limit_reason"), MAX_POWER_MILLIWATTS)
    )


def emit_profile_record(payload: Mapping[str, object], *,
                        write: Callable[[int, bytes], int] | None = None) -> bool:
    normalized = dict(payload)
    if not validate_profile_record(normalized):
        return False
    try:
        line = (PROFILE_PREFIX + json.dumps(
            normalized, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    except (UnicodeEncodeError, ValueError, TypeError):
        return False
    if len(line) > MAX_PROFILE_LINE_BYTES:
        return False
    writer = os.write if write is None else write
    try:
        writer(1, line)
    except (OSError, TypeError, ValueError):
        return False
    return True


def parse_profile_line(line: object) -> dict[str, object] | None:
    if not isinstance(line, str) or not line.startswith(PROFILE_PREFIX):
        return None
    if len(line.encode("utf-8", "ignore")) > MAX_PROFILE_LINE_BYTES:
        raise ValueError("invalid gpu profile line")
    try:
        payload = json.loads(line[len(PROFILE_PREFIX):].strip())
    except (TypeError, ValueError):
        raise ValueError("invalid gpu profile line") from None
    if not isinstance(payload, dict) or not validate_profile_record(payload):
        raise ValueError("invalid gpu profile line")
    return payload


class NvmlSampler:
    def __init__(self, cuda_uuid: object, *,
                 library_factory: Callable[[str], Any] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time) -> None:
        self._requested_uuid = cuda_uuid
        self._uuid = normalize_uuid(cuda_uuid)
        self._library_factory = ctypes.CDLL if library_factory is None else library_factory
        self._clock = clock
        self._wall_clock = wall_clock
        self._library: Any = None
        self._handle: int | None = None
        self._initialized = False
        self._count: Any = None
        self._handle_by_index: Any = None
        self._device_uuid: Any = None
        self._utilization: Any = None
        self._power: Any = None
        self._power_limit: Any = None
        self._shutdown: Any = None

    def open(self) -> str | None:
        if self._initialized:
            return None
        if self._requested_uuid is None:
            return "uuid_unavailable"
        if self._uuid is None:
            return "uuid_invalid"
        try:
            library = self._library_factory(NVML_LIBRARY)
        except Exception:
            return "library_unavailable"
        init = _bind_preferred(library, ("nvmlInit_v2", "nvmlInit"), [], ctypes.c_int)
        if init is None:
            return "function_unsupported"
        try:
            if init() != NVML_SUCCESS:
                return "init_failed"
        except Exception:
            return "init_failed"
        self._library = library
        self._initialized = True
        self._shutdown = _bind_preferred(
            library, ("nvmlShutdown",), [], ctypes.c_int)
        count = _bind_preferred(
            library, ("nvmlDeviceGetCount_v2", "nvmlDeviceGetCount"),
            [ctypes.POINTER(ctypes.c_uint)], ctypes.c_int)
        handle_by_index = _bind_preferred(
            library, ("nvmlDeviceGetHandleByIndex_v2", "nvmlDeviceGetHandleByIndex"),
            [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)], ctypes.c_int)
        device_uuid = _bind_preferred(
            library, ("nvmlDeviceGetUUID",),
            [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char), ctypes.c_uint],
            ctypes.c_int)
        utilization = _bind_preferred(
            library, ("nvmlDeviceGetUtilizationRates",),
            [ctypes.c_void_p, ctypes.POINTER(NvmlUtilization)], ctypes.c_int)
        if count is None or handle_by_index is None or device_uuid is None:
            self.close()
            return "function_unsupported"
        if utilization is None:
            self.close()
            return "utilization_unavailable"
        self._count = count
        self._handle_by_index = handle_by_index
        self._device_uuid = device_uuid
        self._utilization = utilization
        self._power = _bind_preferred(
            library, ("nvmlDeviceGetPowerUsage",),
            [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)], ctypes.c_int)
        self._power_limit = _bind_preferred(
            library, ("nvmlDeviceGetPowerManagementLimit",),
            [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)], ctypes.c_int)
        handle, reason = self._resolve_handle()
        if reason is not None:
            self.close()
            return reason
        self._handle = handle
        return None

    def _resolve_handle(self) -> tuple[int | None, str | None]:
        try:
            count_value = ctypes.c_uint(0)
            if self._count(ctypes.byref(count_value)) != NVML_SUCCESS:
                return None, "device_unavailable"
            count = int(count_value.value)
        except Exception:
            return None, "device_unavailable"
        if count < 1 or count > 256:
            return None, "device_unavailable"
        readable_uuids = 0
        for index in range(count):
            try:
                handle = ctypes.c_void_p()
                if self._handle_by_index(
                        ctypes.c_uint(index), ctypes.byref(handle)) != NVML_SUCCESS:
                    continue
                if not handle.value:
                    continue
                buffer = ctypes.create_string_buffer(96)
                if self._device_uuid(
                        handle, buffer, ctypes.c_uint(len(buffer))) != NVML_SUCCESS:
                    continue
                raw_uuid = buffer.value.decode("ascii")
            except (Exception, UnicodeDecodeError):
                continue
            normalized = normalize_uuid(raw_uuid)
            if normalized is None:
                continue
            readable_uuids += 1
            if normalized == self._uuid:
                return int(handle.value), None
        if readable_uuids == 0:
            return None, "uuid_unavailable"
        return None, "uuid_mismatch"

    def sample(self) -> dict[str, object] | None:
        if not self._initialized or self._handle is None:
            return None
        epoch_ms = _safe_milliseconds(self._wall_clock)
        monotonic_ms = _safe_milliseconds(self._clock)
        gpu_activity = None
        memory_activity = None
        gpu_reason = None
        memory_reason = None
        try:
            utilization = NvmlUtilization()
            code = self._utilization(self._handle, ctypes.byref(utilization))
        except Exception:
            code = -1
        if code != NVML_SUCCESS:
            gpu_reason = "utilization_unavailable"
            memory_reason = "utilization_unavailable"
        else:
            gpu_value = int(utilization.gpu)
            memory_value = int(utilization.memory)
            if 0 <= gpu_value <= 100:
                gpu_activity = gpu_value
            else:
                gpu_reason = "utilization_invalid"
            if 0 <= memory_value <= 100:
                memory_activity = memory_value
            else:
                memory_reason = "utilization_invalid"
        power, power_reason = self._read_optional_value(
            self._power, "power_unavailable", "power_invalid")
        power_limit, power_limit_reason = self._read_optional_value(
            self._power_limit, "power_limit_unavailable", "power_limit_invalid")
        read_duration_ms = max(
            0, _safe_milliseconds(self._clock) - monotonic_ms)
        return {
            "epoch_ms": epoch_ms,
            "monotonic_ms": monotonic_ms,
            "read_duration_ms": min(
                read_duration_ms, MAX_READ_DURATION_MILLISECONDS),
            "gpu_activity_percent": gpu_activity,
            "memory_controller_activity_percent": memory_activity,
            "power_milliwatts": power,
            "power_limit_milliwatts": power_limit,
            "gpu_activity_reason": gpu_reason,
            "memory_controller_activity_reason": memory_reason,
            "power_reason": power_reason,
            "power_limit_reason": power_limit_reason,
        }

    def _read_optional_value(self, function: Any, unavailable_reason: str,
                             invalid_reason: str) -> tuple[int | None, str | None]:
        if function is None:
            return None, unavailable_reason
        try:
            value = ctypes.c_uint(0)
            if function(self._handle, ctypes.byref(value)) != NVML_SUCCESS:
                return None, unavailable_reason
            number = int(value.value)
        except Exception:
            return None, unavailable_reason
        if not 0 <= number <= MAX_POWER_MILLIWATTS:
            return None, invalid_reason
        return number, None

    def close(self) -> None:
        if not self._initialized:
            return
        shutdown = self._shutdown
        self._initialized = False
        self._handle = None
        self._count = None
        self._handle_by_index = None
        self._device_uuid = None
        self._utilization = None
        self._power = None
        self._power_limit = None
        self._shutdown = None
        if shutdown is not None:
            try:
                shutdown()
            except Exception:
                pass


class GpuMonitor:
    def __init__(self, *, run_id: str, owner_pid: int, cuda_uuid: object,
                 workers: int = PROFILE_WORKERS,
                 interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
                 sampler_factory: Callable[[object], Any] | None = None,
                 emit: Callable[[Mapping[str, object]], object] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time,
                 active: Callable[[], bool] | None = None) -> None:
        validate_run_id(run_id)
        if type(owner_pid) is not int or owner_pid < 1:
            raise ValueError("owner_pid must be a positive integer")
        if type(workers) is not int or workers not in PROFILE_WORKER_CHOICES:
            raise ValueError("gpu profile requires a supported worker count")
        if (isinstance(interval_seconds, bool)
                or not isinstance(interval_seconds, (int, float))
                or not math.isfinite(float(interval_seconds))
                or float(interval_seconds) <= 0):
            raise ValueError("interval_seconds must be a finite positive number")
        self.run_id = run_id
        self.owner_pid = owner_pid
        self.cuda_uuid = cuda_uuid
        self.workers = workers
        self.interval_seconds = float(interval_seconds)
        self.clock = clock
        self.wall_clock = wall_clock
        self.active = active
        self._emit = emit_profile_record if emit is None else emit
        self._sampler_factory = sampler_factory or (
            lambda cuda_uuid: NvmlSampler(
                cuda_uuid, clock=self.clock, wall_clock=self.wall_clock))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if self._thread is not None:
            return False
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="verda-gpu-profile")
        self._thread.start()
        return True

    def _run(self) -> None:
        sampler = None
        try:
            if not self._is_active():
                return
            try:
                sampler = self._sampler_factory(self.cuda_uuid)
            except Exception:
                self._emit_failure("function_unsupported")
                return
            try:
                reason = sampler.open()
            except Exception:
                self._emit_failure("function_unsupported")
                return
            if reason is not None:
                self._emit_failure(reason)
                return
            while not self._stop.is_set():
                if not self._is_active():
                    return
                try:
                    sample = sampler.sample()
                except Exception:
                    return
                if sample is None:
                    return
                payload = {
                    "run_id": self.run_id,
                    "owner_pid": self.owner_pid,
                    "workers": self.workers,
                    **sample,
                }
                try:
                    emitted = self._emit(payload)
                except Exception:
                    return
                if emitted is False:
                    return
                if self._stop.wait(self.interval_seconds):
                    return
        finally:
            if sampler is not None:
                try:
                    sampler.close()
                except Exception:
                    pass

    def _is_active(self) -> bool:
        if self.active is None:
            return True
        try:
            return bool(self.active())
        except Exception:
            return False

    def _emit_failure(self, reason: str) -> None:
        if reason not in REASON_CODES:
            reason = "function_unsupported"
        payload = {
            "run_id": self.run_id,
            "owner_pid": self.owner_pid,
            "workers": self.workers,
            "epoch_ms": _safe_milliseconds(self.wall_clock),
            "monotonic_ms": _safe_milliseconds(self.clock),
            "read_duration_ms": 0,
            "gpu_activity_percent": None,
            "memory_controller_activity_percent": None,
            "power_milliwatts": None,
            "power_limit_milliwatts": None,
            "gpu_activity_reason": reason,
            "memory_controller_activity_reason": reason,
            "power_reason": reason,
            "power_limit_reason": reason,
        }
        try:
            self._emit(payload)
        except Exception:
            pass

    def stop(self, timeout: float = 5.0) -> bool:
        self._stop.set()
        thread = self._thread
        if thread is None:
            return True
        if thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout)))
        return not thread.is_alive()

    def is_alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()
