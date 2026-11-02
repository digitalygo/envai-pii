import base64
import hashlib
import json
import lzma
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools.verda_model_experiment import batch_package, batch_runtime, package, runtime

DEFAULT_ARCHIVE_SHA256 = (
    "419c191c8afab6a444fa7642db81695d56a5660794b301deb84cbc6b01ad161b"
)
DEFAULT_GPU_ARCHIVE_SHA256 = (
    "9442ec409db31645a23b9400ed4314348d72894449e6f4d0d9afd1bf6b6e0cb5"
)
DEFAULT_PAYLOAD_SHA256 = (
    "6758fa7d0950e88733e67fa590d2bb8c15c411d54a3f8542feae735823405007"
)
DEFAULT_GPU_PAYLOAD_SHA256 = (
    "9eede487ceabcc2ecebc3a986b5bbe4329bf58ea793115696ba4f798e5e64da2"
)
DEFAULT_PROFILE_SHA256 = (
    "e668227f49a553a5d5e74d1e6ed3f3aadc2e2efb2bf58c4f691d5d256013a86e"
)
DEFAULT_GPU_PROFILE_SHA256 = (
    "c217f373ce0510bb4ea0e213db02da7bf4d58a1d8cf49da81236787225786dbf"
)
BASE_ENVIRONMENT_COUNT = 0


def parse_bundle(archive):
    blob = lzma.decompress(archive)
    if not blob.startswith(batch_package.BATCH_BUNDLE_MAGIC):
        raise AssertionError("bundle magic")
    position = len(batch_package.BATCH_BUNDLE_MAGIC)
    files = {}
    for name in batch_package.BATCH_ARCHIVE_FILES:
        size = int.from_bytes(blob[position:position + 2], "big")
        position += 2
        observed = blob[position:position + size].decode("ascii")
        position += size
        if observed != name:
            raise AssertionError("bundle order")
        length = int.from_bytes(blob[position:position + 4], "big")
        position += 4
        files[name] = blob[position:position + length]
        position += length
    if position != len(blob):
        raise AssertionError("bundle trailing data")
    return files


def build_bundle(files, names=None):
    blob = bytearray(batch_package.BATCH_BUNDLE_MAGIC)
    ordered_names = (
        batch_package.BATCH_ARCHIVE_FILES if names is None else names)
    for name in ordered_names:
        if name not in files:
            continue
        name_bytes = name.encode("ascii")
        data = files[name]
        blob += struct.pack(">H", len(name_bytes))
        blob += name_bytes
        blob += struct.pack(">I", len(data))
        blob += data
    return bytes(blob)


def compression_independent_profile_pins(profile):
    command = (profile["deployment_patch"]["containers"][0]
               ["entrypoint_overrides"]["cmd"])
    payload_sha256 = hashlib.sha256(
        package.reconstruct_signed_payload(command).encode()).hexdigest()
    normalized_profile = json.loads(json.dumps(profile))
    normalized_profile["deployment_patch"]["containers"][0][
        "entrypoint_overrides"]["cmd"] = ["<verified-uncompressed-payload>"]
    raw_sha256 = hashlib.sha256(json.dumps(
        profile, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    normalized_sha256 = hashlib.sha256(json.dumps(
        normalized_profile, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    return payload_sha256, normalized_sha256, raw_sha256


def execute_profile(command, root, environment, *, gunicorn_path):
    carrier_names = tuple(
        name for name in environment
        if name.startswith(batch_package.BATCH_ARCHIVE_ENV_PREFIX))
    payload = package.reconstruct_signed_payload(command).replace(
        f"root={package.RUNTIME_DESTINATION!r}",
        f"root={str(root)!r}",
    ).replace(repr(package.GUNICORN_PATH), repr(str(gunicorn_path)))
    signed = package.build_signed_command(payload)
    captured = []
    with mock.patch.object(sys, "argv", ["-c", *signed[1:]]), \
            mock.patch.dict(os.environ, environment, clear=False), \
            mock.patch("os.execv", side_effect=lambda path, argv: captured.append(
                (path, argv))):
        exec(compile(signed[0], "<signed-batch-profile>", "exec"), {})
        observed = {
            "remaining_carriers": tuple(
                name for name in carrier_names if name in os.environ),
            "workers": os.environ.get(runtime.PROFILE_WORKERS_ENV),
            "run_id": os.environ.get(runtime.PROFILE_RUN_ID_ENV),
            "pythonpath": os.environ.get("PYTHONPATH"),
            "batch_size": os.environ.get(batch_runtime.BATCH_SIZE_ENV),
            "tokenizers_parallelism": os.environ.get(
                "TOKENIZERS_PARALLELISM"),
            "auth_mode": os.environ.get("PII_AUTH_MODE"),
            "runtime_environment": {
                name: os.environ.get(name)
                for name, _value in package.ENVIRONMENT
            },
        }
    return captured, observed


class BatchArchiveTests(unittest.TestCase):
    def test_overlay_assets_are_exact_bounded_and_manifest_bound(self):
        archive, hashes, manifest, manifest_bytes = (
            batch_package.build_batch_archive())
        self.assertEqual(set(hashes), set(batch_package.BATCH_ARCHIVE_FILES))
        self.assertLessEqual(len(archive), package.ARCHIVE_LIMIT_BYTES)
        self.assertLessEqual(
            len(lzma.decompress(archive)),
            batch_package.BATCH_EXTRACTED_LIMIT_BYTES)
        files = parse_bundle(archive)
        helper = batch_package.BATCH_HELPER_SOURCE.read_bytes()
        self.assertEqual(files[batch_package.BATCH_HELPER_ASSET], helper)
        self.assertEqual(
            manifest["helper_sha256"], hashlib.sha256(helper).hexdigest())
        self.assertEqual(
            hashlib.sha256(manifest_bytes).hexdigest(),
            hashes[batch_package.BATCH_MANIFEST_ASSET])
        self.assertEqual(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode(),
            manifest_bytes)
        self.assertEqual(manifest["base_app_sha256"],
                         runtime.SOURCE_HASHES["app.py"])
        self.assertEqual(
            manifest["base_app_sha256"],
            "b0ec5163cd0d9eee05922d4b80718eb26abc762b0612935e1f1ad8275dc3848e")
        self.assertNotEqual(manifest["base_app_sha256"],
                            manifest["helper_sha256"])
        self.assertNotEqual(manifest["base_app_sha256"],
                            manifest["detector_source_sha256"])
        self.assertNotEqual(manifest["base_app_sha256"],
                            manifest["detector_code_sha256"])
        detector = files[batch_package.BATCH_DETECTOR_ASSET]
        self.assertEqual(manifest["detector_source_sha256"],
                         hashlib.sha256(detector).hexdigest())
        compiled = batch_runtime.compile_detector(
            detector,
            source_sha256=manifest["detector_source_sha256"],
            code_sha256=manifest["detector_code_sha256"])
        self.assertEqual(compiled.__name__, "_guardrail_detect")
        app_source = batch_package.BATCH_APP_SOURCE.read_bytes()
        self.assertNotIn(app_source, lzma.decompress(archive))
        self.assertNotIn(b"APP_VERSION", lzma.decompress(archive))
        self.assertNotIn(b"urlopen", lzma.decompress(archive))
        self.assertNotIn("src/app/app.py", manifest_bytes.decode("ascii"))

    def test_source_and_detector_extraction_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.py"
            source.write_bytes(b"source")
            link = root / "link.py"
            link.symlink_to(source)
            with self.assertRaisesRegex(
                    ValueError, "not a regular file"):
                batch_package._read_source(link)
            with self.assertRaisesRegex(
                    ValueError, "not a regular file"):
                batch_package._read_source(root)
        for app_source in (
                b"\xff",
                b"pass\n",
                b"@staticmethod\n"
                b"def _guardrail_detect(text, check_deadline, categories=None):\n"
                b"    return []\n",
                b"def _guardrail_detect(text, check_deadline, categories=None):\n"
                b"    return []\n"
                b"def _guardrail_detect(text, check_deadline, categories=None):\n"
                b"    return []\n"):
            with self.subTest(app_source=app_source[:20]), self.assertRaises(
                    ValueError):
                batch_package._extract_detector(app_source)
        with mock.patch.object(batch_package, "FIXTURE_TEXT", "mismatch"):
            with self.assertRaisesRegex(ValueError, "fixture text mismatch"):
                batch_package._fixture_source()

    def test_old_archives_and_profiles_stay_byte_identical(self):
        default_archive, _ = package.build_archive()
        gpu_archive, _ = package.build_gpu_archive()
        self.assertEqual(hashlib.sha256(default_archive).hexdigest(),
                         DEFAULT_ARCHIVE_SHA256)
        self.assertEqual(hashlib.sha256(gpu_archive).hexdigest(),
                         DEFAULT_GPU_ARCHIVE_SHA256)
        default_profile = package.build_profile(8, "baseline")
        gpu_profile = package.build_gpu_profile("verda-20261028-gpu8")
        self.assertEqual(package.build_profile(8, "baseline"), default_profile)
        self.assertEqual(
            package.build_gpu_profile("verda-20261028-gpu8"), gpu_profile)
        for profile, expected_payload_sha, expected_profile_sha in (
                (default_profile, DEFAULT_PAYLOAD_SHA256,
                 DEFAULT_PROFILE_SHA256),
                (gpu_profile, DEFAULT_GPU_PAYLOAD_SHA256,
                 DEFAULT_GPU_PROFILE_SHA256)):
            with self.subTest(profile=expected_profile_sha):
                payload_sha256, normalized_sha256, raw_sha256 = (
                    compression_independent_profile_pins(profile))
                self.assertEqual(payload_sha256, expected_payload_sha)
                self.assertEqual(normalized_sha256, expected_profile_sha)
                self.assertNotEqual(normalized_sha256, raw_sha256)

    def test_batch_archive_is_deterministic_and_fails_closed_on_limits(self):
        first = batch_package.build_batch_archive()
        second = batch_package.build_batch_archive()
        self.assertEqual(first, second)
        with mock.patch.object(batch_package, "BATCH_EXTRACTED_LIMIT_BYTES", 10):
            with self.assertRaisesRegex(
                    ValueError, "exceeds extracted size limit"):
                batch_package.build_batch_archive()
        with mock.patch.object(package, "ARCHIVE_LIMIT_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "exceeds size limit"):
                batch_package.build_batch_archive()

    def test_carrier_and_command_limits_are_not_widened(self):
        archive, _, _, _ = batch_package.build_batch_archive()
        encoded = batch_package._encoded_archive(archive)
        split = len(encoded) - 47 * batch_package.BATCH_CARRIER_CHUNK_BYTES
        inline, names, values = batch_package._carrier_parts(encoded, split)
        self.assertTrue(inline)
        self.assertEqual(len(names), 47)
        self.assertEqual(max(len(value) for value in values), 253)
        with mock.patch.object(batch_package, "BATCH_CARRIER_CHUNK_BYTES", 254):
            with self.assertRaisesRegex(
                    ValueError, "carrier exceeds provider limit"):
                batch_package._carrier_parts(encoded, split)
        for invalid in (0, len(encoded), -1, True, None):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                    ValueError, "invalid batch runtime carrier split"):
                batch_package._carrier_parts(encoded, invalid)
        with mock.patch.object(
                batch_package, "BATCH_MAX_ENVIRONMENT_ENTRIES",
                batch_package.BATCH_ENVIRONMENT_COUNT):
            with self.assertRaisesRegex(
                    ValueError, "transport exceeds provider limits"):
                batch_package._command_plan(
                    archive, b"{}", "transport-limit", 1, 8)

    def test_profiles_cover_all_batches_with_expected_transport(self):
        archive, hashes, manifest, manifest_bytes = (
            batch_package.build_batch_archive())
        encoded = batch_package._encoded_archive(archive)
        for batch_size in (1, 4, 8, 16):
            with self.subTest(batch_size=batch_size):
                profile = batch_package.build_batch_gpu_profile(
                    f"batch-{batch_size}", batch_size)
                self.assertEqual(profile["workers"], 8)
                self.assertEqual(profile["batch_size"], batch_size)
                self.assertEqual(profile["source_hashes"],
                                 runtime.SOURCE_HASHES)
                self.assertEqual(profile["archive_file_hashes"], hashes)
                self.assertEqual(profile["scaling_patch"], {
                    "min_replica_count": 0,
                    "max_replica_count": 1,
                    "concurrent_requests_per_replica": 32,
                })
                container = profile["deployment_patch"]["containers"][0]
                command = container["entrypoint_overrides"]["cmd"]
                environment = container["env"]
                self.assertLessEqual(
                    len(command), package.MAX_COMMAND_ARGUMENTS
                    - batch_package.BATCH_TRANSPORT_HEADROOM)
                self.assertLessEqual(
                    len(environment), batch_package.BATCH_MAX_ENVIRONMENT_ENTRIES
                    - batch_package.BATCH_TRANSPORT_HEADROOM)
                self.assertEqual(
                    max(len(argument.encode("ascii")) for argument in command),
                    253)
                self.assertEqual(
                    max(len(entry["value_or_reference_to_secret"].encode("ascii"))
                        for entry in environment), 253)
                self.assertTrue(all(
                    entry["name"].startswith(
                        batch_package.BATCH_ARCHIVE_ENV_PREFIX)
                    for entry in environment))
                self.assertNotIn(
                    batch_runtime.BATCH_SIZE_ENV,
                    {entry["name"] for entry in environment})
                self.assertNotIn(
                    "TOKENIZERS_PARALLELISM",
                    {entry["name"] for entry in environment})
                carrier = {
                    entry["name"]: entry["value_or_reference_to_secret"]
                    for entry in environment[BASE_ENVIRONMENT_COUNT:]
                }
                inline_chars = profile["overrides"][
                    "batch_archive_inline_chars"]
                inline, names, _ = batch_package._carrier_parts(
                    encoded, inline_chars)
                self.assertEqual(
                    inline + "".join(carrier[name] for name in names),
                    encoded)
                self.assertEqual(
                    base64.b64decode(
                        inline + "".join(carrier[name] for name in names),
                        validate=True),
                    archive)
                overlay = profile["overrides"]["batch_overlay"]
                self.assertEqual(overlay["base_app_sha256"],
                                 runtime.SOURCE_HASHES["app.py"])
                self.assertEqual(overlay["helper_sha256"],
                                 manifest["helper_sha256"])
                self.assertEqual(overlay["detector_source_sha256"],
                                 manifest["detector_source_sha256"])
                self.assertEqual(overlay["detector_code_sha256"],
                                 manifest["detector_code_sha256"])
                self.assertEqual(overlay["manifest_sha256"],
                                 hashlib.sha256(manifest_bytes).hexdigest())
                self.assertEqual(len({overlay["base_app_sha256"],
                                      overlay["helper_sha256"],
                                      overlay["detector_source_sha256"],
                                      overlay["detector_code_sha256"]}), 4)
                self.assertEqual(
                    profile["overrides"]["runtime_archive_sha256"],
                    hashlib.sha256(archive).hexdigest())
                self.assertEqual(
                    profile["overrides"]["runtime_archive_bytes"],
                    len(archive))
                self.assertEqual(
                    profile["overrides"]["batch_archive_format"],
                    batch_package.BATCH_BUNDLE_FORMAT)
                self.assertEqual(
                    profile["overrides"]["batch_python_version"],
                    ".".join(map(str, sys.version_info[:2])))
                self.assertEqual(
                    profile["overrides"]["batch_environment_moved"],
                    list(batch_package.BATCH_BOOTSTRAP_ENV))
                self.assertEqual(
                    profile, batch_package.build_batch_gpu_profile(
                        f"batch-{batch_size}", batch_size))

    def test_worker_choices_share_exact_56_carriers_and_only_command_changes(self):
        archive, hashes, _manifest, _manifest_bytes = (
            batch_package.build_batch_archive())
        base = batch_package.build_batch_gpu_profile("copies-batch8", 8)
        base_container = base["deployment_patch"]["containers"][0]
        base_environment = base_container["env"]
        expected_names = [
            f"{batch_package.BATCH_ARCHIVE_ENV_PREFIX}{index:02d}"
            for index in range(batch_package.BATCH_CARRIER_COUNT)
        ]
        self.assertEqual(batch_package.BATCH_CARRIER_COUNT, 56)
        self.assertEqual(len(base_environment), 56)
        self.assertEqual([entry["name"] for entry in base_environment],
                         expected_names)
        self.assertEqual(base["archive_file_hashes"], hashes)
        for workers in (12, 16):
            with self.subTest(workers=workers):
                profile = batch_package.build_batch_gpu_profile(
                    "copies-batch8", 8, workers=workers)
                container = profile["deployment_patch"]["containers"][0]
                command = container["entrypoint_overrides"]["cmd"]
                self.assertEqual(profile["workers"], workers)
                self.assertEqual(profile["overrides"]["workers"], workers)
                self.assertEqual(profile["archive_file_hashes"], hashes)
                self.assertEqual(container["env"], base_environment)
                self.assertEqual(
                    profile["overrides"]["batch_archive_env_chunks"], 56)
                self.assertLessEqual(
                    len(command), package.MAX_COMMAND_ARGUMENTS
                    - batch_package.BATCH_TRANSPORT_HEADROOM)
                self.assertLessEqual(
                    len(container["env"]),
                    batch_package.BATCH_MAX_ENVIRONMENT_ENTRIES
                    - batch_package.BATCH_TRANSPORT_HEADROOM)
                payload = package.reconstruct_signed_payload(command)
                gunicorn = batch_package._gunicorn_arguments(workers)
                self.assertTrue(payload.startswith(
                    f"import sys;sys.argv={['-c', *gunicorn]!r}\n"))
                self.assertIn(
                    f"os.environ['ENVAIPI_VERDA_WORKERS']={str(workers)!r}",
                    payload)
        for workers in (1, 2, 4, 9, 13, 15, 17, True, 8.0, "8", None):
            with self.subTest(rejected=workers), self.assertRaises(ValueError):
                batch_package.build_batch_gpu_profile(
                    "copies-batch8", 8, workers=workers)
        with mock.patch.object(batch_package, "BATCH_CARRIER_COUNT", 55):
            with self.assertRaisesRegex(
                    ValueError, "transport exceeds provider limits"):
                batch_package._command_plan(
                    archive, _manifest_bytes, "carrier-bound", 8, 8)
        with mock.patch.object(batch_package, "BATCH_CARRIER_COUNT", 57):
            with self.assertRaisesRegex(
                    ValueError, "transport exceeds provider limits"):
                batch_package._command_plan(
                    archive, _manifest_bytes, "carrier-bound", 8, 8)

    def test_bootstrap_builder_rejects_invalid_splits_sizes_and_limits(self):
        archive, _, _, manifest_bytes = batch_package.build_batch_archive()
        encoded = batch_package._encoded_archive(archive)
        inline, count, _command = batch_package._command_plan(
            archive, manifest_bytes, "builder-check", 1, 8)
        _, names, _values = batch_package._carrier_parts(encoded, inline)
        with self.assertRaisesRegex(ValueError, "invalid worker count"):
            batch_package._bootstrap_script(
                archive, hashlib.sha256(manifest_bytes).hexdigest(),
                "builder-check", inline, names, 8, 4)
        with self.assertRaisesRegex(ValueError, "invalid batch size"):
            batch_package._bootstrap_script(
                archive, hashlib.sha256(manifest_bytes).hexdigest(),
                "builder-check", inline, names, 2, 8)
        with self.assertRaisesRegex(ValueError, "carrier names mismatch"):
            batch_package._bootstrap_script(
                archive, hashlib.sha256(manifest_bytes).hexdigest(),
                "builder-check", inline, (*names, "extra"), 1, 8)
        with mock.patch.object(
                batch_package, "_command_plan",
                return_value=(1, 1, ["command"])), \
                mock.patch.object(
                    batch_package, "_carrier_parts",
                    return_value=("x", ("name",), ("value",))):
            with self.assertRaisesRegex(
                    ValueError, "carrier count mismatch"):
                batch_package.build_batch_gpu_profile("count-check", 1)
        with mock.patch.object(
                batch_package, "BATCH_MAX_ENVIRONMENT_ENTRIES",
                batch_package.BATCH_ENVIRONMENT_COUNT):
            with self.assertRaisesRegex(
                    ValueError, "carrier exceeds environment limit"):
                batch_package._carrier_parts(encoded, len(encoded) - 1)
        with mock.patch.object(package, "ARCHIVE_LIMIT_BYTES", 1):
            with self.assertRaisesRegex(
                    ValueError, "archive exceeds size limit"):
                batch_package._encoded_archive(archive)
        with mock.patch.object(package, "COMMAND_LIMIT_BYTES", 1):
            with self.assertRaisesRegex(
                    ValueError, "bootstrap exceeds size limit"):
                batch_package._bootstrap_script(
                    archive, hashlib.sha256(manifest_bytes).hexdigest(),
                    "builder-check", inline, names, 1, 8)
        with mock.patch.object(
                batch_package, "_build_command", side_effect=ValueError):
            with self.assertRaisesRegex(
                    ValueError, "transport exceeds provider limits"):
                batch_package._command_plan(
                    archive, manifest_bytes, "builder-check", 1, 8)
        with mock.patch.object(
                batch_package, "_carrier_parts",
                side_effect=ValueError("invalid split")):
            with self.assertRaisesRegex(
                    ValueError, "transport exceeds provider limits"):
                batch_package._command_plan(
                    archive, manifest_bytes, "split-check", 1, 8)
        with mock.patch.object(
                batch_package, "BATCH_ENVIRONMENT_COUNT", 54), \
                mock.patch.object(
                    batch_package, "_carrier_parts",
                    return_value=("x", ("a", "b", "c"), ("1", "2", "3"))):
            with self.assertRaisesRegex(
                    ValueError, "transport exceeds provider limits"):
                batch_package._command_plan(
                    archive, manifest_bytes, "environment-check", 1, 8)
        excessive_names = tuple(f"carrier-{index}" for index in range(57))
        excessive_values = tuple("x" for _ in excessive_names)
        with mock.patch.object(
                batch_package, "_command_plan",
                return_value=(1, 57, ["command"])), \
                mock.patch.object(
                    batch_package, "_carrier_parts",
                    return_value=("x", excessive_names, excessive_values)):
            with self.assertRaisesRegex(
                    ValueError, "environment exceeds provider limit"):
                batch_package.build_batch_gpu_profile("too-many", 1)
        oversized_names = ("x" * 254,)
        with mock.patch.object(
                batch_package, "_command_plan",
                return_value=(1, 1, ["command"])), \
                mock.patch.object(
                    batch_package, "_carrier_parts",
                    return_value=("x", oversized_names, ("value",))):
            with self.assertRaisesRegex(
                    ValueError, "environment value exceeds provider limit"):
                batch_package.build_batch_gpu_profile("oversized-name", 1)

    def test_invalid_run_and_batch_values_fail(self):
        for run_id in ("", "../bad", "bad/run", "x" * 65, None, 4):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                batch_package.build_batch_gpu_profile(run_id, 1)
        for batch_size in (0, 2, 3, 5, 17, True, 1.0, "4", None):
            with self.subTest(batch_size=batch_size), self.assertRaises(ValueError):
                batch_package.build_batch_gpu_profile("batch-run", batch_size)


class FreshImportTests(unittest.TestCase):
    def test_extracted_batch_runtime_imports_without_the_repository(self):
        profile = batch_package.build_batch_gpu_profile("batch-import", 4)
        command = profile["deployment_patch"]["containers"][0][
            "entrypoint_overrides"]["cmd"]
        container = profile["deployment_patch"]["containers"][0]
        environment = {
            "PII_HOST": "127.0.0.1",
            "PII_PORT": "5055",
            **{entry["name"]: entry["value_or_reference_to_secret"]
               for entry in container["env"][BASE_ENVIRONMENT_COUNT:]},
        }
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            runtime_root = temporary_path / "private-runtime"
            working_directory = temporary_path / "unrelated"
            working_directory.mkdir()
            _, observed = execute_profile(
                command, runtime_root, environment,
                gunicorn_path=temporary_path / "gunicorn")
            code = (
                "import hashlib,json,marshal,sys\n"
                "from tools.verda_model_experiment import "
                "batch_runtime,gpu_monitor,gpu_runtime,runtime\n"
                "manifest,_=batch_runtime._load_manifest(batch_runtime.ASSET_ROOT)\n"
                "detector= batch_runtime.compile_detector(\n"
                " (batch_runtime.ASSET_ROOT/'guardrail_detect.py').read_bytes(),\n"
                " source_sha256=manifest['detector_source_sha256'],\n"
                " code_sha256=manifest['detector_code_sha256'])\n"
                "print(json.dumps({\n"
                " 'batch_runtime':batch_runtime.__file__,\n"
                " 'gpu_runtime':gpu_runtime.__file__,\n"
                " 'gpu_monitor':gpu_monitor.__file__,\n"
                " 'runtime':runtime.__file__,\n"
                " 'asset_root':str(batch_runtime.ASSET_ROOT),\n"
                " 'resolved_batch_size':batch_runtime._batch_size_from_env(),\n"
                " 'runtime_settings_ok':runtime._resolved_settings(),\n"
                " 'compiled_code_sha256':hashlib.sha256(\n"
                "  marshal.dumps(detector.__code__)).hexdigest(),\n"
                " 'torch_loaded':'torch' in sys.modules,\n"
                " 'python_version':list(sys.version_info[:2]),\n"
                " 'sys_path':sys.path,\n"
                "}))\n"
            )
            completed = subprocess.run(
                [sys.executable, "-c", code],
                cwd=working_directory,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": str(runtime_root),
                    **observed["runtime_environment"],
                    batch_runtime.BATCH_SIZE_ENV: observed["batch_size"],
                },
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(
                Path(result["batch_runtime"]).resolve(),
                (runtime_root / "tools/verda_model_experiment/"
                 "batch_runtime.py").resolve())
            self.assertEqual(
                Path(result["gpu_runtime"]).resolve(),
                (runtime_root / "tools/verda_model_experiment/"
                 "gpu_runtime.py").resolve())
            self.assertEqual(
                Path(result["gpu_monitor"]).resolve(),
                (runtime_root / "tools/verda_model_experiment/"
                 "gpu_monitor.py").resolve())
            self.assertEqual(
                Path(result["runtime"]).resolve(),
                (runtime_root / "tools/verda_model_experiment/"
                 "runtime.py").resolve())
            self.assertEqual(
                Path(result["asset_root"]).resolve(),
                (runtime_root / "tools/verda_model_experiment/"
                 "batch_overlay").resolve())
            self.assertEqual(result["resolved_batch_size"], 4)
            self.assertIs(result["runtime_settings_ok"], True)
            self.assertEqual(result["python_version"],
                             list(sys.version_info[:2]))
            self.assertEqual(result["compiled_code_sha256"],
                             json.loads(
                                 (runtime_root / batch_package.BATCH_MANIFEST_ASSET)
                                 .read_bytes())["detector_code_sha256"])
            self.assertIs(result["torch_loaded"], False)
            self.assertEqual(observed["batch_size"], "4")
            self.assertEqual(observed["tokenizers_parallelism"], "false")
            self.assertEqual(observed["auth_mode"], "upstream")
            self.assertEqual(observed["remaining_carriers"], ())
            self.assertIn(str(runtime_root), result["sys_path"])
            self.assertNotIn(
                str(Path(__file__).resolve().parents[1]), result["sys_path"])


class BatchBootstrapTests(unittest.TestCase):
    def _profile(self):
        return batch_package.build_batch_gpu_profile("batch-bootstrap", 4)

    def _environment(self, profile):
        container = profile["deployment_patch"]["containers"][0]
        carrier = {
            entry["name"]: entry["value_or_reference_to_secret"]
            for entry in container["env"][BASE_ENVIRONMENT_COUNT:]
        }
        return {
            "PII_HOST": "127.0.0.1",
            "PII_PORT": "5055",
            **carrier,
        }

    def test_bootstrap_extracts_private_runtime_and_execs(self):
        profile = self._profile()
        container = profile["deployment_patch"]["containers"][0]
        command = container["entrypoint_overrides"]["cmd"]
        environment = self._environment(profile)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private-runtime"
            fake_gunicorn = Path(temporary) / "gunicorn"
            captured, observed = execute_profile(
                command, root, environment, gunicorn_path=fake_gunicorn)
            self.assertEqual(len(captured), 1)
            executable, argv = captured[0]
            self.assertEqual(executable, str(fake_gunicorn))
            self.assertEqual(argv, [
                str(fake_gunicorn),
                "--config", package.PRIVATE_CONFIG_PATH,
                "--chdir", package.APP_PATH,
                "--bind", "127.0.0.1:5055",
                "--worker-class", "gthread",
                "--workers", "8",
                "--timeout", "600",
                "--graceful-timeout", "30",
                "--access-logfile", "/dev/null",
                "--error-logfile", "-",
                "cloud_service:create_app()",
            ])
            self.assertEqual(observed["workers"], "8")
            self.assertEqual(observed["run_id"], "batch-bootstrap")
            self.assertEqual(observed["pythonpath"], str(root))
            self.assertEqual(observed["batch_size"], "4")
            self.assertEqual(observed["tokenizers_parallelism"], "false")
            self.assertEqual(observed["auth_mode"], "upstream")
            self.assertEqual(observed["runtime_environment"],
                             dict(package.ENVIRONMENT))
            self.assertEqual(observed["remaining_carriers"], ())
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            for name in batch_package.BATCH_ARCHIVE_FILES:
                target = root.joinpath(*name.split("/"))
                self.assertTrue(target.is_file())
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
                self.assertEqual(
                    hashlib.sha256(target.read_bytes()).hexdigest(),
                    profile["archive_file_hashes"][name])
            self.assertFalse((root / "src/app/app.py").exists())
            config = (root / "gunicorn_config.py").read_bytes()
            self.assertIn(b"batch_runtime import load_gunicorn_config", config)
            compile(config, "gunicorn_config.py", "exec")
            manifest = json.loads(
                (root / batch_package.BATCH_MANIFEST_ASSET).read_bytes())
            self.assertEqual(manifest["base_app_sha256"],
                             runtime.SOURCE_HASHES["app.py"])

    def test_all_profiles_consume_carriers_and_set_worker_batch_size(self):
        for batch_size in (1, 4, 8, 16):
            with self.subTest(batch_size=batch_size), \
                    tempfile.TemporaryDirectory() as temporary:
                profile = batch_package.build_batch_gpu_profile(
                    f"worker-batch-{batch_size}", batch_size)
                command = profile["deployment_patch"]["containers"][0][
                    "entrypoint_overrides"]["cmd"]
                root = Path(temporary) / "private-runtime"
                captured, observed = execute_profile(
                    command, root, self._environment(profile),
                    gunicorn_path=Path(temporary) / "gunicorn")
                self.assertEqual(len(captured), 1)
                self.assertEqual(observed["remaining_carriers"], ())
                self.assertEqual(observed["batch_size"], str(batch_size))
                self.assertEqual(observed["tokenizers_parallelism"], "false")
                self.assertEqual(observed["auth_mode"], "upstream")
                self.assertEqual(observed["runtime_environment"],
                                 dict(package.ENVIRONMENT))
                completed = subprocess.run(
                    [sys.executable, "-c",
                     "from tools.verda_model_experiment import "
                     "batch_runtime; print(batch_runtime._batch_size_from_env())"],
                    cwd=Path(temporary),
                    env={
                        "PATH": os.environ.get("PATH", ""),
                        "PYTHONPATH": str(root),
                        **observed["runtime_environment"],
                        batch_runtime.BATCH_SIZE_ENV: observed["batch_size"],
                    },
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout.strip(), str(batch_size))

    def test_worker_choices_bootstrap_and_exec_real_gunicorn_workers(self):
        for workers in (8, 12, 16):
            with self.subTest(workers=workers), \
                    tempfile.TemporaryDirectory() as temporary:
                profile = batch_package.build_batch_gpu_profile(
                    f"worker-copies-{workers}", 8, workers=workers)
                container = profile["deployment_patch"]["containers"][0]
                command = container["entrypoint_overrides"]["cmd"]
                root = Path(temporary) / "private-runtime"
                captured, observed = execute_profile(
                    command, root, self._environment(profile),
                    gunicorn_path=Path(temporary) / "gunicorn")
                self.assertEqual(len(captured), 1)
                argv = captured[0][1]
                self.assertEqual(argv[argv.index("--workers") + 1],
                                 str(workers))
                self.assertEqual(observed["workers"], str(workers))
                self.assertEqual(observed["batch_size"], "8")
                self.assertEqual(observed["tokenizers_parallelism"], "false")
                self.assertEqual(observed["auth_mode"], "upstream")
                self.assertEqual(observed["remaining_carriers"], ())
                config = (root / "gunicorn_config.py").read_bytes()
                self.assertIn(
                    b"batch_runtime import load_gunicorn_config", config)
                compile(config, "gunicorn_config.py", "exec")

    def test_tampered_missing_ordered_and_oversized_carriers_fail_closed(self):
        profile = self._profile()
        environment = self._environment(profile)
        command = profile["deployment_patch"]["containers"][0][
            "entrypoint_overrides"]["cmd"]
        carrier = {
            name: value for name, value in environment.items()
            if name.startswith(batch_package.BATCH_ARCHIVE_ENV_PREFIX)
        }
        names = list(carrier)
        tampered = dict(carrier)
        value = tampered[names[0]]
        tampered[names[0]] = value[:-1] + (
            "A" if value[-1] != "A" else "B")
        ordered = dict(carrier)
        ordered[names[0]], ordered[names[1]] = (
            ordered[names[1]], ordered[names[0]])
        missing = dict(carrier)
        missing.pop(names[3])
        invalid_base64 = dict(carrier)
        invalid_base64[names[0]] = "!"
        oversized = dict(carrier)
        oversized[names[-1]] = oversized[names[-1]] + "A" * (
            254 - len(oversized[names[-1]]))
        extra = dict(carrier)
        extra[batch_package.BATCH_ARCHIVE_ENV_PREFIX + "99"] = "x"
        invalids = (
            ("tampered", tampered),
            ("order", ordered),
            ("missing", missing),
            ("invalid-base64", invalid_base64),
            ("oversized-254", oversized),
            ("extra", extra),
        )
        for name, chunks in invalids:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "private-runtime"
                with self.assertRaises(SystemExit) as failure:
                    execute_profile(
                        command, root,
                        {"PII_HOST": "127.0.0.1", "PII_PORT": "5055", **chunks},
                        gunicorn_path=Path(temporary) / "gunicorn")
                self.assertEqual(failure.exception.code, 70)
                self.assertFalse(root.exists())

    def test_changed_hash_and_bundle_structure_fail_before_writes(self):
        archive, hashes, manifest, manifest_bytes = (
            batch_package.build_batch_archive())
        encoded = batch_package._encoded_archive(archive)
        changed = bytearray(archive)
        changed[0] ^= 1
        inline, _count, changed_command = batch_package._command_plan(
            bytes(changed), manifest_bytes, "changed", 1, 8)
        carrier = dict(zip(
            batch_package._carrier_parts(encoded, inline)[1],
            batch_package._carrier_parts(encoded, inline)[2]))
        files = parse_bundle(archive)
        files[batch_package.BATCH_MANIFEST_ASSET] = b"{}"
        changed_manifest_archive = lzma.compress(build_bundle(files), preset=6)
        missing_files = dict(files)
        missing_files.pop(batch_package.BATCH_DETECTOR_ASSET)
        missing_archive = lzma.compress(
            build_bundle(missing_files), preset=6)
        malformed = bytes([0]) * len(archive)
        ordered_archive = lzma.compress(build_bundle(
            parse_bundle(archive), tuple(reversed(
                batch_package.BATCH_ARCHIVE_FILES))), preset=6)
        extra_name = b"unexpected.asset"
        extra_bundle = build_bundle(parse_bundle(archive)) + (
            struct.pack(">H", len(extra_name)) + extra_name
            + struct.pack(">I", 1) + b"x")
        extra_archive = lzma.compress(extra_bundle, preset=6)
        cases = (
            ("changed-archive", changed_command, carrier),
            ("changed-manifest", changed_manifest_archive, None),
            ("missing-asset", missing_archive, None),
            ("misordered-assets", ordered_archive, None),
            ("extra-asset", extra_archive, None),
            ("malformed-archive", malformed, None),
        )
        for name, candidate, values in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "private-runtime"
                if values is None:
                    encoded = batch_package._encoded_archive(candidate)
                    selected_manifest = (
                        b"{}" if name == "changed-manifest" else manifest_bytes)
                    candidate_inline, _count, command = (
                        batch_package._command_plan(
                            candidate, selected_manifest, name, 1, 8))
                    _, names, chunks = batch_package._carrier_parts(
                        encoded, candidate_inline)
                    values = dict(zip(names, chunks))
                else:
                    command = candidate
                with self.assertRaises(SystemExit) as failure:
                    execute_profile(
                        command, root,
                        {"PII_HOST": "127.0.0.1", "PII_PORT": "5055", **values},
                        gunicorn_path=Path(temporary) / "gunicorn")
                self.assertEqual(failure.exception.code, 70)
                self.assertFalse(root.exists())

    def test_malformed_manifest_and_changed_assets_fail_before_exec(self):
        archive, _, manifest, _ = batch_package.build_batch_archive()
        files = parse_bundle(archive)
        duplicate_manifest = json.dumps(
            manifest, sort_keys=True, separators=(",", ":")).replace(
                '"format":"envai-pii-batch-overlay-1"',
                '"format":"envai-pii-batch-overlay-1",'
                '"format":"envai-pii-batch-overlay-1"', 1).encode("ascii")
        cases = []
        duplicate_files = dict(files)
        duplicate_files[batch_package.BATCH_MANIFEST_ASSET] = duplicate_manifest
        cases.append(("duplicate-manifest-key", duplicate_files, duplicate_manifest))
        invalid_code_manifest = dict(manifest)
        invalid_code_manifest["detector_code_sha256"] = "0" * 64
        invalid_code_bytes = json.dumps(
            invalid_code_manifest, sort_keys=True,
            separators=(",", ":")).encode("ascii")
        invalid_code_files = dict(files)
        invalid_code_files[batch_package.BATCH_MANIFEST_ASSET] = invalid_code_bytes
        cases.append(("changed-code-hash", invalid_code_files, invalid_code_bytes))
        changed_helper = dict(files)
        changed_helper[batch_package.BATCH_HELPER_ASSET] += b"\n"
        cases.append(("changed-helper", changed_helper,
                      files[batch_package.BATCH_MANIFEST_ASSET]))
        changed_detector = dict(files)
        changed_detector[batch_package.BATCH_DETECTOR_ASSET] += b"\n"
        cases.append(("changed-detector", changed_detector,
                      files[batch_package.BATCH_MANIFEST_ASSET]))
        for name, selected_files, manifest_bytes in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temporary:
                candidate = lzma.compress(
                    build_bundle(selected_files), format=lzma.FORMAT_XZ)
                encoded = batch_package._encoded_archive(candidate)
                inline, _count, command = batch_package._command_plan(
                    candidate, manifest_bytes, name, 1, 8)
                _, carrier_names, carrier_values = batch_package._carrier_parts(
                    encoded, inline)
                environment = dict(zip(carrier_names, carrier_values))
                root = Path(temporary) / "private-runtime"
                with self.assertRaises(SystemExit) as failure:
                    execute_profile(
                        command, root,
                        {"PII_HOST": "127.0.0.1", **environment},
                        gunicorn_path=Path(temporary) / "gunicorn")
                self.assertEqual(failure.exception.code, 70)
                self.assertFalse(root.exists())

    def test_extracted_overflow_and_unsafe_root_fail_closed(self):
        archive, _, _, manifest_bytes = batch_package.build_batch_archive()
        files = parse_bundle(archive)
        files[batch_package.BATCH_DETECTOR_ASSET] = b"a" * (129 * 1024)
        oversized_archive = lzma.compress(build_bundle(files), preset=6)
        encoded = batch_package._encoded_archive(oversized_archive)
        inline, _count, command = batch_package._command_plan(
            oversized_archive, manifest_bytes, "overflow", 1, 8)
        carrier = dict(zip(
            batch_package._carrier_parts(encoded, inline)[1],
            batch_package._carrier_parts(encoded, inline)[2]))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private-runtime"
            with self.assertRaises(SystemExit) as failure:
                execute_profile(
                    command, root,
                    {"PII_HOST": "127.0.0.1", "PII_PORT": "5055", **carrier},
                    gunicorn_path=Path(temporary) / "gunicorn")
            self.assertEqual(failure.exception.code, 70)
            self.assertFalse(root.exists())
        profile = self._profile()
        command = profile["deployment_patch"]["containers"][0][
            "entrypoint_overrides"]["cmd"]
        environment = self._environment(profile)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private-runtime"
            root.mkdir(mode=0o755)
            root.chmod(0o755)
            with self.assertRaises(SystemExit) as failure:
                execute_profile(
                    command, root, environment,
                    gunicorn_path=Path(temporary) / "gunicorn")
            self.assertEqual(failure.exception.code, 71)
            self.assertEqual(root.stat().st_mode & 0o777, 0o755)
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            target = parent / "target"
            target.mkdir()
            root = parent / "private-runtime"
            root.symlink_to(target, target_is_directory=True)
            with self.assertRaises(SystemExit) as failure:
                execute_profile(
                    command, root, environment,
                    gunicorn_path=parent / "gunicorn")
            self.assertEqual(failure.exception.code, 71)
            self.assertTrue(root.is_symlink())
            self.assertTrue(target.is_dir())

    def test_invalid_host_and_port_fail_with_exit_72(self):
        profile = self._profile()
        command = profile["deployment_patch"]["containers"][0][
            "entrypoint_overrides"]["cmd"]
        environment = self._environment(profile)
        for host, port in (("bad/host", "5005"), ("127.0.0.1", "0"),
                           ("127.0.0.1", "70000"), ("127.0.0.1", "abc"),
                           ("h" * 10000, "5005"), ("127.0.0.1", "1" * 10000)):
            with self.subTest(host=host, port=port), \
                    tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "private-runtime"
                with self.assertRaises(SystemExit) as failure:
                    execute_profile(
                        command, root,
                        {**environment, "PII_HOST": host, "PII_PORT": port},
                        gunicorn_path=Path(temporary) / "gunicorn")
                self.assertEqual(failure.exception.code, 72)

    def test_command_argument_and_size_limits_fail_closed(self):
        archive, _, _, manifest_bytes = batch_package.build_batch_archive()
        encoded = batch_package._encoded_archive(archive)
        inline = len(encoded) - 47 * batch_package.BATCH_CARRIER_CHUNK_BYTES
        with mock.patch.object(
                package, "build_signed_command",
                return_value=["x"] * 57):
            with self.assertRaisesRegex(
                    ValueError, "command exceeds argument count limit"):
                batch_package._build_command(
                    archive, manifest_bytes, "args", inline_chars=inline,
                    batch_size=1, workers=8)
        with mock.patch.object(
                package, "build_signed_command",
                return_value=["x" * 254]):
            with self.assertRaisesRegex(
                    ValueError, "command argument exceeds provider limit"):
                batch_package._build_command(
                    archive, manifest_bytes, "size", inline_chars=inline,
                    batch_size=1, workers=8)
        with mock.patch.object(
                package, "build_signed_command",
                return_value=["\0" * 253] * 56):
            with self.assertRaisesRegex(
                    ValueError, "command exceeds size limit"):
                batch_package._build_command(
                    archive, manifest_bytes, "bytes", inline_chars=inline,
                    batch_size=1, workers=8)
        with mock.patch.object(
                batch_package, "BATCH_ARCHIVE_ENV_LIMIT_BYTES", 100):
            with self.assertRaisesRegex(
                    ValueError, "carrier exceeds size limit"):
                batch_package._encoded_archive(archive)


if __name__ == "__main__":
    unittest.main()
