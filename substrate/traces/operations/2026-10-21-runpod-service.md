---
status: blocked
created_at: 2026-10-21
updated_at: 2026-10-25
files_edited:
  - Dockerfile.gpu
  - src/app/requirements-gpu.txt
  - src/app/cloud_service.py
  - src/app/smoke_cloud.py
  - tests/test_cloud_service.py
  - tests/test_gpu_image.py
  - tests/test_smoke_cloud.py
  - docs/runpod-service.md
  - docs/runpod-diagnostic-command.md
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
  - Provision the explicitly requested GPU test Pod and verify its public CUDA readiness while preserving existing account secrets.
  - Bind a user-approved dedicated test secret and prepare private client parameters without changing the original shared secret.
  - Supply the host C compiler and libc headers required by Triton while preserving the model and GPU runtime pins.
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

## Update 2026-10-24: GPU Pod provisioned, authenticated smoke blocked

### Scope and preflight

The user explicitly authorized publishing one running GPU Pod for their tests. Continued on the previously approved `dev` branch at `6dc431395e53432dee98f199ef4429d6f818233c`, clean and synchronized, without changing main, application code, dependencies, training or the image. Re-read repository rules and deployment guidance; directives and expectations directories remain absent. Native Runpod MCP OAuth was verified with an authenticated read; no provider API key was created or read.

Revalidated the exact remote linux/amd64 manifest and configuration using the repository identity validator. The selected image remains `ghcr.io/digitalygo/envai-pii@sha256:a0b25f412c3bcf5741a27cd2afddf4ad0ffe534a16bb3277fb7a0d78dee60733`, release `v1.0.0-dev.2`, with the previously recorded 63 unfixed findings and no scan bypass.

Live stock changed during preflight: the initial RTX 2000 Ada and then RTX 4000 Ada choices were unavailable before reservation. No Pod creation was attempted for those shapes. Before the actual mutation, quoted the available fallback A40 rate of USD 0.59/hour, plus disk charges, to the user. Fresh Secure Cloud catalog reads showed HIGH A40 availability in `EU-SE-1` and host CUDA 13.2. A single specialized backend member made exactly one successful Pod create call for that shape, then the leader independently read it back.

### Resource identity and configuration

- Pod ID: `30cjb6pzibilrh`.
- Name: `envai-pii-test-20261024`.
- State: `RUNNING`.
- Cloud and location: Secure Cloud, `EU-SE-1`, Sweden.
- GPU: one NVIDIA A40. The catalog identifies its GPU class; the pod response's `gpu.memory: 50` is host allocation metadata and is not a measured VRAM requirement.
- Read-back cost: USD 0.59/hour, with disk billing treated separately.
- Container disk: 20 GB; no persistent, network or global volume was created, and `mounts` is empty.
- Configured ports: only `5005/http`; no direct public TCP, SSH or Jupyter was enabled.
- Image CMD, entrypoint and arguments were not overridden.
- `PII_ANALYSIS_TIMEOUT_SECONDS` is `60`.
- `PII_API_TOKEN` references the pre-existing user account secret `pii_api_token` through the documented placeholder. Only secret metadata was read; no secret was created, read for its value, rotated or deleted. The Pod read-back retains the reference rather than a plaintext token.
- HTTPS base URL: `https://30cjb6pzibilrh-5005.proxy.runpod.net`.

The provider runtime also reports its own management mapping in addition to the requested service port. This was not an extra port requested by the agent. No unrelated Pod or account resource was changed.

### Independent runtime verification

- Boot/system logs confirmed the exact pulled digest. Later container logs showed Gunicorn listening on `0.0.0.0:5005`, `gthread`, and a booted worker.
- Fresh Pod read-back populated the service runtime mapping for private port 5005 and retained RUNNING state.
- External HTTPS `GET /health` returned 200 with `status: ok`, `model_loaded: true` and `device: cuda`. This verifies actual CUDA execution and GPU model readiness on this host, not merely a CUDA-built wheel. An earlier transient proxy 403 during boot cleared without a Pod replacement or configuration change.
- The canonical synthetic smoke client passed health, unauthenticated analyses and unauthenticated settings. It then failed at the authenticated JSON EMAIL check. A bounded diagnostic confirmed HTTP 401, not a model accuracy or response-shape failure.
- The previously generated, user-approved debug credential from the conversation does not authenticate against the existing account secret. It was supplied only in memory to the existing smoke client, not printed, stored in a file or passed as a process argument. No credential value is recorded in this trace.
- A negative test using the literal secret-reference placeholder also returned 401; the service is not accepting that predictable configuration string as its credential. The token mismatch is not being bypassed.
- Leader-owned local full unittest discovery passed: 821 tests, no skips, in a disposable Python 3.11 environment with the approved light dependencies. Log: `/tmp/envai-pii-pod-unit-tests.log`. No executable source lines changed; delta line coverage is N/A for the remote configuration.

The six-check smoke has not passed, and PDF redaction has not been tested on this Pod. A read-only focused security review found no blocking issue in the deployed network/auth/reference configuration but explicitly required successful live smoke before a complete runtime-verification claim. The deterministic runtime gate remains blocked by the credential-dependent 401, so no final quality PASS or complete test-readiness claim is made.

### Handoff and billing boundary

The Pod is intentionally left running because the user asked to use it for tests. GPU and disk billing continue until it is stopped or terminated; no automatic termination was configured or promised. The existing shared secret was preserved rather than overwritten to make a test pass.

The next action requires the user: either use the actual value they stored in `pii_api_token`, or explicitly authorize a dedicated test secret and rebinding/restarting only this conversation's Pod. Then rerun the entire synthetic smoke and finish the quality judgment before declaring authenticated end-to-end validation complete. The public health probe alone is not that validation. Real personal documents still require separate provider, region and retention approval.

## Update 2026-10-24: dedicated secret and test file prepared, restart blocked by host capacity

### Approved correction and preserved state

The user approved creating a dedicated test secret with the previously generated debug value, rebinding only this Pod, and restarting it. They reported stopping the Pod beforehand and requested a file containing test parameters. Fresh MCP read-back confirmed `EXITED`, unlocked, with `start` allowed; image, A40 allocation request, Secure `EU-SE-1`, disk, ports and rate remained unchanged. The original user secret `pii_api_token`, ID `ofbngvmbbo`, was preserved.

Created and independently verified the metadata for dedicated secret `envai_pii_test_30cjb6pzibilrh`, ID `yc09axtdyf`. Updated only Pod `30cjb6pzibilrh` to reference that secret, preserving its other environment keys. Fresh Pod read-back confirms the new reference and timeout 60. No secret value is included in this trace, Git or tool-result summaries.

### Restart result

The first start attempt did not restart the Pod. A subsequent read-only diagnostic could not recover its original error and encountered an API deadline on a log read; that deadline is not asserted as the cause of the start failure. After rechecking that the exact Pod remained EXITED, unlocked and eligible for start, authorized one bounded additional start attempt, with no replacement or retry loop.

That attempt returned HTTP 400 with the explicit provider message: `There are not enough free GPUs on the host machine to start this pod.` The GPU released when the user stopped the Pod is not available on its bound host. The Pod remains EXITED. Data-center-wide stock does not prove capacity on that machine. No additional Pod was created, no rate was increased, and no existing Pod was terminated or migrated. Further recovery requires explicit authorization to recreate or migrate, not an unbounded start loop.

### Private test artifact

Prepared `/home/lorenzo/Documents/.secrets/envai-pii-runpod-test/envai-pii-runpod.postman_collection.json`, outside Git. The new dedicated directory is mode 0700; the file is mode 0600, owned by the user, and neither is a symlink. The collection contains the user-approved test credential, so it must remain local and unshared. Do not attach or commit its contents.

Leader-owned JSON and request-contract verification confirmed the base URL, Bearer variable binding, unauthenticated health request, four request definitions, correct v1 `files` versus legacy `file` field names, no manual multipart Content-Type, and no scripts. A redacted review copy was created at `/tmp/envai-pii-postman-collection-redacted.json`; it contains no credential value.

The review also found an unrequested EMAIL-only category filter and extra synthetic text in the multipart file request. This is narrower than the intended default full-category file analysis. A bounded delegated correction to remove those two fields was refused before touching the file because the member incorrectly selected an orchestration role and could not delegate further. The available backend member therefore produced no correction; the other backend members use the provider already excluded for its known HTTP 402 outage. No implementation was rerouted to another role or applied by the leader. The collection remains usable for its documented EMAIL-only example but is not approved as a general full-category upload test until corrected. Do not hide this limitation or mark the artifact quality gate passed.

### Handoff

The dedicated secret and binding are verified, but authenticated runtime smoke cannot run while the Pod is EXITED. The previously blocked live smoke remains unresolved; no new successful end-to-end or PDF claim is made. GPU compute is not running; storage, if any, follows the provider's stopped-resource billing rules. Source code, dependencies, workflows, main, the original account secret and all other resources remain unchanged. The earlier uncommitted audit update is preserved.

The remaining actions are explicit permission to move or recreate the Pod on available infrastructure, followed by updating the client URL if its ID changes, correcting the file request's unintended filter through an available backend member, rerunning the full synthetic smoke and completing the focused security and quality judgments. The existing local collection path can be handed to the user now with its stopped-Pod and EMAIL-only limitations stated.

## Update 2026-10-25: recreated Pod reaches CUDA readiness but inference returns 500

### New user-supplied resource and scope

The user recreated the Pod themselves and supplied `https://2glj7taobhnhvg-5005.proxy.runpod.net`, reporting `500 internal_error` from POST `/api/v1/analyses`. Native MCP read-back identifies Pod `2glj7taobhnhvg`, name `envai-pii-test-20261024-migration`, RUNNING on one A40 in Secure `EU-SE-1`, at the reported rate USD 0.59/hour. It uses the same approved immutable image, only port `5005/http`, no command override and the dedicated test-secret reference created earlier. This new Pod is user-created; diagnosis does not authorize deleting or replacing it.

### Independently reproduced behavior

Using only synthetic text and the credential read in memory from the private collection:

- External GET `/health`: 200, `status: ok`, `model_loaded: true`, `device: cuda`.
- Canonical smoke: health and both unauthenticated 401 checks pass; authenticated JSON EMAIL fails.
- A separate minimal authenticated POST `/api/v1/analyses` confirms HTTP 500 with code `internal_error`.
- The same synthetic text through legacy POST `/analyze` also returns HTTP 500, code `internal_server_error`.
- Container logs show Gunicorn binding on 5005, the GPU model weights loading and `Modello pronto.`. They do not reveal the inference exception; the privacy boundary intentionally sanitizes error logging and responses.

The failure is not reproduced by bad credentials or a multipart-only request. It affects the shared inference path on the GPU deployment; CUDA/model readiness alone is not a forward-pass guarantee.

### Local falsification checks

Ran the exact current application source read-only in a disposable network-isolated CPU image containing the real local model v1.5.0, Torch 2.13.0+cpu, Transformers 5.14.1 and NumPy 2.4.6. Direct model detection and both v1 and legacy synthetic HTTP calls return success (200 for the routes). This narrows the failure to the GPU execution environment or GPU-specific model path, but does not identify the actual exception.

An initial diagnostic mount at `/src` produced a self-induced model-path resolution IndexError and was discarded. Repeated the experiment at the canonical `/app/src/app` path with the explicit baked model directory; no source change was involved. Containers exited with `--rm`; no local diagnostic workload remains.

Local introspection identifies `ModernBertForTokenClassification`, float32 weights and SDPA attention. The checked modeling module contains no `reference_compile` or `torch.compile` call. Therefore a missing compiler or compilation setting is not asserted as the cause from guesswork. Read-only analyst hypotheses remain forward-pass failure, adapter output shape, or shared post-inference processing; none substitutes for the actual GPU exception.

### Diagnostic boundary and next approval

The connected Runpod MCP surface exposes metadata and bounded logs but no command execution or terminal tool. No hidden management endpoint, SSH installation, provider key, unsanitized debug mode or alternate-credential workaround was used. No Pod configuration, lifecycle action, source, image or private collection was modified during diagnosis; only the existing audit is extended.

The next evidence required is the actual exception from a single known synthetic model forward pass on this GPU. Ask the user to authorize a temporary diagnostic restart of this exact new Pod, or to run a local console diagnostic themselves. Any diagnostic must run only the fixed synthetic input before serving requests, avoid logging real documents or credentials, and restore the reviewed startup configuration. Do not rebuild or change model/dependency settings speculatively, and do not claim that this 500 is fixed. There is no executable delivery delta to gate yet.

### Authorized diagnostic restart blocked before execution

The user approved the proposed temporary diagnostic restart. The delegated backend member was asked to prepare and locally test a bounded, synthetic-only runner before any Pod mutation, so privacy and startup restoration could be independently reviewed first. It stopped before creating any artifact, reporting that it had selected the orchestrator role and could not delegate from a child session. Its only remote action was a read-only Pod GET.

The other backend members use the provider already excluded for its known HTTP 402 outage; no fallback probe was made against that excluded provider. No work was rerouted to another role and the leader did not implement the runner or mutate the Pod directly. Preparation and execution therefore remain blocked by implementation-agent availability, not by missing user approval.

A fresh independent Pod read confirms RUNNING, the original empty `args` field, the same pinned image and reported USD 0.59/hour rate. No diagnostic restart occurred, no debug mode was enabled, no startup configuration needs restoration and no new local test resource or script exists. No new executable delta was delivered, so quality and security judgments were not invoked for a nonexistent change. The exact GPU inference exception and the underlying 500 remain unresolved at this checkpoint.

The compatible next diagnostic is a read-only invocation of the existing `app.analyze` function on the fixed synthetic contact from the user's Pod terminal, ideally in a worker thread matching Gunicorn. That check does not require changing the public service configuration, but cannot be executed through the currently available Runpod MCP tools. Alternatively, restore an available backend member before resuming the approved diagnostic-startup workflow. Do not claim diagnosis or repair success while this evidence is missing.

## Update 2026-10-25: confirmed Triton compiler dependency and verified source correction

### Root cause established by the user's synthetic diagnostic

The user supplied the real threaded diagnostic traceback from the GPU Pod. It reaches ModernBERT rotary positional matrix multiplication, then Torch's native `bmm_outer_product` Triton implementation, NVIDIA `CudaUtils`, `compile_module_from_src` and finally `triton/runtime/build.py`, which raises `RuntimeError: Failed to find C compiler`. This confirms the cause that could not safely be inferred from generic API 500 responses or the absence of `torch.compile` in the model module. The compiler is needed by Torch/Triton's own runtime host helper, not by an explicit model compilation setting.

No credentials or real document contents appear in that supplied diagnostic; its input was the fixed synthetic contact. No temporary diagnostic startup or public debug route was applied to the user's Pod.

### Minimal implementation and verification

A backend member completed the now-mechanical source correction, separate from the earlier failed diagnostic-runner preparation:

- `Dockerfile.gpu` adds `gcc` and `libc6-dev` to the existing official bookworm apt transaction, retaining `--no-install-recommends` and apt-list cleanup. Compiler and headers remain available for Triton under UID 10001.
- A fail-closed build probe writes a trivial fixed C program including `Python.h` and `stdlib.h`, compiles it with the running Python's include flags, runs it and removes both fixtures before heavy pip/model downloads.
- Two GPU image contract tests cover explicit package inclusion, headers, actual compilation, execution, cleanup and instruction ordering. No existing assertion was weakened or test removed.
- The pinned base, Python and all ML requirements, model, CPU image, training, application, API contracts, authentication, offline flags and logging are unchanged. No fake CC path or Triton disabling workaround was introduced.

Official package verification confirmed that bookworm's gcc defaults package only Recommends the libc development headers, so `libc6-dev` must be explicit with `--no-install-recommends`. The official Python image already supplies its own Python headers; no unrelated Debian interpreter/dev package or external apt repository was added.

The leader independently ran the exact apt transaction and compiler probe in the digest-pinned Python base. The unchanged base failed for missing gcc; after installation the probe and fixture cleanup passed both as root and as UID 10001. Observed compiler: Debian GCC 12.2.0-14+deb12u1. Test containers were removed with `--rm`.

Full light-dependency unittest discovery passed twice: **823 tests, no skips**. Branch-aware coverage of the modified test module is **99%**, with all added executable test lines covered; Docker configuration and the C probe are not assigned a misleading Python production line percentage. Logs: `/tmp/envai-pii-triton-tests-final.log`, `/tmp/envai-pii-triton-compiler-check.log`; coverage: `/tmp/envai-pii-triton.coverage`.

The first hybrid quality judgment failed only because a changelog status still called the completed native compiler probe pending. A documentation-only correction reports its actual pass and qualifies the diagnostic command's future GPU success as expected, not guaranteed. The deterministic suite was rerun and the final independent quality judgment is **PASS**. Focused compiler-delta security review is **PASS**; runtime compiler availability is the intended dependency and the unchanged remote scan gate still governs publication.

### Documentation and private test parameters

Added `docs/runpod-diagnostic-command.md` with the exact already-provided read-only command, fulfilling the prior request for a copyable file. Updated deployment troubleshooting and changelog to distinguish confirmed root cause, verified source correction and pending artifact/GPU validation.

A separate bounded backend task also corrected the private Postman collection at its existing non-Git path. It now targets the user-supplied Pod URL `https://2glj7taobhnhvg-5005.proxy.runpod.net`, and its multipart file request contains only the `files` upload: the unrequested synthetic text and EMAIL-only filter are removed, so all categories apply by default. The credential is unchanged, the file remains 0600 in a 0700 directory, and no scripts or redirect following were introduced. The leader verified those invariants and an authenticated GET `/settings` returned 200 using the file's opaque credential. Focused review of the redacted client delta is **PASS**. No credential appears in Git or this operation.

### Publication boundary

The source and private-client correction are accepted, but the running Pod still uses the old image and its inference error is not yet fixed there. Next is publishing the compiler-enabled GPU image through the existing dev release/build/remote-scan chain, then obtaining user authorization for applying it to their recreated Pod and proving the real GPU forward. No current Pod restart, new GPU, remote image replacement or inference-success claim has occurred in this source-correction phase.
