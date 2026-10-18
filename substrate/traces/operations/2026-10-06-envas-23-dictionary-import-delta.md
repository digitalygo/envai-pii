---
status: completed
created_at: 2026-10-06
updated_at: 2026-10-18
files_edited:
  - src/app/guardrail_limits.py
  - tests/test_guardrail_limits.py
  - tests/test_guardrail_categories.py
  - docs/TASSONOMIA_TAG.md
  - tests/test_guardrail_timeout.py
  - src/app/guardrail_inputs.py
  - src/app/pdf_text.py
  - tests/test_guardrail_multifiles.py
  - tests/test_pdf_text_limits.py
  - tests/test_guardrail_pdf_privacy.py
  - CLAUDE.md
  - src/app/app.py
  - src/app/pii_dictionary.py
  - src/app/guardrail_api.py
  - tests/test_pii_dictionary.py
  - tests/test_guardrail_api.py
  - docs/GUARDRAIL_API.md
  - docs/guardrail-openapi.yaml
  - docs/CHANGELOG.md
  - README.md
rationale:
  - Implement the approved single-text dictionary import and delta slice of ENVAS-23 without changing legacy clients.
  - Keep caller-owned identifiers stable and sensitive dictionary state request-local.
  - Extend the same endpoint to sequential multifile requests under subsequent explicit user approval.
  - Prevent native PDF diagnostics from leaking document content or silently processing without verified privacy controls.
  - Make the analysis deadline server-configurable with a 60-second default and explicitly verify text-only multipart requests.
  - Apply the caller's category whitelist consistently to model, regex and known seed matches without consulting server preferences.
  - Raise HTTP dictionary capacity within configurable hard ceilings and validate the effective seed plus delta before success.
  - Preserve one normalized original binding across detector category changes so emitted mappings remain reusable by Envai Teams.
supporting_docs:
  - ../../../../1-1-5-envai-aaas/substrate/traces/operations/2026-10-18-durable-pii-anonymization.md
  - ../../../docs/GUARDRAIL_API.md
  - ../../../docs/guardrail-openapi.yaml
  - ../../../docs/TASSONOMIA_TAG.md
  - ../../../CONTRIBUTING.md
---

# ENVAS-23 dictionary import and delta

## Summary of changes

Added `POST /api/v1/analyses`, accepting one JSON `text` and an optional `dictionary` mapping placeholders to originals. The response contains one `results` element and only newly allocated associations in `dictionary_delta`. The user approved this route and explicitly excluded batch processing; uploads and changes to Envai AaaS were not implemented.

The contract and OpenAPI schema were documented before implementation. This operation completes the approved fork-side slice, not the whole ENVAS-23 guardrail integration. The issue title and description were read through YouTrack; no issue state, comments or fields were changed.

## Technical reasoning

- The baseline was clean, synchronized `main` at `30d6f9c675e245bc8494df959adaeaa9d8de35c7`, matching the remote default branch. Repository `AGENTS.md`, `.github/CONTRIBUTING.md`, directives, expectations and prior traces were absent. Root `CONTRIBUTING.md` and `CLAUDE.md` were reviewed.
- The stdlib-only dictionary engine validates and copies the seed, locates known originals with normalized Unicode matching and safe boundaries, preserves existing placeholders, and allocates above occupied IDs per category. Replacements use original offsets in a single pass.
- The Flask shell provides Bearer authentication through server-side `PII_API_TOKEN`, strict JSON validation, resource limits, sanitized errors, a non-blocking per-process lock and `Cache-Control: no-store`. A missing token disables only the new endpoint with HTTP 503.
- The additive application adapter reuses existing chunking, regex/checksum detection, time completion and span merging. Protected seed and placeholder intervals are excluded from detector input; unprotected gaps retain detection. Legacy routes, UI, preferences and the full `mapping` response were not changed.
- The primary backend deliverable contained a misconfigured HTTP example test. Sequential fallback corrected the fixture while preserving useful implementation progress. Two non-blocking security findings were also corrected: escaped unpaired surrogates now fail validation, and seed matching uses a bounded per-start candidate heap instead of accumulating every match. Original-span overlap ordering was preserved.

## Impact assessment

Clients must configure `PII_API_TOKEN` on the server and send the matching Bearer credential. They retain ownership of the seed and merge the returned delta with conflict validation. No dictionary is persisted by the new endpoint, and legacy anonymization preferences do not weaken its masking policy.

The 30-second budget is cooperative, beginning after bounded body reading, authentication, readiness and lock checks. It cannot interrupt an in-flight model call or bound a slow upload; internal deployment still requires worker/proxy hard timeouts. Concurrency is limited per process, not across workers. No real trained-model inference or deployment was exercised.

The existing stdlib-only CI does not execute the 23 new Flask-dependent tests. Those tests were explicitly permitted to skip only without Flask and were all executed during independent verification with real Flask. A future CI dependency decision can bring that HTTP coverage into automation without adding model weights.

## Validation steps

The orchestrator read the changed files, inspected the actual application diff and verified that it was additive. No existing tests were removed or weakened, and no files were staged or committed.

- Baseline: `python3 -m unittest discover -v tests`, 80 tests, OK with seven pre-existing dependency skips.
- Final stdlib verification: `python3 -m unittest discover -v tests`, 201 tests, OK with 30 skips, consisting of 23 Flask-dependent new tests and seven pre-existing dependency skips.
- Final Flask verification: `/tmp/envai-pii-envas23-verify/bin/python -m coverage run --branch --source=src/app -m unittest discover -v tests`, 201 tests, OK with five pre-existing neural-model dependency skips. All 121 new tests executed.
- Coverage: aggregate statement/branch coverage of the two new runtime modules was 96%; `guardrail_api.py` 94%, `pii_dictionary.py` 97%. All 22 changed executable application lines and all eight changed branches were covered.
- Independent Flask application smoke with real regex/checksum detection and an injected empty neural detector passed the documented seed-plus-email example. A second request with the merged seed returned the same placeholders and an empty delta. The new endpoint ignored legacy exclusions and irreversible preferences while `/analyze` still respected them.
- `git diff --check` passed. Documentation was checked against the implemented contract; the deadline wording was clarified following the quality advisory.
- Hybrid quality judgment: `quality-gate-a`, **PASS**. Non-blocking advisories concerned exact deadline wording, Flask tests absent from stdlib CI, and one fake-clock test coupled to internal check counts.
- Focused security review: `security-review-specialist-a`, **PASS** after corrections, with both prior findings verified closed and no blocking findings. Deployment timeout and per-process concurrency limitations remain documented.

The temporary verification environment was removed after checks. No local server or container was started or left running. Changes remain uncommitted for user review.

## Update 2026-10-07: multifile requests

### Approved extension

After committing the single-text feature and the API-only cleanup, the user explicitly requested multifile support. This supersedes the earlier no-batch restriction. The work started on clean `main` at `a3fe33946a3cc60b2eebd5eae68f7ec371de9e8e`, the default branch, with two local unpushed commits. Current root contribution and architecture instructions were read; directives, expectations and repository `AGENTS.md` remained absent. ENVAS-23 and its discussion were read again without modifying the issue.

The human contract and OpenAPI schema 0.2.0 were formalized before runtime changes. This remains a fork-side extension, not completion of the AAAS guardrail integration, provider egress protection or cross-repo smoke criteria.

### Changes and reasoning

- The same `POST /api/v1/analyses` now accepts repeated multipart `files` parts, an optional `text` field and an optional `dictionary` field containing a strict JSON object. Accepted extensions are PDF, TXT and Markdown, including `.text` and `.markdown` aliases. Results use `file_1` to `file_10` in file-part order, followed by optional `text`, and one aggregate `dictionary_delta`.
- Native Werkzeug multipart events are consumed from a bounded in-memory body. Strict UTF-8 form decoding, quoted parameter validation, count and size limits avoid permissive field replacement and default disk spooling. Uploaded names select an extractor but never serve as filesystem paths or result IDs.
- Limits are 20 MiB total multipart body, 5 MiB per file, ten files, twelve parts, 1 MiB per value field, 100000 aggregate extracted characters and 200 pages per PDF. Incoming seed limits are unchanged; they do not cap the growing working map or newly allocated delta.
- All input validation and extraction precede inference. One request-local allocator reserves IDs across every input before allocation, processes inputs sequentially, and makes newly detected originals available as known matches in later inputs. The seed is copied and immutable; no state, file cache, preview-store entry or preferences are retained by this endpoint.
- A failure invalidates the whole request without partial results. Corrupt/encrypted PDFs, empty files and PDFs without extractable text receive sanitized errors. OCR, raster protection, attachments, PDF binaries and ZIP output are outside this intake.
- JSON request fields, success shape, seed rules and limits remain compatible. Configuration, credentials, model readiness and non-blocking lock checks now happen before any body read; media type and charset are checked before choosing the body cap. Combined-invalid error precedence intentionally changes and is documented.
- The 30-second processing budget spans parsing, extraction and all inputs after the bounded read. It cannot interrupt native PDF/model operations or bound a stalled upload; deployment still needs an external hard timeout. The lock covers upload and processing, so concurrent versioned calls receive 429 rather than queueing.
- All baseline application functions/classes remain AST-identical apart from docstrings. Training, data preparation, inspection, dependency declarations, existing API-only routes, legacy successful payloads, PDF export and model resolution were preserved. No UI was restored.

### Rejected output and security closure

Independent verification rejected the primary backend deliverable despite its passing test suite: PDF content named `.txt` or `.md` bypassed the PDF page cap, duplicate disposition parameters were accepted by last-value-wins parsing, and text-only multipart incorrectly required a file extractor. Sequential bounded fallback fixed these cases without discarding useful progress. Real 201-page misnamed PDF and raw-header probes verified the corrections, and regression tests were added.

A focused security review then returned **BLOCKED** for B1: MuPDF could write a synthetic private token from malformed PDF content directly to the process stdout file descriptor and retain it in a process-global warning buffer. Python log capture did not detect this C-level output. The first correction disabled native diagnostics at startup and reset the buffer after extraction, with fresh-child file-descriptor regression tests, but re-review remained **BLOCKED** for B1-1 because unsupported or failing controls were silently tolerated.

The accepted closure validates all three native control functions once at startup, disables both displays, verifies exact boolean `False` or integer `0` readbacks, and probes the reset. Guardrail PDF parsing fails closed with 503 before opening the bytes if this capability is unavailable; JSON and ordinary text remain usable. Reset failure disables subsequent guardrail PDFs until restart. Successful extraction followed by cleanup failure returns 503; an existing 413/504/422 remains the original error. No per-request display toggles or stdout redirection are used.

The permanent native quiet also suppresses legacy native diagnostics in the same process, but legacy HTTP contracts are unchanged. Legacy PDF endpoints do not acquire the new caps or per-request reset gate. No dependency pin or new `/health` field was introduced; the existing model-readiness response remains unchanged. Buffer clearing is not a secure-memory-erasure guarantee, and native-control faults require operator recovery.

### Independently verified results

- Baseline stdlib discovery: 226 tests, OK with 50 dependency skips.
- Final `python3 -m unittest discover -v tests`: 353 tests, OK with 148 explicitly dependency-related skips.
- Final real Flask/Werkzeug/PyMuPDF run: `/tmp/envai-pii-multifiles-verify/bin/python -m coverage run --branch --source=src/app -m unittest discover -v tests`, 353 tests, all passed with no skips. Neural inference was mocked; PDF and HTTP parsing were real.
- Existing PDF export smoke: 23/23 PASS.
- Executable delta line coverage: application additions 104/108 (96.3%), guardrail HTTP shell 66/68 (97.06%), dictionary engine 85/86 (98.84%), PDF collector 45/45 (100%). New multipart input module regression coverage was 95%; aggregate runtime-module statement/branch coverage was 96%.
- Every baseline discoverable test method remains. Only two obsolete multipart-rejection expectations changed under explicit justification because multipart is now supported. No test was deleted or skipped to conceal failures.
- Real application plus actual regex/checksum detection matched the documented two-files, optional-text and seed example exactly, with shared placeholders and one delta. Cross-file reuse, first surface form, later-input ID reservation, all-or-nothing failure, malformed MIME, size/page limits and privacy-degraded SDK cases were exercised.
- Fresh child processes with real PyMuPDF verified no synthetic private marker on either stdout or stderr, disabled native flags, empty warning buffers and preserved error outcomes. Unsupported, raising and unexpected-falsy native controls were tested as fail-closed.
- Protected-file hashes, legacy function ASTs, YAML/schema consistency, documentation links and `git diff --check` passed. No training, configuration, dependency, other-repository or unintended tracked-file changes occurred.
- Hybrid quality judgment: `quality-gate-a`, **PASS**. Non-blocking advisories cover the required upload-held lock/external read timeout, the documented HTTP-token-only boundary interoperability limitation, and broad unreadable-PDF error classification.
- Final focused security re-review: `security-review-specialist-a`, **PASS**, independently confirming B1 and B1-1 closed and re-running the 24-test native privacy suite. No blocking findings remain in this delta.

The temporary verification environment was removed after review. No local server, container, real-model inference or training process was started. The multifile changes remain unstaged and uncommitted; no push was performed. Caller registry merge, authorized restoration and concurrent cross-request ID coordination remain AAAS responsibilities.

## Update 2026-10-08: configurable deadline and optional files

### Summary of changes

The user explicitly approved replacing the fixed 30-second processing budget with server environment configuration and a one-minute default. `PII_ANALYSIS_TIMEOUT_SECONDS` accepts positive finite seconds, including decimals; unset, blank, malformed, zero, negative, NaN, infinity and overflow values safely fall back to 60 seconds. The value is resolved once when constructing the request-local deadline after the bounded body read, under the existing lock, and applies to both JSON and multipart across the whole request.

Multipart `files` was already optional when a non-blank `text` was supplied. This work makes that behavior explicit in the documentation and adds core and HTTP regressions. JSON still requires `text`; multipart still rejects no-input and dictionary-only requests. Present empty or malformed uploads remain all-or-nothing errors rather than being silently ignored. No client timeout field, new response field or request-schema change was added, and schema version remains 0.2.0.

### Technical reasoning and impact

The local CPU deployment can exceed a 30-second budget on real documents. A trusted server environment setting permits tuning without changing input limits or handing resource-budget control to the caller. Finite positive validation prevents NaN or infinity from accidentally disabling the cooperative deadline. Resolving once freezes the budget across all inputs, extraction and model chunks; changing the environment during processing cannot extend or shorten that request.

The native PDF and neural calls remain non-preemptible. Raising the budget is not a hard completion guarantee, and deployment timeouts must exceed the selected budget with suitable headroom. The owned VPN deployment was rebuilt from the verified current application source and changed from application 30 to 60 seconds, with Caddy write and upstream-header timeouts raised from 60 to 120 seconds. The separate upstream port-5005 trial was left unchanged. See the [VPN environment operation](2026-10-07-envai-pii-vpn-test-environment.md) for runtime details.

### Validation steps

- Baseline: default `main` at `a3fe339`, two local commits ahead and none behind the known remote, seventeen pre-existing worktree entries. A 91-file snapshot and pre-change file copies separated the approved delta from earlier multifile work. Eight baseline files changed as intended, plus the new timeout test file; all other source, training, dependencies, legacy routes and native privacy code were preserved.
- Added 35 regressions in `tests/test_guardrail_timeout.py`: default/fallback resolution, finite positive overrides, exact and exceeded boundaries, both media arms, shared extraction/input budget, body-read exclusion, immutable request budget, client-field rejection, sanitized 504, lock release, no-store and text-only requests with or without seed/extractor.
- Nine existing fake-clock fixtures moved from 31 to 61 seconds, explicitly justified by the approved new default. Existing test names and assertions were preserved. Scoped environment patches subsequently made these fixtures independent of an operator exporting a different timeout.
- Parent independently ran the declared `python -m unittest discover -v tests` in the actual updated Python 3.11 image with an inherited `PII_ANALYSIS_TIMEOUT_SECONDS=120`: 389 tests, all passed, no skips. The full Flask/Werkzeug/PyMuPDF coverage environment also passed all 389 tests; host stdlib discovery passed with 164 dependency-related skips.
- Coverage over the runtime source delta: 15/15 executable lines, 100%; guardrail HTTP-module branch coverage was 96.25%. JSON wire schema remained unchanged, multipart `files` remained non-required, and the new text-only OpenAPI example was validated.
- Independent deployed checks passed: 23/23 new timeout/text-only checks, 39/39 existing real-model JSON/multifile/PDF checks, runtime checks with no failures, and zero credential/request/native-marker log leaks. Child-process environment overrides verified the deployed resolver without changing the model worker environment.
- Hybrid code judgment: `quality-gate-a`, **PASS**, including re-review after closing ambient-environment fixture and documentation advisories. Focused code security review: `security-review-specialist-a`, **PASS**. Runtime deployment gates also returned **PASS** independently for quality and security.
- Temporary test containers, verification environments and the temporary rollback image were removed after checks. The two requested VPN services remain running and healthy. No staging, commit, push, training or AAAS changes were performed.

## Update 2026-10-08: request-only category selection

### Summary of changes

The user approved a `categories` whitelist on both media arms of `POST /api/v1/analyses`. Missing, null, empty-list and blank-string selectors mean all 24 categories; a valid non-empty array selects only its canonical labels. Multipart supplies that array as a single UTF-8 Text field containing JSON, with a missing or blank field also selecting all. Unknown labels, invalid types, malformed JSON, duplicate form parts and more than 24 raw items return sanitized `400 invalid_request`. Valid duplicate labels are deduplicated.

This deliberately supersedes the former all-categories-only guardrail policy. The request schema version advances to 0.3.0, adding the optional field without changing the success response. Selection comes exclusively from the request, never legacy preferences, category environment variables, CLI flags or `/settings`. The thirteen-part multipart cap accommodates ten files plus `text`, `dictionary` and `categories`; other limits and the configurable 60-second processing budget are unchanged.

### Technical reasoning and impact

Filtering must occur before overlap resolution. A request-local immutable detector closure passes the active mask to the application adapter before merging model and regex candidates, so an inactive regex cannot suppress an active model span. The default/all-category path keeps the original two-argument callback and prior merge behavior; the merge algorithm and legacy application functions were not rewritten.

The engine separates the full catalog from active categories. All seed keys are still validated, copied and reserved against the full catalog, including inactive entries and existing canonical tokens across every input. Placeholder protection and counting remain full-catalog. Only active seed pairs are known matches and only active detector candidates can allocate delta pairs. Inactive seed entries cannot independently mask their originals or block a shorter active match. Request-local allocation, normalized cross-input reuse, first-surface delta values and seed immutability remain intact.

Selective anonymization intentionally leaves other categories in clear text. This is caller-selected policy, not a complete-PII-protection guarantee. If the detector classifies the same surface under a selected label, that selected detection can still replace it; inactive seed membership is not a global value exemption. Documentation includes the privacy warning and distinguishes this whitelist from legacy exclusion semantics.

### Validation steps

- A 92-file snapshot at `a3fe339` captured eighteen pre-existing worktree entries. Four runtime files changed, with one old multipart test file adjusted and a new category test suite; six documentation files describe the additive schema. Training, dependencies, native PDF privacy functions, legacy routes, preferences, `_merge` and successful legacy payloads remained unchanged.
- Added 53 category regressions covering JSON/multipart empty/default/full selection parity, strict validation, duplicate labels, maximum items, invalid selectors before extraction/inference, request and concurrent state independence, model/regex pre-merge filtering, inactive seed overlaps, full-catalog validation and counters, existing inactive token protection/counts, cross-file allocation and file-free text requests.
- Existing multipart fixtures were explicitly allowed to change from three to four parser return values and move the part-count rejection boundary from thirteen to fourteen. All other existing assertions and cases were preserved. An unapproved native-control skip in a new PDF test was removed and replaced by an assertion of the supported fixture's capability; only missing optional dependencies may skip tests.
- Parent independently ran the declared suite in the actual updated Python 3.11 image with read-only source, no network, non-root execution and an inherited timeout override: 442 tests, all passed, no skips. The full Flask/Werkzeug/PyMuPDF coverage environment passed the same 442 tests; host stdlib passed with 184 dependency-related skips.
- Runtime delta coverage measured independently: 77/77 executable changed lines, 100% across the four modules. OpenAPI 0.3.0 parsed correctly, its 24-label enum matched the real catalog, optional files and unchanged response schema were verified, and `git diff --check` passed.
- Hybrid code quality judgment: `quality-gate-a`, **PASS**. Focused code security review: `security-review-specialist-a`, **PASS**. No blocking findings remained.
- The verified source was rebuilt into the owned VPN environment. Parent independently passed 66/66 real-model category checks, the existing 39/39 live smoke and 23/23 timeout checks, runtime specification checks and log privacy checks. The new live verification script had 94% coverage including branches. Runtime quality and focused security reviews both returned **PASS**.
- A non-blocking deployment-metadata advisory was closed by refreshing the current resource record; the historical baseline audit stayed unchanged. All temporary test containers, verification environments and the unused rollback image were removed. The two requested VPN services remain running; the token and upstream trial are unchanged. No staging, commit, push or AAAS changes were made.

## Update 2026-10-18: bounded capacity and durable Teams integration

### Summary of changes

The user approved changes to both repositories and server-side encrypted dictionary recovery in Envai Teams. The fork remains stateless; Teams now owns the durable per-chat map, turn deltas and ATP integration described in the [Teams operation record](../../../../1-1-5-envai-aaas/substrate/traces/operations/2026-10-18-durable-pii-anonymization.md).

The HTTP boundary now defaults to 10000 seed entries, 4096 code points per original, 1048576 aggregate code points and an 8 MiB JSON body. Trusted server settings have hard ceilings, and multipart dictionary fields use the same body-size budget. The existing 100000-character text budget, file limits, native PDF controls and request-local ownership remain. Direct engine callers retain legacy seed defaults unless explicit limits are supplied.

### Technical reasoning and impact

Successful HTTP responses now validate the effective seed plus delta against the same bounds required by the next request. This supersedes the historical uncapped-delta behavior described above. The normalized original has one stable first binding even if the detector assigns different categories, avoiding deltas that the seed parser would subsequently reject. Blank normalized detections create no mapping.

The baseline was the existing dirty working copy at `a3fe339`, not a clean HEAD. Pre-existing multifile and category work was preserved using a separate source snapshot. Changes are on `feature/teams-pii-integration`; the earlier uncommitted work was not incidentally staged or committed. No training, dependency or UI change was introduced.

### Validation steps

- Parent independently ran all 458 tests in a cached, network-disabled container with current source mounted read-only, then the same suite with tracing active before imports. All passed without dependency skips.
- Changed executable lines: 116/116, 100%, with trace embedding and source hashes verified. The earlier incomplete post-import trace was rejected, not counted as sufficient coverage.
- The Go client exercised this actual Flask API in a private disposable fixture using a synthetic detector: seed 300, stable reuse, immutable seed, local conflict validation, direct HTTP `400 seed_conflict` and no originals in errors all passed. No real neural inference, provider or OCR call was made for these checks.
- Foundation quality and focused security reviews passed; the source slice retained manifest SHA256 `5fa8061f2290e4535edee670d6c6cda2519c5480f566c3af8721bb936d0cb972`. Subsequent Teams runtime quality and security reviews also passed.
- Owned test containers, network, volume, copied toolchain, caches and synthetic credentials were removed. The requested VPN API and proxy kept their original IDs and independently remained healthy. This upgrade was not deployed to that trial, and no push was performed.
