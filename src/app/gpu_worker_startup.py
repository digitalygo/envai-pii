import json
import os
import time


WORKER_COUNT_ENV = "PII_GUNICORN_WORKERS"
VERIFY_STARTUP_ENV = "PII_VERIFY_MODEL_STARTUP"
DEFAULT_WORKERS = 1
MAX_WORKERS = 8
SUPPORTED_BATCH_SIZES = (1, 4, 8, 16)
STARTUP_PROOF_TIMEOUT_SECONDS = 60.0
STARTUP_PROOF_CHUNK_COUNT = 63
STARTUP_PROOF_WORD_COUNT = 6252
MAX_TENSOR_BYTES = 1 << 50
MAX_TENSOR_COUNT = 100_000
MAX_LOG_LINE_LENGTH = 1024
STARTUP_PROOF_ERROR = "worker startup proof failed"
_WORKER_VALUES = {str(value): value for value in range(1, MAX_WORKERS + 1)}
_MISSING = object()


def resolve_gunicorn_workers(environ=None):
    source = os.environ if environ is None else environ
    raw = source.get(WORKER_COUNT_ENV)
    if type(raw) is not str:
        return DEFAULT_WORKERS
    return _WORKER_VALUES.get(raw.strip(), DEFAULT_WORKERS)


def post_worker_init(worker):
    if os.environ.get(VERIFY_STARTUP_ENV) != "1":
        return

    worker_count = None
    try:
        worker_count = _worker_count(worker)
        metadata = _run_startup_proof(worker, worker_count)
        _emit(worker.log.info, "PII_WORKER_READY", {
            "event": "ready",
            "pid": os.getpid(),
            **metadata,
        })
    except Exception:
        _emit_failure(worker, worker_count)
        raise RuntimeError(STARTUP_PROOF_ERROR) from None


def _worker_count(worker):
    value = worker.cfg.workers
    if type(value) is not int or not 1 <= value <= MAX_WORKERS:
        raise ValueError
    return value


def _run_startup_proof(worker, worker_count):
    module = worker.wsgi.module
    original_pipeline = module.nlp
    if original_pipeline is None:
        raise ValueError

    deadline_at = time.monotonic() + STARTUP_PROOF_TIMEOUT_SECONDS

    def check_deadline():
        if time.monotonic() >= deadline_at:
            raise TimeoutError

    calls = _PipelineCounter(original_pipeline, check_deadline)
    installed = False
    try:
        module.nlp = calls
        installed = True
        import torch

        check_deadline()
        if module.device != 0:
            raise ValueError
        model = getattr(original_pipeline, "model", None)
        if model is None:
            raise ValueError
        parameter_bytes = _tensor_collection_bytes(
            model.parameters, torch, check_deadline, require_floating=True)
        buffer_bytes = _tensor_collection_bytes(
            model.buffers, torch, check_deadline, require_floating=False)

        batch_size = module.MODEL_BATCH_SIZE
        if type(batch_size) is not int or batch_size not in SUPPORTED_BATCH_SIZES:
            raise ValueError
        text = "neutral " * (STARTUP_PROOF_WORD_COUNT - 1) + "neutral"
        chunk_count = len(module.chunk_text(text))
        if chunk_count != STARTUP_PROOF_CHUNK_COUNT:
            raise ValueError
        detect = module._guardrail_detect
        detect(text, check_deadline)
        check_deadline()
        torch.cuda.synchronize()
        check_deadline()

        expected_sizes = [
            min(batch_size, chunk_count - start)
            for start in range(0, chunk_count, batch_size)
        ]
        expected_explicit_sizes = (
            [None] * len(expected_sizes) if batch_size == 1
            else [batch_size] * len(expected_sizes)
        )
        if calls.input_sizes != expected_sizes:
            raise ValueError
        if calls.explicit_batch_sizes != expected_explicit_sizes:
            raise ValueError
        if len(calls.input_sizes) != (chunk_count + batch_size - 1) // batch_size:
            raise ValueError

        return {
            "workers": worker_count,
            "model_device": "cuda:0",
            "model_dtype": "float32",
            "parameter_bytes": parameter_bytes,
            "buffer_bytes": buffer_bytes,
            "model_batch_size": batch_size,
            "warmup_chunk_count": chunk_count,
            "warmup_call_count": len(calls.input_sizes),
            "warmup_input_count": sum(calls.input_sizes),
            "warmup_max_batch_size": max(calls.input_sizes),
            "warmup_tail_batch_size": calls.input_sizes[-1],
        }
    finally:
        if installed:
            module.nlp = original_pipeline


def _tensor_collection_bytes(collection, torch, check_deadline, *, require_floating):
    count = 0
    byte_count = 0
    for tensor in collection():
        check_deadline()
        count += 1
        if count > MAX_TENSOR_COUNT:
            raise ValueError
        if str(tensor.device) != "cuda:0":
            raise ValueError
        floating = tensor.is_floating_point()
        if type(floating) is not bool:
            raise ValueError
        if require_floating and not floating:
            raise ValueError
        if floating and tensor.dtype != torch.float32:
            raise ValueError
        elements = tensor.numel()
        element_bytes = tensor.element_size()
        if type(elements) is not int or elements < 0:
            raise ValueError
        if type(element_bytes) is not int or element_bytes < 1:
            raise ValueError
        byte_count += elements * element_bytes
        if byte_count > MAX_TENSOR_BYTES:
            raise ValueError
    if count == 0 or byte_count == 0:
        raise ValueError
    return byte_count


class _PipelineCounter:
    def __init__(self, pipeline, check_deadline):
        self._pipeline = pipeline
        self._check_deadline = check_deadline
        self.input_sizes = []
        self.explicit_batch_sizes = []

    def __call__(self, *args, **kwargs):
        self._check_deadline()
        if len(args) != 1 or len(self.input_sizes) >= STARTUP_PROOF_CHUNK_COUNT:
            raise ValueError
        inputs = args[0]
        if not isinstance(inputs, (list, tuple)) or not inputs:
            raise ValueError
        input_size = len(inputs)
        if input_size > max(SUPPORTED_BATCH_SIZES):
            raise ValueError

        explicit = kwargs.get("batch_size", _MISSING)
        if explicit is _MISSING:
            explicit_size = None
        elif type(explicit) is int and explicit in SUPPORTED_BATCH_SIZES:
            explicit_size = explicit
        else:
            raise ValueError

        self.input_sizes.append(input_size)
        self.explicit_batch_sizes.append(explicit_size)
        return self._pipeline(*args, **kwargs)


def _emit_failure(worker, worker_count):
    try:
        payload = json.dumps({
            "event": "startup_failed",
            "pid": os.getpid(),
            "workers": worker_count,
        }, sort_keys=True, separators=(",", ":"))
        line = f"PII_WORKER_STARTUP_FAILED {payload}"
        if len(line) <= MAX_LOG_LINE_LENGTH:
            worker.log.error(line)
    except Exception:
        return


def _emit(log_method, prefix, fields):
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    line = f"{prefix} {payload}"
    if len(line) > MAX_LOG_LINE_LENGTH:
        raise ValueError
    log_method(line)
