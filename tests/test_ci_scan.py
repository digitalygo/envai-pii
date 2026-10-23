from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import scan_gate as gate

DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "c" * 64
CONFIG_DIGEST = "sha256:" + "b" * 64
OTHER_CONFIG_DIGEST = "sha256:" + "d" * 64
REPO = "ghcr.io/digitalygo/envai-pii"
ARTIFACT = f"{REPO}@{DIGEST}"
OTHER_REPO_ARTIFACT = f"ghcr.io/digitalygo/other@{DIGEST}"
TRIVY_REPO = "ghcr.io/aquasecurity/trivy"
TRIVY_PIN = re.compile(
    rf"{re.escape(TRIVY_REPO)}:\d+\.\d+\.\d+@sha256:[0-9a-f]{{64}}"
)


def trivy_image_refs(text: str) -> list[str]:
    refs = re.findall(rf"{re.escape(TRIVY_REPO)}[^\s\\]*", text)
    if not refs:
        raise AssertionError("the official Trivy image is not used")
    if any(TRIVY_PIN.fullmatch(ref) is None for ref in refs):
        raise AssertionError(
            "the Trivy image must use a semver tag and a full sha256 digest"
        )
    return refs


def report(
    results: list[object],
    artifact: str = ARTIFACT,
    image_id: str = CONFIG_DIGEST,
    **overrides,
) -> dict:
    payload = {
        "SchemaVersion": 2,
        "CreatedAt": "2026-10-22T12:00:00Z",
        "ArtifactName": artifact,
        "ArtifactType": "container_image",
        "Metadata": {
            "OS": {"Family": "debian", "Name": "12"},
            "ImageID": image_id,
            "RepoTags": [],
            "RepoDigests": [artifact],
            "ImageConfig": {"architecture": "amd64", "os": "linux"},
        },
        "Results": results,
    }
    payload.update(overrides)
    return payload


def vuln(severity: str, fixed: str | None = None) -> dict:
    entry = {
        "VulnerabilityID": "CVE-2026-0001",
        "PkgName": "libfoo",
        "InstalledVersion": "1.0",
        "Severity": severity,
    }
    if fixed is not None:
        entry["FixedVersion"] = fixed
    return entry


class TestScanReport(unittest.TestCase):
    def evaluate(self, payload: dict, artifact: str = ARTIFACT, image_id: str = CONFIG_DIGEST):
        return gate.evaluate_scan_report(payload, artifact, image_id)

    def test_clean_report_passes(self):
        result = self.evaluate(report([]))
        self.assertEqual(result["decision"], "pass")
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["ignored"], 0)

    def test_fixable_high_and_critical_block(self):
        for severity in ("HIGH", "CRITICAL"):
            with self.subTest(severity=severity):
                result = self.evaluate(
                    report(
                        [
                            {
                                "Class": "os-pkgs",
                                "Vulnerabilities": [vuln(severity, "1.1")],
                            }
                        ]
                    )
                )
                self.assertEqual(result["decision"], "fail")
                self.assertEqual(len(result["blockers"]), 1)

    def test_unfixed_high_and_critical_are_ignored(self):
        for severity in ("HIGH", "CRITICAL"):
            with self.subTest(severity=severity):
                result = self.evaluate(
                    report(
                        [
                            {
                                "Class": "os-pkgs",
                                "Vulnerabilities": [vuln(severity)],
                            }
                        ]
                    )
                )
                self.assertEqual(result["decision"], "pass")
                self.assertEqual(result["ignored"], 1)

    def test_low_medium_and_unknown_never_block(self):
        result = self.evaluate(
            report(
                [
                    {
                        "Class": "os-pkgs",
                        "Vulnerabilities": [
                            vuln("LOW", "1.1"),
                            vuln("MEDIUM", "1.1"),
                            vuln("UNKNOWN"),
                        ],
                    }
                ]
            )
        )
        self.assertEqual(result["decision"], "pass")
        self.assertEqual(result["ignored"], 0)

    def test_any_secret_finding_blocks(self):
        for result_class in ("secret", "config"):
            with self.subTest(result_class=result_class):
                result = self.evaluate(
                    report(
                        [
                            {
                                "Class": result_class,
                                "Secrets": [
                                    {"RuleID": "private-key", "Match": "redacted"},
                                    {"RuleID": "aws-access-key-id"},
                                ],
                            }
                        ]
                    )
                )
                self.assertEqual(result["decision"], "fail")
                self.assertEqual(len(result["blockers"]), 2)
                self.assertNotIn("redacted", " ".join(result["blockers"]))

    def test_secret_plus_unfixed_vulnerability_still_blocks(self):
        result = self.evaluate(
            report(
                [
                    {"Class": "secret", "Secrets": [{"RuleID": "private-key"}]},
                    {"Class": "os-pkgs", "Vulnerabilities": [vuln("HIGH")]},
                ]
            )
        )
        self.assertEqual(result["decision"], "fail")
        self.assertEqual(len(result["blockers"]), 1)
        self.assertEqual(result["ignored"], 1)

    def test_mixed_fixable_and_unfixed_counts(self):
        result = self.evaluate(
            report(
                [
                    {
                        "Class": "os-pkgs",
                        "Vulnerabilities": [
                            vuln("HIGH", "1.1"),
                            vuln("CRITICAL"),
                        ],
                    }
                ]
            )
        )
        self.assertEqual(result["decision"], "fail")
        self.assertEqual(len(result["blockers"]), 1)
        self.assertEqual(result["ignored"], 1)

    def test_empty_fixed_version_is_unfixed(self):
        result = self.evaluate(
            report(
                [
                    {
                        "Class": "os-pkgs",
                        "Vulnerabilities": [vuln("HIGH", "   ")],
                    }
                ]
            )
        )
        self.assertEqual(result["decision"], "pass")
        self.assertEqual(result["ignored"], 1)

    def test_report_binding_failures(self):
        cases = [
            report([], artifact=f"ghcr.io/digitalygo/envai-pii@{OTHER_DIGEST}"),
            report([], artifact=OTHER_REPO_ARTIFACT),
            report([], image_id=OTHER_CONFIG_DIGEST),
            report([], SchemaVersion=1),
            report([], ArtifactType="filesystem"),
            report([], Metadata={}),
            report([], Metadata={"ImageID": CONFIG_DIGEST, "RepoDigests": [], "ImageConfig": {"architecture": "amd64", "os": "linux"}}),
            report([], Metadata={"ImageID": CONFIG_DIGEST, "RepoDigests": [OTHER_REPO_ARTIFACT], "ImageConfig": {"architecture": "amd64", "os": "linux"}}),
            report([], Metadata={"ImageID": CONFIG_DIGEST, "RepoDigests": [ARTIFACT], "ImageConfig": {"architecture": "arm64", "os": "linux"}}),
            report([], Metadata={"RepoDigests": [ARTIFACT], "ImageConfig": {"architecture": "amd64", "os": "linux"}}),
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(SystemExit):
                    self.evaluate(payload)

    def test_artifact_reference_must_be_canonical(self):
        for artifact in (
            "ghcr.io/x",
            "GHCR.IO/digitalygo/envai-pii@" + DIGEST,
            "ghcr.io/digitalygo/envai-pii:tag",
            f"ghcr.io/digitalygo/envai-pii@{DIGEST}\n",
        ):
            with self.subTest(artifact=artifact):
                with self.assertRaises(SystemExit):
                    self.evaluate(report([]), artifact=artifact)

    def test_image_id_must_be_a_digest(self):
        for image_id in ("", "sha256:xyz", CONFIG_DIGEST.upper()):
            with self.subTest(image_id=image_id):
                with self.assertRaises(SystemExit):
                    self.evaluate(report([]), image_id=image_id)

    def test_result_validation_failures(self):
        cases = [
            [42],
            [{"Vulnerabilities": []}],
            [{"Class": "alien", "Vulnerabilities": []}],
            [{"Class": "secret", "Secrets": "not-a-list"}],
            [{"Class": "secret", "Secrets": [{"Match": "redacted"}]}],
            [{"Class": "secret", "Secrets": [42]}],
            [{"Class": "os-pkgs", "Vulnerabilities": "not-a-list"}],
            [{"Class": "os-pkgs", "Vulnerabilities": [{"Severity": "HIGH"}]}],
            [{"Class": "os-pkgs", "Vulnerabilities": [{"VulnerabilityID": "CVE-1", "Severity": "huge"}]}],
            [{"Class": "os-pkgs", "Vulnerabilities": [vuln("HIGH") | {"FixedVersion": ["1.1"]}]}],
            [{"Class": "os-pkgs", "Vulnerabilities": [42]}],
        ]
        for results in cases:
            with self.subTest(results=results):
                with self.assertRaises(SystemExit):
                    self.evaluate(report(results))

    def test_missing_or_malformed_results_fails(self):
        for payload in (
            {**report([]), "Results": None},
            {key: value for key, value in report([]).items() if key != "Results"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(SystemExit):
                    self.evaluate(payload)

    def test_load_scan_report_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trivy.json"
            with self.assertRaises(SystemExit):
                gate.load_scan_report(str(path))
            path.write_text("", encoding="utf-8")
            with self.assertRaises(SystemExit):
                gate.load_scan_report(str(path))
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(SystemExit):
                gate.load_scan_report(str(path))
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(SystemExit):
                gate.load_scan_report(str(path))
            path.write_text('{"SchemaVersion": 2}', encoding="utf-8")
            with self.assertRaises(SystemExit):
                gate.load_scan_report(str(path))

    def test_evaluate_cli_passes_and_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trivy.json"
            output = Path(tmp) / "output"
            path.write_text(json.dumps(report([])), encoding="utf-8")
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                parser = gate.build_parser()
                args = parser.parse_args(
                    [
                        "evaluate",
                        "--trivy",
                        str(path),
                        "--artifact",
                        ARTIFACT,
                        "--image-id",
                        CONFIG_DIGEST,
                    ]
                )
                args.func(args)
            text = output.read_text(encoding="utf-8")
            self.assertIn("decision=pass", text)
            self.assertIn("blockers=0", text)

    def test_evaluate_cli_fails_on_a_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trivy.json"
            path.write_text(
                json.dumps(
                    report(
                        [
                            {
                                "Class": "secret",
                                "Secrets": [{"RuleID": "private-key"}],
                            }
                        ]
                    )
                ),
                encoding="utf-8",
            )
            parser = gate.build_parser()
            args = parser.parse_args(
                [
                    "evaluate",
                    "--trivy",
                    str(path),
                    "--artifact",
                    ARTIFACT,
                    "--image-id",
                    CONFIG_DIGEST,
                ]
            )
            with self.assertRaises(SystemExit):
                args.func(args)


class TestScanWorkflowContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (ROOT / ".github" / "workflows" / "docker-publish.yml").read_text(
            encoding="utf-8"
        )
        cls.publish = cls.raw.split("\n  publish:", 1)[1].split("\n  notify:", 1)[0]

    def test_scan_uses_the_pinned_trivy_image_and_remote_source(self):
        refs = trivy_image_refs(self.publish)
        self.assertEqual(len(refs), 1)
        self.assertIn("--image-src remote", self.publish)
        self.assertIn("--scanners vuln,secret", self.publish)
        self.assertIn("--exit-code 0", self.publish)
        self.assertIn("--format json", self.publish)

    def test_trivy_pin_contract_accepts_another_semver_and_digest_but_rejects_mutable_refs(self):
        alternative = f"{TRIVY_REPO}:1.2.3@sha256:" + "f" * 64
        self.assertEqual(trivy_image_refs(f"image: {alternative}"), [alternative])
        for ref in (
            f"{TRIVY_REPO}:latest",
            f"{TRIVY_REPO}:0.76",
            f"{TRIVY_REPO}:0.76.1",
            f"{TRIVY_REPO}:0.76.1@sha256:" + "a" * 63,
            f"{TRIVY_REPO}:0.76.1@sha256:" + "A" * 64,
            "ghcr.io/other/trivy:1.2.3@sha256:" + "f" * 64,
        ):
            with self.subTest(ref=ref):
                with self.assertRaises(AssertionError):
                    trivy_image_refs(f"image: {ref}")

    def test_scan_scans_the_exact_digest(self):
        self.assertIn('"${IMAGE_REF}@${DIGEST}"', self.publish)
        self.assertIn("--image-id \"$IMAGE_ID\"", self.publish)

    def test_no_severity_filter_can_hide_secrets(self):
        self.assertNotIn("--severity", self.publish)
        self.assertNotIn("--ignore-unfixed", self.publish)
        self.assertNotIn("--ignore-secret", self.publish)

    def test_scan_credentials_are_environment_only(self):
        self.assertIn("TRIVY_USERNAME: ${{ github.actor }}", self.publish)
        self.assertIn("TRIVY_PASSWORD: ${{ github.token }}", self.publish)
        self.assertIn("-e TRIVY_USERNAME", self.publish)
        self.assertIn("-e TRIVY_PASSWORD", self.publish)
        self.assertNotIn("TRIVY_PASSWORD=", self.publish)
        self.assertNotIn("PII_API_TOKEN", self.raw)

    def test_scan_is_bounded_and_does_not_mount_the_docker_socket(self):
        self.assertIn("--memory 4g", self.publish)
        self.assertIn("--cpus 2", self.publish)
        self.assertIn('--user "$(id -u):$(id -g)"', self.publish)
        self.assertNotIn("/var/run/docker.sock", self.publish)

    def test_report_lives_in_runner_temp_and_is_deleted(self):
        self.assertIn("$RUNNER_TEMP/trivy/out/trivy.json", self.publish)
        self.assertIn('-v "$RUNNER_TEMP/trivy/out:/out"', self.publish)
        self.assertIn("Delete the scan report", self.publish)
        self.assertIn('rm -rf "$RUNNER_TEMP/trivy"', self.publish)
        self.assertNotIn("upload-artifact", self.publish)
        self.assertNotIn("trivy.json", self.publish.split("Delete the scan report", 1)[1])

    def test_scan_cli_failures_stop_before_any_tag(self):
        scan_step = self.publish.split("Scan the remote digest with Trivy", 1)[1]
        scan_step = scan_step.split("Evaluate the scan gate", 1)[0]
        self.assertNotIn("continue-on-error", scan_step)
        self.assertIn("set -euo pipefail", scan_step)
        gate_index = self.publish.index("scan_gate.py evaluate")
        create_index = self.publish.index("imagetools create")
        self.assertLess(gate_index, create_index)

    def test_gate_report_is_not_printed(self):
        gate_step = self.publish.split("Evaluate the scan gate", 1)[1]
        gate_step = gate_step.split("Delete the scan report", 1)[0]
        self.assertNotIn("cat ", gate_step)
        self.assertNotIn("trivy.json", gate_step.replace("$RUNNER_TEMP/trivy/out/trivy.json", ""))

    def test_tags_are_only_created_after_the_scan_gate(self):
        self.assertIn("Preflight tag conflicts", self.publish)
        self.assertIn("Promote the scanned digest", self.publish)
        self.assertIn("Verify the tags resolve to the scanned digest", self.publish)
        gate_index = self.publish.index("scan_gate.py evaluate")
        preflight_index = self.publish.index("registry_publish.py preflight")
        create_index = self.publish.index("imagetools create")
        self.assertLess(gate_index, preflight_index)
        self.assertLess(preflight_index, create_index)


if __name__ == "__main__":
    unittest.main()
