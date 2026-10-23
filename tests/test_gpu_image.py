# -*- coding: utf-8 -*-
"""Static contracts for the GPU image (Dockerfile.gpu and its requirements).

These tests do not build the image or import cloud_service: the GPU runtime
behavior belongs to the integration suite. They pin the properties that are
cheap to verify before a multi-gigabyte build: base provenance, dependency
pins, Gunicorn mode, model path, offline runtime, non-root user, healthcheck
and the absence of build-time secrets or an SSH daemon.
"""

import json
import re
import shlex
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile.gpu"
REQUIREMENTS = ROOT / "src" / "app" / "requirements-gpu.txt"


def _logical_lines(text):
    """Join Dockerfile continuations so one instruction is one line."""
    joined = re.sub(r"\\\s*\n", " ", text)
    return [line.strip() for line in joined.splitlines() if line.strip()]


def _parse_env(instructions):
    env = {}
    for line in instructions:
        if not line.startswith("ENV "):
            continue
        for token in shlex.split(line[4:]):
            key, separator, value = token.partition("=")
            if separator:
                env[key] = value
    return env


def _parse_args(instructions):
    args = {}
    for line in instructions:
        if not line.startswith("ARG "):
            continue
        key, separator, value = line[4:].partition("=")
        if separator:
            args[key] = value
    return args


class GpuImageContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DOCKERFILE.read_text(encoding="utf-8")
        cls.logical = _logical_lines(cls.text)
        cls.instructions = [line for line in cls.logical if not line.startswith("#")]
        cls.instruction_text = "\n".join(cls.instructions)
        cls.run_lines = [line for line in cls.instructions if line.startswith("RUN ")]
        cls.env = _parse_env(cls.instructions)
        cls.args = _parse_args(cls.instructions)

    def test_base_is_digest_pinned_python_311_bookworm(self):
        match = re.search(r"^FROM\s+(\S+)", self.text, re.MULTILINE)
        self.assertIsNotNone(match, "Dockerfile.gpu has no FROM instruction")
        image = match.group(1)
        self.assertRegex(
            image,
            r"^python:3\.11\.17-slim-bookworm@sha256:[0-9a-f]{64}$",
        )
        digest = image.rsplit("@sha256:", 1)[1]
        self.assertNotEqual(digest, "0" * 64, "placeholder digest")

    def test_requirements_are_exact_pinned_without_vision_or_audio(self):
        lines = [
            line.strip()
            for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertTrue(lines, "requirements-gpu.txt is empty")
        for line in lines:
            self.assertRegex(line, r"^[A-Za-z0-9_.-]+==[0-9][A-Za-z0-9.+!-]*$",
                             f"not an exact pin: {line}")

        pins = dict(line.split("==", 1) for line in lines)
        self.assertEqual(pins["torch"], "2.13.0+cu130")
        self.assertEqual(pins["transformers"], "5.14.1")
        self.assertEqual(pins["flask"], "3.1.3")
        self.assertEqual(pins["pymupdf"], "1.28.2")
        self.assertEqual(pins["gunicorn"], "26.2.0")
        self.assertNotIn("torchvision", pins)
        self.assertNotIn("torchaudio", pins)

    def test_install_uses_separate_cuda_and_pypi_indexes(self):
        run_text = "\n".join(self.run_lines)
        torch_index = run_text.index("https://download.pytorch.org/whl/cu130")
        pypi_index = run_text.index("https://pypi.org/simple")
        self.assertLess(torch_index, pypi_index)
        self.assertIn("--no-deps", run_text[:pypi_index])
        self.assertIn('"torch==2.13.0+cu130"', run_text[:pypi_index])
        self.assertIn("-r /tmp/requirements-gpu.txt", run_text[pypi_index:])
        self.assertIn("pip check", run_text)
        self.assertNotIn("--extra-index-url", run_text)

    def test_gunicorn_single_worker_four_threads_factory_without_preload(self):
        commands = [line for line in self.instructions if line.startswith("CMD ")]
        self.assertEqual(len(commands), 1)
        command = commands[0]
        docker_command = json.loads(command.removeprefix("CMD "))
        self.assertEqual(docker_command[:2], ["sh", "-c"])
        self.assertIn('--bind "${PII_HOST}:${PII_PORT}"', docker_command[2])
        self.assertIn("exec gunicorn", command)
        self.assertIn("cloud_service:create_app()", command)
        self.assertIn("--worker-class gthread", command)
        self.assertRegex(command, r"--workers\s+1(?:\s|$)")
        self.assertRegex(command, r"--threads\s+4(?:\s|$)")
        self.assertRegex(command, r"--timeout\s+600(?:\s|$)")
        self.assertRegex(command, r"--graceful-timeout\s+30(?:\s|$)")
        self.assertIn("${PII_HOST}:${PII_PORT}", command)
        self.assertNotIn("--preload", command)

    def test_access_logs_are_discarded_and_errors_go_to_stderr(self):
        self.assertIn("--access-logfile /dev/null", self.instruction_text)
        self.assertIn("--error-logfile -", self.instruction_text)

    def test_runtime_env_binds_all_interfaces_and_forces_offline_mode(self):
        expected = {
            "PII_HOST": "0.0.0.0",
            "PII_PORT": "5005",
            "PII_MODEL_DIR": "/app/models/rizzo-pii-0.3B-v1.5.0",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": "/home/app",
        }
        for key, value in expected.items():
            self.assertEqual(self.env.get(key), value, key)

    def test_model_snapshot_is_fixed_and_reads_build_args_from_environment(self):
        self.assertEqual(self.args.get("MODEL_REPO"), "rizzoaiacademy/rizzo-pii-0.3B")
        self.assertEqual(self.args.get("MODEL_REVISION"), "v1.5.0")

        model_runs = [line for line in self.run_lines if "snapshot_download" in line]
        self.assertEqual(len(model_runs), 1)
        model_run = model_runs[0]
        for key in ("MODEL_REPO", "MODEL_REVISION", "MODEL_DIR"):
            self.assertIn(f"os.environ['{key}']", model_run)
        self.assertIn("local_dir=os.environ['MODEL_DIR']", model_run)
        self.assertIn("allow_patterns", model_run)

        python_code = model_run.split("python -c", 1)[1]
        self.assertNotIn("$MODEL_REPO", python_code)
        self.assertNotIn("$MODEL_REVISION", python_code)
        self.assertNotIn("$MODEL_DIR", python_code)

    def test_build_verifies_cuda_build_and_model_snapshot_without_gpu_probe(self):
        run_text = "\n".join(self.run_lines)
        self.assertIn("config.json", run_text)
        self.assertIn("torch.version.cuda", run_text)
        self.assertIn("startswith('13.')", run_text)
        self.assertNotIn("torch.cuda.is_available", self.instruction_text)
        self.assertNotIn("cloud_service", run_text)

    def test_runs_as_uid_10001_without_chowning_the_model_layer(self):
        user_lines = [line for line in self.instructions if line.startswith("USER ")]
        self.assertEqual(user_lines, ["USER app"])
        self.assertIn("--create-home", self.instruction_text)
        self.assertIn("--uid 10001", self.instruction_text)
        self.assertTrue(any(line.startswith("COPY --chown=app:app src/app/*.py ")
                            for line in self.instructions))
        self.assertIsNone(
            re.search(r"chown\s+-R\s+app:app\s+/app(?:\s|$)", self.text),
            "do not recursively chown the model layer",
        )
        self.assertIsNone(
            re.search(r"chown[^\n]*(?:PII_MODEL_DIR|/app/models)", self.text),
            "the model must stay root-owned and readable",
        )

    def test_no_ssh_daemon_and_only_the_service_port_is_exposed(self):
        instruction_lower = self.instruction_text.lower()
        self.assertNotIn("openssh-server", instruction_lower)
        self.assertNotRegex(instruction_lower, r"\bsshd\b")
        self.assertNotIn("expose 22", instruction_lower)

        exposed = [
            line.split()[1]
            for line in self.instructions
            if line.startswith("EXPOSE ")
        ]
        self.assertEqual(exposed, ["5005"])

    def test_healthcheck_is_stdlib_only_and_requires_cuda(self):
        checks = [line for line in self.instructions if line.startswith("HEALTHCHECK ")]
        self.assertEqual(len(checks), 1)
        check = checks[0]
        self.assertIn("--interval=30s", check)
        self.assertIn("--timeout=5s", check)
        self.assertIn("--start-period=120s", check)
        self.assertIn("--retries=3", check)
        self.assertIn("urllib.request", check)
        self.assertIn("/health", check)
        self.assertIn("json.load", check)
        self.assertIn("r.status == 200", check)
        self.assertIn("p.get('model_loaded') is True", check)
        self.assertIn("'device'", check)
        self.assertIn("'cuda'", check)
        self.assertNotIn("curl", check)
        self.assertNotIn("wget", check)

    def test_no_build_secret_or_dotenv_copy(self):
        for line in self.instructions:
            if line.startswith(("ARG ", "ENV ")):
                self.assertNotIn("PII_API_TOKEN", line)
            if line.startswith(("COPY ", "ADD ")):
                self.assertNotIn(".env", line)

    def test_build_context_is_repository_root_with_explicit_app_copies(self):
        self.assertIn(
            "podman build --platform linux/amd64 -f Dockerfile.gpu -t envai-pii:gpu .",
            self.text,
        )
        self.assertIn(
            "COPY src/app/requirements-gpu.txt /tmp/requirements-gpu.txt",
            self.instructions,
        )
        self.assertTrue(any(line.startswith(
            "COPY --chown=app:app src/app/*.py /app/src/app/"
        ) for line in self.instructions))
        self.assertFalse(any(re.match(r"COPY\s+\.\s", line) for line in self.instructions))
        self.assertFalse(any(line.startswith("COPY src/app/ ") for line in self.instructions))


if __name__ == "__main__":
    unittest.main()
