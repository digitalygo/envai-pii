"""Opt-in Gunicorn configuration wrapper for GPU worker-count observation."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from . import gpu_monitor, runtime

GPU_PROFILE_WORKERS = gpu_monitor.PROFILE_WORKERS
GPU_PROFILE_WORKER_CHOICES = gpu_monitor.PROFILE_WORKER_CHOICES
OWNER_FILE_NAME = "gpu-owner.json"


def cuda0_uuid(torch_module: Any) -> object | None:
    if torch_module is None:
        return None
    try:
        properties = torch_module.cuda.get_device_properties(0)
    except Exception:
        return None
    try:
        return getattr(properties, "uuid", None)
    except Exception:
        return None


def _owner_path(run_path: Path) -> Path:
    return run_path / OWNER_FILE_NAME


def _owner_payload(run_id: str, pid: int) -> bytes:
    return json.dumps({
        "run_id": run_id,
        "pid": pid,
    }, sort_keys=True, separators=(",", ":")).encode("ascii")


def _claim_gpu_owner(run_path: Path, run_id: str, pid: int) -> bool:
    live = runtime._read_live_markers(run_path, run_id)
    if not live or min(live) != pid:
        return False
    payload = _owner_payload(run_id, pid)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(_owner_path(run_path), flags, 0o600)
    except OSError:
        return False
    try:
        os.write(descriptor, payload)
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    except OSError:
        return False
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    return True


def _owner_still_active(run_path: Path, run_id: str, pid: int) -> bool:
    try:
        info = _owner_path(run_path).lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            return False
        payload = json.loads(_owner_path(run_path).read_text(encoding="ascii"))
    except (OSError, ValueError):
        return False
    if payload != {"run_id": run_id, "pid": pid}:
        return False
    return pid in runtime._read_live_markers(run_path, run_id)


def _load_torch() -> Any | None:
    try:
        import torch
    except Exception:
        return None
    return torch


def _start_worker_monitor(worker: Any) -> None:
    run_id = runtime._ACTIVE_RUN_ID
    workers = runtime._ACTIVE_WORKERS
    if run_id is None or workers not in GPU_PROFILE_WORKER_CHOICES:
        return
    pid = os.getpid()
    run_path = runtime._runtime_path(runtime._ACTIVE_RUNTIME_ROOT, run_id)
    if not _claim_gpu_owner(run_path, run_id, pid):
        return
    raw_uuid = cuda0_uuid(_load_torch())
    monitor = gpu_monitor.GpuMonitor(
        run_id=run_id,
        owner_pid=pid,
        cuda_uuid=raw_uuid,
        workers=workers,
        active=lambda: _owner_still_active(run_path, run_id, pid),
    )
    if monitor.start():
        worker._verda_gpu_monitor = monitor


def _stop_worker_monitor(worker: Any) -> None:
    monitor = getattr(worker, "_verda_gpu_monitor", None)
    worker._verda_gpu_monitor = None
    if monitor is None:
        return
    try:
        monitor.stop()
    except Exception:
        pass


def _wrap_post_worker_init(base_hook: Any) -> Any:
    def post_worker_init(worker: Any) -> None:
        base_hook(worker)
        try:
            _start_worker_monitor(worker)
        except Exception:
            pass
    return post_worker_init


def _wrap_worker_exit(base_hook: Any) -> Any:
    def worker_exit(server: Any, worker: Any) -> None:
        try:
            _stop_worker_monitor(worker)
        finally:
            base_hook(server, worker)
    return worker_exit


def load_gunicorn_config(*, app_root: Path = runtime.APP_SOURCE,
                         runtime_root: Path = runtime.RUNTIME_ROOT) -> dict[str, Any]:
    config = runtime.load_gunicorn_config(
        app_root=app_root, runtime_root=runtime_root)
    if config.get("workers") not in GPU_PROFILE_WORKER_CHOICES:
        raise RuntimeError("gpu profile requires a supported worker count")
    base_post = config.get("post_worker_init")
    base_exit = config.get("worker_exit")
    if not callable(base_post) or not callable(base_exit):
        raise RuntimeError("base gunicorn hooks unavailable")
    wrapped = dict(config)
    wrapped["post_worker_init"] = _wrap_post_worker_init(base_post)
    wrapped["worker_exit"] = _wrap_worker_exit(base_exit)
    return wrapped
