#!/usr/bin/env python3
"""Collision-safe GitHub release engine for dev, alpha, beta and main."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Optional

DEFAULT_API_URL = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS = 30
GIT_TIMEOUT_SECONDS = 120
MAX_CLAIM_ATTEMPTS = 50
MAX_RELEASE_READ_ATTEMPTS = 3
MAX_TAG_PEEL_DEPTH = 10

RELEASE_BRANCH_CHANNELS: dict[str, Optional[str]] = {
    "dev": "dev",
    "alpha": "alpha",
    "beta": "beta",
    "main": None,
}
BUMP_BY_TYPE: dict[str, str] = {
    "feat": "minor",
    "fix": "patch",
    "chore": "patch",
    "refactor": "patch",
    "build": "patch",
}
BREAKING_TYPES = frozenset({"feat", "fix"})
BUMP_RANK = {"patch": 1, "minor": 2, "major": 3}
CHANNEL_RANK = {"dev": 0, "alpha": 1, "beta": 2}
SKIP_MARKER = "[skip ci]"

VERSION_RE = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(dev|alpha|beta)\.([1-9][0-9]*))?\Z"
)
COMMIT_RE = re.compile(r"^(?P<type>[a-z][a-z0-9-]*)(?:\((?P<scope>[^()]*)\))?(?P<bang>!)?:\s(?P<desc>\S.*)$")
BREAKING_FOOTER_RE = re.compile(r"^\s*BREAKING[ -]CHANGE:")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
GIT_LOG_FORMAT = "%H%x1f%s%x1f%b%x1e"
FIELD_SEPARATOR = "\x1f"
RECORD_SEPARATOR = "\x1e"


class FatalError(Exception):
    """An error that must fail the release run."""


class InputError(FatalError):
    """Invalid repository, branch, sha or API configuration."""


class GitError(FatalError):
    """A git command or its output is unusable."""


class ApiError(FatalError):
    """The GitHub API returned an unusable response."""


class AuthorizationError(ApiError):
    """The GitHub API rejected the supplied credentials."""


class NetworkError(ApiError):
    """The GitHub API could not be reached."""


class ValidationError(ApiError):
    """The GitHub API returned a response that violates the release contract."""


class NotFoundError(ApiError):
    """The requested GitHub API resource does not exist."""


class RefAlreadyExists(Exception):
    """A tag ref or release with the requested name already exists."""


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    channel: Optional[str] = None
    counter: Optional[int] = None

    @property
    def is_prerelease(self) -> bool:
        return self.channel is not None

    @property
    def core(self) -> "Version":
        return Version(self.major, self.minor, self.patch)

    @property
    def precedence(self) -> tuple[int, int, int, int, int, int]:
        if self.channel is None:
            return (self.major, self.minor, self.patch, 1, 0, 0)
        return (self.major, self.minor, self.patch, 0, CHANNEL_RANK[self.channel], self.counter or 0)

    def with_channel(self, channel: str, counter: int) -> "Version":
        return Version(self.major, self.minor, self.patch, channel, counter)


def parse_version_tag(name: str) -> Optional[Version]:
    match = VERSION_RE.match(name)
    if match is None:
        return None
    counter = int(match.group(5)) if match.group(5) is not None else None
    return Version(int(match.group(1)), int(match.group(2)), int(match.group(3)), match.group(4), counter)


def format_version(version: Version) -> str:
    text = f"{version.major}.{version.minor}.{version.patch}"
    if version.channel is not None:
        text += f"-{version.channel}.{version.counter}"
    return text


def tag_name(version: Version) -> str:
    return f"v{format_version(version)}"


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    body: str


@dataclass(frozen=True)
class TagRef:
    name: str
    commit: str
    version: Optional[Version]


def has_breaking_footer(body: str) -> bool:
    return any(BREAKING_FOOTER_RE.match(line) for line in body.splitlines())


def commit_bump(subject: str, body: str) -> Optional[str]:
    match = COMMIT_RE.match(subject)
    if match is None:
        return None
    bump = BUMP_BY_TYPE.get(match.group("type"))
    if bump is None:
        return None
    is_breaking = match.group("type") in BREAKING_TYPES and (
        match.group("bang") is not None or has_breaking_footer(body)
    )
    return "major" if is_breaking else bump


def is_skip_commit(commit: Commit) -> bool:
    return SKIP_MARKER in f"{commit.subject}\n{commit.body}".casefold()


def commit_is_eligible(commit: Commit) -> bool:
    return not is_skip_commit(commit) and commit_bump(commit.subject, commit.body) is not None


def max_bump(bumps: list[Optional[str]]) -> Optional[str]:
    present = [bump for bump in bumps if bump is not None]
    if not present:
        return None
    return max(present, key=BUMP_RANK.__getitem__)


def apply_bump(version: Version, bump: str) -> Version:
    if bump == "major":
        return Version(version.major + 1, 0, 0)
    if bump == "minor":
        return Version(version.major, version.minor + 1, 0)
    return Version(version.major, version.minor, version.patch + 1)


def next_prerelease(line: Version, channel: str, tags: list[TagRef]) -> Version:
    counters = [
        tag.version.counter
        for tag in tags
        if tag.version is not None
        and tag.version.channel == channel
        and tag.version.core == line
        and tag.version.counter is not None
    ]
    return line.with_channel(channel, max(counters, default=0) + 1)


@dataclass(frozen=True)
class Boundary:
    mode: str
    stop_shas: tuple[str, ...]
    base: Optional[Version]


def select_boundary(tags: list[TagRef], channel: Optional[str] = None) -> Boundary:
    canonical = [tag for tag in tags if tag.version is not None]
    if channel is not None:
        canonical = [
            tag
            for tag in canonical
            if not tag.version.is_prerelease or tag.version.channel == channel
        ]
    if not canonical:
        return Boundary("first", (), None)
    top = max(canonical, key=lambda tag: tag.version.precedence)
    if top.version.is_prerelease:
        return Boundary("inflight", (top.commit,), top.version.core)
    return Boundary("stable", (top.commit,), top.version)


def _top_stable_tag(tags: list[TagRef]) -> Optional[TagRef]:
    stables = [tag for tag in tags if tag.version is not None and not tag.version.is_prerelease]
    if not stables:
        return None
    return max(stables, key=lambda tag: tag.version.precedence)


@dataclass(frozen=True)
class ReleasePlan:
    mode: str
    version: Optional[Version]
    eligible: tuple[Commit, ...]


def finalize_release(
    boundary: Boundary,
    commits: list[Commit],
    channel: Optional[str],
    tags: list[TagRef],
    *,
    bump_since_stable: Optional[str] = None,
) -> ReleasePlan:
    eligible = tuple(commit for commit in commits if commit_is_eligible(commit))
    bump = max_bump([commit_bump(commit.subject, commit.body) for commit in eligible])
    if boundary.mode == "first":
        if not eligible:
            return ReleasePlan("none", None, ())
        version = Version(1, 0, 0, channel, 1) if channel else Version(1, 0, 0)
        return ReleasePlan("first", version, eligible)
    if boundary.mode == "stable":
        if not eligible:
            return ReleasePlan("none", None, ())
        target = apply_bump(boundary.base, bump)
        version = next_prerelease(target, channel, tags) if channel else target
        return ReleasePlan("stable", version, eligible)
    if channel is not None and not eligible:
        return ReleasePlan("none", None, ())
    stable_tag = _top_stable_tag(tags)
    if stable_tag is None:
        line = apply_bump(boundary.base, "major") if bump == "major" else boundary.base
    else:
        cumulative = bump_since_stable if bump_since_stable is not None else bump
        if cumulative is None:
            line = boundary.base
        else:
            line = max(
                apply_bump(stable_tag.version, cumulative),
                boundary.base,
                key=lambda version: version.precedence,
            )
    version = line if channel is None else next_prerelease(line, channel, tags)
    return ReleasePlan("inflight", version, eligible)


def build_release_notes(version: Version, commits: tuple[Commit, ...]) -> str:
    header = f"Release {format_version(version)}"
    if not commits:
        return header
    bullets = "\n".join(f"- `{commit.sha[:7]}` {commit.subject}" for commit in commits)
    return f"{header}\n\n## Commits\n\n{bullets}"


def _sanitize(text: object, secrets: tuple[str, ...] = ()) -> str:
    cleaned = str(text)
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "***")
    return " ".join(cleaned.split())


def _validate_repository(repository: str) -> str:
    if not isinstance(repository, str) or REPOSITORY_RE.fullmatch(repository) is None:
        raise InputError(f"repository must be in owner/name form, got {repository!r}")
    owner, name = repository.split("/", 1)
    if owner in (".", "..") or name in (".", ".."):
        raise InputError(f"repository must be in owner/name form, got {repository!r}")
    return repository


def _validate_sha(value: str, label: str = "sha") -> str:
    if not isinstance(value, str):
        raise InputError(f"{label} must be a full 40-character hexadecimal commit sha")
    text = value.strip().lower()
    if SHA_RE.fullmatch(text) is None:
        raise InputError(f"{label} must be a full 40-character hexadecimal commit sha")
    return text


def validate_api_url(value: str) -> str:
    if not isinstance(value, str):
        raise InputError("GITHUB_API_URL must be an https URL")
    text = value.strip()
    if not text:
        raise InputError("GITHUB_API_URL must not be empty")
    if any(character.isspace() or ord(character) < 32 for character in text):
        raise InputError("GITHUB_API_URL must not contain whitespace or control characters")
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError as exc:
        raise InputError("GITHUB_API_URL is not a valid URL") from exc
    if parsed.scheme != "https":
        raise InputError("GITHUB_API_URL must use https")
    if not parsed.hostname:
        raise InputError("GITHUB_API_URL must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise InputError("GITHUB_API_URL must not include credentials")
    if parsed.query or parsed.fragment:
        raise InputError("GITHUB_API_URL must not include a query or fragment")
    try:
        parsed.port
    except ValueError as exc:
        raise InputError("GITHUB_API_URL has an invalid port") from exc
    return text.rstrip("/")


def _run_git(
    args: list[str],
    *,
    cwd: Optional[str] = None,
    timeout: int = GIT_TIMEOUT_SECONDS,
) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            cwd=cwd,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]} timed out after {timeout} seconds") from exc
    except OSError as exc:
        raise GitError(f"git execution failed: {_sanitize(exc)}") from exc
    if result.returncode != 0:
        stderr_lines = (result.stderr or "").strip().splitlines()
        detail = stderr_lines[-1] if stderr_lines else f"exit code {result.returncode}"
        raise GitError(f"git {args[0]} failed: {_sanitize(detail)}")
    return result.stdout


def _parse_log_output(output: str) -> list[Commit]:
    commits: list[Commit] = []
    for block in output.split(RECORD_SEPARATOR):
        if not block.strip():
            continue
        fields = block.strip("\n").split(FIELD_SEPARATOR)
        if len(fields) != 3:
            raise GitError("git log returned a malformed commit record")
        sha, subject, body = fields
        if SHA_RE.fullmatch(sha) is None:
            raise GitError("git log returned a malformed commit sha")
        commits.append(Commit(sha.lower(), subject, body.rstrip("\n")))
    return commits


class GitClient:
    def __init__(
        self,
        runner: Optional[Callable[[list[str]], str]] = None,
        cwd: Optional[str] = None,
    ) -> None:
        self._runner = runner if runner is not None else lambda args: _run_git(args, cwd=cwd)

    def reachable_tags(self, head_sha: str) -> list[TagRef]:
        head_sha = _validate_sha(head_sha, "head sha")
        output = self._runner(
            [
                "for-each-ref",
                f"--merged={head_sha}",
                "--format=%(refname:short)%09%(objecttype)%09%(*objecttype)%09%(objectname)%09%(*objectname)",
                "refs/tags",
            ]
        )
        tags: list[TagRef] = []
        for line in output.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) != 5:
                raise GitError("git for-each-ref returned a malformed tag record")
            name, object_type, peeled_type, object_name, peeled = parts
            if not name:
                raise GitError("git for-each-ref returned a tag without a name")
            if object_type == "commit":
                commit = object_name
            elif peeled_type == "commit":
                commit = peeled
            else:
                continue
            if SHA_RE.fullmatch(commit) is None:
                raise GitError("git for-each-ref returned a malformed commit sha")
            tags.append(TagRef(name, commit.lower(), parse_version_tag(name)))
        return tags

    def head_commit(self, head_sha: str) -> Commit:
        head_sha = _validate_sha(head_sha, "head sha")
        output = self._runner(["log", "-1", f"--format={GIT_LOG_FORMAT}", head_sha])
        commits = _parse_log_output(output)
        if not commits:
            raise GitError(f"commit {head_sha} not found in repository history")
        if len(commits) != 1:
            raise GitError("git log returned more than one commit for a single head")
        return commits[0]

    def commits_since(self, head_sha: str, stop_shas: list[str]) -> list[Commit]:
        head_sha = _validate_sha(head_sha, "head sha")
        stops = [_validate_sha(stop_sha, "stop sha") for stop_sha in stop_shas]
        args = ["log", f"--format={GIT_LOG_FORMAT}", head_sha]
        if stops:
            args += ["--not", *stops]
        return _parse_log_output(self._runner(args))


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler())


def _urllib_transport(request: urllib.request.Request) -> tuple[int, bytes]:
    try:
        with _NO_REDIRECT_OPENER.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except OSError:
            body = b""
        finally:
            try:
                exc.close()
            except OSError:
                pass
        return exc.code, body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise NetworkError(f"github request failed: {_sanitize(reason)}") from exc


def _is_already_exists_response(status: int, raw: bytes) -> bool:
    if status != 422:
        return False
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        return False
    if not isinstance(parsed, dict):
        return False
    if str(parsed.get("message", "")).strip().lower() == "reference already exists":
        return True
    errors = parsed.get("errors")
    if not isinstance(errors, list):
        return False
    for error in errors:
        if not isinstance(error, dict):
            continue
        if error.get("resource") != "Release" or error.get("field") != "tag_name":
            continue
        if str(error.get("code", "")).lower() != "already_exists":
            continue
        return True
    return False


def _api_error(method: str, path: str, status: int, raw: bytes, secret: str = "") -> Exception:
    message = ""
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                message = _sanitize(parsed.get("message", ""), (secret,))
        except ValueError:
            message = _sanitize(raw.decode("utf-8", "replace")[:200], (secret,))
    if _is_already_exists_response(status, raw):
        return RefAlreadyExists(f"already exists on {path}")
    if 300 <= status < 400:
        return ApiError(f"github {method} {path} returned redirect http {status}; redirects are not followed")
    if status in (401, 403):
        return AuthorizationError(f"github {method} {path} rejected with http {status}")
    if status == 404:
        return NotFoundError(f"github {method} {path} not found (http 404)")
    if status >= 500 or status == 429:
        return ApiError(f"github {method} {path} failed with http {status}")
    return ValidationError(f"github {method} {path} rejected (http {status}): {message}")


def _api_object(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("github response is missing an object")
    obj = data.get("object")
    if not isinstance(obj, dict):
        raise ValidationError("github response is missing an object payload")
    return obj


class GitHubClient:
    def __init__(
        self,
        token: str,
        repository: str,
        api_url: str = DEFAULT_API_URL,
        transport: Optional[Callable[[urllib.request.Request], tuple[int, bytes]]] = None,
    ) -> None:
        _validate_repository(repository)
        if not isinstance(token, str) or not token.strip():
            raise InputError("RELEASE_TOKEN is required for GitHub API authentication")
        self._token = token.strip()
        self._repository = repository
        self._base_url = validate_api_url(api_url)
        self._transport = transport if transport is not None else _urllib_transport

    def _request(self, method: str, path: str, payload: Optional[dict[str, Any]] = None) -> Any:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(f"{self._base_url}{path}", data=body, method=method)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", "envai-pii-release")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        try:
            status, raw = self._transport(request)
        except NetworkError as exc:
            sanitized = _sanitize(exc, (self._token,))
            if sanitized != str(exc):
                raise NetworkError(sanitized) from exc
            raise
        except FatalError:
            raise
        except Exception as exc:
            raise NetworkError(f"github transport failed: {type(exc).__name__}") from exc
        if status >= 400:
            raise _api_error(method, path, status, raw, self._token)
        if 300 <= status < 400:
            raise _api_error(method, path, status, raw, self._token)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise ApiError(f"github {method} {path} returned malformed json") from exc

    def get_release(self, tag: str) -> Optional[dict[str, Any]]:
        encoded = urllib.parse.quote(tag, safe="")
        try:
            release = self._request("GET", f"/repos/{self._repository}/releases/tags/{encoded}")
        except NotFoundError:
            return None
        if release is not None and not isinstance(release, dict):
            raise ValidationError(f"release {tag} response is not an object")
        return release

    def get_ref_commit(self, tag: str) -> Optional[str]:
        encoded = urllib.parse.quote(tag, safe="")
        data = self._request("GET", f"/repos/{self._repository}/git/ref/tags/{encoded}")
        obj = _api_object(data)
        for _ in range(MAX_TAG_PEEL_DEPTH):
            object_type = obj.get("type")
            object_sha = obj.get("sha")
            if object_type == "commit":
                if not isinstance(object_sha, str) or SHA_RE.fullmatch(object_sha) is None:
                    raise ValidationError(f"tag {tag} points to a malformed commit sha")
                return object_sha.lower()
            if object_type != "tag":
                raise ValidationError(f"tag {tag} points to unsupported object type {object_type!r}")
            if not isinstance(object_sha, str) or SHA_RE.fullmatch(object_sha) is None:
                raise ValidationError(f"tag {tag} points to a malformed tag sha")
            tag_data = self._request("GET", f"/repos/{self._repository}/git/tags/{object_sha}")
            obj = _api_object(tag_data)
        raise ValidationError(f"tag {tag} exceeds {MAX_TAG_PEEL_DEPTH} nested tag levels")

    def create_ref(self, tag: str, sha: str) -> Any:
        sha = _validate_sha(sha)
        return self._request(
            "POST",
            f"/repos/{self._repository}/git/refs",
            {"ref": f"refs/tags/{tag}", "sha": sha},
        )

    def create_release(
        self,
        *,
        tag: str,
        name: str,
        body: str,
        prerelease: bool,
        target_commitish: str,
    ) -> dict[str, Any]:
        target_commitish = _validate_sha(target_commitish, "target commitish")
        payload = {
            "tag_name": tag,
            "target_commitish": target_commitish,
            "name": name,
            "body": body,
            "draft": False,
            "prerelease": prerelease,
        }
        release = self._request("POST", f"/repos/{self._repository}/releases", payload)
        if not isinstance(release, dict):
            raise ValidationError(f"release {tag} response is not an object")
        return release


@dataclass(frozen=True)
class PublishOutputs:
    released: bool
    idempotent: bool
    version: str
    tag: str
    release_url: str
    reason: str


def no_release_outputs(reason: str) -> PublishOutputs:
    return PublishOutputs(False, False, "", "", "", reason)


def _channel_matches(version: Optional[Version], channel: Optional[str]) -> bool:
    if version is None:
        return False
    if channel is None:
        return not version.is_prerelease
    return version.channel == channel


def _advance_version(version: Version) -> Version:
    if version.is_prerelease:
        return Version(
            version.major,
            version.minor,
            version.patch,
            version.channel,
            (version.counter or 0) + 1,
        )
    return Version(version.major, version.minor, version.patch + 1)


def _require_ref_sha(github: GitHubClient, tag: str, sha: str) -> None:
    claimed = github.get_ref_commit(tag)
    if claimed != sha:
        raise ValidationError(
            f"release tag {tag} resolves to {claimed or 'nothing'}, expected {sha}"
        )


def _validate_https_url(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{label} must be a non-empty URL")
    if any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        raise ValidationError(f"{label} must not contain whitespace or control characters")
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError as exc:
        raise ValidationError(f"{label} is not a valid URL") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValidationError(f"{label} must be an https URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError(f"{label} must not include credentials")
    return value


def _validate_release_target(release: dict[str, Any], sha: str, *, existing: bool) -> None:
    target = release.get("target_commitish")
    if target is None:
        return
    if not isinstance(target, str) or not target.strip():
        raise ValidationError("release target_commitish is malformed")
    candidate = target.strip()
    if SHA_RE.fullmatch(candidate) is not None:
        if candidate.lower() != sha:
            raise ValidationError(
                f"release target commitish {candidate} does not match {sha}"
            )
        return
    if not existing:
        raise ValidationError(
            f"created release target commitish {candidate!r} is not the expected commit sha"
        )


def _validate_release(
    release: dict[str, Any],
    tag: str,
    version: Version,
    sha: str,
    github: GitHubClient,
    *,
    existing: bool,
) -> str:
    if release.get("tag_name") != tag:
        raise ValidationError(
            f"release {tag} reported tag_name {release.get('tag_name')!r}"
        )
    draft = release.get("draft")
    if not isinstance(draft, bool):
        raise ValidationError(f"release {tag} is missing a boolean draft field")
    prerelease = release.get("prerelease")
    if not isinstance(prerelease, bool):
        raise ValidationError(f"release {tag} is missing a boolean prerelease field")
    wrong_channel = prerelease != version.is_prerelease
    if existing and (draft or wrong_channel):
        raise RefAlreadyExists(f"release {tag} is a draft or belongs to another channel")
    if draft:
        raise ValidationError(f"release {tag} was reported as a draft")
    if wrong_channel:
        raise ValidationError(f"release {tag} prerelease flag does not match the release channel")
    _validate_release_target(release, sha, existing=existing)
    _require_ref_sha(github, tag, sha)
    return _validate_https_url(release.get("html_url"), "release html_url")


def _already_released_outputs(
    release: dict[str, Any],
    tag: str,
    version: Version,
    sha: str,
    github: GitHubClient,
) -> PublishOutputs:
    release_url = _validate_release(
        release, tag, version, sha, github, existing=True
    )
    return PublishOutputs(
        False,
        True,
        format_version(version),
        tag,
        release_url,
        "already_released",
    )


def _ensure_release(
    tag: str,
    version: Version,
    notes: str,
    sha: str,
    github: GitHubClient,
    *,
    recovery_reason: str,
) -> PublishOutputs:
    release = github.get_release(tag)
    if release is not None:
        return _already_released_outputs(release, tag, version, sha, github)
    try:
        created = github.create_release(
            tag=tag,
            name=tag,
            body=notes,
            prerelease=version.is_prerelease,
            target_commitish=sha,
        )
    except RefAlreadyExists:
        for _ in range(MAX_RELEASE_READ_ATTEMPTS):
            release = github.get_release(tag)
            if release is not None:
                return _already_released_outputs(release, tag, version, sha, github)
        existing = github.get_ref_commit(tag)
        if existing != sha:
            raise
        raise ApiError(
            f"release {tag} exists as a tag but no published release could be observed"
        )
    release_url = _validate_release(
        created, tag, version, sha, github, existing=False
    )
    return PublishOutputs(
        True,
        False,
        format_version(version),
        tag,
        release_url,
        recovery_reason,
    )


def _eligible_commits(
    sha: str,
    tags: list[TagRef],
    head_tags: list[TagRef],
    channel: Optional[str],
    git: GitClient,
) -> tuple[Commit, ...]:
    remaining = [tag for tag in tags if tag not in head_tags]
    boundary = select_boundary(remaining, channel)
    commits = git.commits_since(sha, list(boundary.stop_shas))
    return tuple(commit for commit in commits if commit_is_eligible(commit))


def _replay_or_recover(
    channel: Optional[str],
    sha: str,
    tags: list[TagRef],
    git: GitClient,
    github: GitHubClient,
) -> Optional[PublishOutputs]:
    head_tags = [
        tag for tag in tags if tag.commit == sha and _channel_matches(tag.version, channel)
    ]
    if not head_tags:
        return None
    top = max(head_tags, key=lambda tag: tag.version.precedence)
    try:
        claimed = github.get_ref_commit(top.name)
    except NotFoundError:
        claimed = None
    if claimed != sha:
        return _claim_and_release(
            sha,
            top.version,
            _eligible_commits(sha, tags, head_tags, channel, git),
            github,
            created_reason="release_created",
        )
    release = github.get_release(top.name)
    if release is not None:
        try:
            return _already_released_outputs(
                release, top.name, top.version, sha, github
            )
        except RefAlreadyExists:
            return _claim_and_release(
                sha,
                top.version,
                _eligible_commits(sha, tags, head_tags, channel, git),
                github,
                created_reason="release_created",
            )
    eligible = _eligible_commits(sha, tags, head_tags, channel, git)
    try:
        return _ensure_release(
            top.name,
            top.version,
            build_release_notes(top.version, eligible),
            sha,
            github,
            recovery_reason="tag_only_recovery",
        )
    except RefAlreadyExists:
        return _claim_and_release(
            sha,
            top.version,
            eligible,
            github,
            created_reason="release_created",
        )


def _claim_and_release(
    sha: str,
    version: Version,
    eligible: tuple[Commit, ...],
    github: GitHubClient,
    *,
    created_reason: str,
) -> PublishOutputs:
    start_tag = tag_name(version)
    current = version
    for _ in range(MAX_CLAIM_ATTEMPTS):
        tag = tag_name(current)
        try:
            github.create_ref(tag, sha)
        except RefAlreadyExists:
            try:
                existing = github.get_ref_commit(tag)
            except NotFoundError:
                existing = None
            if existing == sha:
                try:
                    return _ensure_release(
                        tag,
                        current,
                        build_release_notes(current, eligible),
                        sha,
                        github,
                        recovery_reason="tag_only_recovery",
                    )
                except RefAlreadyExists:
                    current = _advance_version(current)
                    continue
            current = _advance_version(current)
            continue
        try:
            return _ensure_release(
                tag,
                current,
                build_release_notes(current, eligible),
                sha,
                github,
                recovery_reason=created_reason,
            )
        except RefAlreadyExists:
            current = _advance_version(current)
            continue
    raise FatalError(
        f"exhausted {MAX_CLAIM_ATTEMPTS} tag claim attempts starting at {start_tag}"
    )


def publish(
    repository: str,
    branch: str,
    sha: str,
    *,
    git: GitClient,
    github: GitHubClient,
) -> PublishOutputs:
    _validate_repository(repository)
    if not isinstance(branch, str) or branch not in RELEASE_BRANCH_CHANNELS:
        raise InputError(
            f"unsupported release branch {branch!r}; expected one of dev, alpha, beta, main"
        )
    sha = _validate_sha(sha)
    channel = RELEASE_BRANCH_CHANNELS[branch]
    tags = git.reachable_tags(sha)
    head = git.head_commit(sha)
    if is_skip_commit(head):
        return no_release_outputs("skip_ci_head_commit")
    replay = _replay_or_recover(channel, sha, tags, git, github)
    if replay is not None:
        return replay
    boundary = select_boundary(tags, channel)
    commits = git.commits_since(sha, list(boundary.stop_shas))
    bump_since_stable: Optional[str] = None
    if boundary.mode == "inflight":
        stable_tag = _top_stable_tag(tags)
        if stable_tag is not None:
            since_stable = git.commits_since(sha, [stable_tag.commit])
            bumps = [
                commit_bump(commit.subject, commit.body)
                for commit in since_stable
                if commit_is_eligible(commit)
            ]
            bump_since_stable = max_bump(bumps)
    plan = finalize_release(
        boundary,
        commits,
        channel,
        tags,
        bump_since_stable=bump_since_stable,
    )
    if plan.version is None:
        return no_release_outputs("no_eligible_commits")
    created_reason = (
        "promotion_release_created"
        if plan.mode == "inflight" and channel is None
        else "release_created"
    )
    return _claim_and_release(sha, plan.version, plan.eligible, github, created_reason=created_reason)


def _output_line(name: str, value: object) -> str:
    text = str(value)
    if any(
        character in "\r\n" or ord(character) < 32 or ord(character) == 127
        for character in text
    ):
        raise ValidationError(f"output {name} must be a single line")
    return f"{name}={text}"


def write_outputs(path: str, outputs: PublishOutputs) -> None:
    release_url = (
        _validate_https_url(outputs.release_url, "release_url")
        if outputs.release_url
        else ""
    )
    lines = [
        _output_line("released", str(outputs.released).lower()),
        _output_line("idempotent", str(outputs.idempotent).lower()),
        _output_line("version", outputs.version),
        _output_line("tag", outputs.tag),
        _output_line("release_url", release_url),
        _output_line("reason", outputs.reason),
    ]
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="release.py",
        description="Collision-safe GitHub release engine",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("publish", help="Plan, claim and create the release for one commit")
    run.add_argument("--repository", required=True, help="Owner/name of the GitHub repository")
    run.add_argument("--branch", required=True, help="Branch the commit was pushed to")
    run.add_argument("--sha", required=True, help="Head commit sha to release")
    run.add_argument("--github-output", required=True, help="Path of the GitHub Actions output file")
    return parser


def _execute(
    args: argparse.Namespace,
    token: Optional[str],
    api_url: str,
    *,
    transport: Optional[Callable[[urllib.request.Request], tuple[int, bytes]]] = None,
) -> tuple[PublishOutputs, bool]:
    if not token or not token.strip():
        print(
            "error: required secret RELEASE_TOKEN is not configured; "
            "release publication never falls back to GITHUB_TOKEN",
            file=sys.stderr,
        )
        return no_release_outputs("missing_token"), True
    try:
        git = GitClient()
        github = GitHubClient(
            token=token,
            repository=args.repository,
            api_url=api_url,
            transport=transport,
        )
        return publish(args.repository, args.branch, args.sha, git=git, github=github), False
    except FatalError as exc:
        print(f"error: {_sanitize(exc, (token,))}", file=sys.stderr)
        return no_release_outputs("fatal_error"), True


def main(
    argv: Optional[list[str]] = None,
    *,
    transport: Optional[Callable[[urllib.request.Request], tuple[int, bytes]]] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> int:
    env = os.environ if environ is None else environ
    args = build_parser().parse_args(argv)
    token = (env.get("RELEASE_TOKEN") or "").strip()
    api_url = (env.get("GITHUB_API_URL") or "").strip() or DEFAULT_API_URL
    outputs, failed = _execute(args, token or None, api_url, transport=transport)
    if args.github_output:
        try:
            write_outputs(args.github_output, outputs)
        except (OSError, FatalError) as exc:
            print(f"error: unable to write outputs: {_sanitize(exc)}", file=sys.stderr)
            return 1
    summary = (
        f"released={str(outputs.released).lower()} "
        f"idempotent={str(outputs.idempotent).lower()} "
        f"version={outputs.version} tag={outputs.tag} reason={outputs.reason}"
    )
    print(summary)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
