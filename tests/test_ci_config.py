"""Static contracts for CI, Renovate, ownership, and the agent quality baseline."""

import fnmatch
import json
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
RENOVATE = ROOT / ".github" / "renovate.json"
CODEOWNERS = ROOT / ".github" / "CODEOWNERS"
AGENTS = ROOT / "AGENTS.md"
GPU_REQUIREMENTS = ROOT / "src" / "app" / "requirements-gpu.txt"

MANAGERS = ("pip_requirements", "dockerfile", "docker-compose", "github-actions")
FULL_COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


def _read(path):
    return path.read_text(encoding="utf-8")


def _workflow():
    return _read(WORKFLOW)


def _workflow_name(path):
    match = re.search(r"(?m)^name: (.+)$", _read(path))
    if match is None:
        raise AssertionError(f"workflow name not found: {path}")
    return match.group(1).strip()


def _renovate():
    return json.loads(_read(RENOVATE))


def _codeowners_entries():
    entries = []
    for raw in _read(CODEOWNERS).splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        entries.append((parts[0], tuple(parts[1:])))
    return entries


def _pinned_action_refs(text, action):
    refs = re.findall(
        rf"(?m)^\s*(?:-\s+)?uses: {re.escape(action)}@(\S+)\s*$", text
    )
    if not refs:
        raise AssertionError(f"action is not used: {action}")
    if any(FULL_COMMIT_SHA.fullmatch(ref) is None for ref in refs):
        raise AssertionError(
            f"action must be pinned to a full commit SHA: {action} -> {refs}"
        )
    return refs


def _regex_matches(pattern, path):
    if len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/"):
        return re.search(pattern[1:-1], path) is not None
    return fnmatch.fnmatch(path, pattern)


def _step_run(text, step_name):
    lines = text.splitlines()
    marker = f"- name: {step_name}"
    start = None
    for index, line in enumerate(lines):
        if line.strip() == marker:
            start = index
            break
    if start is None:
        raise AssertionError(f"step not found: {step_name}")
    run_index = None
    for index in range(start + 1, len(lines)):
        if lines[index].strip() == "run: |":
            run_index = index
            break
    if run_index is None:
        raise AssertionError(f"run block not found: {step_name}")
    run_indent = len(lines[run_index]) - len(lines[run_index].lstrip())
    body = []
    for line in lines[run_index + 1:]:
        if not line.strip():
            body.append("")
            continue
        if len(line) - len(line.lstrip()) <= run_indent:
            break
        body.append(line)
    return textwrap.dedent("\n".join(body)).strip() + "\n"


def _install_python(text):
    run = _step_run(text, "Install light runtime dependencies")
    match = re.search(r"<<'PY'\n(.*?)\n\s*PY\b", run, re.DOTALL)
    if match is None:
        raise AssertionError("install heredoc not found")
    return textwrap.dedent(match.group(1)).strip() + "\n"


def _run_install(script, root, output):
    return subprocess.run(
        [sys.executable, "-", str(output)],
        input=script,
        text=True,
        cwd=root,
        capture_output=True,
    )


class TestsWorkflowContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = _workflow()

    def test_public_name_and_triggers_are_preserved(self):
        self.assertRegex(self.text, r"(?m)^name: tests$")
        on_block = re.search(r"(?ms)^on:\n(.*?)(?=^\S)", self.text)
        self.assertIsNotNone(on_block)
        block = on_block.group(1)
        self.assertRegex(block, r"(?m)^  push:$")
        self.assertRegex(block, r"(?m)^    branches: \[main\]$")
        self.assertRegex(block, r"(?m)^  pull_request:$")
        self.assertRegex(block, r"(?m)^  workflow_call:$")

    def test_permissions_are_read_only(self):
        self.assertRegex(self.text, r"(?m)^permissions:\n  contents: read$")
        self.assertNotRegex(
            self.text,
            r"(?m)^\s+(?:contents|packages|actions|checks|deployments|id-token):\s+write\s*$",
        )
        self.assertNotIn("secrets:", self.text)

    def test_timeout_allows_light_dependency_installation(self):
        self.assertRegex(self.text, r"(?m)^    timeout-minutes: 10$")

    def test_reusable_concurrency_is_scoped_to_caller_workflow_and_ref(self):
        match = re.search(
            r"(?ms)^concurrency:\n  group: (.+?)\n  cancel-in-progress: true$",
            self.text,
        )
        self.assertIsNotNone(match)
        template = match.group(1).strip()
        self.assertIn("${{ github.workflow }}", template)
        self.assertIn("${{ github.ref }}", template)

        def group(workflow, ref):
            return template.replace("${{ github.workflow }}", workflow).replace(
                "${{ github.ref }}", ref
            )

        release_path = ROOT / ".github" / "workflows" / "release.yml"
        self.assertIn(
            "uses: ./.github/workflows/tests.yml", _read(release_path)
        )
        standalone_name = _workflow_name(WORKFLOW)
        release_name = _workflow_name(release_path)
        self.assertNotEqual(release_name, standalone_name)

        main = "refs/heads/main"
        standalone = group(standalone_name, main)
        self.assertNotEqual(standalone, group(release_name, main))
        self.assertNotEqual(
            standalone, group(standalone_name, "refs/heads/feature")
        )
        self.assertEqual(standalone, group(standalone_name, main))

    def test_supported_python_matrix_is_preserved(self):
        match = re.search(r"(?m)^\s+python-version: \[([^\]]+)\]$", self.text)
        self.assertIsNotNone(match)
        versions = [item.strip().strip("\"'") for item in match.group(1).split(",")]
        self.assertEqual(versions, ["3.11", "3.13", "3.14"])

    def test_actions_are_pinned_and_checkout_fetches_the_exact_commit(self):
        _pinned_action_refs(self.text, "actions/checkout")
        _pinned_action_refs(self.text, "actions/setup-python")
        self.assertRegex(self.text, r"(?m)^\s+persist-credentials: false$")
        self.assertIn("ref: ${{ github.sha }}", self.text)

    def test_action_pin_contract_accepts_another_full_sha_and_rejects_mutable_refs(self):
        action = "actions/checkout"
        alternative = "0123456789abcdef0123456789abcdef01234567"
        self.assertEqual(
            _pinned_action_refs(f"uses: {action}@{alternative}", action),
            [alternative],
        )
        for ref in (
            "v7",
            "main",
            "latest",
            alternative[:12],
            alternative.upper(),
            "sha256:" + "a" * 64,
            "z" * 40,
        ):
            with self.subTest(ref=ref):
                with self.assertRaises(AssertionError):
                    _pinned_action_refs(f"uses: {action}@{ref}", action)
        with self.assertRaises(AssertionError):
            _pinned_action_refs(f"uses: evil/{action}@{alternative}", action)

    def test_install_step_uses_only_light_pins_from_gpu_requirements(self):
        self.assertIn("src/app/requirements-gpu.txt", self.text)
        self.assertIn('for package in ("flask", "pymupdf")', self.text)
        self.assertIn("--only-binary=:all:", self.text)
        self.assertIn("RUNNER_TEMP/test-requirements.txt", self.text)
        self.assertNotIn("torch==", self.text)
        self.assertNotIn("transformers==", self.text)
        self.assertNotIn("pip install -r src/app/requirements-gpu.txt", self.text)

    def test_full_suite_runs(self):
        self.assertIn("python -m unittest discover -v tests", self.text)

    def test_install_script_extracts_exact_light_pins(self):
        script = _install_python(self.text)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "app" / "requirements-gpu.txt"
            source.parent.mkdir(parents=True)
            source.write_text(
                "torch==9.9.9+cu130\nflask==3.1.3\npymupdf==1.28.2\n",
                encoding="utf-8",
            )
            output = root / "test-requirements.txt"
            result = _run_install(script, root, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                output.read_text(encoding="utf-8").splitlines(),
                ["flask==3.1.3", "pymupdf==1.28.2"],
            )

    def test_install_script_fails_closed_without_gpu_requirements(self):
        script = _install_python(self.text)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "test-requirements.txt"
            result = _run_install(script, root, output)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("src/app/requirements-gpu.txt", result.stderr)
            self.assertIn("missing", result.stderr)
            self.assertFalse(output.exists())

    def test_install_script_rejects_an_incomplete_pin_set(self):
        script = _install_python(self.text)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "app" / "requirements-gpu.txt"
            source.parent.mkdir(parents=True)
            source.write_text("flask==3.1.3\n", encoding="utf-8")
            output = root / "test-requirements.txt"
            result = _run_install(script, root, output)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must pin flask and pymupdf", result.stderr)
            self.assertFalse(output.exists())

    def test_repository_gpu_requirements_pin_the_light_dependencies(self):
        lines = [
            line.strip()
            for line in _read(GPU_REQUIREMENTS).splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        selected = [
            line
            for line in lines
            if line.startswith(("flask==", "pymupdf=="))
        ]
        self.assertEqual(len(selected), 2)


class RenovateContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = _renovate()

    def test_only_repository_managers_are_enabled(self):
        self.assertEqual(set(self.config["enabledManagers"]), set(MANAGERS))

    def test_schedule_is_the_weekly_rome_window(self):
        self.assertEqual(self.config["timezone"], "Europe/Rome")
        schedule = self.config["schedule"]
        self.assertEqual(len(schedule), 1)
        minute, hours, day_of_month, month, day_of_week = schedule[0].split()
        self.assertEqual((minute, day_of_month, month, day_of_week), ("*", "*", "*", "3"))
        self.assertRegex(hours, r"^11(?:-12|,12)$")

    def test_patch_updates_are_grouped_per_manager(self):
        rules = self.config["packageRules"]
        patch_rules = [
            rule for rule in rules if rule.get("matchUpdateTypes") == ["patch"]
        ]
        self.assertEqual(len(patch_rules), len(MANAGERS))
        by_manager = {
            rule["matchManagers"][0]: rule
            for rule in patch_rules
            if len(rule["matchManagers"]) == 1
        }
        self.assertEqual(set(by_manager), set(MANAGERS))
        self.assertEqual(len({rule["groupName"] for rule in patch_rules}), len(MANAGERS))
        self.assertEqual(len({rule["groupSlug"] for rule in patch_rules}), len(MANAGERS))

    def test_conventional_commits_match_the_managers(self):
        self.assertEqual(self.config["semanticCommits"], "enabled")
        semantic = {}
        for rule in self.config["packageRules"]:
            if "semanticCommitType" not in rule:
                continue
            for manager in rule.get("matchManagers", []):
                semantic[manager] = (
                    rule["semanticCommitType"],
                    rule.get("semanticCommitScope"),
                )
        for manager in ("pip_requirements", "dockerfile", "docker-compose"):
            self.assertEqual(semantic[manager], ("build", "packages"))
        self.assertEqual(semantic["github-actions"], ("ci", "github-actions"))

    def test_reviewers_and_automerge_are_locked_down(self):
        self.assertTrue(self.config["reviewersFromCodeOwners"])
        self.assertIs(self.config["automerge"], False)
        self.assertIs(self.config["platformAutomerge"], False)
        self.assertFalse(
            any(rule.get("automerge") is True for rule in self.config["packageRules"])
        )

    def test_manager_patterns_cover_every_actual_manifest(self):
        expected = {
            "pip_requirements": [
                "requirements.txt",
                "src/app/requirements-gpu.txt",
            ],
            "dockerfile": ["Dockerfile", "Dockerfile.gpu"],
            "docker-compose": ["docker-compose.yml"],
            "github-actions": [".github/workflows/tests.yml"],
        }
        for manager, paths in expected.items():
            patterns = self.config[manager]["managerFilePatterns"]
            for path in paths:
                self.assertTrue((ROOT / path).is_file(), path)
                self.assertTrue(
                    any(_regex_matches(pattern, path) for pattern in patterns),
                    (manager, path, patterns),
                )

    def test_coupled_torch_cuda_pin_is_not_rewritten(self):
        disabled = [
            rule for rule in self.config["packageRules"] if rule.get("enabled") is False
        ]
        self.assertTrue(
            any(
                rule.get("matchManagers") == ["pip_requirements"]
                and rule.get("matchFileNames") == ["src/app/requirements-gpu.txt"]
                and "torch" in rule.get("matchPackageNames", [])
                for rule in disabled
            )
        )

    def test_dependabot_is_not_introduced(self):
        self.assertFalse((ROOT / ".github" / "dependabot.yml").exists())
        self.assertFalse((ROOT / ".github" / "dependabot.yaml").exists())


class CodeownersContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = _codeowners_entries()
        cls.mapping = dict(cls.entries)

    def test_canonical_owners_are_preserved(self):
        self.assertEqual(self.mapping["*"], ("@lorenzocamporesi",))
        self.assertEqual(
            self.mapping["*.md"], ("@lucanori", "@lorenzocamporesi")
        )
        self.assertEqual(self.mapping[".github/**"], ("@lucanori",))
        self.assertEqual(self.mapping["Dockerfile"], ("@lucanori",))
        self.assertEqual(self.mapping["docker*"], ("@lucanori",))
        self.assertEqual(self.mapping[".docker*"], ("@lucanori",))
        self.assertEqual(self.mapping[".env*"], ("@lucanori",))
        self.assertEqual(self.mapping[".markdownlint*"], ("@lucanori",))
        self.assertEqual(self.mapping[".releaserc.json"], ("@lucanori",))
        self.assertEqual(self.mapping["docs/**"], ("@lucanori",))
        self.assertEqual(self.mapping["substrate/directives/**"], ("@lucanori",))
        self.assertEqual(self.mapping["substrate/expectations/**"], ("@lucanori",))

    def test_gpu_dockerfile_is_explicitly_owned(self):
        self.assertEqual(self.mapping["Dockerfile.gpu"], ("@lucanori",))

    def test_traces_remain_unowned(self):
        self.assertIn("substrate/traces/**", self.mapping)
        self.assertEqual(self.mapping["substrate/traces/**"], ())

    def test_only_verified_github_users_are_named(self):
        owners = {owner for _, owners in self.entries for owner in owners}
        self.assertEqual(owners, {"@lorenzocamporesi", "@lucanori"})


class AgentsBaselineContract(unittest.TestCase):
    def test_canonical_baseline_and_repository_specifics_are_present(self):
        text = _read(AGENTS)
        baseline = (
            "# Agents quality baseline",
            "## Delta tests",
            "- Map every behavior change to at least one test and run those tests, plus anything upstream they exercise.",
            "## File length",
            "## Code comments",
            "- Never write code comments.",
            "- If code seems to need a comment, simplify it or split it into smaller files instead.",
        )
        for line in baseline:
            self.assertIn(line, text)
        self.assertIn("## Repository specifics", text)
        self.assertIn("`python -m unittest discover -v tests`", text)
        self.assertIn("src/app/requirements-gpu.txt", text)
        self.assertIn("80 percent", text)
        self.assertGreater(
            text.index("## Repository specifics"),
            text.index("- Never write code comments."),
        )


if __name__ == "__main__":
    unittest.main()
