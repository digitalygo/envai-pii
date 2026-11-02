import builtins
import contextlib
import hashlib
import inspect
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.verda_model_experiment import fixture, runtime


class FakeTensor:
    def __init__(self, elements, item_bytes, dtype="torch.float16"):
        self.elements = elements
        self.item_bytes = item_bytes
        self.dtype = dtype

    def numel(self):
        return self.elements

    def element_size(self):
        return self.item_bytes


class FakeModel:
    def parameters(self):
        return [FakeTensor(10, 2), FakeTensor(3, 4, "torch.float32")]

    def buffers(self):
        return [FakeTensor(4, 2)]


class FakePipeline:
    model = FakeModel()


class FakeCuda:
    def __init__(self, *, count=1, name="NVIDIA L40S", available=True):
        self.count = count
        self.name = name
        self.available = available

    def is_available(self):
        return self.available

    def device_count(self):
        return self.count

    def get_device_name(self, index):
        return self.name

    def reset_peak_memory_stats(self, index):
        self.reset_index = index

    def synchronize(self, index):
        self.sync_index = index

    def memory_allocated(self, index):
        return 2_000

    def mem_get_info(self, index):
        return 8_000, 16_000

    def max_memory_allocated(self, index):
        return 4_000


class FakeTorch:
    def __init__(self, cuda=None):
        self.cuda = cuda or FakeCuda()


class FakeWorker:
    def __init__(self, module, pid=None):
        self.wsgi = type("Wsgi", (), {"module": module})()
        self.pid = os.getpid() if pid is None else pid


class RuntimeFixture(unittest.TestCase):
    def _source_fixture(self, root):
        values = {}
        for name in runtime.SOURCE_HASHES:
            contents = f"trusted fixture {name}".encode()
            (root / name).write_bytes(contents)
            values[name] = hashlib.sha256(contents).hexdigest()
        return values

    def _config_fixture(self, root):
        path = root / "gunicorn_config.py"
        path.write_text(
            "workers=1\nworker_class='gthread'\nthreads=50\npreload_app=False\n",
            encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _write_proc_stat(self, proc_root, pid, ticks):
        process_dir = proc_root / str(pid)
        process_dir.mkdir(parents=True)
        fields = ["S"] + ["0"] * 18 + [str(ticks)]
        (process_dir / "stat").write_text(
            f"{pid} (fake process name) {' '.join(fields)}", encoding="ascii")

    def test_fixture_is_fixed_utf8_and_compact_json(self):
        body = fixture.build_json_body(fixture.FIXTURE_TEXT)
        self.assertEqual(fixture.generate_text(45_000, 42), fixture.FIXTURE_TEXT)
        self.assertEqual(len(fixture.FIXTURE_TEXT), 45_000)
        self.assertEqual(len(fixture.FIXTURE_TEXT.encode("utf-8")), 45_163)
        self.assertEqual(hashlib.sha256(fixture.FIXTURE_TEXT.encode()).hexdigest(),
                         "97adc9b463df5728344baa30b734db39a09d24986a1c3d01ffccde3ade3e6fca")
        self.assertEqual(len(body), 45_174)
        self.assertEqual(hashlib.sha256(body).hexdigest(),
                         "d2a274f2ab87b0d3d71f2b9be595350e5a9ce0c919f11a7eea12a2d168d33b59")
        self.assertEqual(json.loads(body), {"text": fixture.FIXTURE_TEXT})

    def test_fixture_rejects_invalid_sizes_and_request_numbers(self):
        for values in ((0, 42), (-1, 42), (True, 42), (1, -1), (1, True), (1, 2.0)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                fixture.generate_text(*values)
        with self.assertRaises(ValueError):
            fixture.generate_text(5, 123456)

    def test_verify_sources_hashes_only_fixed_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = self._source_fixture(root)
            with mock.patch.object(runtime, "SOURCE_HASHES", expected):
                self.assertTrue(all(runtime.verify_sources(root).values()))
                (root / "app.py").write_text("changed", encoding="utf-8")
                result = runtime.verify_sources(root)
            self.assertFalse(result["app.py"])
            self.assertTrue(result["gunicorn_config.py"])

    def test_fixed_container_source_hashes_are_pinned(self):
        self.assertEqual(runtime.SOURCE_HASHES, {
            "app.py": "b0ec5163cd0d9eee05922d4b80718eb26abc762b0612935e1f1ad8275dc3848e",
            "gunicorn_config.py": "8a8d58411b7aca4fd2dea37921e32c373403cf41cd7907863c658405246ab069",
            "runtime_execution.py": "eb03f52dfc1b3ac9d36971b453fb84ad50e92d04ad7cd3d3a241a4c09df8b02a",
            "cloud_service.py": "5b79bdd845e4f3ff9e3f2d8b2657e902f278a11da02021ac0e8473d40b608a4e",
        })

    def test_source_missing_is_a_failed_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(runtime, "SOURCE_HASHES", {"app.py": "0" * 64}):
                self.assertEqual(runtime.verify_sources(Path(temporary)), {"app.py": False})

    def test_config_derives_trusted_base_without_torch_and_resets_run_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "app"
            runtime_root = Path(temporary) / "runtime"
            root.mkdir()
            expected = self._source_fixture(root)
            expected["gunicorn_config.py"] = self._config_fixture(root)
            stale = runtime_root / "run-profile-a"
            stale.mkdir(parents=True)
            (stale / "ready-1.json").write_text("stale", encoding="ascii")
            environment = {
                runtime.PROFILE_WORKERS_ENV: "4",
                runtime.PROFILE_RUN_ID_ENV: "profile-a",
            }
            with mock.patch.object(runtime, "SOURCE_HASHES", expected), \
                    mock.patch.dict(os.environ, environment, clear=False), \
                    mock.patch.dict("sys.modules", {"torch": None}):
                config = runtime.load_gunicorn_config(app_root=root,
                                                      runtime_root=runtime_root)
            self.assertEqual(config["workers"], 4)
            self.assertEqual(config["worker_class"], "gthread")
            self.assertEqual(config["threads"], 50)
            self.assertFalse(config["preload_app"])
            self.assertEqual(config["timeout"], 600)
            self.assertEqual(config["graceful_timeout"], 30)
            self.assertEqual(config["accesslog"], "/dev/null")
            self.assertTrue(callable(config["post_worker_init"]))
            self.assertFalse((stale / "ready-1.json").exists())
            self.assertEqual(runtime._ACTIVE_RUN_ID, "profile-a")

    def test_config_rejects_untrusted_source_and_base_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._source_fixture(root)
            self._config_fixture(root)
            with mock.patch.object(runtime, "SOURCE_HASHES", {"app.py": "0" * 64}):
                with self.assertRaisesRegex(RuntimeError, "source_integrity_failed"):
                    runtime.load_gunicorn_config(app_root=root,
                                                 runtime_root=root / "runtime")
            expected = self._source_fixture(root)
            (root / "gunicorn_config.py").write_text(
                "workers=2\nworker_class='gthread'\nthreads=50\npreload_app=False\n",
                encoding="utf-8")
            expected["gunicorn_config.py"] = hashlib.sha256(
                (root / "gunicorn_config.py").read_bytes()).hexdigest()
            with mock.patch.object(runtime, "SOURCE_HASHES", expected), \
                    mock.patch.dict(os.environ, {
                        runtime.PROFILE_WORKERS_ENV: "1",
                        runtime.PROFILE_RUN_ID_ENV: "profile-b",
                    }, clear=False):
                with self.assertRaisesRegex(RuntimeError, "source_integrity_failed"):
                    runtime.load_gunicorn_config(app_root=root,
                                                 runtime_root=root / "runtime")

    def test_config_rejects_invalid_profile_and_unsafe_runtime_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "app"
            runtime_root = Path(temporary) / "runtime"
            root.mkdir()
            expected = self._source_fixture(root)
            expected["gunicorn_config.py"] = self._config_fixture(root)
            with mock.patch.object(runtime, "SOURCE_HASHES", expected), \
                    mock.patch.dict(os.environ, {
                        runtime.PROFILE_WORKERS_ENV: "3",
                        runtime.PROFILE_RUN_ID_ENV: "safe",
                    }, clear=False):
                with self.assertRaisesRegex(RuntimeError, "invalid worker profile"):
                    runtime.load_gunicorn_config(app_root=root,
                                                 runtime_root=runtime_root)
            runtime_root.symlink_to(root, target_is_directory=True)
            with mock.patch.object(runtime, "SOURCE_HASHES", expected), \
                    mock.patch.dict(os.environ, {
                        runtime.PROFILE_WORKERS_ENV: "1",
                        runtime.PROFILE_RUN_ID_ENV: "safe",
                    }, clear=False):
                with self.assertRaisesRegex(RuntimeError, "runtime directory unsafe"):
                    runtime.load_gunicorn_config(app_root=root,
                                                 runtime_root=runtime_root)

    def test_supported_worker_profile_keeps_legacy_and_new_counts(self):
        self.assertEqual(runtime.SUPPORTED_WORKERS,
                         frozenset({1, 2, 4, 8, 12, 16}))

    def test_config_accepts_twelve_and_sixteen_worker_profiles(self):
        for workers in (12, 16):
            with self.subTest(workers=workers), \
                    tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "app"
                runtime_root = Path(temporary) / "runtime"
                root.mkdir()
                expected = self._source_fixture(root)
                expected["gunicorn_config.py"] = self._config_fixture(root)
                with mock.patch.object(runtime, "SOURCE_HASHES", expected), \
                        mock.patch.dict(os.environ, {
                            runtime.PROFILE_WORKERS_ENV: str(workers),
                            runtime.PROFILE_RUN_ID_ENV: f"copies-{workers}",
                        }, clear=False):
                    config = runtime.load_gunicorn_config(
                        app_root=root, runtime_root=runtime_root)
                self.assertEqual(config["workers"], workers)
                self.assertEqual(runtime._ACTIVE_WORKERS, workers)
        for workers in (3, 9, 13, 15, 17, "08"):
            with self.subTest(rejected=workers), \
                    tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "app"
                root.mkdir()
                expected = self._source_fixture(root)
                expected["gunicorn_config.py"] = self._config_fixture(root)
                with mock.patch.object(runtime, "SOURCE_HASHES", expected), \
                        mock.patch.dict(os.environ, {
                            runtime.PROFILE_WORKERS_ENV: str(workers),
                            runtime.PROFILE_RUN_ID_ENV: "copies-invalid",
                        }, clear=False):
                    with self.assertRaisesRegex(
                            RuntimeError, "invalid worker profile"):
                        runtime.load_gunicorn_config(
                            app_root=root, runtime_root=root / "runtime")

    def test_run_id_and_pid_start_time_validation(self):
        for value in ("", ".", "../bad", "x/y", "a" * 65, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runtime.validate_run_id(value)
        with tempfile.TemporaryDirectory() as temporary:
            proc_root = Path(temporary)
            self._write_proc_stat(proc_root, 321, 99)
            self.assertEqual(runtime._proc_start_ticks(321, proc_root), 99)
            self.assertIsNone(runtime._proc_start_ticks(322, proc_root))
            self.assertTrue(runtime._pid_is_live(
                321, 99, proc_root, kill=lambda pid, signal: None))
            self.assertFalse(runtime._pid_is_live(
                321, 98, proc_root, kill=lambda pid, signal: None))
            self.assertFalse(runtime._pid_is_live(
                321, 99, proc_root,
                kill=lambda pid, signal: (_ for _ in ()).throw(ProcessLookupError())))

    def test_barrier_requires_exact_distinct_live_pids_and_current_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_path = root / "run-test-run"
            run_path.mkdir()
            proc_root = root / "proc"
            proc_root.mkdir()
            self._write_proc_stat(proc_root, 101, 11)
            self._write_proc_stat(proc_root, 102, 22)
            (run_path / "ready-101.json").write_text(json.dumps({
                "run_id": "test-run", "pid": 101, "start_ticks": 11}), encoding="ascii")
            (run_path / "ready-102.json").write_text(json.dumps({
                "run_id": "old-run", "pid": 102, "start_ticks": 22}), encoding="ascii")
            alive = {101, 102}
            kill = lambda pid, signal: None if pid in alive else (_ for _ in ()).throw(
                ProcessLookupError())
            now = [0.0]
            sleep = lambda duration: now.__setitem__(0, now[0] + duration)
            self.assertFalse(runtime.wait_for_worker_barrier(
                run_path, "test-run", 2, timeout_seconds=0.2,
                interval_seconds=0.1, clock=lambda: now[0], sleep=sleep,
                proc_root=proc_root, kill=kill))
            (run_path / "ready-102.json").write_text(json.dumps({
                "run_id": "test-run", "pid": 101, "start_ticks": 11}), encoding="ascii")
            now[0] = 0.0
            self.assertFalse(runtime.wait_for_worker_barrier(
                run_path, "test-run", 2, timeout_seconds=0.1,
                interval_seconds=0.1, clock=lambda: now[0], sleep=sleep,
                proc_root=proc_root, kill=kill))
            (run_path / "ready-102.json").write_text(json.dumps({
                "run_id": "test-run", "pid": 102, "start_ticks": 22}), encoding="ascii")
            self.assertTrue(runtime.wait_for_worker_barrier(
                run_path, "test-run", 2, timeout_seconds=0.1,
                proc_root=proc_root, kill=kill))
            alive.remove(102)
            self.assertFalse(runtime.wait_for_worker_barrier(
                run_path, "test-run", 2, timeout_seconds=0,
                proc_root=proc_root, kill=kill))

    def test_barrier_requires_all_twelve_and_sixteen_live_pids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc_root = root / "proc"
            proc_root.mkdir()
            for index in range(16):
                self._write_proc_stat(proc_root, 1000 + index, index + 1)
            self._write_proc_stat(proc_root, 9999, 99)
            for workers in (12, 16):
                with self.subTest(workers=workers):
                    run_path = root / f"run-copies-{workers}"
                    run_path.mkdir()
                    for index in range(workers):
                        (run_path / f"ready-{1000 + index}.json").write_text(
                            json.dumps({
                                "run_id": f"copies-{workers}",
                                "pid": 1000 + index,
                                "start_ticks": index + 1,
                            }), encoding="ascii")
                    kill = lambda pid, signal: None
                    self.assertTrue(runtime.wait_for_worker_barrier(
                        run_path, f"copies-{workers}", workers,
                        timeout_seconds=0, proc_root=proc_root, kill=kill))
                    (run_path / "ready-9999.json").write_text(json.dumps({
                        "run_id": f"copies-{workers}",
                        "pid": 9999,
                        "start_ticks": 99,
                    }), encoding="ascii")
                    self.assertFalse(runtime.wait_for_worker_barrier(
                        run_path, f"copies-{workers}", workers,
                        timeout_seconds=0, proc_root=proc_root, kill=kill))
                    (run_path / f"ready-{1000 + workers - 1}.json").unlink()
                    self.assertTrue(runtime.wait_for_worker_barrier(
                        run_path, f"copies-{workers}", workers,
                        timeout_seconds=0, proc_root=proc_root, kill=kill))
            self.assertFalse(runtime.wait_for_worker_barrier(
                root / "run-copies-12", "copies-12", 9,
                timeout_seconds=0, proc_root=proc_root,
                kill=lambda pid, signal: None))

    def test_private_runtime_directories_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            linked_root = root / "linked"
            linked_root.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "runtime directory unsafe"):
                runtime._set_private_directory(linked_root)
            with mock.patch.object(Path, "chmod", side_effect=OSError()):
                with self.assertRaisesRegex(RuntimeError, "runtime directory unavailable"):
                    runtime._set_private_directory(root / "private")
            run_root = root / "runs"
            run_root.mkdir()
            linked_run = run_root / "run-case"
            linked_run.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "runtime directory unsafe"):
                runtime._reset_run_directory(run_root, "case")
            linked_run.unlink()
            (run_root / "run-case").mkdir()
            with mock.patch.object(runtime.shutil, "rmtree", side_effect=OSError()):
                with self.assertRaisesRegex(RuntimeError, "runtime directory unavailable"):
                    runtime._reset_run_directory(run_root, "case")
            runtime.shutil.rmtree(run_root / "run-case")
            original_mkdir = Path.mkdir

            def fail_run_directory(path, *args, **kwargs):
                if path.name == "run-case":
                    raise OSError()
                return original_mkdir(path, *args, **kwargs)

            with mock.patch.object(Path, "mkdir", fail_run_directory):
                with self.assertRaisesRegex(RuntimeError, "runtime directory unavailable"):
                    runtime._reset_run_directory(run_root, "case")

    def test_marker_parser_rejects_unreadable_malformed_and_stale_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_path = root / "run-safe"
            run_path.mkdir()
            (run_path / "ready-101.json").write_text("not json", encoding="ascii")
            (run_path / "ready-102.json").write_text(
                json.dumps({"run_id": "safe", "pid": "102", "start_ticks": 4}),
                encoding="ascii")
            (run_path / "ready-103.json").symlink_to(run_path / "ready-101.json")
            self.assertEqual(runtime._read_live_markers(run_path, "safe"), set())
            with mock.patch.object(Path, "glob", side_effect=OSError()):
                self.assertEqual(runtime._read_live_markers(run_path, "safe"), set())
            with mock.patch.object(runtime.os, "open", side_effect=OSError()), \
                    mock.patch.object(Path, "unlink", side_effect=OSError()):
                with self.assertRaisesRegex(RuntimeError, "worker marker unavailable"):
                    runtime._write_ready_marker(run_path, "safe", 104, 5)

    def test_ready_marker_is_atomic_private_and_pid_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_path = Path(temporary) / "run-x"
            run_path.mkdir(mode=0o700)
            runtime._write_ready_marker(run_path, "x", 123, 456)
            marker = run_path / "ready-123.json"
            self.assertEqual(json.loads(marker.read_text(encoding="ascii")), {
                "run_id": "x", "pid": 123, "start_ticks": 456})
            self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
            self.assertFalse((run_path / "ready-123.tmp").exists())

    def test_cgroup_metrics_are_numeric_or_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = {
                "memory.current": "1000", "memory.peak": "1500",
                "memory.max": "max", "pids.current": "8", "pids.max": "max",
                "cpu.max": "max 100000",
            }
            for name, value in values.items():
                (root / name).write_text(value, encoding="ascii")
            metrics = runtime._resource_metrics(
                FakeTorch(), root, affinity=lambda pid: {0, 1})
            self.assertEqual(metrics["cgroup_memory_current_bytes"], 1000)
            self.assertEqual(metrics["cgroup_memory_peak_bytes"], 1500)
            self.assertIsNone(metrics["cgroup_memory_limit_bytes"])
            self.assertEqual(metrics["cgroup_memory_limit_reason"], "limit_unavailable")
            self.assertEqual(metrics["cgroup_pids_current"], 8)
            self.assertIsNone(metrics["cgroup_pids_limit"])
            self.assertEqual(metrics["cuda_allocated_bytes"], 2_000)
            self.assertEqual(metrics["cuda_free_bytes"], 8_000)
            self.assertEqual(metrics["cuda_total_bytes"], 16_000)
            self.assertEqual(metrics["torch_max_allocated_bytes"], 4_000)
            self.assertEqual(metrics["cpu_period_us"], 100_000)
            self.assertIsNone(metrics["cpu_quota_us"])
            self.assertEqual(metrics["cpu_affinity_count"], 2)

    def test_cgroup_missing_invalid_and_torch_failures_are_not_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "memory.current").write_text("oops", encoding="ascii")
            (root / "cpu.max").write_text("broken", encoding="ascii")
            metrics = runtime._resource_metrics(
                None, root, affinity=lambda pid: (_ for _ in ()).throw(OSError()))
            self.assertIsNone(metrics["cuda_allocated_bytes"])
            self.assertEqual(metrics["cuda_allocated_reason"], "torch_metric_unavailable")
            self.assertIsNone(metrics["cgroup_memory_current_bytes"])
            self.assertEqual(metrics["cgroup_memory_current_reason"], "cgroup_value_invalid")
            self.assertIsNone(metrics["cgroup_memory_peak_bytes"])
            self.assertEqual(metrics["cgroup_memory_peak_reason"], "cgroup_file_missing")
            self.assertIsNone(metrics["cpu_period_us"])
            self.assertEqual(metrics["cpu_quota_reason"], "cgroup_value_invalid")
            self.assertIsNone(metrics["cpu_affinity_count"])

    def test_resource_parsers_reject_negative_and_malformed_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = root / "current"
            current.write_text("-1", encoding="ascii")
            self.assertEqual(runtime._read_cgroup_number(current),
                             (None, "cgroup_value_invalid"))
            self.assertEqual(runtime._read_cgroup_number(root / "missing"),
                             (None, "cgroup_file_missing"))
            cpu = root / "cpu.max"
            cpu.write_text("1000 0", encoding="ascii")
            self.assertEqual(runtime._read_cpu_limit(cpu),
                             (None, None, "cgroup_value_invalid"))
            cpu.write_text("-1 100000", encoding="ascii")
            self.assertEqual(runtime._read_cpu_limit(cpu),
                             (None, None, "cgroup_value_invalid"))
            cpu.write_text("1000 nope", encoding="ascii")
            self.assertEqual(runtime._read_cpu_limit(cpu),
                             (None, None, "cgroup_value_invalid"))

    def test_model_footprint_counts_parameters_buffers_and_rejects_unknown_dtype(self):
        parameters, buffers, dtypes = runtime._model_footprint(FakePipeline())
        self.assertEqual(parameters, 32)
        self.assertEqual(buffers, 8)
        self.assertEqual(dtypes, "float16,float32")
        model = type("Model", (), {
            "parameters": lambda self: [FakeTensor(1, 1, "torch.complex64")],
            "buffers": lambda self: [],
        })()
        with self.assertRaisesRegex(RuntimeError, "unknown dtype"):
            runtime._model_footprint(type("Pipeline", (), {"model": model})())
        with self.assertRaisesRegex(RuntimeError, "model metrics unavailable"):
            runtime._model_footprint(object())

    def test_gpu_profile_requires_one_l40s(self):
        self.assertEqual(runtime._gpu_profile(FakeTorch()), (True, 1, True, None))
        self.assertEqual(runtime._gpu_profile(FakeTorch(FakeCuda(count=2))),
                         (False, 2, False, "gpu_profile_mismatch"))
        self.assertEqual(runtime._gpu_profile(FakeTorch(FakeCuda(name="A100"))),
                         (False, 1, False, "gpu_profile_mismatch"))
        self.assertEqual(runtime._gpu_profile(FakeTorch(FakeCuda(available=False))),
                         (False, 0, False, "gpu_profile_mismatch"))

    def test_event_writer_accepts_only_fixed_safe_numeric_schema(self):
        writes = []
        with mock.patch.object(runtime.os, "write", side_effect=lambda fd, line: writes.append(line)):
            runtime.emit_event("ready", "run-1", 123, 1, request_count=4,
                               model_dtypes="float16,float32")
            runtime.emit_event("ready", "run-1", 123, 1, body="synthetic")
            runtime.emit_event("ready", "run-1", 123, 1, error_code="secret value")
        self.assertEqual(len(writes), 1)
        line = writes[0].decode("ascii")
        self.assertTrue(line.startswith("VERDAEXPERIMENT "))
        payload = json.loads(line.removeprefix("VERDAEXPERIMENT "))
        self.assertEqual(payload["request_count"], 4)
        self.assertNotIn("body", payload)

    def test_event_writer_accepts_supported_worker_counts_and_rejects_others(self):
        writes = []
        with mock.patch.object(
                runtime.os, "write",
                side_effect=lambda fd, line: writes.append(line)):
            for workers in (1, 2, 4, 8, 12, 16):
                runtime.emit_event("ready", "run-1", 123, workers,
                                   request_count=workers)
            for workers in (0, 3, 9, 13, 15, 17, True, 8.0, "8"):
                runtime.emit_event("ready", "run-1", 123, workers,
                                   request_count=1)
        self.assertEqual(len(writes), 6)
        emitted = [json.loads(line.decode("ascii").removeprefix(
            "VERDAEXPERIMENT ")) for line in writes]
        self.assertEqual([payload["workers"] for payload in emitted],
                         [1, 2, 4, 8, 12, 16])

    def test_telemetry_samples_only_allowlisted_values_and_request_count(self):
        class StopAfterSample:
            def __init__(self):
                self.calls = 0

            def wait(self, interval):
                self.calls += 1
                return self.calls > 1

        module = type("Application", (), {"nlp": FakePipeline()})()
        worker = FakeWorker(module)
        worker._verda_request_count = 7
        stop = StopAfterSample()
        events = []
        with (
            mock.patch.dict(os.environ, runtime.EXPECTED_ENV, clear=False),
            mock.patch.object(runtime, "_ACTIVE_THREADS", runtime.EXPECTED_THREADS),
            mock.patch.object(runtime, "verify_sources", return_value={
                name: True for name in runtime.SOURCE_HASHES}),
            mock.patch.object(runtime, "_event_metrics", return_value={}),
            mock.patch.object(runtime, "_gpu_profile", return_value=(
                True, 1, True, None)),
            mock.patch.object(runtime, "emit_event", side_effect=lambda *args, **kwargs:
                events.append((args, kwargs))),
        ):
            runtime._telemetry_loop(stop, worker, "sample-run", 1, FakeTorch())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0][0], "sample")
        self.assertEqual(events[0][1]["request_count"], 7)
        self.assertTrue(events[0][1]["settings_ok"])

    def test_post_request_matches_gunicorn_hook_arity_without_inspecting_context(self):
        parameters = tuple(inspect.signature(runtime.post_request).parameters.values())
        self.assertEqual(len(parameters), 4)
        self.assertTrue(all(
            parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
            for parameter in parameters
        ))

        class PrivateRequestContext:
            def __getattribute__(self, name):
                raise AssertionError("request context must remain opaque")

        worker = type("Worker", (), {"_verda_request_count": 0})()
        runtime.post_request(
            worker, PrivateRequestContext(), PrivateRequestContext(), PrivateRequestContext())
        self.assertEqual(worker._verda_request_count, 1)

    def test_worker_warms_existing_pipeline_and_waits_before_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_root = root / "app"
            app_root.mkdir()
            expected = self._source_fixture(app_root)
            calls = []
            module = type("Application", (), {
                "nlp": FakePipeline(),
                "device": 0,
                "detect_model": staticmethod(lambda text: calls.append(len(text))),
            })()
            worker = FakeWorker(module)
            run_id = "one-worker"
            run_path = runtime._reset_run_directory(root / "private", run_id)
            writes = []
            with mock.patch.object(runtime, "SOURCE_HASHES", expected), \
                    mock.patch.object(runtime, "APP_SOURCE", app_root), \
                    mock.patch.object(runtime, "_ACTIVE_RUN_ID", run_id), \
                    mock.patch.object(runtime, "_ACTIVE_WORKERS", 1), \
                    mock.patch.object(runtime, "_ACTIVE_RUNTIME_ROOT", root / "private"), \
                    mock.patch.dict(os.environ, runtime.EXPECTED_ENV, clear=False), \
                    mock.patch("builtins.__import__", side_effect=self._torch_import(FakeTorch())), \
                    mock.patch.object(runtime.os, "write", side_effect=lambda fd, line: writes.append(line)):
                runtime.post_worker_init(worker)
                self.assertEqual(calls, [45_000])
                self.assertEqual(worker._verda_request_count, 0)
                runtime.post_request(worker, object(), object(), object())
                self.assertEqual(worker._verda_request_count, 1)
                runtime.worker_exit(None, worker)
                runtime.child_exit(None, worker)
            self.assertFalse((run_path / f"ready-{worker.pid}.json").exists())
            events = [json.loads(line.decode().split(" ", 1)[1]) for line in writes]
            ready = next(event for event in events if event["event"] == "ready")
            self.assertEqual(ready["parameter_bytes"], 32)
            self.assertEqual(ready["buffer_bytes"], 8)
            self.assertEqual(ready["model_dtypes"], "float16,float32")
            self.assertEqual(ready["max_concurrent_analyses"], 16)
            self.assertEqual(ready["gunicorn_threads"], 50)
            self.assertTrue(ready["auth_upstream"])
            self.assertTrue(ready["gpu_l40s"])
            self.assertTrue(any(event["event"] == "exit" and
                                event["request_count"] == 1 for event in events))
            self.assertTrue(any(event["event"] == "child_exit" and
                                event["marker_removed"] for event in events))

    @staticmethod
    def _torch_import(torch_module):
        original_import = builtins.__import__

        def importer(name, *args, **kwargs):
            if name == "torch":
                return torch_module
            return original_import(name, *args, **kwargs)
        return importer

    @contextlib.contextmanager
    def _active_worker(self, app_root, run_id, workers, runtime_root):
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(runtime, "APP_SOURCE", app_root))
            stack.enter_context(mock.patch.object(runtime, "_ACTIVE_RUN_ID", run_id))
            stack.enter_context(mock.patch.object(runtime, "_ACTIVE_WORKERS", workers))
            stack.enter_context(mock.patch.object(runtime, "_ACTIVE_THREADS",
                                                 runtime.EXPECTED_THREADS))
            stack.enter_context(mock.patch.object(runtime, "_ACTIVE_RUNTIME_ROOT", runtime_root))
            yield

    def test_worker_fails_closed_on_source_settings_gpu_and_barrier_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_root = root / "app"
            app_root.mkdir()
            expected = self._source_fixture(app_root)
            module = type("Application", (), {
                "nlp": FakePipeline(), "device": 0,
                "detect_model": staticmethod(lambda text: None),
            })()
            worker = FakeWorker(module)
            run_id = "failure-run"
            runtime._reset_run_directory(root / "private", run_id)
            with mock.patch.object(runtime, "SOURCE_HASHES", {"app.py": "0" * 64}), \
                    self._active_worker(app_root, run_id, 2, root / "private"), \
                    mock.patch.object(runtime.os, "write"):
                with self.assertRaisesRegex(RuntimeError, "worker startup failed"):
                    runtime.post_worker_init(worker)
            with mock.patch.object(runtime, "SOURCE_HASHES", expected), \
                    self._active_worker(app_root, run_id, 2, root / "private"), \
                    mock.patch.dict(os.environ, {"PII_AUTH_MODE": "bad"}, clear=False), \
                    mock.patch.object(runtime.os, "write"):
                with self.assertRaisesRegex(RuntimeError, "worker startup failed"):
                    runtime.post_worker_init(worker)
            with mock.patch.object(runtime, "SOURCE_HASHES", expected), \
                    self._active_worker(app_root, run_id, 2, root / "private"), \
                    mock.patch.dict(os.environ, runtime.EXPECTED_ENV, clear=False), \
                    mock.patch("builtins.__import__", side_effect=self._torch_import(
                        FakeTorch(FakeCuda(count=2)))), mock.patch.object(runtime.os, "write"):
                with self.assertRaisesRegex(RuntimeError, "worker startup failed"):
                    runtime.post_worker_init(worker)
            with mock.patch.object(runtime, "SOURCE_HASHES", expected), \
                    self._active_worker(app_root, run_id, 2, root / "private"), \
                    mock.patch.dict(os.environ, runtime.EXPECTED_ENV, clear=False), \
                    mock.patch("builtins.__import__", side_effect=self._torch_import(FakeTorch())), \
                    mock.patch.object(runtime, "wait_for_worker_barrier", return_value=False), \
                    mock.patch.object(runtime.os, "write"):
                with self.assertRaisesRegex(RuntimeError, "worker startup failed"):
                    runtime.post_worker_init(worker)
            self.assertFalse((root / "private" / f"run-{run_id}" /
                              f"ready-{worker.pid}.json").exists())

    def test_resource_guard_compatibility_wrappers_match_controller_module(self):
        from tools.verda_model_experiment import evaluate_resource_guard, resources

        observed = {
            "current_workers": 1,
            "per_worker_peak_bytes": 2_000,
            "per_worker_pids": 20,
            "observed_per_worker_gpu_peak_bytes": 2_000,
        }
        limits = {
            "memory_current_bytes": 10_000,
            "memory_limit_bytes": 20_000,
            "pids_current": 100,
            "pids_limit": 200,
            "gpu_free_bytes": 8_000,
            "gpu_total_bytes": 16_000,
        }
        expected = resources.evaluate_resource_guard(2, observed, limits, 1_000)
        self.assertEqual(runtime.evaluate_resource_guard(
            2, observed, limits, 1_000), expected)
        self.assertEqual(evaluate_resource_guard(
            2, observed, limits, 1_000), expected)
        self.assertEqual(expected["required_memory_bytes"], 16_250)
        self.assertEqual(expected["required_pids"], 150)

    def test_resource_guard_requires_known_limits_and_margin(self):
        observed = {
            "current_workers": 1,
            "per_worker_peak_bytes": 2_000,
            "per_worker_pids": 20,
            "observed_per_worker_gpu_peak_bytes": 2_000,
        }
        limits = {
            "memory_current_bytes": 10_000,
            "memory_limit_bytes": 20_000,
            "pids_current": 100,
            "pids_limit": 200,
            "gpu_free_bytes": 8_000,
            "gpu_total_bytes": 16_000,
        }
        result = runtime.evaluate_resource_guard(2, observed, limits, 1_000)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason"], "headroom_verified")
        self.assertEqual(result["projected_memory_bytes"], 13_000)
        self.assertEqual(result["required_memory_bytes"], 16_250)
        self.assertEqual(result["required_pids"], 150)
        too_small = dict(limits, memory_limit_bytes=16_249)
        self.assertEqual(runtime.evaluate_resource_guard(
            2, observed, too_small, 1_000)["reason"], "memory_headroom_insufficient")
        too_few_pids = dict(limits, pids_limit=149)
        self.assertEqual(runtime.evaluate_resource_guard(
            2, observed, too_few_pids, 1_000)["reason"], "pid_headroom_insufficient")
        unknown = dict(limits, pids_limit=None)
        self.assertFalse(runtime.evaluate_resource_guard(
            2, observed, unknown, 1_000)["allowed"])
        self.assertEqual(runtime.evaluate_resource_guard(
            2, observed, unknown, 1_000)["reason"], "pids_limit_unknown")
        unknown_memory = dict(limits, memory_limit_bytes=None)
        self.assertEqual(runtime.evaluate_resource_guard(
            2, observed, unknown_memory, 1_000)["reason"], "memory_limit_unknown")
        self.assertEqual(runtime.evaluate_resource_guard(
            3, observed, limits, 1_000)["reason"], "unsupported_workers")
        self.assertEqual(runtime.evaluate_resource_guard(
            2, observed, limits, 0)["reason"], "invalid_observation")
        self.assertEqual(runtime.evaluate_resource_guard(
            2, observed, limits, True)["reason"], "loading_margin_unknown")

        scale_limits = dict(
            limits,
            memory_limit_bytes=100_000,
            pids_limit=1_000,
            gpu_free_bytes=50_000,
            gpu_total_bytes=60_000,
        )
        for workers in (2, 4, 8):
            with self.subTest(workers=workers):
                allowed = runtime.evaluate_resource_guard(
                    workers, observed, scale_limits, 1_000)
                extra_workers = workers - observed["current_workers"]
                additional_gpu = extra_workers * observed[
                    "observed_per_worker_gpu_peak_bytes"] + 1_000
                current_gpu_used = 10_000
                projected_gpu_used = current_gpu_used + additional_gpu
                required_gpu_total = (projected_gpu_used * 5 + 3) // 4
                self.assertTrue(allowed["allowed"])
                self.assertEqual(allowed["additional_gpu_bytes"], additional_gpu)
                self.assertEqual(allowed["current_gpu_used_bytes"], current_gpu_used)
                self.assertEqual(allowed["projected_gpu_used_bytes"], projected_gpu_used)
                self.assertEqual(allowed["required_gpu_total_bytes"], required_gpu_total)
                self.assertEqual(allowed["gpu_free_bytes"], 50_000)
                self.assertEqual(allowed["gpu_total_bytes"], 60_000)

        insufficient_gpu = runtime.evaluate_resource_guard(
            2, observed, dict(limits, gpu_free_bytes=3_749), 1_000)
        self.assertFalse(insufficient_gpu["allowed"])
        self.assertEqual(insufficient_gpu["reason"], "gpu_headroom_insufficient")
        self.assertEqual(insufficient_gpu["additional_gpu_bytes"], 3_000)
        self.assertEqual(insufficient_gpu["current_gpu_used_bytes"], 12_251)
        self.assertEqual(insufficient_gpu["projected_gpu_used_bytes"], 15_251)
        self.assertEqual(insufficient_gpu["required_gpu_total_bytes"], 19_064)

        near_full_observed = dict(observed, observed_per_worker_gpu_peak_bytes=50)
        near_full_limits = dict(
            limits, gpu_free_bytes=100, gpu_total_bytes=1_000)
        near_full_gpu = runtime.evaluate_resource_guard(
            2, near_full_observed, near_full_limits, 25)
        self.assertFalse(near_full_gpu["allowed"])
        self.assertEqual(near_full_gpu["reason"], "gpu_headroom_insufficient")
        self.assertEqual(near_full_gpu["additional_gpu_bytes"], 75)
        self.assertEqual(near_full_gpu["current_gpu_used_bytes"], 900)
        self.assertEqual(near_full_gpu["projected_gpu_used_bytes"], 975)
        self.assertEqual(near_full_gpu["required_gpu_total_bytes"], 1_219)

        boundary_observed = dict(
            observed, observed_per_worker_gpu_peak_bytes=100)
        boundary_limits = dict(
            limits,
            memory_limit_bytes=100_000,
            pids_limit=1_000,
            gpu_free_bytes=400,
            gpu_total_bytes=1_000,
        )
        exact_boundary = runtime.evaluate_resource_guard(
            2, boundary_observed, boundary_limits, 100)
        self.assertTrue(exact_boundary["allowed"])
        self.assertEqual(exact_boundary["current_gpu_used_bytes"], 600)
        self.assertEqual(exact_boundary["additional_gpu_bytes"], 200)
        self.assertEqual(exact_boundary["projected_gpu_used_bytes"], 800)
        self.assertEqual(exact_boundary["required_gpu_total_bytes"], 1_000)

        one_byte_over = runtime.evaluate_resource_guard(
            2, boundary_observed, boundary_limits, 101)
        self.assertFalse(one_byte_over["allowed"])
        self.assertEqual(one_byte_over["reason"], "gpu_headroom_insufficient")
        self.assertEqual(one_byte_over["current_gpu_used_bytes"], 600)
        self.assertEqual(one_byte_over["additional_gpu_bytes"], 201)
        self.assertEqual(one_byte_over["projected_gpu_used_bytes"], 801)
        self.assertEqual(one_byte_over["required_gpu_total_bytes"], 1_002)

        unknown_gpu_cases = (
            (dict(observed, observed_per_worker_gpu_peak_bytes=None), limits,
             "gpu_per_worker_peak_unknown"),
            (observed, dict(limits, gpu_free_bytes=None), "gpu_free_unknown"),
            (observed, dict(limits, gpu_total_bytes=None), "gpu_total_unknown"),
            (dict(observed, observed_per_worker_gpu_peak_bytes=float("nan")), limits,
             "gpu_per_worker_peak_unknown"),
        )
        for invalid_observed, invalid_limits, reason in unknown_gpu_cases:
            with self.subTest(reason=reason):
                denied = runtime.evaluate_resource_guard(
                    2, invalid_observed, invalid_limits, 1_000)
                self.assertFalse(denied["allowed"])
                self.assertEqual(denied["reason"], reason)

        negative_gpu_cases = (
            (dict(observed, observed_per_worker_gpu_peak_bytes=-1), limits),
            (observed, dict(limits, gpu_free_bytes=-1)),
            (observed, dict(limits, gpu_total_bytes=-1)),
        )
        for invalid_observed, invalid_limits in negative_gpu_cases:
            with self.subTest(observed=invalid_observed, limits=invalid_limits):
                denied = runtime.evaluate_resource_guard(
                    2, invalid_observed, invalid_limits, 1_000)
                self.assertFalse(denied["allowed"])
                self.assertEqual(denied["reason"], "invalid_observation")

        inconsistent_gpu_limits = (
            dict(limits, gpu_free_bytes=16_001),
            dict(limits, gpu_total_bytes=0),
        )
        for invalid_limits in inconsistent_gpu_limits:
            with self.subTest(limits=invalid_limits):
                denied = runtime.evaluate_resource_guard(
                    2, observed, invalid_limits, 1_000)
                self.assertFalse(denied["allowed"])
                self.assertEqual(denied["reason"], "gpu_limits_inconsistent")

    def test_unbounded_pid_guard_requires_native_proof_and_explicit_budget(self):
        observed = {
            "current_workers": 1,
            "per_worker_peak_bytes": 2_000,
            "per_worker_pids": 20,
            "observed_per_worker_gpu_peak_bytes": 2_000,
        }
        limits = {
            "memory_current_bytes": 10_000,
            "memory_limit_bytes": 20_000,
            "pids_current": 100,
            "pids_limit": None,
            "gpu_free_bytes": 8_000,
            "gpu_total_bytes": 16_000,
        }
        proven = dict(
            limits,
            pids_limit_state="unbounded",
            pids_limit_reason="limit_unavailable",
            experiment_pids_budget=150,
        )
        invalid_proofs = (
            (dict(limits, experiment_pids_budget=150), "no proof"),
            (dict(proven, pids_limit_state="bounded"), "wrong state"),
            (dict(proven, pids_limit_state=None), "invalid state"),
            (dict(proven, pids_limit_reason="cgroup_file_missing"), "missing limit"),
            (dict(proven, pids_limit_reason="cgroup_value_invalid"), "invalid limit"),
            (dict(proven, pids_limit_reason="other"), "wrong limit reason"),
            (dict(proven, pids_limit_reason=None), "missing reason"),
            ({key: value for key, value in proven.items()
              if key != "pids_limit_reason"}, "omitted reason"),
            ({key: value for key, value in proven.items()
              if key != "pids_limit_state"}, "omitted state"),
            ({key: value for key, value in proven.items()
              if key != "experiment_pids_budget"}, "no budget"),
            ({key: value for key, value in proven.items()
              if key != "pids_limit"}, "missing actual value"),
        )
        for invalid_limits, label in invalid_proofs:
            with self.subTest(proof=label):
                denied = runtime.evaluate_resource_guard(
                    2, observed, invalid_limits, 1_000)
                self.assertFalse(denied["allowed"])
                self.assertEqual(denied["reason"], "pids_limit_unknown")
                self.assertIsNone(denied["effective_pid_guard_limit"])
                self.assertIsNone(denied["pids_guard_source"])

    def test_experiment_pid_budget_is_strict_and_capped_at_512(self):
        observed = {
            "current_workers": 1,
            "per_worker_peak_bytes": 2_000,
            "per_worker_pids": 20,
            "observed_per_worker_gpu_peak_bytes": 2_000,
        }
        limits = {
            "memory_current_bytes": 10_000,
            "memory_limit_bytes": 20_000,
            "pids_current": 100,
            "pids_limit": None,
            "pids_limit_state": "unbounded",
            "pids_limit_reason": "limit_unavailable",
            "gpu_free_bytes": 8_000,
            "gpu_total_bytes": 16_000,
        }
        for budget in (True, False, 0, -1, 513, None, 1.0, "512"):
            with self.subTest(budget=budget):
                denied = runtime.evaluate_resource_guard(
                    2, observed, dict(limits, experiment_pids_budget=budget), 1_000)
                self.assertFalse(denied["allowed"])
                self.assertEqual(denied["reason"], "experiment_pids_budget_invalid")
                self.assertIsNone(denied["effective_pid_guard_limit"])
                self.assertIsNone(denied["experiment_pids_budget"])
                self.assertIsNone(denied["pids_guard_source"])

    def test_experiment_pid_budget_boundaries_preserve_actual_limit_and_source(self):
        observed = {
            "current_workers": 1,
            "per_worker_peak_bytes": 2_000,
            "per_worker_pids": 20,
            "observed_per_worker_gpu_peak_bytes": 2_000,
        }
        limits = {
            "memory_current_bytes": 10_000,
            "memory_limit_bytes": 20_000,
            "pids_current": 100,
            "pids_limit": None,
            "pids_limit_state": "unbounded",
            "pids_limit_reason": "limit_unavailable",
            "gpu_free_bytes": 8_000,
            "gpu_total_bytes": 16_000,
        }
        boundary = runtime.evaluate_resource_guard(
            2, observed, dict(limits, experiment_pids_budget=150), 1_000)
        self.assertTrue(boundary["allowed"])
        self.assertEqual(boundary["reason"], "experiment_pid_guard_verified")
        self.assertEqual(boundary["pids_limit"], None)
        self.assertEqual(boundary["effective_pid_guard_limit"], 150)
        self.assertEqual(boundary["experiment_pids_budget"], 150)
        self.assertEqual(boundary["pids_guard_source"], "experiment_pids_budget")
        self.assertEqual(boundary["projected_pids"], 120)
        self.assertEqual(boundary["required_pids"], 150)

        one_below = runtime.evaluate_resource_guard(
            2, observed, dict(limits, experiment_pids_budget=149), 1_000)
        self.assertFalse(one_below["allowed"])
        self.assertEqual(one_below["reason"], "pid_headroom_insufficient")
        self.assertEqual(one_below["pids_limit"], None)
        self.assertEqual(one_below["effective_pid_guard_limit"], 149)

        exhausted = runtime.evaluate_resource_guard(
            2, observed, dict(limits, pids_current=120,
                             experiment_pids_budget=150), 1_000)
        self.assertFalse(exhausted["allowed"])
        self.assertEqual(exhausted["reason"], "pid_headroom_insufficient")
        self.assertEqual(exhausted["projected_pids"], 140)
        self.assertEqual(exhausted["required_pids"], 175)

        finite_cases = (
            (200, 150, 150, "experiment_pids_budget", True,
             "experiment_pid_guard_verified"),
            (120, 150, 120, "actual_pids_limit", False,
             "pid_headroom_insufficient"),
            (200, 512, 200, "actual_pids_limit", True, "headroom_verified"),
        )
        for actual, budget, effective, source, allowed, reason in finite_cases:
            with self.subTest(actual=actual, budget=budget):
                result = runtime.evaluate_resource_guard(
                    2, observed,
                    dict(limits, pids_limit=actual,
                         experiment_pids_budget=budget),
                    1_000)
                self.assertEqual(result["allowed"], allowed)
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["pids_limit"], actual)
                self.assertEqual(result["effective_pid_guard_limit"], effective)
                self.assertEqual(result["experiment_pids_budget"], budget)
                self.assertEqual(result["pids_guard_source"], source)

        negative_actual = runtime.evaluate_resource_guard(
            2, observed, dict(limits, pids_limit=-1), 1_000)
        self.assertFalse(negative_actual["allowed"])
        self.assertEqual(negative_actual["reason"], "invalid_observation")
        self.assertEqual(negative_actual["effective_pid_guard_limit"], -1)

        zero_actual = runtime.evaluate_resource_guard(
            2, observed, dict(limits, pids_limit=0), 1_000)
        self.assertFalse(zero_actual["allowed"])
        self.assertEqual(zero_actual["reason"], "resource_limit_unknown")
        self.assertEqual(zero_actual["effective_pid_guard_limit"], 0)


if __name__ == "__main__":

    unittest.main()
