from __future__ import annotations

from typing import Any

PROSPECTIVE_WORKERS = frozenset({2, 4, 8, 12, 16})


def evaluate_resource_guard(workers: int, observed: dict[str, Any],
                            limits: dict[str, Any],
                            loading_margin_bytes: int) -> dict[str, Any]:
    """Evaluate scale-up against a completed earlier run and finite limits."""
    result = {
        "allowed": False,
        "reason": "resource_data_unknown",
        "workers": workers if type(workers) is int else None,
        "projected_memory_bytes": None,
        "required_memory_bytes": None,
        "memory_limit_bytes": None,
        "projected_pids": None,
        "required_pids": None,
        "pids_limit": None,
        "effective_pid_guard_limit": None,
        "experiment_pids_budget": None,
        "pids_guard_source": None,
        "additional_gpu_bytes": None,
        "current_gpu_used_bytes": None,
        "projected_gpu_used_bytes": None,
        "required_gpu_total_bytes": None,
        "gpu_free_bytes": None,
        "gpu_total_bytes": None,
    }
    if type(workers) is not int or workers not in PROSPECTIVE_WORKERS:
        result["reason"] = "unsupported_workers"
        return result
    if not isinstance(observed, dict) or not isinstance(limits, dict):
        return result
    if workers > 8 and (
        type(observed.get("batch_size")) is not int
        or observed.get("batch_size") != 8
    ):
        result["reason"] = "actual_b8_observation_required"
        return result
    current_workers = observed.get("current_workers")
    per_worker_memory = observed.get("per_worker_peak_bytes")
    per_worker_pids = observed.get("per_worker_pids")
    memory_current = limits.get("memory_current_bytes")
    memory_limit = limits.get("memory_limit_bytes")
    pids_current = limits.get("pids_current")
    pids_limit = limits.get("pids_limit")
    budget_provided = "experiment_pids_budget" in limits
    experiment_pids_budget = limits.get("experiment_pids_budget")
    per_worker_gpu_peak = observed.get("observed_per_worker_gpu_peak_bytes")
    gpu_free = limits.get("gpu_free_bytes")
    gpu_total = limits.get("gpu_total_bytes")
    result["memory_limit_bytes"] = memory_limit if type(memory_limit) is int else None
    result["pids_limit"] = pids_limit if type(pids_limit) is int else None
    result["gpu_free_bytes"] = gpu_free if type(gpu_free) is int else None
    result["gpu_total_bytes"] = gpu_total if type(gpu_total) is int else None
    if budget_provided:
        if (type(experiment_pids_budget) is not int
                or not 1 <= experiment_pids_budget <= 512):
            result["reason"] = "experiment_pids_budget_invalid"
            return result
        result["experiment_pids_budget"] = experiment_pids_budget
    if type(pids_limit) is int:
        effective_pid_guard_limit = pids_limit
        result["pids_guard_source"] = "actual_pids_limit"
        if budget_provided and experiment_pids_budget < pids_limit:
            effective_pid_guard_limit = experiment_pids_budget
            result["pids_guard_source"] = "experiment_pids_budget"
        result["effective_pid_guard_limit"] = effective_pid_guard_limit
    elif (pids_limit is None and "pids_limit" in limits and budget_provided
          and type(limits.get("pids_limit_state")) is str
          and limits.get("pids_limit_state") == "unbounded"
          and type(limits.get("pids_limit_reason")) is str
          and limits.get("pids_limit_reason") == "limit_unavailable"):
        effective_pid_guard_limit = experiment_pids_budget
        result["effective_pid_guard_limit"] = effective_pid_guard_limit
        result["pids_guard_source"] = "experiment_pids_budget"
    else:
        effective_pid_guard_limit = None
    required_values = (
        (current_workers, "worker_count_unknown"),
        (per_worker_memory, "observed_memory_unknown"),
        (per_worker_pids, "observed_pids_unknown"),
        (memory_current, "memory_current_unknown"),
        (memory_limit, "memory_limit_unknown"),
        (pids_current, "pids_current_unknown"),
        (effective_pid_guard_limit, "pids_limit_unknown"),
        (loading_margin_bytes, "loading_margin_unknown"),
    )
    for value, reason in required_values:
        if type(value) is not int:
            result["reason"] = reason
            return result
        if value < 0:
            result["reason"] = "invalid_observation"
            return result
    gpu_values = (
        (per_worker_gpu_peak, "gpu_per_worker_peak_unknown"),
        (gpu_free, "gpu_free_unknown"),
        (gpu_total, "gpu_total_unknown"),
    )
    for value, reason in gpu_values:
        if type(value) is not int:
            result["reason"] = reason
            return result
        if value < 0:
            result["reason"] = "invalid_observation"
            return result
    if current_workers < 1 or current_workers >= workers:
        result["reason"] = "invalid_observation"
        return result
    if (per_worker_memory < 1 or per_worker_pids < 1
            or per_worker_gpu_peak < 1 or loading_margin_bytes < 1
            or gpu_total < 1 or gpu_free > gpu_total):
        result["reason"] = (
            "gpu_limits_inconsistent" if gpu_total < 1 or gpu_free > gpu_total
            else "invalid_observation"
        )
        return result
    extra_workers = workers - current_workers
    projected_memory = memory_current + extra_workers * per_worker_memory + loading_margin_bytes
    required_memory = (projected_memory * 5 + 3) // 4
    projected_pids = pids_current + extra_workers * per_worker_pids
    required_pids = (projected_pids * 5 + 3) // 4
    additional_gpu = extra_workers * per_worker_gpu_peak + loading_margin_bytes
    current_gpu_used = gpu_total - gpu_free
    projected_gpu_used = current_gpu_used + additional_gpu
    required_gpu_total = (projected_gpu_used * 5 + 3) // 4
    result.update({
        "projected_memory_bytes": projected_memory,
        "required_memory_bytes": required_memory,
        "memory_limit_bytes": memory_limit,
        "projected_pids": projected_pids,
        "required_pids": required_pids,
        "pids_limit": pids_limit,
        "effective_pid_guard_limit": effective_pid_guard_limit,
        "additional_gpu_bytes": additional_gpu,
        "current_gpu_used_bytes": current_gpu_used,
        "projected_gpu_used_bytes": projected_gpu_used,
        "required_gpu_total_bytes": required_gpu_total,
        "gpu_free_bytes": gpu_free,
        "gpu_total_bytes": gpu_total,
    })
    if memory_limit == 0 or effective_pid_guard_limit == 0:
        result["reason"] = "resource_limit_unknown"
        return result
    if memory_limit < required_memory:
        result["reason"] = "memory_headroom_insufficient"
        return result
    if effective_pid_guard_limit < required_pids:
        result["reason"] = "pid_headroom_insufficient"
        return result
    if gpu_total < required_gpu_total:
        result["reason"] = "gpu_headroom_insufficient"
        return result
    result.update({"allowed": True, "reason": (
        "experiment_pid_guard_verified"
        if result["pids_guard_source"] == "experiment_pids_budget"
        else "headroom_verified"
    )})
    return result
