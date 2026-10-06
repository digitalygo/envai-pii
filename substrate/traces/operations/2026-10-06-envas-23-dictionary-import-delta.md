---
status: completed
created_at: 2026-10-06
files_edited:
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
supporting_docs:
  - ../../../docs/GUARDRAIL_API.md
  - ../../../docs/guardrail-openapi.yaml
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
