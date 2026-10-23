---
status: completed
created_at: 2026-10-21
updated_at: 2026-10-23
files_edited:
  - Dockerfile.gpu
  - src/app/requirements-gpu.txt
  - src/app/cloud_service.py
  - src/app/smoke_cloud.py
  - tests/test_cloud_service.py
  - tests/test_gpu_image.py
  - tests/test_smoke_cloud.py
  - docs/runpod-service.md
  - README.md
  - docs/CHANGELOG.md
  - AGENTS.md
  - .github/CODEOWNERS
  - .github/renovate.json
  - .github/scripts/release.py
  - .github/scripts/registry_publish.py
  - .github/scripts/scan_gate.py
  - .github/workflows/tests.yml
  - .github/workflows/release.yml
  - .github/workflows/docker-publish.yml
  - .github/workflows/trigger-build.yml
  - tests/test_ci_config.py
  - tests/test_ci_release.py
  - tests/test_ci_publish.py
  - tests/test_ci_scan.py
  - docs/ci-release.md
rationale:
  - Prepare GPU execution of the existing HTTP service without changing training or the CPU deployment.
  - Require working CUDA and authenticate the entire cloud API before request bodies or legacy routes are reached.
  - Provide reproducible direct dependency pins and a synthetic remote verification client.
  - Complete local image export after disk cleanup and verify the resulting artifact without claiming GPU inference.
  - Configure the approved Digitalygo release and GHCR automation bundle with scan-before-tag publication and explicit activation prerequisites.
  - Activate the authorized dev prerelease without changing main and preserve the security block before image tagging.
  - Replace vulnerable setuptools-vendored dependencies in the GPU image and require independent build and remote scan verification before promotion.
supporting_docs:
  - ../research/2026-10-21-runpod-readiness.md
  - ../../../docs/runpod-service.md
  - ../../../docs/GUARDRAIL_API.md
  - ../../../docs/ci-release.md
---

# RunPod service preparation

## Summary of changes

Created `feature/runpod-service` from `feature/teams-pii-integration` at `0fd115c5dbee905882ef6651dfb3c77a92cb3739`, following the user's explicit instruction to branch from the current checkout. Implemented the service-only GPU container, authenticated cloud entry point, remote smoke client, tests and deployment guide. Training, the existing CPU Dockerfile and Compose deployment, and `src/app/app.py` remain unchanged.

The repository implementation passed quality and focused security review. No image was published and no RunPod resource was provisioned. Final image export and actual GPU inference remain outstanding, as described below; completion here refers to the repository changes, not a deployed service.

## Technical reasoning

The existing engine already supports CUDA and the existing HTTP API already implements the request contracts. Native Pod container execution, Gunicorn and standard-library WSGI/HTTP facilities resolved the deployment requirement without a RunPod SDK, Serverless handler, engine rewrite or new web framework.

- `Dockerfile.gpu` uses the verified `linux/amd64` Python 3.11.17 Bookworm image digest, CUDA PyTorch `2.13.0+cu130` and Transformers `5.14.1`. The latter versions preserve CPU runtime parity rather than introducing unrelated ML upgrades. The cu130 channel was verified against official PyTorch information and installed successfully; the older Blackwell cu128 guidance is not applicable to this torch pin.
- Direct dependencies are exact-pinned in `src/app/requirements-gpu.txt`. Transitive dependencies and OS package resolution are not locked. The cu130 wheel comes from the official PyTorch index, with remaining requirements resolved separately from PyPI.
- The v1.5.0 model is included at build time. Offline Hugging Face flags prevent runtime model fetches, but are not an egress firewall. The non-root runtime requires no training assets or model volume.
- `cloud_service:create_app()` verifies a nonblank token, actual CUDA tensor arithmetic and synchronization, then imports the unchanged app and checks GPU/model readiness. There is no CPU fallback in this entry point.
- The WSGI wrapper authenticates every non-health request before application routing or body access. Only exact GET/HEAD health probes are anonymous and expose minimal readiness. Responses receive `no-store`; error logging and late WSGI failures are sanitized. HEAD and streaming cleanup retain protocol and resource semantics.
- Existing legacy functionality remains accessible to authenticated clients. A shared token represents one trusted tenant, not multi-user isolation. Guardrail concurrency remains one request per process; extra Gunicorn threads do not change that lock.
- `smoke_cloud.py` exercises public readiness, guardrail and legacy authentication, JSON anonymization, seed reuse and multipart aggregation using synthetic values only. It requires HTTPS except literal loopback, refuses redirects, bounds responses and never prints response bodies or credentials.

Implementation was split into bounded runtime, container and smoke tasks with disjoint file ownership, followed by documentation. No competing architecture or algorithm was needed. Two primary implementation calls ended with provider errors after partial writes; fallback writers inspected and completed their own bounded slices without resetting unrelated work.

## Impact assessment

The new image adds authentication and minimal health responses only through its cloud entry point. The existing local entry points and API schemas are unchanged. The pre-existing research note was preserved. No training, taxonomy, dataset, model source, existing tests, workflow, production VPN configuration or unrelated repository was modified. No commit or push was performed.

RunPod deployment requires a compatible NVIDIA host driver for CUDA 13, registry access and a runtime `PII_API_TOKEN` secret. Use the RunPod HTTPS proxy, not public plaintext TCP. The documented 100-second proxy limit is separate from the cooperative application deadline; Gunicorn's gthread worker timeout is not a hard per-request cancellation mechanism.

Only synthetic data was used. Cloud execution processes data before anonymization on provider infrastructure; deployment does not retain the original local-only privacy boundary. Real documents require separate approval of provider, region, access and retention terms.

## Validation steps

The orchestrator inspected implementation files, tests, documentation and the combined worktree delta, and independently executed verification rather than accepting member test claims.

### Deterministic verification

- Baseline standard-library discovery: 458 tests passed, 186 optional-dependency skips.
- Final discovery in a disposable Python 3.11.16 environment with Flask 3.1.3, PyMuPDF 1.28.2 and Gunicorn 26.2.0: **575 tests passed, no skips**.
- Branch-aware coverage on the two new executable Python modules: **95% aggregate**, 95% for each module. GPU image tests additionally verify structural deployment contracts; they do not claim real CUDA coverage.
- A disposable, network-isolated, read-only container using the existing real CPU torch runtime confirmed that the new factory rejects both a missing token and unavailable CUDA before importing the model application. It was removed with `--rm`.
- The base image digest and architecture were independently inspected. The GPU dependency set resolved and was actually installed during the image build, including successful `pip check`.
- `git diff --check` passed. Existing tracked runtime, training and CPU deployment files were unchanged.

The final test command was:

```bash
PYTHONPATH=src/app COVERAGE_FILE=/tmp/envai-pii-runpod.coverage \
  /tmp/envai-pii-runpod-verify/bin/python -m coverage run --branch \
  --source=cloud_service,smoke_cloud -m unittest discover -v tests
```

Local evidence logs are `/tmp/envai-pii-runpod-tests-final.log` and `/tmp/envai-pii-runpod-build.log`. These are ephemeral machine-local evidence, not required repository artifacts. The temporary verification environments are removed at closure.

### Review outcomes

- Initial quality review: **FAIL**, identifying a lazy HEAD error path that did not close the response body. The delegated correction added guaranteed cleanup and nine regression tests, followed by independent full-suite and coverage reruns.
- Final `quality-gate-a` judgment: **PASS**. A Dockerfile comment was corrected to acknowledge the CUDA userspace dependencies installed by PyTorch. The README documentation-index link was explicitly within the documentation delegation, resolving the review's scope question.
- Focused `security-review-specialist-a` review and follow-up: **PASS**. No blocking findings remain in the implementation delta.
- Non-blocking security observation: Gunicorn's pre-WSGI parser/error logs can still include malformed request targets or query strings. The Flask logger filter is not a server-wide or provider-wide logging guarantee. This limitation is disclosed in the deployment guide; secrets must never be carried in URLs.

### Build and GPU limitations

All 18 Dockerfile instructions completed successfully, including dependency installation, model download and CUDA-build/model-file checks. Podman then failed during final image commit with `no space left on device` while exporting `model.safetensors`. Approximately 19 GB was available before the build; **no final GPU image artifact was produced**. The failed build's temporary container was not retained.

There is no local NVIDIA GPU. Actual GPU model inference, GPU memory sizing, RunPod proxy behavior and remote smoke verification were not performed. Build-instruction success and mocked CUDA tests are not evidence that a chosen RunPod GPU/driver combination works.

Next steps are to complete the build on a builder with sufficient free disk, manually publish and record the registry digest, then run the documented synthetic smoke test on a CUDA-compatible Pod. Do not send real personal data or declare the service deployed before those checks.

## Update 2026-10-22: local image build and packaging verification

### Summary of changes

After the user freed disk space, both local build attempts completed all 18 instructions and final image commit. This resolves the image-export blocker recorded above. The user explicitly deferred GitHub Actions automation and GHCR publication to a later step; neither was configured or executed.

Only build-status documentation changed in this follow-up: `docs/runpod-service.md`, `docs/CHANGELOG.md` and this operation. Hash comparisons confirmed the Dockerfiles, application modules, requirements and tests remained byte-identical to the accepted implementation. The branch and HEAD remain unchanged, with all previous work uncommitted and preserved.

### Technical reasoning and artifact identity

The first successful retry used Podman's default OCI format, which emitted a warning and dropped Docker's `HEALTHCHECK` metadata. A second complete build with `--format docker` produced a Docker v2 image and preserved the healthcheck. The deployment guide now specifies that flag for Podman and explicitly omits it for Docker, whose build command does not accept it.

The final local test artifact was:

- Image ID: `19ce644e3037abfb7856f3777383752977a6da26d28c9252cd6afadffb95d591`.
- Local manifest digest: `sha256:8e5f60a4a31e335d4f3d3a4fce9642df84f24eb6c66ba18d19532b9deee3ca84`. This is not a published GHCR digest.
- Platform: `linux/amd64`; image format: `application/vnd.docker.distribution.manifest.v2+json`.
- Local uncompressed image size: 6,592,638,364 bytes, approximately 6.14 GiB. Registry transfer size was not measured.
- Model weights SHA-256: `b1e046e3aec52c3cd74eaf166b034644a4dac0c91128bf06803e1478657fcd9f`.
- Runtime: Python 3.11.17, torch 2.13.0+cu130 with CUDA-build version 13.0, Transformers 5.14.1, Flask 3.1.3, PyMuPDF 1.28.2 and Gunicorn 26.2.0.

The verification build used:

```bash
podman build --format docker --platform linux/amd64 --layers=false \
  --rm --force-rm --memory 4g --cpu-period 100000 --cpu-quota 200000 \
  -f Dockerfile.gpu -t localhost/envai-pii-runpod-buildtest-docker:20261022 .
```

Approximately 56 GB was free before the retry. This is observed capacity, not a minimum-space guarantee for another builder or a GitHub-hosted runner.

### Independent validation

- Inspected the actual image configuration, Docker manifest type, user, command, offline environment, exposed port and preserved healthcheck. No API token was embedded in the environment.
- Compared SHA-256 of all 15 baked `src/app/*.py` files with the working tree; all matched.
- Imported the actual ML, web and PDF dependencies and loaded the tokenizer offline in a non-root, read-only, network-isolated container. The model directory, config, tokenizer and weights are root-owned and not group/world writable; the process runs as UID 10001.
- Loaded the real baked model offline and completed a synthetic EMAIL analysis through the existing v1 Flask endpoint using CPU explicitly in a test entrypoint. The placeholder, dictionary delta and response status matched expectations. This checks packaging and inference compatibility on CPU, not CUDA execution or a cloud CPU fallback.
- Confirmed native MuPDF privacy capability in the final image. An in-memory PDF text round-trip also passed in the first successful OCI artifact.
- Verified missing-token and unavailable-CUDA rejection through both the factory and the actual default Gunicorn command. Gunicorn exited with code 3 in both negative tests, with the expected fixed diagnostic and no synthetic token in its captured logs.
- Ran the repository's full `python -m unittest discover -v tests` command inside the final built image: **575 tests passed, no skips**. The container was network-isolated, read-only, capability-free and resource-bounded, with repository source mounted read-only.
- `git diff --check` and the pre-build executable-file checksum manifest passed. No executable changes were needed; the prior quality/security gate remains applicable. This documentation-only follow-up does not trigger new automatic quality or security reviews.

Local evidence is recorded in `/tmp/envai-pii-runpod-build-20261022.log`, `/tmp/envai-pii-runpod-build-docker-20261022.log`, `/tmp/envai-pii-runpod-image-docker-20261022.json`, `/tmp/envai-pii-runpod-final-package-20261022.log`, `/tmp/envai-pii-runpod-image-tests-20261022.log` and the two `/tmp/envai-pii-runpod-no-{token,gpu}-20261022.log` files. These are ephemeral evidence, not repository dependencies.

### Impact and remaining boundaries

No NVIDIA GPU is available locally. Real GPU inference, GPU memory sizing and the RunPod HTTPS path still require a later Pod test. The successful build does not satisfy those separate checks. No registry push, real-document upload, provider deployment, training, commit or GitHub Actions workflow change occurred.

Temporary containers and both local test images are removed at closure, together with the base image pulled only for these builds. No unrelated images or services are pruned. The next requested phase is GitHub Actions image building and GHCR storage; its runner disk budget and healthcheck-preserving output format must be addressed when that phase is implemented.

## Update 2026-10-22: GitHub Actions and GHCR configuration

### Summary of changes

The user approved the previously deferred CI and registry phase. Added the mandatory Digitalygo bundle: reusable tests, Conventional Commit releases, release-triggered GPU image publishing, manual empty-chore trigger, Renovate, CODEOWNERS and the shared agent quality baseline. The resulting configuration targets `ghcr.io/digitalygo/envai-pii` and builds only `Dockerfile.gpu`; neither application behavior nor either Dockerfile changed in this phase.

This is verified local configuration, not an activated or successfully executed hosted release chain. No commit, branch push, release creation, registry publication, secret mutation, package visibility change or RunPod deployment occurred.

### Environment and scope decisions

Read-only GitHub inspection confirmed a public repository, Actions enabled, read-only default workflow token permissions and no repository-level secrets. Organization-inherited secrets were not verified: the read-only request for the organization RELEASE_TOKEN metadata returned HTTP 403, and no additional token scopes were requested. The remote still has `main` and `feature/teams-pii-integration`, with no release tags or GitHub releases; `feature/runpod-service` remains local and uncommitted. Existing CLI credentials were not reused as a workflow secret.

The company CI skill requires its complete bundle even for a container-publishing request. This expansion and the required `RELEASE_TOKEN` were disclosed to the user. Existing Python release and registry-validation patterns from trusted sibling repositories informed bounded, separately owned implementation tasks; no sibling repository was modified and no new Node package manifest was introduced.

### Workflow behavior

- The reusable test workflow keeps Python 3.11, 3.13 and 3.14. It installs only the Flask and PyMuPDF pins from the GPU requirements file, then runs unittest discovery. Inline workflow JavaScript tests use Node already present on GitHub-hosted Ubuntu. Its concurrency key includes the caller workflow and ref, preventing an independent main-branch test run from cancelling release validation.
- Pushes to `dev`, `alpha`, `beta` and `main` run the reusable tests and Python release engine. Conventional Commit rules, highest cumulative bumps, prerelease channels, version collisions, tag-only recovery and same-SHA idempotence are covered. Release success requires observing a published, matching release and validating the tag's commit. Drafts and channel conflicts are never silently accepted as successful publication.
- Release and trigger workflows require `RELEASE_TOKEN` and fail explicitly if absent. The default `GITHUB_TOKEN` is never a fallback for operations that must trigger downstream workflows. The manual trigger creates only one empty chore commit on the selected branch, without tests or a build in that job.
- Published releases trigger the GPU publisher. It validates the exact tag/event SHA, builds one `linux/amd64` image and pushes it without tags using the ephemeral workflow token with `packages: write`. Provenance/SBOM indexes are disabled for this single-manifest path, and Docker media types preserve `HEALTHCHECK`.
- Build metadata, raw remote manifest hash, platform and Trivy image-config identity are bound to the emitted digest. The pinned Trivy container reads the exact remote digest, scanning vulnerabilities and secrets. Any secret, fixable HIGH/CRITICAL finding, failed scan or malformed/incomplete/mismatched report blocks before any tag is created or moved. Unfixed vulnerabilities do not block.
- Only a passed digest is promoted, without rebuilding. Stable aliases are version, major.minor, major, latest and version-short-SHA. Prereleases receive version, channel and version-short-SHA only. Immutable conflicts fail closed; older releases cannot roll back newer rolling aliases; written tags are checked against the scanned digest.
- Runner cleanup is limited to fixed, unnecessary SDK directories on GitHub-hosted runners. A 30 GiB free-space preflight fails clearly if insufficient. This is a selected safety budget, not a measured hosted-runner capacity guarantee.
- Optional kChat notifications begin with the required success/failure emoji and include repository, release, commit and outcome. Optional swarm dispatch occurs only after tag verification; missing or unavailable credentials/targets skip silently. No remote integration was exercised.
- Renovate groups patch updates per active manager in the Wednesday 11:00-13:00 Europe/Rome window, with `build` package commits and `ci` action commits, CODEOWNERS reviewers and no automerge. The coupled CUDA torch pin is explicitly manual so an automated update cannot drop the cu130 suffix or disagree with the Dockerfile literal. Inline CPU pip pins remain manual.

### Independent verification and review

The orchestrator reviewed the actual workflow/helper files and independently ran:

- Full unittest discovery with real Flask/PyMuPDF: **820 tests passed, no skips on each of Python 3.11.16, 3.13.5 and 3.14.7**. Branch-aware coverage of `.github/scripts` on Python 3.11 measures 99% for the release helper, 93% for the registry helper, 95% for the scan gate, and **97% aggregate**. Coverage includes API and registry fakes, temporary Git repositories, CLI errors, redirect rejection and executed JavaScript dispatch tests.
- `actionlint` 1.7.12 on all four workflows: PASS.
- YAML parsing, JSON parsing and full-commit-SHA checks for external actions: PASS.
- Renovate 44.176.3 configuration validation with `--no-global --strict`: PASS.
- The remote manifest/config validator against the actual public, digest-pinned Trivy image using Docker Buildx 0.37.0: PASS. This checks the CLI evidence format and digest binding; it is not a scan or publish of envai-pii.
- Pre-existing executable-file SHA-256 checks and `git diff --check`: PASS. Training, CPU/GPU Dockerfiles, application modules and previous tests were preserved.

Current action pins and Trivy 0.76.1 were researched from official sources, then action tag refs and the Trivy linux/amd64 manifest were independently resolved. No unverified action SHA was invented.

Leader inspection corrected two issues before final review: reusable-workflow concurrency collisions and a release API recovery path that could otherwise mistake a tag for an observed published release. Tests were added rather than weakened. Optional swarm skips were made silent, scan-container isolation was tightened, and the repository baseline now distinguishes model-free unit tests from model-downloading image builds.

A final test-only correction replaced fixed action-SHA and Trivy-version snapshots with immutable-pin and official-repository contracts. Two additional regressions permit valid future pin updates while rejecting mutable, short, malformed or unofficial references; this prevents Renovate updates from failing solely because a test duplicated the old version. All workflow and tool pins remained unchanged, and no test was deleted or skipped.

Final `quality-gate-a` verdict, including the test-only follow-up: **PASS**. Focused `security-review-specialist-a` verdict: **PASS**, with no blocking findings in the CI delta. The security review did not substitute for a live hosted run. Non-blocking observations concern future-proofing output delimiters and deeper manifest-shape checks, not a demonstrated bypass of the bound single-platform scan.

Evidence logs: `/tmp/envai-pii-ghcr-tests.log`, `/tmp/envai-pii-ghcr-tests313.log`, `/tmp/envai-pii-ghcr-tests314.log`, `/tmp/envai-pii-ghcr.coverage`, `/tmp/envai-pii-ghcr-renovate-validator.log`, `/tmp/envai-pii-ghcr-live-manifest.json`, `/tmp/envai-pii-ghcr-live-config.json` and `/tmp/envai-pii-ghcr-preexisting.sha256`. These are temporary local audit artifacts, not build dependencies.

### Activation boundary and next action

Configure a dedicated `RELEASE_TOKEN` with repository content write permission, or verify an appropriately scoped organization secret is inherited. Never paste its value in chat or automatically copy the local CLI token. Introduce the automation on a releasing branch with `[skip ci]` in the landing commit, verify that no accidental release is created, then intentionally trigger the first release. The branch itself must first be committed and pushed with user approval.

GHCR uses `GITHUB_TOKEN`; an existing package may need repository Actions write access. Package visibility is not changed by this configuration. A private package requires separate read-only registry credentials in RunPod. Renovate app access also remains to be verified by an administrator.

Live release triggering, GHCR authorization, remote scanning of the actual GPU image, tag promotion, hosted disk headroom, optional notifications/dispatch, Renovate app operation and RunPod GPU inference remain unverified until activation. No runtime or security outcome for those external systems is claimed here.

## Update 2026-10-23: dev activation blocked by image vulnerabilities

### Summary of changes

With explicit user approval, created and pushed `dev` from the published bootstrap commit `a4525db1ed67139621ba9d5dfbde89687b4c0396`. Verified that this initial `[skip ci]` landing produced no release. Then pushed the empty commit `766cb1af8e567e3e9b9388ef4887fbef53461975`, `chore: trigger dev image build`, and verified that its Git tree is identical to its parent.

The [Release workflow](https://github.com/digitalygo/envai-pii/actions/runs/39957892878) succeeded and created the [v1.0.0-dev.1 prerelease](https://github.com/digitalygo/envai-pii/releases/tag/v1.0.0-dev.1) at that exact SHA. The subsequent [GPU publisher run](https://github.com/digitalygo/envai-pii/actions/runs/39957975454) built and uploaded the image, but the mandatory remote scan gate blocked tagging on two fixable HIGH vulnerabilities. The image is not approved for RunPod; this operation is blocked pending remediation.

### Technical reasoning and impact

No application, dependency, test or workflow source changed during activation. `main` remains at `30d6f9c675e245bc8494df959adaeaa9d8de35c7`; neither its contents, protection rules nor the repository default branch were changed. The user-approved dev branch and prerelease remain as the operational record. No RunPod service or other production resource was started.

The manual workflow is not yet available on the default branch, so activation used the approved empty Git commit rather than relying on a `workflow_dispatch` UI button. The push-triggered release and release-published workflows both executed successfully from dev/tag source without promoting to main. GitHub's documented distinction is between [push/release events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows) and the default-branch requirement for [manual workflow dispatch](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

`RELEASE_TOKEN` availability is now verified by the successful live preflight and release API operation, despite the repository-secret CLI list still returning empty. Its source, such as organization inheritance, was not determined. No secret value was read, copied, changed or logged, and the local CLI token was not reused as a workflow secret.

The Packages API reports `ghcr.io/digitalygo/envai-pii` as **public**, linked to this repository. This observed result replaces the earlier documentation assumption that the new package would be private. No explicit package visibility change was made by the agent.

### Verified publication boundary

- Hosted tests succeeded on Python 3.11, 3.13 and 3.14 in both the release and publisher workflows, running the existing 820-test suite.
- Publisher steps for source validation, runner disk cleanup/preflight, GHCR login, GPU build and digest-only push all succeeded.
- Pushed digest: `sha256:01b0b97ba69682d200a636de35d2528ff9e13858bea07abe20930ae1d66758ab`.
- Remote image config ID: `sha256:55b0837994dce29a097b54306832b6549a21678b1abdc4ea83e9b76b245a4cbd`.
- Exact remote manifest/config validation and the Trivy scan completed successfully. The policy evaluation then failed on the findings below.
- Registry package version ID `1434889853` is independently confirmed to reference that digest with `tags: []`.
- Tag inspection, tag preflight, promotion, tag verification and swarm dispatch were all skipped after the blocked scan. The notification job completed, but that alone does not prove that an optional webhook was configured or sent.
- The scan report was deleted by the workflow's privacy cleanup. Local evidence logs contain the fixed finding summaries, not original secret-scanner payloads.

### Blocking findings and remediation boundary

| Finding | Package identified by the advisory | Severity | First fixed version |
|---|---|---|---|
| CVE-2026-23949 | jaraco.context | HIGH | 6.1.0 |
| CVE-2026-24049 | wheel | HIGH | 0.46.2 |

Package identities and fixed versions were verified against [GHSA-58pv-8j8x-9vj2](https://github.com/advisories/GHSA-58pv-8j8x-9vj2) and [GHSA-8rrh-rw8j-w5fx](https://github.com/advisories/GHSA-8rrh-rw8j-w5fx). Both advisories also describe vendored copies in setuptools. The build log confirms `setuptools 79.0.1` is present, but the exact vulnerable file paths and installed copies were not recovered from the deleted Trivy report and must not be asserted from inference alone.

No dependency was upgraded, no scanner finding was ignored and no tag was manually created to bypass the block. Remediation requires identifying and updating the affected copies, rebuilding, rerunning tests and obtaining a passing remote scan before release tags can be promoted. User approval for this dependency-remediation follow-up is pending.

### Validation and remaining state

The orchestrator watched both hosted runs through completion, inspected job/step conclusions and the gate log, and independently queried the GitHub release, registry version and branch SHAs. Expected negative unit tests emitted error annotations while their jobs still succeeded; the actual publisher failure is the two-finding scan gate, not those test annotations.

Local evidence logs include `/tmp/envai-pii-dev-publish-failed.log` and `/tmp/envai-pii-dev-publish-full.log`. `docs/ci-release.md` and `docs/runpod-service.md` were updated locally to distinguish successful activation/build from blocked image approval. These documentation changes are not yet committed. No local test server or container was started in this activation step. A new source quality gate is not applicable to an unchanged Git tree and documentation-only updates; the image security gate remains **blocked**, not waived by the earlier source-review PASS.

## Update 2026-10-23: GPU dependency remediation

### Approved scope and implementation

The user approved resolving the two blocking image findings and republishing from `dev`. Continued on the explicitly approved dev branch, preserved the three pre-existing documentation updates and synchronized with `git pull --ff-only`. Session baseline was `766cb1af8e567e3e9b9388ef4887fbef53461975`; the local status snapshot is `substrate/traces/status/2026-10-23-gpu-dependency-remediation-workspace-state.md`.

Official PyPI wheel inspection independently confirmed that setuptools 79.0.1 contains jaraco.context 5.3.0 and wheel 0.45.1 under `setuptools/_vendor`. The pinned base image contains this same setuptools version. Setuptools 80.10.2 contains patched jaraco.context 6.1.0 and wheel 0.46.3, supports Python >=3.9 and retains `pkg_resources`. Updating unrelated standalone distributions would not replace these vendored copies, so the correction pins the parent distribution instead.

A single backend member implemented the mechanical GPU-only pin and build verification, with a bounded follow-up strengthening vendor-specific negative tests. No race was warranted for this exact dependency bump. The primary provider was already known unavailable with a credit error in the preceding session, so available fallback members were used sequentially; no role was bypassed.

- `src/app/requirements-gpu.txt`: added `setuptools==80.10.2`; all previous runtime and ML pins remain unchanged.
- `Dockerfile.gpu`: reads installed vendor metadata and checks fixed minimum versions before `pip check`. Missing, stale or malformed metadata fails the build; no vendored archive-extraction code is imported or executed by this check.
- `tests/test_gpu_image.py`: checks the exact-pin format and setuptools minimum, verifies installation/check ordering and executes the actual embedded build check against old, partial, separately stale vendors, missing vendors, malformed metadata, fixed and future-patch cases.
- `docs/CHANGELOG.md`, `docs/ci-release.md`, `docs/runpod-service.md`: documented the correction and distinguished local source approval from the pending artifact scan.

Training, the CPU Dockerfile, model source/version, application Python, workflow policies, secrets and main branch were not modified. No vulnerability suppression or manual release tagging was added.

### Independent local verification and gates

- Full unittest discovery passed with **821 tests, no skips** on Python 3.11.16, 3.13.5 and 3.14.7. Logs: `/tmp/envai-pii-remediation-tests-final.log`, `/tmp/envai-pii-remediation-tests313.log`, `/tmp/envai-pii-remediation-tests314.log`.
- Branch-aware coverage for the changed test module is **98%**; all newly added executable test lines ran. Coverage file: `/tmp/envai-pii-remediation.coverage`. Requirements and Dockerfile instructions have no meaningful Python line-coverage percentage; their behavior is covered by the extracted-check tests and actual container execution, not a claim that test-file coverage measures the image runtime.
- In a disposable Podman container from the exact pinned Python base, with no network, dropped capabilities and bounded memory/CPU, independently extracted and executed the exact Dockerfile check. It rejected the original setuptools 79.0.1. Offline installation of the official 80.10.2 wheel replaced it, the same check and `pip check` passed, and inspection confirmed the old vendor metadata directories were removed. Containers exited with `--rm`.
- Inspected the actual diff and verified `git diff --check`; no unrelated executable files changed and no tests were removed or skipped.
- Hybrid quality judgment: **PASS** from `quality-gate-b` after clarifying that the applicable contributing guide is root `CONTRIBUTING.md`, not the absent `.github/CONTRIBUTING.md`. The first response requested that path clarification and did not issue a verdict.
- Focused security validation: **PASS** from `security-review-specialist-b` for the source correction only. This is not a clean-image claim and does not replace the hosted scan.

### Successful publication and artifact identity

Committed and pushed the approved correction as `6c9e4aeef964cf25a7ed40b0c0efaa732921b182`, `build(gpu): patch vulnerable setuptools vendored dependencies`, without a skip marker. The [Release run 39968680451](https://github.com/digitalygo/envai-pii/actions/runs/39968680451) passed and created [v1.0.0-dev.2](https://github.com/digitalygo/envai-pii/releases/tag/v1.0.0-dev.2) at that SHA. The automatic [publisher run 39968768255](https://github.com/digitalygo/envai-pii/actions/runs/39968768255) completed successfully, including all three Python test jobs, GPU build, remote identity verification, Trivy policy gate, tag promotion and final tag verification.

- Approved registry manifest: `sha256:a0b25f412c3bcf5741a27cd2afddf4ad0ffe534a16bb3277fb7a0d78dee60733`.
- Registry package version ID: `1435321891`.
- Tags: `dev`, `1.0.0-dev.2`, `1.0.0-dev.2-6c9e4aeef964`.
- Preferred RunPod test reference: `ghcr.io/digitalygo/envai-pii@sha256:a0b25f412c3bcf5741a27cd2afddf4ad0ffe534a16bb3277fb7a0d78dee60733`.

The hosted installation log confirms setuptools 79.0.1 was removed and 80.10.2 installed. The actual Dockerfile vendor-floor check and `pip check` both passed, as did the existing CUDA-build/model-file checks. The remote Trivy result was exactly **`scan gate passed: 0 blocker(s), 63 unfixed ignored`**. The two fixable HIGH findings no longer block publication; 63 findings without a fix remain accepted by the unchanged policy. This is not a claim of zero vulnerabilities or unconditional safety.

After CI completion, independently queried GitHub Packages and used read-only Docker Buildx remote inspection to verify that all three tags resolve to that exact manifest digest. Ran the repository's remote identity validator against the actual raw manifest and configuration; linux/amd64 identity, non-root user, release revision/version labels and absence of an embedded API token passed. Buildx was used only for registry metadata inspection, not to start a local Docker workload. The original blocked digest remains untagged and was not promoted or deleted.

### Closure and remaining verification boundary

Updated the three deployment documents and this operation to record actual publication, the residual findings and the next synthetic Pod test. A separate documentation-only commit does not change the released executable Git tree and does not warrant another image build. No new quality or security judgment is required for that documentation-only closure.

Main remains at `30d6f9c675e245bc8494df959adaeaa9d8de35c7`; package visibility remains public, with no manual visibility or credential mutation. No RunPod Pod was provisioned, no real personal document was uploaded, no training ran and no GPU inference or RunPod proxy behavior was tested. Completion means the requested dependency remediation and approved GHCR publication, not production deployment or GPU runtime certification.

Evidence logs are `/tmp/envai-pii-remediation-release-watch.log`, `/tmp/envai-pii-remediation-publish-watch.log` and `/tmp/envai-pii-remediation-publish-full.log`; raw remote metadata is `/tmp/envai-pii-remediation-remote-{manifest,config}.json`. Test environments, downloaded wheel fixtures and the task-only pinned base image are removed at closure. No task container or local server remains running, and no unrelated image or resource is pruned.
