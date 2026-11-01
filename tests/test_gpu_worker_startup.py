import ast
import builtins
import importlib
import json
import os
import re
import subprocess
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "src" / "app"
APP_SOURCE = APP_DIR / "app.py"
sys.path.insert(0, str(APP_DIR))

import gpu_worker_startup
import model_batching
import runtime_execution


class FakeTensor:
    def __init__(self, elements, element_bytes, dtype, *, device="cuda:0",
                 floating=True):
        self.device = device
        self.dtype = dtype
        self._elements = elements
        self._element_bytes = element_bytes
        self._floating = floating

    def is_floating_point(self):
        return self._floating

    def numel(self):
        return self._elements

    def element_size(self):
        return self._element_bytes


class FakeModel:
    def __init__(self, parameters=None, buffers=None):
        self._parameters = parameters if parameters is not None else [
            FakeTensor(4, 4, "float32"),
            FakeTensor(6, 4, "float32"),
        ]
        self._buffers = buffers if buffers is not None else [
            FakeTensor(3, 8, "int64", floating=False),
            FakeTensor(2, 4, "float32"),
        ]

    def parameters(self):
        return iter(self._parameters)

    def buffers(self):
        return iter(self._buffers)


class RecordingPipeline:
    def __init__(self, model=None, *, error=None, result_factory=None):
        self.model = model if model is not None else FakeModel()
        self.error = error
        self.result_factory = result_factory
        self.calls = []

    def __call__(self, inputs, **kwargs):
        self.calls.append((len(inputs), kwargs.get("batch_size"),
                           threading.current_thread().name))
        if self.error is not None:
            raise self.error
        if self.result_factory is not None:
            return self.result_factory(inputs)
        return [[] for _ in inputs]


class FakeTorch:
    float32 = "float32"
    int64 = "int64"

    class Cuda:
        def __init__(self):
            self.synchronize_calls = 0

        def synchronize(self):
            self.synchronize_calls += 1

    def __init__(self):
        self.cuda = self.Cuda()


class CaptureLogger:
    def __init__(self):
        self.info_lines = []
        self.error_lines = []

    def info(self, line):
        self.info_lines.append(line)

    def error(self, line):
        self.error_lines.append(line)


class FakeWorker:
    def __init__(self, module, workers=8):
        self.cfg = types.SimpleNamespace(workers=workers)
        self.wsgi = types.SimpleNamespace(module=module)
        self.log = CaptureLogger()


def _fake_app(batch_size, pipeline):
    tree = ast.parse(APP_SOURCE.read_text(encoding="utf-8"))
    names = {"chunk_text", "_guardrail_detect"}
    functions = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {
        "MAX_WORDS": 120,
        "OVERLAP": 20,
        "MODEL_BATCH_SIZE": batch_size,
        "device": 0,
        "nlp": pipeline,
        "re": re,
        "model_batching": model_batching,
        "runtime_execution": runtime_execution,
        "guardrail_api": types.SimpleNamespace(ModelUnavailable=RuntimeError),
        "complete_time": lambda _entities, _text: None,
        "detect_regex": lambda _text: [],
        "_merge": lambda candidates, _text: candidates,
    }
    module = types.ModuleType("fake_app")
    module.__dict__.update(namespace)
    exec(compile(ast.Module(functions, type_ignores=[]), str(APP_SOURCE), "exec"),
         module.__dict__)
    return module


def _success_metadata(worker):
    line = worker.log.info_lines[0]
    prefix = "PII_WORKER_READY "
    if not line.startswith(prefix):
        raise AssertionError(line)
    return json.loads(line[len(prefix):])


def _assert_generic_startup_failure(testcase, worker, app, pipeline):
    testcase.assertIs(app.nlp, pipeline)
    testcase.assertEqual(worker.log.info_lines, [])
    testcase.assertEqual(len(worker.log.error_lines), 1)
    line = worker.log.error_lines[0]
    prefix = "PII_WORKER_STARTUP_FAILED "
    testcase.assertTrue(line.startswith(prefix))
    testcase.assertLessEqual(len(line), gpu_worker_startup.MAX_LOG_LINE_LENGTH)
    testcase.assertNotIn("SECRET", line)
    testcase.assertNotIn("neutral", line)
    testcase.assertEqual(set(json.loads(line[len(prefix):])),
                         {"event", "pid", "workers"})


class GunicornWorkerConfigurationTests(unittest.TestCase):
    def test_worker_count_defaults_and_accepts_only_canonical_bounded_values(self):
        self.assertEqual(gpu_worker_startup.resolve_gunicorn_workers({}), 1)
        for value in range(1, 9):
            with self.subTest(value=value):
                self.assertEqual(gpu_worker_startup.resolve_gunicorn_workers({
                    gpu_worker_startup.WORKER_COUNT_ENV: str(value)}), value)
        self.assertEqual(gpu_worker_startup.resolve_gunicorn_workers({
            gpu_worker_startup.WORKER_COUNT_ENV: " \t8\n"}), 8)

    def test_invalid_worker_values_fall_back_to_one(self):
        invalid = (
            "", " ", "0", "9", "01", "00", "+1", "-1", "1.0", "1e0",
            "８", "٨", "١", "1_0", "1 " * 2, "9" * 5000,
            True, False, None, 1, 8.0, b"8", [], {},
        )
        for value in invalid:
            with self.subTest(value=repr(value)[:24]):
                self.assertEqual(gpu_worker_startup.resolve_gunicorn_workers({
                    gpu_worker_startup.WORKER_COUNT_ENV: value}), 1)

    def test_config_applies_worker_environment_and_keeps_default_threads(self):
        with patch.dict(os.environ, {}, clear=True):
            config = importlib.import_module("gunicorn_config")
        self.assertEqual(config.workers, 1)
        self.assertEqual(config.threads, 10)
        self.assertIs(config.preload_app, False)
        self.assertEqual(config.worker_class, "gthread")
        self.assertTrue(callable(config.post_worker_init))

        with patch.dict(os.environ, {
                gpu_worker_startup.WORKER_COUNT_ENV: "8",
                "PII_MODEL_BATCH_SIZE": "1",
                "PII_MAX_CONCURRENT_ANALYSES": "2",
                "PII_MAX_QUEUED_ANALYSES": "0",
        }, clear=True):
            configured = importlib.reload(config)
        self.assertEqual(configured.workers, 8)
        self.assertEqual(configured.threads, 4)
        self.assertEqual(configured.worker_class, "gthread")
        self.assertIs(configured.preload_app, False)

    def test_gunicorn_config_is_stdlib_only_and_preserves_other_settings(self):
        script = f"""
import importlib
import json
import os
import sys
sys.path.insert(0, {str(APP_DIR)!r})
os.environ.pop("PII_GUNICORN_WORKERS", None)
os.environ["PII_MODEL_BATCH_SIZE"] = "8"
os.environ["PII_MAX_CONCURRENT_ANALYSES"] = "6"
os.environ["PII_MAX_QUEUED_ANALYSES"] = "3"
import gunicorn_config as config
assert config.workers == 1
assert config.worker_class == "gthread"
assert config.threads == 11
assert config.preload_app is False
assert callable(config.post_worker_init)
for value, expected in (("8", 8), (" 8 ", 8), ("9", 1), ("08", 1), ("+8", 1)):
    os.environ["PII_GUNICORN_WORKERS"] = value
    importlib.reload(config)
    assert config.workers == expected, (value, config.workers)
    assert config.threads == 11
    assert config.worker_class == "gthread"
    assert config.preload_app is False
    assert "torch" not in sys.modules
    assert "app" not in sys.modules
print(json.dumps({{"workers": config.workers, "threads": config.threads}}))
"""
        environment = os.environ.copy()
        environment.pop("PII_GUNICORN_WORKERS", None)
        environment.pop("PII_VERIFY_MODEL_STARTUP", None)
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(json.loads(result.stdout), {"workers": 1, "threads": 11})

    def test_hook_requires_exact_one_and_does_not_import_torch_when_disabled(self):
        class UnavailableWorker:
            @property
            def cfg(self):
                raise AssertionError("disabled hook inspected worker")

        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "torch":
                raise AssertionError("disabled hook imported torch")
            return original_import(name, *args, **kwargs)

        for value in (None, "true", "01", " 1"):
            with self.subTest(value=value):
                environment = ({} if value is None else {
                    gpu_worker_startup.VERIFY_STARTUP_ENV: value})
                with patch.dict(os.environ, environment, clear=True), \
                        patch("builtins.__import__", side_effect=guarded_import):
                    self.assertIsNone(gpu_worker_startup.post_worker_init(
                        UnavailableWorker()))


class WorkerStartupProofTests(unittest.TestCase):
    def _run_success(self, batch_size):
        pipeline = RecordingPipeline()
        app = _fake_app(batch_size, pipeline)
        worker = FakeWorker(app)
        torch = FakeTorch()
        with patch.dict(os.environ, {
                gpu_worker_startup.VERIFY_STARTUP_ENV: "1"}, clear=True), \
                patch.dict(sys.modules, {"torch": torch}):
            gpu_worker_startup.post_worker_init(worker)
        metadata = _success_metadata(worker)
        self.assertIs(app.nlp, pipeline)
        self.assertEqual(len(worker.log.info_lines), 1)
        self.assertLessEqual(len(worker.log.info_lines[0]),
                             gpu_worker_startup.MAX_LOG_LINE_LENGTH)
        self.assertEqual(worker.log.error_lines, [])
        self.assertEqual(torch.cuda.synchronize_calls, 1)
        self.assertEqual(len(pipeline.calls), (63 + batch_size - 1) // batch_size)
        self.assertTrue(all(name.startswith("native-model")
                            for _size, _batch, name in pipeline.calls))
        return metadata, pipeline

    def test_warmup_exercises_native_lane_and_reports_bounded_safe_metadata(self):
        permitted_fields = {
            "event", "pid", "workers", "model_device", "model_dtype",
            "parameter_bytes", "buffer_bytes", "model_batch_size",
            "warmup_chunk_count", "warmup_call_count", "warmup_input_count",
            "warmup_max_batch_size", "warmup_tail_batch_size",
        }
        for batch_size in (1, 4, 8, 16):
            with self.subTest(batch_size=batch_size):
                metadata, pipeline = self._run_success(batch_size)
                self.assertEqual(set(metadata), permitted_fields)
                self.assertEqual(metadata["event"], "ready")
                self.assertEqual(metadata["pid"], os.getpid())
                self.assertEqual(metadata["workers"], 8)
                self.assertEqual(metadata["model_device"], "cuda:0")
                self.assertEqual(metadata["model_dtype"], "float32")
                self.assertEqual(metadata["parameter_bytes"], 40)
                self.assertEqual(metadata["buffer_bytes"], 32)
                self.assertEqual(metadata["model_batch_size"], batch_size)
                self.assertEqual(metadata["warmup_chunk_count"], 63)
                self.assertEqual(metadata["warmup_call_count"],
                                 (63 + batch_size - 1) // batch_size)
                self.assertEqual(metadata["warmup_input_count"], 63)
                self.assertEqual(metadata["warmup_max_batch_size"], batch_size)
                self.assertEqual(metadata["warmup_tail_batch_size"],
                                 63 % batch_size or batch_size)
                self.assertTrue(all(
                    batch is None if batch_size == 1 else batch == batch_size
                    for _size, batch, _name in pipeline.calls))
                self.assertNotIn("neutral", json.dumps(metadata))

    def test_pipeline_error_restores_original_and_sanitizes_failure(self):
        pipeline = RecordingPipeline(error=RuntimeError("SECRET_PIPELINE_INPUT"))
        app = _fake_app(8, pipeline)
        worker = FakeWorker(app)
        with patch.dict(os.environ, {
                gpu_worker_startup.VERIFY_STARTUP_ENV: "1"}, clear=True), \
                patch.dict(sys.modules, {"torch": FakeTorch()}):
            with self.assertRaises(RuntimeError) as caught:
                gpu_worker_startup.post_worker_init(worker)
        self.assertEqual(str(caught.exception), gpu_worker_startup.STARTUP_PROOF_ERROR)
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        _assert_generic_startup_failure(self, worker, app, pipeline)

    def test_invalid_pipeline_result_restores_original_and_fails_closed(self):
        pipeline = RecordingPipeline(result_factory=lambda inputs: [[]])
        app = _fake_app(8, pipeline)
        worker = FakeWorker(app)
        with patch.dict(os.environ, {
                gpu_worker_startup.VERIFY_STARTUP_ENV: "1"}, clear=True), \
                patch.dict(sys.modules, {"torch": FakeTorch()}):
            with self.assertRaises(RuntimeError) as caught:
                gpu_worker_startup.post_worker_init(worker)
        self.assertEqual(str(caught.exception), gpu_worker_startup.STARTUP_PROOF_ERROR)
        self.assertIsNone(caught.exception.__cause__)
        _assert_generic_startup_failure(self, worker, app, pipeline)

    def test_cooperative_deadline_restores_original_pipeline(self):
        pipeline = RecordingPipeline()
        app = _fake_app(8, pipeline)
        worker = FakeWorker(app)
        with patch.dict(os.environ, {
                gpu_worker_startup.VERIFY_STARTUP_ENV: "1"}, clear=True), \
                patch.dict(sys.modules, {"torch": FakeTorch()}), \
                patch.object(gpu_worker_startup.time, "monotonic",
                             side_effect=(0.0, 61.0)):
            with self.assertRaises(RuntimeError) as caught:
                gpu_worker_startup.post_worker_init(worker)
        self.assertEqual(str(caught.exception), gpu_worker_startup.STARTUP_PROOF_ERROR)
        self.assertEqual(pipeline.calls, [])
        _assert_generic_startup_failure(self, worker, app, pipeline)

    def test_invalid_worker_count_fails_closed_without_loading_model(self):
        pipeline = RecordingPipeline()
        app = _fake_app(8, pipeline)
        worker = FakeWorker(app, workers=9)
        with patch.dict(os.environ, {
                gpu_worker_startup.VERIFY_STARTUP_ENV: "1"}, clear=True):
            with self.assertRaises(RuntimeError) as caught:
                gpu_worker_startup.post_worker_init(worker)
        self.assertEqual(str(caught.exception), gpu_worker_startup.STARTUP_PROOF_ERROR)
        self.assertIs(app.nlp, pipeline)
        self.assertEqual(pipeline.calls, [])
        self.assertEqual(json.loads(worker.log.error_lines[0].split(" ", 1)[1]), {
            "event": "startup_failed", "pid": os.getpid(), "workers": None,
        })

    def test_cuda_device_and_parameter_dtype_failures_restore_pipeline(self):
        cases = (
            (0, FakeModel(parameters=[FakeTensor(
                4, 2, "float16", floating=True)])),
            (0, FakeModel(parameters=[FakeTensor(
                4, 4, "float32", device="cuda:1")])),
            (-1, FakeModel()),
        )
        for device, model in cases:
            with self.subTest(device=device, model=model):
                pipeline = RecordingPipeline(model=model)
                app = _fake_app(8, pipeline)
                app.device = device
                worker = FakeWorker(app)
                with patch.dict(os.environ, {
                        gpu_worker_startup.VERIFY_STARTUP_ENV: "1"}, clear=True), \
                        patch.dict(sys.modules, {"torch": FakeTorch()}):
                    with self.assertRaises(RuntimeError) as caught:
                        gpu_worker_startup.post_worker_init(worker)
                self.assertEqual(str(caught.exception),
                                 gpu_worker_startup.STARTUP_PROOF_ERROR)
                _assert_generic_startup_failure(self, worker, app, pipeline)

    def test_empty_parameter_or_buffer_collections_fail_closed(self):
        for model in (FakeModel(parameters=[]), FakeModel(buffers=[])):
            with self.subTest(model=model):
                pipeline = RecordingPipeline(model=model)
                app = _fake_app(1, pipeline)
                worker = FakeWorker(app)
                with patch.dict(os.environ, {
                        gpu_worker_startup.VERIFY_STARTUP_ENV: "1"}, clear=True), \
                        patch.dict(sys.modules, {"torch": FakeTorch()}):
                    with self.assertRaises(RuntimeError):
                        gpu_worker_startup.post_worker_init(worker)
                _assert_generic_startup_failure(self, worker, app, pipeline)

    def test_invalid_batch_size_and_missing_pipeline_fail_closed(self):
        pipeline = RecordingPipeline()
        for batch_size, model_pipeline in ((2, pipeline), (8, None)):
            app = _fake_app(batch_size, model_pipeline)
            worker = FakeWorker(app)
            with self.subTest(batch_size=batch_size), \
                    patch.dict(os.environ, {
                        gpu_worker_startup.VERIFY_STARTUP_ENV: "1"}, clear=True), \
                    patch.dict(sys.modules, {"torch": FakeTorch()}):
                with self.assertRaises(RuntimeError):
                    gpu_worker_startup.post_worker_init(worker)
            self.assertIs(app.nlp, model_pipeline)
            self.assertEqual(worker.log.info_lines, [])
            self.assertEqual(len(worker.log.error_lines), 1)


if __name__ == "__main__":
    unittest.main()
