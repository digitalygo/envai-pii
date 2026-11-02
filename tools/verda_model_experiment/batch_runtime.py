import ast
import hashlib
import json
import marshal
import os
import stat
import sys
import time
import types
from pathlib import Path

from . import gpu_runtime, runtime
from .fixture import FIXTURE_TEXT

BATCH_SIZE_ENV = "PII_MODEL_BATCH_SIZE"
SUPPORTED_BATCH_SIZES = (1, 4, 8, 16)
BATCH_PROFILE_WORKERS = gpu_runtime.GPU_PROFILE_WORKERS
BATCH_PROFILE_WORKER_CHOICES = gpu_runtime.GPU_PROFILE_WORKER_CHOICES
FIXTURE_CHUNKS = 63
WARM_TIMEOUT_SECONDS = 60.0
EVENT_PREFIX = "VERDABATCH "
EVENT_LIMIT_BYTES = 4096
READY_EVENT_FIELDS = frozenset({
    "event", "run_id", "pid", "workers", "batch_size",
    "base_app_sha256", "helper_sha256", "detector_source_sha256",
    "detector_code_sha256", "manifest_sha256", "installed_code_ok",
    "installed_defaults_ok", "globals_ok", "legacy_ok", "binder_ok",
    "base_app_ok", "overlay_ok", "warm_calls", "warm_max_batch",
    "warm_sum_batches", "fixture_chunks", "warm_ok",
})
FAILED_EVENT_FIELDS = frozenset({
    "event", "run_id", "pid", "workers", "startup_ok",
})
READY_HASH_FIELDS = frozenset({
    "base_app_sha256", "helper_sha256", "detector_source_sha256",
    "detector_code_sha256", "manifest_sha256",
})
READY_BOOLEAN_FIELDS = frozenset({
    "installed_code_ok", "installed_defaults_ok", "globals_ok", "legacy_ok",
    "binder_ok", "base_app_ok", "overlay_ok", "warm_ok",
})
READY_INTEGER_FIELDS = frozenset({
    "pid", "workers", "batch_size", "warm_calls", "warm_max_batch",
    "warm_sum_batches", "fixture_chunks",
})
ASSET_ROOT = Path(__file__).with_name("batch_overlay")
MANIFEST_NAME = "manifest.json"
HELPER_ASSET = "tools/verda_model_experiment/batch_overlay/model_batching.py"
DETECTOR_ASSET = "tools/verda_model_experiment/batch_overlay/guardrail_detect.py"
MANIFEST_FORMAT = "envai-pii-batch-overlay-1"
TARGET_FUNCTION = "_guardrail_detect"
EXTRACTED_LIMIT_BYTES = 128 * 1024
DETECTOR_CODE_LIMIT_BYTES = 16 * 1024
CODE_HASH_PYTHON_VERSION = sys.version_info[:2]
ALLOWED_NAMES = frozenset("""
_merge MODEL_BATCH_SIZE MODEL_LANE ModelUnavailable append chunk_groups
chunk_text complete_time detect_regex dict end entity_group enumerate float
guardrail_api int isinstance len list model_batching normalize_batch_results
nlp run runtime_execution score start tuple
""".split())
FORBIDDEN_NODES = tuple(
    value for value in (
        ast.AsyncFunctionDef, ast.Await, ast.ClassDef, ast.Global, ast.Import,
        ast.ImportFrom, ast.Lambda, ast.NamedExpr, ast.Nonlocal, ast.Try,
        getattr(ast, "TryStar", None), ast.With, ast.AsyncWith, ast.Yield,
        ast.YieldFrom,
    ) if value is not None
)


class BatchOverlayError(RuntimeError):
    pass


class _ModelProxy:
    def __init__(self, model, calls):
        self._model = model
        self._calls = calls

    def __call__(self, texts, **kwargs):
        self._calls.append((
            len(texts), kwargs.get("batch_size"), tuple(sorted(kwargs))))
        return self._model(texts, **kwargs)

    def __getattr__(self, name):
        return getattr(self._model, name)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _is_sha(value):
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _read_private_file(path):
    descriptor = None
    try:
        descriptor = os.open(
            path, os.O_RDONLY | os.O_NONBLOCK
            | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size > EXTRACTED_LIMIT_BYTES):
            raise BatchOverlayError
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            data = stream.read(EXTRACTED_LIMIT_BYTES + 1)
    except OSError:
        raise BatchOverlayError from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(data) > EXTRACTED_LIMIT_BYTES:
        raise BatchOverlayError
    return data


def compile_detector(fragment, *, source_sha256=None, code_sha256=None):
    if not isinstance(fragment, bytes) or len(fragment) > EXTRACTED_LIMIT_BYTES:
        raise BatchOverlayError
    if source_sha256 is not None and _sha(fragment) != source_sha256:
        raise BatchOverlayError
    try:
        tree = ast.parse(
            fragment.decode("utf-8"), "<verified-guardrail-detect>", "exec")
    except (UnicodeDecodeError, SyntaxError, ValueError):
        raise BatchOverlayError from None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise BatchOverlayError
    node = tree.body[0]
    args = node.args
    if (node.name != TARGET_FUNCTION or node.decorator_list
            or args.posonlyargs or args.vararg or args.kwonlyargs or args.kwarg
            or any(arg.annotation is not None for arg in args.args)
            or [arg.arg for arg in args.args]
            != ["text", "check_deadline", "categories"]
            or len(args.defaults) != 1
            or not isinstance(args.defaults[0], ast.Constant)
            or args.defaults[0].value is not None
            or node.returns is not None
            or any(isinstance(child, FORBIDDEN_NODES)
                   for child in ast.walk(node))):
        raise BatchOverlayError
    module = compile(
        ast.Module(body=[node], type_ignores=[]),
        "<verified-guardrail-detect>", "exec")
    codes = [
        value for value in module.co_consts
        if isinstance(value, types.CodeType) and value.co_name == TARGET_FUNCTION
    ]
    if len(codes) != 1:
        raise BatchOverlayError
    code = codes[0]
    if (len(code.co_code) > DETECTOR_CODE_LIMIT_BYTES
            or code.co_argcount != 3 or code.co_kwonlyargcount != 0
            or code.co_varnames[:3] != ("text", "check_deadline", "categories")
            or code.co_freevars != () or code.co_flags & 0x0C
            or not set(code.co_names).issubset(ALLOWED_NAMES)):
        raise BatchOverlayError
    function = types.FunctionType(
        code, {"__builtins__": {}}, TARGET_FUNCTION, (None,))
    if function.__code__ is not code or function.__kwdefaults__ is not None:
        raise BatchOverlayError
    if code_sha256 is not None and _sha(marshal.dumps(code)) != code_sha256:
        raise BatchOverlayError
    return function


def _load_helper(assets_root, manifest):
    path = assets_root / Path(HELPER_ASSET).name
    data = _read_private_file(path)
    if _sha(data) != manifest["helper_sha256"]:
        raise BatchOverlayError
    module = types.ModuleType("model_batching")
    module.__file__ = str(path)
    try:
        exec(compile(data, module.__file__, "exec"), module.__dict__)
    except Exception:
        raise BatchOverlayError from None
    if (not callable(getattr(module, "chunk_groups", None))
            or not callable(getattr(module, "normalize_batch_results", None))
            or tuple(getattr(module, "SUPPORTED_BATCH_SIZES", ()))
            != SUPPORTED_BATCH_SIZES):
        raise BatchOverlayError
    return module


def _manifest_object(pairs):
    manifest = {}
    for key, value in pairs:
        if key in manifest:
            raise BatchOverlayError
        manifest[key] = value
    return manifest


def _validate_manifest(manifest):
    expected_fields = {
        "format", "base_app_sha256", "helper_sha256",
        "detector_source_sha256", "detector_code_sha256",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_fields:
        raise BatchOverlayError
    if (manifest.get("format") != MANIFEST_FORMAT
            or not all(_is_sha(manifest.get(field)) for field in (
                "base_app_sha256", "helper_sha256",
                "detector_source_sha256", "detector_code_sha256"))):
        raise BatchOverlayError
    return manifest


def _load_manifest(assets_root):
    data = _read_private_file(assets_root / MANIFEST_NAME)
    try:
        manifest = json.loads(data, object_pairs_hook=_manifest_object)
    except (UnicodeDecodeError, ValueError):
        raise BatchOverlayError from None
    return _validate_manifest(manifest), _sha(data)


def _batch_size_from_env():
    raw = os.environ.get(BATCH_SIZE_ENV)
    if raw is None or raw == "":
        return 1
    if raw not in ("1", "4", "8", "16"):
        raise BatchOverlayError
    return int(raw)


def _binder_is_bound(module, function):
    binder = module.__dict__.get("_guardrail_detect_for_categories")
    return (isinstance(binder, types.FunctionType)
            and module.__dict__.get(TARGET_FUNCTION) is function
            and any(isinstance(value, types.CodeType)
                    and TARGET_FUNCTION in value.co_names
                    for value in binder.__code__.co_consts))


def _install(module, app_root, assets_root, manifest):
    _validate_manifest(manifest)
    try:
        app_data = (Path(app_root) / "app.py").read_bytes()
    except OSError:
        raise BatchOverlayError from None
    if _sha(app_data) != manifest["base_app_sha256"]:
        raise BatchOverlayError
    helper = _load_helper(assets_root, manifest)
    detector_data = _read_private_file(assets_root / Path(DETECTOR_ASSET).name)
    if _sha(detector_data) != manifest["detector_source_sha256"]:
        raise BatchOverlayError
    detector = compile_detector(
        detector_data,
        source_sha256=manifest["detector_source_sha256"],
        code_sha256=manifest["detector_code_sha256"])
    batch_size = _batch_size_from_env()
    original = module.__dict__.get(TARGET_FUNCTION)
    legacy = module.__dict__.get("detect_model")
    if not isinstance(original, types.FunctionType):
        raise BatchOverlayError
    code = original.__code__
    if (code.co_argcount != 3 or code.co_kwonlyargcount != 0
            or code.co_varnames[:3] != ("text", "check_deadline", "categories")
            or code.co_freevars != () or code.co_flags & 0x0C
            or original.__defaults__ != (None,)
            or original.__kwdefaults__ is not None
            or original.__globals__ is not module.__dict__
            or not callable(legacy)
            or not _binder_is_bound(module, original)):
        raise BatchOverlayError
    defaults = original.__defaults__
    kwdefaults = original.__kwdefaults__
    legacy_code = legacy.__code__
    missing = object()
    previous_globals = {
        name: module.__dict__.get(name, missing)
        for name in ("model_batching", "MODEL_BATCH_SIZE")
    }
    try:
        module.__dict__["model_batching"] = helper
        module.__dict__["MODEL_BATCH_SIZE"] = batch_size
        original.__code__ = detector.__code__
        original.__defaults__ = detector.__defaults__
        original.__kwdefaults__ = detector.__kwdefaults__
        if not (
                module.__dict__.get(TARGET_FUNCTION) is original
                and original.__code__ is detector.__code__
                and original.__defaults__ == detector.__defaults__
                and original.__kwdefaults__ is detector.__kwdefaults__
                and original.__globals__ is module.__dict__
                and module.__dict__.get("model_batching") is helper
                and module.__dict__.get("MODEL_BATCH_SIZE") == batch_size
                and module.__dict__.get("detect_model") is legacy
                and legacy.__code__ is legacy_code
                and _binder_is_bound(module, original)):
            raise BatchOverlayError
    except BaseException:
        original.__code__ = code
        original.__defaults__ = defaults
        original.__kwdefaults__ = kwdefaults
        for name, value in previous_globals.items():
            if value is missing:
                module.__dict__.pop(name, None)
            else:
                module.__dict__[name] = value
        raise
    return {
        "batch_size": batch_size,
        "base_app_sha256": manifest["base_app_sha256"],
        "helper_sha256": manifest["helper_sha256"],
        "detector_source_sha256": manifest["detector_source_sha256"],
        "detector_code_sha256": manifest["detector_code_sha256"],
        "manifest_sha256": _sha(json.dumps(
            manifest, sort_keys=True, separators=(",", ":")).encode()),
        "installed_code_ok": True,
        "installed_defaults_ok": True,
        "globals_ok": True,
        "legacy_ok": True,
        "binder_ok": True,
        "base_app_ok": True,
        "overlay_ok": True,
    }


def _warm_v1(module, batch_size, *, clock=time.monotonic,
             timeout=WARM_TIMEOUT_SECONDS):
    if batch_size not in SUPPORTED_BATCH_SIZES:
        raise BatchOverlayError
    chunks = list(module.chunk_text(FIXTURE_TEXT))
    if len(chunks) != FIXTURE_CHUNKS:
        raise BatchOverlayError
    original = module.__dict__.get("nlp")
    if original is None:
        raise BatchOverlayError
    calls = []
    deadline = clock() + timeout

    def check_deadline():
        if clock() > deadline:
            raise BatchOverlayError

    module.__dict__["nlp"] = _ModelProxy(original, calls)
    try:
        module.__dict__[TARGET_FUNCTION](FIXTURE_TEXT, check_deadline)
    except Exception:
        raise BatchOverlayError from None
    finally:
        module.__dict__["nlp"] = original
    if module.__dict__.get("nlp") is not original:
        raise BatchOverlayError
    expected_calls = (FIXTURE_CHUNKS + batch_size - 1) // batch_size
    expected = ([batch_size] * (expected_calls - 1)
                + [FIXTURE_CHUNKS - (expected_calls - 1) * batch_size])
    if [call[0] for call in calls] != expected:
        raise BatchOverlayError
    for length, recorded, names in calls:
        if batch_size == 1:
            if recorded is not None or names != ():
                raise BatchOverlayError
        elif recorded != batch_size or names != ("batch_size",):
            raise BatchOverlayError
    return {
        "batch_size": batch_size,
        "warm_calls": len(calls),
        "warm_max_batch": max(expected),
        "warm_sum_batches": sum(expected),
        "fixture_chunks": FIXTURE_CHUNKS,
        "warm_ok": True,
    }


def _emit(event, fields):
    if (not isinstance(event, str) or event not in {"ready", "failed"}
            or not isinstance(fields, dict)):
        return
    if "event" in fields:
        return
    payload = {"event": event, **fields}
    expected_fields = (
        READY_EVENT_FIELDS if event == "ready" else FAILED_EVENT_FIELDS)
    if set(payload) != expected_fields:
        return
    if (not isinstance(payload["run_id"], str)
            or type(payload["pid"]) is not int or payload["pid"] < 1
            or type(payload["workers"]) is not int
            or payload["workers"] not in BATCH_PROFILE_WORKER_CHOICES):
        return
    try:
        runtime.validate_run_id(payload["run_id"])
    except ValueError:
        return
    if event == "failed":
        if payload["startup_ok"] is not False:
            return
    else:
        if (type(payload["batch_size"]) is not int
                or payload["batch_size"] not in SUPPORTED_BATCH_SIZES
                or any(not _is_sha(payload[key]) for key in READY_HASH_FIELDS)
                or any(type(payload[key]) is not bool
                       or payload[key] is not True
                       for key in READY_BOOLEAN_FIELDS)
                or any(type(payload[key]) is not int or payload[key] < 0
                       for key in READY_INTEGER_FIELDS)):
            return
        batch_size = payload["batch_size"]
        expected_calls = (FIXTURE_CHUNKS + batch_size - 1) // batch_size
        if (payload["fixture_chunks"] != FIXTURE_CHUNKS
                or payload["warm_sum_batches"] != FIXTURE_CHUNKS
                or payload["warm_calls"] != expected_calls
                or payload["warm_max_batch"] != batch_size):
            return
    try:
        line = (EVENT_PREFIX + json.dumps(
            payload, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        if len(line) <= EVENT_LIMIT_BYTES:
            os.write(1, line)
    except (OSError, UnicodeEncodeError, ValueError):
        return


def _wrap_post_worker_init(base_hook, *, app_root=runtime.APP_SOURCE,
                           assets_root=ASSET_ROOT, manifest=None,
                           clock=time.monotonic):
    def post_worker_init(worker):
        run_id = runtime._ACTIVE_RUN_ID
        workers = runtime._ACTIVE_WORKERS
        if run_id is None or workers not in BATCH_PROFILE_WORKER_CHOICES:
            raise RuntimeError("worker startup failed")
        module = getattr(getattr(worker, "wsgi", None), "module", None)
        try:
            if module is None:
                raise BatchOverlayError
            selected = (_load_manifest(assets_root)[0]
                        if manifest is None else _validate_manifest(manifest))
            evidence = _install(
                module, Path(app_root), Path(assets_root), selected)
            warm = _warm_v1(
                module, evidence["batch_size"], clock=clock,
                timeout=WARM_TIMEOUT_SECONDS)
        except BaseException:
            _emit("failed", {
                "run_id": run_id, "pid": os.getpid(), "workers": workers,
                "startup_ok": False,
            })
            raise RuntimeError("worker startup failed") from None
        try:
            base_hook(worker)
        except BaseException:
            _emit("failed", {
                "run_id": run_id, "pid": os.getpid(), "workers": workers,
                "startup_ok": False,
            })
            raise RuntimeError("worker startup failed") from None
        _emit("ready", {
            **evidence, **warm,
            "run_id": run_id, "pid": os.getpid(), "workers": workers,
        })
    return post_worker_init


def load_gunicorn_config(*, app_root=runtime.APP_SOURCE,
                         runtime_root=runtime.RUNTIME_ROOT):
    config = gpu_runtime.load_gunicorn_config(
        app_root=app_root, runtime_root=runtime_root)
    if config.get("workers") not in BATCH_PROFILE_WORKER_CHOICES:
        raise RuntimeError("batch profile requires a supported worker count")
    base_post = config.get("post_worker_init")
    if not callable(base_post):
        raise RuntimeError("base gunicorn hooks unavailable")
    wrapped = dict(config)
    wrapped["post_worker_init"] = _wrap_post_worker_init(
        base_post, app_root=app_root)
    return wrapped
