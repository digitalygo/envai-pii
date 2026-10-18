---
status: completed
created_at: 2026-10-07
updated_at: 2026-10-08
files_edited:
  - /home/lorenzo/.local/share/envai-pii/vpn-test/verify_categories_live.py
  - /home/lorenzo/.local/share/envai-pii/vpn-test/runtime.env
  - /home/lorenzo/.local/share/envai-pii/vpn-test/verify_timeout_live.py
  - tests/test_guardrail_multifiles.py
  - /home/lorenzo/.local/share/envai-pii/vpn-test/Containerfile
  - /home/lorenzo/.local/share/envai-pii/vpn-test/Containerfile.caddy
  - /home/lorenzo/.local/share/envai-pii/vpn-test/Caddyfile
  - /home/lorenzo/.local/share/envai-pii/vpn-test/start-env.sh
  - /home/lorenzo/.local/share/envai-pii/vpn-test/verify_baseline.py
  - /home/lorenzo/.local/share/envai-pii/vpn-test/verify_live.py
  - /home/lorenzo/.local/share/envai-pii/vpn-test/verify_runtime.py
  - /home/lorenzo/.local/share/envai-pii/vpn-test/check_logs.py
  - /home/lorenzo/.local/share/envai-pii/vpn-test/record_deployment.py
  - /home/lorenzo/.local/share/envai-pii/vpn-test/source-manifest.json
  - /home/lorenzo/.local/share/envai-pii/vpn-test/baseline-audit.json
  - /home/lorenzo/.local/share/envai-pii/vpn-test/deployment.json
  - /home/lorenzo/.local/share/envai-pii/vpn-test/server.env
rationale:
  - Start the current multifile working tree with the real model for explicitly requested remote VPN testing.
  - Isolate the fork from the upstream trial, public network and unrelated development stacks.
  - Preserve uncommitted source and keep credentials private while retaining a reproducible runtime snapshot.
  - Deploy the approved configurable 60-second analysis budget with longer proxy timeouts and verify file-free multipart requests.
  - Serve the approved request-only category whitelist from the sealed current working tree while preserving credentials and runtime isolation.
supporting_docs:
  - ../../../README.md
  - ../../../docs/GUARDRAIL_API.md
  - ../../../docs/guardrail-openapi.yaml
  - 2026-10-06-envas-23-dictionary-import-delta.md
---

# Envai-pii VPN test environment

## Summary of changes

Started the current envai-pii multifile service with the real upstream v1.5.0 model. The endpoint is `http://100.115.67.57:5006/api/v1/analyses`, bound exclusively to the host's NetBird VPN address. Anonymous `GET /health` and `/healthz` are readiness probes; every other remote path requires the configured Bearer token at the proxy, including legacy endpoints.

The user explicitly requested a running environment for remote tests, so the application and proxy remain running. The upstream Docker Rizzo trial on VPN port 5005 and all other development stacks were left intact.

## Technical reasoning

- Initial HEAD was `a3fe33946a3cc60b2eebd5eae68f7ec371de9e8e` on default branch `main`, with sixteen unstaged multifile paths from the preceding verified work. Their source was captured as a 90-path audit baseline; a Git-ignored status snapshot distinguished that work from deployment changes. No commit or push was made.
- Host `vmi3564751` has NetBird interface `wt0` at `100.115.67.57`; its public interface is separate. Port 5005 belonged to the upstream `rizzo-pii` Docker container, so a distinct fork environment uses free VPN port 5006.
- Rootless Podman was available and compatible. The existing cached Docker image and real model were copied into Podman's image storage without migrating or altering the upstream service. A derived image replaces the entire inherited application tree with the sealed current `src/app` working-tree files, including the untracked multifile intake module, and removes old UI assets. Dependencies and model weights were not upgraded or mocked.
- The backend has no published port. An isolated internal Podman network connects it to a dedicated Caddy 2.11.7 proxy. This was the latest stable Caddy release verified before selection. The proxy admin API is disabled, access/runtime request logging is discarded, and header/body/write/upstream timeouts bound HTTP phases in addition to the application's cooperative processing deadline.
- Both containers run as non-root users with read-only roots, dropped capabilities, no-new-privileges and CPU/memory limits. A private writable home volume supports legacy non-sensitive configuration; uploads and guardrail mappings remain request-local. A static backend address and `--add-host` are used because the host lacks aardvark-dns. No host package, firewall, SSH, VPN routing or unrelated proxy configuration was changed.
- Runtime configuration lives outside Git in `/home/lorenzo/.local/share/envai-pii/vpn-test`, mode 0700. The API token was generated cryptographically and saved to `server.env`, mode 0600, with secrets only. Its value is never included in this record, commands, metadata or test output. The proxy interpolates it from the environment rather than storing a literal in its configuration.

## Impact assessment

The remote test service requires the same Bearer token for every non-health path. This is a deployment-layer restriction protecting legacy APIs; it does not change application source or the existing versioned endpoint's authentication contract. The server runs on CPU with two backend CPU units and a 4 GiB memory limit, alongside the unchanged upstream trial.

Managed resources are:

- Backend: `envai-pii-vpn-api`, image `localhost/envai-pii-vpn:multifiles`, UID 10001, internal port 5005 only.
- Proxy: `envai-pii-vpn-proxy`, image `localhost/envai-pii-vpn-caddy:2.11.7`, UID 65534, only published binding `100.115.67.57:5006`.
- Network: `envai-pii-vpn-net`, internal, with backend address `10.89.0.10`.
- Home volume: `envai-pii-vpn-home`, private and writable by UID 10001.

The launcher refuses unrelated same-named resources, leaves running managed containers untouched and propagates failed starts. Persistent source validation checks the exact twelve runtime files and aggregate against `source-manifest.json`; source mismatch requires a resnapshot/rebuild. Historical Git/audit metadata is optional and persistent, so later commits, documentation/test changes or `/tmp` cleanup do not block restarting an unchanged runtime image.

To stop only this environment, use `podman stop envai-pii-vpn-proxy envai-pii-vpn-api`. To start it again, run `/home/lorenzo/.local/share/envai-pii/vpn-test/start-env.sh`. The token file is readable by the host owner over an authenticated SSH session, not served by HTTP.

## Validation steps

Independent orchestration checks, rather than only subagent reports, verified:

- Current source hashes in the image match the twelve sealed working-tree application files. Real model weights are present, model version is 1.5.0, `/health` reports CPU and `model_loaded: true`, and the native PDF capability succeeds on real requests.
- The declared unittest command ran inside a disposable, network-isolated, read-only container using the deployed Python 3.11 runtime. It exposed one test fixture that conflated valid non-object JSON with parser recursion limits: Python 3.11 returned `invalid_request` where the fixture expected `invalid_seed`. A delegated, explicitly justified test-only correction uses a shallow nested array for the shape case and adds a deterministic recursion-error case verifying error code, lock release and no inference. Runtime source was unchanged.
- Final declared suite: 354 tests, all passed, no skips. This is one additional portability regression over the prior 353-case suite. All application behavior retained the prior multifile coverage and reviews.
- Independent real-model live checks: 39/39 PASS, covering authentication, token-case handling, JSON seed reuse, actual inference, combined TXT/Markdown/PDF/text multipart processing, shared delta, PDF magic under Markdown, scanned-PDF rejection, native diagnostic marker handling, API-only root, legacy proxy protection and no-store.
- Runtime checks passed for rootless execution, UID/capabilities, read-only mounts, CPU/memory limits, restart policy, health checks, private secret permissions, source/image hashes, internal network, no backend publication and absence of public/IPv6/admin listeners.
- Actual process logs contained no token, synthetic private marker, original test identity, uploaded filename, authorization header or request URI. Credentials were absent from process arguments and non-secret runtime state files.
- Original 90-path source audit: 89 remained byte-identical; only the authorized portable-test fixture changed. HEAD and the sixteen-entry dirty worktree were preserved; no staging or push occurred. The upstream Docker trial retained its original container identity and remained healthy.
- Launcher idempotence and sealed-manifest failure cases were verified without stopping either live service. Temporary test/build containers and the redundant exported base-image archive were removed.
- Hybrid quality judgment: `quality-gate-a`, **PASS**. Non-blocking advisories concern future token-character safety, rebuild-context freshness and phase-based timeout interpretation.
- Focused deployment security review: `security-review-specialist-a`, **PASS**, confirming VPN-only publication, blanket proxy authentication, internal backend isolation, secret handling, log privacy and no collateral changes.

The current token is nonempty and URL-safe, so the proxy regex interpolation is literal for this deployment. A future manual token replacement must preserve that constraint and must not be empty. The proxy timeouts bound phases, not one universal total; native model/PDF calls cannot be preempted cooperatively. Artificially slow-client/native timeout paths were not stress-tested against the user environment. Reachability was verified from the host through its VPN address, not from a second NetBird peer; the user's VPN ACL/routing still needs the remote client trial.

The two requested services remain healthy and running. No real user documents were used in verification, and no unrelated service was stopped or modified.

## Update 2026-10-08: deploy the configurable analysis budget

### Summary of changes

Rebuilt the owned backend from the current verified working tree and deployed `PII_ANALYSIS_TIMEOUT_SECONDS=60` using a separate non-secret `runtime.env`. Caddy's write timeout and both upstream-header timeouts increased to 120 seconds. The URL and existing token are unchanged; text-only multipart requests work without any `files` part.

### Technical reasoning and impact

The application now defaults to 60 seconds and accepts a trusted server override. The former 60-second proxy window needed additional headroom rather than racing the new application default. The current 120-second proxy setting is a finite hard backstop, not a guarantee that native PDF or model work completes: cooperative checks cannot interrupt such calls. Further application-budget increases require coordinated proxy adjustment.

The source context was refreshed and checked before building. Its twelve files, working-tree hashes and image contents match the new sealed aggregate `56d367d991aa9db648aecdbe9d320b7f3775ee70e0f37551cf780191c3e82504`. The launcher now validates build-context hashes and exact file membership before a rebuild, and uses an explicit internal network subnet/gateway to preserve the backend's static address.

Only the two managed containers and their owned internal network were replaced after checking ownership. The private home volume, credentials, Caddy image, real v1.5.0 model weights, SDK versions, users, capability restrictions, resource limits and VPN-only publication were preserved. `server.env` bytes were unchanged and its secret was not copied into audit artifacts. Historical baseline provenance remains historical rather than being silently rewritten.

Current managed container identities are backend `89af02ba2c22bb984b713ba21a8920b8700b5caccd3316a2def47259651c4f08` and proxy `61f816052d47eab7c2f337e63d11575df3d75d47c8c34f2516385905695feee1`. Backend publication remains empty; proxy publication remains only `100.115.67.57:5006`. The upstream Docker container `211c94f13b47` on VPN port 5005 stayed running and healthy throughout.

### Validation steps

- Parent reran the declared 389-test suite in the updated deployed Python 3.11 image, network-isolated with read-only source, including an inherited operator timeout of 120 seconds: all passed, no skips.
- Parent reran 23/23 new live checks for deployed resolver default, actual inherited child override, unchanged worker environment, safe finite-value policy, deadline boundaries, rejection of client timeout fields, text-only real inference with and without an organization seed, dictionary-only rejection and strict corrupt-PDF errors.
- Parent reran the 39/39 existing real-model JSON/multifile/PDF smoke, runtime specification checks and log-leak checks: all passed. No real customer documents or artificially slow model requests were used.
- New verification-script coverage was 86% including branches. The installed build-context validator was independently extracted verbatim and tested with pristine, missing, hash-mismatched, extra-file and corrupted-aggregate cases; all outcomes matched expectations, with 33/34 executable lines covered. Temporary synthetic contexts contained no credentials and were removed.
- Bash syntax and Caddy validation passed using a dummy validation token, never the real credential. Comment-only follow-up corrected an overclaim about proxy preemption without altering configuration tokens or restarting the service.
- Runtime hybrid quality judgment: `quality-gate-a`, **PASS**. Focused runtime security review: `security-review-specialist-a`, **PASS**, independently checking isolation, blanket proxy authentication, secret permissions, unchanged token, absence of secret copies in artifacts and no collateral changes.
- Only the current application, proxy and required cached images remain. Temporary verification containers/environments and the accepted deployment's temporary rollback image were removed. Pre-update non-secret audit artifacts remain available.

The environment is intentionally left running for the user's VPN tests. No commit or push was made. The application remains on CPU; documents exceeding the chosen processing budget can still receive `deadline_exceeded`, and a remote client's VPN ACL/routing is outside the host-side verification.

## Update 2026-10-08: deploy request-only categories

### Summary of changes

Rebuilt the owned backend to serve schema 0.3.0 category selection from the verified working tree. Added `verify_categories_live.py` for small synthetic JSON and multipart trials. The API URL, real model, existing token, 60-second runtime budget and 120-second proxy windows are unchanged.

### Technical reasoning and impact

The twelve-file source seal now has aggregate `2bf9f034b2773261bd0f96f2af27d00c1fcdd226fc0aef67a02b0dc39265595a`, matching the worktree, build context, image and managed resource labels. Backend image is `a9d7aca2ef5fdbd7f20ea0cacc06d154071b81963460cd8676c5fc0207758fbe`; current backend container is `e7b7be1530a9f27f5df3f28ae82cf204fa24525c0f4d9d263e47324d697f7a53`, proxy container `3acb9d9db1136262a30340a3338c9fc8dc819afd973b176402b1135ca34d3513`. The proxy image, SDK versions and v1.5.0 model weights remain unchanged.

Only the owned services and internal network were replaced to refresh source labels. The private home volume and token were preserved, backend ports remain unpublished, and only VPN `100.115.67.57:5006` is published by the proxy. Parent byte comparisons confirmed unchanged Caddy configuration, non-secret runtime environment, launcher and Containerfiles. No category selection was introduced through environment variables or stored preferences.

The current `deployment.json` was refreshed after a quality advisory identified stale pre-category identities. `baseline-audit.json` still describes the original historical state and was not rewritten. The unused pre-category rollback image was removed after acceptance. Read-only metadata/prose cleanup did not restart or alter either healthy service.

### Validation steps

- Parent reran the declared suite in the updated image: 442 tests, all passed, no skips.
- Parent reran 66/66 real-model category checks, 39/39 original JSON/multifile/PDF smoke checks and 23/23 timeout/file-free-text checks, all passed. Category trials cover selected-only replacement, inactive seed originals, empty/default/full parity, regex categories, full-catalog reserved IDs and counts, repeated request isolation, mixed files and optional text, the thirteen-part request shape, malformed selectors, full seed validation and native PDF privacy.
- Runtime/source/bind/permission checks passed and logs contained no credential, private native marker, synthetic original or request-header leaks. New live-script coverage was 94% including branches.
- Runtime hybrid quality judgment: `quality-gate-a`, **PASS**; focused runtime security review: `security-review-specialist-a`, **PASS**. The only informational metadata advisory was subsequently closed.
- `Caddyfile`, `runtime.env`, launcher, Containerfiles, credentials, isolation and upstream Docker container `211c94f13b47` were preserved. Temporary containers, verification environments and the unused rollback image were removed.

The requested environment remains healthy and running for remote VPN trials. A selected subset intentionally leaves other categories in clear text. No real user documents, prolonged timeout stress, global configuration changes, staging, commit or push were used.
