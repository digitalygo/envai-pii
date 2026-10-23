from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import registry_publish as publish

SHA = "ab" * 20
OTHER_SHA = "cd" * 20
DIGEST = "sha256:" + "1" * 64
OTHER_DIGEST = "sha256:" + "2" * 64
CONFIG_DIGEST = "sha256:" + "3" * 64
IMAGE = "ghcr.io/digitalygo/envai-pii"
PLAIN_MEDIA_TYPE = "application/vnd.docker.distribution.manifest.v2+json"
INDEX_MEDIA_TYPE = "application/vnd.oci.image.index.v1+json"
FULL_COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


def pinned_action_refs(text: str, action: str) -> list[str]:
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


def write(path: Path, data: str | bytes) -> None:
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")


def metadata(digest: str = DIGEST) -> dict:
    return {
        "containerimage.digest": digest,
        "containerimage.descriptor": {
            "mediaType": PLAIN_MEDIA_TYPE,
            "digest": digest,
            "size": 512,
            "platform": {"architecture": "amd64", "os": "linux"},
        },
    }


def remote_manifest(config_digest: str = CONFIG_DIGEST) -> dict:
    return {
        "schemaVersion": 2,
        "mediaType": PLAIN_MEDIA_TYPE,
        "config": {
            "mediaType": "application/vnd.docker.container.image.v1+json",
            "digest": config_digest,
            "size": 12,
        },
        "layers": [],
    }


def write_inspection(
    directory: Path,
    tag: str,
    status: str,
    digest: str = "",
    stderr: str = "",
    version: str | None = None,
    config: object | None = None,
) -> None:
    write(directory / f"{tag}.status", status)
    write(directory / f"{tag}.digest", digest)
    write(directory / f"{tag}.stderr", stderr)
    if config is not None:
        write(directory / f"{tag}.config", json.dumps(config))
    elif version is not None:
        write(
            directory / f"{tag}.config",
            json.dumps(
                {
                    "architecture": "amd64",
                    "os": "linux",
                    "config": {
                        "Labels": {publish.VERSION_LABEL: version},
                    },
                }
            ),
        )


def missing_inspection(directory: Path, tag: str) -> None:
    write_inspection(
        directory,
        tag,
        "1",
        stderr=f"ERROR: {IMAGE}:{tag}: not found",
    )


DISPATCH_HARNESS = """\
const fs = require('fs');
const script = fs.readFileSync(process.argv[2], 'utf8');
const calls = [];
const logs = [];
const status = Number(process.env.MOCK_STATUS);
const networkError = process.env.MOCK_NETWORK_ERROR === '1';
const fetch = async (url, options) => {
  calls.push({ url: String(url), method: options && options.method });
  if (networkError) {
    throw new Error('simulated network failure');
  }
  return { status, ok: status >= 200 && status < 300 };
};
const core = {
  info: (message) => logs.push(['info', String(message)]),
  warning: (message) => logs.push(['warning', String(message)]),
};
(async () => {
  try {
    await eval('(async () => {' + script + '\\n})()');
  } catch (error) {
    logs.push(['uncaught', String(error && error.message)]);
  }
  process.stdout.write(JSON.stringify({ calls, logs }));
})();
"""


def workflow_script(step_name: str) -> str:
    raw = (ROOT / ".github" / "workflows" / "docker-publish.yml").read_text(
        encoding="utf-8"
    )
    block = raw.split(f"- name: {step_name}", 1)[1].split("script: |", 1)[1]
    lines = []
    for line in block.splitlines():
        indent = len(line) - len(line.lstrip(" "))
        if line.strip() and indent <= 10:
            break
        lines.append(line[12:] if line.startswith("            ") else "")
    return "\n".join(lines).strip() + "\n"


def run_dispatch_script(
    script: str,
    *,
    token: str,
    repository: str,
    status: int = 204,
    network_error: bool = False,
) -> dict:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is required to execute the workflow dispatch script")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        script_path = root / "dispatch.js"
        harness_path = root / "harness.js"
        write(script_path, script)
        write(harness_path, DISPATCH_HARNESS)
        environment = {
            **os.environ,
            "SWARM_TOKEN": token,
            "SWARM_REPOSITORY": repository,
            "SOURCE_REPOSITORY": "digitalygo/envai-pii",
            "RELEASE_TAG": "1.2.3",
            "COMMIT_SHA": SHA,
            "RUN_ID": "12345",
            "MOCK_STATUS": str(status),
            "MOCK_NETWORK_ERROR": "1" if network_error else "0",
        }
        completed = subprocess.run(
            [node, str(harness_path), str(script_path)],
            env=environment,
            capture_output=True,
            check=True,
            text=True,
        )
    return json.loads(completed.stdout)


class TestReleaseSource(unittest.TestCase):
    def test_valid_stable_source(self):
        result = publish.validate_source(
            "v1.2.3", "false", "false", "published", SHA, SHA
        )
        self.assertEqual(result["version"], "1.2.3")
        self.assertEqual(result["channel"], "stable")
        self.assertEqual(result["short_sha"], SHA[:12])

    def test_valid_prerelease_sources(self):
        for channel in ("dev", "alpha", "beta"):
            with self.subTest(channel=channel):
                result = publish.validate_source(
                    f"1.2.3-{channel}.4", "true", "false", "published", SHA, SHA
                )
                self.assertEqual(result["channel"], channel)
                self.assertEqual(result["version"], f"1.2.3-{channel}.4")

    def test_release_commit_must_match_when_provided(self):
        publish.validate_source(
            "1.2.3", "false", "false", "published", SHA, SHA, SHA
        )
        with self.assertRaises(SystemExit):
            publish.validate_source(
                "1.2.3", "false", "false", "published", SHA, SHA, OTHER_SHA
            )
        with self.assertRaises(SystemExit):
            publish.validate_source(
                "1.2.3", "false", "false", "published", SHA, SHA, "main"
            )

    def test_invalid_release_tags(self):
        for tag in (
            "1.2",
            "1.2.3.4",
            "v1.2.3+build",
            "1.02.3",
            "1.2.3-rc.1",
            "1.2.3-alpha",
            "1.2.3-alpha.01",
            "V1.2.3",
            "",
        ):
            with self.subTest(tag=tag):
                with self.assertRaises(SystemExit):
                    publish.validate_source(
                        tag, "false", "false", "published", SHA, SHA
                    )

    def test_invalid_event_conditions(self):
        for args in (
            ("1.2.3", "false", "false", "edited", SHA, SHA),
            ("1.2.3", "false", "true", "published", SHA, SHA),
            ("1.2.3", "true", "false", "published", SHA, SHA),
            ("1.2.3-alpha.1", "false", "false", "published", SHA, SHA),
            ("1.2.3", "false", "false", "published", "", SHA),
            ("1.2.3", "false", "false", "published", SHA.upper(), SHA),
            ("1.2.3", "false", "false", "published", SHA, OTHER_SHA),
        ):
            with self.subTest(args=args):
                with self.assertRaises(SystemExit):
                    publish.validate_source(*args)

    def test_version_key_comparison(self):
        self.assertGreater(
            publish.version_key("1.3.0", "stable"),
            publish.version_key("1.2.9", "stable"),
        )
        self.assertGreater(
            publish.version_key("1.2.3-beta.2", "beta"),
            publish.version_key("1.2.3-beta.1", "beta"),
        )
        with self.assertRaises(SystemExit):
            publish.version_key("1.2.3-alpha.1", "beta")

    def test_validate_source_cli_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                parser = publish.build_parser()
                args = parser.parse_args(
                    [
                        "validate-source",
                        "--tag",
                        "v1.2.3",
                        "--prerelease",
                        "false",
                        "--draft",
                        "false",
                        "--action",
                        "published",
                        "--event-sha",
                        SHA,
                        "--peeled-sha",
                        SHA,
                    ]
                )
                args.func(args)
            text = output.read_text(encoding="utf-8")
            self.assertIn("version=1.2.3", text)
            self.assertIn(f"verified_sha={SHA}", text)

    def test_required_dockerfiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(SystemExit):
                publish.check_dockerfiles(str(root))
            write(root / "Dockerfile", "FROM scratch\n")
            with self.assertRaises(SystemExit):
                publish.check_dockerfiles(str(root))
            write(root / "Dockerfile.gpu", "FROM scratch\n")
            publish.check_dockerfiles(str(root))
            write(root / "Dockerfile.gpu", "")
            with self.assertRaises(SystemExit):
                publish.check_dockerfiles(str(root))


class TestPlan(unittest.TestCase):
    def test_stable_tag_set(self):
        plan = publish.plan_tags("v1.4.2", "false", SHA)
        self.assertEqual(plan["version"], "1.4.2")
        self.assertEqual(plan["channel"], "stable")
        self.assertEqual(plan["short_sha"], SHA[:12])
        self.assertEqual(
            set(plan["tags"]),
            {"1.4.2", "1.4", "1", "latest", f"1.4.2-{SHA[:12]}"},
        )
        self.assertEqual(set(plan["immutable_tags"]), {"1.4.2", f"1.4.2-{SHA[:12]}"})
        self.assertEqual(set(plan["rolling_tags"]), {"1.4", "1", "latest"})

    def test_prerelease_tag_sets_have_no_numeric_floating_aliases(self):
        for channel in ("dev", "alpha", "beta"):
            with self.subTest(channel=channel):
                version = f"1.4.2-{channel}.3"
                plan = publish.plan_tags(version, "true", SHA)
                self.assertEqual(
                    set(plan["tags"]),
                    {version, channel, f"{version}-{SHA[:12]}"},
                )
                self.assertEqual(set(plan["rolling_tags"]), {channel})
                self.assertNotIn("1", plan["tags"])
                self.assertNotIn("1.4", plan["tags"])
                self.assertNotIn("latest", plan["tags"])

    def test_plan_errors(self):
        with self.assertRaises(SystemExit):
            publish.plan_tags("1.2.3", "maybe", SHA)
        with self.assertRaises(SystemExit):
            publish.plan_tags("1.2.3-alpha.1", "false", SHA)
        with self.assertRaises(SystemExit):
            publish.plan_tags("1.2.3", "false", SHA.upper())
        with self.assertRaises(SystemExit):
            publish.plan_tags("1.2.3", "false", SHA[:-1])

    def test_plan_cli_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                parser = publish.build_parser()
                args = parser.parse_args(
                    [
                        "plan",
                        "--release-tag",
                        "v1.2.3",
                        "--prerelease",
                        "false",
                        "--sha",
                        SHA,
                    ]
                )
                args.func(args)
            text = output.read_text(encoding="utf-8")
            self.assertIn("version=1.2.3", text)
            self.assertIn("channel=stable", text)
            self.assertIn("tags<<GH_OUT", text)
            self.assertIn("latest", text)


class TestBuildMetadata(unittest.TestCase):
    def test_valid_metadata(self):
        self.assertEqual(
            publish.validate_build_metadata(metadata(), "linux/amd64", DIGEST),
            DIGEST,
        )

    def test_metadata_without_descriptor_platform_is_accepted(self):
        payload = metadata()
        del payload["containerimage.descriptor"]["platform"]
        self.assertEqual(
            publish.validate_build_metadata(payload, "linux/amd64", DIGEST),
            DIGEST,
        )

    def test_metadata_errors(self):
        cases = []
        cases.append(({}, "linux/amd64", DIGEST))
        cases.append((metadata(), "linux/arm64", DIGEST))
        cases.append((metadata(), "linux/amd64", ""))
        cases.append((metadata(), "linux/amd64", OTHER_DIGEST))
        cases.append(({"containerimage.digest": DIGEST}, "linux/amd64", DIGEST))
        cases.append(({"containerimage.descriptor": metadata()["containerimage.descriptor"]}, "linux/amd64", DIGEST))
        cases.append(({"containerimage.digest": "", "containerimage.descriptor": metadata()["containerimage.descriptor"]}, "linux/amd64", DIGEST))
        cases.append(({"containerimage.digest": "sha256:xyz", "containerimage.descriptor": metadata()["containerimage.descriptor"]}, "linux/amd64", DIGEST))
        cases.append(({"containerimage.digest": f"{DIGEST} {OTHER_DIGEST}", "containerimage.descriptor": metadata()["containerimage.descriptor"]}, "linux/amd64", DIGEST))
        cases.append(({"containerimage.digest": DIGEST, "containerimage.descriptor": {}}, "linux/amd64", DIGEST))
        cases.append(({"containerimage.digest": DIGEST, "containerimage.descriptor": {"mediaType": PLAIN_MEDIA_TYPE}}, "linux/amd64", DIGEST))
        cases.append(({"containerimage.digest": DIGEST, "containerimage.descriptor": {"mediaType": PLAIN_MEDIA_TYPE, "digest": "bad"}}, "linux/amd64", DIGEST))
        cases.append(({"containerimage.digest": DIGEST, "containerimage.descriptor": {"mediaType": INDEX_MEDIA_TYPE, "digest": DIGEST}}, "linux/amd64", DIGEST))
        cases.append(({"containerimage.digest": DIGEST, "containerimage.descriptor": {"mediaType": "application/alien", "digest": DIGEST}}, "linux/amd64", DIGEST))
        cases.append(({"containerimage.digest": DIGEST, "containerimage.descriptor": {"mediaType": PLAIN_MEDIA_TYPE, "digest": OTHER_DIGEST}}, "linux/amd64", DIGEST))
        cases.append(({"containerimage.digest": DIGEST, "containerimage.descriptor": {"mediaType": PLAIN_MEDIA_TYPE, "digest": DIGEST, "platform": "amd64"}}, "linux/amd64", DIGEST))
        cases.append(({"containerimage.digest": DIGEST, "containerimage.descriptor": {"mediaType": PLAIN_MEDIA_TYPE, "digest": DIGEST, "platform": {"architecture": "arm64", "os": "linux"}}}, "linux/amd64", DIGEST))
        cases.append(({"containerimage.digest": DIGEST, "containerimage.descriptor": metadata()["containerimage.descriptor"], "containerimage.index": {}}, "linux/amd64", DIGEST))
        for payload, platform, expected in cases:
            with self.subTest(payload=payload, platform=platform, expected=expected):
                with self.assertRaises(SystemExit):
                    publish.validate_build_metadata(payload, platform, expected)

    def test_load_metadata_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metadata.json"
            with self.assertRaises(SystemExit):
                publish.load_metadata(str(path))
            write(path, "")
            with self.assertRaises(SystemExit):
                publish.load_metadata(str(path))
            write(path, "not json")
            with self.assertRaises(SystemExit):
                publish.load_metadata(str(path))
            write(path, "[]")
            with self.assertRaises(SystemExit):
                publish.load_metadata(str(path))

    def test_validate_build_cli_writes_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metadata.json"
            output = Path(tmp) / "output"
            write(path, json.dumps(metadata()))
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                parser = publish.build_parser()
                args = parser.parse_args(
                    [
                        "validate-build",
                        "--metadata",
                        str(path),
                        "--platform",
                        "linux/amd64",
                        "--expected",
                        DIGEST,
                    ]
                )
                args.func(args)
            self.assertIn(f"digest={DIGEST}", output.read_text(encoding="utf-8"))


class TestRemoteIdentity(unittest.TestCase):
    def write_remote(
        self, tmp: str, manifest: object, config: object, suffix: bytes = b""
    ) -> tuple[str, str]:
        manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
        manifest_path = Path(tmp) / "manifest.json"
        config_path = Path(tmp) / "config.json"
        manifest_path.write_bytes(manifest_bytes + suffix)
        write(config_path, json.dumps(config))
        return str(manifest_path), str(config_path)

    def expected_digest(self, manifest: object) -> str:
        raw = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    def test_valid_remote_identity(self):
        manifest = remote_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, config_path = self.write_remote(
                tmp, manifest, {"architecture": "amd64", "os": "linux"}
            )
            expected = self.expected_digest(manifest)
            digest, config_digest = publish.validate_remote_identity(
                manifest_path, config_path, expected
            )
        self.assertEqual(digest, expected)
        self.assertEqual(config_digest, CONFIG_DIGEST)

    def test_raw_manifest_trailing_newline_is_tolerated(self):
        manifest = remote_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, config_path = self.write_remote(
                tmp,
                manifest,
                {"architecture": "amd64", "os": "linux"},
                suffix=b"\n",
            )
            expected = self.expected_digest(manifest)
            digest, _ = publish.validate_remote_identity(
                manifest_path, config_path, expected
            )
        self.assertEqual(digest, expected)

    def test_remote_identity_errors(self):
        config = {"architecture": "amd64", "os": "linux"}
        cases = []
        cases.append((remote_manifest(), config, b"", OTHER_DIGEST))
        cases.append((remote_manifest(), config, b"\n\n", None))
        cases.append(({**remote_manifest(), "schemaVersion": 1}, config, b"", None))
        cases.append(({**remote_manifest(), "mediaType": INDEX_MEDIA_TYPE}, config, b"", None))
        cases.append(({**remote_manifest(), "manifests": []}, config, b"", None))
        cases.append(({k: v for k, v in remote_manifest().items() if k != "mediaType"}, config, b"", None))
        cases.append(({**remote_manifest(), "mediaType": "application/alien"}, config, b"", None))
        cases.append(({k: v for k, v in remote_manifest().items() if k != "config"}, config, b"", None))
        cases.append(({**remote_manifest(), "config": {"digest": "bad"}}, config, b"", None))
        cases.append(({k: v for k, v in remote_manifest().items() if k != "layers"}, config, b"", None))
        cases.append((remote_manifest(), {"architecture": "arm64", "os": "linux"}, b"", None))
        cases.append((remote_manifest(), {"architecture": "amd64", "os": "windows"}, b"", None))
        for manifest, image_config, suffix, expected in cases:
            with self.subTest(manifest=manifest, config=image_config, suffix=suffix):
                with tempfile.TemporaryDirectory() as tmp:
                    manifest_path, config_path = self.write_remote(
                        tmp, manifest, image_config, suffix=suffix
                    )
                    if expected is None:
                        expected = self.expected_digest(manifest)
                    with self.assertRaises(SystemExit):
                        publish.validate_remote_identity(
                            manifest_path, config_path, expected
                        )

    def test_empty_and_malformed_remote_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            config_path = Path(tmp) / "config.json"
            write(manifest_path, "")
            write(config_path, "{}")
            with self.assertRaises(SystemExit):
                publish.validate_remote_identity(
                    str(manifest_path), str(config_path), DIGEST
                )
            write(manifest_path, "not json")
            with self.assertRaises(SystemExit):
                publish.validate_remote_identity(
                    str(manifest_path), str(config_path), DIGEST
                )
            with self.assertRaises(SystemExit):
                publish.validate_remote_identity(
                    str(Path(tmp) / "missing.json"), str(config_path), DIGEST
                )

    def test_validate_remote_cli_writes_config_digest(self):
        manifest = remote_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, config_path = self.write_remote(
                tmp, manifest, {"architecture": "amd64", "os": "linux"}
            )
            output = Path(tmp) / "output"
            expected = self.expected_digest(manifest)
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                parser = publish.build_parser()
                args = parser.parse_args(
                    [
                        "validate-remote",
                        "--manifest",
                        manifest_path,
                        "--config",
                        config_path,
                        "--digest",
                        expected,
                    ]
                )
                args.func(args)
            text = output.read_text(encoding="utf-8")
            self.assertIn(f"digest={expected}", text)
            self.assertIn(f"config_digest={CONFIG_DIGEST}", text)


class TestPreflight(unittest.TestCase):
    immutable = ["1.2.3", f"1.2.3-{SHA[:12]}"]
    rolling = ["1.2", "1", "latest"]
    all_tags = immutable + rolling

    def classify(self, directory: Path, version: str = "1.2.3", channel: str = "stable"):
        return publish.classify_preflight(
            DIGEST,
            IMAGE,
            version,
            channel,
            str(directory),
            self.immutable,
            self.rolling,
        )

    def test_absent_tags_are_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for tag in self.all_tags:
                missing_inspection(directory, tag)
            result = self.classify(directory)
        self.assertEqual(set(result["create_tags"]), set(self.all_tags))
        self.assertEqual(set(result["verify_tags"]), set(self.all_tags))
        self.assertEqual(result["skipped_tags"], [])

    def test_idempotent_tags_are_verified_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for tag in self.all_tags:
                write_inspection(directory, tag, "0", DIGEST)
            result = self.classify(directory)
        self.assertEqual(result["create_tags"], [])
        self.assertEqual(set(result["verify_tags"]), set(self.all_tags))

    def test_immutable_tag_foreign_digest_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for tag in self.all_tags:
                missing_inspection(directory, tag)
            write_inspection(directory, "1.2.3", "0", OTHER_DIGEST)
            with self.assertRaises(SystemExit):
                self.classify(directory)

    def test_ambiguous_inspection_failure_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for tag in self.all_tags:
                missing_inspection(directory, tag)
            write_inspection(directory, "1.2", "1", stderr="ERROR: unauthorized")
            with self.assertRaises(SystemExit):
                self.classify(directory)

    def test_manifest_unknown_is_real_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for tag in self.all_tags:
                write_inspection(directory, tag, "1", stderr="manifest unknown")
            result = self.classify(directory)
        self.assertEqual(set(result["create_tags"]), set(self.all_tags))
        self.assertEqual(set(result["verify_tags"]), set(self.all_tags))

    def test_url_404_is_real_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for tag in self.all_tags:
                stderr = (
                    "ERROR: unexpected status from HEAD request to "
                    f"https://ghcr.io/v2/digitalygo/envai-pii/manifests/{tag}: "
                    "404 Not Found"
                )
                write_inspection(directory, tag, "1", stderr=stderr)
            result = self.classify(directory)
        self.assertEqual(set(result["create_tags"]), set(self.all_tags))

    def test_rolling_tag_moves_forward_from_older_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for tag in self.all_tags:
                missing_inspection(directory, tag)
            write_inspection(directory, "latest", "0", OTHER_DIGEST, version="1.1.9")
            result = self.classify(directory)
        self.assertIn("latest", result["create_tags"])
        self.assertIn("latest", result["verify_tags"])

    def test_rolling_tag_is_not_rolled_back_by_an_older_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for tag in self.all_tags:
                missing_inspection(directory, tag)
            write_inspection(directory, "1.2", "0", OTHER_DIGEST, version="1.3.0")
            result = self.classify(directory)
        self.assertIn("1.2", result["skipped_tags"])
        self.assertNotIn("1.2", result["create_tags"])
        self.assertNotIn("1.2", result["verify_tags"])

    def test_same_version_with_foreign_digest_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for tag in self.all_tags:
                missing_inspection(directory, tag)
            write_inspection(directory, "1", "0", OTHER_DIGEST, version="1.2.3")
            with self.assertRaises(SystemExit):
                self.classify(directory)

    def test_rolling_channel_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for tag in self.all_tags:
                missing_inspection(directory, tag)
            write_inspection(directory, "latest", "0", OTHER_DIGEST, version="1.2.3-alpha.1")
            with self.assertRaises(SystemExit):
                self.classify(directory)

    def test_rolling_config_missing_or_malformed_fails(self):
        for config in (None, "not json", {}, {"config": {}}, {"config": {"Labels": {}}}):
            with self.subTest(config=config):
                with tempfile.TemporaryDirectory() as tmp:
                    directory = Path(tmp)
                    for tag in self.all_tags:
                        missing_inspection(directory, tag)
                    write_inspection(directory, "latest", "0", OTHER_DIGEST)
                    if config is not None:
                        write(directory / "latest.config", config if isinstance(config, str) else json.dumps(config))
                    with self.assertRaises(SystemExit):
                        self.classify(directory)

    def test_malformed_inspection_status_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for tag in self.all_tags:
                missing_inspection(directory, tag)
            write_inspection(directory, "latest", "2", OTHER_DIGEST)
            with self.assertRaises(SystemExit):
                self.classify(directory)

    def test_image_reference_validation(self):
        with self.assertRaises(SystemExit):
            publish.validate_image_reference("GHCR.IO/digitalygo/envai-pii")
        with self.assertRaises(SystemExit):
            publish.validate_image_reference("envai-pii")

    def test_preflight_cli_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for tag in self.all_tags:
                missing_inspection(directory, tag)
            output = directory / "output"
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                parser = publish.build_parser()
                args = parser.parse_args(
                    [
                        "preflight",
                        "--expected",
                        DIGEST,
                        "--image",
                        IMAGE,
                        "--release-tag",
                        "v1.2.3",
                        "--prerelease",
                        "false",
                        "--sha",
                        SHA,
                        "--inspect-dir",
                        str(directory),
                    ]
                )
                args.func(args)
            text = output.read_text(encoding="utf-8")
            self.assertIn("create_tags<<GH_OUT", text)
            self.assertIn("verify_tags<<GH_OUT", text)

    def test_verify_tags_success_and_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            verified = directory / "verified"
            verified.mkdir()
            tags = directory / "tags.txt"
            write(tags, "1.2\nlatest\n")
            for tag in ("1.2", "latest"):
                write(verified / f"{tag}.digest", DIGEST)
            output = directory / "output"
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                publish.verify_refs(DIGEST, str(verified), str(tags))
            self.assertIn("verified=true", output.read_text(encoding="utf-8"))

            write(verified / "latest.digest", OTHER_DIGEST)
            with self.assertRaises(SystemExit):
                publish.verify_refs(DIGEST, str(verified), str(tags))

            write(tags, "")
            with self.assertRaises(SystemExit):
                publish.verify_refs(DIGEST, str(verified), str(tags))

            write(tags, "missing\n")
            with self.assertRaises(SystemExit):
                publish.verify_refs(DIGEST, str(verified), str(tags))

            write(tags, "bad tag\n")
            with self.assertRaises(SystemExit):
                publish.verify_refs(DIGEST, str(verified), str(tags))

    def test_verify_tags_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            verified = directory / "verified"
            verified.mkdir()
            tags = directory / "tags.txt"
            write(tags, "latest\n")
            write(verified / "latest.digest", DIGEST)
            output = directory / "output"
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                parser = publish.build_parser()
                args = parser.parse_args(
                    [
                        "verify-tags",
                        "--expected",
                        DIGEST,
                        "--inspect-dir",
                        str(verified),
                        "--tags",
                        str(tags),
                    ]
                )
                args.func(args)
            self.assertIn("verified=true", output.read_text(encoding="utf-8"))

    def test_stderr_matching(self):
        self.assertTrue(
            publish.is_missing_ref_error(
                f"ERROR: {IMAGE}:latest: not found\n", IMAGE, "latest"
            )
        )
        self.assertTrue(
            publish.is_missing_ref_error(
                "manifest unknown", IMAGE, "latest"
            )
        )
        self.assertFalse(
            publish.is_missing_ref_error(
                "ERROR: unauthorized\nanother line", IMAGE, "latest"
            )
        )
        self.assertFalse(
            publish.is_missing_ref_error(
                "ERROR: unexpected status from HEAD request to "
                "https://ghcr.io/v2/digitalygo/envai-pii/manifests/latest: "
                "403 Forbidden",
                IMAGE,
                "latest",
            )
        )

    def test_check_dockerfiles_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "Dockerfile", "FROM scratch\n")
            write(root / "Dockerfile.gpu", "FROM scratch\n")
            parser = publish.build_parser()
            args = parser.parse_args(["check-dockerfiles", "--root", str(root)])
            args.func(args)


class TestWorkflowContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (ROOT / ".github" / "workflows" / "docker-publish.yml").read_text(
            encoding="utf-8"
        )
        cls.head = cls.raw.split("\njobs:", 1)[0]
        cls.publish = cls.raw.split("\n  publish:", 1)[1].split("\n  notify:", 1)[0]
        cls.notify = cls.raw.split("\n  notify:", 1)[1]

    def test_trigger_is_release_published_only(self):
        self.assertIn("on:\n  release:\n    types: [published]", self.raw)
        self.assertNotIn("pull_request", self.head)
        self.assertNotIn("workflow_dispatch", self.head)
        self.assertNotIn("push:", self.head)

    def test_tests_are_reused_and_required(self):
        self.assertIn("uses: ./.github/workflows/tests.yml", self.raw)
        self.assertIn("needs: tests", self.publish)

    def test_permissions_are_minimal(self):
        self.assertIn("permissions:\n  contents: read", self.head)
        self.assertEqual(self.raw.count("packages: write"), 1)
        self.assertIn("packages: write", self.publish)
        self.assertNotIn("packages: write", self.notify)

    def test_publish_runner_and_timeout(self):
        self.assertIn("runs-on: ubuntu-24.04", self.publish)
        self.assertIn("timeout-minutes: 60", self.publish)
        self.assertNotIn("self-hosted", self.raw)

    def test_concurrency_serializes_publication(self):
        self.assertIn("group: docker-publish-${{ github.repository }}", self.head)
        self.assertIn("cancel-in-progress: false", self.head)

    def test_checkout_is_the_exact_release_commit(self):
        pinned_action_refs(self.publish, "actions/checkout")
        self.assertIn("ref: ${{ github.sha }}", self.publish)
        self.assertIn("fetch-depth: 0", self.publish)
        self.assertIn("fetch-tags: true", self.publish)
        self.assertIn("persist-credentials: false", self.publish)
        self.assertNotIn("target_commitish", self.raw)

    def test_source_gate_peels_the_actual_tag(self):
        self.assertIn('git rev-parse --verify "refs/tags/${RELEASE_TAG}^{commit}"', self.publish)
        self.assertIn("validate-source", self.publish)
        for argument in (
            "--tag",
            "--prerelease",
            "--draft",
            "--action",
            "--event-sha",
            "--peeled-sha",
        ):
            self.assertIn(argument, self.publish)

    def test_dockerfiles_are_required_and_gpu_is_the_build_target(self):
        self.assertIn("check-dockerfiles", self.publish)
        self.assertIn("file: ./Dockerfile.gpu", self.publish)
        self.assertIn("context: .", self.publish)

    def test_image_reference_is_lowercase_ghcr(self):
        self.assertIn('image_ref="ghcr.io/${GITHUB_REPOSITORY,,}"', self.publish)
        self.assertIn("name=${{ steps.image.outputs.ref }}", self.publish)

    def test_build_is_digest_only_single_platform(self):
        pinned_action_refs(self.publish, "docker/build-push-action")
        self.assertIn("platforms: linux/amd64", self.publish)
        self.assertIn(
            "type=image,name=${{ steps.image.outputs.ref }},"
            "push-by-digest=true,name-canonical=true,push=true,oci-mediatypes=false",
            self.publish,
        )
        self.assertNotIn("\n          tags:", self.publish)
        self.assertNotIn("type=registry", self.publish)
        self.assertNotIn("buildcache", self.publish)

    def test_build_disables_index_producing_features_and_uses_bounded_cache(self):
        self.assertIn("provenance: false", self.publish)
        self.assertIn("sbom: false", self.publish)
        self.assertIn("cache-from: type=gha,scope=gpu", self.publish)
        self.assertIn("cache-to: type=gha,mode=min,scope=gpu", self.publish)

    def test_labels_bind_the_release_without_a_license_claim(self):
        self.assertIn("org.opencontainers.image.source=", self.publish)
        self.assertIn("org.opencontainers.image.revision=${{ github.sha }}", self.publish)
        self.assertIn("org.opencontainers.image.version=${{ steps.plan.outputs.version }}", self.publish)
        self.assertNotIn("org.opencontainers.image.licenses", self.publish)

    def test_digest_chain_order_is_source_build_remote_scan_gate_tags_dispatch(self):
        order = [
            "validate-source",
            "Build and push by digest",
            "validate-build",
            "validate-remote",
            "Scan the remote digest with Trivy",
            "scan_gate.py evaluate",
            "imagetools create",
            "registry_publish.py verify-tags",
            "Dispatch to the swarm when configured",
        ]
        positions = [self.publish.index(marker) for marker in order]
        self.assertEqual(positions, sorted(positions))

    def test_remote_manifest_and_config_are_validated(self):
        self.assertIn("docker buildx imagetools inspect \"$ref\" --raw", self.publish)
        self.assertIn("--format '{{json .Image}}'", self.publish)
        self.assertIn("validate-remote", self.publish)
        self.assertIn("config_digest", self.publish)

    def test_scan_container_is_hardened(self):
        scan_step = self.publish.split("Scan the remote digest with Trivy", 1)[1]
        scan_step = scan_step.split("Evaluate the scan gate", 1)[0]
        for flag in (
            "--cap-drop ALL",
            "--security-opt no-new-privileges",
            "--read-only",
            "--tmpfs /tmp",
        ):
            self.assertIn(flag, scan_step)
        self.assertNotIn("/var/run/docker.sock", scan_step)

    def test_scan_precedes_tag_creation(self):
        scan_index = self.publish.index("scan_gate.py evaluate")
        create_index = self.publish.index("imagetools create")
        self.assertLess(scan_index, create_index)
        self.assertIn("--image-id \"$IMAGE_ID\"", self.publish)
        self.assertIn("${{ steps.remote.outputs.config_digest }}", self.publish)

    def test_tag_promotion_does_not_rebuild(self):
        self.assertIn("--prefer-index=false", self.publish)
        self.assertIn('--tag "${IMAGE_REF}:${tag}"', self.publish)
        self.assertIn('"${IMAGE_REF}@${DIGEST}"', self.publish)
        self.assertEqual(self.publish.count("docker/build-push-action@"), 1)

    def test_created_tags_are_verified_right_after_promotion(self):
        create_index = self.publish.index("imagetools create")
        verify_index = self.publish.index("registry_publish.py verify-tags")
        dispatch_index = self.publish.index("Dispatch to the swarm when configured")
        self.assertLess(create_index, verify_index)
        self.assertLess(verify_index, dispatch_index)

    def test_swarm_dispatch_is_optional_and_after_verification(self):
        self.assertIn("SWARM_REPOSITORY_DISPATCH_TOKEN", self.publish)
        self.assertIn("vars.SWARM_REPOSITORY", self.publish)
        self.assertIn("renovate-run", self.publish)
        self.assertIn("source_repository", self.publish)
        self.assertIn("release_tag", self.publish)
        self.assertIn("commit_sha", self.publish)
        self.assertIn("run_id", self.publish)
        self.assertNotIn("SWARM_TOKEN", self.notify)

    def test_disk_cleanup_is_bounded_and_checks_the_budget(self):
        self.assertIn("RUNNER_ENVIRONMENT: ${{ runner.environment }}", self.publish)
        self.assertIn('if [[ "$RUNNER_ENVIRONMENT" == "github-hosted" ]]', self.publish)
        for path in (
            "/usr/local/lib/android",
            "/usr/share/dotnet",
            "/opt/ghc",
            "/usr/local/share/boost",
        ):
            self.assertIn(path, self.publish)
        self.assertIn("30 * 1024 * 1024 * 1024", self.publish)
        self.assertNotIn("hostedtoolcache", self.publish)

    def test_notification_is_always_and_starts_with_the_outcome_emoji(self):
        self.assertIn("needs: [tests, publish]", self.notify)
        self.assertIn("if: always()", self.notify)
        self.assertIn("KCHAT_WEBHOOK_URL", self.notify)
        self.assertIn("const emoji = success ? '✅' : '❌';", self.notify)
        self.assertIn("`${emoji} Docker publish ${outcome}", self.notify)
        self.assertIn("Repository:", self.notify)
        self.assertIn("Release:", self.notify)
        self.assertIn("Commit:", self.notify)
        self.assertIn("Outcome:", self.notify)
        self.assertNotIn("console.log(webhook", self.notify)

    def test_no_runtime_secret_is_referenced(self):
        self.assertNotIn("PII_API_TOKEN", self.raw)


class TestSwarmDispatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = workflow_script("Dispatch to the swarm when configured")

    def run_dispatch(self, **overrides):
        settings = {"token": "dispatch-token", "repository": "owner/repo"}
        settings.update(overrides)
        return run_dispatch_script(self.script, **settings)

    def test_script_has_no_skip_logging(self):
        self.assertNotIn("Swarm dispatch skipped", self.script)
        self.assertNotIn("core.info", self.script)

    def test_missing_target_returns_before_posting(self):
        cases = (
            {"token": "", "repository": "owner/repo"},
            {"token": "dispatch-token", "repository": ""},
            {"token": "", "repository": ""},
        )
        for case in cases:
            with self.subTest(case=case):
                result = self.run_dispatch(**case)
                self.assertEqual(result["calls"], [])
                self.assertEqual(result["logs"], [])

    def test_invalid_target_returns_before_posting(self):
        for repository in ("owner", "owner/repo/extra", "owner/re po", "owner//repo"):
            with self.subTest(repository=repository):
                result = self.run_dispatch(repository=repository)
                self.assertEqual(result["calls"], [])
                self.assertEqual(result["logs"], [])

    def test_unauthorized_responses_skip_silently_after_the_post(self):
        for status in (401, 403, 404):
            with self.subTest(status=status):
                result = self.run_dispatch(status=status)
                self.assertEqual(
                    result["calls"],
                    [
                        {
                            "url": "https://api.github.com/repos/owner/repo/dispatches",
                            "method": "POST",
                        }
                    ],
                )
                self.assertEqual(result["logs"], [])

    def test_network_errors_skip_silently(self):
        result = self.run_dispatch(network_error=True)
        self.assertEqual(len(result["calls"]), 1)
        self.assertEqual(result["logs"], [])

    def test_unexpected_status_warns_without_leaking_the_token(self):
        result = self.run_dispatch(status=500, token="sensitive-dispatch-token")
        self.assertEqual(len(result["calls"]), 1)
        self.assertEqual(
            result["logs"], [["warning", "Swarm dispatch failed with HTTP 500"]]
        )
        self.assertNotIn("sensitive-dispatch-token", json.dumps(result))

    def test_successful_dispatch_posts_once(self):
        result = self.run_dispatch(status=204)
        self.assertEqual(
            result["calls"],
            [
                {
                    "url": "https://api.github.com/repos/owner/repo/dispatches",
                    "method": "POST",
                }
            ],
        )
        self.assertEqual(result["logs"], [])


if __name__ == "__main__":
    unittest.main()
