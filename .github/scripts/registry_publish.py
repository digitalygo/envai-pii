from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHORT_SHA_RE = re.compile(r"^[0-9a-f]{12}$")
RELEASE_RE = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(dev|alpha|beta)\.(0|[1-9]\d*))?$"
)
TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*(?::[0-9]+)?/[a-z0-9][a-z0-9._/-]*$")
INDEX_MEDIA_TYPES = {
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.index.v1+json",
}
PLAIN_MANIFEST_MEDIA_TYPES = {
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
}
AMD64_PLATFORM = "linux/amd64"
AMD64_ARCH = "amd64"
LINUX_OS = "linux"
VERSION_LABEL = "org.opencontainers.image.version"


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


def validate_digest(digest: str) -> str:
    if not isinstance(digest, str) or not digest:
        fail("missing digest: the build output did not report a container digest")
    if not DIGEST_RE.fullmatch(digest):
        fail(f"malformed digest value: {digest}")
    return digest


def validate_tag_name(name: str) -> str:
    if not TAG_RE.fullmatch(name):
        fail(f"tag {name!r} is not a valid container tag")
    if name.startswith(".") or name.startswith("-"):
        fail(f"tag {name!r} must not start with a dot or dash")
    return name


def validate_image_reference(image: str) -> str:
    if not isinstance(image, str) or not IMAGE_RE.fullmatch(image):
        fail(f"image reference is not canonical lowercase registry/repository: {image!r}")
    return image


def parse_release_tag(release_tag: str) -> tuple[str, str]:
    match = RELEASE_RE.fullmatch(release_tag)
    if match is None:
        fail(
            "release tag must be v?X.Y.Z or v?X.Y.Z-(dev|alpha|beta).N: "
            f"{release_tag!r}"
        )
    version = release_tag[1:] if release_tag.startswith("v") else release_tag
    channel = match.group(4) or "stable"
    return version, channel


def version_key(version: str, channel: str) -> tuple[int, ...]:
    match = RELEASE_RE.fullmatch(version)
    if match is None:
        fail(f"version {version!r} is not canonical semver")
    observed_channel = match.group(4) or "stable"
    if observed_channel != channel:
        fail(f"version {version!r} belongs to channel {observed_channel}, not {channel}")
    key = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    if channel == "stable":
        return key
    return key + (int(match.group(5)),)


def plan_tags(release_tag: str, prerelease: str, sha: str) -> dict[str, object]:
    if prerelease not in ("true", "false"):
        fail(f"prerelease flag must be true or false, got {prerelease!r}")
    if not SHA_RE.fullmatch(sha):
        fail(f"commit sha must be 40 lowercase hexadecimal characters: {sha!r}")
    version, channel = parse_release_tag(release_tag)
    expected_prerelease = channel != "stable"
    if (prerelease == "true") != expected_prerelease:
        fail(
            f"release {release_tag} prerelease flag {prerelease} "
            f"does not match channel {channel}"
        )
    short_sha = sha[:12]
    if not SHORT_SHA_RE.fullmatch(short_sha):
        fail(f"short sha must be 12 lowercase hexadecimal characters: {short_sha!r}")
    match = RELEASE_RE.fullmatch(version)
    if match is None:
        fail(f"version {version!r} is not canonical semver")
    major = int(match.group(1))
    minor = int(match.group(2))
    immutable_tags = [version, f"{version}-{short_sha}"]
    if channel == "stable":
        rolling_tags = [f"{major}.{minor}", f"{major}", "latest"]
        tags = [version, *rolling_tags, f"{version}-{short_sha}"]
    else:
        rolling_tags = [channel]
        tags = [version, channel, f"{version}-{short_sha}"]
    for tag in tags:
        validate_tag_name(tag)
    if len(set(tags)) != len(tags):
        fail(f"tag plan contains duplicates: {tags}")
    return {
        "version": version,
        "channel": channel,
        "short_sha": short_sha,
        "immutable_tags": immutable_tags,
        "rolling_tags": rolling_tags,
        "tags": tags,
    }


def validate_source(
    tag: str,
    prerelease: str,
    draft: str,
    action: str,
    event_sha: str,
    peeled_sha: str,
    release_commit: str = "",
) -> dict[str, str]:
    if action != "published":
        fail(f"release action must be published, got {action!r}")
    if draft != "false":
        fail(f"release must not be a draft, got {draft!r}")
    version, channel = parse_release_tag(tag)
    if prerelease not in ("true", "false"):
        fail(f"prerelease flag must be true or false, got {prerelease!r}")
    expected_prerelease = channel != "stable"
    if (prerelease == "true") != expected_prerelease:
        fail(
            f"release {tag} prerelease flag {prerelease} "
            f"does not match channel {channel}"
        )
    if not SHA_RE.fullmatch(event_sha):
        fail(f"event commit must be 40 lowercase hexadecimal characters: {event_sha!r}")
    if not SHA_RE.fullmatch(peeled_sha):
        fail(f"tag commit must be 40 lowercase hexadecimal characters: {peeled_sha!r}")
    if event_sha != peeled_sha:
        fail(f"release event commit {event_sha} does not match tag commit {peeled_sha}")
    if release_commit:
        if not SHA_RE.fullmatch(release_commit):
            fail("release commit must be a full 40 hexadecimal commit, not a branch")
        if release_commit != event_sha:
            fail(
                f"release commit {release_commit} does not match "
                f"the event commit {event_sha}"
            )
    return {
        "version": version,
        "channel": channel,
        "short_sha": event_sha[:12],
    }


def check_dockerfiles(root: str) -> None:
    for name in ("Dockerfile", "Dockerfile.gpu"):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            fail(f"missing required Dockerfile at {path}")
        if os.path.getsize(path) == 0:
            fail(f"required Dockerfile is empty at {path}")


def load_metadata(metadata_path: str) -> dict:
    try:
        with open(metadata_path, encoding="utf-8") as handle:
            raw = handle.read()
    except OSError as exc:
        fail(f"cannot read build metadata {metadata_path}: {exc}")
    if not raw.strip():
        fail("empty build metadata: the build output is missing")
    try:
        metadata = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"build metadata is not valid JSON: {exc}")
    if not isinstance(metadata, dict):
        fail("build metadata JSON must be an object")
    return metadata


def validate_descriptor(descriptor: object) -> str:
    if not isinstance(descriptor, dict):
        fail("build metadata descriptor must be an object")
    media_type = descriptor.get("mediaType")
    if not isinstance(media_type, str) or not media_type:
        fail("build metadata descriptor has no mediaType")
    if media_type in INDEX_MEDIA_TYPES:
        fail(
            f"build produced an index or manifest list ({media_type}); "
            "a plain amd64 manifest is required"
        )
    if media_type not in PLAIN_MANIFEST_MEDIA_TYPES:
        fail(f"build metadata descriptor has an unsupported mediaType: {media_type!r}")
    descriptor_digest = descriptor.get("digest")
    if not isinstance(descriptor_digest, str):
        fail("build metadata descriptor has no digest")
    validated = validate_digest(descriptor_digest)
    platform = descriptor.get("platform")
    if platform is None:
        return validated
    if not isinstance(platform, dict):
        fail("build metadata descriptor platform is malformed")
    architecture = platform.get("architecture")
    operating_system = platform.get("os")
    if architecture != AMD64_ARCH or operating_system != LINUX_OS:
        fail(
            f"descriptor platform contradicts the amd64 publication: "
            f"{operating_system}/{architecture}"
        )
    return validated


def validate_build_metadata(metadata: dict, platform: str, expected: str) -> str:
    if platform != AMD64_PLATFORM:
        fail(f"unsupported build platform {platform}: this publication is amd64-only")
    if "containerimage.index" in metadata:
        fail("build metadata retains an image index; a plain amd64 manifest is required")
    descriptor = metadata.get("containerimage.descriptor")
    if not isinstance(descriptor, dict):
        fail("build metadata has no descriptor; cannot bind the pushed digest")
    descriptor_digest = validate_descriptor(descriptor)
    digest = metadata.get("containerimage.digest")
    if not isinstance(digest, str) or not digest:
        fail("build metadata has no containerimage.digest")
    if not DIGEST_RE.fullmatch(digest):
        fail(f"build metadata digest is malformed or ambiguous: {digest!r}")
    validated = validate_digest(digest)
    if not isinstance(expected, str) or not expected:
        fail("missing expected digest: the build step did not report a digest")
    if expected != validated:
        fail(
            f"unverified digest {validated} does not match "
            f"the build output digest {expected}"
        )
    if descriptor_digest != validated:
        fail(
            f"contradictory digests: descriptor {descriptor_digest} "
            f"does not match metadata {validated}"
        )
    return validated


def read_bytes(path: str, label: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        fail(f"cannot read {label} {path}: {exc}")


def read_text(path: str, label: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        fail(f"cannot read {label} {path}: {exc}")


def normalize_manifest_bytes(raw: bytes, expected: str) -> bytes:
    if f"sha256:{hashlib.sha256(raw).hexdigest()}" == expected:
        return raw
    if raw.endswith(b"\n"):
        trimmed = raw[:-1]
        if f"sha256:{hashlib.sha256(trimmed).hexdigest()}" == expected:
            return trimmed
    observed = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    fail(f"remote identity mismatch: the manifest at {expected} hashes to {observed}")


def validate_remote_identity(manifest_path: str, config_path: str, expected: str) -> tuple[str, str]:
    validated = validate_digest(expected)
    raw = read_bytes(manifest_path, "remote manifest")
    if not raw.strip():
        fail("empty remote manifest: the registry did not return the pushed manifest")
    normalized = normalize_manifest_bytes(raw, validated)
    try:
        manifest = json.loads(normalized)
    except json.JSONDecodeError as exc:
        fail(f"the remote manifest is not valid JSON: {exc}")
    if not isinstance(manifest, dict):
        fail("the remote manifest JSON must be an object")
    if manifest.get("schemaVersion") != 2:
        fail(f"unsupported remote manifest schemaVersion: {manifest.get('schemaVersion')!r}")
    if "manifests" in manifest:
        fail("the remote digest is an index or manifest list; a plain amd64 manifest is required")
    media_type = manifest.get("mediaType")
    if media_type in INDEX_MEDIA_TYPES:
        fail(
            f"the remote digest is an index or manifest list ({media_type}); "
            "a plain amd64 manifest is required"
        )
    if media_type not in PLAIN_MANIFEST_MEDIA_TYPES:
        fail(f"the remote manifest has an unsupported media type: {media_type!r}")
    config_descriptor = manifest.get("config")
    if not isinstance(config_descriptor, dict):
        fail("the remote manifest has no config descriptor")
    config_digest = config_descriptor.get("digest")
    if not isinstance(config_digest, str) or not DIGEST_RE.fullmatch(config_digest):
        fail(f"the remote manifest config digest is malformed: {config_digest!r}")
    if not isinstance(manifest.get("layers"), list):
        fail("the remote manifest has no layer list")
    config_raw = read_text(config_path, "remote image config")
    if not config_raw.strip():
        fail("empty remote image config")
    try:
        image_config = json.loads(config_raw)
    except json.JSONDecodeError as exc:
        fail(f"the remote image config is not valid JSON: {exc}")
    if not isinstance(image_config, dict):
        fail("the remote image config JSON must be an object")
    architecture = image_config.get("architecture")
    operating_system = image_config.get("os")
    if architecture != AMD64_ARCH or operating_system != LINUX_OS:
        fail(
            f"the remote image covers the wrong platform: "
            f"{operating_system}/{architecture}, expected linux/amd64"
        )
    return validated, config_digest


def normalize_stderr(stderr: str) -> str:
    if stderr.endswith("\n"):
        return stderr[:-1]
    return stderr


def build_url_form(image: str, tag: str) -> str:
    registry, repository = image.split("/", 1)
    return f"https://{registry}/v2/{repository}/manifests/{tag}"


def is_missing_ref_error(stderr_raw: str, image: str, tag: str) -> bool:
    stderr = normalize_stderr(stderr_raw)
    if "\n" in stderr or "\r" in stderr:
        return False
    ref = f"{image}:{tag}"
    if stderr == "manifest unknown":
        return True
    if stderr == f"ERROR: {ref}: not found":
        return True
    url_form = build_url_form(image, tag)
    return stderr == f"ERROR: unexpected status from HEAD request to {url_form}: 404 Not Found"


def read_inspection(inspect_dir: str, tag: str) -> tuple[str, str, str]:
    status = read_text(os.path.join(inspect_dir, f"{tag}.status"), "tag status").strip()
    digest = read_text(os.path.join(inspect_dir, f"{tag}.digest"), "tag digest").strip()
    stderr = read_text(os.path.join(inspect_dir, f"{tag}.stderr"), "tag inspection error")
    if status not in ("0", "1"):
        fail(f"tag {tag} has a malformed registry inspection status: {status!r}")
    return status, digest, stderr


def read_image_version(config_path: str) -> tuple[str, str]:
    raw = read_text(config_path, "tag image config")
    if not raw.strip():
        fail("empty tag image config")
    try:
        image_config = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"tag image config is not valid JSON: {exc}")
    if not isinstance(image_config, dict):
        fail("tag image config JSON must be an object")
    config = image_config.get("config")
    if not isinstance(config, dict):
        fail("tag image config has no config object")
    labels = config.get("Labels")
    if labels is None:
        labels = config.get("labels")
    if not isinstance(labels, dict):
        fail("tag image config has no labels")
    version = labels.get(VERSION_LABEL)
    if not isinstance(version, str) or not version:
        fail(f"tag image config has no {VERSION_LABEL} label")
    return parse_release_tag(version)


def classify_preflight(
    expected: str,
    image: str,
    version: str,
    channel: str,
    inspect_dir: str,
    immutable_tags: list[str],
    rolling_tags: list[str],
) -> dict[str, list[str]]:
    validate_digest(expected)
    validate_image_reference(image)
    candidate_key = version_key(version, channel)
    create_tags: list[str] = []
    verify_tags: list[str] = []
    skipped_tags: list[str] = []
    for tag in immutable_tags:
        validate_tag_name(tag)
        status, digest, stderr = read_inspection(inspect_dir, tag)
        if status == "0":
            if digest == expected:
                verify_tags.append(tag)
                continue
            fail(
                f"immutable tag {tag} already resolves to {digest}, "
                "refusing to overwrite"
            )
        if is_missing_ref_error(stderr, image, tag):
            create_tags.append(tag)
            verify_tags.append(tag)
            continue
        fail(f"registry inspection for tag {tag} failed with an ambiguous error: {stderr.strip()}")
    for tag in rolling_tags:
        validate_tag_name(tag)
        status, digest, stderr = read_inspection(inspect_dir, tag)
        if status == "0":
            if digest == expected:
                verify_tags.append(tag)
                continue
            existing_version, existing_channel = read_image_version(
                os.path.join(inspect_dir, f"{tag}.config")
            )
            if existing_channel != channel:
                fail(
                    f"rolling tag {tag} belongs to channel {existing_channel}, "
                    f"not {channel}"
                )
            existing_key = version_key(existing_version, channel)
            if existing_key > candidate_key:
                skipped_tags.append(tag)
                continue
            if existing_key == candidate_key:
                fail(
                    f"rolling tag {tag} already resolves to {digest} for version "
                    f"{existing_version}, refusing a mutable rebuild"
                )
            create_tags.append(tag)
            verify_tags.append(tag)
            continue
        if is_missing_ref_error(stderr, image, tag):
            create_tags.append(tag)
            verify_tags.append(tag)
            continue
        fail(f"registry inspection for tag {tag} failed with an ambiguous error: {stderr.strip()}")
    return {
        "create_tags": create_tags,
        "verify_tags": verify_tags,
        "skipped_tags": skipped_tags,
    }


def read_tag_list(tags_path: str) -> list[str]:
    raw = read_text(tags_path, "tag plan")
    tags = [line.strip() for line in raw.splitlines() if line.strip()]
    if not tags:
        fail("tag plan is empty")
    return tags


def verify_refs(expected: str, inspect_dir: str, tags_path: str) -> None:
    validated = validate_digest(expected)
    tags = read_tag_list(tags_path)
    for tag in tags:
        validate_tag_name(tag)
        digest = read_text(
            os.path.join(inspect_dir, f"{tag}.digest"), "verified tag digest"
        ).strip()
        if digest != validated:
            fail(f"tag {tag} resolves to {digest!r}, expected {validated}")
    emit_outputs([("verified", "true")])
    print(f"verified {len(tags)} tag(s) resolve to {validated}")


def command_check_dockerfiles(args: argparse.Namespace) -> None:
    check_dockerfiles(args.root)
    print("required Dockerfiles are present")


def command_validate_source(args: argparse.Namespace) -> None:
    result = validate_source(
        args.tag,
        args.prerelease,
        args.draft,
        args.action,
        args.event_sha,
        args.peeled_sha,
        args.release_commit,
    )
    emit_outputs(
        [
            ("version", result["version"]),
            ("channel", result["channel"]),
            ("short_sha", result["short_sha"]),
            ("verified_sha", args.event_sha),
        ]
    )
    print(f"release source verified for channel {result['channel']}")


def command_plan(args: argparse.Namespace) -> None:
    plan = plan_tags(args.release_tag, args.prerelease, args.sha)
    emit_outputs(
        [
            ("version", str(plan["version"])),
            ("channel", str(plan["channel"])),
            ("short_sha", str(plan["short_sha"])),
            ("immutable_tags", "\n".join(plan["immutable_tags"])),
            ("rolling_tags", "\n".join(plan["rolling_tags"])),
            ("tags", "\n".join(plan["tags"])),
        ]
    )
    print(f"planned {len(plan['tags'])} tag(s) for channel {plan['channel']}")


def command_validate_build(args: argparse.Namespace) -> None:
    metadata = load_metadata(args.metadata)
    digest = validate_build_metadata(metadata, args.platform, args.expected)
    emit_outputs([("digest", digest)])
    print(f"validated amd64 digest {digest}")


def command_validate_remote(args: argparse.Namespace) -> None:
    digest, config_digest = validate_remote_identity(
        args.manifest, args.config, args.digest
    )
    emit_outputs([("digest", digest), ("config_digest", config_digest)])
    print(f"validated the exact remote amd64 manifest and config for {digest}")


def command_preflight(args: argparse.Namespace) -> None:
    plan = plan_tags(args.release_tag, args.prerelease, args.sha)
    result = classify_preflight(
        args.expected,
        args.image,
        str(plan["version"]),
        str(plan["channel"]),
        args.inspect_dir,
        plan["immutable_tags"],
        plan["rolling_tags"],
    )
    emit_outputs(
        [
            ("create_tags", "\n".join(result["create_tags"])),
            ("verify_tags", "\n".join(result["verify_tags"])),
            ("skipped_tags", "\n".join(result["skipped_tags"])),
        ]
    )
    print(
        f"preflight: {len(result['create_tags'])} tag(s) to create, "
        f"{len(result['verify_tags'])} selected for verification, "
        f"{len(result['skipped_tags'])} skipped as newer"
    )


def command_verify_tags(args: argparse.Namespace) -> None:
    verify_refs(args.expected, args.inspect_dir, args.tags)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and plan the amd64 GHCR publication"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser(
        "check-dockerfiles", help="Require the root production Dockerfiles"
    )
    check.add_argument("--root", default=".")
    check.set_defaults(func=command_check_dockerfiles)

    source = subparsers.add_parser(
        "validate-source", help="Validate the release event and the tagged commit"
    )
    source.add_argument("--tag", required=True)
    source.add_argument("--prerelease", required=True)
    source.add_argument("--draft", required=True)
    source.add_argument("--action", required=True)
    source.add_argument("--event-sha", required=True)
    source.add_argument("--peeled-sha", required=True)
    source.add_argument("--release-commit", default="")
    source.set_defaults(func=command_validate_source)

    plan = subparsers.add_parser("plan", help="Plan the exact release tag set")
    plan.add_argument("--release-tag", required=True)
    plan.add_argument("--prerelease", required=True)
    plan.add_argument("--sha", required=True)
    plan.set_defaults(func=command_plan)

    build = subparsers.add_parser(
        "validate-build", help="Validate the build metadata digest"
    )
    build.add_argument("--metadata", required=True)
    build.add_argument("--platform", required=True)
    build.add_argument("--expected", required=True)
    build.set_defaults(func=command_validate_build)

    remote = subparsers.add_parser(
        "validate-remote", help="Validate the exact remote amd64 manifest and config"
    )
    remote.add_argument("--manifest", required=True)
    remote.add_argument("--config", required=True)
    remote.add_argument("--digest", required=True)
    remote.set_defaults(func=command_validate_remote)

    preflight = subparsers.add_parser(
        "preflight", help="Classify existing tags before creating any tag"
    )
    preflight.add_argument("--expected", required=True)
    preflight.add_argument("--image", required=True)
    preflight.add_argument("--release-tag", required=True)
    preflight.add_argument("--prerelease", required=True)
    preflight.add_argument("--sha", required=True)
    preflight.add_argument("--inspect-dir", required=True)
    preflight.set_defaults(func=command_preflight)

    verify = subparsers.add_parser(
        "verify-tags", help="Verify written tags resolve to the scanned digest"
    )
    verify.add_argument("--expected", required=True)
    verify.add_argument("--inspect-dir", required=True)
    verify.add_argument("--tags", required=True)
    verify.set_defaults(func=command_verify_tags)

    return parser


if __name__ == "__main__":
    parser = build_parser()
    arguments = parser.parse_args()
    arguments.func(arguments)
