import ast
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from tools.verda_model_experiment import package


DEFAULT_ARCHIVE_SHA256 = (
    "419c191c8afab6a444fa7642db81695d56a5660794b301deb84cbc6b01ad161b"
)
BASE_ENVIRONMENT = [
    ("PII_AUTH_MODE", "upstream"),
    ("PII_ANALYSIS_TIMEOUT_SECONDS", "60"),
    ("PII_MAX_CONCURRENT_ANALYSES", "16"),
    ("PII_MAX_QUEUED_ANALYSES", "32"),
    ("PII_QUEUE_TIMEOUT_SECONDS", "30"),
    ("OMP_NUM_THREADS", "1"),
    ("MKL_NUM_THREADS", "1"),
    ("TOKENIZERS_PARALLELISM", "false"),
]


def profile_parts(profile):
    container = profile["deployment_patch"]["containers"][0]
    command = container["entrypoint_overrides"]["cmd"]
    carrier = {
        entry["name"]: entry["value_or_reference_to_secret"]
        for entry in container["env"][len(BASE_ENVIRONMENT):]
    }
    return container, command, carrier


def payload_carrier_metadata(command):
    payload = package.reconstruct_signed_payload(command)
    inline = ast.literal_eval(
        re.search(r"^inline_carrier=(.+)$", payload, re.MULTILINE).group(1))
    names = ast.literal_eval(
        re.search(r"^carrier_names=(.+)$", payload, re.MULTILINE).group(1))
    return inline, names


def reconstruct_carrier(command, carrier):
    inline, names = payload_carrier_metadata(command)
    return inline + "".join(carrier[name] for name in names)


def carrier_for_archive(archive, inline_chars):
    encoded = base64.b64encode(archive).decode("ascii")
    _, names, values = package._gpu_carrier_parts(encoded, inline_chars)
    return dict(zip(names, values))


def execute_profile(command, runtime_root, environment, *,
                    gunicorn_path=None, carrier_names=()):
    payload = package.reconstruct_signed_payload(command).replace(
        f"root={package.RUNTIME_DESTINATION!r}",
        f"root={str(runtime_root)!r}",
    )
    if gunicorn_path is not None:
        payload = payload.replace(
            repr(package.GUNICORN_PATH), repr(str(gunicorn_path)))
    signed_command = package.build_signed_command(payload)
    captured = []
    with mock.patch.object(sys, "argv", ["-c", *signed_command[1:]]), \
            mock.patch.dict(os.environ, environment, clear=False), \
            mock.patch("os.execv", side_effect=lambda path, argv: captured.append(
                (path, argv))):
        exec(compile(signed_command[0], "<signed-gpu-profile>", "exec"), {})
        observed = {
            "carrier": os.environ.get(package.GPU_ARCHIVE_ENV),
            "carrier_chunks": [name for name in carrier_names
                               if os.environ.get(name) is not None],
            "workers": os.environ.get("ENVAIPI_VERDA_WORKERS"),
            "run_id": os.environ.get("ENVAIPI_VERDA_RUN_ID"),
            "pythonpath": os.environ.get("PYTHONPATH"),
        }
    return captured, observed


class DefaultArchiveTests(unittest.TestCase):
    def test_original_archive_and_default_profiles_remain_byte_identical(self):
        archive, hashes = package.build_archive()
        self.assertEqual(len(archive), 8972)
        self.assertEqual(hashlib.sha256(archive).hexdigest(),
                         DEFAULT_ARCHIVE_SHA256)
        self.assertEqual(set(hashes), set(package.ARCHIVE_FILES))
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            self.assertEqual(bundle.namelist(), list(package.ARCHIVE_FILES))
            self.assertNotIn(
                "tools/verda_model_experiment/gpu_monitor.py",
                bundle.namelist(),
            )
            self.assertNotIn(
                "tools/verda_model_experiment/gpu_runtime.py",
                bundle.namelist(),
            )
        for workers in (1, 2, 4, 8):
            with self.subTest(workers=workers):
                profile = package.build_profile(workers, f"original-{workers}")
                self.assertEqual(set(profile), {
                    "workers", "run_id", "deployment_patch", "scaling_patch",
                    "overrides", "source_hashes", "archive_file_hashes",
                })
                self.assertEqual(profile["overrides"]["runtime_archive_sha256"],
                                 DEFAULT_ARCHIVE_SHA256)
                self.assertEqual(profile["overrides"]["runtime_archive_bytes"],
                                 8972)
                self.assertEqual(profile["scaling_patch"], {
                    "min_replica_count": 0,
                    "max_replica_count": 1,
                    "concurrent_requests_per_replica": 32,
                })
                container = profile["deployment_patch"]["containers"][0]
                self.assertEqual(len(container["env"]), 8)
                self.assertEqual(
                    [(entry["name"], entry["value_or_reference_to_secret"])
                     for entry in container["env"]],
                    BASE_ENVIRONMENT,
                )
                self.assertEqual(
                    container["entrypoint_overrides"]["cmd"][0],
                    package.SIGNED_PAYLOAD_LOADER,
                )

    def test_gpu_archive_is_deterministic_whitelisted_and_separate(self):
        first, first_hashes = package.build_gpu_archive()
        second, second_hashes = package.build_gpu_archive()
        self.assertEqual(first, second)
        self.assertEqual(first_hashes, second_hashes)
        self.assertEqual(set(first_hashes), set(package.GPU_ARCHIVE_FILES))
        self.assertNotIn("tools/verda_model_experiment/gpu_profile.py",
                         first_hashes)
        self.assertNotIn("tools/verda_model_experiment/package.py",
                         first_hashes)
        self.assertNotIn("tools/verda_model_experiment/resources.py",
                         first_hashes)
        self.assertLessEqual(len(first), package.ARCHIVE_LIMIT_BYTES)
        self.assertLessEqual(
            sum(len((package.PACKAGE_ROOT / name).read_bytes())
                for name in package.GPU_ARCHIVE_FILES),
            package.GPU_EXTRACTED_LIMIT_BYTES,
        )
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertEqual(archive.namelist(), list(package.GPU_ARCHIVE_FILES))
            for entry in archive.infolist():
                mode = (entry.external_attr >> 16) & 0xffff
                self.assertTrue(stat.S_ISREG(mode))
                self.assertEqual(stat.S_IMODE(mode), 0o600)
                self.assertEqual(hashlib.sha256(archive.read(entry)).hexdigest(),
                                 first_hashes[entry.filename])

    def test_gpu_archive_sources_and_bootstrap_limits_are_strict(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                    ValueError, "packaging source is not a regular file"):
                package._gpu_archive_sources(Path(temporary))
        archive, hashes = package.build_gpu_archive()
        split = (len(base64.b64encode(archive)) + 1) // 2
        with self.assertRaisesRegex(
                ValueError, "gpu runtime archive exceeds size limit"):
            package._gpu_bootstrap_script(
                b"x" * (package.ARCHIVE_LIMIT_BYTES + 1), hashes, "archive",
                split, 8)
        changed = dict(hashes)
        changed["unexpected.py"] = "0" * 64
        with self.assertRaisesRegex(
                ValueError, "gpu runtime archive file set mismatch"):
            package._gpu_bootstrap_script(archive, changed, "file-set", split, 8)
        with self.assertRaisesRegex(ValueError, "invalid worker count"):
            package._gpu_bootstrap_script(
                archive, hashes, "workers", split, 4)
        with mock.patch.object(package, "COMMAND_LIMIT_BYTES", 100):
            with self.assertRaisesRegex(
                    ValueError, "gpu runtime bootstrap exceeds size limit"):
                package._gpu_bootstrap_script(
                    archive, hashes, "bootstrap", split, 8)
        with mock.patch.object(package, "GPU_ARCHIVE_ENV_LIMIT_BYTES", 100):
            with self.assertRaisesRegex(
                    ValueError,
                    "gpu runtime archive carrier exceeds size limit"):
                package._gpu_bootstrap_script(
                    archive, hashes, "carrier-limit", split, 8)

    def test_gpu_archive_limits_are_enforced_before_encoding(self):
        with mock.patch.object(package, "ARCHIVE_LIMIT_BYTES", 100):
            with self.assertRaisesRegex(
                    ValueError, "gpu runtime archive exceeds size limit"):
                package.build_gpu_archive()
        with mock.patch.object(package, "GPU_EXTRACTED_LIMIT_BYTES", 10):
            with self.assertRaisesRegex(
                    ValueError, "gpu runtime archive exceeds extracted size limit"):
                package.build_gpu_archive()
        archive, hashes = package.build_gpu_archive()
        split = (len(base64.b64encode(archive)) + 1) // 2
        with mock.patch.object(package, "GPU_ARCHIVE_ENV_LIMIT_BYTES", 100):
            with self.assertRaisesRegex(
                    ValueError,
                    "gpu runtime archive carrier exceeds size limit"):
                package._gpu_bootstrap_script(
                    archive, hashes, "carrier-limit", split, 8)


class GpuProfileTests(unittest.TestCase):
    def test_gpu_profile_uses_hybrid_carrier_and_keeps_base_contract(self):
        profile = package.build_gpu_profile("gpu-20261027")
        self.assertEqual(set(profile), {
            "workers", "run_id", "deployment_patch", "scaling_patch",
            "overrides", "source_hashes", "archive_file_hashes",
        })
        self.assertEqual(profile["workers"], 8)
        self.assertEqual(profile["run_id"], "gpu-20261027")
        self.assertEqual(profile["scaling_patch"], {
            "min_replica_count": 0,
            "max_replica_count": 1,
            "concurrent_requests_per_replica": 32,
        })
        self.assertEqual(profile["overrides"]["gpu_profile"], True)
        self.assertEqual(profile["overrides"]["gpu_archive_transport"],
                         "hybrid")
        self.assertEqual(profile["overrides"]["gpu_archive_env"],
                         package.GPU_ARCHIVE_ENV_PREFIX)
        self.assertEqual(profile["overrides"]["gpu_archive_env_chunks"], 41)
        self.assertEqual(profile["overrides"]["gpu_archive_inline_chars"],
                         9759)
        self.assertEqual(profile["overrides"]["workers"], 8)
        self.assertFalse(profile["overrides"]["preload_app"])
        self.assertFalse(profile["overrides"]["access_logs"])
        self.assertEqual(profile["source_hashes"],
                         package.runtime.SOURCE_HASHES)
        archive, hashes = package.build_gpu_archive()
        self.assertEqual(profile["archive_file_hashes"], hashes)
        self.assertEqual(profile["overrides"]["runtime_archive_sha256"],
                         hashlib.sha256(archive).hexdigest())
        self.assertEqual(profile["overrides"]["runtime_archive_bytes"],
                         len(archive))
        container, command, carrier = profile_parts(profile)
        inline, names = payload_carrier_metadata(command)
        encoded = base64.b64encode(archive).decode("ascii")
        self.assertEqual(len(container["env"]),
                         len(BASE_ENVIRONMENT) + len(names))
        self.assertEqual(
            [(entry["name"], entry["value_or_reference_to_secret"])
             for entry in container["env"][:8]],
            BASE_ENVIRONMENT,
        )
        self.assertEqual(
            names,
            tuple(f"{package.GPU_ARCHIVE_ENV_PREFIX}{index:02d}"
                  for index in range(len(names))))
        self.assertEqual(set(carrier), set(names))
        self.assertTrue(all(entry["type"] == "plain"
                            for entry in container["env"]))
        self.assertTrue(inline.isascii())
        self.assertEqual(inline, encoded[:len(inline)])
        self.assertEqual(reconstruct_carrier(command, carrier), encoded)
        self.assertEqual(base64.b64decode(
            reconstruct_carrier(command, carrier), validate=True), archive)
        self.assertLessEqual(
            abs(len(inline) - len(encoded) // 2),
            package.GPU_CARRIER_CHUNK_BYTES)
        self.assertEqual(len(names),
                         profile["overrides"]["gpu_archive_env_chunks"])
        self.assertEqual(len(inline),
                         profile["overrides"]["gpu_archive_inline_chars"])
        self.assertTrue(all(len(value.encode("ascii"))
                            <= package.MAX_COMMAND_ARGUMENT_BYTES
                            for value in carrier.values()))
        self.assertEqual(max(len(value.encode("ascii"))
                             for value in carrier.values()),
                         package.MAX_COMMAND_ARGUMENT_BYTES)
        self.assertLessEqual(len(container["env"]),
                             package.GPU_MAX_ENVIRONMENT_ENTRIES)
        self.assertTrue(all(
            len(entry["name"].encode("ascii"))
            <= package.MAX_COMMAND_ARGUMENT_BYTES
            and len(entry["value_or_reference_to_secret"].encode("ascii"))
            <= package.MAX_COMMAND_ARGUMENT_BYTES
            for entry in container["env"]))
        self.assertNotIn(package.GPU_ARCHIVE_ENV, carrier)
        self.assertNotIn(package.GPU_ARCHIVE_ENV,
                         [entry["name"] for entry in container["env"]])
        self.assertNotIn(package.GPU_ARCHIVE_ENV, json.dumps(command))
        self.assertIn(package.GPU_ARCHIVE_ENV_PREFIX,
                      package.reconstruct_signed_payload(command))
        entrypoint = container["entrypoint_overrides"]["entrypoint"]
        self.assertEqual(entrypoint, ["/usr/local/bin/python", "-c"])
        payload = package.reconstruct_signed_payload(command)
        gunicorn_arguments = package._gpu_gunicorn_arguments(8)
        self.assertTrue(payload.startswith(
            f"import sys;sys.argv={['-c', *gunicorn_arguments]!r}\n"))
        self.assertLessEqual(len(command), package.MAX_COMMAND_ARGUMENTS)
        self.assertLessEqual(
            max(len(argument.encode("ascii"))
                for argument in [*entrypoint, *command]),
            package.MAX_COMMAND_ARGUMENT_BYTES,
        )
        self.assertLessEqual(
            len(json.dumps(command, separators=(",", ":")).encode("utf-8")),
            package.COMMAND_LIMIT_BYTES,
        )
        encoded_length = len(encoded)
        with self.assertRaisesRegex(
                ValueError, "runtime command exceeds argument count limit"):
            package._build_gpu_command(
                archive, hashes, "inline-too-wide",
                inline_chars=encoded_length - 1, workers=8)

    def test_worker_choices_share_the_archive_carrier_and_bounds(self):
        base = package.build_gpu_profile("copies-profile")
        base_container, base_command, base_carrier = profile_parts(base)
        for workers in (12, 16):
            with self.subTest(workers=workers):
                profile = package.build_gpu_profile(
                    "copies-profile", workers=workers)
                container, command, carrier = profile_parts(profile)
                self.assertEqual(profile["workers"], workers)
                self.assertEqual(profile["overrides"]["workers"], workers)
                self.assertEqual(profile["archive_file_hashes"],
                                 base["archive_file_hashes"])
                self.assertEqual(carrier, base_carrier)
                self.assertEqual(len(container["env"]),
                                 len(base_container["env"]))
                self.assertEqual(
                    profile["overrides"]["gpu_archive_env_chunks"], 41)
                self.assertEqual(
                    profile["overrides"]["gpu_archive_inline_chars"], 9759)
                self.assertLessEqual(
                    len(command), package.MAX_COMMAND_ARGUMENTS
                    - package.GPU_TRANSPORT_HEADROOM)
                self.assertLessEqual(
                    len(container["env"]), package.GPU_MAX_ENVIRONMENT_ENTRIES
                    - package.GPU_TRANSPORT_HEADROOM)
                self.assertNotEqual(command, base_command)
                gunicorn = package._gpu_gunicorn_arguments(workers)
                self.assertTrue(package.reconstruct_signed_payload(
                    command).startswith(
                        f"import sys;sys.argv={['-c', *gunicorn]!r}\n"))
        for workers in (1, 2, 4, 9, 13, 15, 17, True, 8.0, "8", None):
            with self.subTest(rejected=workers), self.assertRaises(ValueError):
                package.build_gpu_profile("copies-profile", workers=workers)

    def test_gpu_profile_is_deterministic_and_fails_closed_on_too_many_chunks(self):
        first = package.build_gpu_profile("verda-20261028-gpu8")
        second = package.build_gpu_profile("verda-20261028-gpu8")
        self.assertEqual(first, second)
        container, command, carrier = profile_parts(first)
        inline, names = payload_carrier_metadata(command)
        archive, hashes = package.build_gpu_archive()
        encoded = base64.b64encode(archive).decode("ascii")
        self.assertEqual(inline + "".join(carrier[name] for name in names),
                         encoded)
        self.assertLessEqual(len(container["env"]),
                             package.GPU_MAX_ENVIRONMENT_ENTRIES)
        self.assertLessEqual(len(command), package.MAX_COMMAND_ARGUMENTS)
        with mock.patch.object(
                package, "GPU_MAX_ENVIRONMENT_ENTRIES",
                len(BASE_ENVIRONMENT)):
            with self.assertRaisesRegex(
                    ValueError,
                    "gpu runtime transport exceeds provider limits"):
                package._gpu_command_plan(archive, hashes, "too-many-chunks", 8)

    def test_environment_value_boundary_is_253_not_254(self):
        archive, _ = package.build_gpu_archive()
        encoded = base64.b64encode(archive).decode("ascii")
        split = (len(encoded) + 1) // 2
        _, names, values = package._gpu_carrier_parts(encoded, split)
        self.assertEqual(package.GPU_CARRIER_CHUNK_BYTES, 253)
        self.assertEqual(package.MAX_COMMAND_ARGUMENT_BYTES, 253)
        self.assertEqual(len(names), len(values))
        self.assertEqual(max(len(value.encode("ascii")) for value in values),
                         253)
        with mock.patch.object(package, "GPU_CARRIER_CHUNK_BYTES", 254):
            with self.assertRaisesRegex(
                    ValueError,
                    "gpu runtime archive carrier exceeds provider limit"):
                package._gpu_carrier_parts(encoded, split)

    def test_gpu_profile_rejects_invalid_run_and_enforces_command_limits(self):
        for run_id in ("", "../bad", "bad/run", "x" * 65, None):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                package.build_gpu_profile(run_id)
        archive, hashes = package.build_gpu_archive()
        split = (len(base64.b64encode(archive)) + 1) // 2
        with mock.patch.object(
                package, "build_signed_command",
                return_value=["x"] * (package.MAX_COMMAND_ARGUMENTS + 1)):
            with self.assertRaisesRegex(
                    ValueError, "runtime command exceeds argument count limit"):
                package._build_gpu_command(
                    archive, hashes, "arg-count", inline_chars=split, workers=8)
        with mock.patch.object(
                package, "build_signed_command",
                return_value=["x" * (package.MAX_COMMAND_ARGUMENT_BYTES + 1)]):
            with self.assertRaisesRegex(
                    ValueError, "runtime command argument exceeds provider limit"):
                package._build_gpu_command(
                    archive, hashes, "arg-size", inline_chars=split, workers=8)
        oversized = ["\0" * package.MAX_COMMAND_ARGUMENT_BYTES] * \
            package.MAX_COMMAND_ARGUMENTS
        with mock.patch.object(
                package, "build_signed_command", return_value=oversized):
            with self.assertRaisesRegex(
                    ValueError, "runtime command exceeds size limit"):
                package._build_gpu_command(
                    archive, hashes, "command-size", inline_chars=split,
                    workers=8)


class CarrierBootstrapTests(unittest.TestCase):
    def _profile_command(self):
        profile = package.build_gpu_profile("carrier-run")
        _, command, carrier = profile_parts(profile)
        return command, carrier, profile

    def test_carrier_bootstrap_verifies_extracts_and_removes_carrier(self):
        command, carrier, profile = self._profile_command()
        inline, names = payload_carrier_metadata(command)
        self.assertEqual(len(carrier), len(names))
        self.assertEqual(set(carrier), set(names))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private-runtime"
            fake_gunicorn = Path(temporary) / "gunicorn"
            captured, observed = execute_profile(
                command, root,
                {
                    "PII_HOST": "127.0.0.1",
                    "PII_PORT": "5055",
                    **carrier,
                },
                gunicorn_path=fake_gunicorn,
                carrier_names=carrier,
            )
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
            self.assertIsNone(observed["carrier"])
            self.assertEqual(observed["carrier_chunks"], [])
            self.assertEqual(observed["workers"], "8")
            self.assertEqual(observed["run_id"], "carrier-run")
            self.assertEqual(observed["pythonpath"], str(root))
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            for name in package.GPU_ARCHIVE_FILES:
                target = root.joinpath(*name.split("/"))
                self.assertTrue(target.is_file())
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
                self.assertEqual(
                    hashlib.sha256(target.read_bytes()).hexdigest(),
                    profile["archive_file_hashes"][name],
                )
            self.assertFalse(
                (root / "tools/verda_model_experiment/gpu_profile.py").exists())
            config = (root / "gunicorn_config.py").read_bytes()
            self.assertIn(b"gpu_runtime import load_gunicorn_config", config)
            compile(config, "gunicorn_config.py", "exec")

    def test_tampered_missing_ordered_and_oversized_carriers_fail_before_writes(self):
        command, carrier, _ = self._profile_command()
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
            package.MAX_COMMAND_ARGUMENT_BYTES + 1
            - len(oversized[names[-1]]))
        invalids = (
            ("tampered", tampered),
            ("order", ordered),
            ("missing", missing),
            ("invalid-base64", invalid_base64),
            ("oversized-254", oversized),
        )
        for name, chunks in invalids:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "private-runtime"
                environment = {
                    "PII_HOST": "127.0.0.1",
                    "PII_PORT": "5055",
                    **chunks,
                }
                with self.assertRaises(SystemExit) as failure:
                    execute_profile(command, root, environment,
                                    carrier_names=chunks)
                self.assertEqual(failure.exception.code, 70)
                self.assertFalse(root.exists())

    def test_changed_file_hash_and_path_traversal_fail_before_writes(self):
        archive, hashes = package.build_gpu_archive()
        split = (len(base64.b64encode(archive)) + 1) // 2
        changed = dict(hashes)
        changed[package.GPU_ARCHIVE_FILES[-1]] = "0" * 64
        command = package._build_gpu_command(
            archive, changed, "hash-tamper", inline_chars=split, workers=8)
        carrier = carrier_for_archive(archive, split)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private-runtime"
            with self.assertRaises(SystemExit) as failure:
                execute_profile(command, root, carrier,
                                carrier_names=carrier)
            self.assertEqual(failure.exception.code, 70)
            self.assertFalse(root.exists())
        with zipfile.ZipFile(io.BytesIO(archive)) as original:
            members = {
                name: original.read(name) for name in package.GPU_ARCHIVE_FILES
            }
        traversal = io.BytesIO()
        with zipfile.ZipFile(traversal, "w", compression=zipfile.ZIP_LZMA) as bundle:
            for index, name in enumerate(package.GPU_ARCHIVE_FILES):
                member_name = "../../escape.py" if index == 0 else name
                info = zipfile.ZipInfo(
                    member_name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_LZMA
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                bundle.writestr(info, members[name])
        traversal_bytes = traversal.getvalue()
        traversal_split = (
            len(base64.b64encode(traversal_bytes)) + 1) // 2
        command = package._build_gpu_command(
            traversal_bytes, hashes, "traversal",
            inline_chars=traversal_split, workers=8)
        traversal_carrier = carrier_for_archive(
            traversal_bytes, traversal_split)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private-runtime"
            with self.assertRaises(SystemExit) as failure:
                execute_profile(command, root, traversal_carrier,
                                carrier_names=traversal_carrier)
            self.assertEqual(failure.exception.code, 70)
            self.assertFalse((Path(temporary) / "escape.py").exists())
            self.assertFalse(root.exists())

    def test_symlink_member_and_extracted_overflow_fail_before_writes(self):
        symlink_archive = io.BytesIO()
        symlink_contents = {}
        with zipfile.ZipFile(
                symlink_archive, "w", compression=zipfile.ZIP_LZMA) as bundle:
            for index, name in enumerate(package.GPU_ARCHIVE_FILES):
                info = zipfile.ZipInfo(
                    name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_LZMA
                info.create_system = 3
                if index == 0:
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                else:
                    info.external_attr = (stat.S_IFREG | 0o600) << 16
                contents = b"../../escape.py" if index == 0 else b"safe"
                symlink_contents[name] = contents
                bundle.writestr(info, contents)
        symlink_bytes = symlink_archive.getvalue()
        symlink_hashes = {
            name: hashlib.sha256(contents).hexdigest()
            for name, contents in symlink_contents.items()
        }
        symlink_split = (len(base64.b64encode(symlink_bytes)) + 1) // 2
        command = package._build_gpu_command(
            symlink_bytes, symlink_hashes, "symlink",
            inline_chars=symlink_split, workers=8)
        symlink_carrier = carrier_for_archive(symlink_bytes, symlink_split)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private-runtime"
            with self.assertRaises(SystemExit) as failure:
                execute_profile(command, root, symlink_carrier,
                                carrier_names=symlink_carrier)
            self.assertEqual(failure.exception.code, 70)
            self.assertFalse(root.exists())
        oversized_archive = io.BytesIO()
        oversized_contents = {}
        with zipfile.ZipFile(
                oversized_archive, "w", compression=zipfile.ZIP_LZMA) as bundle:
            for name in package.GPU_ARCHIVE_FILES:
                info = zipfile.ZipInfo(
                    name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_LZMA
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                contents = b"\0" * 25_000
                oversized_contents[name] = contents
                bundle.writestr(info, contents)
        oversized_bytes = oversized_archive.getvalue()
        self.assertLessEqual(len(oversized_bytes), package.ARCHIVE_LIMIT_BYTES)
        oversized_hashes = {
            name: hashlib.sha256(contents).hexdigest()
            for name, contents in oversized_contents.items()
        }
        oversized_split = (
            len(base64.b64encode(oversized_bytes)) + 1) // 2
        command = package._build_gpu_command(
            oversized_bytes, oversized_hashes, "extracted-overflow",
            inline_chars=oversized_split, workers=8)
        oversized_carrier = carrier_for_archive(
            oversized_bytes, oversized_split)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private-runtime"
            with self.assertRaises(SystemExit) as failure:
                execute_profile(command, root, oversized_carrier,
                                carrier_names=oversized_carrier)
            self.assertEqual(failure.exception.code, 70)
            self.assertFalse(root.exists())

    def test_unsafe_existing_root_is_not_replaced(self):
        command, carrier, _ = self._profile_command()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private-runtime"
            root.mkdir(mode=0o755)
            root.chmod(0o755)
            with self.assertRaises(SystemExit) as failure:
                execute_profile(command, root, carrier,
                                carrier_names=carrier)
            self.assertEqual(failure.exception.code, 71)
            self.assertEqual(root.stat().st_mode & 0o777, 0o755)


class FreshImportTests(unittest.TestCase):
    def test_actual_opt_in_package_execs_and_imports_in_a_fresh_subprocess(self):
        for workers in (8, 12, 16):
            with self.subTest(workers=workers):
                self._fresh_import(workers)

    def _fresh_import(self, workers):
        run_id = f"fresh-import-run-{workers}"
        profile = package.build_gpu_profile(run_id, workers=workers)
        _, command, carrier = profile_parts(profile)
        carrier_names = json.dumps(list(carrier))
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            runtime_root = temporary_path / "private-runtime"
            working_directory = temporary_path / "unrelated"
            working_directory.mkdir()
            fake_gunicorn = temporary_path / "fake-gunicorn"
            fake_gunicorn.write_text(
                f"#!{sys.executable}\n"
                "import json,os,sys\n"
                "from tools.verda_model_experiment import gpu_monitor,gpu_runtime,runtime\n"
                "print(json.dumps({\n"
                " 'gpu_runtime':gpu_runtime.__file__,\n"
                " 'gpu_monitor':gpu_monitor.__file__,\n"
                " 'carrier':os.environ.get('ENVAIPI_VERDA_GPU_ARCHIVE'),\n"
                f" 'carrier_chunks':[name for name in {carrier_names} "
                "if name in os.environ],\n"
                " 'workers':os.environ.get(runtime.PROFILE_WORKERS_ENV),\n"
                " 'run_id':os.environ.get(runtime.PROFILE_RUN_ID_ENV),\n"
                " 'torch_loaded':'torch' in sys.modules,\n"
                " 'sys_path':sys.path,\n"
                "}))\n",
                encoding="utf-8",
            )
            fake_gunicorn.chmod(0o700)
            payload = package.reconstruct_signed_payload(command).replace(
                f"root={package.RUNTIME_DESTINATION!r}",
                f"root={str(runtime_root)!r}",
            ).replace(repr(package.GUNICORN_PATH), repr(str(fake_gunicorn)))
            signed_command = package.build_signed_command(payload)
            completed = subprocess.run(
                [sys.executable, "-c", *signed_command],
                cwd=working_directory,
                env={
                    "PII_HOST": "127.0.0.1",
                    "PII_PORT": "5005",
                    **carrier,
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(
                Path(result["gpu_runtime"]).resolve(),
                (runtime_root / "tools/verda_model_experiment/gpu_runtime.py").resolve(),
            )
            self.assertEqual(
                Path(result["gpu_monitor"]).resolve(),
                (runtime_root / "tools/verda_model_experiment/gpu_monitor.py").resolve(),
            )
            self.assertIsNone(result["carrier"])
            self.assertEqual(result["carrier_chunks"], [])
            self.assertIs(result["torch_loaded"], False)
            self.assertEqual(result["workers"], str(workers))
            self.assertEqual(result["run_id"], run_id)
            self.assertIn(str(runtime_root), result["sys_path"])
            self.assertNotIn(
                str(Path(__file__).resolve().parents[1]), result["sys_path"])


if __name__ == "__main__":
    unittest.main()
