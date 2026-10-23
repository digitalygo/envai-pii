import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / ".github" / "scripts" / "release.py"
SPEC = importlib.util.spec_from_file_location("ci_release_engine", SCRIPT_PATH)
engine = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = engine
assert SPEC.loader is not None
SPEC.loader.exec_module(engine)

OWNER_REPO = "owner/repo"
API_BASE = engine.DEFAULT_API_URL


def sha(label: str) -> str:
    return hashlib.sha1(label.encode("utf-8")).hexdigest()


def pinned_action_refs(text: str, action: str) -> list[str]:
    refs = re.findall(
        rf"(?m)^\s*(?:-\s+)?uses: {re.escape(action)}@(\S+)\s*$", text
    )
    if not refs:
        raise AssertionError(f"action is not used: {action}")
    if any(re.fullmatch(r"[0-9a-f]{40}", ref) is None for ref in refs):
        raise AssertionError(
            f"action must be pinned to a full commit SHA: {action} -> {refs}"
        )
    return refs


def commit(label: str, subject: str, body: str = "") -> engine.Commit:
    return engine.Commit(sha(label), subject, body)


def tag_ref(name: str, label: str, version: engine.Version | None = None) -> engine.TagRef:
    if version is None:
        version = engine.parse_version_tag(name)
    return engine.TagRef(name, sha(label), version)


def release_payload(
    tag: str,
    target: str,
    *,
    prerelease: bool = False,
    draft: bool = False,
    base_url: str = API_BASE,
    **overrides,
) -> dict:
    payload = {
        "tag_name": tag,
        "name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "target_commitish": target,
        "html_url": f"{base_url}/releases/tag/{tag}",
    }
    payload.update(overrides)
    return payload


class FakeGitRunner:
    def __init__(self, history=None, tags=None):
        self.history = list(history) if history is not None else []
        self.tags = list(tags) if tags is not None else []
        self.calls = []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(list(args))
        if args[0] == "for-each-ref":
            return "".join(f"{tag.name}\tcommit\t\t{tag.commit}\t\n" for tag in self.tags)
        if args[0] == "log":
            rest = args[1:]
            if "-1" in rest:
                target = rest[-1]
                return self._format([item for item in self.history if item.sha == target])
            stops = set()
            if "--not" in rest:
                stops = set(rest[rest.index("--not") + 1 :])
            return self._format([item for item in self.history if item.sha not in stops])
        raise AssertionError(f"unexpected git invocation: {args}")

    @staticmethod
    def _format(commits: list[engine.Commit]) -> str:
        return "".join(
            f"{item.sha}{engine.FIELD_SEPARATOR}{item.subject}{engine.FIELD_SEPARATOR}"
            f"{item.body}{engine.RECORD_SEPARATOR}\n"
            for item in commits
        )


class FakeGitHubApi:
    def __init__(self, refs=None, releases=None, base_url: str = API_BASE):
        self.refs = dict(refs or {})
        self.releases = dict(releases or {})
        self.base_url = base_url
        self.calls = []

    def transport(self, request):
        method = request.get_method()
        path = urllib.parse.urlparse(request.full_url).path
        payload = json.loads(request.data) if request.data else None
        self.calls.append((method, path, payload, dict(request.headers)))
        if method == "POST" and path.endswith("/git/refs"):
            ref = payload["ref"]
            tag = ref.removeprefix("refs/tags/")
            if tag in self.refs:
                return 422, b'{"message": "Reference already exists"}'
            self.refs[tag] = payload["sha"]
            return 201, json.dumps({"ref": ref, "object": {"sha": payload["sha"]}}).encode()
        if method == "GET" and "/releases/tags/" in path:
            tag = urllib.parse.unquote(path.rsplit("/", 1)[1])
            if tag in self.releases:
                return 200, json.dumps(self.releases[tag]).encode()
            return 404, b'{"message": "Not Found"}'
        if method == "POST" and path.endswith("/releases"):
            tag = payload["tag_name"]
            if tag in self.releases:
                return 422, (
                    b'{"message": "Validation Failed", "errors": [{"resource": "Release",'
                    b' "field": "tag_name", "code": "already_exists"}]}'
                )
            release = release_payload(
                tag,
                payload["target_commitish"],
                prerelease=payload["prerelease"],
                draft=payload["draft"],
                base_url=self.base_url,
                name=payload["name"],
            )
            self.releases[tag] = release
            return 201, json.dumps(release).encode()
        if method == "GET" and path.startswith("/repos/") and "/git/ref/tags/" in path:
            tag = urllib.parse.unquote(path.rsplit("/", 1)[1])
            if tag in self.refs:
                return 200, json.dumps({"object": {"type": "commit", "sha": self.refs[tag]}}).encode()
            return 404, b'{"message": "Not Found"}'
        if method == "GET" and "/git/tags/" in path:
            object_sha = path.rsplit("/", 1)[1]
            return 200, json.dumps({"object": {"type": "commit", "sha": object_sha}}).encode()
        raise AssertionError(f"unexpected github call: {method} {path}")

    def release_posts(self) -> list[dict]:
        return [
            payload
            for method, path, payload, _headers in self.calls
            if method == "POST" and path.endswith("/releases")
        ]


class RacingReleaseTransport:
    def __init__(self, api: FakeGitHubApi, *, insert: bool = True):
        self.api = api
        self.insert = insert
        self.raced = False

    def __call__(self, request):
        method = request.get_method()
        path = urllib.parse.urlparse(request.full_url).path
        if method == "POST" and path.endswith("/releases") and not self.raced:
            self.raced = True
            payload = json.loads(request.data)
            tag = payload["tag_name"]
            if self.insert:
                self.api.releases.setdefault(
                    tag,
                    release_payload(
                        tag,
                        payload["target_commitish"],
                        prerelease=payload["prerelease"],
                        base_url=self.api.base_url,
                        name=payload["name"],
                    ),
                )
            return 422, (
                b'{"message": "Validation Failed", "errors": [{"resource": "Release",'
                b' "field": "tag_name", "code": "already_exists"}]}'
            )
        return self.api.transport(request)


class RefMovedAfterReleaseTransport:
    def __init__(self, api: FakeGitHubApi, tag: str, foreign_sha: str):
        self.api = api
        self.tag = tag
        self.foreign_sha = foreign_sha

    def __call__(self, request):
        status, body = self.api.transport(request)
        method = request.get_method()
        path = urllib.parse.urlparse(request.full_url).path
        if method == "POST" and path.endswith("/releases") and status < 400:
            self.api.refs[self.tag] = self.foreign_sha
        return status, body


class ForeignReleaseOnCreateTransport:
    def __init__(self, api: FakeGitHubApi, tag: str, foreign_sha: str):
        self.api = api
        self.tag = tag
        self.foreign_sha = foreign_sha
        self.triggered = False

    def __call__(self, request):
        method = request.get_method()
        path = urllib.parse.urlparse(request.full_url).path
        if method == "POST" and path.endswith("/releases") and not self.triggered:
            self.triggered = True
            self.api.refs[self.tag] = self.foreign_sha
            return 422, (
                b'{"message": "Validation Failed", "errors": [{"resource": "Release",'
                b' "field": "tag_name", "code": "already_exists"}]}'
            )
        return self.api.transport(request)


class InconsistentReleaseResponseTransport:
    def __init__(self, api: FakeGitHubApi, **overrides):
        self.api = api
        self.overrides = overrides

    def __call__(self, request):
        status, body = self.api.transport(request)
        method = request.get_method()
        path = urllib.parse.urlparse(request.full_url).path
        if method == "POST" and path.endswith("/releases") and status < 400:
            release = json.loads(body)
            release.update(self.overrides)
            return status, json.dumps(release).encode()
        return status, body


class MissingRefOnCollisionTransport:
    def __init__(self, api: FakeGitHubApi):
        self.api = api
        self.triggered = False

    def __call__(self, request):
        method = request.get_method()
        path = urllib.parse.urlparse(request.full_url).path
        if method == "POST" and path.endswith("/git/refs") and not self.triggered:
            self.triggered = True
            return 422, b'{"message": "Reference already exists"}'
        return self.api.transport(request)


def make_github(transport) -> engine.GitHubClient:
    return engine.GitHubClient("token", OWNER_REPO, transport=transport)


class TemporaryGitRepository:
    def __init__(self):
        self._temp = tempfile.TemporaryDirectory()
        self.path = Path(self._temp.name)

    def __enter__(self):
        self.run("init", "-q")
        self.run("symbolic-ref", "HEAD", "refs/heads/main")
        self.run("config", "user.email", "ci@example.com")
        self.run("config", "user.name", "CI")
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._temp.cleanup()

    def run(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=60,
        )
        if result.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
        return result.stdout.strip()

    def commit(self, subject: str) -> str:
        self.run("commit", "--allow-empty", "-q", "-m", subject)
        return self.run("rev-parse", "HEAD")

    def tag(self, name: str, target: str | None = None, *, annotated: bool = False) -> None:
        args = ["tag"]
        if annotated:
            args += ["-a", name, "-m", name]
        else:
            args += [name]
        if target is not None:
            args.append(target)
        self.run(*args)


@contextmanager
def change_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class TestVersioning(unittest.TestCase):
    def test_parse_version_tags(self):
        cases = {
            "v1.2.3": engine.Version(1, 2, 3),
            "v1.2.3-dev.4": engine.Version(1, 2, 3, "dev", 4),
            "v1.2.3-alpha.2": engine.Version(1, 2, 3, "alpha", 2),
            "v1.2.3-beta.10": engine.Version(1, 2, 3, "beta", 10),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(engine.parse_version_tag(raw), expected)

    def test_parse_rejects_noncanonical_tags(self):
        for raw in (
            "1.2.3",
            "v1.2",
            "v1.2.3.4",
            "v01.2.3",
            "v1.02.3",
            "v1.2.03",
            "v1.2.3-dev",
            "v1.2.3-dev.0",
            "v1.2.3-gamma.1",
            "v1.2.3-alpha.01",
            "release-1.2.3",
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(engine.parse_version_tag(raw))

    def test_format_and_tag_name(self):
        stable = engine.Version(1, 2, 3)
        prerelease = engine.Version(1, 2, 3, "dev", 7)
        self.assertEqual(engine.format_version(stable), "1.2.3")
        self.assertEqual(engine.tag_name(stable), "v1.2.3")
        self.assertEqual(engine.format_version(prerelease), "1.2.3-dev.7")
        self.assertEqual(engine.tag_name(prerelease), "v1.2.3-dev.7")

    def test_precedence_orders_channels_and_stable(self):
        base = engine.Version(1, 2, 3)
        dev = base.with_channel("dev", 9)
        alpha = base.with_channel("alpha", 1)
        beta = base.with_channel("beta", 1)
        self.assertLess(dev.precedence, alpha.precedence)
        self.assertLess(alpha.precedence, beta.precedence)
        self.assertLess(beta.precedence, base.precedence)
        self.assertEqual(base.core, engine.Version(1, 2, 3))

    def test_next_prerelease_uses_only_the_same_channel(self):
        line = engine.Version(1, 2, 3)
        tags = [
            tag_ref("v1.2.3-dev.2", "c0"),
            tag_ref("v1.2.3-alpha.9", "c1"),
            tag_ref("v1.2.3-beta.4", "c2"),
        ]
        self.assertEqual(engine.next_prerelease(line, "dev", tags), engine.Version(1, 2, 3, "dev", 3))
        self.assertEqual(engine.next_prerelease(line, "alpha", tags), engine.Version(1, 2, 3, "alpha", 10))
        self.assertEqual(engine.next_prerelease(line, "beta", tags), engine.Version(1, 2, 3, "beta", 5))
        self.assertEqual(engine.next_prerelease(line, "dev", []), engine.Version(1, 2, 3, "dev", 1))
        self.assertEqual(
            engine.next_prerelease(
                line,
                "dev",
                [engine.TagRef("v1.2.3-dev", sha("c9"), engine.Version(1, 2, 3, "dev"))],
            ),
            engine.Version(1, 2, 3, "dev", 1),
        )

    def test_advance_version(self):
        self.assertEqual(engine._advance_version(engine.Version(1, 2, 3)), engine.Version(1, 2, 4))
        self.assertEqual(
            engine._advance_version(engine.Version(1, 2, 3, "dev", 4)),
            engine.Version(1, 2, 3, "dev", 5),
        )


class TestCommitClassification(unittest.TestCase):
    def test_release_bearing_types(self):
        cases = (
            ("feat: add search", "", "minor"),
            ("feat(api): add search", "", "minor"),
            ("fix: repair search", "", "patch"),
            ("chore: update deps", "", "patch"),
            ("refactor: reshape module", "", "patch"),
            ("build: change image", "", "patch"),
        )
        for subject, body, expected in cases:
            with self.subTest(subject=subject):
                self.assertEqual(engine.commit_bump(subject, body), expected)

    def test_non_release_bearing_types(self):
        for subject in (
            "ci: tune workflow",
            "docs: explain release",
            "test: add cases",
            "style: format code",
            "perf: speed up",
            "unknown: thing",
            "feat add search",
            "feat:",
            "FEAT: uppercase",
        ):
            with self.subTest(subject=subject):
                self.assertIsNone(engine.commit_bump(subject, ""))

    def test_breaking_marker_only_for_feat_and_fix(self):
        self.assertEqual(engine.commit_bump("feat!: drop support", ""), "major")
        self.assertEqual(engine.commit_bump("fix!: change contract", ""), "major")
        self.assertEqual(engine.commit_bump("chore!: drop support", ""), "patch")
        self.assertEqual(engine.commit_bump("docs!: drop support", ""), None)

    def test_breaking_footer_only_for_feat_and_fix(self):
        self.assertEqual(engine.commit_bump("feat: change", "BREAKING CHANGE: old API removed"), "major")
        self.assertEqual(engine.commit_bump("fix: change", "BREAKING-CHANGE: old API removed"), "major")
        self.assertEqual(engine.commit_bump("chore: change", "BREAKING CHANGE: old API removed"), "patch")
        self.assertEqual(engine.commit_bump("feat: change", "  BREAKING CHANGE: old API removed"), "major")
        self.assertEqual(engine.commit_bump("feat: change", "BREAKING CHANGE old API removed"), "minor")

    def test_max_bump_ranks(self):
        self.assertIsNone(engine.max_bump([None, None]))
        self.assertEqual(engine.max_bump([None, "patch", "minor", "major"]), "major")
        self.assertEqual(engine.max_bump(["patch", "minor"]), "minor")

    def test_skip_marker_is_exact_and_case_insensitive(self):
        self.assertTrue(engine.is_skip_commit(commit("h", "fix: x [skip ci]")))
        self.assertTrue(engine.is_skip_commit(commit("h", "fix: x", "details\n\n[SKIP CI]")))
        self.assertFalse(engine.is_skip_commit(commit("h", "fix: x [ci skip]")))
        self.assertFalse(engine.is_skip_commit(commit("h", "fix: x skip ci")))
        self.assertFalse(engine.is_skip_commit(commit("h", "fix: x [skip-ci]")))
        self.assertFalse(engine.commit_is_eligible(commit("h", "fix: x [skip ci]")))
        self.assertTrue(engine.commit_is_eligible(commit("h", "fix: x")))
        self.assertFalse(engine.commit_is_eligible(commit("h", "docs: x")))

    def test_build_release_notes(self):
        version = engine.Version(1, 2, 3)
        self.assertEqual(engine.build_release_notes(version, ()), "Release 1.2.3")
        notes = engine.build_release_notes(version, (commit("a", "feat: one"),))
        self.assertIn("Release 1.2.3", notes)
        self.assertIn(f"`{sha('a')[:7]}` feat: one", notes)


class TestBoundaryAndPlanning(unittest.TestCase):
    def test_select_boundary_first(self):
        self.assertEqual(engine.select_boundary([]), engine.Boundary("first", (), None))
        self.assertEqual(
            engine.select_boundary([tag_ref("release-1", "c0")]),
            engine.Boundary("first", (), None),
        )

    def test_select_boundary_stable_and_inflight(self):
        stable = tag_ref("v1.0.0", "c0")
        self.assertEqual(
            engine.select_boundary([stable]),
            engine.Boundary("stable", (stable.commit,), engine.Version(1, 0, 0)),
        )
        alpha = tag_ref("v1.1.0-alpha.2", "c1")
        self.assertEqual(
            engine.select_boundary([stable, alpha]),
            engine.Boundary("inflight", (alpha.commit,), engine.Version(1, 1, 0)),
        )

    def test_select_boundary_channel_filters_other_prereleases(self):
        tags = [
            tag_ref("v1.0.0", "c0"),
            tag_ref("v1.1.0-dev.3", "c1"),
            tag_ref("v1.2.0-alpha.1", "c2"),
        ]
        self.assertEqual(engine.select_boundary(tags, "dev").stop_shas, (sha("c1"),))
        self.assertEqual(engine.select_boundary(tags, "alpha").stop_shas, (sha("c2"),))
        self.assertEqual(engine.select_boundary(tags, "beta").stop_shas, (sha("c0"),))
        self.assertEqual(engine.select_boundary(tags, "beta").base, engine.Version(1, 0, 0))

    def test_select_boundary_highest_precedence_wins(self):
        alpha = tag_ref("v1.2.0-alpha.5", "c1")
        beta = tag_ref("v1.2.0-beta.1", "c2")
        stable = tag_ref("v1.1.9", "c3")
        self.assertEqual(engine.select_boundary([alpha, beta, stable]).stop_shas, (beta.commit,))
        dev = tag_ref("v1.2.0-dev.9", "c4")
        self.assertEqual(engine.select_boundary([alpha, beta, dev, stable]).stop_shas, (beta.commit,))

    def test_first_release_every_channel(self):
        commits = [commit("h", "feat: initial")]
        for channel, expected in (
            ("dev", engine.Version(1, 0, 0, "dev", 1)),
            ("alpha", engine.Version(1, 0, 0, "alpha", 1)),
            ("beta", engine.Version(1, 0, 0, "beta", 1)),
            (None, engine.Version(1, 0, 0)),
        ):
            with self.subTest(channel=channel):
                plan = engine.finalize_release(engine.Boundary("first", (), None), commits, channel, [])
                self.assertEqual(plan.mode, "first")
                self.assertEqual(plan.version, expected)
                self.assertEqual(plan.eligible, tuple(commits))

    def test_first_release_without_eligible_commits(self):
        plan = engine.finalize_release(
            engine.Boundary("first", (), None),
            [commit("h", "docs: nothing")],
            None,
            [],
        )
        self.assertEqual(plan.mode, "none")
        self.assertIsNone(plan.version)

    def test_stable_bumps(self):
        tags = [tag_ref("v1.0.0", "c0")]
        boundary = engine.select_boundary(tags)
        cases = (
            ("fix: x", "", engine.Version(1, 0, 1)),
            ("chore: x", "", engine.Version(1, 0, 1)),
            ("refactor: x", "", engine.Version(1, 0, 1)),
            ("build: x", "", engine.Version(1, 0, 1)),
            ("feat: x", "", engine.Version(1, 1, 0)),
            ("feat!: x", "", engine.Version(2, 0, 0)),
            ("fix: x", "BREAKING CHANGE: x", engine.Version(2, 0, 0)),
            ("docs: x", "", None),
        )
        for subject, body, expected in cases:
            with self.subTest(subject=subject):
                plan = engine.finalize_release(boundary, [commit("h", subject, body)], None, tags)
                self.assertEqual(plan.version, expected)

    def test_stable_opens_channel_prerelease(self):
        tags = [tag_ref("v1.0.0", "c0")]
        boundary = engine.select_boundary(tags)
        plan = engine.finalize_release(boundary, [commit("h", "feat: x")], "dev", tags)
        self.assertEqual(plan.version, engine.Version(1, 1, 0, "dev", 1))

    def test_inflight_channel_advances_counter(self):
        tags = [tag_ref("v1.2.3-dev.2", "c0")]
        boundary = engine.select_boundary(tags, "dev")
        plan = engine.finalize_release(boundary, [commit("h", "fix: x")], "dev", tags)
        self.assertEqual(plan.mode, "inflight")
        self.assertEqual(plan.version, engine.Version(1, 2, 3, "dev", 3))

    def test_inflight_channel_without_eligible_is_none(self):
        tags = [tag_ref("v1.2.3-alpha.2", "c0")]
        boundary = engine.select_boundary(tags, "alpha")
        plan = engine.finalize_release(boundary, [commit("h", "docs: x")], "alpha", tags)
        self.assertEqual(plan.mode, "none")
        self.assertIsNone(plan.version)

    def test_inflight_major_opens_new_line(self):
        tags = [tag_ref("v1.2.3-dev.2", "c0")]
        boundary = engine.select_boundary(tags, "dev")
        plan = engine.finalize_release(boundary, [commit("h", "feat!: x")], "dev", tags)
        self.assertEqual(plan.version, engine.Version(2, 0, 0, "dev", 1))

    def test_inflight_main_promotes_without_new_commits(self):
        tags = [tag_ref("v1.0.0-alpha.2", "c0")]
        boundary = engine.select_boundary(tags)
        plan = engine.finalize_release(boundary, [], None, tags)
        self.assertEqual(plan.mode, "inflight")
        self.assertEqual(plan.version, engine.Version(1, 0, 0))

    def test_inflight_main_uses_cumulative_bump_since_stable(self):
        tags = [tag_ref("v1.0.0", "c0"), tag_ref("v1.0.1-alpha.1", "c1")]
        boundary = engine.select_boundary(tags)
        plan = engine.finalize_release(
            boundary,
            [commit("h", "docs: merge")],
            None,
            tags,
            bump_since_stable="minor",
        )
        self.assertEqual(plan.version, engine.Version(1, 1, 0))

    def test_inflight_main_without_stable_keeps_prerelease_core(self):
        tags = [tag_ref("v2.0.0-beta.3", "c0")]
        boundary = engine.select_boundary(tags)
        plan = engine.finalize_release(boundary, [commit("h", "fix: x")], None, tags)
        self.assertEqual(plan.version, engine.Version(2, 0, 0))

    def test_inflight_main_major_without_stable_opens_major(self):
        tags = [tag_ref("v1.2.3-dev.1", "c0")]
        boundary = engine.select_boundary(tags)
        plan = engine.finalize_release(boundary, [commit("h", "feat!: x")], None, tags)
        self.assertEqual(plan.version, engine.Version(2, 0, 0))

    def test_inflight_main_with_stable_and_no_bump_keeps_base(self):
        tags = [tag_ref("v0.9.0", "c0"), tag_ref("v1.0.0-alpha.1", "c1")]
        boundary = engine.select_boundary(tags)
        plan = engine.finalize_release(boundary, [], None, tags)
        self.assertEqual(plan.mode, "inflight")
        self.assertEqual(plan.version, engine.Version(1, 0, 0))


class TestPublishFlows(unittest.TestCase):
    def test_publish_first_stable(self):
        head = commit("h", "feat: initial")
        runner = FakeGitRunner([head], [])
        api = FakeGitHubApi()
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(runner),
            github=make_github(api.transport),
        )
        self.assertTrue(outputs.released)
        self.assertFalse(outputs.idempotent)
        self.assertEqual(outputs.version, "1.0.0")
        self.assertEqual(outputs.tag, "v1.0.0")
        self.assertEqual(outputs.reason, "release_created")
        self.assertEqual(api.release_posts()[0]["target_commitish"], head.sha)

    def test_publish_first_dev(self):
        head = commit("h", "feat: initial")
        api = FakeGitHubApi()
        outputs = engine.publish(
            OWNER_REPO,
            "dev",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], [])),
            github=make_github(api.transport),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.version, "1.0.0-dev.1")
        self.assertTrue(api.release_posts()[0]["prerelease"])

    def test_publish_no_eligible_commits(self):
        head = commit("h", "docs: nothing")
        api = FakeGitHubApi()
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], [])),
            github=make_github(api.transport),
        )
        self.assertFalse(outputs.released)
        self.assertEqual(outputs.reason, "no_eligible_commits")
        self.assertEqual(api.calls, [])

    def test_publish_skip_ci_head_commit(self):
        head = commit("h", "chore: skip [skip ci]")
        api = FakeGitHubApi()
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], [])),
            github=make_github(api.transport),
        )
        self.assertFalse(outputs.released)
        self.assertEqual(outputs.reason, "skip_ci_head_commit")
        self.assertEqual(api.calls, [])

    def test_publish_ignores_skip_commits_in_history(self):
        head = commit("h2", "feat: real work")
        skipped = commit("h1", "fix: skipped [skip ci]")
        api = FakeGitHubApi()
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head, skipped], [])),
            github=make_github(api.transport),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.version, "1.0.0")
        notes = api.release_posts()[0]["body"]
        self.assertIn("feat: real work", notes)
        self.assertNotIn("fix: skipped", notes)

    def test_publish_promotes_alpha_to_main_with_highest_bump(self):
        c0 = commit("c0", "feat: stable")
        c1 = commit("c1", "feat: next")
        head = commit("h", "docs: merge alpha")
        tags = [tag_ref("v1.0.0", "c0"), tag_ref("v1.1.0-alpha.1", "c1")]
        api = FakeGitHubApi()
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head, c1, c0], tags)),
            github=make_github(api.transport),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.version, "1.1.0")
        self.assertEqual(outputs.tag, "v1.1.0")
        self.assertEqual(outputs.reason, "promotion_release_created")
        self.assertFalse(api.release_posts()[0]["prerelease"])

    def test_publish_promotes_dev_to_main(self):
        c0 = commit("c0", "feat: stable")
        c1 = commit("c1", "feat: dev work")
        head = commit("h", "docs: merge dev")
        tags = [tag_ref("v1.0.0", "c0"), tag_ref("v1.2.0-dev.2", "c1")]
        api = FakeGitHubApi()
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head, c1, c0], tags)),
            github=make_github(api.transport),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.version, "1.2.0")
        self.assertEqual(outputs.reason, "promotion_release_created")

    def test_publish_promotes_beta_to_main_with_major_bump(self):
        c0 = commit("c0", "feat: stable")
        c1 = commit("c1", "feat: beta work")
        head = commit("h", "feat!: breaking")
        tags = [tag_ref("v1.0.0", "c0"), tag_ref("v1.1.0-beta.1", "c1")]
        api = FakeGitHubApi()
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head, c1, c0], tags)),
            github=make_github(api.transport),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.version, "2.0.0")

    def test_publish_dev_releases_without_protection(self):
        c0 = commit("c0", "feat: initial")
        head = commit("h", "fix: dev patch")
        tags = [tag_ref("v1.0.0-dev.1", "c0")]
        api = FakeGitHubApi()
        outputs = engine.publish(
            OWNER_REPO,
            "dev",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head, c0], tags)),
            github=make_github(api.transport),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.version, "1.0.0-dev.2")
        self.assertEqual(outputs.tag, "v1.0.0-dev.2")

    def test_publish_alpha_to_beta_starts_beta_train(self):
        c0 = commit("c0", "feat: stable")
        head = commit("h", "feat: next")
        tags = [tag_ref("v1.0.0", "c0")]
        runner = FakeGitRunner([head, c0], tags)
        api = FakeGitHubApi()
        alpha = engine.publish(
            OWNER_REPO,
            "alpha",
            head.sha,
            git=engine.GitClient(runner),
            github=make_github(api.transport),
        )
        self.assertEqual(alpha.tag, "v1.1.0-alpha.1")
        runner.tags.append(tag_ref(alpha.tag, "h"))
        beta = engine.publish(
            OWNER_REPO,
            "beta",
            head.sha,
            git=engine.GitClient(runner),
            github=make_github(api.transport),
        )
        self.assertTrue(beta.released)
        self.assertEqual(beta.tag, "v1.1.0-beta.1")

    def test_unsupported_branch_fails_before_git(self):
        head = commit("h", "feat: x")
        runner = FakeGitRunner([head], [])
        api = FakeGitHubApi()
        with self.assertRaisesRegex(engine.InputError, "unsupported release branch"):
            engine.publish(
                OWNER_REPO,
                "feature/runpod-service",
                head.sha,
                git=engine.GitClient(runner),
                github=make_github(api.transport),
            )
        self.assertEqual(runner.calls, [])
        self.assertEqual(api.calls, [])

    def test_invalid_repository_fails_before_git(self):
        head = commit("h", "feat: x")
        runner = FakeGitRunner([head], [])
        with self.assertRaisesRegex(engine.InputError, "owner/name"):
            engine.publish(
                "not-a-repo",
                "main",
                head.sha,
                git=engine.GitClient(runner),
                github=make_github(FakeGitHubApi().transport),
            )
        self.assertEqual(runner.calls, [])

    def test_invalid_sha_fails_before_git(self):
        runner = FakeGitRunner([], [])
        for bad_sha in ("", "abc", "g" * 40, "a" * 39, "a" * 41, None):
            with self.subTest(bad_sha=bad_sha):
                with self.assertRaisesRegex(engine.InputError, "40-character"):
                    engine.publish(
                        OWNER_REPO,
                        "main",
                        bad_sha,
                        git=engine.GitClient(runner),
                        github=make_github(FakeGitHubApi().transport),
                    )
        self.assertEqual(runner.calls, [])


class TestCollisionRecovery(unittest.TestCase):
    def test_stable_collision_advances_patch(self):
        head = commit("h", "feat: first")
        api = FakeGitHubApi(refs={"v1.0.0": sha("foreign")})
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], [])),
            github=make_github(api.transport),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.version, "1.0.1")
        self.assertEqual(outputs.tag, "v1.0.1")
        ref_posts = [
            payload
            for method, path, payload, _headers in api.calls
            if method == "POST" and path.endswith("/git/refs")
        ]
        self.assertEqual(
            [payload["ref"] for payload in ref_posts],
            ["refs/tags/v1.0.0", "refs/tags/v1.0.1"],
        )

    def test_prerelease_collision_advances_counter(self):
        c0 = commit("c0", "feat: initial")
        head = commit("h", "fix: patch")
        tags = [tag_ref("v1.0.0-alpha.1", "c0")]
        api = FakeGitHubApi(refs={"v1.0.0-alpha.2": sha("foreign")})
        outputs = engine.publish(
            OWNER_REPO,
            "alpha",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head, c0], tags)),
            github=make_github(api.transport),
        )
        self.assertEqual(outputs.version, "1.0.0-alpha.3")
        self.assertEqual(outputs.tag, "v1.0.0-alpha.3")

    def test_collision_notes_use_final_version(self):
        head = commit("h", "feat: first")
        api = FakeGitHubApi(refs={"v1.0.0": sha("foreign")})
        engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], [])),
            github=make_github(api.transport),
        )
        body = api.release_posts()[0]["body"]
        self.assertIn("Release 1.0.1", body)
        self.assertNotIn("Release 1.0.0", body)

    def test_claim_exhaustion_fails_clearly(self):
        head = commit("h", "feat: first")
        refs = {f"v1.0.{index}": sha(f"foreign-{index}") for index in range(engine.MAX_CLAIM_ATTEMPTS)}
        with self.assertRaisesRegex(
            engine.FatalError,
            r"exhausted 50 tag claim attempts starting at v1\.0\.0",
        ):
            engine.publish(
                OWNER_REPO,
                "main",
                head.sha,
                git=engine.GitClient(FakeGitRunner([head], [])),
                github=make_github(FakeGitHubApi(refs=refs).transport),
            )

    def test_completed_replay_is_idempotent(self):
        head = commit("h", "feat: shipped")
        tags = [tag_ref("v1.0.0", "h")]
        api = FakeGitHubApi(
            refs={"v1.0.0": head.sha},
            releases={
                "v1.0.0": release_payload(
                    "v1.0.0", head.sha, html_url="https://example.test/v1.0.0"
                )
            },
        )
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], tags)),
            github=make_github(api.transport),
        )
        self.assertFalse(outputs.released)
        self.assertTrue(outputs.idempotent)
        self.assertEqual(outputs.reason, "already_released")
        self.assertEqual(outputs.release_url, "https://example.test/v1.0.0")
        self.assertEqual(api.release_posts(), [])

    def test_tag_only_recovery_creates_release(self):
        head = commit("h", "feat: shipped")
        tags = [tag_ref("v1.0.0", "h")]
        api = FakeGitHubApi(refs={"v1.0.0": head.sha})
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], tags)),
            github=make_github(api.transport),
        )
        self.assertTrue(outputs.released)
        self.assertFalse(outputs.idempotent)
        self.assertEqual(outputs.tag, "v1.0.0")
        self.assertEqual(outputs.reason, "tag_only_recovery")

    def test_foreign_tag_advances(self):
        head = commit("h", "feat: shipped")
        tags = [tag_ref("v1.0.0", "h")]
        api = FakeGitHubApi(refs={"v1.0.0": sha("foreign")})
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], tags)),
            github=make_github(api.transport),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.tag, "v1.0.1")
        self.assertNotEqual(api.refs["v1.0.0"], head.sha)
        self.assertEqual(api.refs["v1.0.1"], head.sha)

    def test_foreign_release_advances(self):
        head = commit("h", "feat: shipped")
        tags = [tag_ref("v1.0.0", "h")]
        api = FakeGitHubApi(
            refs={"v1.0.0": sha("foreign")},
            releases={
                "v1.0.0": release_payload(
                    "v1.0.0", sha("foreign"), html_url="https://example.test/foreign"
                )
            },
        )
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], tags)),
            github=make_github(api.transport),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.tag, "v1.0.1")
        self.assertEqual(outputs.reason, "release_created")

    def test_existing_release_is_verified_before_idempotent(self):
        head = commit("h", "feat: shipped")
        api = FakeGitHubApi(
            refs={"v1.0.0": head.sha},
            releases={
                "v1.0.0": release_payload(
                    "v1.0.0", head.sha, html_url="https://example.test/v1.0.0"
                )
            },
        )
        outputs = engine._ensure_release(
            "v1.0.0",
            engine.Version(1, 0, 0),
            "notes",
            head.sha,
            make_github(api.transport),
            recovery_reason="unused",
        )
        self.assertFalse(outputs.released)
        self.assertTrue(outputs.idempotent)
        self.assertEqual(outputs.reason, "already_released")
        self.assertEqual(outputs.release_url, "https://example.test/v1.0.0")

    def test_existing_release_with_foreign_ref_fails_verification(self):
        api = FakeGitHubApi(
            refs={"v1.0.0": sha("foreign")},
            releases={
                "v1.0.0": release_payload(
                    "v1.0.0", sha("head"), html_url="https://example.test/v1.0.0"
                )
            },
        )
        with self.assertRaisesRegex(engine.ValidationError, "resolves to"):
            engine._ensure_release(
                "v1.0.0",
                engine.Version(1, 0, 0),
                "notes",
                sha("head"),
                make_github(api.transport),
                recovery_reason="unused",
            )

    def test_tag_without_remote_ref_is_created(self):
        head = commit("h", "feat: shipped")
        tags = [tag_ref("v1.0.0", "h")]
        api = FakeGitHubApi()
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], tags)),
            github=make_github(api.transport),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.tag, "v1.0.0")
        self.assertEqual(outputs.reason, "release_created")

    def test_replay_tag_only_release_race_advances(self):
        head = commit("h", "feat: shipped")
        tags = [tag_ref("v1.0.0", "h")]
        api = FakeGitHubApi(refs={"v1.0.0": head.sha})
        transport = ForeignReleaseOnCreateTransport(api, "v1.0.0", sha("foreign"))
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], tags)),
            github=make_github(transport),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.tag, "v1.0.1")

    def test_claim_collision_with_same_sha_then_release_race_advances(self):
        head = commit("h", "feat: first")
        api = FakeGitHubApi(refs={"v1.0.0": head.sha})
        transport = ForeignReleaseOnCreateTransport(api, "v1.0.0", sha("foreign"))
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], [])),
            github=make_github(transport),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.tag, "v1.0.1")

    def test_release_race_after_successful_ref_creation_advances(self):
        head = commit("h", "feat: first")
        api = FakeGitHubApi()
        transport = ForeignReleaseOnCreateTransport(api, "v1.0.0", sha("foreign"))
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], [])),
            github=make_github(transport),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.tag, "v1.0.1")

    def test_claim_collision_with_missing_ref_advances(self):
        head = commit("h", "feat: first")
        api = FakeGitHubApi()
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], [])),
            github=make_github(MissingRefOnCollisionTransport(api)),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.tag, "v1.0.1")

    def test_create_release_race_is_idempotent(self):
        head = commit("h", "feat: first")
        api = FakeGitHubApi()
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], [])),
            github=make_github(RacingReleaseTransport(api)),
        )
        self.assertFalse(outputs.released)
        self.assertTrue(outputs.idempotent)
        self.assertEqual(outputs.tag, "v1.0.0")
        self.assertEqual(outputs.reason, "already_released")

    def test_create_release_race_without_observable_release_fails_closed(self):
        head = commit("h", "feat: first")
        api = FakeGitHubApi()
        with self.assertRaisesRegex(engine.ApiError, "no published release"):
            engine.publish(
                OWNER_REPO,
                "main",
                head.sha,
                git=engine.GitClient(FakeGitRunner([head], [])),
                github=make_github(RacingReleaseTransport(api, insert=False)),
            )
        self.assertEqual(api.releases, {})
        observed = [
            (method, path)
            for method, path, _payload, _headers in api.calls
            if method == "GET" and "/releases/tags/" in path
        ]
        self.assertEqual(
            len(observed), engine.MAX_RELEASE_READ_ATTEMPTS + 1
        )

    def test_existing_draft_release_advances_without_modifying_it(self):
        head = commit("h", "feat: shipped")
        tags = [tag_ref("v1.0.0", "h")]
        draft = release_payload("v1.0.0", head.sha, draft=True)
        api = FakeGitHubApi(refs={"v1.0.0": head.sha}, releases={"v1.0.0": dict(draft)})
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], tags)),
            github=make_github(api.transport),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.tag, "v1.0.1")
        self.assertEqual(api.releases["v1.0.0"], draft)
        self.assertEqual(
            [payload["tag_name"] for payload in api.release_posts()],
            ["v1.0.1"],
        )

    def test_existing_release_with_wrong_channel_advances_without_modifying_it(self):
        head = commit("h", "feat: shipped")
        tags = [tag_ref("v1.0.0", "h")]
        wrong_channel = release_payload("v1.0.0", head.sha, prerelease=True)
        api = FakeGitHubApi(
            refs={"v1.0.0": head.sha}, releases={"v1.0.0": dict(wrong_channel)}
        )
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], tags)),
            github=make_github(api.transport),
        )
        self.assertTrue(outputs.released)
        self.assertEqual(outputs.tag, "v1.0.1")
        self.assertEqual(api.releases["v1.0.0"], wrong_channel)
        self.assertFalse(api.releases["v1.0.1"]["prerelease"])

    def test_existing_release_with_mismatched_tag_name_fails(self):
        head = commit("h", "feat: shipped")
        tags = [tag_ref("v1.0.0", "h")]
        api = FakeGitHubApi(
            refs={"v1.0.0": head.sha},
            releases={"v1.0.0": release_payload("v9.9.9", head.sha)},
        )
        with self.assertRaisesRegex(engine.ValidationError, "tag_name"):
            engine.publish(
                OWNER_REPO,
                "main",
                head.sha,
                git=engine.GitClient(FakeGitRunner([head], tags)),
                github=make_github(api.transport),
            )
        self.assertEqual(api.release_posts(), [])

    def test_existing_release_with_foreign_sha_target_fails(self):
        head = commit("h", "feat: shipped")
        tags = [tag_ref("v1.0.0", "h")]
        api = FakeGitHubApi(
            refs={"v1.0.0": head.sha},
            releases={"v1.0.0": release_payload("v1.0.0", sha("foreign"))},
        )
        with self.assertRaisesRegex(engine.ValidationError, "target commitish"):
            engine.publish(
                OWNER_REPO,
                "main",
                head.sha,
                git=engine.GitClient(FakeGitRunner([head], tags)),
                github=make_github(api.transport),
            )

    def test_existing_release_without_target_commitish_is_idempotent(self):
        head = commit("h", "feat: shipped")
        tags = [tag_ref("v1.0.0", "h")]
        release = release_payload("v1.0.0", head.sha)
        release.pop("target_commitish")
        api = FakeGitHubApi(refs={"v1.0.0": head.sha}, releases={"v1.0.0": release})
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], tags)),
            github=make_github(api.transport),
        )
        self.assertFalse(outputs.released)
        self.assertTrue(outputs.idempotent)
        self.assertEqual(outputs.reason, "already_released")

    def test_existing_release_with_malformed_state_fails(self):
        head = commit("h", "feat: shipped")
        tags = [tag_ref("v1.0.0", "h")]
        missing_draft = release_payload("v1.0.0", head.sha)
        missing_draft.pop("draft")
        missing_prerelease = release_payload("v1.0.0", head.sha)
        missing_prerelease.pop("prerelease")
        cases = (
            missing_draft,
            missing_prerelease,
            release_payload("v1.0.0", head.sha, draft=None),
            release_payload("v1.0.0", ""),
        )
        for release in cases:
            with self.subTest(release=release):
                api = FakeGitHubApi(
                    refs={"v1.0.0": head.sha}, releases={"v1.0.0": release}
                )
                with self.assertRaises(engine.ValidationError):
                    engine.publish(
                        OWNER_REPO,
                        "main",
                        head.sha,
                        git=engine.GitClient(FakeGitRunner([head], tags)),
                        github=make_github(api.transport),
                    )

    def test_existing_release_with_branch_target_is_idempotent_when_ref_matches(self):
        head = commit("h", "feat: shipped")
        tags = [tag_ref("v1.0.0", "h")]
        api = FakeGitHubApi(
            refs={"v1.0.0": head.sha},
            releases={"v1.0.0": release_payload("v1.0.0", "main")},
        )
        outputs = engine.publish(
            OWNER_REPO,
            "main",
            head.sha,
            git=engine.GitClient(FakeGitRunner([head], tags)),
            github=make_github(api.transport),
        )
        self.assertFalse(outputs.released)
        self.assertTrue(outputs.idempotent)
        self.assertEqual(outputs.reason, "already_released")
        self.assertEqual(api.release_posts(), [])

    def test_inconsistent_create_release_response_fails(self):
        head = commit("h", "feat: first")
        cases = (
            {"tag_name": "v9.9.9"},
            {"draft": True},
            {"prerelease": True},
            {"target_commitish": sha("foreign")},
            {"target_commitish": "main"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                api = FakeGitHubApi()
                transport = InconsistentReleaseResponseTransport(api, **overrides)
                with self.assertRaises(engine.ValidationError):
                    engine.publish(
                        OWNER_REPO,
                        "main",
                        head.sha,
                        git=engine.GitClient(FakeGitRunner([head], [])),
                        github=make_github(transport),
                    )

    def test_existing_release_with_multiline_url_fails_before_output(self):
        head = commit("h", "feat: shipped")
        tags = [tag_ref("v1.0.0", "h")]
        api = FakeGitHubApi(
            refs={"v1.0.0": head.sha},
            releases={
                "v1.0.0": release_payload(
                    "v1.0.0", head.sha, html_url="https://example.test/v1.0.0\nreleased=false"
                )
            },
        )
        with self.assertRaisesRegex(engine.ValidationError, "html_url"):
            engine.publish(
                OWNER_REPO,
                "main",
                head.sha,
                git=engine.GitClient(FakeGitRunner([head], tags)),
                github=make_github(api.transport),
            )

    def test_ref_moved_after_release_creation_is_not_reported(self):
        head = commit("h", "feat: first")
        api = FakeGitHubApi()
        transport = RefMovedAfterReleaseTransport(api, "v1.0.0", sha("foreign"))
        with self.assertRaisesRegex(engine.ValidationError, "resolves to"):
            engine.publish(
                OWNER_REPO,
                "main",
                head.sha,
                git=engine.GitClient(FakeGitRunner([head], [])),
                github=make_github(transport),
            )


class TestGitParsingAndIntegration(unittest.TestCase):
    def test_parse_log_output_valid(self):
        first = commit("a", "feat: one", "body")
        second = commit("b", "fix: two")
        output = FakeGitRunner._format([first, second])
        self.assertEqual(engine._parse_log_output(output), [first, second])

    def test_parse_log_output_rejects_malformed_records(self):
        header = f"{sha('a')}\x1ffeat: one"
        cases = (
            header,
            f"{header}\x1fbody\x1fextra\x1e",
            f"not-a-sha\x1ffeat: one\x1f\x1e",
            f"{sha('a')}\x1ffeat: one\x1fbody\x1e{sha('b')}\x1ffix: two",
        )
        for output in cases:
            with self.subTest(output=output):
                with self.assertRaises(engine.GitError):
                    engine._parse_log_output(output)

    def test_head_commit_requires_exactly_one_record(self):
        head = commit("h", "feat: one")
        empty = engine.GitClient(lambda args: "")
        with self.assertRaisesRegex(engine.GitError, "not found"):
            empty.head_commit(head.sha)
        duplicate = engine.GitClient(lambda args: FakeGitRunner._format([head, head]))
        with self.assertRaisesRegex(engine.GitError, "more than one"):
            duplicate.head_commit(head.sha)

    def test_reachable_tags_rejects_malformed_output(self):
        head = commit("h", "feat: one")
        cases = (
            "only-one-field\n",
            f"\tcommit\t\t{sha('a')}\t\n",
            f"v1.0.0\tcommit\t\tnot-a-sha\t\n",
        )
        for output in cases:
            with self.subTest(output=output):
                with self.assertRaises(engine.GitError):
                    engine.GitClient(lambda args, text=output: text).reachable_tags(head.sha)

    def test_reachable_tags_ignores_non_commit_tags(self):
        head = commit("h", "feat: one")
        output = f"\n v1.0.0\tblob\t\t{sha('blob')}\t\n"
        tags = engine.GitClient(lambda args: output).reachable_tags(head.sha)
        self.assertEqual(tags, [])

    def test_commits_since_rejects_invalid_stop_sha(self):
        head = commit("h", "feat: one")
        git = engine.GitClient(lambda args: "")
        with self.assertRaisesRegex(engine.InputError, "stop sha"):
            git.commits_since(head.sha, ["bad"])

    def test_git_failure_is_wrapped(self):
        with tempfile.TemporaryDirectory() as directory:
            git = engine.GitClient(cwd=directory)
            with self.assertRaisesRegex(engine.GitError, "git log failed"):
                git.head_commit(sha("missing"))

    def test_git_failure_without_stderr_is_wrapped(self):
        with tempfile.TemporaryDirectory() as directory:
            run_git = engine._run_git
            with unittest.mock.patch.object(engine.subprocess, "run") as run:
                run.return_value = subprocess.CompletedProcess(
                    ["git"], 1, stdout="", stderr=""
                )
                with self.assertRaisesRegex(engine.GitError, "exit code 1"):
                    run_git(["log", "-1", "HEAD"], cwd=directory)

    def test_git_timeout_and_execution_errors_are_wrapped(self):
        with unittest.mock.patch.object(
            engine.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["git"], 1),
        ):
            with self.assertRaisesRegex(engine.GitError, "timed out"):
                engine._run_git(["status"])
        with unittest.mock.patch.object(
            engine.subprocess, "run", side_effect=OSError("no git")
        ):
            with self.assertRaisesRegex(engine.GitError, "git execution failed"):
                engine._run_git(["status"])

    def test_temporary_repository_history_and_tags(self):
        with TemporaryGitRepository() as repo:
            c0 = repo.commit("feat: initial")
            repo.tag("inner", c0, annotated=True)
            repo.tag("outer", "inner", annotated=True)
            repo.tag("v1.0.0", c0)
            c1 = repo.commit("fix: patch")
            repo.tag("v1.0.1", c1)
            repo.run("checkout", "-q", "-b", "side", c0)
            c2 = repo.commit("feat!: side")
            repo.tag("v2.0.0", c2)
            repo.run("checkout", "-q", "main")
            git = engine.GitClient(cwd=str(repo.path))
            tags = {tag.name: tag for tag in git.reachable_tags(c1)}
            self.assertIn("inner", tags)
            self.assertIn("outer", tags)
            self.assertIn("v1.0.0", tags)
            self.assertIn("v1.0.1", tags)
            self.assertNotIn("v2.0.0", tags)
            self.assertEqual(tags["inner"].commit, c0)
            self.assertEqual(tags["outer"].commit, c0)
            self.assertEqual([item.sha for item in git.commits_since(c1, [c0])], [c1])
            self.assertEqual(git.head_commit(c1).subject, "fix: patch")

    def test_temporary_repository_publish_end_to_end(self):
        with TemporaryGitRepository() as repo:
            c0 = repo.commit("feat: initial")
            repo.tag("v1.0.0", c0)
            head = repo.commit("feat: next")
            api = FakeGitHubApi()
            outputs = engine.publish(
                OWNER_REPO,
                "main",
                head,
                git=engine.GitClient(cwd=str(repo.path)),
                github=make_github(api.transport),
            )
            self.assertTrue(outputs.released)
            self.assertEqual(outputs.version, "1.1.0")
            self.assertEqual(api.refs["v1.1.0"], head)
            self.assertEqual(api.release_posts()[0]["target_commitish"], head)


class TestApiClient(unittest.TestCase):
    def test_constructor_validation(self):
        with self.assertRaisesRegex(engine.InputError, "owner/name"):
            engine.GitHubClient("token", "bad", transport=lambda request: (200, b"{}"))
        for repository in ("./repo", "owner/..", "../repo", "owner/."):
            with self.subTest(repository=repository):
                with self.assertRaisesRegex(engine.InputError, "owner/name"):
                    engine.GitHubClient("token", repository, transport=lambda request: (200, b"{}"))
        with self.assertRaisesRegex(engine.InputError, "RELEASE_TOKEN"):
            engine.GitHubClient("", OWNER_REPO, transport=lambda request: (200, b"{}"))
        with self.assertRaisesRegex(engine.InputError, "RELEASE_TOKEN"):
            engine.GitHubClient("   ", OWNER_REPO, transport=lambda request: (200, b"{}"))

    def test_validate_api_url(self):
        self.assertEqual(engine.validate_api_url("https://api.github.com/"), "https://api.github.com")
        self.assertEqual(engine.validate_api_url("https://ghe.example/api/v3/"), "https://ghe.example/api/v3")
        for value in (
            "",
            "http://api.github.com",
            "https://",
            "https://user:pass@api.github.com",
            "https://api.github.com?x=1",
            "https://api.github.com#fragment",
            "https://api.github.com:bad",
            "https://api.github.com:70000",
            "https://[invalid",
            "https://api.github.com/ path",
            None,
        ):
            with self.subTest(value=value):
                with self.assertRaises(engine.InputError):
                    engine.validate_api_url(value)

    def test_request_sets_headers_and_returns_json(self):
        captured = {}

        def transport(request):
            captured.update({key.lower(): value for key, value in request.headers.items()})
            return 200, b'{"ok": true}'

        client = engine.GitHubClient("secret-token", OWNER_REPO, transport=transport)
        self.assertEqual(client._request("GET", "/repos/owner/repo"), {"ok": True})
        self.assertEqual(captured["authorization"], "Bearer secret-token")
        self.assertEqual(captured["accept"], "application/vnd.github+json")
        self.assertEqual(captured["x-github-api-version"], "2022-11-28")

    def test_request_maps_statuses(self):
        cases = (
            (401, engine.AuthorizationError),
            (403, engine.AuthorizationError),
            (404, engine.NotFoundError),
            (422, engine.ValidationError),
            (429, engine.ApiError),
            (500, engine.ApiError),
            (302, engine.ApiError),
            (503, engine.ApiError),
        )
        for status, error_type in cases:
            with self.subTest(status=status):
                client = engine.GitHubClient(
                    "token",
                    OWNER_REPO,
                    transport=lambda request, code=status: (code, b'{"message": "failure"}'),
                )
                with self.assertRaises(error_type):
                    client._request("GET", "/repos/owner/repo")

    def test_request_detects_already_exists(self):
        for body in (
            b'{"message": "Reference already exists"}',
            b'{"message": "Validation Failed", "errors": [{"resource": "Release", "field": "tag_name", "code": "already_exists"}]}',
        ):
            with self.subTest(body=body):
                client = engine.GitHubClient(
                    "token",
                    OWNER_REPO,
                    transport=lambda request, payload=body: (422, payload),
                )
                with self.assertRaises(engine.RefAlreadyExists):
                    client._request("POST", "/repos/owner/repo/git/refs")

    def test_request_wraps_transport_errors_without_details(self):
        def transport(request):
            raise RuntimeError("secret-token")

        client = engine.GitHubClient("secret-token", OWNER_REPO, transport=transport)
        with self.assertRaisesRegex(engine.NetworkError, "RuntimeError") as caught:
            client._request("GET", "/repos/owner/repo")
        self.assertNotIn("secret-token", str(caught.exception))

    def test_request_rejects_malformed_json(self):
        client = engine.GitHubClient(
            "token",
            OWNER_REPO,
            transport=lambda request: (200, b"not-json"),
        )
        with self.assertRaisesRegex(engine.ApiError, "malformed json"):
            client._request("GET", "/repos/owner/repo")

    def test_request_handles_empty_success_body(self):
        client = engine.GitHubClient(
            "token",
            OWNER_REPO,
            transport=lambda request: (204, b""),
        )
        self.assertIsNone(client._request("DELETE", "/repos/owner/repo"))

    def test_request_propagates_fatal_transport_errors(self):
        def transport(request):
            raise engine.InputError("bad input")

        client = engine.GitHubClient("token", OWNER_REPO, transport=transport)
        with self.assertRaises(engine.InputError):
            client._request("GET", "/repos/owner/repo")

    def test_request_reraises_clean_network_errors(self):
        def transport(request):
            raise engine.NetworkError("clean failure")

        client = engine.GitHubClient("token", OWNER_REPO, transport=transport)
        with self.assertRaisesRegex(engine.NetworkError, "clean failure"):
            client._request("GET", "/repos/owner/repo")

    def test_api_errors_redact_the_token(self):
        client = engine.GitHubClient(
            "secret-token",
            OWNER_REPO,
            transport=lambda request: (400, b'{"message": "bad secret-token"}'),
        )
        with self.assertRaises(engine.ValidationError) as caught:
            client._request("GET", "/repos/owner/repo")
        self.assertNotIn("secret-token", str(caught.exception))
        self.assertIn("***", str(caught.exception))

    def test_validation_errors_tolerate_malformed_bodies(self):
        bodies = (
            b"[]",
            b"not-json",
            b'{"message": "Validation Failed", "errors": "bad"}',
            b'{"message": "Validation Failed", "errors": [null, {"resource": "Other",'
            b' "field": "tag_name", "code": "already_exists"}, {"resource": "Release",'
            b' "field": "name", "code": "already_exists"}, {"resource": "Release",'
            b' "field": "tag_name", "code": "other"}]}',
        )
        for body in bodies:
            with self.subTest(body=body):
                client = engine.GitHubClient(
                    "token",
                    OWNER_REPO,
                    transport=lambda request, payload=body: (422, payload),
                )
                with self.assertRaises(engine.ValidationError):
                    client._request("POST", "/repos/owner/repo/git/refs")

    def test_channel_matches_handles_missing_versions(self):
        self.assertFalse(engine._channel_matches(None, None))
        self.assertFalse(engine._channel_matches(engine.Version(1, 0, 0, "alpha", 1), None))
        self.assertTrue(engine._channel_matches(engine.Version(1, 0, 0), None))
        self.assertTrue(engine._channel_matches(engine.Version(1, 0, 0, "dev", 1), "dev"))
        self.assertFalse(engine._channel_matches(engine.Version(1, 0, 0, "dev", 1), "alpha"))

    def test_get_release_returns_none_for_missing_and_rejects_non_object(self):
        missing = engine.GitHubClient(
            "token",
            OWNER_REPO,
            transport=lambda request: (404, b'{"message": "Not Found"}'),
        )
        self.assertIsNone(missing.get_release("v1.0.0"))
        invalid = engine.GitHubClient(
            "token",
            OWNER_REPO,
            transport=lambda request: (200, b"[]"),
        )
        with self.assertRaises(engine.ValidationError):
            invalid.get_release("v1.0.0")

    def test_get_ref_commit_peels_nested_annotated_tags(self):
        tag_one = sha("tag-one")
        tag_two = sha("tag-two")
        commit_sha = sha("target")

        def transport(request):
            path = urllib.parse.urlparse(request.full_url).path
            if path.endswith("/git/ref/tags/v1.0.0"):
                return 200, json.dumps({"object": {"type": "tag", "sha": tag_one}}).encode()
            if path.endswith(f"/git/tags/{tag_one}"):
                return 200, json.dumps({"object": {"type": "tag", "sha": tag_two}}).encode()
            if path.endswith(f"/git/tags/{tag_two}"):
                return 200, json.dumps({"object": {"type": "commit", "sha": commit_sha}}).encode()
            return 404, b'{"message": "Not Found"}'

        client = engine.GitHubClient("token", OWNER_REPO, transport=transport)
        self.assertEqual(client.get_ref_commit("v1.0.0"), commit_sha)

    def test_get_ref_commit_rejects_bad_payloads(self):
        tag_one = sha("tag-one")
        cases = (
            lambda request: (200, b"null"),
            lambda request: (200, b'{"object": null}'),
            lambda request: (200, json.dumps({"object": {"type": "tree", "sha": tag_one}}).encode()),
            lambda request: (200, json.dumps({"object": {"type": "commit", "sha": "bad"}}).encode()),
            lambda request: (200, json.dumps({"object": {"type": "tag", "sha": "bad"}}).encode()),
        )
        for transport in cases:
            with self.subTest(transport=transport):
                client = engine.GitHubClient("token", OWNER_REPO, transport=transport)
                with self.assertRaises(engine.ValidationError):
                    client.get_ref_commit("v1.0.0")

    def test_get_ref_commit_bounds_deep_nesting(self):
        chain = [sha(f"tag-{index}") for index in range(engine.MAX_TAG_PEEL_DEPTH + 1)]

        def transport(request):
            path = urllib.parse.urlparse(request.full_url).path
            if path.endswith("/git/ref/tags/v1.0.0"):
                return 200, json.dumps({"object": {"type": "tag", "sha": chain[0]}}).encode()
            object_sha = path.rsplit("/", 1)[1]
            index = chain.index(object_sha)
            if index + 1 < len(chain):
                return 200, json.dumps({"object": {"type": "tag", "sha": chain[index + 1]}}).encode()
            return 200, json.dumps({"object": {"type": "commit", "sha": sha("target")}}).encode()

        client = engine.GitHubClient("token", OWNER_REPO, transport=transport)
        with self.assertRaisesRegex(engine.ValidationError, "nested tag levels"):
            client.get_ref_commit("v1.0.0")

    def test_create_release_requires_valid_target_commitish(self):
        client = engine.GitHubClient(
            "token",
            OWNER_REPO,
            transport=lambda request: (201, b'{"tag_name": "v1.0.0"}'),
        )
        with self.assertRaisesRegex(engine.InputError, "target commitish"):
            client.create_release(
                tag="v1.0.0",
                name="v1.0.0",
                body="body",
                prerelease=False,
                target_commitish="bad",
            )

    def test_create_release_rejects_non_object_response(self):
        client = engine.GitHubClient(
            "token",
            OWNER_REPO,
            transport=lambda request: (201, b"[]"),
        )
        with self.assertRaises(engine.ValidationError):
            client.create_release(
                tag="v1.0.0",
                name="v1.0.0",
                body="body",
                prerelease=False,
                target_commitish=sha("head"),
            )

    def test_redirects_are_not_followed(self):
        class Handler(BaseHTTPRequestHandler):
            seen = []

            def do_GET(self):
                type(self).seen.append(self.path)
                if self.path == "/start":
                    self.send_response(302)
                    self.send_header("Location", "/next")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"should-not-be-read")

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/start",
                headers={"Authorization": "Bearer secret-token"},
            )
            status, body = engine._urllib_transport(request)
            self.assertEqual(status, 302)
            self.assertEqual(body, b"")
            self.assertEqual(Handler.seen, ["/start"])
            ok_request = urllib.request.Request(f"http://127.0.0.1:{port}/ok")
            status, body = engine._urllib_transport(ok_request)
            self.assertEqual(status, 200)
            self.assertEqual(body, b"should-not-be-read")
            self.assertEqual(Handler.seen, ["/start", "/ok"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)

    def test_network_errors_are_wrapped_without_details(self):
        client = engine.GitHubClient("secret-token", OWNER_REPO)
        with unittest.mock.patch.object(
            engine._NO_REDIRECT_OPENER,
            "open",
            side_effect=urllib.error.URLError("offline secret-token"),
        ) as opened:
            with self.assertRaises(engine.NetworkError) as caught:
                client._request("GET", "/repos/owner/repo")
        opened.assert_called_once()
        self.assertEqual(opened.call_args.kwargs["timeout"], engine.REQUEST_TIMEOUT_SECONDS)
        self.assertIn("github request failed", str(caught.exception))
        self.assertNotIn("secret-token", str(caught.exception))
        self.assertIn("***", str(caught.exception))

    def test_http_error_body_and_close_failures_are_tolerated(self):
        class BrokenHTTPError(urllib.error.HTTPError):
            def read(self):
                raise OSError("read failed")

            def close(self):
                self._closer.close()
                raise OSError("close failed")

        request = urllib.request.Request("https://api.github.com")
        error = BrokenHTTPError(
            "https://api.github.com", 500, "server error", {}, io.BytesIO(b"")
        )
        with unittest.mock.patch.object(engine._NO_REDIRECT_OPENER, "open", side_effect=error):
            status, body = engine._urllib_transport(request)
        error.fp.close()
        self.assertEqual(status, 500)
        self.assertEqual(body, b"")


class TestEntrypoint(unittest.TestCase):
    def _args(self, output_path: Path, repository: str = OWNER_REPO) -> list[str]:
        return [
            "publish",
            "--repository",
            repository,
            "--branch",
            "main",
            "--sha",
            sha("head"),
            "--github-output",
            str(output_path),
        ]

    def test_missing_token_fails_naming_release_token(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            stderr = io.StringIO()
            stdout = io.StringIO()
            with redirect_stderr(stderr), redirect_stdout(stdout):
                code = engine.main(self._args(output), environ={"GITHUB_TOKEN": "fallback"})
            self.assertEqual(code, 1)
            self.assertIn("RELEASE_TOKEN", stderr.getvalue())
            self.assertIn("GITHUB_TOKEN", stderr.getvalue())
            self.assertNotIn("released=true", stdout.getvalue())
            self.assertIn("reason=missing_token", output.read_text(encoding="utf-8"))

    def test_missing_token_never_calls_transport(self):
        called = []
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                code = engine.main(
                    self._args(Path(directory) / "output"),
                    transport=lambda request: called.append(request),
                    environ={},
                )
        self.assertEqual(code, 1)
        self.assertEqual(called, [])

    def test_non_secret_failure_returns_one_and_redacts_token(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            stderr = io.StringIO()
            with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
                code = engine.main(
                    self._args(output, repository="not-a-repo"),
                    environ={"RELEASE_TOKEN": "secret-token"},
                    transport=lambda request: (200, b"{}"),
                )
            self.assertEqual(code, 1)
            self.assertNotIn("secret-token", stderr.getvalue())
            self.assertIn("reason=fatal_error", output.read_text(encoding="utf-8"))

    def test_main_rejects_non_https_api_url(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            stderr = io.StringIO()
            with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
                code = engine.main(
                    self._args(output),
                    environ={
                        "RELEASE_TOKEN": "secret-token",
                        "GITHUB_API_URL": "http://api.github.com",
                    },
                    transport=lambda request: self.fail("transport must not run"),
                )
            self.assertEqual(code, 1)
            self.assertIn("https", stderr.getvalue())
            self.assertNotIn("secret-token", stderr.getvalue())
            self.assertIn("reason=fatal_error", output.read_text(encoding="utf-8"))

    def test_successful_main_writes_outputs(self):
        with TemporaryGitRepository() as repo:
            head = repo.commit("feat: initial")
            api = FakeGitHubApi()
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output"
                stdout = io.StringIO()
                args = [
                    "publish",
                    "--repository",
                    OWNER_REPO,
                    "--branch",
                    "main",
                    "--sha",
                    head,
                    "--github-output",
                    str(output),
                ]
                with change_directory(repo.path), redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = engine.main(
                        args,
                        environ={"RELEASE_TOKEN": "secret-token"},
                        transport=api.transport,
                    )
                self.assertEqual(code, 0)
                self.assertIn("released=true", stdout.getvalue())
                text = output.read_text(encoding="utf-8")
                self.assertIn("version=1.0.0", text)
                self.assertIn("tag=v1.0.0", text)
                self.assertIn("reason=release_created", text)

    def test_output_write_failure_returns_one(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "missing" / "output"
            stderr = io.StringIO()
            with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
                code = engine.main(self._args(output), environ={"GITHUB_TOKEN": "fallback"})
            self.assertEqual(code, 1)
            self.assertIn("unable to write outputs", stderr.getvalue())

    def test_output_write_failure_after_successful_release_returns_one(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            stderr = io.StringIO()
            outputs = engine.PublishOutputs(True, False, "1.0.0", "v1.0.0", "", "release_created")
            with unittest.mock.patch.object(engine, "_execute", return_value=(outputs, False)):
                with unittest.mock.patch.object(
                    engine, "write_outputs", side_effect=OSError("disk full")
                ):
                    with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
                        code = engine.main(
                            self._args(output),
                            environ={"RELEASE_TOKEN": "secret-token"},
                        )
            self.assertEqual(code, 1)
            self.assertIn("unable to write outputs", stderr.getvalue())

    def test_subprocess_missing_token_does_not_use_github_token(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            env = os.environ.copy()
            env.pop("RELEASE_TOKEN", None)
            env["GITHUB_TOKEN"] = "fallback-token"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "publish",
                    "--repository",
                    OWNER_REPO,
                    "--branch",
                    "main",
                    "--sha",
                    sha("head"),
                    "--github-output",
                    str(output),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("RELEASE_TOKEN", result.stderr)
            self.assertNotIn("fallback-token", result.stderr)
            self.assertIn("reason=missing_token", output.read_text(encoding="utf-8"))

    def test_write_outputs_fields(self):
        outputs = engine.PublishOutputs(True, False, "1.2.3", "v1.2.3", "https://example.test", "release_created")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "output"
            engine.write_outputs(str(path), outputs)
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "released=true\n"
                "idempotent=false\n"
                "version=1.2.3\n"
                "tag=v1.2.3\n"
                "release_url=https://example.test\n"
                "reason=release_created\n",
            )

    def test_validate_https_url_rejects_unsafe_values(self):
        for value in (
            "",
            None,
            "http://example.test/release",
            "https://user:pass@example.test/release",
            "https://[invalid",
            "https://example.test/release\nreleased=false",
        ):
            with self.subTest(value=value):
                with self.assertRaises(engine.ValidationError):
                    engine._validate_https_url(value, "release_url")

    def test_output_line_rejects_multiline_values(self):
        with self.assertRaisesRegex(engine.ValidationError, "reason"):
            engine._output_line("reason", "release_created\nreleased=false")

    def test_write_outputs_rejects_multiline_release_url(self):
        outputs = engine.PublishOutputs(
            True,
            False,
            "1.2.3",
            "v1.2.3",
            "https://example.test/release\nreleased=false",
            "release_created",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "output"
            with self.assertRaisesRegex(engine.ValidationError, "release_url"):
                engine.write_outputs(str(path), outputs)
            self.assertFalse(path.exists())

    def test_write_outputs_rejects_non_https_release_url(self):
        outputs = engine.PublishOutputs(
            True, False, "1.2.3", "v1.2.3", "http://example.test", "release_created"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "output"
            with self.assertRaisesRegex(engine.ValidationError, "https"):
                engine.write_outputs(str(path), outputs)
            self.assertFalse(path.exists())


class TestWorkflowWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        cls.trigger = (ROOT / ".github" / "workflows" / "trigger-build.yml").read_text(encoding="utf-8")

    def test_release_triggers_on_all_release_branches(self):
        self.assertIn(
            "on:\n"
            "  push:\n"
            "    branches:\n"
            "      - dev\n"
            "      - alpha\n"
            "      - beta\n"
            "      - main\n",
            self.release,
        )
        self.assertNotIn("pull_request", self.release)

    def test_release_uses_reusable_tests_and_security_settings(self):
        self.assertIn("uses: ./.github/workflows/tests.yml", self.release)
        self.assertIn("needs: tests", self.release)
        self.assertIn("permissions:\n  contents: read", self.release)
        self.assertIn("concurrency:\n  group: release-${{ github.ref }}\n  cancel-in-progress: false", self.release)
        self.assertIn("runs-on: ubuntu-24.04", self.release)
        self.assertIn("timeout-minutes: 15", self.release)

    def test_release_checks_out_exact_sha_with_full_history(self):
        pinned_action_refs(self.release, "actions/checkout")
        self.assertIn("ref: ${{ github.sha }}", self.release)
        self.assertIn("fetch-depth: 0", self.release)
        self.assertIn("persist-credentials: false", self.release)

    def test_release_requires_release_token_without_github_token_fallback(self):
        self.assertIn("name: Require RELEASE_TOKEN", self.release)
        self.assertIn("RELEASE_TOKEN: ${{ secrets.RELEASE_TOKEN }}", self.release)
        self.assertIn("--repository \"${RELEASE_REPOSITORY}\"", self.release)
        self.assertIn("--branch \"${RELEASE_BRANCH}\"", self.release)
        self.assertIn("--sha \"${RELEASE_SHA}\"", self.release)
        self.assertIn("python3 .github/scripts/release.py publish", self.release)
        self.assertNotIn("secrets.GITHUB_TOKEN", self.release)
        self.assertNotIn("github.token", self.release)
        self.assertNotIn("continue-on-error", self.release)
        self.assertNotIn("if:", self.release)
        self.assertNotIn("[skip ci]", self.release)
        self.assertNotIn("git push", self.release)
        self.assertNotIn("refs/heads", self.release)

    def test_release_run_blocks_use_env_not_inline_expressions(self):
        for block in self._run_blocks(self.release):
            self.assertNotIn("${{", block)
        env_lines = self.release.splitlines()
        self.assertIn("          RELEASE_REPOSITORY: ${{ github.repository }}", env_lines)
        self.assertIn("          RELEASE_BRANCH: ${{ github.ref_name }}", env_lines)
        self.assertIn("          RELEASE_SHA: ${{ github.sha }}", env_lines)

    def test_trigger_is_manual_only(self):
        self.assertIn("on:\n  workflow_dispatch:\n", self.trigger)
        self.assertNotIn("repository_dispatch", self.trigger)
        self.assertNotIn("pull_request", self.trigger)
        self.assertNotIn("push:", self.trigger)
        self.assertNotIn("alpha", self.trigger)
        self.assertNotIn("beta", self.trigger)
        self.assertNotIn("case ", self.trigger)

    def test_trigger_uses_pinned_github_script_and_release_token(self):
        pinned_action_refs(self.trigger, "actions/github-script")
        self.assertIn("github-token: ${{ secrets.RELEASE_TOKEN }}", self.trigger)
        self.assertIn("TARGET_BRANCH: ${{ github.ref_name }}", self.trigger)
        self.assertIn("RELEASE_TOKEN: ${{ secrets.RELEASE_TOKEN }}", self.trigger)
        self.assertNotIn("secrets.GITHUB_TOKEN", self.trigger)
        self.assertNotIn("github.token", self.trigger)
        self.assertEqual(self.trigger.count("uses:"), 1)
        self.assertIn("permissions:\n  contents: read", self.trigger)
        self.assertIn("concurrency:\n  group: trigger-build-${{ github.ref_name }}\n  cancel-in-progress: false", self.trigger)

    def test_trigger_creates_exactly_one_empty_commit(self):
        self.assertIn("message: 'chore: trigger image build'", self.trigger)
        self.assertIn("github.rest.git.getRef", self.trigger)
        self.assertIn("github.rest.git.getCommit", self.trigger)
        self.assertIn("github.rest.git.createCommit", self.trigger)
        self.assertIn("github.rest.git.updateRef", self.trigger)
        self.assertIn("tree", self.trigger)
        self.assertIn("parents: [head]", self.trigger)
        self.assertIn("force: false", self.trigger)
        self.assertIn("const head = ref.data.object.sha", self.trigger)
        self.assertIn("const tree = commit.data.tree.sha", self.trigger)
        self.assertIn("ref: `heads/${branch}`", self.trigger)
        self.assertNotIn("actions/checkout@", self.trigger)
        self.assertNotIn("release.py", self.trigger)
        self.assertNotIn("git commit", self.trigger)
        self.assertNotIn("git push", self.trigger)
        self.assertNotIn("pytest", self.trigger)

    def test_workflows_are_tidy_yaml(self):
        for name, text in (("release.yml", self.release), ("trigger-build.yml", self.trigger)):
            with self.subTest(name=name):
                self.assertTrue(text.endswith("\n"))
                self.assertFalse(text.endswith("\n\n"))
                self.assertNotIn("\t", text)
                for number, line in enumerate(text.splitlines(), start=1):
                    self.assertEqual(line, line.rstrip(), f"{name}:{number} has trailing whitespace")
                    self.assertFalse(line.lstrip().startswith("#"), f"{name}:{number} has a comment")

    @staticmethod
    def _run_blocks(text: str) -> list[str]:
        lines = text.splitlines()
        blocks = []
        index = 0
        while index < len(lines):
            stripped = lines[index].strip()
            if stripped.startswith("run: |"):
                indent = len(lines[index]) - len(lines[index].lstrip())
                index += 1
                block = []
                while index < len(lines):
                    line = lines[index]
                    current_indent = len(line) - len(line.lstrip())
                    if line.strip() and current_indent <= indent:
                        break
                    block.append(line)
                    index += 1
                blocks.append("\n".join(block))
                continue
            index += 1
        return blocks


if __name__ == "__main__":
    unittest.main()
