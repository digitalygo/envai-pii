---
status: completed
created_at: 2026-10-21
updated_at: 2026-11-02
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
  - src/app/request_admission.py
  - src/app/runtime_execution.py
  - src/app/gunicorn_config.py
  - src/app/guardrail_api.py
  - src/app/app.py
  - src/app/pdf_export.py
  - Dockerfile
  - tests/test_request_admission.py
  - tests/test_guardrail_concurrency.py
  - tests/test_runtime_execution.py
  - tests/test_codifiche.py
  - tests/test_guardrail_api.py
  - tests/test_guardrail_categories.py
  - tests/test_guardrail_multifiles.py
  - tests/test_guardrail_pdf_privacy.py
  - docs/GUARDRAIL_API.md
  - docs/guardrail-openapi.yaml
  - docs/runpod-load-pricing.md
  - docs/runpod-single-gpu-capacity.md
  - tests/test_upstream_auth.py
  - docs/verda-service.md
  - tools/__init__.py
  - tools/verda_model_experiment/__init__.py
  - tools/verda_model_experiment/fixture.py
  - tools/verda_model_experiment/runtime.py
  - tools/verda_model_experiment/package.py
  - tools/verda_model_experiment/measure.py
  - tools/verda_model_experiment/resources.py
  - tools/verda_model_experiment/gpu_monitor.py
  - tools/verda_model_experiment/gpu_runtime.py
  - tools/verda_model_experiment/gpu_profile.py
  - tests/test_verda_gpu_monitor.py
  - tests/test_verda_gpu_package.py
  - tests/test_verda_gpu_profile.py
  - substrate/traces/reports/2026-10-28-verda-eight-model-gpu-profile.md
  - tests/test_verda_model_runtime.py
  - tests/test_verda_model_package.py
  - tests/test_verda_model_measure.py
  - substrate/traces/plans/2026-10-27-verda-model-copies.md
  - substrate/traces/reports/2026-10-27-verda-model-copies.md
  - src/app/model_batching.py
  - tests/test_model_batching.py
  - tools/verda_model_experiment/batch_package.py
  - tools/verda_model_experiment/batch_runtime.py
  - tests/test_verda_batch_package.py
  - tests/test_verda_batch_runtime.py
  - tools/verda_model_experiment/batch_experiment.py
  - tools/verda_model_experiment/transport.py
  - tests/test_verda_batch_experiment.py
  - tests/test_verda_transport.py
  - tools/verda_model_experiment/startup.py
  - tests/test_verda_copy_resources.py
  - tests/test_verda_startup.py
  - docs/chunk-batching.md
  - substrate/traces/plans/2026-10-28-chunk-batching.md
  - substrate/traces/reports/2026-10-28-chunk-batching.md
  - substrate/traces/research/2026-10-29-chunk-batching-handoff.md
  - substrate/traces/plans/2026-10-29-copies-startup-comparison.md
  - substrate/traces/reports/2026-10-30-copy-count-startup.md
  - substrate/traces/plans/2026-11-01-verda-n8-b8-image-scale-to-zero.md
  - substrate/traces/reports/2026-11-01-verda-n8-b8-ordinary-image-rollout.md
  - docs/gpu-worker-startup.md
  - src/app/gpu_worker_startup.py
  - tests/test_gpu_worker_startup.py
  - substrate/traces/reports/2026-11-02-verda-online-capacity-blocker.md
  - substrate/traces/reports/2026-11-02-verda-n8-b8-online.md
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
  - Place one explicitly approved replacement test service on available A40 hardware, preserve the stopped Pod and verify real four-client GPU service requests.
  - Complete the approved Verda CUDA 12.6 deployment with the same PyTorch release and model, verified provider authentication and natural scale-to-zero.
  - Measure unchanged Verda HTTP response times for synchronized bursts of 4, 8 and 16 requests with one identical 45000-character synthetic document.
  - Prepare and verify four guarded model-copy configurations while stopping before live activation when no operational delegate can execute the approved changes.
  - Complete the four-way live comparison, retain every measured outcome including a disclosed replay, and leave the final verified eight-copy definition at idle zero for user selection.
  - Implement approved same-analysis chunk batching with default one and disclose the real-GPU comparison blocked by provider capacity.
  - Implement a reusable collector and transport module package, complete the B4, B8 and B16 GPU matrices against the preserved B1 baseline with full operational disclosure, recommend B8 as the production validation candidate without changing the source default, and verify final paused/min-zero shutdown.
  - Extend the diagnostic harness for 8, 12, and 16 model copies at fixed B8 with native startup instrumentation, complete the live 3x6 copy-count and startup comparison with a fresh N8 control, recommend 8 copies with B8 as the candidate resource and startup tradeoff up to 32 concurrent clients without changing defaults, and verify final paused/min-zero shutdown.
  - Record the 2026-11-02 owner-authorized attempt to bring the ordinary N8/B8 Verda deployment online, verify private client fixes offline, disclose the external provider placement/capacity blocker (NoNodesAvailable) and final quality-gate-b FAIL, and confirm failure-safe paused/min-zero shutdown.
supporting_docs:
  - ../reports/2026-11-02-verda-n8-b8-online.md
  - ../reports/2026-11-02-verda-online-capacity-blocker.md
  - ../plans/2026-11-01-verda-n8-b8-image-scale-to-zero.md
  - ../reports/2026-11-01-verda-n8-b8-ordinary-image-rollout.md
  - ../../../docs/gpu-worker-startup.md
  - ../plans/2026-10-29-copies-startup-comparison.md
  - ../reports/2026-10-30-copy-count-startup.md
  - ../plans/2026-10-28-chunk-batching.md
  - ../reports/2026-10-28-chunk-batching.md
  - ../research/2026-10-28-chunk-batching-inspection.md
  - ../research/2026-10-29-chunk-batching-handoff.md
  - ../../../docs/chunk-batching.md
  - ../reports/2026-10-28-verda-eight-model-gpu-profile.md
  - ../plans/2026-10-27-verda-model-copies.md
  - ../reports/2026-10-27-verda-model-copies.md
  - ../../../docs/verda-service.md
  - ../research/2026-10-21-runpod-readiness.md
  - ../../../docs/runpod-service.md
  - ../../../docs/GUARDRAIL_API.md
  - ../../../docs/ci-release.md
---

# GPU API service preparation

## Current outcome

**2026-11-02 current status: live acceptance PASS, healthy and unpaused.** The explicitly requested fifth attempt on the same L40S/dev.8 profile proves eight CUDA/float32 B8 workers, a canonical cold HTTP 200, health/auth and 72/72 valid benchmark requests. Native scale-to-zero and two empty observations more than 5 s apart are verified; final independent management read at 15:35:34Z confirms min 0/max 1/CC16/TTL600 and zero idle replicas. No final pause, source/image/oracle change or new release. Details: [successful deployment report](../reports/2026-11-02-verda-n8-b8-online.md). Earlier placement failures below remain historical.

**2026-11-01 status (historical): blocked for live validation of the ordinary `N8 / B8` image.** Source, CI image (`v1.0.0-dev.8`) and Verda configuration are done; the live validation stopped at `auth_pre_positive` with `0` health/auth probes and `0/72` benchmark requests, so `CC8`/`CC16` metrics are `N/A`. The deployment `envai-pii-test` is `paused`, `min=0`, `max=1`, zero replicas (latest management-only parent verification `2026-11-01T23:43:58.199710+00:00`, all 10 configuration/state checks passed). This is a failure-safe forced pause, not a ready state and not a natural scale-to-zero. Both authorized GPU activations are consumed; no third activation, automatic retry or new release is allowed without a new owner permission. See the [rollout report](../reports/2026-11-01-verda-n8-b8-ordinary-image-rollout.md) and the [session plan](../plans/2026-11-01-verda-n8-b8-image-scale-to-zero.md).

Previous native verification at `2026-10-30T00:44:20.956746+00:00` (after `N16` cleanup at `00:38:14.931Z`): **`paused`, minimum `0`, maximum `1`, concurrency `32`, `replicas.list: []` (zero active replicas)** on `envai-pii-test`. Compute for this test deployment is off (without claiming global account billing is zero), and the diagnostic `N16 / B8` overlay command (`16` model copies, `PII_MODEL_BATCH_SIZE=8`, `56` command arguments, `105` environment entries) remains configured on `envai-pii-test-0` but inactive.

The follow-up 3x6 model-copy and startup comparison at fixed `PII_MODEL_BATCH_SIZE=8` (`B8`) (`N8`, `N12`, `N16` across client concurrencies `1`, `2`, `4`, `8`, `16`, `32`) on the same single L40S (`size=1`, `max_replica_count=1`, `float32`, pinned image `c1d9d9c089047f7c1e4b7b0815e91a12cd810c963ddb58ba1f0da1233e961714`) is **completed and independently verified** alongside the preserved historical 4x6 chunk-batching comparison (`B1`, `B4`, `B8`, `B16` at `8` copies). All 18 cells of the new series (`402/402` validated HTTP `200` requests per copy count across `81` bursts and `27` groups, `1206/1206` new measured requests with unique composite IDs and zero replay, plus one excluded authenticated HTTP `200` warmup per matrix, using an explicitly authorized fresh `N8` control rather than substituting the older `4.026919 req/s` `B8` run) matched the exact `45174`-byte (`63`-chunk) request body and canonical response oracle (`ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40`). At `CC32`, throughput is `3.861909 req/s` (`N8`, mean `5.971478 s`, p95 `8.015375 s`), `4.001195 req/s` (`N12`, `+3.60665%` vs `N8`, mean `5.793653 s`, p95 `7.899093 s`), and `3.818058 req/s` (`N16`, `-1.13547%` vs `N8`, mean `5.637245 s`, p95 `8.197978 s`), while the native same-pod Gunicorn startup proxy (`first_gunicorn_listening_to_all_ready`, one observation per copy count) increases from `15.450720 s` (`N8`) to `17.542707 s` (`N12`) and `19.874904 s` (`N16`, `+4.424184 s` / `+28.63416%` vs `N8`), and peak GPU VRAM increases from `14.106934 GiB` (`70.224%` min free of `47.376160 GiB`) to `21.160950 GiB` (`55.334%` min free) and `28.213013 GiB` (`40.449%` min free). **`8` model copies with `PII_MODEL_BATCH_SIZE=8` (`N8 / B8`) is recommended as the best candidate resource-footprint and startup tradeoff for workloads up to `32` concurrent clients**, while `src/app/model_batching.py` keeps `DEFAULT_BATCH_SIZE = 1`. The application core (`src/app/app.py`, `src/app/model_batching.py`), `fixture.py`, and `transport.py` are unchanged, while the 21-file diagnostic/test package (`46d02491337709447e475ebaca92e61f444bf0ae9871f638a04ffce585047a0e`, XZ archive `17216` bytes `015dd46695c207a36af412bafde7e96031ccce1c5b81ae5a34726f9bbe13dcdb`) passed **1233 tests with no skips** (`74.308 s`), `412/443` (`93.0023%`) production executable delta coverage, `946/949` (`99.6839%`) test delta coverage, and `quality-gate-a` PASS (`security-review-specialist-a` PASS on initial preparation `2979376b44178d5a6568c421d8a529ec86372d9282010621901e9c07fc822acf`, followed only by offline lifecycle metric disambiguation in `startup.py`). See the [copy-count and startup report](../reports/2026-10-30-copy-count-startup.md), the [copy-count and startup plan](../plans/2026-10-29-copies-startup-comparison.md), the [historical chunk batching report](../reports/2026-10-28-chunk-batching.md), and the [chunk batching guide](../../../docs/chunk-batching.md).

### State at the intermediate B4 warmup closure

At the earlier `2026-10-29T13:13:51Z` checkpoint, the deployment was `paused`, minimum `0`/maximum `1`/concurrency `32`, zero replicas. Credit had been restored and `B4` warmed all eight models with the exact canonical result, but the earlier ephemeral collector timed out before the matrix; `B8`/`B16` had not yet been activated. That execution-capability blocker was subsequently resolved by the reusable collector and transport module package documented below.

### State at the first batching closure

Chunk batching1/4/8/16 is implemented and independently verified in the local dev source, default1, without cross-request mixing. Both1119-test suites and focused quality/security reviews pass; executable delta550/551lines99.82percent. The new image is not published. The live comparison stopped before any inference: a single controlled pause/PATCH/resume stored diagnosticB1, provider env merging differed from the predicted replacement, and L40S scheduling failed for no nodes. Independent14:40:37Z reads confirm unhealthy, one error replica with no running GPU, user min1/max1/concurrency32 retained. B4/B8/B16 were not activated and no new speedup is claimed. See the [batching report](../reports/2026-10-28-chunk-batching.md) and [blocked living plan](../plans/2026-10-28-chunk-batching.md).

### Earlier verified outcomes

The user returned to L40S and the GPU-observation test is now completed: **402/402 measured analyses returned validated200**, with310activeNVMLsamples independently matched to provider records. Eightmodels, float32, B1 and the c1d9 image remain unchanged. [The GPU report](../reports/2026-10-28-verda-eight-model-gpu-profile.md) contains six latency/throughput/GPU/power rows and preliminary deviations. Finalnative verification at2026-10-28T11:10:41Z confirms exact correcteddefinition, one runningL40S, the user'sminimum1/maximum1/concurrency32, and providercontrolstatusupdating ratherthanhealthy. No productionpromotion or strongeravailability/billing claim ismade.

The 1/2/4/8-model comparison is completed with a disclosed N8/CC1 replay limitation. The [final experiment report](../reports/2026-10-27-verda-model-copies.md) includes all759actualattempts,739validsuccesses,20HTTP429 and four resource/latency comparisons. The last verified eight-copy experimental definition is retained, healthy with zero idle replicas and maxoneGPUallocation; no winner was automatically promoted or original configuration restored.

The latest Verda delivery is completed: `envai-pii-test` uses the scanned CUDA 12.6 `dev.7` image by digest, real GPU inference and provider-auth contrasts passed, and independent management reads show healthy, unpaused, zero replicas after natural idle scale-down. The initial RunPod preparation and all dated measurements below remain historical. Completion here does not claim that the earlier blocked RunPod replica-capacity sweep was completed.

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

### Compiler-enabled artifact publication verified

Committed and pushed the accepted source correction as `4d6037bfc0c5ba8220399afe58dde968ee4b74a4`, `build(gpu): add compiler for Triton runtime`. The [Release run 40140407527](https://github.com/digitalygo/envai-pii/actions/runs/40140407527) passed and created [v1.0.0-dev.3](https://github.com/digitalygo/envai-pii/releases/tag/v1.0.0-dev.3). The [publisher run 40140446020](https://github.com/digitalygo/envai-pii/actions/runs/40140446020) completed successfully, including all three Python jobs with 823 tests each, compiler installation, the actual C compilation/execution probe, image build, remote identity validation, Trivy gate and tag promotion/read-back.

- Published manifest digest: `sha256:2b0324fe6e154eadc270b1accf157519abb5cac1663453579d5f76e1cf2f2f13`.
- Remote config digest: `sha256:47bea1e9e0ad1293a3029f3ede8c858d35f73fb6bc82fd2e1a546debafb1b1d3`.
- GHCR version ID: `1441208809`.
- Tags: `dev`, `1.0.0-dev.3`, `1.0.0-dev.3-4d6037bfc0c5`.
- Scan result: **`scan gate passed: 0 blocker(s), 247 unfixed ignored`**. The residual count increased with the compiler dependency closure; it is disclosed, not represented as zero vulnerabilities. No secret or fixable HIGH/CRITICAL finding passed the unchanged gate.

The leader independently inspected all three remote tag references and confirmed each resolves to the published digest. Re-ran the repository remote manifest/config identity validator against actual registry bytes; linux/amd64, user `app`, source revision/version labels and absence of an embedded API token passed. Hosted logs show GCC 12.2.0-14+deb12u1, libc6-dev 2.36-9+deb12u14 and the compiler probe executing successfully before downloads. No manual image tag or gate bypass was used.

Publication evidence is in `/tmp/envai-pii-triton-publish-full.log`, `/tmp/envai-pii-triton-publish-watch-final.log`, `/tmp/envai-pii-triton-remote-manifest.json` and `/tmp/envai-pii-triton-remote-config.json`. The disposable local verifier and task-only Python base image were removed; no unrelated image was pruned.

Updated the deployment and CI guides and changelog to distinguish this verified new artifact from the still-running old image. These final edits are documentation-only and do not change the released executable tree. Main remains at `30d6f9c675e245bc8494df959adaeaa9d8de35c7`.

The user-created Pod `2glj7taobhnhvg` has not been modified. Asked for explicit permission to apply the new image and restart only its container, preserving the GPU. That approval and the subsequent real GPU forward/full synthetic smoke remain pending. The operation therefore stays blocked rather than declaring the live 500 repaired.

## Update 2026-10-25: verified v3 GPU serving and later user shutdown

The user subsequently explicitly approved the v3 image update and in-place container restart. Backend operations were delegated; a transient member log-read failure caused no mutation, and the leader independently obtained a fresh successful native log read before resuming. Applied only the image field to Pod `2glj7taobhnhvg`, then restarted its container once. No stop/start, GPU resize, migration, recreation or other resource mutation occurred.

Independent before/after native reads confirmed `RUNNING`, the exact v3 digest, A40 x1, EU-SE-1 and the same configuration: env mapping byte-for-byte, args, GPU, disk, mounts, ports, cloud, cost, registry, template, lock and networking. System logs confirmed download of the exact approved digest and container start at 23:46:23Z on 2026-10-24; container logs confirmed `Listening at: http://0.0.0.0:5005`, gthread, model loading on GPU and `Modello pronto.` at 23:46:30.806776880Z. No secret values were printed or copied.

The leader then executed the entire six-check remote synthetic smoke through the HTTPS proxy: CUDA health, unauthenticated guardrail/legacy rejection, actual JSON inference, seed reuse and multipart aggregate all passed. Additional default-category JSON and real synthetic PDF extraction/anonymization plus legacy redacted PDF returned 200; originals were absent from the tested anonymized text/PDF. Recorded request times were 0.51, 0.32 and 0.34 seconds, and the six-check smoke took 2.52 seconds total. These are functional observations, not load-capacity or accuracy benchmarks. Independent unit discovery also passed all 823 tests without skips. Evidence: `/tmp/envai-pii-runpod-v3-unit.log` and `/tmp/envai-pii-runpod-v3-live-checks.json`.

The earlier compiler-related 500 is therefore resolved for those verified real-GPU synthetic cases. Afterward, the user reported stopping the Pod for the night. That later statement supersedes the historical running state and observed $0.59/h rate; the current control-plane state was not queried during the following source-development phase and no restart was performed there. Local parameters remain outside Git, without a literal token in their Markdown file; the existing private Postman collection was not changed by the deployment.

## Update 2026-10-25: approved bounded concurrent admission

### Decision and scope

Before load testing, the user explicitly requested removal of the one-in-flight HTTP restriction and approved four configurable active analyses with a short finite queue. The old lock was deliberate backpressure, but rejected the second overlapping request regardless of available HTTP capacity. Its behavior is replaced by bounded FIFO admission; a one-line lock removal or adding GPU workers was rejected because shared Transformers state, PyMuPDF thread safety and the process-local preview cache require separate treatment.

The standard library resolves this feature without a new dependency or application stack. Implementation was split into disjoint admission/server and native-runtime slices. Only backend-dev-b was eligible: the other backend members' shared OpenRouter provider was already unavailable with HTTP 402 in this session, so a same-task race was not possible. Training, model and dependency pins, auth, category semantics, payload field sets, sensitive-data logging policy and main remain unchanged.

### Implemented behavior

- `PII_MAX_CONCURRENT_ANALYSES`: startup default 4, valid minimum 1 and hard maximum 16.
- `PII_MAX_QUEUED_ANALYSES`: startup default 4, valid minimum 0 and hard maximum 32. Zero disables queuing.
- `PII_QUEUE_TIMEOUT_SECONDS`: startup default 5 seconds, positive finite values, hard maximum 30 seconds. Invalid values use safe defaults and values above ceilings are clamped.
- Configuration/token, credential and model-readiness gates run before admission. Waiting requests do not read or parse the body. Admitted waiters read and process it normally; only an unavailable/full queue or an expired admission wait produces the existing 429 busy envelope before body access.
- FIFO controller state retains waiter tokens rather than payloads. Leases release once on every processing exit; cancellation, clock errors, timed-out waiters and error paths are covered. Explicit legacy lock injection remains available for internal callers and tests; the real default blueprint uses the new controller.
- Queue wait is bounded separately from the existing cooperative analysis budget, which still starts after the bounded body read. Waiting for native execution during analysis consumes that processing budget. Already-running native calls remain non-preemptible; neither a client timeout nor Gunicorn heartbeat changes the RunPod proxy limit.
- Two dedicated single-owner threads protect native operations, one for the single shared model and one for every service PyMuPDF entrypoint, including startup diagnostics, reset, extraction, rendering and export. Native PDF objects do not cross thread boundaries. Reentrant PDF helper calls execute inline on their owner.
- A submission gate remains owned until scheduled native work completes, avoiding a hidden executor backlog. If submit fails after queuing, the lane closes, cancels queued jobs and waits for running work before freeing the gate; repeated failures cannot accumulate orphan payloads. Expired native waiters do not start work.
- Both container commands load a shared pure Gunicorn config: one gthread worker, no preload, and active plus queued capacity plus two service threads, default 10. It imports no Torch, app or native executor before worker fork. The preview cache remains in the same process.

Four admitted HTTP analyses do not mean four parallel GPU forwards or four times throughput: model calls remain intentionally serialized for safety while other request phases can overlap. Real GPU concurrency and load capacity must be measured with the new artifact, not inferred from the previous v3 functional smoke.

### Independent verification and corrections

The orchestrator independently ran the declared full suite with real Flask/PyMuPDF and mocked model: **856 tests passed, no skips**. All **236/236 modified or added production executable lines are covered, 100%**. The native helper has 100% branch coverage, admission has all lines covered with 99% branch coverage, and Gunicorn config has 100% statement coverage. Actual Gunicorn 26.2 config parsing confirmed default 10 threads, mixed setting 11, maximum 50 and queue-disabled 3, always one gthread worker and no preload. YAML validation confirmed OpenAPI 0.4.0 and unchanged JSON request/response field sets. `git diff --check` passed.

Tests exercise four active requests, four FIFO waiters, ninth-request rejection without body access, auth/readiness precedence, timeout/cancellation/permit recovery, mixed JSON and real synthetic PDF requests with independent nonempty dictionary deltas, owner-thread identity, bounded native submission, nested calls, deadlines and interrupted/failed submissions. Existing AST fixtures use the actual runtime helper; no dummy execution path or test skip was introduced.

Three old deadline fixtures needed a justified update: the new owner-before-native checkpoint preserves the existing immediate post-model check, and PDF fixtures now expire after the actual open event rather than counting callbacks. All close/reset/error-precedence assertions remain, with an extra pre-open-expired/no-open recovery regression. No test was deleted or weakened. An initial parallel local matrix attempt stalled on pre-existing Node workflow tests under host resource pressure; sequential full runs passed, with no unrelated host process killed or repository test altered to hide that signal.

Initial source review found only documentation inconsistencies: wording conflated waiting with rejection, final test status was stale, and historical Pod-running observations conflicted with the later shutdown. Those were corrected and the deterministic suite rerun. Final independent hybrid quality judgment: **PASS**. Focused core-API security review and the native-submit cleanup follow-up: **PASS**; the orphan-retention advisory was closed by actual code and regression tests, not waived.

Evidence: `/tmp/envai-pii-concurrency-tests-final.log`, `/tmp/envai-pii-concurrency-coverage.json`, `/tmp/envai-pii-concurrency-delta-coverage.txt`, `/tmp/envai-pii-concurrency-baseline.sha256` and `/tmp/envai-pii-concurrency-preexisting-docs.diff`. Source implementation, test fixture changes, contracts and documentation have been independently inspected. The pre-existing three documentation additions are preserved, with historical state labeled explicitly.

### Release and live-validation boundary

The accepted source is ready for CI image publication. No new artifact, GPU concurrency result, throughput claim, Pod restart or provider configuration mutation is yet asserted for this concurrency phase. The user-reported shutdown remains respected. Publication and subsequent real-device testing are separate from the completed local implementation and review gates.

### Bounded-concurrency artifact published

Committed and pushed the reviewed feature as `0f161021b03b630ecf03556b6bf3cfe2f074cf75`, `feat(api): add bounded concurrent analysis queue`. [Release run 40194500271](https://github.com/digitalygo/envai-pii/actions/runs/40194500271) succeeded on Python 3.11, 3.13 and 3.14 and created [v1.0.0-dev.4](https://github.com/digitalygo/envai-pii/releases/tag/v1.0.0-dev.4). [Publisher run 40194544097](https://github.com/digitalygo/envai-pii/actions/runs/40194544097) completed all tests, build, remote identity, scan, promotion and tag-readback steps.

- Published digest: `sha256:c71a392411ab14aed2d4b28bb8e84e5e727f32df6e24e5238b11715d3fbaf9ef`.
- Config digest: `sha256:5bc8d0974a646e01ad9358813a79acf02c7be52cc8e454b0612dfb309ac1bb2b`.
- GitHub Packages version ID: `1443057951`.
- Verified tags: `dev`, `1.0.0-dev.4`, `1.0.0-dev.4-0f161021b03b`.
- Actual scan result: **`scan gate passed: 0 blocker(s), 247 unfixed ignored`**. The residual is not zero; policy is unchanged, with no finding suppression introduced.

The leader independently confirmed all three tag digests and the registry manifest/config identity. Revision/version labels, user `app`, the new shared Gunicorn config command and absence of a baked API token passed. Docker-specific Healthcheck is omitted by Buildx's typed `.Image` projection, not necessarily by the actual artifact; fetching the raw public config blob and checking its SHA against the manifest proved that the real Docker Healthcheck is preserved. The short-lived anonymous public-registry read token was held only in memory and never printed or persisted. No application or provider secret was used for that verification.

An additional local check used the pre-existing CPU runtime image with the reviewed source mounted read-only, network disabled, capabilities dropped and resource limits. Four simultaneous Flask request handlers completed real CPU model inference with independent nonempty deltas, followed by actual PDF extraction and real model inference through both native-owner lanes. This is stronger packaging/compatibility evidence than mocked inference, but is **not** GPU concurrency or capacity evidence. An earlier optional bounded probe did not finish within its timeout; separate baseline and candidate startup checks and the final unbuffered command completed successfully without further source changes. Every task-specific container was removed.

Evidence: `/tmp/envai-pii-concurrency-publish-full.log`, `/tmp/envai-pii-concurrency-remote-manifest.json`, `/tmp/envai-pii-concurrency-remote-config.json`, `/tmp/envai-pii-concurrency-raw-config.json` and `/tmp/envai-pii-concurrency-real-cpu-final.log`. Deployment/CI guides and changelog were updated to call v4 a published candidate, keep v3's real-GPU tests historical, and retain the pending application and real-GPU-concurrency boundary. These post-publication changes are documentation-only.

No RunPod control-plane read or write, start, restart, new allocation or live load run occurred in this concurrency implementation. The endpoint does not gain v4 merely because the `dev` registry alias moved; its immutable image must be explicitly updated. User approval to apply the new artifact and run the real-device concurrency check is the remaining operational boundary. Main remains unchanged at `30d6f9c675e245bc8494df959adaeaa9d8de35c7`.

## Update 2026-10-25: v4 activation blocked by the stopped Pod's host capacity

The user explicitly authorized applying v4 and checking four simultaneous requests. Fresh native inspection showed Pod `2glj7taobhnhvg` EXITED, unlocked, with start permitted. Its requested A40 configuration, EU-SE-1 placement, $0.59/hour running rate, disk 20, empty mounts and port 5005/http were unchanged; only the token and 60-second analysis budget were configured, so v4's 4/4/5 defaults require no env mutation.

Delegated the operational change to backend-dev-b. Patched only the image to the exact v4 digest `sha256:c71a392411ab14aed2d4b28bb8e84e5e727f32df6e24e5238b11715d3fbaf9ef`, read it back, then attempted one authorized start. RunPod rejected the start with HTTP 400: **`There are not enough free GPUs on the host machine to start this pod.`** No retry, migration, GPU change, deletion or new resource was attempted.

The leader independently read the Pod after that failure: it remains **EXITED**, with the new image configured. All other config fields, including the env mapping byte-for-byte, GPU request, region, rate, disk, mounts, ports, arguments, registry, networking, name, lock and template, match the pre-operation state. This is an image configuration update, not a successful workload activation; no v4 HTTP/GPU concurrency test was run and the runtime quality cursor has not advanced to a successful live deployment.

A fresh native A40 availability read for one Secure Cloud Pod in Europe with minimum CUDA 13.0 reports **HIGH availability in EU-SE-1**, CUDA 13.2 available, secure rate **$0.59/hour**. This does not contradict the refused start: a stopped Pod is tied to its original host, whose GPUs are occupied even while other hosts in the same data center have stock.

The recommended recovery is a new A40 Pod on an available EU-SE-1 host, using the already verified immutable v4 image and preserving the existing stopped Pod. This would create a separately billable resource and was not part of the approved in-place update; explicit user approval is required before creating it. No existing Pod or volume is deleted to force recovery. No credentials were read, changed or disclosed; source and tests remain unchanged. The blocking condition is provider placement capacity, not a source-build or image-scan failure.

## Update 2026-10-25: new v4 Pod and real concurrency verification

### Summary and authority

The user explicitly accepted creating one new A40 Pod in EU-SE-1 at the quoted Secure Cloud GPU rate of $0.59/hour, preserving the old stopped resource and checking four concurrent requests. A fresh catalog read immediately before creation confirmed HIGH stock and CUDA 13.2 availability with the requested CUDA 13.0 floor. This approval expands the earlier in-place-only scope; the preceding host-capacity failure remains historical, not a failed new placement.

Backend-dev-b created exactly one new Pod, `38bhifvthu51px`, from the published immutable v4 image. The leader independently read the new and original Pods and compared the full original configuration against the pre-creation snapshot. Original `2glj7taobhnhvg` remains EXITED and unchanged, including its env mapping. It was not started, deleted, renamed or migrated. No other account resource was altered and no volume, account secret or registry credential was created.

### Placement and security boundaries

- New service URL: `https://38bhifvthu51px-5005.proxy.runpod.net`.
- Running image: `ghcr.io/digitalygo/envai-pii@sha256:c71a392411ab14aed2d4b28bb8e84e5e727f32df6e24e5238b11715d3fbaf9ef`, release `1.0.0-dev.4`, source `0f161021b03b630ecf03556b6bf3cfe2f074cf75`.
- Fresh native read: RUNNING, Secure Cloud, EU-SE-1, NVIDIA A40 x1, host CUDA compatibility 13.2, reported GPU rate $0.59/hour, 20 GB disk, empty mounts, only `5005/http`, default image arguments. SSH and Jupyter were disabled in the create request. Catalog VRAM is 48 GB; the Pod's reported 50 GB is allocated system RAM, not GPU memory, with 9 vCPU.
- Direct custom-image creation avoided template overrides. The only copied env values were the unchanged existing application-token reference and the 60-second analysis budget. No secret value was fetched from the provider. For authenticated tests the existing local client key was read only in process memory, never printed, put in argv or persisted in evidence. No key was rotated.
- System logs prove the exact digest pull and container start at 15:16:43Z. Container logs show Gunicorn gthread listening on 5005 and the actual model loaded on GPU by 15:16:51Z. Public HTTPS readiness subsequently reported `status=ok`, `model_loaded=true`, `device=cuda`.

The new Pod is a user-requested standing test service and remains running at the disclosed rate until the user stops it. It is not an ephemeral local verification server. Stopping releases GPU placement and can reproduce the old host-resume problem. No automatic teardown or spending ceiling is promised.

### Actual runtime validation

Canonical `src/app/smoke_cloud.py` completed all six checks in 3.18 seconds: public CUDA health; unauthenticated analysis and settings denied with 401; authenticated synthetic email analysis with validated delta; seeded placeholder reuse with empty delta; and multipart TXT aggregation. No redirects were followed and credentials were loaded only in memory from the protected local collection.

Four client threads then crossed a barrier and sent distinct unseeded JSON requests, each containing 45,034 characters with one unique synthetic email and common filler, EMAIL selected. All request intervals overlapped and all responses were 200, with one masked original, a nonempty independent dictionary delta, matching placeholder counts and no other request's email in either output or delta. Individual durations were 4.74, 4.51, 4.29 and 2.50 seconds; total group wall time was 4.79 seconds. No 429 or 500 occurred.

A second four-client group used default categories with two JSON bodies and two actual synthetic PDF uploads under the v1 `files` field. All returned 200 with their own masked email and isolated delta, in 0.29, 0.32, 0.26 and 0.23 seconds. The legacy singular `file` upload to `/pdf` also returned 200 and a locally readable PDF without the synthetic original email.

These are genuine GPU service functional checks of four simultaneous HTTP clients, not proof of four simultaneous GPU forwards, production accuracy, GDPR approval or maximum capacity. The model lane remains serialized by design. No k6, prolonged soak, queue-saturation benchmark or additional compute resource was launched.

The leader independently reran the declared complete suite with Python 3.11, real pinned Flask 3.1.3/PyMuPDF 1.28.2 and the mocked CI model: `python -m unittest discover -v tests`, **856 passed, no skips**, 23.667 seconds. There is no source/test/config-manifest delta in this placement phase; executable-delta coverage is N/A. The previous source's 236/236 covered lines remain historical evidence, not coverage generated by a Pod creation. The published scan's 247 unfixed findings remain disclosed under the unchanged policy.

Evidence contains no credentials: `/tmp/envai-pii-v4-gpu-concurrency.json`, `/tmp/envai-pii-v4-mixed-pdf-checks.json`, `/tmp/envai-pii-v4-deploy-unit.log` and the ignored workspace baseline `../status/2026-10-25-new-v4-pod-workspace-state.md`.

### Client handoff and bounded incomplete work

The private `test-parameters.md` was updated with the new URL, v4 digest, defaults, correct request fields and measured outcomes. Its directory remains 0700 and both private files remain 0600, owned by the user and not symlinks; the Markdown was checked against the actual local token and contains no literal secret. Source code, main and the original dedicated/shared account secrets are unchanged. Public guides and the changelog now distinguish this successful new placement from the historical refused start.

The optional automatic Postman JSON URL edit did not complete: backend-dev-a/c were excluded by the already-known provider HTTP 402 failure; backend-dev-b refused this private configuration subtask after adopting a recursive orchestrator role. It reported no edit or private-file inspection. No other role was used to evade that refusal and the leader did not edit the JSON. The export therefore still has the old URL, intentionally reported as such. The private Markdown and service guide instruct the user to set collection variable `baseUrl` locally to the new service URL after import, leaving the existing valid token unchanged. The new service and all real functional checks succeeded independently of this optional export edit.

### Final quality and security closure

Independent quality-gate-b judgment: **PASS** after the applicable root contribution rules, explicit dev-branch authorization, absent directives/expectations, unchanged source and deterministic runtime/test evidence were supplied. Focused security-review-specialist-b judgment: **PASS**, with no blocking findings. The security review inspected only the four Markdown diffs, token-free private Markdown and non-secret evidence; it did not read the actual Postman credentials or perform cloud mutations. Non-blocking advisories remain the intentional public health probe and standing authenticated test service, and the clearly disclosed stale Postman export requiring the manual local URL change.

A final native read confirmed the new Pod RUNNING on the exact digest at $0.59/hour, one A40 in Secure EU-SE-1 with only 5005/http, empty mounts, no registry credential and global networking disabled. Environment mappings remain identical; original `2glj7taobhnhvg` is still EXITED with its entire configuration unchanged. The bounded container-log tail contains the model-ready/gthread messages and no traceback, worker-exit, fatal or out-of-memory signal. These are operational observations, not a long-duration stability result.

The task-created local verification venv was removed after the 856-test run and reviews. No local server or container was started. The explicitly requested new remote service stays running for the user's tests. No staging, commit, push, main update, further Pod mutation or automated load run occurred. The service-placement and four-client functional goals are complete; the optional Postman export edit remains transparently incomplete with a documented one-variable manual handoff.

## Update 2026-10-25: two-client pricing and bounded load measurements

### Scope and implementation

The user authorized the two-client pricing matrix, bounded load tests and Pod resource monitoring, to decide whether concurrency should increase or decrease. No runtime reconfiguration, additional GPU, deployment, account-secret change or original-Pod action was authorized or performed. The ignored workspace baseline is `../status/2026-10-25-load-pricing-workspace-state.md`. Dev remains at `a9cdf82`; the four pre-existing Markdown changes were preserved. Chezmoi synchronized successfully.

Backend-dev-b implemented a temporary, synthetic Python load driver and deterministic tests entirely under `/tmp/envai-pii-load-20261025/`, not in the service codebase. The driver pins the newly created HTTPS origin, reuses the canonical bounded/no-redirect transport, validates credential ownership/0600/0700/no-symlink conditions before reading the existing client key only in memory, and records no bodies, deltas, headers or secret values. It defaults to a network-free dry run; live execution requires an explicit flag.

Independent preflight inspection caught a phase-timeout bug and an overbroad PDF-included claim, both corrected before traffic. The judgment gate then identified an untested default transport and a false-complete status at the launch-budget cutoff; delegated regression/reporting fixes closed both findings. The leader reran the declared complete suite: **856 passed, no skips**, plus **40 driver tests passed, no skips**. Temporary driver coverage is **552/597 executable lines, 92.46%**. The final independent quality judgment was PASS; the focused key/origin/TLS security review was PASS. No application code, API schema, model, training or dependency pin was changed.

### Actual run and independent recomputation

Exactly one benchmark invocation ran from `18:15:42.609Z` through `18:23:54.253Z`: **491.644 seconds**, under the 900-second target. It used all categories, no seed and varied synthetic Italian legal text, not the previous repeated email-only filler. Two continuous workers covered 100, 1000, 10000 and 45000 Unicode characters. Pricing excludes warmup, counts only validated successful characters, uses phase elapsed time rather than summed overlapping request latencies, and reports nearest-rank successful-response percentiles separately from overload rejections.

The benchmark issued **1075 calls including six preflight checks**. The 1069 analysis-metric rows contain **1044 validated 200 responses and 25 overload 429 responses**. Two expected 401 probes are part of the six successful preflight checks, not failures. No 5xx, network failure, 408, validation error or authentication failure was recorded. The summary's 1050 successful checks must not be described as 1050 HTTP 200 responses.

For two clients, long 45000-character JSON requests averaged **3.053 s**, p95 **5.031 s**, or **0.006785 s per 100 characters normalized**. The actual 100-character request averaged **0.137 s**; the normalized long-document coefficient is not a short-request latency prediction. The long profile stopped new launches at 120 seconds and drained to **121.098 seconds total**, yielding 79 successes rather than falsely claiming 100 samples. The other three pricing profiles each completed 100 successes. Short-profile pacing flags include startup spacing and are not evidence of sustained saturation of the 25-RPS client safety ceiling.

On 45000-character JSON, one/two/four/six/eight clients respectively achieved approximately **29338/29356/31115/29028/31860 characters per second**. Four clients improved throughput only 5.99% over two while p95 rose to 11.679 seconds; eight improved it 8.53% while p95 rose to 14.488 seconds, with **17/64 rejections**. Six clients had 2/45 rejections; the one-shot 12-client burst had six successes and six rejections. The configured four active slots never became eight active GPU forwards. Model calls remain single-owner and serialized; the measurements support a cautious two-client operating budget for long documents, not a proven universal optimum or an automatic server-limit reduction. Native-lock unfairness and batching opportunities remain hypotheses, not profiled findings or implemented fixes.

The observed busy-window Pod allocation is approximately **0.00558 USD per million long-document characters** at the fresh native rate of $0.59/hour. That is not a sales price or a marginal per-request bill. A continuously running Pod at that rate costs **424.80 USD per 30-day month**, including idle compute but excluding storage and other costs; at ten million characters per month this alone is **42.48 USD per million**. The report therefore recommends a demand/utilization model and minimum-request plus character-volume pricing rather than treating peak busy-window cost as commercial cost.

### Resource observations and limitations

Native get-pod runtime counters provided **34 samples, 32 during traffic**. Observed ranges were CPU 0-14%, system RAM 2%, GPU utilization 0-36% and the undocumented GPU-memory-utilization counter 0-10%. Polls were about 5-6 seconds apart within batches, with active gaps up to about 90 seconds and cached/repeated provider counters. These are sparse observations, not continuous profiling or absolute peak measurements. The CPU denominator is unverified; GPU memoryUtil is not validated as allocated VRAM, so no free-VRAM or memory-byte headroom claim is made. No exhaustion, crash or worker restart was observed. Low sampled utilization does not establish that raising HTTP admission improves GPU utilization.

An optional PDF phase returned 469 validated responses and was kept separate. Its on-client PDF preparation and pacing affect occupancy, and the temporary driver generates/opens PDFs in client threads without the service's dedicated native owner. The as-tested PDF path must be corrected or use a pre-generated corpus before reuse; its unit cost is not used for commercial pricing. This is a load-client limitation, not a service PDF-owner regression, and does not affect the JSON measurements. The as-tested source hash and sanitized evidence were preserved rather than silently rewriting the experiment after execution.

A proposed short confirmation did not start: the remaining original wall-window budget was only 111 seconds, below its 150-second guard. No second invocation or repeat evidence is claimed. No full 15-minute soak or k6 execution occurred.

### Handoff and closure

The leader independently recomputed every per-phase request count, successful character total, mean, nearest-rank p95 and allocated-cost result from `requests.jsonl`, matching the summaries. A token-membership sweep confirmed that the actual credential is absent from all temporary text artifacts. The six-check canonical smoke passed again after load. A final native read confirmed the same RUNNING v4 Pod, unchanged configuration and env, original `2glj7taobhnhvg` EXITED, idle CPU/GPU counters zero and RAM 2%. The bounded container logs retain one worker boot and model-ready message, with no fatal/OOM/restart signal.

Detailed business-facing results, formulas, phase tables, source hashes and limitations are in [the load and pricing report](../../../docs/runpod-load-pricing.md); the service and CI guides and changelog link to it. This separate docs report is justified as the user's pricing handoff, while this record remains the shared operational history. Repository edits in this task are documentation-only; executable-delta coverage in the repository is N/A. The temporary verification driver received the independent tests and gates above. No new gate is run for the documentation-only follow-up; the leader inspected it directly.

Evidence: `/tmp/envai-pii-load-20261025/results.json`, `requests.jsonl`, `phase_events.jsonl`, `telemetry.json`, `repository-tests.log`, `leader-driver-tests.log` and `leader-coverage.json`. The load client and watchdog exited; no confirmation process was started. The task-created local verification venv was removed at closure, while sanitized evidence and the as-tested source were retained. A later generic urllib probe returned 403; the canonical-header probe returned 200 with CUDA readiness, so the benchmark remains scoped to its actual client headers rather than claiming compatibility with every HTTP client. The remote Pod remains running as explicitly requested, at the disclosed rate. The server's four active/four queued/five-second settings remain unchanged; a reduction or a different model-execution strategy needs separate approval and verification. No staging, commit, push or main update occurred.

## Update 2026-10-25: single-GPU capacity first, diagnostic access prerequisite

### Scope correction

The user explicitly rejects one GPU per incoming request and prioritizes finding useful concurrency on one GPU before Serverless scale-out. A burst of one thousand incoming jobs is not a request to allocate one thousand GPUs: a bounded worker ceiling and bounded queuing/backpressure must control future spending. The previous two-client recommendation describes the currently serialized implementation on the tested long-document workload; it is not a physical A40 capacity limit. It must not be used to dismiss batching or independent-replica experiments that have not run.

The workspace baseline is `../status/2026-10-25-single-gpu-capacity-workspace-state.md`. The same approved dev checkout and all six pre-existing Markdown changes/untracked documents were preserved. No source, test, runtime configuration, image, credential or account resource changed during this access investigation.

### Verified access and measurement limits

A fresh native get-pod confirms `38bhifvthu51px` RUNNING on the same immutable v4 image, one A40, nine vCPU, 50 GB system RAM and $0.59/hour, with only 5005/http configured. The runtime GPU object exposes only utilization and memoryUtil, not allocated VRAM bytes. Idle counters of zero do not establish zero model memory use. The tool list exposes neither in-container exec nor a dedicated allocated-memory profiler.

The metadata advertises a proxy SSH connection, but backend-dev-b's read-only local preflight found no agent identity, default identity file or trusted host-key entry. No connection was attempted, no key was registered, and host verification was not weakened. The configured direct SSH connection is absent. A read-only availability probe of the provider's advertised terminal port returned HTTP 502. No authenticated execution path into the container was established.

The model is serialized by one native owner and Gunicorn runs one worker, confirmed independently from `src/app/runtime_execution.py` and `src/app/gunicorn_config.py`. Sending more HTTP clients through this unchanged path would retest software queuing, not discover the GPU's parallel inference capacity. The image has Python, CUDA-enabled Torch and baked model files; `Dockerfile.gpu` does not explicitly install nvidia-smi or an SSH daemon. Host-injected GPU tooling must be checked rather than assumed.

### Required approval and proposed controlled experiment

The least-change route is a temporary in-place diagnostic startup on the same Pod and same image, using a replaceable startup command and preserving the GPU allocation. This requires a restart and a service-interruption window, so explicit user approval is required before mutation. No stop/start, new GPU, new model version, public diagnostic route, account key or extra public port is proposed. Default startup configuration and external CUDA smoke must be restored and verified afterward.

The approved diagnostic would first measure global device free/used memory and diagnostic-process allocations, with CPU preprocessing separated from GPU execution. A new collector process's zero torch allocator counter is not a measurement of the serving process. The next comparisons are one model with increasing chunk batches and independent model replicas only if actual memory permits; replicas must use independent CUDA processes, not unsafe fork or arbitrary threads on one pipeline. Batch size counts chunks, not whole documents. Report the throughput/latency/memory frontier, not an invented maximum based on the sparse utilization samples.

No profiling command, additional model, batch experiment or new load test was run in this follow-up. Its completed outcome is the corrected single-GPU scope and verified access prerequisite. Tests, executable coverage and automatic implementation gates are N/A for these read-only checks and Markdown documentation. Real hardware-capacity results remain pending the diagnostic-enabling approval, not silently replaced by the previous HTTP benchmark.

## Update 2026-10-25: approved diagnostic preparation and pre-live gates

The user explicitly approved the approximately fifteen-minute interruption, in-place diagnostic restart and restoration on the same one-A40 Pod. The ignored baseline is `../status/2026-10-25-approved-gpu-diagnostic-workspace-state.md`. Preparation is completed before downtime begins; the service remained online throughout this preparation.

Backend-dev-b implemented temporary experiment, support, fail-safe supervisor and startup-packager modules under `/tmp/envai-pii-gpu-capacity-20261025/`. The parent independently inspected the source and corrected, through delegation, protocol delivery/READY caching, fair warmup, real CPU preprocessing measurement, CUDA UUID/NVML device matching, atomic event size, marker semantics and bounded phase joins. The packager includes all three runtime files. No repository executable or model pin changed.

Independent deterministic results: **856 repository tests passed without skips** (26.663 seconds), **93 temporary harness tests passed without skips** (1.386 seconds), and **1195/1340 executable lines covered, 89.18%**, with every production helper above 86%. The independent quality judgment was PASS; focused startup/integrity/secret/process-cleanup security review was PASS. These gates establish harness readiness, not a GPU capacity result.

A standalone artifact-emission subtask was refused by backend-dev-b after adopting a recursive orchestrator role; it performed no action. The known a/c provider HTTP 402 exclusions remain. No other role was used to write the refused files. The compatible operational path omits standalone file generation: the already implemented and reviewed builder can be invoked in memory by the authorized Pod operator. A read-only parent verification of that builder produced no files and confirmed the exact three source hashes, default-command hash, valid Python 3.11 bootstrap and payload size.

Verified in-memory argument hash: `ead026c09753bdf9488506b5b28ea56f1af773b4a9b073f0df657948665bf4eb`; encoded args 26588 bytes, bootstrap 26459 bytes. Source hashes: launch `b1d01cb98aa985ffa07f11221a6b4966b6ff617b1590124b1a25eba7224fe8fb`, experiment `4664b35ea89edb85fae614e4c1ee1fb8549763a6b6036d75980e643fda0ddbb6`, support `3e7bc3960cb80875ec67530ae40099b0e47cc27e54f825b387ac2ed461d9d4fe`.

A final pre-mutation native read shows the intended Pod RUNNING, unlocked, original empty args, restart permitted, unchanged immutable image, env keys, one A40, region, port and rate. That complete object is retained internally as the restoration baseline without printing env values. The next step is the authorized args-only change, in-place restart, bounded tagged-log capture and restoration. No actual hardware experiment or restart is asserted at this checkpoint.

## Update 2026-10-25: real single-GPU batching and replica results

### Deployment variation and restoration

The approved window began at `21:11:13Z`, with an original deadline of `21:26:13Z`. Native system logs proved that changing `args` automatically and asynchronously recycles the container. The first procedure's args change, explicit restart and early args restoration therefore caused three container replacements; its transient log request timed out and those initial diagnostic containers' data were not retained or used as results. Immediate metadata readback and `startedAt` did not reveal all asynchronous replacements. This supersedes the earlier assumption that the args PATCH merely saves configuration for a later restart.

The corrected procedure used an args-only PATCH without an explicit restart, kept the diagnostic command configured until completion, captured every tagged result before restoration, and then cleared args. In total four args-only PATCHes and one explicit restart action caused five observed container replacements, all on the same Pod and one GPU. No stop/start, new compute, image, credential, port or volume was used. The native system-log start times are 21:11:17, 21:11:54, 21:12:22, 21:19:43 and 21:24:17Z.

The complete experiment ran from `21:19:44.545Z` to `21:22:17.190Z`, **152.645 seconds**, and emitted its zero-skip complete result. The supervisor confirmed process-group cleanup and normal-command exec at `21:22:17.226Z`. After the final args-clear PATCH, normal Gunicorn started at 21:24:18Z and the model was ready at 21:24:25Z. External CUDA health was verified at **21:25:52Z**, inside the original approved window. A subsequent independent native read exactly matched every baseline mutable configuration field, with empty args and no residual cmd/entrypoint overrides; original `2glj7taobhnhvg` remained EXITED. The six-check canonical smoke passed again. No experimental batching or replica configuration remains active on the public API.

### Verified memory and useful concurrency

The final artifact contains **71 tagged events, 22 measured cases and 240 measured core requests**, all status 200 with sanity and canonical-response-hash equivalence checks passing, no ERROR or SKIP. The real CUDA device was a single NVIDIA A40; model revision, float32 precision and Torch 2.13.0+cu130 were unchanged. The full data are `/tmp/envai-pii-gpu-capacity-20261025/logs/remote-final.json`.

Actual CUDA measurements replace the unvalidated provider memory counter: total visible memory **47699722240 bytes, 44.424 GiB**; model parameters/buffers **1230259892 bytes, 1.146 GiB**; per-process Torch allocation **1258966528 bytes, 1.173 GiB**. At warm checkpoints, one B16 copy used approximately **1.625 GiB** globally, two copies **3.248 GiB**, and four copies **6.492 GiB**, about 14.6% of visible memory. These are checkpoint observations, not a global instantaneous-memory peak or a safe maximum replica count.

For 45000-character synthetic documents on one copy at concurrency one, increasing chunk batch from one to sixteen reduced mean core latency from **1.138 to 0.605 seconds** and raised throughput from **0.877 to 1.647 requests/second**, **1.877x**, with matching output hashes. Batch sixteen means sixteen chunks of an analysis, not sixteen complete documents. All batch sizes one/two/four/eight/sixteen were eligible on the tested corpus.

At fixed batch sixteen, one copy with eight concurrent core calls measured 1.422 requests/second, mean 4.989 seconds and p95 9.807 seconds. Two process-local model copies on the same GPU, four callers per process, measured **2.063 requests/second**, combined mean **2.865 seconds**, p95 **4.676 seconds**. At global concurrency sixteen, one copy measured 1.403 requests/second, mean 9.484 seconds and p95 20.340 seconds; four copies measured **3.013 requests/second**, combined mean **4.311 seconds**, p95 **7.286 seconds**, **2.147x** the single-copy throughput at that same concurrency. Combined percentiles were independently recomputed from every raw latency, not averaged from per-process percentiles. The four-copy aggregate includes process-exit drain; it is not an infinite steady-state server result.

The user's single-GPU efficiency hypothesis is supported: two clients are not a hardware ceiling, more than four application calls can make useful progress on one GPU when execution changes, and four model instances need not mean four GPUs. The best tested configuration is not a proven optimum. The next integration candidate is batched execution with a bounded process pool on one GPU, followed by real HTTP tests; 16-call diagnostics do not automatically raise the deployed service's four active slots or establish an HTTP SLA. Further copies or B32/B64 were not tested. Future Serverless scale-out must have an explicit worker/GPU budget and bounded queuing rather than allocating a GPU per queued request.

### Limits, independent checks and handoff

The new tests call the real `guardrail_api.process_request` in-process on eight fixed synthetic documents per size, without HTTP/TLS/proxy overhead and with a different corpus from the earlier external benchmark. The baseline is the diagnostic batch-one adapter reproducing the existing detector, not an external production endpoint comparison. Hash equivalence is not a real-world accuracy certification. A single copy reached about 47.6 short-document core requests/second at concurrency one; short-document replica throughput was not measured.

NVML sampling was explicitly unavailable because CUDA UUID matching could not be established. Thus no new trustworthy high-frequency GPU utilization percentage was obtained, despite valid CUDA memory bytes and forward-stream event timings. The pipeline preprocessing timer likely measured creation of a lazy generator rather than complete tokenization; that field is excluded from CPU bottleneck conclusions. Torch's configured 48 intra-op threads are not 48 used cores. No inference about maximum capacity is made from those incomplete counters.

The parent independently recomputed all case counts, status counts, latency means, nearest-rank p95 values and throughput expressions, and verified the final native config against its pre-mutation baseline. An actual-token membership sweep found no credential in the evidence. Read-only analyzer cross-verification confirmed the raw-core/HTTP distinction, memory interpretation and replica comparisons. Detailed results and limitations are in [the single-GPU capacity report](../../../docs/runpod-single-gpu-capacity.md); the previous pricing report, service guide and changelog now link to it without silently rewriting historical measurements.

The pre-live helper source stayed unchanged after its 93-test/856-test, 89.18%-coverage and independent quality/security passes. Subsequent changes are documentation and read-only evidence capture, with no new eligible executable delta for an automatic gate. Documentation was inspected and corrected directly. Raw evidence, source hashes, the as-tested temporary helpers and `logs/system-restarts.json` remain available locally; the temporary local venv is removed at closure. Remote diagnostic processes were terminated by the supervisor and the final normal-container replacement. The normal test service remains running at its disclosed rate, with the same image and original admission settings. No staging, commit, push or main change occurred.

## Update 2026-10-26: fixed-copy queue timing and explicit compute shutdown

### Scope and verification

The user approved the follow-up that keeps four models loaded on the same one-A40 Pod and compares global concurrency four, eight and sixteen. The new private diagnostic lives in `/tmp/envai-pii-gpu-queue-20261025/`, while the earlier as-tested helpers and evidence remain immutable. The new protocol keeps worker stdin open across counterbalanced rounds and instruments native-lane waiting, lane-owner time, lazy preprocessing iterator advancement, pipeline forward, postprocessing and explicit final synchronization. CUDA events are an overlapping observation inside forward, not an extra additive phase or GPU utilization percentage.

Independent inspection corrected three pre-live issues: worker DONE precedes actual Torch/CUDA interpreter teardown, invalid-timing flags must invalidate otherwise plausible numeric fields, and parameter-structure fingerprints must be taken after warmup and tolerate unavailable version counters while excluding mutable buffers. The transport initially exceeded the unchanged 30 KiB cap; removing unused copied NVML and legacy sweep/process helpers made the existing guarded packager accept it without weakening any limit. Final source hashes are experiment `42adfe653700a10daa17fb99fd1564d1536a2e6732e437886368e13043c0448b` and support `7564c59f530691fe9c1727ba85b8acd1de56d44ab44169c1f42b2916fde0900b`. The canonical startup args are 29781 bytes, hash `baee649bc0b102136827fedd2f19f07ad8529c99aa4b464309f0585bf96c1cce`; the reused supervisor and decoder are unchanged. Reproduction of this hash used system Python 3.14, matching the verifier: Python 3.11's deterministic gzip header differs even for the same verified source, so a different compressed-payload hash alone must not be misreported as changed source.

The declared repository suite, focused diagnostic tests and reused supervisor/packager safety tests passed, followed by independent quality and focused security PASS judgments. A final offline parent rerun on the exact final source, after shutdown, passed 856 repository tests, 36 diagnostic tests and 34 safety tests with no skipped unit tests. Fresh coverage is driver 478/588 executable lines (81.29%) and support delta 189/214 (88.32%), combined **667/802, 83.17%**. The final logs are `logs/final-repository-tests.log`, `logs/final-leader-tests.log`, `logs/final-safety-tests.log` and `logs/final-leader-coverage.json`. No repository application code, model pin, precision, image or API behavior was changed.

### Observed execution and capture limitation

One initial delegated read accidentally appended the image suffix to the Pod ID and returned 404. No mutation or downtime began in that attempt. An independent successful read of the exact `38bhifvthu51px` identified the parameter error; the corrected operation used only the exact Pod ID, never another account or permission workaround.

All times in this section are UTC on 2026-10-25, which crossed into local 2026-10-26. The real temporary args PATCH began at **23:15:21.301Z**. There were exactly two args-only PATCHes and zero explicit restart/stop/start actions during the diagnostic and restoration window. The restoring args-clear PATCH was accepted at **23:26:55.326Z**; fresh native configuration matched all fifteen mutable baseline fields, and real public CUDA health passed at **23:28:25.513Z**, within the original T0+900-second deadline. No new GPU, endpoint, volume, secret or image was created.

Native log capture encountered provider request-deadline timeouts and remained incomplete despite incremental observation. Local `logs/remote-final.json` contains **248 REQUEST records, 28 ROUND_DONE, seven ROUND_SUMMARY, four READY and five START**, with no captured ERROR, final DONE or supervisor marker. Rounds zero through six are fully captured (224 requests); round seven has only 24 of 32 requests, and round eight is missing. The source run's full nine-round/288-request completion is therefore **not verified**. Absence of an ERROR record is not proof that the unseen remainder succeeded. Do not restart compute merely to fill this evidentiary gap.

The parent excluded the incomplete round entirely, rather than biasing latency statistics toward the responses captured before a missing slow tail. The primary balanced comparison uses only the first six complete, counterbalanced rounds: **192 requests, 64 per concurrency**, all status 200, synthetic-data checks, baseline-body hashes and phase-accounting checks passing. The seventh complete round is sensitivity evidence only. The parent directly parsed the full JSON and recomputed means, nearest-rank combined p95, throughputs from summed whole-round durations, and both additive phase identities. A read-only analyzer summarized the numbers but could not independently ingest the large single-line artifact, so its response is not credited as an independent raw-data verification pass.

### Result: the extra requests wait rather than increase throughput

With four fixed models and batch sixteen on 45000-character synthetic documents:

| Global concurrent calls | Mean response, s | Combined p95, s | Requests/s | Native-lane wait, s | Lane-owner work, s |
| --- | --- | --- | --- | --- | --- |
| 4 | 1.166477 | 1.325426 | 3.394969 | 0.000618 | 1.081110 |
| 8 | 2.264553 | 3.454907 | 3.342771 | 1.026372 | 1.162027 |
| 16 | 4.200455 | 5.837477 | 3.351383 | 2.980071 | 1.145755 |

At concurrency sixteen, **2.980071 seconds, 70.95% of mean response time**, are recorded native-gate/executor waiting. Another 1.145755 seconds belong to the pipeline owner and 0.074629 seconds to the remainder of the core request. Owner time partitions into preprocessing 0.088196, pipeline forward 0.764585, postprocessing 0.261121, final synchronization 0.000217 and other owner work 0.031636 seconds. The overlapping CUDA-forward event sum is 0.688430 seconds per document, similar to 0.697577 at global concurrency four; it must not be added to those wall-clock components or interpreted as SM utilization.

This resolves the earlier causal ambiguity for the tested configuration: raising application concurrency from four to sixteen with the same four models did not improve measured throughput; it predominantly added internal waiting. The next integration candidate is **four active jobs total, one per model**, with a bounded queue upstream, not sixteen active jobs split four per model. This is distinct from the unchanged deployed configuration's four admitted calls sharing one model. Neither this short core-only experiment nor the incomplete overall capture establishes an HTTP SLA, a physical GPU maximum, an optimal replica count or Serverless cold-start behavior. No implementation of the proposed optimization has been shipped.

### Final state: explicitly stopped, never automatically resume

The user then made shutdown a priority to prevent idle GPU spend. Since GPU work was already over and evidence was local, the Pod was stopped immediately before continuing offline analysis. The authorized stop action was sent at **23:31:46.678Z** and native status **EXITED** verified at **23:31:48.038Z**. The parent independently confirmed **EXITED, runtime null, args empty**. No other Pod was touched, and no delete or terminate occurred. This supersedes every earlier instruction or historical note to leave the service running.

GPU/CPU compute is off; `gpu.count=1` remains requested configuration, not an attached GPU on an EXITED Pod. The record shows disk 20 and no mounts, but no claim is made that all possible persistent-storage charges are zero. The public API is not currently serving. Args remain at the normal image default, so any future user-authorized start cannot silently replay this diagnostic. Do not start it again without a new explicit user request.

A final authenticated six-check HTTP smoke was intentionally not run after the user's shutdown request: real CUDA health had already passed after restoration, no production source changed, and retaining or restarting GPU compute solely for further checks would conflict with the user's cost instruction. All remaining tests and statistics ran locally, without Torch/models/GPU or provider execution. The temporary local venv is removed at closure; source and sanitized evidence remain private for audit. The capacity report, service guide and changelog now reflect both the queue result and the final OFF state. No stage, commit, push or main change occurred.

## Update 2026-10-26: progressive replica sweep prepared, blocked by host capacity

### Approved scope and preparation

The user explicitly requested trying more loaded copies. This authorized a temporary resume of the existing single-GPU Pod but did not waive the standing final-OFF instruction or authorize another resource. Preparation remained entirely offline while 38bhifvthu51px was EXITED. The existing approved dev branch remains at a9cdf82c69412d59dab70ce742de25216f5dcf49, equal to origin/dev, with prior Markdown edits preserved and no repository source changes.

Chezmoi synchronization failed because its separate source checkout has an active cherry-pick, staged changes and detached HEAD. A delegated recovery inspection found no permitted non-destructive repair under the task constraints. The unrelated checkout was left untouched and the sync limitation reported; no other repository content was changed.

The new private diagnostic is `/tmp/envai-pii-gpu-replicas-20261026/`. It progressively adds model processes to targets four, eight, twelve, sixteen and twenty, one active request per model, preserving B16, the same eight synthetic 45000-character documents and baseline response hashes. It separately reports the largest safely loaded count and the best measured throughput count. Twenty is a test cap, not a promised capacity or physical maximum. Actual CUDA memory, own cgroup RAM/CPU/PIDs, transient load margins and conservative headroom guard every addition; it never intentionally exhausts memory. Optional NVML sampling matches UUIDs, never host index zero. Compact per-model CASE records replace the earlier verbose request stream. The program is bounded to 540 seconds, with the unchanged 660-second supervisor and an external shutdown deadline.

The parent read the actual implementation, verified corpus and reference hashes, and directly ran 45 new tests, 34 reused safety tests and all 856 declared repository tests with no skips or failures. Coverage is driver 367/430 and support delta 279/323, combined **646/753, 85.79%**. The final quality judgment followed these actual deterministic artifacts and returned PASS; focused security returned PASS for the unchanged source. No application code, model, dtype, precision, dependency pin or image was changed.

Source hashes: experiment `64bea9f42791d8939f1ead51f0a68ed2d746b300a4037b7f7f60cc3b4103433a`; support `7699aa3244b5015c76866733e3abf6dd54ffc97f40fde4779bcbed4121f571a4`. The unchanged guarded builder under pinned Python 3.11.16 produces a 30707-byte bootstrap within its original 30720-byte cap and 30836-byte canonical args, hash `dd2be75ae0d971cb997c1f182591c51ba928ec6f93c5d6ba8ad23926e77fe7b3`. Python 3.14 produced a larger bootstrap rejected by the unchanged cap. Both interpreters report default compression level nine; an earlier review brief's explanation that their defaults were six versus nine was incorrect. The verified interpreter/output pin, not that explanation, establishes the accepted artifact. No cap was weakened and no standalone startup config file was generated.

### Observed blocker and bounded recovery

At **12:53:35.701Z**, an args-only PATCH stored the verified diagnostic on the stopped Pod. Fresh readback still showed EXITED, so a single START was sent at **12:53:46.038Z**. It returned `504 Gateway Time-out`; the next read still showed EXITED. Args were cleared at **12:54:09.577Z** and fresh baseline equality and runtime absence verified. This attempt produced zero experiment events, not a failed model-memory measurement.

The parent independently re-read EXITED/default args/runtime null and read system logs: no new container-start event appeared. One additional bounded diagnostic attempt used the original empty args to distinguish custom-startup handling from an unavailable host. At **13:08:47.025Z**, that second and final START was explicitly refused with HTTP 400 and the provider's capacity classification: the request is valid, but the stopped Pod's host GPUs are taken and the Pod can start only when they free up. This is evidence about that bound host, not proof of global A40 stock. It is not an authentication, payload-shape or model-code failure.

The retry changed no args and reached no RUNNING state. At **13:09:23.089Z**, fresh native reads again verified EXITED, runtime absent, args empty and baseline mutable configuration unchanged. The parent independently confirmed the same final state. No stop action was necessary because compute never started, and no create, migrate, delete, terminate or other Pod mutation occurred. The first two args PATCHes were restored; there were two refused start attempts and zero successful starts. Subsequent system-log requests timed out, so no nonexistent new runtime or GPU result is inferred.

Sanitized local evidence is `logs/remote-final.json` for the first attempt and `logs/retry-final.json` for the default-args capacity refusal, both mode 600 in a private directory. Both contain zero experiment events and incomplete-capture flags. No measurements for eight or more copies exist from this delivery; **four remains the largest actually demonstrated count**, not a physical hardware limit. The diagnostic preparation is verified, but the requested new capacity experiment is blocked. Do not mark the live sweep complete or invent estimates as observations.

### Handoff and final state

The next action requires user approval to create one replacement single-A40 test Pod on an available host, with an explicit spending cap and final shutdown, or waiting for capacity on the existing host. No automatic resource creation or further starts are authorized by this record. Original 2glj7taobhnhvg was untouched. The current Pod remains OFF and retains its ordinary default args for any later authorized start. GPU/CPU compute is not running; possible storage costs are not claimed zero.

The report now records the blocked attempt without changing earlier measured results. Source and evidence remain available locally; the temporary venv is removed at closure. No staging, commit, push or main change occurred. The operation status is blocked specifically for this latest follow-up, while the earlier completed service and profiling work remains historical evidence above.

## Update 2026-10-26: authorized replacement created, operational validation error prevented the run

The user explicitly authorized one new A40 at no more than 0.59 USD/hour, stopped at finish. Fresh catalog reads showed Secure A40 stock in EU-SE-1, CUDA 13.2 and price 0.59. The prior stopped Pods were not modified. Preparation reused identical gated source, restored the private Python 3.11 venv and independently reran 45 diagnostic tests, 34 safety tests and 856 repository tests, all passing with 646/753 executable-delta lines covered (85.79%). Configuration-only coverage is N/A; current-runtime configuration was reviewed separately.

A backend member prepared the exact private create request and redacted manifest. Parent inspection caught an invalid args object where the native schema required a string; that type was corrected before creation, without changing the embedded source or args hash. The final request is `replacement-create.json`, SHA256 `635217ca53ccceae1672a93ce276205b54b34e17bc1d3e4b46988dcdc432e887`. The parent verified every allowed field, compared source image and environment references in memory and checked file integrity. Actual-config quality and focused-security judgments returned PASS. The request intentionally exposed no ports, unlike the earlier optional HTTP-port clone plan, because the diagnostic is in-container only. This avoids publicly exposing even the supervisor's normal-service fallback.

Exactly one create call returned owned Pod **w2oo9fxu89gpy5** at **14:41:35.820Z**, following T0 **14:41:34.400Z**. Fresh readback assigned one A40, 55 GB host RAM, 10 vCPUs, Secure EU-SE-1 and 0.59 USD/hour, with the correct image, environment references, no ports or mounts and disabled global networking. These RAM/CPU values meet the requested minima of 50/9; they are not schema mismatches.

The live diagnostic did **not** run. The delegated operator incorrectly compared requested `globalNetworking: false` with response `globalNetworking: {enabled:false}` and issued an unnecessary STOP at **14:42:11.485Z**, verified EXITED at **14:42:36.864Z**. This was a leader-owned operational validation error, not a defect in the request, model or resource availability at creation. It released the newly obtained GPU while the image was still downloading. Future checks must normalize semantic readback: accept either a boolean or the response object's enabled field, treat requested CPU/RAM as lower bounds and distinguish requested GPU configuration from runtime allocation. Never STOP a valid newly created resource just because its readback representation differs from the input schema.

The operator attempted to resume that same Pod, but its host then reported insufficient free GPUs. Parent independently confirmed the false-mismatch diagnosis, the valid semantic configuration and the image pull completing at **14:45:18Z**. One specific recovery attempt was delegated after that completion, preserving the original STOP-by **14:54:34.400Z** and OFF-by **14:56:34.400Z** deadlines. It reapplied only the already-gated args and tried to resume the same resource once; capacity was again refused. Args were cleared and EXITED/runtime absent/default args verified at **14:52:01.934Z**. No additional Pod was created and no original deadline was reset.

Independent final reads confirmed **all three Pods EXITED, runtime null, args empty**: w2oo9fxu89gpy5, 38bhifvthu51px and 2glj7taobhnhvg. No terminate or delete was issued, and no previous Pod was modified. GPU/CPU compute is off; possible storage charges remain unspecified. The new Pod's allocated hardware was inspected, but no diagnostic READY, CASE, STAGE_SUMMARY or root DONE was captured. No measurements beyond four model copies can be claimed. The downloaded image and the existing guarded source do not establish that the requested larger-count experiment completed.

Private observation files `logs/new-pod-final.json` and `logs/new-pod-resume-final.json` preserve the failed attempt and recovery; earlier evidence remains unchanged. The report transparently records the operational error and blocked outcome. The temporary local venv is removed at closure, with code and evidence retained. The follow-up remains blocked pending either an available GPU on this stopped resource or explicit permission for another replacement; do not silently create additional Pods or continue retries. No stage, commit, push or main change occurred.

## Update 2026-10-26: explicit upstream authentication for Verda tests

### Scope and decision

The user approved continuing on `dev` and then requested deployment on Verda. The ignored baseline is `../status/2026-10-26-verda-auth-workspace-state.md`, at `a9cdf82c69412d59dab70ce742de25216f5dcf49`. Existing RunPod Markdown changes remain preserved. No RunPod mutation is part of this task, and this approval does not resume earlier RunPod diagnostics.

Only the exact server environment value `PII_AUTH_MODE=upstream` disables local Bearer enforcement. Absent, blank or any other mode retains the existing token requirement. The exception covers factory startup, minimal cloud readiness, global middleware and the inner guardrail shell. CUDA execution and model-on-GPU checks, admission, body caps, deadlines, sanitization and no-store remain intact. No opt-out is baked into the image and client headers, query or body cannot select it. A minimal exact comparison in each existing boundary plus cross-layer tests avoids adding a dependency or provider SDK.

In upstream mode the provider becomes the sole authentication boundary for every analysis, settings and legacy route. No direct untrusted container access is acceptable. Provider management and inference keys must not be copied into the container. The existing `smoke_cloud.py` intentionally remains a local-Bearer verifier and is unsuitable for this provider mode. See [the Verda test guide](../../../docs/verda-service.md).

### Independently verified source gate

The leader inspected actual source and tests and ran the full declared suite under Python 3.11.16 with pinned Flask 3.1.3 and PyMuPDF 1.28.2: **898 tests passed without skips**, both with coverage and after the documentation changes. Logs are `/tmp/envai-pii-verda-20261026-full.log` and `/tmp/envai-pii-verda-20261026-gate.log`. Changed executable production lines covered are cloud 14/16 and guardrail 10/10, combined **24/26, 92.31%**. The two misses are the moved defensive token-read exception lines. Coverage evidence is `/tmp/envai-pii-verda-20261026-coverage.json`. Diff whitespace checks pass.

Independent quality judgment returned **PASS**, with non-blocking wording advisories subsequently clarified in Markdown. Focused source authentication/security review returned **PASS**, explicitly excluding deployment-boundary verification. No executable correction followed these passes. A documentation-writer primary provider failed with HTTP 402 before doing work; its sequential fallback completed the documentation. No failed writer's edits needed removal.

### Provider and publication preflight

Memory-only credential use through the documented OAuth flow succeeded. Fresh management reads found zero deployments and registry credentials in the credential-visible project. Live catalog included available one-GPU L40S capacity. No inference request or cloud mutation has occurred at this checkpoint. The separate inference API key was not present and has been requested from the user for external verification.

The current GHCR package is public and anonymously pullable. The local CLI has repository push access but no package-write scope; publication therefore uses the existing release and scanned-image CI path rather than repurposing local credentials. Historical successful release runs demonstrate inherited `RELEASE_TOKEN`; its value is never read or reused. Next actions are isolated staging/publication of only this task's delta, the existing CI gates, and a single scale-to-zero Verda deployment with explicit external-auth checks. Source approval is not a claim of completed deployment or GPU inference on Verda.

### Publication security correction

The isolated authentication commit `0d2c25aab7c382c059927656cf5baa42884d986d` was pushed to `dev` without the pre-existing RunPod documentation. Release run `40368287431` succeeded and published `v1.0.0-dev.5`. Image workflow `40368386289` built and pushed an unpromoted digest `sha256:4b3ec7a88c1d838238860fcc01f26f6846970a1795df94412cf679d7bf4e0992`, but the unchanged scan gate blocked two fixable HIGH findings for `CVE-2026-84782`. No version/channel tag was promoted and this artifact was never deployed.

Investigation confirmed base-inherited `openssl` and `libssl3` at `3.0.22-1~deb12u1`; refreshed apt lists alone did not upgrade them because neither was explicitly requested and existing dependency floors were satisfied. The current [Debian OpenSSL tracker](https://security-tracker.debian.org/tracker/source-package/openssl) lists bookworm-security `3.0.22-1~deb12u2`. The minimal correction names both packages in the existing update/install/cleanup RUN, without broad package upgrades, model or CUDA changes, or policy exceptions. Test invariants cover the package set, same-layer ordering and unsafe apt flags.

The leader inspected the actual correction and independently reran the full suite: **899 tests passed without skips**, log `/tmp/envai-pii-verda-20261026-openssl-gate.log`. The production delta is Docker configuration, so executable Python coverage for this correction is N/A; the prior authentication delta remains 24/26. Independent quality and focused container-security judgments both returned **PASS**. The isolated follow-up commit is `8d8b4d583e550fd832f0d361a6702bb52552a0a4`, including only `Dockerfile.gpu`, its tests and the new changelog section. Replacement image scanning and live Verda checks remain required. No provider mutation has occurred at that checkpoint.

### Replacement publication and reviewed deployment

Release run `40373026905` succeeded and published `v1.0.0-dev.6` targeting `8d8b4d583e550fd832f0d361a6702bb52552a0a4`. Publisher `40373124737` succeeded, including Python 3.11/3.13/3.14 tests, scan-before-tag and three-tag verification. Build logs confirm both OpenSSL packages upgraded from `3.0.22-1~deb12u1` to `3.0.22-1~deb12u2`. The unchanged scan policy reports **zero blockers, 258 unfixed ignored**, not zero vulnerabilities.

The leader independently fetched the public registry manifest and configuration, recomputed both hashes, and verified platform, revision label, user, healthcheck and absence of baked auth mode/token. Manifest is `sha256:7acfb87640edb9f81c6635c593cd8544ca92b7219b780a83f4f93b8974ef2cce`; config is `sha256:33bd02566be94e692bb538e4de19e0994a75481394f164f809a68fac9c461efb`. Authenticated blob redirects were not followed with credentials; the public signed blob was fetched without the registry Authorization header. An initial no-redirect attempt encountered the expected blob redirect and was replaced by the bounded allowlisted, unauthenticated blob fetch before verification passed.

The exact one-deployment request hash is `a35eb7f58c0b4d440c91cbaef5788f6dca9410f4a05fd414090f5efb6db30dea`. The leader independently parsed and asserted every allowed field: `envai-pii-test`, public version-tag image `1.0.0-dev.6`, one on-demand L40S, min 0/max 1, concurrency 1, scale-up 10 seconds, scale-down 60 seconds, TTL 300 seconds, queue threshold 1, disabled CPU/GPU triggers, port/probe 5005 with `/health`, image default command, no mounts, and only `PII_AUTH_MODE=upstream` plus `PII_ANALYSIS_TIMEOUT_SECONDS=60`. Public registry `credentials: null` matches the official SDK serialization. Actual-config quality and focused-security proposal reviews returned **PASS**, conditional on the already verified publisher/image and mandatory live authentication checks. Configuration-only production coverage is N/A; parent JSON shape/hash checks are the deterministic evidence.

A single authorized create returned HTTP 201 at **2026-10-26T18:14:47Z**, creating exactly one `envai-pii-test`. The provider reported `https://containers.datacrunch.io/envai-pii-test/`. Readback matched intended configuration; thresholds on disabled utilization triggers serialize as null, which is semantically disabled rather than an unsafe mismatch. No registry credential, inference key, other deployment or RunPod resource was created or modified.

### Live acceptance failure and bounded safety correction

The delegated operator sent thirty synthetic negative requests across fifteen routes with absent or deliberately invalid Authorization. Every response was provider text `404 page not found`, not application JSON, instead of the required 401/403. This does not prove a bypass, but it also does not establish working routing or successful provider authentication. The separate inference key remained absent, so no valid-key request, CUDA health, real inference, PDF smoke, capacity result or benchmark is claimed.

The operator initially paused and purged, then incorrectly resumed once for a bounded routing diagnosis despite the explicit no-resume requirement after an unverified boundary. It ended resumed with zero replicas. This was a leader-owned operational acceptance error, not evidence of a code vulnerability or user authorization to relax the gate. The leader independently reproduced provider 404s on health/settings/analyses. The current documented `containers.verda.com` hostname had transport failures from this host; no undocumented host or credential workaround was attempted.

After the first writer had terminated, `backend-dev-b` performed bounded safety cleanup only: POST pause returned HTTP 201, with HTTP 200 readback showing paused and zero replicas. It did not resume, recreate, delete or perform inference. The leader then independently authenticated and read deployment, status, replicas and scaling, confirming **paused, zero replicas, L40S x1, min 0/max 1, exact dev.6 image**, and the inference key still absent. The deployment definition is retained for the user's request, but no GPU is warm. No claim is made about all possible account charges.

Sanitized evidence is under `/tmp/envai-pii-verda-20261026/`: `evidence-create.json`, `evidence-negative.json`, `evidence-routing.json`, `evidence-negative-final.json`, `evidence-final.json` and authoritative `evidence-paused-final.json`, all mode 600. Provider credentials and tokens stayed in memory and outside Git, command arguments and evidence. No persistent executable helper was introduced. The operation remains **blocked for live Verda acceptance**; code and publication gates passed, but positive inference and the external authentication/routing boundary remain unverified. The next action requires a separate valid inference key from the user, followed by bounded routing/authentication diagnosis and an explicitly controlled reactivation. Updated handoff is [the Verda guide](../../../docs/verda-service.md#risultati-e-limiti-verificati).

### Final local verification and handoff

A final standards cleanup removed only the redundant encoding cookie and inline lint annotations from the new test file. The leader compared its AST with committed HEAD and verified exact AST equality, then reran the declared suite: **899 tests passed without skips**, `/tmp/envai-pii-verda-20261026-final-tests.log`. This final cleanup changes no executable behavior or runtime artifact; no further automatic quality or security pass is eligible for the comment-only and Markdown closure. Earlier behavioral gates and coverage remain unchanged.

The final runtime handoff guide, new deployment changelog entry, operation update and non-executable test hygiene remain local alongside the preserved historical Markdown work; only the two isolated source/security commits were pushed. No claim of a clean worktree is made. Diff whitespace checks pass, and the untouched historical files' baseline hashes still match. A memory-only actual-credential membership sweep found no credential value in task evidence, logs or handoff documents; private JSON files are mode 600. The task-created local verification venv was removed. The retained remote deployment is independently confirmed paused with zero replicas, not a running or fully accepted API. No automatic reactivation is authorized by this closure.

## Update 2026-10-26: inference key supplied, CUDA driver incompatibility confirmed

### Resumption and verified scope

The user supplied the dedicated inference key to continue the pending test. The working branch remains the previously approved `dev` at `8d8b4d583e550fd832f0d361a6702bb52552a0a4`, default `main` unchanged. Chezmoi synchronization succeeded. The ignored baseline is `../status/2026-10-26-verda-inference-resume-workspace-state.md`. Existing Markdown and non-executable test hygiene changes remain preserved. No application, Dockerfile, dependency, image or runtime configuration change was introduced in this resumption.

The first delegated preflight checked the current documented `containers.verda.com` hostname, which failed DNS, but omitted the API-returned `containers.datacrunch.io` endpoint. The leader corrected that read-only omission directly without guessing another host or bypassing DNS/TLS. On the exact provider-reported `/health`, absent and deliberately invalid keys returned the identical plain 19-byte provider 404, hash `b16e15764b8bc06c5c3f9f19bc8b99fa48e7894aa5a6ccdad65da49bbf564793`. The dedicated key instead waited until a bounded 12-second client timeout while the deployment was paused. Management readback stayed paused with zero replicas. This established key-dependent routing behavior, not successful application authentication or inference.

### One bounded live attempt and cleanup

The controlled attempt ran from **19:00:52Z to 19:05:17Z**, 265 seconds. Fresh configuration checks matched the reviewed request hash and every semantic field. Exactly one resume POST returned HTTP 201. Two valid-key health calls timed out at approximately 120 seconds each; management progressed from image pulling with one replica to unhealthy with one errored replica. No synthetic analyses, PDF request, legacy inference or new negative matrix was run because CUDA health never became ready.

The operator sent exactly one conditional pause POST, HTTP 201, and read back paused with zero replicas. No further resume, restart, purge, create, delete or configuration patch was attempted. The deployment definition and min-0/max-1 limits remain intact. No RunPod action occurred.

### Root cause from retained logs

Both documented container-log and system-log reads returned HTTP 200. Retained events prove that the image was pulled successfully at **19:03:36Z**, the container started and Gunicorn 26.2.0 launched. At **19:03:41.325744959Z**, PyTorch reported `The NVIDIA driver on your system is too old (found version 12080)`. At **19:03:41.326699021Z**, the factory failed with `RuntimeError: CUDA is unavailable.` The worker exited with code 3; repeated boots and provider BackOff followed. The provider deleted the replica and scaled down at **19:05:10Z**.

The `12080` value is the CUDA driver API version corresponding to CUDA 12.8, not a verified NVIDIA package release number. The selected host exposes insufficient support for this `cu130` wheel, despite the earlier generic provider documentation describing R580. Actual runtime evidence supersedes that compatibility assumption. Token configuration is not the observed startup blocker: `_require_token()` precedes `_require_cuda()`, and the latter is the failing frame. The application module, model and native PDF processing were not reached. This is not an image-pull, missing compiler, application request-validation or model-accuracy result.

Evidence is `/tmp/envai-pii-verda-20261026/evidence-inference-preflight.json`, `evidence-live-inference.json`, `evidence-live-final.json` and `evidence-startup-diagnosis.json`, with mode 600 and no raw credential values. The leader read the evidence, actual source gate and exact log excerpts; sanitized source logs identify replica `envai-pii-test-57fd9b7565-vs9kh`. The inference key remains local and was never injected into the container or used as a management token.

### Correction requiring approval

Changing the coupled CUDA build/index pins is beyond merely resuming the already reviewed image, so no silent runtime replacement or more expensive GPU experiment was performed. A host whose exposed driver supports CUDA 13 would preserve the image; a CUDA-12-compatible build would change its runtime packaging. Read-only official-index verification confirms `torch-2.13.0+cu126-cp311-cp311-manylinux_2_28_x86_64.whl` at [the cu126 index](https://download.pytorch.org/whl/cu126/torch/), allowing investigation of CUDA 12.6 without downgrading the PyTorch release or changing the model. This is wheel availability, not a completed compatible-image proof. A search result suggesting cu128 was required was not used as a dependency recommendation; the official cu126 entry and actual driver evidence are the retained facts.

The next proposed step is explicit approval for a CUDA-12-compatible build, coupled pin/index updates, full tests and image/security gates, followed by another bounded test on the same deployment. There is no CPU fallback, compatibility shim, model downgrade, provider-driver modification or additional GPU allocation. This follow-up changed only operational state and documentation: new repository executable tests and coverage are N/A, and the previous 899-test/92.31%-delta evidence remains historical rather than a new run. No automatic quality or source-security gate is eligible for this documentation-only repository delta; live acceptance remains **blocked**, never relabeled as passed. Final independent leader reads again confirmed paused and zero replicas; a membership sweep including the newly supplied inference key found no actual credential in task JSON evidence or handoff documents. Diff whitespace checks pass. No temporary verification environment or local server was created during this resumption.

## Update 2026-10-26: approved CUDA 12.6 packaging and publication

### Approval, baseline and implementation

The user explicitly approved proceeding with CUDA 12.6 while retaining PyTorch release 2.13.0 and the model. The existing `dev` approval remains in force; baseline is `8d8b4d583e550fd832f0d361a6702bb52552a0a4`, synchronized with origin, with the ignored snapshot `../status/2026-10-26-verda-cu126-workspace-state.md`. Chezmoi synchronization succeeded. All prior Markdown and non-executable test hygiene changes were preserved, and directives/expectations remain absent.

The smallest unified-image correction changes the manually coupled requirement and Docker literal to `torch==2.13.0+cu126`, selects the official cu126 wheel index, and requires the exact build-time `torch.version.cuda == '12.6'`. No provider-specific handler, alternate Dockerfile, build matrix, application API, authentication default, CPU recipe, model revision, other direct dependency pin, base digest, compiler/OpenSSL protection, port, Gunicorn configuration or scan policy changed. Current policy/docs describe cu126 while retaining all dated cu130 results and the actual dev.6 driver failure as history. The target remains the same single Verda deployment, never an additional GPU or RunPod mutation.

### Independent source verification

The leader inspected the actual diff and ran the full declared suite with Python 3.11.16, Flask 3.1.3 and PyMuPDF 1.28.2: **901 tests passed without skips**, `/tmp/envai-pii-cu126-20261026-tests.log`. New static contracts pin the coupled channel and execute the actual Docker build-check Python with a fake Torch/temp model snapshot, accepting 12.6 and rejecting missing or other CUDA versions and incomplete/invalid model snapshots. Production coverage for this packaging/configuration delta is **N/A**; no production Python code changed.

Quality and focused dependency/container security reviews returned **PASS**. A non-blocking test-scope advisory was corrected through delegation: the old no-`cloud_service` guard covers all RUN instructions again, not only the selected build-check line. The leader then reran the full suite, **901 tests without skips**, `/tmp/envai-pii-cu126-20261026-final-tests.log`, and the follow-up quality judgment returned **PASS**. The production delta remained identical to the security-reviewed snapshot. Documentation wording advisories were corrected directly. Real wheel import, resolved transitive packages and remote Trivy remain publication gates, not inferred from unit tests.

The isolated commit is `4c4db76ee1712283ba8f5778da70871b2b43e169` (`fix(container): support CUDA 12.6 hosts with the pinned model`). It contains the three packaging/test files, current coupling policy and README, only the relevant CI/RunPod/current changelog edits, and the coherent same-thread Verda guide. No unrelated RunPod history, pending test comment cleanup, trace record or untracked report was included. The leader reviewed the exact staged result before the normal dev push. `main` is unchanged. At that checkpoint, live acceptance remained pending the new scanned image and a bounded update/test of the existing paused deployment.

### Published image and corrected configuration gates

Release `v1.0.0-dev.7` and publisher `40402660173` succeeded. Logs confirm a real installation of `torch-2.13.0+cu126`, successful exact CUDA-12.6 build check and `pip check`, all three CI Python test jobs, and the unchanged Trivy policy: **zero blockers, 287 unfixed ignored**. The residual is nonzero and differs from dev.6 because the dependency set changed; no ignore exception was added.

The leader independently fetched the public registry manifest and config, recomputed their digests and verified source `4c4db76ee1712283ba8f5778da70871b2b43e169`, version `1.0.0-dev.7`, linux/amd64, user `app`, preserved healthcheck and no baked auth-mode/token. Manifest is `sha256:c1d9d9c089047f7c1e4b7b0815e91a12cd810c963ddb58ba1f0da1233e961714`; config is `sha256:feb376bc156db28f44f81a3864fcb3c98a9391daa33f1908e34c85061b5f5de0`.

The private image-update artifacts are under `/home/lorenzo/private/tmp/envai-pii-cu126-20261026/`, not the earlier `/tmp` evidence directory. Proposal review initially failed on an unverified tag/publication state and timestamp projection; a second judgment required explicit new-image readback separate from all-other-fields preservation and current publication wording. These were corrected rather than waived. The actual request now pins only `containers[name=envai-pii-test-0].image` to the verified full digest, SHA256 `49d8400b6c9bdb6eb1d0cdb1b7dc862733b6fcf8db278895f4a5417339a5cbaf`. The preservation bundle removes the whole image object and optional container-root update timestamp, retains every other setting, and separately requires exact new-image equality before resume. The leader freshly reproduced canonical preservation hash `bab9ca5cb5a7f2173563795530376a5dfa1fcfacf412c5ace54c8320ffc51cae` and reran all **901 tests without skips** after the corrections. Final configuration quality and focused-security proposal judgments returned **PASS**. Logs are `/tmp/envai-pii-cu126-20261026-config-gate.log` and `-final-config-gate.log`.

A backend-dev-b artifact task produced an unusable recursive-role refusal and no edits. After it terminated, backend-dev-a completed only bounded artifact correction, preserving verified progress; no general-family writer bypassed the restriction. The provider accepted exactly one digest-reference PATCH with HTTP 200. All settings remained intact. The operator unnecessarily paused once on transient `updating` with zero replicas instead of waiting for apply to settle. This was a non-blocking observation-guard error, not an actual unpause or allocation. The target then read back paused/zero and the leader independently verified exact new image plus unchanged preservation hash before approving live traffic. No tag fallback, alternate resource or incompatible-image rollback was attempted.

### Real GPU verification and honest first-run failure

The first cu126 live run resumed the same deployment once. CUDA health became ready after 237.8 seconds including the initial image pull. Thirteen known positive checks returned 200, covering GPU health, settings/tags/config, port-check, JSON email masking and seed reuse, multipart TXT plus text, guardrail extraction and masking of a real synthetic PDF, legacy analysis, preview and PDF responses. Thirty absent/invalid-key probes across fifteen route/method cases all returned the same 19-byte provider 404, SHA256 `b16e15764b8bc06c5c3f9f19bc8b99fa48e7894aa5a6ccdad65da49bbf564793`, never an application or 2xx response.

In parallel, the leader independently called valid-key GPU health and a unique synthetic JSON analysis while the replica was warm, checking the exact placeholder, exact dictionary delta, placeholder count and no-store. The same health path with absent and invalid keys returned the provider 404 while the valid key returned 200. This is direct verification, not merely acceptance of the worker's PASS flags.

The first verification client then misclassified the expected valid-key 404 for a nonexistent PDF-preview page as failure, before its route-specific expectation ran. It stopped and safely paused, with zero replicas verified. No application or security failure was observed, but the remaining unknown-path contrasts and natural idle observation were incomplete. The original `evidence-cu126-live.json` and `evidence-cu126-final.json` retain **FAIL** and the exact failure classification; they were not rewritten as success.

The leader approved a separate, bounded closure on the same deployment, correcting only verification expectations rather than app logic: existing routes still require 200, missing resources require an application 404 distinct from the provider denial, and absent/invalid keys may never reach application behavior. This did not change user-visible behavior or any configuration, and required no extra resource. The closure client self-tested the classifications before one further explicit resume. No blind automatic retry, third resume, restart or recreation occurred.

### Final auth contrasts and natural scale-to-zero

The closure ran from **22:16:22Z to 22:19:22Z**. With the image cached, CUDA health was ready in 37.7 seconds. It reconfirmed JSON masking/seed reuse and settings/config health. All three previously incomplete missing-page/file/unknown-path cases now returned expected application 404s with a valid key and the distinct provider 404 without or with an invalid key. `/healthz` returned valid-key 200 and absent/invalid-key provider 404. The leader independently queried management while warm, correctly parsing `replicas.list` and observing **one running replica**, rather than inferring activity from a stale empty list during initialization.

After the last endpoint request at **22:17:08.419Z**, only management reads were made. One running replica progressed through terminating to zero. Provider events show `ReplicaDeleted` and `ScaledToZero` at **22:19:14Z**, approximately 125.6 seconds after traffic, despite a configured 60-second scale-down delay. This is a dated observation, not a 60-second guarantee, SLA, benchmark or cost estimate. The closure made **one resume and zero pause calls**. The leader then independently re-read **healthy, unpaused, zero replicas**, exact deployed image and min 0/max 1, and fetched the matching creation and natural-delete lifecycle events. The first cu126 run's safety pause and the image-apply observer's unnecessary pause remain separately disclosed above.

Focused live upstream-auth evidence review returned **PASS** with no blocking findings. The proof is the combined same-path valid/invalid-key contrast, actual successful GPU requests, preserved configuration and verified cleanup; a 404 alone is not called proof, and no 401 response was invented. The review covers the tested provider-only boundary, not a penetration test or certification of the entire provider. PyTorch release/model/API remain unchanged; real-world accuracy, GDPR, complete PDF redaction and capacity are not claimed.

Authoritative closure evidence is `evidence-cu126-closure.json`, `evidence-cu126-closure-final.json` and `evidence-cu126-closure-ready.json` in the private directory, plus `evidence-image-patch.json` and the retained first-run FAIL artifacts. All are sanitized mode 600. The final endpoint is `https://containers.datacrunch.io/envai-pii-test/`, authenticated with the dedicated Verda inference key, never the management client secret. The deployment definition is retained for the user's requested service, with no warm GPU and no claim that every possible account charge is zero. No RunPod resource or additional deployment, GPU class, provider key or volume was changed. [The Verda handoff](../../../docs/verda-service.md) and [CI guide](../../../docs/ci-release.md) now record the completed state.

### Final repository and resource closure

Documentation was committed and pushed separately as `167826a3616efe5ccb709817e03046107905d799` and the historical-callout consistency follow-up `89412bf750c2a6bf3e80fcfbb7bebd192597ef46`. These `docs` commits change no runtime artifact or application/test tree relative to source `4c4db76`; the final Release workflow `40414142988` succeeded without creating another release, and dev.7 remains the latest image version. No history rewrite, forced push or main update occurred. All unrelated pre-existing Markdown, reports, research and test-comment cleanup remain preserved locally; no clean-worktree claim is made.

Final independent management reads at **23:41 local time on 2026-10-26** again confirmed healthy, unpaused, zero replicas, min 0/max 1 and the exact cu126 digest, without calling the inference endpoint or waking a GPU. Actual-credential membership checks passed over private evidence and handoff files. The task-created local verification venv was removed, and no local server, helper process or test container remains. Documentation structure and diff-whitespace checks pass. The final documentation-only closure has tests/coverage N/A and does not trigger another automatic implementation gate; the earlier 901-test, source/config PASS and focused live-auth PASS evidence remains the applicable verified result.

## Update 2026-10-27: unchanged Verda bursts at 4, 8 and 16 requests

### Scope and technical reasoning

The user approved continuing on `dev` and requested three HTTP bursts using the same 45000-character text, without changing configuration. HEAD and origin/dev remained `89412bf750c2a6bf3e80fcfbb7bebd192597ef46`; the ignored baseline is `../status/2026-10-27-verda-load-workspace-state.md`. Existing changes were preserved, and directives/expectations remain absent.

The user's recollection of four model copies was valid for the earlier temporary A40 diagnostics documented in [single-GPU capacity](../../../docs/runpod-single-gpu-capacity.md), including the fixed-four-model experiment. Those optimizations were not integrated into the published service. This test measures the existing Verda deployment, not that diagnostic topology: one L40S, one Gunicorn worker/model copy, serialized model calls, provider concurrency one and min 0/max 1 replicas. No model, batching, image, admission or provider limit was changed.

The previous reviewed HTTP fixture helper was reused with `generate_text(45000, 42)`, fixed once rather than varied per request. Independent reconstruction verified exactly 45000 Unicode characters, 45163 UTF-8 bytes and one identical compact JSON body across the warmup and all 28 measured requests. All categories were enabled by omission of the filter; no seed was supplied. Text SHA256 is `97adc9b463df5728344baa30b734db39a09d24986a1c3d01ffccde3ade3e6fca`; request-body SHA256 is `d2a274f2ab87b0d3d71f2b9be595350e5a9ce0c919f11a7eea12a2d168d33b59`.

### Measured results

Each level was one synchronized burst, one call per client, with no pacing, retry or replacement request. A barrier released all prepared clients; measured start spreads were approximately 1.1, 2.7 and 6.5 milliseconds. The previous group fully drained before the next began. Times below are client-observed seconds through receipt of the full response, including transport and provider queueing, excluding setup, validation, cold start and warmup.

| Simultaneous clients | Validated successes | Mean response seconds | Maximum response seconds | Group elapsed seconds |
| --- | --- | --- | --- | --- |
| 4 | 4/4 | 4.464946 | 6.963792 | 6.965009 |
| 8 | 8/8 | 7.905010 | 13.983125 | 13.984228 |
| 16 | 16/16 | 14.492715 | 26.951788 | 26.955514 |

All 28 measured requests returned validated 200 responses, with no overload rejections, network failures or timeouts. Every response's canonical hash matched the separately validated warmup. Independent interval reconstruction confirmed client overlap peaks of 4, 8 and 16; these are in-flight HTTP clients, not simultaneous GPU forwards. The means were independently recalculated from every request row and checked with the calculator.

Measured traffic ran from `09:04:18.871Z` through `09:05:07.300Z`. Readiness and the single 3.923475-second full-document warmup are excluded. The first readiness probe timed out after 150 seconds; a second probe confirmed CUDA readiness before warmup and measurement. There were 29 analysis calls including warmup, plus two readiness attempts. The artifact field `endpoint_requests_started: 29` counts analysis calls only, not the health attempts.

### Impact and cleanup

The whole bounded operation took 415.011 seconds. After the last measured response, only management reads continued. One running replica returned naturally to healthy, unpaused, zero replicas; the idle observation took 119.010 seconds and provider system logs reported post-traffic `ReplicaDeleted` and `ScaledToZero`. A terminating sample was not captured and is not claimed. No pause, resume, PATCH, restart, recreation, key mutation or RunPod action occurred.

The sanitized deployment/scaling fingerprint remained `0d9c72938d6e945c5d2e6d7d4259ee84ed0accc06c8a252e73eb1f3d7842d1ba`. The leader independently queried management afterward and confirmed the exact cu126 image digest, one container, healthy state, zero replicas, min 0/max 1 and provider concurrency one, without generating further endpoint traffic. The load process returned and no local server, dependency environment or additional cloud resource was created.

### Evidence and validation

Private evidence is `/home/lorenzo/private/tmp/envai-pii-verda-load-20261027/`: `evidence-preflight.json`, `evidence-warmup.json`, `evidence-ready.json`, `requests.jsonl`, `results.json` and `final-state.json`. The directory is mode 700 and files are mode 600. Only request metadata, status, timing and hashes were recorded; actual-credential membership checks passed. Credentials stayed in memory, with normal TLS, pinned origins and redirects disabled.

The leader read the actual artifacts, reconstructed the fixed fixture, checked all 29 unique analysis records, verified all measured statuses and response hashes, recomputed latency and client-overlap statistics, and compared baseline source/document hashes. All baseline files remained byte-identical except this intentionally extended operation record. No source, executable helper, test or runtime configuration file changed; repository tests, executable coverage and automatic implementation/security gates are N/A for this operational measurement and Markdown-only delta. No new gate or coverage pass is claimed.

This is one burst per level on one synthetic document, not a soak test, hardware-capacity maximum or real-world accuracy benchmark. More simultaneous requests were accepted, but average and tail response times increased. The earlier in-process four-model/B16 results are not directly comparable to these end-to-end HTTP timings.

## Update 2026-10-27: model-copy comparison prepared, activation blocked

### Summary of changes

The user authorized `dev`, a comparison of 1/2/4/8 model copies with 1/2/4/8/16/32 concurrent clients, and retention of the final experimental definition instead of restoring the old one. Portable native-Gunicorn configuration, numeric readiness/resource telemetry, deterministic fixture packaging and transport-injected burst measurement were implemented and verified. The [living plan](../plans/2026-10-27-verda-model-copies.md) is blocked before activation; the [preparation report](../reports/2026-10-27-verda-model-copies.md) explicitly marks every new cell unmeasured.

### Technical reasoning

Independent worker processes provide multiple model copies without modifying the production model, inference functions or API. The comparison holds B1 and precision fixed and targets the stateless v1 endpoint; legacy PDF caches and preference state remain per process and are not declared production-ready. The planned matrix has three bursts per cell, 189 calls per feasible model count and 756 overall. Runtime/source integrity, all-worker CUDA warmup barriers and conservative GPU/RAM/PID headroom precede growth. The final verified configuration would be retained, not automatically chosen as a winner.

Two initial integration faults were independently reproduced despite passing unit tests: unpacked module paths did not survive exec and Gunicorn rejected the variadic post-request hook. Delegated corrections fixed these and strengthened command-size and total-VRAM guards. All four configurations now pass actual Gunicorn 26.2.0 validation and a fresh-child exec import probe. Archive differences between Python 3.14/zlib-ng and the specified Python 3.11/zlib were diagnosed without changing source; all activation artifacts reproduce the exact reviewed archive with the prescribed builder.

### Impact assessment

No provider runtime change or GPU wake occurred. The operational backend member refused the actual PATCH because it adopted the recursive coordinator role and could not delegate from inside a subagent. Other backend members remain excluded by the known session OpenRouter 402. The coordinator did not evade this by applying the PATCH directly or assigning it to an unsuitable agent family. Repairing the global agent-role workflow would involve the separate chezmoi Git repository and requires explicit approval before adding that repository to the task.

The final independent management read at `12:44:54Z` confirms healthy, zero replicas, the original c1d9 image, disabled entrypoint overrides, the original two env names, provider concurrency one and min 0/max 1. Nothing was restored because none of the new profiles was applied. There is no new GPU feasibility, RAM/VRAM capacity or performance finding for any of the four variants. Existing model, keys, RunPod resources and pre-existing worktree files remain preserved.

### Validation steps

The parent executed all 958 tests without skips using Python 3.11, Flask 3.1.3 and PyMuPDF 1.28.2. New helper coverage is 969/1057 executable lines, rounded 92 percent, with every file above 80 percent. Independent quality judgment returned PASS, requiring an external hard process watchdog for all live runs. A fault-injected stalled client was terminated and reaped with no network calls. No internal barrier deadline or server-side cancellation is claimed. No application API, authentication or sensitive-data handler changed; a new core-surface security review was not triggered by this preparation slice.

Private source, manifest and gate evidence is `/home/lorenzo/private/tmp/envai-pii-verda-replicas-20261027/`. The common reviewed archive is `3c5958809df67665a41ab84d801d74d8d1d2506d751bb357f37a321ee40537dd`. No code comments, test deletion, skip or weakening was introduced. Source/diff checks passed; no Git staging, commit or push occurred. Preparation was verified, but at that earlier checkpoint the requested live experiment was not complete.

## Update 2026-10-27: four-copy-count experiment completed with a disclosed replay

### Summary of changes

The user reported restored OpenRouter credits and the primary backend route became usable again. The [same living plan](../plans/2026-10-27-verda-model-copies.md) was resumed without changing the frozen baseline or repairing another repository. All four requested model counts1/2/4/8 and concurrency levels1/2/4/8/16/32 were measured on the existing single-L40S deployment. [The report](../reports/2026-10-27-verda-model-copies.md) contains latency, tails, throughput, errors, actual memory/task observations, final state and method limitations. No production app/model/image or authentication handler changed; native Gunicorn configuration creates one model per process.

### Technical reasoning

Two unadvertised provider constraints required reviewed equivalent command delivery:253characters per argument and64cmditems. A compact self-contained signed/compressed package now uses61items, max253characters and unchanged source/model behavior. Build-only modules and the local resource guard are excluded from the GPU archive. Real image startup proved its ZIP_LZMA integration. Archive02997f5797c376163051c1c8c5685f617be93077ebe0ed5b85e7d9dcc0dda753 stays fixed across every measured profile.

Native leaf pids.max is explicitly max, not missing; this was distinguished through its exact pinned parser reason. A separately declared512task experiment budget with20percent headroom is permitted only on that proof. Unknown/invalid readings remain blocked and any finite smaller provider cap prevails. Actual pids_limit remains null and the budget is never represented as a kernel or provider quota; hidden ancestor/host limits remain unknown. RAM and total-VRAM guards retain their20percent headroom. Only the local controller and its tests changed for this correction, so earlier N1 data and all runtime/profile bytes remain valid.

Increasing processes also replicates per-process HTTP admission and changes connection distribution. These results are end-to-end topology comparisons, not isolated VRAM effects or GPU-forward concurrency measurements. B1, float32, modelv1.5 and the45000Unicode-character JSON fixture remain fixed; old A40/B16 core measurements are not relabeled as these HTTP results.

### Impact assessment and retained configuration

The final definition has eight Gunicorn model copies, provider concurrency32, admission16/queue32/timeout30 per worker, analysis60seconds, OMP/MKL1 and tokenizer parallelism disabled. The same c1d9 image, oneL40S, port5005/health, public registry, no mounts and min0/max1 remain. No extra deployment, GPU class, RunPod resource, key, volume or image was created. No original-config restore or automatic fastest-profile choice occurred. The existing definition is healthy with zero replicas at idle and will load the configured copies on demand.

The operator's first N8 run stopped after three valid CC1 responses, temporarily returned to lastsafeP4 atzero, and then repeated the complete N8 matrix. This contradicted the declared no-replay method and is not retroactively approved. All three original rows are preserved in the separate attempt1-guard-bug directory and included in the report's descriptive six-sample CC1 pool. The remaining N8 cells keep the intended three bursts. Full main matrices contain756attempts/736successes; the three extras yield759/739. The20failures are all N1/CC32 HTTP429. No success was invented from the first attempt's incorrect unconsolidated zero-success aggregate, and no failed record was deleted or silently replaced.

### Validation steps

The parent ran972tests without skips, approximately92percent overall helper coverage and97percent local-guard coverage. All applicable packaging/controller quality judgments passed; source/archive fingerprints remained fixed during measurements. The changed slice contains no new app API, authentication or sensitive-data handler, so no additional automatic core-surface security gate was eligible. This is neither a security certification nor a clean-protocol claim. Subsequent report/ledger edits are Markdownonly and human-reviewed, not another automatic codegate.

Parent independently reaggregated every row, fixture/body/oracle hash and all24mean cells, verified arithmetic with the calculator and byte/GiB conversions with the unitconverter, and checked report values against raw data. Native serving-window evidence proves2/4/8independent ready PIDs with unchanged model/dtype/settings; N8 pagination recovered1008events and no measured-window exit/churn. The earlier N1 final empty-ready aggregate was checked against196events of the actual serving window, not treated as a failed startup. N2/N4 summary-scope errors were reconciled via management-only lifecycle records, without replaying their measured requests.

Final independent management reads at22:30:46Z confirmed exact retainedN8, healthy, zero replicas, provider concurrency32 and min0/max1, with no new health/inference traffic. Parent lifecycle reads verified that the first N8 replica was deleted before the second was created and the final replica naturally scaled to zero at22:13:04Z. Actual-credential membership checks passed over119private/source/report files; no scoped local benchmark client remained. The pre-existing verifier environment was preserved, not removed as if task-created. Gitstaging/commit/push and globalagentconfig changes were not performed. Older unrelated worktree changes remain preserved.

The detailed evidence is under `/home/lorenzo/private/tmp/envai-pii-verda-replicas-20261027/`, with N1/N2/N4/N8 cmd64 prefixes, plus the separate first-attempt N8 directory. The current delivery is complete with the disclosed method deviation; earlier blocked RunPod-capacity work and other historical outcomes are not claimed complete. Next action at that checkpoint was the user's topology selection, not another automatic run or deployment change.

## Update 2026-10-28: eight-copy GPU-observation preparation verified, execution blocked

### Summary of changes

The user explicitly requested GPU-monitored tests directly on the retained eight-model setup. The same living plan gained a separately authorized Phase7; original comparison rows and its disclosed replay remain unchanged. Three optional diagnostic modules, build-side packaging and three fake-test modules were added. The [follow-up report](../reports/2026-10-28-verda-eight-model-gpu-profile.md) separates verified offline preparation from missing live results.

### Technical reasoning

The complete live public Verda contract exposes no observed GPU metrics endpoint. The optional Gunicorn wrapper therefore preserves all original hooks/warmup/barrier while one fixed owner samples NVML with CUDA/NVML UUID matching, numeric-only schema, explicit unavailability, optionalpower and safe lifecycleclose. B1, model/dtype/image/API/authentication/inference/admission remain unchanged. The fixed transport-injected load would contain402calls, no retry/substitution and perburst persistence; it has not produced verified live results.

An initial19688char environmentcarrier was rejected by the undocumented253charpervaluebound. A controlled diagnosis captured the exact validationmessage and unchangedoldN8. Corrected hybrid delivery keeps halfarchiveinverifiedbootstrap and halfin39numbered253byteenvchunks, removedbeforeexec:56cmdargs/47envvars. Defaultarchive02997f57 and diagnosticarchive2b2c5854 remain byteidentical. Correctedcandidate e0ee052e is built/verified but not applied. The private gpu8-profile.json still denotes the rejectedfirstformat, not thatcandidate.

### Impact assessment

Operationalprimary-a returnedproviderfinish_reason:error, b acceptedtheexistingdevpermission but adopted a coordinatorworkflow requiring forbiddennesteddelegation, and c endedwithupstreamidletimeout. No corrected-profile artifacts or usable measurementrows appeared. Provider-interruptedcalls lackcompleteAPIactionledgers, so their unknownactions are not assertedzero. Withthefamilyroutesexhausted, thecoordinator didnotbypassrestrictionsviaanotherrole orapplytheoperationdirectly, and didnoteditglobalagentconfiguration in anotherrepository.

Parent finalnativeverification at2026-10-28T02:41:57Z confirms exactpreviousN8, healthy,0replicas,min0/max1,ingress32, monitoredcandidateunapplied. No original/4copyrestoration, newresource, image/modelchange orcommit/push/staging occurred. This is a blockedfollow-up, not a regression of the completedfour-waycomparison.

### Validation steps

Parent fullunittestdiscovery undercoverage passed1036tests withoutskips; diagnosticdelta approximately90percentcoverage, monitor90/wrapper87/profile88/package95 andnewGPUpackage114/120lines. Independentquality-gate-a returnedPASS forinitialslice andtransportcorrection. ActualGunicorn26.2 hookarity andfreshsubprocess exec/import passed. No app/Dockerchange ornewcomments. No additional coreAPI/auth/sensitivedata securitygate waseligible; thisisnotasecuritycertification. Private10file actualcredentialmembership sweep passed, and no scopedbenchmark/verifierprocess remained; the pre-existing verificationenvironment ispreserved. Remaining editsareMarkdownonly andhuman-reviewed.

Evidence: /home/lorenzo/private/tmp/envai-pii-verda-gpu-profile-20261028/. Restore a compatible working operationaldelegate before resumption; any repair involvingthe separatechezmoirepository still needs explicitapproval. No new performanceorGPUutilization result isclaimed.

## Update 2026-10-28: retry accepted, L40S scheduling unavailable

### Summary of changes

The user asked to retry. The coordinator revalidated the unchanged package, reran all 1036 tests successfully and resumed the same Phase7 without editing global agent configuration. The primary delegate now completed the operational attempt: one corrected deployment PATCH returned200, no scaling PATCH, and the exact hybrid profile e0ee052e was eventually visible after readback lag. This supersedes the earlier unapplied-candidate and exhausted-executor snapshot, not its historical evidence.

### Technical reasoning

One authenticated health trigger requested replica `envai-pii-test-6cdbf8cd4c-lcpjw`, then timed out after330seconds. The operator obtained no application logs or ready/counter events. The coordinator independently fetched provider system logs and established the actual cause: `SchedulingFailed`, four grouped occurrences, message `Replica could not be scheduled: no nodes available for the selected instance type right now`. The replica creation time08:22:52Z is not proof that a container or GPU started. No warmup, benchmark, GPU-sample or correlation result is credited.

### Impact assessment

The monitored eight-copy definition is now retained, with the same image/model/B1/precision/authentication/admission and L40Sx1 allocation limit. No alternate GPU, deployment or extra resource was created to bypass the capacity restriction. Provider lifecycle shows natural scale-to-zero08:28:36Z and replica deletion08:28:37Z. Parent final management-only reads at08:35:00Z confirm exact command/all47environment entries, healthy/zero, min0/max1 and concurrency32. There was no original/four-copy restore or safety pause. Startup and inference of this diagnostic candidate remain unverified.

### Validation steps

Unchanged gated source hashes, parent1036tests/no skips, prior90percentcoverage and qualityPASS remain valid. Parent independently read the actual action artifacts, seven native system events and unfiltered exactpod application logs. The first parent log-parser attempt assumed a dictionary instead of the actual top-level list and was corrected without network mutation. A future-valued timestamp in the delegate's summary is excluded from evidence; action artifacts and native events supply the timeline. The private21file credential/mode sweep passed and no verifier/client process remained. Whitespace and unchangedapp/Docker checks passed. New changes are operational and Markdown only; no additional executable or coresecurity delta, commit, staging or push.

The [updated report](../reports/2026-10-28-verda-eight-model-gpu-profile.md) and same living plan record the genuine capacity blocker. Resume only when L40S capacity is available, or after explicit approval for a hardware change; do not turn absent measurements into zeros or continuously wake the deployment to poll availability.

## Update 2026-10-28: manual RTX PRO6000 selection and production-availability guidance

### Summary of changes

The user reports manually trying another GPU and asks how production should avoid capacity failures. Read-only management checks confirm RTX PRO6000x1 with the previous monitored N8 entrypoint/environment and c1d9 image. No new health, inference, configuration PATCH, production minimum or extra resource was issued by the coordinator or another operator during this follow-up.

### Technical reasoning

The diagnostic's `_gpu_profile` explicitly requires L40S, while the current image pins Torch2.13/cu126. A non-L40S startup would be rejected by the diagnostic even if memory is sufficient. Official PyTorch maintainer guidance also requires CUDA12.8+ binary support for Blackwell sm120; this is a compatibility warning, not proof of the selected node's actual CUDA architecture or a completed inference test. Changing image/runtime pins requires an approved verification slice, not a blind retry.

The user-initiated rollout has native Scheduled/Created/Started events around09:05:43–44Z, and ScaledToZero/ReplicaDeleted events09:12:22Z. No application readiness or inference logs were returned. Final09:18:27Z read reports healthy with one terminating replica, not an independently proven zero or ready service. User-created transitions are preserved rather than stopped or rolled back.

### Impact assessment

The report now distinguishes hardware availability from image/GPU compatibility. Production advice is warm baseline capacity, an explicit capacity/SLA agreement where required, separately qualified fallback deployments, durable encrypted/idempotent application jobs, bounded retry and monitoring. Eight model copies on one GPU are not independent hardware availability. The existing v1 path is stateless, while legacy previews/preferences remain worker-local and cannot be assumed transparent across failover.

These are proposals only: no production deployment, new GPU, region/provider, queue, secret flow, reservation contract or image change was implemented. A fallback must respect data residency and privacy constraints. A scaling minimum alone or a price discount is not presumed to guarantee replacement capacity.

### Validation steps

Chezmoi/pull and unchanged-source/whitespace checks pass; inherited dev approval and dirty work are preserved. Primary analyzer failed with provider finish_reason:error; sequential read-only fallback confirmed source constraints. Official Verda scaling and Terraform documentation was fetched and read: minimum1 keeps a replica warm, the request TTL includes queue and inference time, and compute selects one GPU type. Official PyTorch maintainer guidance was checked separately. The report links these sources and labels recommendations versus facts. Tests and coverage for this new read-only/Markdown delta are N/A; existing executable fingerprints and prior gates are unchanged. The next approval at that checkpoint concerned a compatible image/diagnostic scope for the selected hardware, not automatic production provisioning.

## Update 2026-10-28: complete L40S GPU and power measurements

### Summary of changes

The user returned to L40S and requested the GPU tests. A fresh read found an already-running L40S with user-owned minimum1; no production or hardware substitution was applied. Eight CUDA models were ready, but the numeric sampler stopped at uuid_invalid. A mechanical correction added strict support for PyTorch's documented _CUuuid.bytes representation, preserving exact CUDA/NVML device matching. Five regression tests and only the corresponding GPU package golden sizes changed; app, model, image, precision, B1 and admission remain untouched.

### Technical reasoning

The old sampler supported Python UUID/string/ascii-bytes but not the PyTorch binding's16-octet list object. The new bounded parser accepts exactly16strictintegeroctets/rawbytes and still rejects malformed/forgedstring-only objects; it never assumes hostGPUindex0. Parent independently ran1041repositorytests and69focusedPython3.14tests, allwithoutskips; all39normalization executablelines/branches covered. Quality-gate-a returnedPASS. Defaultarchive02997f57 stays byte-identical; newGPUarchive6c84cf08/profile3cc02fb1 was frozen beforedeployment.

To replace only the failed diagnostic without twoGPUallocations, the operator used one pause201, actualzero, onePATCH200, exactreadback and one resume201, with no scalingPATCH and finalminimum1 unchanged. Nativeevents independently show the oldpoddeleted10:39:14Z before newpodscheduled10:39:44Z. The new eightPIDs82–89 and owner82 then yielded real GPU counters. An early forward-onlylogcursor missed readiness ingestion and was repaired by a fullpodreread, not anotheractivation.

### Measured result and limitations

All402timedrequests passedbody/oracle/status/timing validation,81bursts/27groups, no402-windowerrors/churn/replay. Meanlatencies byCC1/2/4/8/16/32 are1.945772/2.422759/2.747809/3.797528/6.139454/10.820193seconds; throughput0.513918/0.781741/1.168404/1.525936/1.700565/2.048396successes/s. GPUactivitysamplemeans17.649/25.660/54.350/60.794/70.436/77.833percent; percase57/47/40/63/55/48samples. Powermeans135.162/152.719/180.104/201.663/215.042/233.251W. VRAMmaximum13.482GiB of47.384GiB; RAMpeak8.804GiB, max105tasks.

The measuredwindow is10:46:15.855979–10:51:43.096496Z. Finalcorrelation accepts698owner samples,310active/388excluded, with noidentity/clock/schemaanomalies. NVMLactivity isnotSMoccupancy/FLOPs and powernotbilling. The dataset doesnotseparateCPU/tokenization/GPU/queue time orqualifyB4/B8/B16. Differenthostassignments preventattributingchangesfromoldresults toanoptimizationthatwasnotmade.

One extraunauthenticatedpreliminaryPOST returnedprovider404 beforetheapp at10:45:25Z, preservedoutsideallmeasurements. Thenoneauthwarmup200 passedoracle, followedbythe402timed200. Exactendpointaccounting404POSTstotal=402measured+1authwarm+1unauthextra. This is a disclosedpreliminarymethoddeviation, notanerror-freewholeprocedure or discardedmeasuredfailure. Readysnapshot367versusfinal698 samples coverdifferenttimes; botharepreserved.

### Validation and maintained state

Parent reaggregatedall402rawrows/allp95/throughput and independentlyselectedall310activesamples, exactlyreproducingcorrelation. Sixnative60secondqueries recovered331GPUsamples/1328baseevents and matched every310usedsample, eightstablePIDs and no matrixchurn. An independentread-onlyanalyst confirmed formulas/identity and interpretationlimits. Calculator and explicitmW/1000 conversions support powerstatistics; byte/GiB conversions were verified. The final56privatefile actualcredential scan passed, all21newartifacts are600 in700directory, no savedrunner or localverifierclient remains. No sourcechangedafterqualityPASS and noapp/Docker/git-writecollateral occurred.

Finalnativeat11:10:41Z confirms exactnewentrypoint/all49env, one runningL40S, min1/max1/32, unpaused, providerstatusupdating. The functionalproof is402validanalyses plusready8, not a fabricatedhealthycontrolstatus. The warmreplica iskept under the user'spre-existingminimum1; no original/four-copyrestore, automaticwinner orpermanentpause. SubsequentclosureeditsareMarkdownonly, human-reviewed, with noadditionalautomaticcodegate/coresecuritydelta. The [same living plan](../plans/2026-10-27-verda-model-copies.md) and [GPU report](../reports/2026-10-28-verda-eight-model-gpu-profile.md) are complete withtheir statedlimits; futurechunkbatching orproductionHA work requires itsownscope.

## Update 2026-10-28: chunk batching implemented, real comparison blocked

### Summary of changes

The user approved grouping chunks of the same document, configurable1/4/8/16, and explicitly confirmed dev. The source now batches only within one detector invocation of one unprotected input gap, retaining default1, legacy behavior, request-local seed/categories and the serialized native lane. Batched result cardinality and local indices are validated fail-closed. The [same-thread research](../research/2026-10-28-chunk-batching-inspection.md) informed a new [living plan](../plans/2026-10-28-chunk-batching.md); the [delivery report](../reports/2026-10-28-chunk-batching.md) distinguishes the verified source from the unmeasured GPU comparison.

### Technical reasoning and impact

The installed Transformers pipeline already accepts a batch parameter; grouping with standard-library slicing resolves the requirement without a new scheduler or dependency. A parameter alone could not combine separate singleton calls. Deadline checks remain cooperative around each chunk group and while waiting for the owner; no in-flight model call is cancelled and the60second default is unchanged.

The current published image is untouched. A separately verified opt-in diagnostic bundle carries the exact AST adapter and helper, preserves the registered function object and binder, warms the v1 path on every worker before readiness, and attests base-file and overlay identities separately. The old package/runtime/monitor archives remain unchanged. No weights, precision, auth boundary, wire schema, admission policy, training, release, commit or push changed.

### Validation steps

Parent independently ran1119tests without skips on Python3.11 and3.14, and again on3.11 after documentation. Changed executable lines: adapter21/21, helper57/57, package193/193, diagnostic runtime279/280, total550/551 (99.82percent). Quality-gate-a PASS and focused security-review-specialist-a PASS cover frozen nine-file package0fcada80459283e62029f9cea50ab9cc5146539ae5fdf28eaa9cb3ef6aeeb971, rechecked without drift. The nonblocking direct-helper float/bool advisory is unreachable from the validated server configuration and explicitly disclosed, not represented as fixed.

One packaging primary exhausted context, a sequential fallback completed useful partial files, and a later fallback refusal made no edits; member-c corrected only the new compression-sensitive golden. Tests now pin every decompressed payload byte and all other profile metadata across zlib versions, preserving old archive pins. No failing test was deleted or skipped. The documentation primary left useful partial edits before an abort error; its fallback completed only docs. These are delegate failures, not user cancellation or role bypass.

### Native stop and handoff

Exactly one pause201, actualzero, one deploymentPATCH200 and one resume201 occurred. The provider retained49oldenv names and added56newcarrier names; the exact56readback gate stopped. Parent GETs confirmed105entries are precisely the known union, both subsets intact and the new55argument command exact, not arbitrary unknown configuration. No undocumented env deletion was guessed.

The old pod was deleted14:16:26Z, the replacement was created14:18:56Z, and native SchedulingFailed reports no nodes available for L40S. At14:40:37Z the deployment is unhealthy, unpaused, one error replica and no running GPU, min1/max1/concurrency32 preserved. The diagnosticB1 has not executed; B4/B8/B16, warmup and measured inference counts are all zero. No previousB1 data are relabeled as new measurements. The user's existing minimum is not forced to zero and no replacement GPU/deployment is created.

The executable implementation is verified; the comparison remains blocked. Resume requires actual L40S capacity, explicit expected-union readback handling or documented env removal, all-eight-worker warmup proof and the original response oracle before load. No performance or real-GPU equivalence result exists yet. Private mode600 operational JSONs, source/gate logs and sanitized readbacks live under `/home/lorenzo/private/tmp/envai-pii-batching-20261028/`; a parent actual-secret membership check was negative on26text artifacts. The ephemeral runner is removed and no local benchmark server/container/client remains. Markdown and description-only closure is human-reviewed, not a new automatic codegate.

## Update 2026-10-29: B1 measured, B4 blocked by funds, final shutdown requested

### Summary and verification

The returned L40S ran the verified B1 overlay on eight workers. The existing replica was reused without restart: one excluded authenticated warmup and402measured requests all passed the original canonical oracle. Parent independently reconstructed all81bursts/27groups and every composite request ID; the raw records remain under resume1818-b1-* in the private batching directory. A false consumer FAIL confused case indices with concurrency; a later false stop required a paused boolean absent from the provider schema. Neither caused a model failure or a B1 replay. The user interrupted the next stalled delegate; no fallback was triggered by that cancellation, and a later explicit continue authorized new bounded slices.

Parent native historical audit of18:37:31.379614–18:42:29.808810Z fetched1511lines in six nontruncated windows. It validated302GPUrecords,279active/23excluded,1192base samples, eight stablePIDs and no measured-window exits. At concurrency32, B1 averaged10.872464seconds, p9514.007766seconds,2.253740successes/s, GPUmean87.14percent; sampledglobalVRAMmax13.482GiB and peak kernelRAM8.806GiB. These are B1 observations, not gains from larger batching. The [report](../reports/2026-10-28-chunk-batching.md) includes all six rows and evidence-retention limitations.

### Blocker and operational deviations

At the next preflight the deployment was already paused/zero, old pod deleted22:03:09Z. The operator applied one entrypoint-only B4 PATCH, exact readback and unchanged105env/image/scaling, but reported three resume400 responses with insufficient_funds. The assigned one-running precondition and single-resume limit were not followed; this is disclosed, not retroactive acceptance of retries. No new replica, warmup, benchmark, payment, alternate GPU or other resource was created. Parent independently confirmed paused/zero, B4 exact and min1/max1/32 at23:37:36Z, without retrying resume. The earlier pause's cause is not inferred from a deletion event.

### Cost instruction and handoff

The user explicitly requests shutting machines down after all tests to save money. Final target for this test deployment is now minimum0/maximum1 plus pause and verified zero active replicas. This supersedes the earlier instruction to retain a warm minimum1 at the end; it does not authorize modifying other account resources. Current minimum is still1, but pause already means zero active replicas. No premature conditional change or automatic restart is claimed. Further B4/B8/B16 tests need credit restored by the user; preserve all B1 data, do not replay it, and apply the shutdown postcondition when testing concludes.

Source remains at frozen review package0fcada80 with the prior1119-test and quality/security evidence unchanged. This follow-up changes operational state and Markdown only; no new code/security certification is claimed. No task client remains running. Secrets were held only in memory and no body/delta/carrier was persisted in these action records. The living plan remains blocked for credit with the new cost postcondition recorded.

## Update 2026-10-29: B4 warmup verified and shutdown applied

### Verified progress and remaining gap

After the user restored credit, native reads showed healthy/min0/zero. Primary-a returned an empty provider error. Backend-b failed a duplicated-v1 client path, sent no inference, then cleaned up. Backend-c normalized the image response object and handled eventually consistent scaling readbacks before a successful temporary-min1/resume201 cycle. Earlier client stops and cleanup actions remain in c0950-b4-* rather than being disguised as workload failures.

B4 podbb8bc47ff-w2kht started10:12:49Z, eightPID82–89 passed source/settings/base+overlay checks, realbatch4warm16calls/sum63/max4. One excluded HTTP warmup at10:13:34Z returned200 and the original ddda56ee... canonical oracle,45174request/45746responsebytes. Parent read the actual artifacts and independently confirmed the running replica and min1 at10:17Z. This is not a B4 latency benchmark.

The all-remaining collector then hit UpstreamIdleTimeout before any complete1017-* data. A bounded offline-client attempt also timed out without creating its proposed module or tests. No B4 matrix, no B8/B16 activation, no new executable source or weakened oracle, and no replay of preserved B1. The families' errors are disclosed rather than treated as completion; no general-role or direct-implementation bypass was used.

### Cleanup and checks

Backend-b refused the cleanup role before any request. A narrow backend-c cleanup succeeded: one pause201 and one minimum0PATCH200. The first short OAuth client defect occurred before deployment actions; an incorrect status-source parse was corrected with GETs only. No repeated deployment mutation was needed. stop1130-final.json records11:46:04Z; independent parent GETs at11:48 and13:13:51 confirm paused/min0/max1/32 and an empty replica list. This is the requested cost state, not a claim that all tests finished. No unrelated resource, payment, image or environment was changed.

Parent reran1119tests, PASS in40.132s, no skips; all nine frozen-source hashes remain0fcada80 and prior99.82percent delta coverage applies unchanged. Quality-gate-a PASS for CLEANUPONLY, explicitly excludes incomplete matrices. Remote-toggle coverage is N/A; no new automatic security review is appropriate for unchanged application/auth/secret boundaries and Markdown. Core security remains the prior focused PASS.

### Handoff

Keep this deployment paused/min0 until a working collector/execution agent is available. Credit is no longer the observed blocker. Then resume only missing B4/B8/B16 measurements under the same identity, oracle and resource guards, never replay B1 or infer speedup from warmup. Any future attempt must end min0/paused/zero even on failure. The existing living plan remains blocked, not completed, with these evidence and capability limits recorded.

## Update 2026-10-29: reusable collector verified and B4, B8, and B16 matrices completed

### Summary of changes

Added the reusable 4-file collector and transport module package (`tools/verda_model_experiment/batch_experiment.py`, `tools/verda_model_experiment/transport.py`, `tests/test_verda_batch_experiment.py`, `tests/test_verda_transport.py`, manifest SHA256 `1a66159cd95884b24b4e58994470b6b77861775887380f7ef636b75047188776`, invoked as Python modules/functions without a CLI tool) while keeping the frozen 9-file core batching package (`0fcada80459283e62029f9cea50ab9cc5146539ae5fdf28eaa9cb3ef6aeeb971`) byte-identical. Completed the live single-L40S 4x6 comparison across `B4`, `B8`, and `B16` (`402/402` validated HTTP `200` responses per batch, `1206` new measured requests plus the `402` preserved historical `B1` requests for `1608` comparable HTTP rows across `81` bursts and `27` groups per batch, plus one excluded authenticated HTTP `200` warmup per matrix) without replaying `B1` (`b1_replayed: false`). Updated the [chunk batching report](../reports/2026-10-28-chunk-batching.md), [chunk batching guide](../../../docs/chunk-batching.md), [Verda service guide](../../../docs/verda-service.md), and [superseded batching handoff](../research/2026-10-29-chunk-batching-handoff.md).

### Technical reasoning

- **Reusable collector and transport:** `batch_experiment.py` implements 8-worker base/overlay readiness and NVML owner attestation, bounded `<=55 s` ascending log windows with page splitting, the excluded warmup against the fixed canonical oracle (`ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40`), and the existing 402-request burst protocol with private evidence persistence. `transport.py` provides credential-separated bounded HTTP calls. Neither module orchestrates deployment lifecycle: separate delegated operational commands verified the exact 105-entry env union, image/hardware/probe/mounts, polled eventual readback consistency, and used `try/finally` to pause, set minimum0 and verify zero replicas.
- **Measured windows and results:**
  - `B1` (historical, preserved, not replayed): `2026-10-28T18:37:31.379614Z` to `18:42:29.808810Z`, `bursts.jsonl` SHA256 `57edaf2e70e8fb8212d65e1eecc502951590afeaa85385d29758b4284b13f993`. At `CC32`: mean `10.872464 s`, p95 `14.007766 s`, `2.253740 req/s`.
  - `B4` (pod `envai-pii-test-bb8bc47ff-2q8l5`, PIDs `83-90`, owner `83`): `2026-10-29T16:41:46.700559Z` to `16:46:02.938611Z`, `bursts.jsonl` SHA256 `ba2d9ea0aafa81eb1c81a76e084ea9ffce8c5c968b9219a4d43ccbc45c741c60`. At `CC32`: mean `6.630575 s`, p95 `9.369125 s`, `3.392860 req/s`, active GPU mean `69.62%`, memory controller mean `9.28%`, `29` active samples (`100%` coverage), power mean `259.52 W`. Overall `275` NVML samples (`173` active), `1091` base samples, max VRAM `13.7943115234 GiB` (`14811529216` B, `70.888%` min free of `47.384 GiB`), kernel RAM peak `8.8021812439 GiB` (`9451270144` B, `84.826%` min free of `58 GiB`), max PIDs `106`.
  - `B8` (pod `envai-pii-test-7596b899c7-qdk9c`, PIDs `82-89`, owner `82`): `2026-10-29T17:44:44.862892Z` to `17:48:39.565890Z`, `bursts.jsonl` SHA256 `31124d70bda71c598e38dc408bb99ee7a5a98415105a179b68e3adc9a28aa775`. At `CC32`: mean `5.974584 s` (`-45.05%` vs `B1`), p95 `8.247637 s`, `4.026919 req/s` (`1.78677x`, `+78.68%` vs `B1`), active GPU mean `81.17%`, memory controller mean `25.09%`, `23` active samples (`95.83%` coverage), power mean `283.06 W`. Overall `249` NVML samples (`145` active), `990` base samples, max VRAM `14.0911865234 GiB` (`15130296320` B, `70.262%` min free), kernel RAM peak `8.80100250244 GiB` (`9450004480` B, `84.829%` min free), max PIDs `103`.
  - `B16` (pod `envai-pii-test-8449bf7c67-qxrkq`, PIDs `82-89`, owner `82`): `2026-10-29T18:45:55.480513Z` to `18:49:57.710973Z`, `bursts.jsonl` SHA256 `28abd4687c53abe6df2bbdbf482c7ca702a9e8021caecb6a539c92d345797614`. At `CC32`: mean `5.597851 s` (`-48.51%` vs `B1`), p95 `8.063148 s`, `3.919794 req/s`, active GPU mean `75.96%`, memory controller mean `24.56%`, `25` active samples (`100%` coverage), power mean `276.44 W`. Collector captured `263` NVML samples (`156` active) and `1054` base samples; parent read-only audit recovered `268` NVML samples (`156` active) and `1070` base samples. Max VRAM `15.2630615234 GiB` (`16388587520` B, `67.789%` min free), kernel RAM peak `8.80948638916 GiB` (`9459113984` B, `84.812%` min free), max PIDs `105`.
- **Methodological and operational disclosures:**
  - During `B8`, primary `backend-dev-a` failed with a provider error before writing files. Fallback `backend-dev-b` first stopped pre-resume on a bounded config readback lag (`live-b8`, `17:11:42Z`; read-only follow-up confirmed `B8` was applied and state remained `paused`/`min=0`/`0` replicas with `0` inference calls), and in a second run (`live-b8-ready`) activated the GPU (`min=1` + `resume`), hit a client readiness log-collection deadline (`log_collection_deadline`) with `0` warmup and `0` measured HTTP requests, cleaned up to `paused`/`min=0`/`0` replicas (`17:30:45Z`), and hit an `AttributeError` while constructing the post-cleanup API ledger (`api-ledger.json` finalized offline at `17:32:58Z` with `accounting_complete: false` for intermediate pre-cleanup poll counts). Both `live-b8` and `live-b8-ready` are preserved. Member `backend-dev-c` (`live-b8-c`) reused the proven `B4` collector path with consistent monotonic clocks for readiness deadlines and completed `B8`.
  - During `B16`, attempt 1 (`live-b16-attempt1-preflight-failed`, `18:25:59Z`) stopped in preflight on a healthcheck key mismatch with `0` mutations and `0` inference requests. Attempt 2 (`live-b16-attempt2-gate-failed`, pod `envai-pii-test-8449bf7c67-zmnt5`) applied the `B16` entrypoint PATCH, set `min=1`, and resumed (first `B16` GPU activation), but readiness log polling missed log ingestion within budget with `0` warmup and `0` inference requests, and cleaned up to `paused`/`min=0`/`0` replicas at `18:35:55.830Z`. Attempt 3 (`live-b16-c`, pod `envai-pii-test-8449bf7c67-qxrkq`) started with `B16` already configured (`state_at_start: b16_exact`, no entrypoint PATCH resubmitted), performed a second sequential single-GPU activation (`min=1` + `resume`), completed the warmup and all `402/402` measured HTTP requests, and cleaned up to `paused`/`min=0`/`0` replicas at `18:51:00.242Z`. `B16` therefore used **two sequential single-GPU activations** (never two simultaneous GPUs, and zero measured HTTP replay).
  - In `live-b16-c/matrix-b16/result.json` (preserved unaltered), `stop_reason` is `gpu_log_collection_failed` because the final 30-second post-matrix log reread budget expired. Even in that original file, `matrix_complete: true` and `gpu_evidence_sufficient: true` were already satisfied (`263` NVML samples, `156` active, `1054` base samples, minimum `18` active samples per cell, `0` anomalies). A delegate's claim that 40 samples were missing from the last 26 seconds is false and rejected: the original `263` samples already contained all `156` active samples, including all `25` active samples of the final `24.491 s` `CC32` window (`100%` coverage). The parent executed 6 non-truncated `<=55 s` historical log queries (`2026-10-29T18:44:50.480513+00:00` to `18:50:07.710973+00:00`), recovering `268` NVML samples, `1070` base samples, and all 8 ready PIDs (`82-89`, owner `82`), removing zero original samples and adding `1` pre-matrix and `4` post-HTTP correlation-inactive samples (`leader-b16-audit.json`, `leader-b16-gpu-correlation.json`). Every active sample and all per-case and overall statistics are identical between the original and recovered correlations.

### Impact assessment

- **Candidate recommendation without default change:** `B8` (`PII_MODEL_BATCH_SIZE=8`) delivers the highest observed throughput at `CC8` (`3.124 req/s`), `CC16` (`3.452 req/s`), and `CC32` (`4.027 req/s`), beats `B16` on mean and p95 latency at `CC2`, `CC4`, `CC8`, and `CC16`, and preserves more free VRAM (`70.262%` vs `67.789%`). `B16` has slightly lower mean latency only at `CC1` (`1.015 s` vs `1.028 s`) and `CC32` (`5.598 s` vs `5.975 s`) and a slight RPS edge at `CC4` (`2.546` vs `2.521`). `B8` is recommended as the candidate for production image validation, while `src/app/model_batching.py` keeps `DEFAULT_BATCH_SIZE = 1`.
- **Preserved boundaries and shutdown:** No API schema, authentication mode, model weights, `float32` precision, published image (`c1d9`), Git commit/push/release, or unrelated hardware resource changed. At `2026-10-29T18:57:48.974474+00:00`, independent parent management reads confirmed `status: "paused"`, `min_replica_count: 0`, `max_replica_count: 1`, `concurrent_requests_per_replica: 32`, and `replicas.list: []`. Compute for this test deployment is off (without claiming global account billing is zero); the `B16` diagnostic overlay remains configured on `envai-pii-test-0` but inactive.

### Validation steps

- Parent independently ran `python -m unittest discover -v tests`: **1187 tests passed, no skips** (`59.068 s` post-B16 in `post-b16-tests.log`; also verified in `leader-tests.log`, `post-b4-tests.log`, `post-b8-tests.log`).
- Coverage on the 4-file collector/transport delta (`leader-coverage.json`): **`866/934` statements (`92.72%`)**, `batch_experiment.py` `564/627` lines (`89.95%`, `86%` combined lines/branches), `transport.py` `302/307` lines (`98.37%`), overall combined lines/branches `90%`. Core 9-file batching package `0fcada80` remains unchanged at `550/551` (`99.82%`).
- `quality-gate-a` and `security-review-specialist-a` returned **PASS** on the new collector/transport package. `quality-gate-a` returned **PASS** on the live `B4`, `B8`, and `B16` runs (accepting `B16` with the parent read-only historical log audit while preserving the original `result.json`). No new automated core-surface security review was triggered for the live remote configuration toggles and Markdown closure.
- Parent independently recomputed all 24 latency/throughput cells, verified byte-to-GiB conversions and throughput/latency ratios with the unit converter and calculator, verified all `1608` HTTP `200` rows and canonical oracle hashes (`leader-comparison.json`), and verified file permissions (`0600` in `0700` directory `/home/lorenzo/private/tmp/envai-pii-batching-resume-20261029/`, `leader-all-evidence-manifest.json`) with zero raw credentials, request/response bodies, `dictionary_delta`, bearer tokens, or raw GPU UUIDs persisted. No ephemeral test process or container remains running.
- Final parent management reads at `2026-10-29T19:26:42.223652+00:00` again confirm paused/min0/max1/concurrency32/zero replicas and exact inactive B16 entrypoint (`leader-final-verification.json`). Both documented 24-cell tables match the verified raw statistics; actual-credential membership checks pass over 76 task files. The sole task-generated `.coverage` file was moved out of the repository into the private evidence directory, preserving its hash and leaving existing coverage files untouched.

## Update 2026-10-30: 8, 12, and 16 model copies at B8 and startup comparison

### Summary of changes

Extended the diagnostic runtime, packaging, resource guard, collector, and startup modules in a 21-file diagnostic/test package (`review-manifest.json` SHA-256 `46d02491337709447e475ebaca92e61f444bf0ae9871f638a04ffce585047a0e`, XZ archive `17216` bytes SHA-256 `015dd46695c207a36af412bafde7e96031ccce1c5b81ae5a34726f9bbe13dcdb`) while keeping the application core (`src/app/app.py`, `src/app/model_batching.py`, `tests/test_model_batching.py`), `tools/verda_model_experiment/fixture.py`, and `tools/verda_model_experiment/transport.py` byte-identical to their reviewed versions (and archiving the pre-task diagnostic baseline under `/home/lorenzo/private/tmp/envai-pii-copies-startup-20261029/source-baseline/`). Completed the live 3x6 copy-count and startup comparison across `8`, `12`, and `16` Gunicorn model copies at fixed `PII_MODEL_BATCH_SIZE=8` (`B8`) on the existing single-L40S deployment `envai-pii-test` (`copy-20261029-n8`, `copy-20261029-n12`, `copy-20261029-n16`, `402/402` validated HTTP `200` requests per copy count, `1206/1206` new measured requests total across `81` bursts and `27` groups per matrix, plus one excluded authenticated HTTP `200` warmup per matrix and zero measured HTTP replay). Recorded the results in the new [copy-count and startup report](../reports/2026-10-30-copy-count-startup.md) and updated the [Verda service guide](../../../docs/verda-service.md), [chunk batching guide](../../../docs/chunk-batching.md), and [changelog](../../../docs/CHANGELOG.md), while preserving the [previous chunk-batching plan](../plans/2026-10-28-chunk-batching.md) and [chunk-batching report](../reports/2026-10-28-chunk-batching.md) as historical records.

### Technical reasoning

- **Experimental axis and fresh `N8` control:** The previous 4x6 experiment varied `PII_MODEL_BATCH_SIZE` (`1`, `4`, `8`, `16`) at fixed `8` worker copies. To evaluate whether increasing model copies at fixed `B8` improves throughput and how much it increases startup time and memory use, this series holds `PII_MODEL_BATCH_SIZE=8`, `float32`, model v1.5.0, the `c1d9` image, the `45000`-character (`63`-chunk, `45174`-byte) fixture, and the canonical response oracle (`ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40`) fixed while varying Gunicorn workers across `N=8`, `12`, and `16`. Rather than substituting the older `8-copy / B8` row (`4.026919 req/s`), an explicitly authorized fresh `N8 / B8` control (`copy-20261029-n8`) was executed in the same series. Because the task began on `2026-10-29` and finished after midnight UTC on `2026-10-30`, the run IDs (`copy-20261029-n8`, `copy-20261029-n12`, `copy-20261029-n16`), [series plan](../plans/2026-10-29-copies-startup-comparison.md), and private evidence directory (`/home/lorenzo/private/tmp/envai-pii-copies-startup-20261029/`) intentionally retain the `2026-10-29` date prefix.
- **Packaging and runtime identity:** Because the previous 9-file `0fcada80...` manifest included `batch_package.py`, `batch_runtime.py`, and their tests, that 9-file manifest is not unchanged as a whole; only the application core (`src/app/app.py`, `src/app/model_batching.py`, `tests/test_model_batching.py`) is unchanged. The new `17216`-byte XZ archive (`015dd46695c207a36af412bafde7e96031ccce1c5b81ae5a34726f9bbe13dcdb`) uses `56` command arguments (`<=64` limit, `8` headroom) and `56` `ENVAIPI_VERDA_BATCH_ARCHIVE_*` environment carrier entries (`<=253` bytes each), merged once with the `49` older entries into `105` deployment environment entries during the corrected `N8` PATCH and left untouched for `N12` and `N16` (which required only an entrypoint PATCH without resending `env`). Every profile enforces real copy-count identity across all `N` workers and selects `min(PID)` (`240`, `241`, `240`) as the single NVML sampler owner.
- **Measured windows, performance, and resources:**
  - `N8` (`copy-20261029-n8`, pod `envai-pii-test-7cf76d48bf-v7rfm`, PIDs `240-247`, owner `240`, `2026-10-29T23:20:49.227942Z` to `23:24:01.848945Z`, `bursts.jsonl` SHA-256 `dcd13a0a6adfda34fa90f39b710a08d162111deba8c2f73a8895df4e37f7cf14`): at `CC32`, `3.861909 req/s`, mean `5.971478 s`, p95 `8.015375 s`, group elapsed sum `24.858170 s`, active GPU mean `80.33%`, memory controller mean `24.83%`, `24` active samples (`96.00%` coverage), power mean `269.98 W`. Peak VRAM `15147204608` B (`14.106934 GiB`, `70.224%` min free of `50869764096` B / `47.376160 GiB` visible GPU memory on these host nodes), kernel RAM peak `9692217344` B (`9.026581 GiB`, max current `9692209152` B, `84.437%` min free of `62277025792` B / `58 GiB`), max PIDs `108` (`62` at readiness, with finite node cgroup `pids.max = 580081` and experimental budget `512` / guard `409`), `211` NVML samples (`146` active, `65` inactive, min `18` active/cell), `836` base samples, `0` anomalies.
  - `N12` (`copy-20261029-n12`, pod `envai-pii-test-5748cbf69d-mv9dd`, PIDs `241-252`, owner `241`, `2026-10-30T00:13:06.485549Z` to `00:16:23.484341Z`, `bursts.jsonl` SHA-256 `ce08cdcafa508cd55dc71725e6ed2158c511b684c50243f604b78e36372e5484`): at `CC32`, `4.001195 req/s` (`+3.60665%` vs `N8`), mean `5.793653 s`, p95 `7.899093 s`, group elapsed sum `23.992832 s`, active GPU mean `78.87%`, memory controller mean `24.04%`, `23` active samples (`95.83%` coverage), power mean `280.18 W`. Peak VRAM `22721396736` B (`21.160950 GiB`, `55.334%` min free), kernel RAM peak `14461227008` B (`13.468067 GiB`, max current `14458363904` B, `76.784%` min free), max PIDs `149` (`99` at readiness), `209` NVML samples (`145` active, `64` inactive, min `16` active/cell), `1238` base samples, `0` anomalies.
  - `N16` (`copy-20261029-n16`, pod `envai-pii-test-888b88f44-rcd47`, PIDs `240-254, 256`, owner `240`, `2026-10-30T00:33:56.707109Z` to `00:37:11.770536Z`, `bursts.jsonl` SHA-256 `d8042db2138c96436d6759ade710453702a4e68a22ddfe1092618fd6f384ec76`): at `CC32`, `3.818058 req/s` (`-1.13547%` vs `N8`), mean `5.637245 s`, p95 `8.197978 s`, group elapsed sum `25.143670 s`, active GPU mean `71.54%`, memory controller mean `22.54%`, `26` active samples (`100.00%` coverage), power mean `267.32 W` (at `CC16`, `N16` reaches `3.726926 req/s` vs `3.675123` for `N8` and `3.602240` for `N12`). Peak VRAM `30293491712` B (`28.213013 GiB`, `40.449%` min free), kernel RAM peak `19242373120` B (`17.920856 GiB`, max current `19240988672` B, `69.104%` min free), max PIDs `191` (`131` at readiness), `214` NVML samples (`154` active, `60` inactive, min `17` active/cell), `1705` base samples, `0` anomalies.
- **Startup timings and interpretation boundaries (one observation per copy count):**
  - The primary comparable post-pull proxy uses native same-pod timestamps from Gunicorn master `Listening at` (PID `1`) to the last worker's `batch_ready` event (`first_gunicorn_listening_to_all_ready`): `15.450720 s` (`N8`), `17.542707 s` (`N12`), and `19.874904 s` (`N16`, `+4.424184 s` / `+28.63416%` vs `N8`); `first_worker_boot_to_all_ready` is `15.444970 s`, `17.537627 s`, and `19.868978 s`. These intervals include application/model initialization, CUDA initialization, the 63-chunk `B8` warmup per worker (`8` calls, sum `63`, max `8`), and the all-worker barrier, not pure weight-file loading.
  - Cross-clock `resume_accepted_to_last_ready_event` is `220.147965 s` (`N8`), `26.108766 s` (`N12`), and `26.620396 s` (`N16`; from `resume_requested`: `220.473965 s`, `26.396766 s`, `26.955396 s`, with client-provider clock offset unmeasured). Client-observed `resume_accepted_to_ready_observed` (`232.382 s`, `32.050 s`, `38.955 s`) includes log ingestion and polling latency, and `resume_accepted_to_first_valid_response` (`233.481720 s`, `33.188905 s`, `40.365413 s`) includes collector waiting before sending the excluded warmup POST (`warmup_transport`: `0.975753 s`, `0.991116 s`, `1.209247 s`).
  - `N8` recorded provider `Pulling` (`23:17:01Z`) to `Pulled` (`23:20:18Z`) = `197.0 s` (which may include verification, scheduling, and pull, not pure download bytes or cold-cache proof), whereas `N12` and `N16` recorded `Pulled` without a `Pulling` event (`provider_pull_phase: null`, `unknown_reason: "provider_pulling_unavailable"`, not zero), and `image_cache.status` is `"unknown"` (`trusted_cache_metadata_unavailable`) across all three runs. Therefore, one cannot conclude that `12` or `16` copies have faster total startup than `N8` from `26.1-26.6 s` vs `220.1 s`. Because Verda emits two `Created` and two `Started` events per pod (init/main container) without container-name disambiguation, `container_created_to_started` and `container_started_to_all_ready` are recorded as `null` (`provider_multiple_container_events` or `provider_timestamp_ambiguous`).
- **Operational disclosures:**
  - The first `N8` attempt (`n8-b8/`) sent all `105` union environment entries instead of the `56` builder carrier entries (`body_bytes: 47887`, SHA-256 `cc7e6171536a5cf55e5af3a7be760a4d69b1b581b22680fd1f1aa7d523347543`), failed pre-activation with HTTP `400` (`deployment_patch:management_http (400)`), activated zero GPUs, sent zero inference requests, and verified `paused`/`min=0`/`0` replicas at `23:08:28.050Z` (`n8-b8/final.json` falsely recorded `deployment_patch.attempted: false`; `n8-b8/api-ledger-final.json` is the authoritative record of the HTTP `400` PATCH, and `n8-b8/` is preserved).
  - The second `N8` run (`n8-b8-corrected/`) sent the exact `56` builder entries (`body_bytes: 33332`, SHA-256 `a2421aa719226fd45fe8fa8a2572ea24551f6d313754d292739bc815df32aba5`), verified the `105`-entry union readback, completed all `402/402` measured requests, and cleaned up to `paused`/`min=0`/`0` replicas at `23:25:13.326Z`. Its post-run startup parser encountered two distinct `count=1` `Created`/`Started` rows and wrote `status: "partial_only"` (`system_event_duplicate_mismatch`) in `n8-b8-corrected/startup.json` (preserved unaltered). After a bounded offline update to `startup.py` and `test_verda_startup.py` only, the parent recovered the complete startup record in read-only mode (`leader-n8-startup.json`, `leader-n8-startup-audit.json`, `leader-n8-system-metadata.json`) with zero extra GPU activations and zero HTTP replay.
  - Before `N12`, `backend-dev-b` stopped without actions to ask for redundant `dev`-branch confirmation; sequential fallback `backend-dev-c` received the task with the explicit inherited `dev` authorization and completed `N12` (`n12-b8/`, one entrypoint PATCH without `env`, one `min=1`/`resume`, `402/402` requests, one `pause`/`min=0` cleanup at `00:16:42.664Z`), followed by `N16` (`n16-b8/`, one entrypoint PATCH without `env`, one `min=1`/`resume`, `402/402` requests, one `pause`/`min=0` cleanup at `00:38:14.931Z`).

### Impact assessment

- **Candidate recommendation:** Because `12` and `16` copies yield no clear material throughput advantage at `CC32` (`+3.60665%` and `-1.13547%` vs `N8`) while substantially increasing VRAM consumption (`14.11 GiB` -> `21.16 GiB` -> `28.21 GiB`) and same-pod Gunicorn startup time (`15.451 s` -> `17.543 s` -> `19.875 s`), **`8` model copies with `PII_MODEL_BATCH_SIZE=8` (`N8 / B8`) is recommended as the candidate best resource-footprint and startup tradeoff for workloads up to `32` concurrent clients**. This is not a physical hardware maximum or an SLA.
- **Preserved defaults and shutdown state:** `src/app/model_batching.py` keeps `DEFAULT_BATCH_SIZE = 1`, the published `1.0.0-dev.7` image (`c1d9...`) remains unchanged, and no automatic profile promotion, image build/publish, Git commit/push/release, or other resource change was performed. At `2026-10-30T00:44:20.956746+00:00`, independent parent management reads (`leader-comparison.json` and `leader-n16-audit.json`) confirmed `status: "paused"`, `min_replica_count: 0`, `max_replica_count: 1`, `concurrent_requests_per_replica: 32`, `replicas.list: []`, and `entrypoint_exact: true` (`N16 / B8` inactive; compute off for this deployment without claiming zero global account billing).

### Validation steps

- Parent independently ran `python -m unittest discover -v tests`: **1233 tests passed, zero skips** (`74.308 s` post-N16 in `post-n16-tests.log`; also verified in `leader-tests.log` and `post-n12-tests.log`, up from `1231` tests before the offline startup ambiguity fix), with no weakened/skipped tests, no code comments, and no model/dataset downloads.
- Coverage on the 21-file diagnostic/test delta (`leader-delta-coverage.json`): production executable lines **`412/443` (`93.0023%`)**, test lines **`946/949` (`99.6839%`)**.
- `quality-gate-a` returned **PASS** on the current 21-file package (`46d02491337709447e475ebaca92e61f444bf0ae9871f638a04ffce585047a0e`) and **PASS** on the live `N8`, `N12`, and `N16` executions. Focused `security-review-specialist-a` returned **PASS** on the initial 21-file preparation package (`2979376b44178d5a6568c421d8a529ec86372d9282010621901e9c07fc822acf`); the subsequent code delta touched only `tools/verda_model_experiment/startup.py` and `tests/test_verda_startup.py` for offline lifecycle timestamp disambiguation without altering server runtime, archive, application core, or transport, so no new automated security review was triggered for that metric-only fix or for remote configuration toggles and Markdown updates.
- Parent independently recomputed all `1206` HTTP rows (`18` cells), mean/p95/RPS values, NVML correlations, prospective guards (`leader-n12-prospective-guard.json`, `leader-n16-prospective-guard.json`), and native startup reconstructions (`leader-n8-startup.json`, `leader-n12-startup.json` from `230` native rows, `leader-n16-startup.json` from `353` native rows across two windows). Byte-to-GiB conversions and percentage deltas were checked with the unit converter and calculator. Temporary driver scripts were removed while preserving the pre-existing Python 3.11 verification venv. For this Markdown-only documentation closure, new executable tests and coverage are N/A.
- Final parent management reads at `2026-10-30T01:09:57.158686+00:00` confirm paused/min0/max1/concurrency32/zero replicas, exact inactive N16/B8 entrypoint, and the preserved old49/new56 environment union (`leader-final-verification.json`). The 18 report cells match verified statistics; Markdown/local-link, private permission and real-credential membership checks pass over 146 task files. Collateral inspection identifies only 22 intended baseline file changes and 5 new files, with HEAD and staging unchanged.

## Update 2026-11-01: ordinary N8 and B8 image published, live validation blocked

### Summary of changes

- **Source and tests:** commit `8773c86895577c6040c2cbc6fd2438bfea7d7ef8` on `dev` (12-file package `7dc956b761e4b27100249be3bf9e10053d96286d5809b5b9127167a67a6162eb`) moves `PII_GUNICORN_WORKERS`, `PII_MODEL_BATCH_SIZE` and `PII_VERIFY_MODEL_STARTUP` into the ordinary image path and drops `--workers 1` from `Dockerfile.gpu`. Source suite `950` passed in `43.816 s`, production delta `217/235` (`92.34%`); root worktree `1246` passed (`72.839 s` post activation); private offline client `34` passed in `0.082 s`, delta `164/171`, which is not a full runtime pass.
- **Gates:** the source gate `7dc956...` passed with `quality-gate-b` (the primary DeepSeek member was known offline) and `security-review-specialist-a`. The private client got a first `FAIL` and then `PASS`, both from `quality-gate-b`. The cleanup-only `quality-gate-b` `PASS` covers the remote Verda failure-safe closure (paused, `min=0`, zero replicas), not local Podman cleanup, which had no LLM gate. The October `quality-gate-a` history above is unchanged.
- **CI and image:** Release run `41342246921` and docker-publish run `41342296083` succeeded for the source commit; digest `sha256:9d7a579b45513a0ae6de01298e7312e3f849fdef98c84ccc6238541a345c6f53`, config `sha256:9d7ffed2d5008d745321f7740feb6476a16e9261f0340f9620744e908a37aab4`, scan `0 blocker(s), 239 unfixed ignored` (not zero vulnerabilities). `main` is untouched.
- **Configuration:** ordinary N8/B8 on L40S, `min=0`, `max=1`, concurrency `16`, queue TTL `600`, `11` plain environment variables, `97` old carrier variables removed, overrides disabled, probe `5005` `/health`, no async mode, no secret in the image.

### Technical reasoning

- **Observations:** first activation resume accepted `21:27:16.279779Z`, last native ready `21:30:51.248098911Z` (PID `126`), `Listening at` to ready `11.479905 s` on the same pod, resume to last ready `214.968319 s`, cold HTTP `215.627098 s`. Second activation `22:54:02.648537Z`, ready `34.837916 s`, `Listening at` to ready `11.128448 s`, cold HTTP `35.746288 s`, PIDs `202..209`, `cuda:0`, `float32`, warmup `63` chunks in `8` calls, max `8`, tail `7`. Both cold responses carry the same wire hash, and the canonical hash `ddda56ee...` was checked directly in the second run. Pull and cache time of the first start are unknown.
- **TTL:** the conservative engineering budget of `334.968319 s` is not covered by `300 s`, which is a margin statement and not proof that `300 s` would fail. `600 s` is not an SLA.
- **Failure:** the private guard looked up `name` while the public `ReplicaInfo` schema requires `id`, `status` and `started_at`. The exact runtime payload was not persisted, so real replica churn is neither proved nor excluded. No runtime code fix was made.
- **Retracted claims:** the `cu130` versus `cu126` diagnosis is false (both images use `cu126`); the `skopeo` attribution for the Podman reset is retracted (the user reset it).
- **Protocol deviation preserved:** two earlier client attempts (`21:23:20.468` and `21:25:20.411`) performed extra `resume` actions before the first observed GPU, each followed by a confirmed pause. They are not zero-mutation preflight aborts. The client reports no GPU from them, which is reported, not assumed. Observed real activations remain `2`.

### Impact assessment

- The deployment stays `paused`, `min=0`, zero replicas. A future success must stay unpaused at `min=0`, `max=1` and reach zero naturally, with no final pause; pause remains only a failure cleanup.
- Recommended future work, under a new owner permission only: fix the private API parser to read `id`, and persist sanitized `/replicas` and `/status` snapshots before any guard fault. No automatic third GPU activation.
- Local cleanup removed only the known unused task leaf image `9b59783...` (no force, no prune); the parent verified it gone at `2026-11-01T23:14:01Z`, task temp directories absent and the old virtualenv preserved. The `20261102T0011Z` cleanup file name comes from an unverified local date projection. User containers were untouched.

### Validation steps

- Parent private proofs under `/home/lorenzo/private/tmp/envai-pii-n8-b8-image-20261101/`: `ci-image-verified.json`, `release-review-package.json`, `release-commit.json`, `configuration-parent-verified.json`, `one-activation-native-parent-audit.json`, `second-activation-parent-audit.json`, `replica-schema-parent-audit.json`.
- This documentation closure is Markdown only: tests and coverage are N/A. Corrections were checked with Markdown, local link and diff checks inside the assigned files. Nothing was committed.

## Update 2026-11-02: online attempt blocked by provider placement and capacity

### Summary of changes

The private validation client under `/home/lorenzo/private/tmp/envai-pii-n8-b8-online-20261102/` was fixed and verified offline, then two bounded activation attempts (`3` and `4`) ran against the unchanged `v1.0.0-dev.8` deployment. The online state was not achieved; the deployment was returned to `paused`, `min=0`, `max=1`, `CC16`, `TTL 600`, `0` replicas. Full evidence is in the [2026-11-02 capacity blocker report](../reports/2026-11-02-verda-online-capacity-blocker.md).

### Technical reasoning

- Pre-live gates passed: focused security review on the initial package, final `quality-gate-b` `PASS` on the corrected packages (`62` private tests, root `1246` tests). The live acceptance `quality-gate-b` is `FAIL` for missing capacity proofs.
- Attempt `4` ended with provider `unhealthy` and replica `error` at `09:50:13.084453Z`. Parent-read native events show a nodes-unavailable indication (local label `no_nodes_available`, not a formal provider code). Scheduling or placement is strongly supported; quota, GPU pool, image pull and container start are unknown.

### Impact assessment

- No claim covers global `L40S` stock, account billing or physical GPU allocation. Wait for provider recovery or an owner decision on GPU or profile; do not bypass guards, force `min=1` or change the oracle.

### Validation steps

- Markdown-only closure: tests and coverage N/A. Markdown structure, local links and `git diff --check` verified on the scoped files; nothing committed.

## Update 2026-11-02: fifth attempt passed and service left enabled

### Summary of changes

The owner explicitly requested another same-profile attempt. One resume on the frozen dev.8 image completed real startup, auth, 72 measured requests and natural scale-to-zero. The service is healthy and unpaused with zero idle replicas; no sixth attempt or new release.

### Technical reasoning

Reuse the reviewed client with only new output paths, attempt labels and current authorization. Backend-b stopped before actions on a role-classification issue; sequential backend-c executed the one existing command. No runtime or security-surface change.

### Impact assessment

Min 0/max 1, CC16 and TTL600 remain unchanged. Authenticated requests can activate the GPU again. Previous failed attempts are retained; neither cold-start timing nor future capacity is guaranteed.

### Validation steps

Parent root 1246 PASS, client 62 PASS, changed executable coverage 4/4 (100%); quality-b pre-live and final live acceptance PASS. Independent native 53+7 rows prove eight PID 202..209 and exact B8 metadata; 72 rows and both concurrency statistics recomputed. Health 200/no-store, six exact provider 404 denials, native ScaledToZero and 7.114408 s empty-snapshot gap verified. Final read at 15:35:34Z is healthy/unpaused/zero. Full evidence: [online report](../reports/2026-11-02-verda-n8-b8-online.md). Documentation-only closure tests and coverage N/A; no post-idle HTTP traffic.
