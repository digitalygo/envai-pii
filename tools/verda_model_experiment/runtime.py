from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import stat
import threading
import time
from typing import Any

from .fixture import FIXTURE_TEXT

APP_SOURCE = Path("/app/src/app")
RUNTIME_ROOT = Path("/tmp/envai-pii-verda-runtime")
PROFILE_WORKERS_ENV = "ENVAIPI_VERDA_WORKERS"
PROFILE_RUN_ID_ENV = "ENVAIPI_VERDA_RUN_ID"
BARRIER_TIMEOUT_SECONDS = 300.0
TELEMETRY_INTERVAL_SECONDS = 2.0
SOURCE_HASHES = {
    "app.py": "b0ec5163cd0d9eee05922d4b80718eb26abc762b0612935e1f1ad8275dc3848e",
    "gunicorn_config.py": "8a8d58411b7aca4fd2dea37921e32c373403cf41cd7907863c658405246ab069",
    "runtime_execution.py": "eb03f52dfc1b3ac9d36971b453fb84ad50e92d04ad7cd3d3a241a4c09df8b02a",
    "cloud_service.py": "5b79bdd845e4f3ff9e3f2d8b2657e902f278a11da02021ac0e8473d40b608a4e",
}
EXPECTED_ENV = {
    "PII_AUTH_MODE": "upstream",
    "PII_ANALYSIS_TIMEOUT_SECONDS": "60",
    "PII_MAX_CONCURRENT_ANALYSES": "16",
    "PII_MAX_QUEUED_ANALYSES": "32",
    "PII_QUEUE_TIMEOUT_SECONDS": "30",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "TOKENIZERS_PARALLELISM": "false",
}
SUPPORTED_WORKERS = frozenset({1, 2, 4, 8, 12, 16})
PROSPECTIVE_WORKERS = frozenset({2, 4, 8})
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
DTYPE_NAMES = frozenset({
    "bfloat16", "bool", "float16", "float32", "float64", "int8",
    "int16", "int32", "int64", "uint8",
})
REASON_CODES = frozenset({
    "barrier_timeout", "cgroup_file_missing", "cgroup_value_invalid",
    "cpu_affinity_unavailable", "cpu_quota_unknown", "gpu_profile_mismatch",
    "limit_unavailable", "memory_limit_unknown", "model_metrics_unavailable",
    "pid_unavailable", "source_integrity_failed", "startup_failed",
    "settings_mismatch", "torch_metric_unavailable", "unknown_dtype",
})
EVENT_NAMES = frozenset({
    "ready", "sample", "startup_failed", "exit", "child_exit",
})
BOOLEAN_EVENT_FIELDS = frozenset({
    "source_app_ok", "source_config_ok", "source_execution_ok",
    "source_service_ok", "settings_ok", "auth_upstream", "gpu_l40s",
    "marker_removed",
})
INTEGER_EVENT_FIELDS = frozenset({
    "pid", "workers", "request_count", "analysis_timeout_seconds",
    "max_concurrent_analyses",
    "max_queued_analyses", "queue_timeout_seconds", "gunicorn_threads",
    "parameter_bytes", "buffer_bytes", "cuda_allocated_bytes",
    "cuda_free_bytes", "cuda_total_bytes", "torch_max_allocated_bytes",
    "cgroup_memory_current_bytes", "cgroup_memory_peak_bytes",
    "cgroup_memory_limit_bytes", "cgroup_pids_current", "cgroup_pids_limit",
    "cpu_quota_us", "cpu_period_us", "cpu_affinity_count", "gpu_device_count",
})
EVENT_KEYS = frozenset({
    "run_id", "event", "pid", "workers", "gunicorn_threads", "request_count",
    "source_app_ok", "source_config_ok", "source_execution_ok",
    "source_service_ok", "settings_ok", "auth_upstream",
    "analysis_timeout_seconds", "max_concurrent_analyses",
    "max_queued_analyses", "queue_timeout_seconds", "parameter_bytes",
    "buffer_bytes", "model_dtypes", "model_metrics_reason", "cuda_allocated_bytes",
    "cuda_allocated_reason", "cuda_free_bytes", "cuda_free_reason",
    "cuda_total_bytes", "cuda_total_reason", "torch_max_allocated_bytes",
    "torch_max_allocated_reason", "cgroup_memory_current_bytes",
    "cgroup_memory_current_reason", "cgroup_memory_peak_bytes",
    "cgroup_memory_peak_reason", "cgroup_memory_limit_bytes",
    "cgroup_memory_limit_reason", "cgroup_pids_current",
    "cgroup_pids_current_reason", "cgroup_pids_limit",
    "cgroup_pids_limit_reason", "cpu_quota_us", "cpu_quota_reason",
    "cpu_period_us", "cpu_period_reason", "cpu_affinity_count", "cpu_affinity_reason",
    "gpu_l40s", "gpu_device_count", "gpu_reason", "error_code",
    "marker_removed",
})

_ACTIVE_RUN_ID: str | None = None
_ACTIVE_WORKERS: int | None = None
_ACTIVE_THREADS: int | None = None
_ACTIVE_RUNTIME_ROOT = RUNTIME_ROOT
EXPECTED_THREADS = (int(EXPECTED_ENV["PII_MAX_CONCURRENT_ANALYSES"])
                    + int(EXPECTED_ENV["PII_MAX_QUEUED_ANALYSES"]) + 2)


def validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("invalid run id")
    return run_id


def verify_sources(root: Path | None = None) -> dict[str, bool]:
    root = APP_SOURCE if root is None else root
    results = {}
    for name, expected in SOURCE_HASHES.items():
        try:
            digest = hashlib.sha256((root / name).read_bytes()).hexdigest()
        except OSError:
            results[name] = False
        else:
            results[name] = digest == expected
    return results


def _set_private_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = path.lstat()
    except OSError:
        raise RuntimeError("runtime directory unavailable") from None
    if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()):
        raise RuntimeError("runtime directory unsafe")
    try:
        path.chmod(0o700)
    except OSError:
        raise RuntimeError("runtime directory unavailable") from None


def _reset_run_directory(root: Path, run_id: str) -> Path:
    _set_private_directory(root)
    run_path = root / f"run-{run_id}"
    try:
        info = run_path.lstat()
    except FileNotFoundError:
        info = None
    except OSError:
        raise RuntimeError("runtime directory unavailable") from None
    if info is not None:
        if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid()):
            raise RuntimeError("runtime directory unsafe")
        try:
            shutil.rmtree(run_path)
        except OSError:
            raise RuntimeError("runtime directory unavailable") from None
    try:
        run_path.mkdir(mode=0o700)
    except OSError:
        raise RuntimeError("runtime directory unavailable") from None
    return run_path


def _proc_start_ticks(pid: int, proc_root: Path = Path("/proc")) -> int | None:
    try:
        stat_line = (proc_root / str(pid) / "stat").read_text(encoding="ascii")
        fields = stat_line[stat_line.rfind(")") + 1:].split()
        start_ticks = int(fields[19])
    except (OSError, ValueError, IndexError):
        return None
    return start_ticks if start_ticks >= 0 else None


def _pid_is_live(pid: int, start_ticks: int, proc_root: Path = Path("/proc"),
                 kill=os.kill) -> bool:
    if type(pid) is not int or pid < 1 or type(start_ticks) is not int:
        return False
    try:
        kill(pid, 0)
    except OSError:
        return False
    return _proc_start_ticks(pid, proc_root) == start_ticks


def _marker_path(run_path: Path, pid: int) -> Path:
    return run_path / f"ready-{pid}.json"


def _write_ready_marker(run_path: Path, run_id: str, pid: int,
                        start_ticks: int) -> None:
    marker = _marker_path(run_path, pid)
    temporary = run_path / f"ready-{pid}.tmp"
    payload = json.dumps({
        "run_id": run_id,
        "pid": pid,
        "start_ticks": start_ticks,
    }, sort_keys=True, separators=(",", ":")).encode("ascii")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, marker)
        marker.chmod(0o600)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError("worker marker unavailable") from None


def _read_live_markers(run_path: Path, run_id: str,
                       proc_root: Path = Path("/proc"), kill=os.kill) -> set[int]:
    live = set()
    try:
        candidates = tuple(run_path.glob("ready-*.json"))
    except OSError:
        return live
    for marker in candidates:
        if not re.fullmatch(r"ready-[1-9][0-9]*\.json", marker.name):
            continue
        try:
            info = marker.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                continue
            payload = json.loads(marker.read_text(encoding="ascii"))
        except (OSError, ValueError):
            continue
        if (not isinstance(payload, dict)
                or set(payload) != {"run_id", "pid", "start_ticks"}
                or payload.get("run_id") != run_id
                or type(payload.get("pid")) is not int
                or type(payload.get("start_ticks")) is not int):
            continue
        pid = payload["pid"]
        if marker.name != f"ready-{pid}.json":
            continue
        if _pid_is_live(pid, payload["start_ticks"], proc_root, kill):
            live.add(pid)
    return live


def wait_for_worker_barrier(run_path: Path, run_id: str, workers: int,
                            *, timeout_seconds: float = BARRIER_TIMEOUT_SECONDS,
                            interval_seconds: float = 0.1,
                            clock=time.monotonic, sleep=time.sleep,
                            proc_root: Path = Path("/proc"), kill=os.kill) -> bool:
    validate_run_id(run_id)
    if type(workers) is not int or workers not in SUPPORTED_WORKERS:
        return False
    deadline = clock() + max(0.0, timeout_seconds)
    while True:
        if len(_read_live_markers(run_path, run_id, proc_root, kill)) == workers:
            return True
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        sleep(min(interval_seconds, remaining))


def _read_cgroup_number(path: Path, *, allow_max: bool = False) -> tuple[int | None, str | None]:
    try:
        value = path.read_text(encoding="ascii").strip()
    except OSError:
        return None, "cgroup_file_missing"
    if allow_max and value == "max":
        return None, "limit_unavailable"
    try:
        number = int(value)
    except ValueError:
        return None, "cgroup_value_invalid"
    if number < 0:
        return None, "cgroup_value_invalid"
    return number, None


def _read_cpu_limit(path: Path) -> tuple[int | None, int | None, str | None]:
    try:
        parts = path.read_text(encoding="ascii").split()
    except OSError:
        return None, None, "cgroup_file_missing"
    if len(parts) != 2:
        return None, None, "cgroup_value_invalid"
    try:
        period = int(parts[1])
    except ValueError:
        return None, None, "cgroup_value_invalid"
    if period <= 0:
        return None, None, "cgroup_value_invalid"
    if parts[0] == "max":
        return None, period, "limit_unavailable"
    try:
        quota = int(parts[0])
    except ValueError:
        return None, None, "cgroup_value_invalid"
    if quota < 0:
        return None, None, "cgroup_value_invalid"
    return quota, period, None


def _resource_metrics(torch_module: Any = None,
                      cgroup_root: Path = Path("/sys/fs/cgroup"),
                      affinity=os.sched_getaffinity) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if torch_module is None:
        for metric in ("cuda_allocated_bytes", "cuda_free_bytes",
                       "cuda_total_bytes", "torch_max_allocated_bytes"):
            metrics[metric] = None
            metrics[f"{metric.removesuffix('_bytes')}_reason"] = "torch_metric_unavailable"
    else:
        try:
            metrics["cuda_allocated_bytes"] = int(torch_module.cuda.memory_allocated(0))
            metrics["cuda_allocated_reason"] = None
        except Exception:
            metrics["cuda_allocated_bytes"] = None
            metrics["cuda_allocated_reason"] = "torch_metric_unavailable"
        try:
            free_bytes, total_bytes = torch_module.cuda.mem_get_info(0)
            metrics["cuda_free_bytes"] = int(free_bytes)
            metrics["cuda_free_reason"] = None
            metrics["cuda_total_bytes"] = int(total_bytes)
            metrics["cuda_total_reason"] = None
        except Exception:
            metrics["cuda_free_bytes"] = None
            metrics["cuda_free_reason"] = "torch_metric_unavailable"
            metrics["cuda_total_bytes"] = None
            metrics["cuda_total_reason"] = "torch_metric_unavailable"
        try:
            metrics["torch_max_allocated_bytes"] = int(
                torch_module.cuda.max_memory_allocated(0))
            metrics["torch_max_allocated_reason"] = None
        except Exception:
            metrics["torch_max_allocated_bytes"] = None
            metrics["torch_max_allocated_reason"] = "torch_metric_unavailable"
    cgroup_files = {
        "cgroup_memory_current_bytes": ("memory.current", False),
        "cgroup_memory_peak_bytes": ("memory.peak", False),
        "cgroup_memory_limit_bytes": ("memory.max", True),
        "cgroup_pids_current": ("pids.current", False),
        "cgroup_pids_limit": ("pids.max", True),
    }
    for key, (filename, allow_max) in cgroup_files.items():
        value, reason = _read_cgroup_number(cgroup_root / filename,
                                           allow_max=allow_max)
        metrics[key] = value
        metrics[f"{key.removesuffix('_bytes')}_reason"] = reason
    quota, period, quota_reason = _read_cpu_limit(cgroup_root / "cpu.max")
    metrics["cpu_quota_us"] = quota
    metrics["cpu_quota_reason"] = quota_reason
    metrics["cpu_period_us"] = period
    metrics["cpu_period_reason"] = quota_reason if period is None else None
    try:
        metrics["cpu_affinity_count"] = len(affinity(0))
        metrics["cpu_affinity_reason"] = None
    except (OSError, AttributeError, TypeError):
        metrics["cpu_affinity_count"] = None
        metrics["cpu_affinity_reason"] = "cpu_affinity_unavailable"
    return metrics


def _model_footprint(nlp: Any) -> tuple[int, int, str]:
    model = getattr(nlp, "model", None)
    if model is None:
        raise RuntimeError("model metrics unavailable")
    totals = {"parameter_bytes": 0, "buffer_bytes": 0}
    dtypes = set()
    for collection_name, total_name in (("parameters", "parameter_bytes"),
                                        ("buffers", "buffer_bytes")):
        collection = getattr(model, collection_name, None)
        if not callable(collection):
            raise RuntimeError("model metrics unavailable")
        for tensor in collection():
            count = int(tensor.numel())
            item_bytes = int(tensor.element_size())
            if count < 0 or item_bytes < 0:
                raise RuntimeError("model metrics unavailable")
            totals[total_name] += count * item_bytes
            dtype = str(tensor.dtype).removeprefix("torch.")
            if dtype not in DTYPE_NAMES:
                raise RuntimeError("unknown dtype")
            dtypes.add(dtype)
    return totals["parameter_bytes"], totals["buffer_bytes"], ",".join(sorted(dtypes))


def _resolved_settings() -> bool:
    return all(os.environ.get(name) == expected
               for name, expected in EXPECTED_ENV.items())


def _source_fields(results: dict[str, bool]) -> dict[str, bool]:
    return {
        "source_app_ok": results.get("app.py") is True,
        "source_config_ok": results.get("gunicorn_config.py") is True,
        "source_execution_ok": results.get("runtime_execution.py") is True,
        "source_service_ok": results.get("cloud_service.py") is True,
    }


def _safe_event_value(field: str, value: Any) -> bool:
    if value is None:
        return True
    if field in BOOLEAN_EVENT_FIELDS:
        return type(value) is bool
    if field in INTEGER_EVENT_FIELDS:
        return type(value) is int and value >= 0
    if not isinstance(value, str) or len(value) > 128:
        return False
    if field == "run_id":
        return RUN_ID_PATTERN.fullmatch(value) is not None
    if field == "event":
        return value in EVENT_NAMES
    if field == "model_dtypes":
        names = value.split(",")
        return bool(value) and all(item in DTYPE_NAMES for item in names)
    if field == "error_code" or field.endswith("_reason"):
        return value in REASON_CODES
    return False


def emit_event(event: str, run_id: str, pid: int, workers: int,
               **fields: Any) -> None:
    validate_run_id(run_id)
    if (event not in EVENT_NAMES or type(pid) is not int or pid < 1
            or type(workers) is not int or workers not in SUPPORTED_WORKERS):
        return
    if not set(fields).issubset(EVENT_KEYS - {"run_id", "event", "pid", "workers"}):
        return
    payload = {"run_id": run_id, "event": event, "pid": pid,
               "workers": workers, **fields}
    if not all(_safe_event_value(key, value) for key, value in payload.items()):
        return
    try:
        line = ("VERDAEXPERIMENT " + json.dumps(
            payload, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        if len(line) <= 4096:
            os.write(1, line)
    except (OSError, UnicodeEncodeError, ValueError):
        return


def _base_config_values(app_root: Path) -> dict[str, Any]:
    config_path = app_root / "gunicorn_config.py"
    try:
        values = runpy.run_path(str(config_path))
    except Exception:
        raise RuntimeError("source_integrity_failed") from None
    workers = values.get("workers")
    worker_class = values.get("worker_class")
    preload = values.get("preload_app")
    threads = values.get("threads")
    if (type(workers) is not int or workers != 1 or worker_class != "gthread"
            or preload is not False or type(threads) is not int or threads < 1):
        raise RuntimeError("source_integrity_failed")
    return {"workers": workers, "worker_class": worker_class,
            "preload_app": preload, "threads": threads}


def _runtime_path(root: Path, run_id: str) -> Path:
    return root / f"run-{run_id}"


def _load_active_profile() -> tuple[int, str]:
    raw_workers = os.environ.get(PROFILE_WORKERS_ENV)
    run_id = os.environ.get(PROFILE_RUN_ID_ENV)
    if raw_workers not in {str(workers) for workers in SUPPORTED_WORKERS}:
        raise RuntimeError("invalid worker profile")
    return int(raw_workers), validate_run_id(run_id)


def load_gunicorn_config(*, app_root: Path = APP_SOURCE,
                         runtime_root: Path = RUNTIME_ROOT) -> dict[str, Any]:
    global _ACTIVE_RUN_ID, _ACTIVE_WORKERS, _ACTIVE_THREADS, _ACTIVE_RUNTIME_ROOT
    source_results = verify_sources(app_root)
    if not all(source_results.values()):
        raise RuntimeError("source_integrity_failed")
    base = _base_config_values(app_root)
    workers, run_id = _load_active_profile()
    _reset_run_directory(runtime_root, run_id)
    _ACTIVE_RUN_ID = run_id
    _ACTIVE_WORKERS = workers
    _ACTIVE_THREADS = base["threads"]
    _ACTIVE_RUNTIME_ROOT = runtime_root
    return {
        "workers": workers,
        "worker_class": base["worker_class"],
        "threads": base["threads"],
        "preload_app": False,
        "timeout": 600,
        "graceful_timeout": 30,
        "accesslog": "/dev/null",
        "errorlog": "-",
        "post_worker_init": post_worker_init,
        "post_request": post_request,
        "worker_exit": worker_exit,
        "child_exit": child_exit,
    }


def _gpu_profile(torch_module: Any) -> tuple[bool, int | None, bool | None, str | None]:
    try:
        if not torch_module.cuda.is_available():
            return False, 0, False, "gpu_profile_mismatch"
        device_count = int(torch_module.cuda.device_count())
        if device_count != 1:
            return False, device_count, False, "gpu_profile_mismatch"
        device_name = str(torch_module.cuda.get_device_name(0)).upper()
        is_l40s = "L40S" in device_name
        return is_l40s, device_count, is_l40s, None if is_l40s else "gpu_profile_mismatch"
    except Exception:
        return False, None, None, "gpu_profile_mismatch"


def _event_metrics(torch_module: Any, nlp: Any = None) -> dict[str, Any]:
    values = _resource_metrics(torch_module)
    values.update({"parameter_bytes": None, "buffer_bytes": None,
                   "model_dtypes": None,
                   "model_metrics_reason": "model_metrics_unavailable"})
    if nlp is not None:
        try:
            parameters, buffers, dtypes = _model_footprint(nlp)
            values.update({"parameter_bytes": parameters, "buffer_bytes": buffers,
                           "model_dtypes": dtypes, "model_metrics_reason": None})
        except Exception:
            pass
    return values


def _record_worker_error(run_id: str, workers: int, code: str,
                         source_results: dict[str, bool] | None = None,
                         settings_ok: bool | None = None,
                         gpu: tuple[bool, int | None, bool | None, str | None] | None = None) -> None:
    fields: dict[str, Any] = {"error_code": code}
    if source_results is not None:
        fields.update(_source_fields(source_results))
    if settings_ok is not None:
        fields.update({"settings_ok": settings_ok,
                       "auth_upstream": os.environ.get("PII_AUTH_MODE") == "upstream",
                       "analysis_timeout_seconds": 60,
                       "max_concurrent_analyses": 16,
                       "max_queued_analyses": 32,
                       "queue_timeout_seconds": 30,
                       "gunicorn_threads": _ACTIVE_THREADS})
    if gpu is not None:
        fields.update({"gpu_l40s": gpu[2], "gpu_device_count": gpu[1],
                       "gpu_reason": gpu[3]})
    emit_event("startup_failed", run_id, os.getpid(), workers, **fields)


def _worker_module(worker: Any) -> Any:
    wsgi = getattr(worker, "wsgi", None)
    return getattr(wsgi, "module", None)


def _ready_event_fields(source_results: dict[str, bool], settings_ok: bool,
                        gpu: tuple[bool, int | None, bool | None, str | None],
                        nlp: Any, torch_module: Any) -> dict[str, Any]:
    fields = _source_fields(source_results)
    fields.update({
        "settings_ok": settings_ok,
        "auth_upstream": os.environ.get("PII_AUTH_MODE") == "upstream",
        "analysis_timeout_seconds": 60,
        "max_concurrent_analyses": 16,
        "max_queued_analyses": 32,
        "queue_timeout_seconds": 30,
        "gunicorn_threads": _ACTIVE_THREADS,
        "gpu_l40s": gpu[2],
        "gpu_device_count": gpu[1],
        "gpu_reason": gpu[3],
    })
    fields.update(_event_metrics(torch_module, nlp))
    return fields


def post_worker_init(worker: Any) -> None:
    run_id = _ACTIVE_RUN_ID
    workers = _ACTIVE_WORKERS
    if run_id is None or workers is None:
        raise RuntimeError("worker profile unavailable")
    pid = os.getpid()
    source_results = verify_sources()
    if not all(source_results.values()):
        _record_worker_error(run_id, workers, "source_integrity_failed", source_results)
        raise RuntimeError("worker startup failed") from None
    settings_ok = _resolved_settings() and _ACTIVE_THREADS == EXPECTED_THREADS
    if not settings_ok:
        _record_worker_error(run_id, workers, "settings_mismatch", source_results,
                             settings_ok=False)
        raise RuntimeError("worker startup failed") from None
    module = _worker_module(worker)
    nlp = getattr(module, "nlp", None) if module is not None else None
    device = getattr(module, "device", None) if module is not None else None
    if nlp is None or device != 0 or not callable(getattr(module, "detect_model", None)):
        _record_worker_error(run_id, workers, "startup_failed", source_results,
                             settings_ok=True)
        raise RuntimeError("worker startup failed") from None
    try:
        import torch
    except Exception:
        _record_worker_error(run_id, workers, "gpu_profile_mismatch", source_results,
                             settings_ok=True)
        raise RuntimeError("worker startup failed") from None
    gpu = _gpu_profile(torch)
    if gpu[3] is not None:
        _record_worker_error(run_id, workers, "gpu_profile_mismatch", source_results,
                             settings_ok=True, gpu=gpu)
        raise RuntimeError("worker startup failed") from None
    try:
        module.detect_model(FIXTURE_TEXT)
        torch.cuda.synchronize(0)
        parameter_bytes, buffer_bytes, model_dtypes = _model_footprint(nlp)
        if not model_dtypes:
            raise RuntimeError("model metrics unavailable")
    except Exception:
        _record_worker_error(run_id, workers, "startup_failed", source_results,
                             settings_ok=True, gpu=gpu)
        raise RuntimeError("worker startup failed") from None
    start_ticks = _proc_start_ticks(pid)
    if start_ticks is None:
        _record_worker_error(run_id, workers, "pid_unavailable", source_results,
                             settings_ok=True, gpu=gpu)
        raise RuntimeError("worker startup failed") from None
    run_path = _runtime_path(_ACTIVE_RUNTIME_ROOT, run_id)
    try:
        _write_ready_marker(run_path, run_id, pid, start_ticks)
        worker._verda_start_ticks = start_ticks
    except RuntimeError:
        _record_worker_error(run_id, workers, "startup_failed", source_results,
                             settings_ok=True, gpu=gpu)
        raise RuntimeError("worker startup failed") from None
    if not wait_for_worker_barrier(run_path, run_id, workers):
        try:
            _marker_path(run_path, pid).unlink(missing_ok=True)
        except OSError:
            pass
        _record_worker_error(run_id, workers, "barrier_timeout", source_results,
                             settings_ok=True, gpu=gpu)
        raise RuntimeError("worker startup failed") from None
    fields = _ready_event_fields(source_results, settings_ok, gpu, nlp, torch)
    fields.update({"parameter_bytes": parameter_bytes,
                   "buffer_bytes": buffer_bytes,
                   "model_dtypes": model_dtypes})
    emit_event("ready", run_id, pid, workers, **fields)
    stop = threading.Event()
    worker._verda_stop_event = stop
    worker._verda_request_count = 0
    thread = threading.Thread(target=_telemetry_loop,
                              args=(stop, worker, run_id, workers, torch),
                              daemon=True, name="verda-runtime-telemetry")
    worker._verda_telemetry_thread = thread
    thread.start()


def _telemetry_loop(stop: threading.Event, worker: Any, run_id: str,
                    workers: int, torch_module: Any) -> None:
    while not stop.wait(TELEMETRY_INTERVAL_SECONDS):
        module = _worker_module(worker)
        nlp = getattr(module, "nlp", None) if module is not None else None
        source_results = verify_sources()
        fields = _source_fields(source_results)
        fields.update({
            "settings_ok": _resolved_settings() and _ACTIVE_THREADS == EXPECTED_THREADS,
            "auth_upstream": os.environ.get("PII_AUTH_MODE") == "upstream",
            "analysis_timeout_seconds": 60,
            "max_concurrent_analyses": 16,
            "max_queued_analyses": 32,
            "queue_timeout_seconds": 30,
            "gunicorn_threads": _ACTIVE_THREADS,
            "request_count": int(getattr(worker, "_verda_request_count", 0)),
        })
        fields.update(_event_metrics(torch_module, nlp))
        gpu = _gpu_profile(torch_module)
        fields.update({"gpu_l40s": gpu[2], "gpu_device_count": gpu[1],
                       "gpu_reason": gpu[3]})
        emit_event("sample", run_id, os.getpid(), workers, **fields)


def post_request(worker: Any, req: Any, environ: Any, resp: Any) -> None:
    worker._verda_request_count = int(
        getattr(worker, "_verda_request_count", 0)) + 1


def worker_exit(server: Any, worker: Any) -> None:
    run_id = _ACTIVE_RUN_ID
    workers = _ACTIVE_WORKERS
    if run_id is None or workers is None:
        return
    stop = getattr(worker, "_verda_stop_event", None)
    if stop is not None:
        stop.set()
    thread = getattr(worker, "_verda_telemetry_thread", None)
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=TELEMETRY_INTERVAL_SECONDS + 1)
    count = int(getattr(worker, "_verda_request_count", 0))
    emit_event("exit", run_id, int(getattr(worker, "pid", os.getpid())),
               workers, request_count=count)


def child_exit(server: Any, worker: Any) -> None:
    run_id = _ACTIVE_RUN_ID
    workers = _ACTIVE_WORKERS
    if run_id is None or workers is None:
        return
    pid = getattr(worker, "pid", None)
    removed = False
    if type(pid) is int and pid > 0:
        path = _runtime_path(_ACTIVE_RUNTIME_ROOT, run_id)
        marker = _marker_path(path, pid)
        expected_ticks = getattr(worker, "_verda_start_ticks", None)
        try:
            marker_info = marker.lstat()
            if (not stat.S_ISREG(marker_info.st_mode)
                    or marker_info.st_uid != os.getuid()
                    or stat.S_IMODE(marker_info.st_mode) != 0o600):
                raise OSError
            payload = json.loads(marker.read_text(encoding="ascii"))
            if (isinstance(payload, dict) and payload.get("run_id") == run_id
                    and payload.get("pid") == pid
                    and (expected_ticks is None
                         or payload.get("start_ticks") == expected_ticks)):
                marker.unlink()
                removed = True
        except (OSError, ValueError):
            pass
    emit_event("child_exit", run_id, int(pid) if type(pid) is int else 0,
               workers, marker_removed=removed)


def evaluate_resource_guard(workers: int, observed: dict[str, Any],
                            limits: dict[str, Any],
                            loading_margin_bytes: int) -> dict[str, Any]:
    from .resources import evaluate_resource_guard as evaluate
    return evaluate(workers, observed, limits, loading_margin_bytes)
