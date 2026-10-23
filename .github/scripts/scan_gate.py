from __future__ import annotations

import argparse
import json
import os
import re
import sys

BLOCKING_SEVERITIES = {"HIGH", "CRITICAL"}
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REF_RE = re.compile(
    r"^(?P<repository>[a-z0-9][a-z0-9.-]*(?::[0-9]+)?/[a-z0-9][a-z0-9._/-]*)"
    r"@(?P<digest>sha256:[0-9a-f]{64})$"
)
RESULT_CLASSES = {"os-pkgs", "lang-pkgs", "config", "secret", "license"}
CONTAINER_IMAGE_TYPE = "container_image"
SCHEMA_VERSION = 2
AMD64_ARCH = "amd64"
LINUX_OS = "linux"


def fail(message: str) -> None:
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(message)


def emit_outputs(outputs: list[tuple[str, str]]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as handle:
        for key, value in outputs:
            if "\n" in value:
                handle.write(f"{key}<<GH_OUT\n{value}\nGH_OUT\n")
            else:
                handle.write(f"{key}={value}\n")


def parse_expected_ref(expected_ref: str) -> tuple[str, str]:
    match = REF_RE.fullmatch(expected_ref)
    if match is None:
        fail(
            "expected artifact must be a canonical lowercase "
            f"repository@digest reference: {expected_ref!r}"
        )
    return match.group("repository"), match.group("digest")


def validate_image_id(image_id: str) -> str:
    if not isinstance(image_id, str) or not DIGEST_RE.fullmatch(image_id):
        fail(f"expected image config digest is malformed: {image_id!r}")
    return image_id


def validate_report_identity(
    report: dict, repository: str, digest: str, image_id: str
) -> None:
    schema_version = report.get("SchemaVersion")
    if schema_version != SCHEMA_VERSION:
        fail(f"scan report has an unsupported schema version: {schema_version!r}")
    expected_ref = f"{repository}@{digest}"
    artifact_name = report.get("ArtifactName")
    if not isinstance(artifact_name, str) or artifact_name != expected_ref:
        fail(
            f"scan report does not match the expected artifact {expected_ref!r}: "
            f"{artifact_name!r}"
        )
    artifact_type = report.get("ArtifactType")
    if artifact_type != CONTAINER_IMAGE_TYPE:
        fail(f"scan report was not produced against a container image: {artifact_type!r}")
    metadata = report.get("Metadata")
    if not isinstance(metadata, dict):
        fail("scan report has no scan metadata")
    report_image_id = metadata.get("ImageID")
    if report_image_id != image_id:
        fail(
            f"scan report image identifier {report_image_id!r} does not match "
            f"the remote config digest {image_id!r}"
        )
    repo_digests = metadata.get("RepoDigests")
    if not isinstance(repo_digests, list) or not repo_digests:
        fail("scan report metadata has no repository digests")
    for entry in repo_digests:
        if not isinstance(entry, str) or entry != expected_ref:
            fail(f"scan report covers a foreign reference: {entry!r}")
    image_config = metadata.get("ImageConfig")
    if not isinstance(image_config, dict):
        fail("scan report metadata has no image configuration")
    architecture = image_config.get("architecture")
    operating_system = image_config.get("os")
    if architecture != AMD64_ARCH or operating_system != LINUX_OS:
        fail(
            f"scan report covers the wrong platform: "
            f"{operating_system}/{architecture}, expected linux/amd64"
        )


def validate_vulnerability(vuln: object) -> dict:
    if not isinstance(vuln, dict):
        fail("scan report contains a malformed vulnerability entry")
    if not isinstance(vuln.get("VulnerabilityID"), str) or not vuln["VulnerabilityID"]:
        fail("scan report contains a vulnerability without an identifier")
    if vuln.get("Severity") not in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
        fail(
            "scan report contains a vulnerability with a malformed severity: "
            f"{vuln.get('Severity')!r}"
        )
    fixed_version = vuln.get("FixedVersion")
    if fixed_version is not None and not isinstance(fixed_version, str):
        fail("scan report contains a vulnerability with a malformed fixed version")
    return vuln


def validate_secret(secret: object) -> dict:
    if not isinstance(secret, dict):
        fail("scan report contains a malformed secret entry")
    if not isinstance(secret.get("RuleID"), str) or not secret["RuleID"]:
        fail("scan report contains a secret without a rule identifier")
    return secret


def evaluate_scan_report(report: dict, expected_ref: str, image_id: str) -> dict[str, object]:
    if not isinstance(report, dict):
        fail("scan report JSON must be an object")
    if not isinstance(report.get("Results"), list):
        fail("scan report is incomplete: Results is missing or not a list")
    repository, digest = parse_expected_ref(expected_ref)
    validate_image_id(image_id)
    validate_report_identity(report, repository, digest, image_id)

    blockers: list[str] = []
    ignored = 0
    for result in report["Results"]:
        if not isinstance(result, dict):
            fail("scan report contains a malformed result entry")
        result_class = result.get("Class")
        if result_class not in RESULT_CLASSES:
            fail(f"scan report contains a result with an unknown class: {result_class!r}")
        secrets = result.get("Secrets")
        if secrets is not None:
            if not isinstance(secrets, list):
                fail("scan report contains a malformed secret result")
            for secret in secrets:
                validate_secret(secret)
            blockers.extend(f"secret {secret['RuleID']}" for secret in secrets)
        vulnerabilities = result.get("Vulnerabilities")
        if vulnerabilities is None:
            continue
        if not isinstance(vulnerabilities, list):
            fail("scan report contains a malformed vulnerability result")
        for vuln in vulnerabilities:
            validated = validate_vulnerability(vuln)
            severity = validated["Severity"]
            if severity not in BLOCKING_SEVERITIES:
                continue
            fixed_version = validated.get("FixedVersion")
            if isinstance(fixed_version, str) and fixed_version.strip():
                blockers.append(
                    f"{validated['VulnerabilityID']} {severity} fix {fixed_version}"
                )
            else:
                ignored += 1
    return {"decision": "fail" if blockers else "pass", "blockers": blockers, "ignored": ignored}


def load_scan_report(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
    except OSError as exc:
        fail(f"cannot read scan report {path}: {exc}")
    if not raw.strip():
        fail("empty scan report: the scan did not complete")
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"scan report is not valid JSON: {exc}")
    if not isinstance(report, dict):
        fail("scan report JSON must be an object")
    if not isinstance(report.get("Results"), list):
        fail("scan report is incomplete: Results is missing or not a list")
    return report


def command_evaluate(args: argparse.Namespace) -> None:
    report = load_scan_report(args.trivy)
    result = evaluate_scan_report(report, args.artifact, args.image_id)
    blockers = result["blockers"]
    ignored = result["ignored"]
    emit_outputs(
        [
            ("decision", str(result["decision"])),
            ("blockers", str(len(blockers))),
            ("ignored", str(ignored)),
        ]
    )
    if result["decision"] == "fail":
        fail(f"scan gate blocked by {len(blockers)} finding(s): {', '.join(blockers)}")
    print(f"scan gate passed: {len(blockers)} blocker(s), {ignored} unfixed ignored")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Decide whether a Trivy scan of the published digest may tag the image"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    evaluate = subparsers.add_parser("evaluate", help="Evaluate a Trivy JSON report")
    evaluate.add_argument("--trivy", required=True)
    evaluate.add_argument("--artifact", required=True)
    evaluate.add_argument("--image-id", required=True)
    evaluate.set_defaults(func=command_evaluate)

    return parser


if __name__ == "__main__":
    parser = build_parser()
    arguments = parser.parse_args()
    arguments.func(arguments)
