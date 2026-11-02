import hashlib
import json
import lzma
import marshal
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

from tools.verda_model_experiment import batch_package, batch_runtime, fixture, runtime


class FakeGuardrail:
    class ModelUnavailable(Exception):
        pass


class FakeLane:
    def run(self, function, *args, check_deadline=None, **kwargs):
        if check_deadline is not None:
            check_deadline()
        return function(*args, **kwargs)


class FakeModel:
    def __init__(self, fail=False):
        self.model = object()
        self.tokenizer = object()
        self.calls = []
        self.fail = fail

    def __call__(self, texts, **kwargs):
        self.calls.append((
            len(texts), kwargs.get("batch_size"), tuple(sorted(kwargs))))
        if self.fail:
            raise RuntimeError("model failure with payload text")
        return [[{
            "entity_group": "EMAIL",
            "start": 0,
            "end": 1,
            "score": 0.5,
        }] for _ in texts]


def make_module(chunks=63, fail=False):
    module = types.ModuleType("app")
    module.nlp = FakeModel(fail=fail)
    module.device = 0
    module.runtime_execution = types.SimpleNamespace(MODEL_LANE=FakeLane())
    module.guardrail_api = FakeGuardrail
    module.chunk_text = lambda text: [
        (f"fixture-chunk-{index}", index) for index in range(chunks)]
    module.complete_time = lambda entities, text: None
    module.detect_regex = lambda text: []
    module._merge = lambda candidates, text: candidates
    exec(
        "def _guardrail_detect(text, check_deadline, categories=None):\n"
        "    return []\n",
        module.__dict__)
    exec(
        "def _guardrail_detect_for_categories(categories):\n"
        "    active = frozenset(categories)\n"
        "    def detect_active(text, check_deadline):\n"
        "        return _guardrail_detect(text, check_deadline, categories=active)\n"
        "    return detect_active\n",
        module.__dict__)
    exec(
        "def detect_model(text):\n"
        "    return 'legacy'\n",
        module.__dict__)
    return module


def parse_bundle(archive):
    blob = lzma.decompress(archive)
    position = len(batch_package.BATCH_BUNDLE_MAGIC)
    files = {}
    for name in batch_package.BATCH_ARCHIVE_FILES:
        size = int.from_bytes(blob[position:position + 2], "big")
        position += 2
        position += size
        length = int.from_bytes(blob[position:position + 4], "big")
        position += 4
        files[name] = blob[position:position + length]
        position += length
    return files


def build_assets(root):
    archive, hashes, manifest, manifest_bytes = (
        batch_package.build_batch_archive())
    files = parse_bundle(archive)
    runtime_root = Path(root) / "runtime"
    for name, data in files.items():
        target = runtime_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o600)
    for directory in (
            runtime_root,
            runtime_root / "tools",
            runtime_root / "tools/verda_model_experiment",
            runtime_root / "tools/verda_model_experiment/batch_overlay"):
        directory.chmod(0o700)
    app_root = Path(root) / "app"
    app_root.mkdir()
    app_bytes = b"verified base application fixture"
    (app_root / "app.py").write_bytes(app_bytes)
    selected = dict(manifest)
    selected["base_app_sha256"] = hashlib.sha256(app_bytes).hexdigest()
    assets_root = runtime_root / "tools/verda_model_experiment/batch_overlay"
    return app_root, assets_root, selected, files


def install(module, app_root, assets_root, manifest, batch_size):
    with mock.patch.dict(
            os.environ, {batch_runtime.BATCH_SIZE_ENV: str(batch_size)},
            clear=False):
        return batch_runtime._install(
            module, app_root, assets_root, manifest)


def captured_events():
    lines = []

    def write(descriptor, data):
        lines.append(data)

    return lines, mock.patch.object(batch_runtime.os, "write", side_effect=write)


class CompileDetectorTests(unittest.TestCase):
    def test_exact_current_fragment_compiles_and_hash_matches_manifest(self):
        archive, _, manifest, _ = batch_package.build_batch_archive()
        files = parse_bundle(archive)
        detector = batch_runtime.compile_detector(
            files[batch_package.BATCH_DETECTOR_ASSET],
            source_sha256=manifest["detector_source_sha256"],
            code_sha256=manifest["detector_code_sha256"])
        self.assertEqual(detector.__name__, "_guardrail_detect")
        self.assertEqual(detector.__defaults__, (None,))
        self.assertEqual(batch_runtime.CODE_HASH_PYTHON_VERSION,
                         sys.version_info[:2])
        self.assertEqual(
            hashlib.sha256(marshal.dumps(detector.__code__)).hexdigest(),
            manifest["detector_code_sha256"])

    def test_tampered_and_forbidden_fragments_fail_closed(self):
        archive, _, manifest, _ = batch_package.build_batch_archive()
        detector = parse_bundle(archive)[batch_package.BATCH_DETECTOR_ASSET]
        variants = (
            b"pass\n",
            b"def _guardrail_detect(text, check_deadline, categories=None):\n"
            b"    return []\n"
            b"def _guardrail_detect(text, check_deadline, categories=None):\n"
            b"    return []\n",
            detector.replace(
                b"def _guardrail_detect(", b"def other_detector(", 1),
            b"import os\n" + detector,
            detector + b"\npass\n",
            b"def _guardrail_detect(text, check_deadline, categories=1):\n"
            b"    return []\n",
            b"def _guardrail_detect(text, check_deadline, *args):\n"
            b"    return []\n",
            b"def _guardrail_detect(text, check_deadline, categories=None):\n"
            b"    return eval(text)\n",
            b"def _guardrail_detect(text, check_deadline, categories=None):\n"
            b"    return __import__('os')\n",
            b"def _guardrail_detect(text, check_deadline, categories=None):\n"
            b"    return (lambda: 1)()\n",
            b"def _guardrail_detect(text, check_deadline, categories=None):\n"
            b"    with open('x'):\n"
            b"        return []\n",
            b"@staticmethod\n" + detector,
            b"def _guardrail_detect(text, check_deadline, categories: str = None):\n"
            b"    return []\n",
            b"def _guardrail_detect(text: str, check_deadline, categories=None):\n"
            b"    return []\n",
            b"def _guardrail_detect(text, check_deadline, categories=None) -> list:\n"
            b"    return []\n",
            b"def _guardrail_detect(text, check_deadline, categories=object()):\n"
            b"    return []\n",
        )
        for fragment in variants:
            with self.subTest(fragment=fragment[:40]), self.assertRaises(
                    batch_runtime.BatchOverlayError):
                batch_runtime.compile_detector(fragment)
        with mock.patch.object(
                batch_runtime, "CODE_HASH_PYTHON_VERSION", (3, 10)):
            self.assertEqual(
                batch_runtime.compile_detector(detector).__name__,
                "_guardrail_detect")
        with self.assertRaises(batch_runtime.BatchOverlayError):
            batch_runtime.compile_detector(detector, source_sha256="0" * 64)
        with self.assertRaises(batch_runtime.BatchOverlayError):
            batch_runtime.compile_detector(
                detector, code_sha256="0" * 64)
        with mock.patch.object(
                batch_runtime, "compile",
                return_value=types.SimpleNamespace(co_consts=())):
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime.compile_detector(detector)
        with mock.patch.object(
                batch_runtime.types, "FunctionType",
                side_effect=lambda code, *args: types.SimpleNamespace(
                    __code__=code, __kwdefaults__={})):
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime.compile_detector(detector)
        with self.assertRaises(batch_runtime.BatchOverlayError):
            batch_runtime.compile_detector(b"x" * (129 * 1024))
        with self.assertRaises(batch_runtime.BatchOverlayError):
            batch_runtime.compile_detector(
                b"def _guardrail_detect(text, check_deadline, categories=None):\n"
                + b"    value = 1\n" * 5000)
        with self.assertRaises(batch_runtime.BatchOverlayError):
            batch_runtime.compile_detector(b"\xff\xfe")


class InstallTests(unittest.TestCase):
    def test_install_preserves_registered_object_binder_and_legacy(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            module = make_module()
            registered = module._guardrail_detect
            binder = module._guardrail_detect_for_categories
            legacy = module.detect_model
            legacy_code = legacy.__code__
            evidence = install(module, app_root, assets_root, manifest, 4)
            self.assertIs(module._guardrail_detect, registered)
            self.assertIs(module._guardrail_detect_for_categories, binder)
            self.assertIs(module.detect_model, legacy)
            self.assertIs(legacy.__code__, legacy_code)
            self.assertEqual(evidence["batch_size"], 4)
            self.assertEqual(module.MODEL_BATCH_SIZE, 4)
            self.assertEqual(
                module.model_batching.__file__,
                str(assets_root / Path(batch_runtime.HELPER_ASSET).name))
            self.assertEqual(
                module.model_batching.SUPPORTED_BATCH_SIZES, (1, 4, 8, 16))
            self.assertEqual(registered.__defaults__, (None,))
            self.assertIsNone(registered.__kwdefaults__)
            self.assertIs(registered.__globals__, module.__dict__)
            self.assertIn("model_batching", registered.__code__.co_names)
            self.assertIn("MODEL_BATCH_SIZE", registered.__code__.co_names)
            self.assertIs(evidence["installed_code_ok"], True)
            self.assertEqual(
                evidence["detector_code_sha256"],
                manifest["detector_code_sha256"])
            self.assertEqual(module.detect_model("text"), "legacy")
            bound = module._guardrail_detect_for_categories(("EMAIL",))
            model = module.nlp
            registered("text", lambda: None, categories=("EMAIL",))
            bound("text", lambda: None)
            self.assertEqual(len(model.calls), 32)
            self.assertTrue(all(call[1] == 4 for call in model.calls))
            self.assertTrue(all(call[2] == ("batch_size",) for call in model.calls))

    def test_install_rejects_bad_base_signature_and_interface(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            module = make_module()
            original_code = module._guardrail_detect.__code__
            changed = dict(manifest)
            changed["base_app_sha256"] = "0" * 64
            with self.assertRaises(batch_runtime.BatchOverlayError):
                install(module, app_root, assets_root, changed, 1)
            self.assertIs(module._guardrail_detect.__code__, original_code)
            with self.assertRaises(batch_runtime.BatchOverlayError):
                install(module, Path(temporary) / "missing", assets_root,
                        manifest, 1)
            short = make_module()
            exec(
                "def _guardrail_detect(text):\n"
                "    return []\n",
                short.__dict__)
            with self.assertRaises(batch_runtime.BatchOverlayError):
                install(short, app_root, assets_root, manifest, 1)
            no_detector = make_module()
            del no_detector.__dict__["_guardrail_detect"]
            with self.assertRaises(batch_runtime.BatchOverlayError):
                install(no_detector, app_root, assets_root, manifest, 1)
            no_binder = make_module()
            del no_binder.__dict__["_guardrail_detect_for_categories"]
            with self.assertRaises(batch_runtime.BatchOverlayError):
                install(no_binder, app_root, assets_root, manifest, 1)
            no_legacy = make_module()
            del no_legacy.__dict__["detect_model"]
            with self.assertRaises(batch_runtime.BatchOverlayError):
                install(no_legacy, app_root, assets_root, manifest, 1)
            closed = make_module()
            exec(
                "def _make_detector():\n"
                "    outer = 1\n"
                "    def _guardrail_detect(text, check_deadline, categories=None):\n"
                "        return [outer]\n"
                "    return _guardrail_detect\n",
                closed.__dict__)
            closed.__dict__["_guardrail_detect"] = closed.__dict__[
                "_make_detector"]()
            with self.assertRaises(batch_runtime.BatchOverlayError):
                install(closed, app_root, assets_root, manifest, 1)

    def test_install_rejects_tampered_assets_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            helper = assets_root / Path(batch_package.BATCH_HELPER_ASSET).name
            detector = assets_root / Path(batch_package.BATCH_DETECTOR_ASSET).name
            helper.write_bytes(helper.read_bytes() + b"\n")
            with self.assertRaises(batch_runtime.BatchOverlayError):
                install(make_module(), app_root, assets_root, manifest, 1)
            helper.write_bytes(
                batch_package.BATCH_HELPER_SOURCE.read_bytes())
            detector.write_bytes(detector.read_bytes() + b"\n")
            with self.assertRaises(batch_runtime.BatchOverlayError):
                install(make_module(), app_root, assets_root, manifest, 1)
            detector.write_bytes(
                parse_bundle(
                    batch_package.build_batch_archive()[0]
                )[batch_package.BATCH_DETECTOR_ASSET])
            variants = []
            for field, value in (
                    ("format", "other"),
                    ("helper", "other"),
                    ("detector", "other"),
                    ("function", "other"),
                    ("workers", 1),
                    ("fixture_chunks", 1),
                    ("warm_timeout_seconds", 1),
                    ("batch_sizes", [1, 2]),
                    ("base_app_sha256", "0" * 64),
                    ("helper_sha256", "0" * 64),
                    ("detector_source_sha256", "0" * 64),
                    ("detector_code_sha256", "0" * 64)):
                changed = dict(manifest)
                changed[field] = value
                variants.append(changed)
            missing = dict(manifest)
            missing.pop("helper_sha256")
            variants.append(missing)
            extra = dict(manifest)
            extra["extra"] = 1
            variants.append(extra)
            for changed in variants:
                with self.subTest(changed=changed.get("format")), \
                        self.assertRaises(batch_runtime.BatchOverlayError):
                    install(make_module(), app_root, assets_root, changed, 1)
            with self.assertRaises(batch_runtime.BatchOverlayError):
                install(make_module(), app_root, assets_root, manifest, 2)

    def test_install_restores_state_when_post_install_identity_check_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            module = make_module()
            original_code = module._guardrail_detect.__code__
            with mock.patch.object(
                    batch_runtime, "_binder_is_bound",
                    side_effect=[True, False]):
                with self.assertRaises(batch_runtime.BatchOverlayError):
                    install(module, app_root, assets_root, manifest, 4)
            self.assertIs(module._guardrail_detect.__code__, original_code)
            self.assertNotIn("MODEL_BATCH_SIZE", module.__dict__)
            self.assertNotIn("model_batching", module.__dict__)
            previous_model_batching = object()
            module.MODEL_BATCH_SIZE = 37
            module.model_batching = previous_model_batching
            with mock.patch.object(
                    batch_runtime, "_binder_is_bound",
                    side_effect=[True, False]):
                with self.assertRaises(batch_runtime.BatchOverlayError):
                    install(module, app_root, assets_root, manifest, 8)
            self.assertIs(module._guardrail_detect.__code__, original_code)
            self.assertEqual(module.MODEL_BATCH_SIZE, 37)
            self.assertIs(module.model_batching, previous_model_batching)


class WarmTests(unittest.TestCase):
    def test_warm_counts_for_all_batches_and_restores_model(self):
        expected = {1: (63, 1), 4: (16, 4), 8: (8, 8), 16: (4, 16)}
        for batch_size, (calls, maximum) in expected.items():
            with self.subTest(batch_size=batch_size), \
                    tempfile.TemporaryDirectory() as temporary:
                app_root, assets_root, manifest, _ = build_assets(temporary)
                module = make_module()
                original = module.nlp
                legacy_code = module.detect_model.__code__
                install(module, app_root, assets_root, manifest, batch_size)
                warm = batch_runtime._warm_v1(module, batch_size)
                self.assertIs(module.nlp, original)
                self.assertIs(module.detect_model.__code__, legacy_code)
                self.assertEqual(warm["warm_calls"], calls)
                self.assertEqual(warm["warm_max_batch"], maximum)
                self.assertEqual(warm["warm_sum_batches"], 63)
                self.assertEqual(warm["fixture_chunks"], 63)
                self.assertEqual(len(original.calls), calls)
                if batch_size == 1:
                    self.assertTrue(all(
                        call[1] is None and call[2] == ()
                        for call in original.calls))
                else:
                    self.assertTrue(all(
                        call[1] == batch_size
                        and call[2] == ("batch_size",)
                        for call in original.calls))
                self.assertTrue(all(type(call[0]) is int
                                    for call in original.calls))

    def test_failure_and_timeout_restore_model_without_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            module = make_module(fail=True)
            original = module.nlp
            install(module, app_root, assets_root, manifest, 4)
            with self.assertRaises(batch_runtime.BatchOverlayError) as failure:
                batch_runtime._warm_v1(module, 4)
            self.assertNotIn("payload text", str(failure.exception))
            self.assertIs(module.nlp, original)
            self.assertEqual(len(original.calls), 1)
            self.assertNotIn(fixture.FIXTURE_TEXT, repr(original.calls))
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            module = make_module()
            original = module.nlp
            install(module, app_root, assets_root, manifest, 8)
            values = iter([0.0, 61.0, 61.0, 61.0, 61.0, 61.0, 61.0, 61.0])
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._warm_v1(
                    module, 8, clock=lambda: next(values), timeout=60.0)
            self.assertIs(module.nlp, original)
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            module = make_module(chunks=62)
            original = module.nlp
            install(module, app_root, assets_root, manifest, 4)
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._warm_v1(module, 4)
            self.assertIs(module.nlp, original)
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._warm_v1(module, 2)
        missing_model = make_module()
        del missing_model.nlp
        with self.assertRaises(batch_runtime.BatchOverlayError):
            batch_runtime._warm_v1(missing_model, 1)

    def test_warm_rejects_wrong_call_counts_and_batch_keywords(self):
        for batch_size, lengths, keyword in (
                (1, [1] * 63, True), (4, [4] * 15 + [3], False)):
            with self.subTest(batch_size=batch_size), \
                    tempfile.TemporaryDirectory() as temporary:
                app_root, assets_root, manifest, _ = build_assets(temporary)
                module = make_module()
                install(module, app_root, assets_root, manifest, batch_size)
                original = module.nlp

                def detect(text, check_deadline):
                    for length in lengths:
                        arguments = {"batch_size": 1} if keyword else {}
                        module.nlp(["chunk"] * length, **arguments)

                module._guardrail_detect = detect
                with self.assertRaises(batch_runtime.BatchOverlayError):
                    batch_runtime._warm_v1(module, batch_size)
                self.assertIs(module.nlp, original)
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            module = make_module()
            install(module, app_root, assets_root, manifest, 1)
            original = module.nlp
            module._guardrail_detect = lambda text, check_deadline: []
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._warm_v1(module, 1)
            self.assertIs(module.nlp, original)

    def test_proxy_preserves_model_and_tokenizer_and_records_numbers(self):
        model = FakeModel()
        calls = []
        proxy = batch_runtime._ModelProxy(model, calls)
        self.assertIs(proxy.model, model.model)
        self.assertIs(proxy.tokenizer, model.tokenizer)
        result = proxy(["fixture text"], batch_size=4)
        self.assertEqual(len(result), 1)
        self.assertEqual(calls, [(1, 4, ("batch_size",))])
        self.assertNotIn("fixture text", repr(calls))


class BatchSizeTests(unittest.TestCase):
    def test_batch_size_is_strict_supported_and_defaults_to_one(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(batch_runtime._batch_size_from_env(), 1)
        with mock.patch.dict(
                os.environ, {batch_runtime.BATCH_SIZE_ENV: ""}, clear=True):
            self.assertEqual(batch_runtime._batch_size_from_env(), 1)
        for value in ("1", "4", "8", "16"):
            with self.subTest(value=value), mock.patch.dict(
                    os.environ,
                    {batch_runtime.BATCH_SIZE_ENV: value}, clear=True):
                self.assertEqual(batch_runtime._batch_size_from_env(), int(value))
        for value in ("0", "2", "3", "5", "17", " 4 ", "04", "+4", "4\n"):
            with self.subTest(value=value), mock.patch.dict(
                    os.environ,
                    {batch_runtime.BATCH_SIZE_ENV: value}, clear=True):
                with self.assertRaises(batch_runtime.BatchOverlayError):
                    batch_runtime._batch_size_from_env()


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.old_run_id = runtime._ACTIVE_RUN_ID
        self.old_workers = runtime._ACTIVE_WORKERS
        runtime._ACTIVE_RUN_ID = "batch-wrapper"
        runtime._ACTIVE_WORKERS = 8

    def tearDown(self):
        runtime._ACTIVE_RUN_ID = self.old_run_id
        runtime._ACTIVE_WORKERS = self.old_workers

    def test_warm_runs_before_base_hook_and_ready_after_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            module = make_module()
            original = module.nlp
            worker = types.SimpleNamespace(
                wsgi=types.SimpleNamespace(module=module))
            order = []

            def base_hook(selected):
                order.append(("base", len(original.calls),
                              selected.wsgi.module.nlp is original))

            lines, patch = captured_events()
            emit = batch_runtime._emit

            def emit_spy(event, fields):
                order.append((event, fields.get("workers"),
                              fields.get("batch_size")))
                emit(event, fields)

            with patch, mock.patch.dict(
                    os.environ,
                    {batch_runtime.BATCH_SIZE_ENV: "8"}, clear=False), \
                    mock.patch.object(batch_runtime, "_emit",
                                      side_effect=emit_spy):
                wrapped = batch_runtime._wrap_post_worker_init(
                    base_hook, app_root=app_root,
                    assets_root=assets_root, manifest=manifest)
                wrapped(worker)
            self.assertEqual(order, [
                ("base", 8, True),
                ("ready", 8, 8),
            ])
            self.assertEqual(len(lines), 1)
            self.assertIs(module.nlp, original)

    def test_base_hook_failure_is_sanitized_and_never_emits_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            module = make_module()
            original = module.nlp
            worker = types.SimpleNamespace(
                wsgi=types.SimpleNamespace(module=module))
            lines, patch = captured_events()

            def base_hook(selected):
                raise RuntimeError("private response text")

            with patch, mock.patch.dict(
                    os.environ,
                    {batch_runtime.BATCH_SIZE_ENV: "4"}, clear=False):
                wrapped = batch_runtime._wrap_post_worker_init(
                    base_hook, app_root=app_root, assets_root=assets_root,
                    manifest=manifest)
                with self.assertRaisesRegex(
                        RuntimeError, "worker startup failed") as failure:
                    wrapped(worker)
            self.assertNotIn("private response text", str(failure.exception))
            self.assertIs(module.nlp, original)
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0].decode("ascii").split(" ", 1)[1])
            self.assertEqual(payload["event"], "failed")
            self.assertFalse(payload["startup_ok"])

    def test_failure_before_base_hook_emits_generic_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            module = make_module(fail=True)
            original = module.nlp
            worker = types.SimpleNamespace(
                wsgi=types.SimpleNamespace(module=module))
            order = []

            def base_hook(selected):
                order.append("base")

            lines, patch = captured_events()
            with patch, mock.patch.dict(
                    os.environ,
                    {batch_runtime.BATCH_SIZE_ENV: "4"}, clear=False):
                wrapped = batch_runtime._wrap_post_worker_init(
                    base_hook, app_root=app_root,
                    assets_root=assets_root, manifest=manifest)
                with self.assertRaisesRegex(
                        RuntimeError, "worker startup failed"):
                    wrapped(worker)
            self.assertEqual(order, [])
            self.assertIs(module.nlp, original)
            payload = json.loads(lines[0].decode("ascii").split(" ", 1)[1])
            self.assertEqual(payload["event"], "failed")
            self.assertFalse(payload["startup_ok"])
            self.assertNotIn("payload text", lines[0].decode("ascii"))

    def test_install_failure_also_skips_the_marker_hook(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            changed = dict(manifest)
            changed["base_app_sha256"] = "0" * 64
            module = make_module()
            worker = types.SimpleNamespace(
                wsgi=types.SimpleNamespace(module=module))
            order = []
            lines, patch = captured_events()
            with patch:
                wrapped = batch_runtime._wrap_post_worker_init(
                    lambda selected: order.append("base"),
                    app_root=app_root, assets_root=assets_root,
                    manifest=changed)
                with self.assertRaisesRegex(
                        RuntimeError, "worker startup failed"):
                    wrapped(worker)
            self.assertEqual(order, [])
            payload = json.loads(lines[0].decode("ascii").split(" ", 1)[1])
            self.assertEqual(payload["event"], "failed")

    def test_wrapper_accepts_supported_worker_counts_and_emits_real_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            for workers in (12, 16):
                with self.subTest(workers=workers):
                    runtime._ACTIVE_WORKERS = workers
                    module = make_module()
                    worker = types.SimpleNamespace(
                        wsgi=types.SimpleNamespace(module=module))
                    lines, patch = captured_events()
                    with patch, mock.patch.dict(
                            os.environ,
                            {batch_runtime.BATCH_SIZE_ENV: "8"}, clear=False):
                        wrapped = batch_runtime._wrap_post_worker_init(
                            lambda selected: None, app_root=app_root,
                            assets_root=assets_root, manifest=manifest)
                        wrapped(worker)
                    payload = json.loads(
                        lines[0].decode("ascii").split(" ", 1)[1])
                    self.assertEqual(payload["event"], "ready")
                    self.assertEqual(payload["workers"], workers)
                    self.assertEqual(payload["batch_size"], 8)
                    self.assertEqual(payload["warm_calls"], 8)
                    self.assertEqual(payload["warm_max_batch"], 8)
                    self.assertEqual(payload["warm_sum_batches"], 63)

    def test_wrapper_requires_supported_worker_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            worker = types.SimpleNamespace(
                wsgi=types.SimpleNamespace(module=make_module()))
            for workers in (1, 2, 4, 9, 13, None):
                runtime._ACTIVE_WORKERS = workers
                wrapped = batch_runtime._wrap_post_worker_init(
                    lambda selected: None, app_root=app_root,
                    assets_root=assets_root, manifest=manifest)
                with self.subTest(workers=workers), self.assertRaisesRegex(
                        RuntimeError, "worker startup failed"):
                    wrapped(worker)
            runtime._ACTIVE_WORKERS = 8
            runtime._ACTIVE_RUN_ID = None
            wrapped = batch_runtime._wrap_post_worker_init(
                lambda selected: None, app_root=app_root,
                assets_root=assets_root, manifest=manifest)
            with self.assertRaisesRegex(
                    RuntimeError, "worker startup failed"):
                wrapped(worker)

    def test_missing_worker_module_fails_before_the_base_hook(self):
        runtime._ACTIVE_RUN_ID = "batch-wrapper"
        runtime._ACTIVE_WORKERS = 8
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            lines, patch = captured_events()
            with patch:
                wrapped = batch_runtime._wrap_post_worker_init(
                    lambda selected: None, app_root=app_root,
                    assets_root=assets_root, manifest=manifest)
                with self.assertRaisesRegex(
                        RuntimeError, "worker startup failed"):
                    wrapped(types.SimpleNamespace(wsgi=None))
            self.assertEqual(len(lines), 1)


class BarrierTests(unittest.TestCase):
    def setUp(self):
        self.old_run_id = runtime._ACTIVE_RUN_ID
        self.old_workers = runtime._ACTIVE_WORKERS
        runtime._ACTIVE_RUN_ID = "batch-barrier"
        runtime._ACTIVE_WORKERS = 8

    def tearDown(self):
        runtime._ACTIVE_RUN_ID = self.old_run_id
        runtime._ACTIVE_WORKERS = self.old_workers

    def _run_eight(self, fail_index=None, *, count=8, batch_size=1):
        runtime._ACTIVE_WORKERS = count
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        app_root, assets_root, manifest, _ = build_assets(temporary.name)
        run_path = Path(temporary.name) / "run"
        run_path.mkdir(mode=0o700)
        proc_root = Path(temporary.name) / "proc"
        proc_root.mkdir()
        for index in range(count):
            pid = 5000 + index
            process = proc_root / str(pid)
            process.mkdir()
            fields = ["S"] + ["0"] * 18 + [str(index + 1)]
            (process / "stat").write_text(
                f"{pid} (fake process) {' '.join(fields)}", encoding="ascii")
        results = []
        errors = []
        lines, patch = captured_events()

        def base_hook(worker):
            runtime._write_ready_marker(
                run_path, "batch-barrier", worker.pid, worker.pid - 4999)
            result = runtime.wait_for_worker_barrier(
                run_path, "batch-barrier", count, timeout_seconds=2.0,
                interval_seconds=0.01, proc_root=proc_root,
                kill=lambda pid, signal: None)
            results.append(result)
            if not result:
                raise RuntimeError("barrier timeout")

        with patch, mock.patch.dict(
                os.environ,
                {batch_runtime.BATCH_SIZE_ENV: str(batch_size)}, clear=False):
            wrapped = batch_runtime._wrap_post_worker_init(
                base_hook, app_root=app_root,
                assets_root=assets_root, manifest=manifest)
            threads = []
            for index in range(count):
                module = make_module(fail=index == fail_index)
                worker = types.SimpleNamespace(
                    pid=5000 + index,
                    wsgi=types.SimpleNamespace(module=module))
                def run(selected=worker):
                    try:
                        wrapped(selected)
                    except Exception as error:
                        errors.append(error)
                thread = threading.Thread(target=run)
                threads.append(thread)
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
        return results, errors, lines

    def test_eight_warm_workers_reach_the_real_barrier_before_ready(self):
        results, errors, lines = self._run_eight()
        self.assertEqual(errors, [])
        self.assertEqual(results, [True] * 8)
        self.assertEqual(len(lines), 8)
        for line in lines:
            payload = json.loads(line.decode("ascii").split(" ", 1)[1])
            self.assertEqual(payload["event"], "ready")
            self.assertEqual(payload["warm_calls"], 63)
            self.assertEqual(payload["warm_sum_batches"], 63)
            self.assertEqual(payload["workers"], 8)

    def test_twelve_and_sixteen_warm_workers_keep_batch_eight(self):
        for count in (12, 16):
            with self.subTest(count=count):
                results, errors, lines = self._run_eight(
                    count=count, batch_size=8)
                self.assertEqual(errors, [])
                self.assertEqual(results, [True] * count)
                self.assertEqual(len(lines), count)
                for line in lines:
                    payload = json.loads(
                        line.decode("ascii").split(" ", 1)[1])
                    self.assertEqual(payload["event"], "ready")
                    self.assertEqual(payload["workers"], count)
                    self.assertEqual(payload["batch_size"], 8)
                    self.assertEqual(payload["warm_calls"], 8)
                    self.assertEqual(payload["warm_max_batch"], 8)
                    self.assertEqual(payload["warm_sum_batches"], 63)

    def test_one_warm_failure_prevents_a_false_barrier_and_ready(self):
        results, errors, lines = self._run_eight(fail_index=3)
        self.assertEqual(len(errors), 8)
        self.assertEqual(
            [str(error) for error in errors],
            ["worker startup failed"] * 8)
        self.assertEqual(results, [False] * 7)
        self.assertEqual(len(lines), 8)
        for line in lines:
            payload = json.loads(line.decode("ascii").split(" ", 1)[1])
            self.assertEqual(payload["event"], "failed")
            self.assertFalse(payload["startup_ok"])


class EventTests(unittest.TestCase):
    def test_ready_event_is_bounded_numeric_boolean_and_sha_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            module = make_module()
            install(module, app_root, assets_root, manifest, 4)
            original = module.nlp
            warm = batch_runtime._warm_v1(module, 4)
            evidence = {
                "base_app_sha256": "1" * 64,
                "helper_sha256": "2" * 64,
                "detector_source_sha256": "3" * 64,
                "detector_code_sha256": "4" * 64,
                "manifest_sha256": "5" * 64,
                "installed_code_ok": True,
                "installed_defaults_ok": True,
                "globals_ok": True,
                "legacy_ok": True,
                "binder_ok": True,
                "base_app_ok": True,
                "overlay_ok": True,
            }
            lines, patch = captured_events()
            with patch, mock.patch.dict(os.environ, {}, clear=False):
                batch_runtime._emit("ready", {
                    **evidence, **warm,
                    "run_id": "batch-wrapper", "pid": 1234, "workers": 8,
                })
            self.assertEqual(len(lines), 1)
            line = lines[0].decode("ascii")
            self.assertTrue(line.startswith("VERDABATCH "))
            self.assertLessEqual(len(lines[0]), 4096)
            payload = json.loads(line.split(" ", 1)[1])
            self.assertEqual(payload["event"], "ready")
            self.assertEqual(payload["batch_size"], 4)
            self.assertEqual(payload["warm_calls"], 16)
            self.assertEqual(payload["warm_max_batch"], 4)
            self.assertEqual(payload["warm_sum_batches"], 63)
            self.assertEqual(payload["fixture_chunks"], 63)
            self.assertIs(payload["warm_ok"], True)
            self.assertIs(payload["overlay_ok"], True)
            self.assertNotIn(fixture.FIXTURE_TEXT, line)
            self.assertNotIn("req42@example.com", line)
            for key in payload:
                self.assertNotIn(key, {
                    "text", "input", "output", "exception", "uuid", "pii",
                    "email", "token", "model", "tokenizer",
                })
            for key, value in payload.items():
                if key.endswith("_sha256"):
                    self.assertEqual(len(value), 64)
                elif key.endswith("_ok"):
                    self.assertIs(type(value), bool)
                elif key in {"event", "run_id"}:
                    self.assertIs(type(value), str)
                else:
                    self.assertIs(type(value), int)
                    self.assertGreaterEqual(value, 0)
            self.assertIs(module.nlp, original)

    def test_events_accept_only_supported_worker_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            module = make_module()
            install(module, app_root, assets_root, manifest, 8)
            warm = batch_runtime._warm_v1(module, 8)
            evidence = {
                "base_app_sha256": "1" * 64,
                "helper_sha256": "2" * 64,
                "detector_source_sha256": "3" * 64,
                "detector_code_sha256": "4" * 64,
                "manifest_sha256": "5" * 64,
                "installed_code_ok": True,
                "installed_defaults_ok": True,
                "globals_ok": True,
                "legacy_ok": True,
                "binder_ok": True,
                "base_app_ok": True,
                "overlay_ok": True,
            }
            lines, patch = captured_events()
            with patch:
                for workers in (8, 12, 16):
                    batch_runtime._emit("ready", {
                        **evidence, **warm, "run_id": "batch-wrapper",
                        "pid": 1234, "workers": workers,
                    })
                    batch_runtime._emit("failed", {
                        "run_id": "batch-wrapper", "pid": 1234,
                        "workers": workers, "startup_ok": False,
                    })
                for workers in (1, 2, 4, 9, 13, 15, 17, True):
                    batch_runtime._emit("ready", {
                        **evidence, **warm, "run_id": "batch-wrapper",
                        "pid": 1234, "workers": workers,
                    })
                    batch_runtime._emit("failed", {
                        "run_id": "batch-wrapper", "pid": 1234,
                        "workers": workers, "startup_ok": False,
                    })
            self.assertEqual(len(lines), 6)
            payloads = [json.loads(
                line.decode("ascii").split(" ", 1)[1]) for line in lines]
            self.assertEqual(
                [payload["workers"] for payload in payloads],
                [8, 8, 12, 12, 16, 16])

    def test_invalid_events_are_dropped_without_writing(self):
        lines, patch = captured_events()
        with patch:
            batch_runtime._emit([], {})
            batch_runtime._emit("other", {})
            batch_runtime._emit("failed", {
                "run_id": "bad/run", "pid": 1, "workers": 8,
                "startup_ok": False})
            batch_runtime._emit("failed", {
                "run_id": "batch-wrapper", "pid": 1, "workers": 8,
                "startup_ok": "yes"})
            batch_runtime._emit("failed", {
                "run_id": "batch-wrapper", "pid": 1, "workers": 8,
                "startup_ok": False, "extra": "text"})
            batch_runtime._emit("failed", {
                "run_id": "batch-wrapper", "pid": True, "workers": 8,
                "startup_ok": False})
            batch_runtime._emit("failed", {
                "event": "ready", "run_id": "batch-wrapper", "pid": 1,
                "workers": 8, "startup_ok": False})
            batch_runtime._emit("failed", {
                "run_id": "batch-wrapper", "pid": 1, "workers": 8,
                "startup_ok": False, "bad_sha256": "0"})
            batch_runtime._emit("ready", {
                "run_id": "batch-wrapper", "pid": 1, "workers": 8,
                "batch_size": 2, "warm_calls": 1, "warm_max_batch": 1,
                "warm_sum_batches": 1, "fixture_chunks": 63,
                "base_app_sha256": "1" * 64, "helper_sha256": "2" * 64,
                "detector_source_sha256": "3" * 64,
                "detector_code_sha256": "4" * 64,
                "manifest_sha256": "5" * 64, "installed_code_ok": True,
                "installed_defaults_ok": True, "globals_ok": True,
                "legacy_ok": True, "binder_ok": True, "base_app_ok": True,
                "overlay_ok": True, "warm_ok": True})
            batch_runtime._emit("ready", {
                "run_id": "batch-wrapper", "pid": 1, "workers": 8,
                "batch_size": 4, "warm_calls": 16, "warm_max_batch": 4,
                "warm_sum_batches": 62, "fixture_chunks": 63,
                "base_app_sha256": "1" * 64, "helper_sha256": "2" * 64,
                "detector_source_sha256": "3" * 64,
                "detector_code_sha256": "4" * 64,
                "manifest_sha256": "5" * 64, "installed_code_ok": True,
                "installed_defaults_ok": True, "globals_ok": True,
                "legacy_ok": True, "binder_ok": True, "base_app_ok": True,
                "overlay_ok": True, "warm_ok": True})
        self.assertEqual(lines, [])
        with mock.patch.object(
                batch_runtime.os, "write", side_effect=OSError):
            batch_runtime._emit("failed", {
                "run_id": "batch-wrapper", "pid": 1, "workers": 8,
                "startup_ok": False,
            })


class PrivateAssetTests(unittest.TestCase):
    def test_private_file_modes_symlinks_and_limits_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "asset"
            target.write_bytes(b"data")
            target.chmod(0o644)
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._read_private_file(target)
            target.chmod(0o600)
            self.assertEqual(batch_runtime._read_private_file(target), b"data")
            link = root / "link"
            link.symlink_to(target)
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._read_private_file(link)
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._read_private_file(root / "missing")
            target.write_bytes(b"x" * (batch_runtime.EXTRACTED_LIMIT_BYTES + 1))
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._read_private_file(target)
            real_fstat = batch_runtime.os.fstat

            def underreported_size(descriptor):
                info = real_fstat(descriptor)
                return types.SimpleNamespace(
                    st_mode=info.st_mode, st_uid=info.st_uid, st_size=0)

            with mock.patch.object(
                    batch_runtime.os, "fstat",
                    side_effect=underreported_size):
                with self.assertRaises(batch_runtime.BatchOverlayError):
                    batch_runtime._read_private_file(target)

    def test_manifest_and_helper_loading_reject_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_root, assets_root, manifest, _ = build_assets(temporary)
            loaded, digest = batch_runtime._load_manifest(assets_root)
            self.assertEqual(loaded["base_app_sha256"],
                             runtime.SOURCE_HASHES["app.py"])
            self.assertEqual(len(digest), 64)
            helper = batch_runtime._load_helper(assets_root, manifest)
            self.assertTrue(callable(helper.chunk_groups))
            self.assertTrue(callable(helper.normalize_batch_results))
            self.assertEqual(helper.SUPPORTED_BATCH_SIZES, (1, 4, 8, 16))
            manifest_path = assets_root / batch_runtime.MANIFEST_NAME
            original = manifest_path.read_bytes()
            manifest_path.write_bytes(b"{}")
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._load_manifest(assets_root)
            manifest_path.write_bytes(b"{")
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._load_manifest(assets_root)
            manifest_path.write_bytes(
                original.replace(b'"format":"envai-pii-batch-overlay-1"',
                                 b'"format":"envai-pii-batch-overlay-1",'
                                 b'"format":"envai-pii-batch-overlay-1"'))
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._load_manifest(assets_root)
            manifest_path.write_bytes(original)
            helper_path = assets_root / Path(batch_runtime.HELPER_ASSET).name
            helper_path.write_bytes(helper_path.read_bytes() + b"\n")
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._load_helper(assets_root, manifest)
            for source in (b"def invalid(:\n", b"value = 1\n"):
                helper_path.write_bytes(source)
                changed = dict(manifest)
                changed["helper_sha256"] = hashlib.sha256(source).hexdigest()
                with self.assertRaises(batch_runtime.BatchOverlayError):
                    batch_runtime._load_helper(assets_root, changed)
            helper_path.write_bytes(
                batch_package.BATCH_HELPER_SOURCE.read_bytes())
            manifest_path.write_bytes(original)
            changed = dict(manifest)
            changed["helper_sha256"] = "0" * 64
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._load_helper(assets_root, changed)
            changed = dict(manifest)
            changed.pop("helper_sha256")
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._validate_manifest(changed)
            changed = dict(manifest)
            changed["batch_sizes"] = [1, 2]
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._validate_manifest(changed)
            changed = dict(manifest)
            changed["workers"] = 1
            with self.assertRaises(batch_runtime.BatchOverlayError):
                batch_runtime._validate_manifest(changed)
            self.assertEqual(app_root, app_root)


class ConfigTests(unittest.TestCase):
    def test_load_gunicorn_config_wraps_only_post_worker_init(self):
        base_post = lambda worker: None
        base_exit = lambda server, worker: None
        base_config = {
            "workers": 8,
            "worker_class": "gthread",
            "post_worker_init": base_post,
            "worker_exit": base_exit,
            "extra": "kept",
        }
        with mock.patch.object(
                batch_runtime.gpu_runtime, "load_gunicorn_config",
                return_value=base_config):
            config = batch_runtime.load_gunicorn_config(
                app_root=Path("/app/src/app"),
                runtime_root=Path("/tmp/runtime"))
        self.assertEqual(config["workers"], 8)
        self.assertEqual(config["worker_class"], "gthread")
        self.assertEqual(config["worker_exit"], base_exit)
        self.assertEqual(config["extra"], "kept")
        self.assertIsNot(config["post_worker_init"], base_post)
        self.assertTrue(callable(config["post_worker_init"]))
        self.assertEqual(config.get("workers"), 8)
        for workers in (12, 16):
            changed = dict(base_config)
            changed["workers"] = workers
            with self.subTest(workers=workers), mock.patch.object(
                    batch_runtime.gpu_runtime, "load_gunicorn_config",
                    return_value=changed):
                accepted = batch_runtime.load_gunicorn_config()
                self.assertEqual(accepted["workers"], workers)
                self.assertIsNot(accepted["post_worker_init"], base_post)
        for workers, post in ((1, base_post), (4, base_post), (9, base_post),
                              (13, base_post), (8, None), (12, None)):
            changed = dict(base_config)
            changed["workers"] = workers
            changed["post_worker_init"] = post
            with self.subTest(workers=workers), mock.patch.object(
                    batch_runtime.gpu_runtime, "load_gunicorn_config",
                    return_value=changed):
                with self.assertRaises(RuntimeError):
                    batch_runtime.load_gunicorn_config()

    def test_load_gunicorn_config_rejects_unsupported_profile(self):
        with mock.patch.object(
                batch_runtime.gpu_runtime, "load_gunicorn_config",
                return_value={"workers": 9, "post_worker_init": lambda w: None}):
            with self.assertRaisesRegex(
                    RuntimeError, "requires a supported worker count"):
                batch_runtime.load_gunicorn_config()
        with mock.patch.object(
                batch_runtime.gpu_runtime, "load_gunicorn_config",
                return_value={"workers": 8, "post_worker_init": None}):
            with self.assertRaisesRegex(
                    RuntimeError, "base gunicorn hooks unavailable"):
                batch_runtime.load_gunicorn_config()


if __name__ == "__main__":
    unittest.main()
