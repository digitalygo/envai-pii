import base64
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
import zlib

from tools.verda_model_experiment import package, runtime


class PackageProfileTests(unittest.TestCase):
    def test_profiles_have_exact_container_scaling_and_environment_shapes(self):
        expected_environment = [
            ("PII_AUTH_MODE", "upstream"),
            ("PII_ANALYSIS_TIMEOUT_SECONDS", "60"),
            ("PII_MAX_CONCURRENT_ANALYSES", "16"),
            ("PII_MAX_QUEUED_ANALYSES", "32"),
            ("PII_QUEUE_TIMEOUT_SECONDS", "30"),
            ("OMP_NUM_THREADS", "1"),
            ("MKL_NUM_THREADS", "1"),
            ("TOKENIZERS_PARALLELISM", "false"),
        ]
        for workers in (1, 2, 4, 8):
            with self.subTest(workers=workers):
                profile = package.build_profile(workers, f"run-{workers}")
                self.assertEqual(set(profile), {
                    "workers", "run_id", "deployment_patch", "scaling_patch",
                    "overrides", "source_hashes", "archive_file_hashes",
                })
                patch = profile["deployment_patch"]
                self.assertEqual(set(patch), {"containers"})
                self.assertEqual(len(patch["containers"]), 1)
                container = patch["containers"][0]
                self.assertEqual(set(container), {
                    "name", "entrypoint_overrides", "env",
                })
                self.assertEqual(container["name"], "envai-pii-test-0")
                overrides = container["entrypoint_overrides"]
                self.assertEqual(overrides["enabled"], True)
                self.assertEqual(overrides["entrypoint"], [
                    "/usr/local/bin/python", "-c",
                ])
                command = overrides["cmd"]
                gunicorn_arguments = [
                    "--config", package.PRIVATE_CONFIG_PATH,
                    "--chdir", "/app/src/app",
                    "--bind", "__VERDA_BIND__",
                    "--worker-class", "gthread",
                    "--workers", str(workers),
                    "--timeout", "600",
                    "--graceful-timeout", "30",
                    "--access-logfile", "/dev/null",
                    "--error-logfile", "-",
                    "cloud_service:create_app()",
                ]
                payload = package.reconstruct_signed_payload(command)
                self.assertTrue(payload.startswith(
                    f"import sys;sys.argv={['-c', *gunicorn_arguments]!r}\n"))
                env = container["env"]
                self.assertEqual(len(env), 8)
                self.assertEqual([(entry["name"], entry["value_or_reference_to_secret"])
                                  for entry in env], expected_environment)
                self.assertTrue(all(entry["type"] == "plain" for entry in env))
                self.assertEqual(profile["scaling_patch"], {
                    "min_replica_count": 0,
                    "max_replica_count": 1,
                    "concurrent_requests_per_replica": 32,
                })
                self.assertEqual(profile["overrides"]["workers"], workers)
                self.assertFalse(profile["overrides"]["preload_app"])
                self.assertFalse(profile["overrides"]["access_logs"])
                self.assertEqual(profile["source_hashes"], runtime.SOURCE_HASHES)
                self.assertLessEqual(profile["overrides"]["runtime_archive_bytes"],
                                     package.ARCHIVE_LIMIT_BYTES)
                self.assertEqual(command[0], package.SIGNED_PAYLOAD_LOADER)
                self.assertTrue(all(argument.isascii() for argument in command))
                self.assertLessEqual(len(command), package.MAX_COMMAND_ARGUMENTS)
                self.assertLessEqual(max(len(argument.encode("ascii"))
                                         for argument in [*overrides["entrypoint"], *command]),
                                     package.MAX_COMMAND_ARGUMENT_BYTES)
                payload_chunks = command[package.PAYLOAD_CHUNK_START:]
                self.assertLessEqual(max(len(chunk.encode("ascii"))
                                         for chunk in payload_chunks),
                                     package.PAYLOAD_CHUNK_BYTES)
                self.assertLessEqual(len(json.dumps(
                    command, separators=(",", ":")).encode("utf-8")),
                    package.COMMAND_LIMIT_BYTES)
                self.assertEqual(package.reconstruct_signed_payload(command), payload)
                self.assertEqual(profile["overrides"]["fixture"]["text_codepoints"],
                                 45_000)

    def test_full_run_profiles_fit_the_provider_argument_envelope(self):
        from tools.verda_model_experiment import build_profile

        self.assertIs(build_profile, package.build_profile)
        for workers in (1, 2, 4, 8):
            run_id = f"verda-20261027-n{workers}"
            with self.subTest(run_id=run_id):
                profile = package.build_profile(workers, run_id)
                container = profile["deployment_patch"]["containers"][0]
                command = container["entrypoint_overrides"]["cmd"]
                serialized_bytes = len(json.dumps(
                    command, separators=(",", ":")).encode("utf-8"))
                entrypoint = container["entrypoint_overrides"]["entrypoint"]
                max_argument_bytes = max(
                    len(argument.encode("ascii"))
                    for argument in [*entrypoint, *command])
                self.assertEqual(profile["run_id"], run_id)
                self.assertLess(len(command), package.MAX_COMMAND_ARGUMENTS)
                self.assertLessEqual(max_argument_bytes,
                                     package.MAX_COMMAND_ARGUMENT_BYTES)
                self.assertLessEqual(serialized_bytes, package.COMMAND_LIMIT_BYTES)
                self.assertEqual(
                    profile["overrides"]["runtime_archive_sha256"],
                    hashlib.sha256(package.build_archive()[0]).hexdigest(),
                )

    def test_package_exports_build_profile_lazily_and_guard_remains_compatible(self):
        program = """import json,sys
import tools.verda_model_experiment as api
package_name='tools.verda_model_experiment.package'
resources_name='tools.verda_model_experiment.resources'
initial=(package_name in sys.modules,resources_name in sys.modules)
builder=api.build_profile
guard=api.evaluate_resource_guard(2,{}, {},1)
print(json.dumps({'initial':initial,'package_after':package_name in sys.modules,'resources_after':resources_name in sys.modules,'builder':callable(builder),'guard_reason':guard['reason']}))"""
        completed = subprocess.run(
            [sys.executable, "-c", program],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {
            "initial": [False, False],
            "package_after": True,
            "resources_after": True,
            "builder": True,
            "guard_reason": "worker_count_unknown",
        })

    def test_signed_payload_validation_rejects_non_ascii_non_string_and_empty(self):
        for payload in ("pi\u00f1ata", None, 7):
            with self.subTest(payload=payload), self.assertRaisesRegex(
                ValueError, "signed runtime payload must be ASCII"
            ):
                package.build_signed_command(payload)
        with self.assertRaisesRegex(ValueError, "signed runtime payload must not be empty"):
            package.build_signed_command("")

    def test_signed_command_rejects_oversized_loader_argument(self):
        with mock.patch.object(
            package,
            "MAX_COMMAND_ARGUMENT_BYTES",
            len(package.SIGNED_PAYLOAD_LOADER) - 1,
        ):
            with self.assertRaisesRegex(
                ValueError, "runtime command argument exceeds provider limit"
            ):
                package.build_signed_command("payload")

    def test_reconstructed_command_rejects_malformed_digests_and_chunks(self):
        command = package.build_signed_command("x")
        digest_index = package.PAYLOAD_CHUNK_START - 1
        malformed_commands = {
            "non-list": tuple(command),
            "short-command": command[:package.PAYLOAD_CHUNK_START],
            "wrong-loader": ["unexpected-loader", *command[1:]],
            "short-digest": [*command[:digest_index], "0" * 63,
                             *command[digest_index + 1:]],
            "empty-chunk": [*command[:-1], ""],
            "non-ascii-chunk": [*command[:-1], "\u00e9"],
            "wrong-type-chunk": [*command[:-1], 1],
            "oversized-chunk": [
                *command[:-1], "x" * (package.PAYLOAD_CHUNK_BYTES + 1)
            ],
        }
        for name, malformed in malformed_commands.items():
            with self.subTest(malformed=name), self.assertRaisesRegex(
                ValueError, "invalid signed runtime command"
            ):
                package.reconstruct_signed_payload(malformed)

    def test_reconstructed_command_rejects_oversized_decompression_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "payload-executed"
            payload = (
                f"from pathlib import Path;Path({str(marker)!r}).write_text('executed')\n"
                + "_padding='" + "x" * (package.PAYLOAD_LIMIT_BYTES + 128) + "'\n"
            )
            encoded = payload.encode("ascii")
            compressed = zlib.compress(encoded, level=9)
            compressed_text = base64.b64encode(compressed).decode("ascii")
            chunks = [compressed_text[index:index + package.PAYLOAD_CHUNK_BYTES]
                      for index in range(0, len(compressed_text), package.PAYLOAD_CHUNK_BYTES)]
            command = [
                package.SIGNED_PAYLOAD_LOADER,
                *package.SIGNED_PAYLOAD_VERIFIER_CHUNKS,
                hashlib.sha256(encoded).hexdigest(),
                *chunks,
            ]
            self.assertLessEqual(len(command), package.MAX_COMMAND_ARGUMENTS)
            with self.assertRaisesRegex(ValueError, "invalid signed runtime command"):
                package.reconstruct_signed_payload(command)
            with self.assertRaisesRegex(ValueError, "runtime payload exceeds size limit"):
                package.build_signed_command(payload)
            completed = subprocess.run(
                [sys.executable, "-c", *command],
                cwd=temporary,
                env={},
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(completed.returncode, 70, completed.stderr)
            self.assertFalse(marker.exists())

    def test_profile_rechecks_mocked_argument_and_serialized_command_limits(self):
        oversized_argument = "x" * (package.MAX_COMMAND_ARGUMENT_BYTES + 1)
        with mock.patch.object(
            package, "build_signed_command", return_value=[oversized_argument]
        ):
            with self.assertRaisesRegex(
                ValueError, "runtime command argument exceeds provider limit"
            ):
                package.build_profile(1, "argument-over-limit")

        too_many_arguments = ["x"] * (package.MAX_COMMAND_ARGUMENTS + 1)
        with mock.patch.object(
            package, "build_signed_command", return_value=too_many_arguments
        ):
            with self.assertRaisesRegex(
                ValueError, "runtime command exceeds argument count limit"
            ):
                package.build_profile(1, "argument-count-over-limit")

        oversized_command = ["\0" * package.MAX_COMMAND_ARGUMENT_BYTES] * \
            package.MAX_COMMAND_ARGUMENTS
        with mock.patch.object(
            package, "build_signed_command", return_value=oversized_command
        ):
            with self.assertRaisesRegex(ValueError, "runtime command exceeds size limit"):
                package.build_profile(1, "serialized-over-limit")

    def test_signed_command_enforces_provider_argument_count(self):
        payload = "_=" + repr(hashlib.shake_256(b"argument-cap").hexdigest(120))
        with mock.patch.object(package, "PAYLOAD_CHUNK_BYTES", 1):
            with self.assertRaisesRegex(
                ValueError, "runtime command exceeds argument count limit"
            ):
                package.build_signed_command(payload)
        command = package.build_signed_command("x")
        too_many_arguments = command + ["x"] * (
            package.MAX_COMMAND_ARGUMENTS + 1 - len(command))
        with self.assertRaisesRegex(ValueError, "invalid signed runtime command"):
            package.reconstruct_signed_payload(too_many_arguments)

    def test_signed_loader_rejects_malformed_and_trailing_compressed_transport(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "payload-executed"
            payload = (
                f"from pathlib import Path;Path({str(marker)!r}).write_text('executed')\n"
            ).encode("ascii")
            digest = hashlib.sha256(payload).hexdigest()
            valid_compressed = zlib.compress(payload, level=9)
            malformed_inputs = {
                "base64": ["!"],
                "zlib": [base64.b64encode(b"not-zlib").decode("ascii")],
                "truncated": [base64.b64encode(valid_compressed[:-1]).decode("ascii")],
                "trailing": [base64.b64encode(valid_compressed + b"trailing").decode("ascii")],
            }
            for name, encoded_chunks in malformed_inputs.items():
                if name != "base64":
                    encoded = encoded_chunks[0]
                    encoded_chunks = [
                        encoded[index:index + package.PAYLOAD_CHUNK_BYTES]
                        for index in range(0, len(encoded), package.PAYLOAD_CHUNK_BYTES)
                    ]
                command = [
                    package.SIGNED_PAYLOAD_LOADER,
                    *package.SIGNED_PAYLOAD_VERIFIER_CHUNKS,
                    digest,
                    *encoded_chunks,
                ]
                with self.subTest(transport=name):
                    with self.assertRaises(ValueError):
                        package.reconstruct_signed_payload(command)
                    completed = subprocess.run(
                        [sys.executable, "-c", *command],
                        cwd=temporary,
                        env={},
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 70, completed.stderr)
                    self.assertFalse(marker.exists())

    def test_signed_loader_rejects_hash_order_tamper_and_truncation_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "payload-executed"
            payload = (
                f"from pathlib import Path;Path({str(marker)!r}).write_text('executed')\n"
                + "_padding='" + hashlib.shake_256(b"order-tamper").hexdigest(900) + "'\n"
            )
            command = package.build_signed_command(payload)
            self.assertEqual(package.reconstruct_signed_payload(command), payload)
            chunk_start = package.PAYLOAD_CHUNK_START
            self.assertGreater(len(command[chunk_start:]), 1)
            tampered_hash = command.copy()
            tampered_hash[chunk_start - 1] = "0" * 64
            tampered_verifier = command.copy()
            tampered_verifier[1] = (
                "x" if tampered_verifier[1][0] != "x" else "y"
            ) + tampered_verifier[1][1:]
            tampered_chunk = command.copy()
            tampered_chunk[chunk_start] = (
                "x" if tampered_chunk[chunk_start][0] != "x" else "y"
            ) + tampered_chunk[chunk_start][1:]
            reordered = command[:chunk_start] + list(reversed(command[chunk_start:]))
            truncated = command[:-1]
            for name, malformed in (
                ("hash", tampered_hash),
                ("verifier", tampered_verifier),
                ("chunk", tampered_chunk),
                ("ordering", reordered),
                ("truncation", truncated),
            ):
                with self.subTest(malformed=name):
                    with self.assertRaises(ValueError):
                        package.reconstruct_signed_payload(malformed)
                    completed = subprocess.run(
                        [sys.executable, "-c", *malformed],
                        cwd=temporary,
                        env={},
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 70, completed.stderr)
                    self.assertFalse(marker.exists())

    def test_worker_count_and_run_id_are_strict(self):
        for workers in (0, 3, 9, True, 1.0, "2"):
            with self.subTest(workers=workers), self.assertRaises(ValueError):
                package.build_profile(workers, "valid-run")
        for run_id in ("", "../run", "bad/name", "-starts-wrong", "x" * 65, None):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                package.build_profile(1, run_id)

    def test_archive_is_deterministic_whitelisted_and_hash_validated(self):
        first, first_hashes = package.build_archive()
        second, second_hashes = package.build_archive()
        self.assertEqual(first, second)
        self.assertEqual(first_hashes, second_hashes)
        self.assertEqual(set(first_hashes), set(package.ARCHIVE_FILES))
        self.assertNotIn("tools/verda_model_experiment/package.py", first_hashes)
        self.assertNotIn("tools/verda_model_experiment/resources.py", first_hashes)
        self.assertLessEqual(len(first), package.ARCHIVE_LIMIT_BYTES)
        self.assertEqual(hashlib.sha256(first).hexdigest(),
                         package.build_profile(1, "archive-test")["overrides"][
                             "runtime_archive_sha256"])
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertEqual(archive.namelist(), list(package.ARCHIVE_FILES))
            for entry in archive.infolist():
                mode = (entry.external_attr >> 16) & 0xffff
                self.assertTrue(stat.S_ISREG(mode))
                self.assertEqual(stat.S_IMODE(mode), 0o600)
                self.assertEqual(hashlib.sha256(archive.read(entry)).hexdigest(),
                                 first_hashes[entry.filename])

    def _run_bootstrap(self, command, runtime_root, environment=None):
        payload = package.reconstruct_signed_payload(command)
        payload = payload.replace(
            f"root={package.RUNTIME_DESTINATION!r}", f"root={str(runtime_root)!r}")
        signed_command = package.build_signed_command(payload)
        captured = []
        with mock.patch.object(sys, "argv", ["-c", *signed_command[1:]]), \
                mock.patch.dict(os.environ, environment or {}, clear=False), \
                mock.patch("os.execv", side_effect=lambda path, argv: captured.append(
                    (path, argv))):
            exec(compile(signed_command[0], "<signed-profile-loader>", "exec"), {})
        return Path(runtime_root), captured

    def test_bootstrap_extracts_verified_files_with_private_modes_then_execs_gunicorn(self):
        profile = package.build_profile(2, "extract-run")
        container = profile["deployment_patch"]["containers"][0]
        command = container["entrypoint_overrides"]["cmd"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private-runtime"
            root, captured = self._run_bootstrap(command, root, {
                "PII_HOST": "127.0.0.1", "PII_PORT": "5055",
            })
            self.assertEqual(len(captured), 1)
            executable, argv = captured[0]
            self.assertEqual(executable, package.GUNICORN_PATH)
            self.assertEqual(argv, [
                package.GUNICORN_PATH,
                "--config", package.PRIVATE_CONFIG_PATH,
                "--chdir", package.APP_PATH,
                "--bind", "127.0.0.1:5055",
                "--worker-class", "gthread",
                "--workers", "2",
                "--timeout", "600",
                "--graceful-timeout", "30",
                "--access-logfile", "/dev/null",
                "--error-logfile", "-",
                "cloud_service:create_app()",
            ])
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            for name in package.ARCHIVE_FILES:
                target = root.joinpath(*name.split("/"))
                self.assertTrue(target.is_file())
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
                self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(),
                                 profile["archive_file_hashes"][name])
            self.assertFalse((root / "tools/verda_model_experiment/package.py").exists())
            self.assertFalse((root / "tools/verda_model_experiment/resources.py").exists())
            config = root / "gunicorn_config.py"
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            config_source = config.read_bytes()
            self.assertIn(b"load_gunicorn_config", config_source)
            compile(config_source, str(config), "exec")
            self.assertIn(str(root), sys.path)
            sys.path.remove(str(root))

    def test_bootstrap_exec_keeps_runtime_importable_outside_project_directory(self):
        profile = package.build_profile(2, "exec-import-run")
        command = profile["deployment_patch"]["containers"][0][
            "entrypoint_overrides"]["cmd"]
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            runtime_root = temporary_path / "private-runtime"
            working_directory = temporary_path / "unrelated"
            working_directory.mkdir()
            fake_gunicorn = temporary_path / "fake-gunicorn"
            fake_gunicorn.write_text(
                f"#!{sys.executable}\n"
                "import json,sys\n"
                "from tools.verda_model_experiment import runtime\n"
                "print(json.dumps({'runtime_file':runtime.__file__,'sys_path':sys.path}))\n",
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
                env={"PII_HOST": "127.0.0.1", "PII_PORT": "5005"},
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(
                Path(result["runtime_file"]).resolve(),
                (runtime_root / "tools/verda_model_experiment/runtime.py").resolve(),
            )
            self.assertIn(str(runtime_root), result["sys_path"])
            self.assertNotIn(str(Path(__file__).resolve().parents[1]), result["sys_path"])

    def test_bootstrap_rejects_encoded_archive_over_limit(self):
        compressed = io.BytesIO()
        with zipfile.ZipFile(compressed, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("payload.bin", bytes(range(256)) * 96)
        compressed_archive = compressed.getvalue()
        encoded_archive = base64.b64encode(compressed_archive)
        self.assertLess(len(compressed_archive), package.ARCHIVE_LIMIT_BYTES)
        self.assertGreater(len(encoded_archive), package.COMMAND_LIMIT_BYTES)
        with self.assertRaisesRegex(ValueError, "encoded runtime archive exceeds size limit"):
            package._bootstrap_script(
                compressed_archive,
                {name: "0" * 64 for name in package.ARCHIVE_FILES},
                1,
                "encoded-over-limit",
            )

    def test_bootstrap_and_payload_limits_are_enforced(self):
        archive, _ = package.build_archive()
        oversized_hashes = {"oversized": "x" * package.COMMAND_LIMIT_BYTES}
        with self.assertRaisesRegex(ValueError, "runtime bootstrap exceeds size limit"):
            package._bootstrap_script(archive, oversized_hashes, 1, "bootstrap-over-limit")
        with mock.patch.object(
            package, "_bootstrap_script", return_value="x" * package.COMMAND_LIMIT_BYTES
        ):
            with self.assertRaisesRegex(ValueError, "runtime payload exceeds size limit"):
                package.build_profile(1, "command-over-limit")

    def test_bootstrap_rejects_path_traversal_and_changed_archive_members(self):
        archive, hashes = package.build_archive()
        with zipfile.ZipFile(io.BytesIO(archive)) as original:
            members = {name: original.read(name) for name in package.ARCHIVE_FILES}
        malicious = io.BytesIO()
        with zipfile.ZipFile(malicious, "w", compression=zipfile.ZIP_LZMA) as bundle:
            for index, name in enumerate(package.ARCHIVE_FILES):
                safe_name = "../../escape.py" if index == 0 else name
                info = zipfile.ZipInfo(safe_name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_LZMA
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                bundle.writestr(info, members[name])
        script = package._bootstrap_script(malicious.getvalue(), hashes, 1, "safe-run")
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(SystemExit) as failure:
                self._run_bootstrap(
                    package.build_signed_command(script),
                    Path(temporary) / "private-runtime",
                )
            self.assertEqual(failure.exception.code, 70)
            self.assertFalse((Path(temporary) / "escape.py").exists())
        changed = dict(members)
        changed[package.ARCHIVE_FILES[0]] += b"tampered"
        bad_archive = io.BytesIO()
        with zipfile.ZipFile(bad_archive, "w", compression=zipfile.ZIP_LZMA) as bundle:
            for name in package.ARCHIVE_FILES:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_LZMA
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                bundle.writestr(info, changed[name])
        bad_script = package._bootstrap_script(bad_archive.getvalue(), hashes, 1,
                                               "safe-run")
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(SystemExit) as failure:
                self._run_bootstrap(
                    package.build_signed_command(bad_script),
                    Path(temporary) / "private-runtime",
                )
            self.assertEqual(failure.exception.code, 70)

    def test_bootstrap_refuses_preexisting_runtime_directory_with_unsafe_mode(self):
        profile = package.build_profile(1, "unsafe-root")
        container = profile["deployment_patch"]["containers"][0]
        command = container["entrypoint_overrides"]["cmd"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private-runtime"
            root.mkdir(mode=0o755)
            root.chmod(0o755)
            with self.assertRaises(SystemExit) as failure:
                self._run_bootstrap(command, root)
            self.assertEqual(failure.exception.code, 71)
            self.assertTrue(root.is_dir())
            self.assertEqual(root.stat().st_mode & 0o777, 0o755)

    def test_bootstrap_refuses_unsafe_bind_settings(self):
        profile = package.build_profile(1, "bind-run")
        container = profile["deployment_patch"]["containers"][0]
        command = container["entrypoint_overrides"]["cmd"]
        with tempfile.TemporaryDirectory() as temporary:
            runtime_root = Path(temporary) / "private-runtime"
            with self.assertRaises(SystemExit) as failure:
                self._run_bootstrap(command, runtime_root, {
                    "PII_HOST": "--bad-host", "PII_PORT": "5005",
                })
            self.assertEqual(failure.exception.code, 72)
            self.assertFalse((Path(temporary) / "private-runtime").exists())


if __name__ == "__main__":
    unittest.main()
