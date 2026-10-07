---
status: completed
created_at: 2026-10-06
updated_at: 2026-10-06
files_edited:
  - .gitignore
  - docker-compose.yml
  - src/app/app.py
  - src/app/serve.py
  - src/app/assets/
  - tests/test_api_only.py
  - tests/test_ripristino_placeholder.py
  - docs/GUARDRAIL_API.md
  - docs/guardrail-openapi.yaml
  - docs/TASSONOMIA_TAG.md
  - .dockerignore
  - Dockerfile
  - README.md
  - CLAUDE.md
  - CONTRIBUTING.md
  - THIRD_PARTY_LICENSES.md
  - docs/CHANGELOG.md
  - docs/releases/v2.0.0.md
  - .env.notarize.example
  - .github/workflows/build-windows.yml
  - .github/workflows/release.yml
  - Dockerfile.linux
  - build.spec
  - build_sidecar.spec
  - build_linux.sh
  - build_mac.sh
  - build_macos.sh
  - installer.iss
  - create_mock_model.py
  - src/app/desktop_app.py
  - scripts/plot_star_history.py
  - docs/BUILD.md
  - docs/.nojekyll
  - docs/index.html
  - docs/star_history_dark.png
  - docs/star_history_light.png
  - docs/assets/
  - tauri/
rationale:
  - Remove inherited desktop distribution and promotional targets that the internal service does not need.
  - Preserve training, preparation, evaluation, PDF functionality and successful HTTP API contracts throughout cleanup.
  - Initially retain the browser UI, then retire it under the subsequent explicit API-only user request documented below.
supporting_docs:
  - ../../../docs/GUARDRAIL_API.md
  - ../../../docs/guardrail-openapi.yaml
  - ../../../README.md
  - ../../../CLAUDE.md
  - ../../../CONTRIBUTING.md
  - ../../../THIRD_PARTY_LICENSES.md
  - 2026-10-06-envas-23-dictionary-import-delta.md
---

# Remove desktop packaging while preserving training

## Summary of changes

Removed 93 tracked desktop and promotional files from the envai-pii fork. The removed paths include the Tauri tree, PyInstaller and installer targets, native platform build scripts, the unused browser-opening desktop launcher, desktop/tag-release workflows, the landing page and its assets, star-history generation, notarization example, mock packaging model generator and desktop build guide. The directory entries in `files_edited` cover their retired tracked descendants.

Training, data generation, inspection, evaluation, all tests, the existing Flask browser UI, PDF extraction/preview/redaction and the guardrail API remain. The scientific report, its source and charts, the TARGA evaluation baseline and historical upstream release notes were deliberately kept as training and evaluation provenance. No ignored models, datasets, credentials or generated build outputs were deleted.

## Technical reasoning

The user authorized removing superfluous material while explicitly retaining training. The leader distinguished the Flask browser UI from Tauri's native shell, and explained that PDF support includes text extraction, on-screen rendering and true redaction. The cleanup retained those runtime capabilities rather than coupling desktop retirement to removal of PDF or browser functionality.

The baseline was clean `main` at `92e43d7c8154679b864f2c4486ecb50a2bd3a663`, containing the previously verified dictionary import/delta feature. Root `CONTRIBUTING.md` and `CLAUDE.md` were reviewed; repository `AGENTS.md`, `.github/CONTRIBUTING.md`, directives and expectations were absent. Discovery confirmed that no retained Python module or test consumed the removed launcher or packaging targets.

- An exact deletion manifest and SHA-256 hashes for 81 protected tracked files were captured before implementation. All protected files remained byte-identical after cleanup.
- The retained training, data preparation and inspection code, tests, requirements, model selection, API contracts, PDF modules, Flask UI assets, Compose deployment and test workflow were not changed.
- `Dockerfile` and `.dockerignore` changes are comments only. Their non-comment instruction streams remained identical. The runtime image already copied only `src/app/`; desktop and training files were not inflating it.
- `.gitignore` remained unchanged, including `.env.notarize` and old generated-artifact rules, to avoid exposing stale local credentials or build outputs after their tools were removed.
- README and current operating instructions now describe the service fork rather than native installers. The source copyright, attribution and PyMuPDF AGPL/Artifex notices were retained. Historical reports and old changelog entries are explicitly historical, not current deployment instructions.

## Impact assessment

Python and container startup, browser access, PDF workflows, API request/response contracts, training and evaluation remain available. The native desktop launcher, native installer builds and automatic upstream-style tag releases are intentionally no longer available. Existing remote releases and the upstream repository were not modified.

The README distinguishes the authenticated versioned endpoint from unauthenticated legacy routes, documents passing `PII_API_TOKEN` into the server/container environment, and does not claim that the unchanged Compose file supplies this token. The token, model weights and training data were not configured or generated during cleanup.

Some protected source comments, docstrings and ignore entries still mention the historical desktop build. They have no executable consumers and were left unchanged to keep this cleanup separate from runtime edits. They can be addressed in a later comment-only pass.

## Validation steps

Independent verification covered the combined backend and documentation output:

- Exact manifest check: all 93 expected tracked removals, with no extra deletion.
- Preservation check: all 81 protected file hashes matched, including all training sources, tests and retained runtime modules. Dockerfile instructions and ignore patterns matched the baseline.
- Before and after: `python3 -m unittest discover -v tests`, 201 tests, OK with the same 30 dependency skips.
- Real Flask/PyMuPDF verification: `/tmp/envai-pii-cleanup-verify/bin/python -m coverage run --branch --source=src/app -m unittest discover -v tests`, 201 tests, OK with five pre-existing neural-model dependency skips. All 121 guardrail tests ran. Retained guardrail module regression coverage was 96%.
- Browser restore regression: `python3 tests/test_ripristino_placeholder.py`, 14 passed, zero failed.
- PDF export regression: `/tmp/envai-pii-cleanup-verify/bin/python src/app/smoke_pdf_export.py`, 23/23 PASS.
- Documentation checks: local links resolve, headings checked outside fenced code, required fence languages, whitespace and final-newline checks pass. Training command fences in `CLAUDE.md` and prior changelog history remained unchanged.
- `git diff --check` passed; no test was removed or weakened.
- Hybrid quality judgment: `quality-gate-a`, **PASS**. The reviewer independently confirmed the manifest, protected hashes, regression evidence, documentation and attribution. Non-blocking source-comment remnants were recorded above.

The slice introduced no new runtime code; coverage of removed, deliberately retired packaging targets is not a new application-behavior coverage claim. No additional security review was invoked because the retained API, authentication, sensitive-data handling and deployment instruction streams remained byte-identical to their previously reviewed versions.

No model was downloaded, trained or used for real neural inference, and no container or local server was started. The temporary verification environment was removed after checks. Cleanup changes remain unstaged and uncommitted; no push was performed.

## Update 2026-10-06: API-only service

### Scope decision

After the desktop cleanup, the user explicitly stated that the web UI was unnecessary and that only endpoints would be used. This supersedes the UI-retention decision in the earlier sections; it does not supersede the requirements to retain training, PDF endpoints or the existing successful HTTP response contracts. Prior uncommitted desktop-cleanup changes were captured as the working baseline and preserved, without resets or automatic commits. A local workspace snapshot was recorded under the now-ignored `substrate/traces/status/` directory.

### Changes

- Removed the embedded `PAGE` HTML/CSS/JavaScript, browser entry and asset/favicon routes, runtime mascot assets and Flask's default static route.
- Retired only `tests/test_ripristino_placeholder.py`, a manual Node/DOM regression script for JavaScript removed with the page. This retirement was explicitly authorized; every existing unittest case was retained.
- Added a narrow `HTTPException` handler that returns generic JSON instead of framework HTML, retaining status, protocol headers and correct content length. `/` and unknown paths now return actual JSON 404 responses rather than the old HTML 200 fallback. Errors do not reflect request URLs or exception descriptions; successful PDF and PNG responses remain binary.
- Retained all 16 HTTP routing rules for the guardrail and legacy APIs, including health, settings/configuration, text analysis, PDF extraction/redaction, document download and page rendering. The 31 retained business functions match the pre-change ASTs after removing docstrings. Model resolution, detectors, allocation, preferences and training were not changed.
- Updated current API documentation and container comments. OpenAPI version, security, schema properties and POST response definitions are unchanged; only descriptions were adjusted for UI retirement and JSON method errors. Restore remains caller-side: no backend restore endpoint was added.

### Validation and reviews

The orchestrator independently executed the declared unittest suite and verified the API-only delta against the captured working baseline:

- Before: 201 unittest cases, OK with 30 dependency skips in the stdlib environment.
- After: 226 cases, OK with 50 dependency skips in the stdlib environment. The 25 added API-only cases include five dependency-free static checks and 20 Flask-dependent cases.
- With real Flask and PyMuPDF: 226 cases, all passed with no skips. Neural inference was mocked, not downloaded. Previously skipped application tests also executed through the new model-free app harness.
- New HTTP handler coverage: all 14 executable lines and every branch covered. Tests exercised 404/405/413/500, URL/exception-body non-reflection, `Allow`/authentication/retry headers, HEAD and OPTIONS, legacy mapping responses, guardrail seed/delta and real PDF/PNG endpoint round-trips.
- Direct PDF export smoke: 23/23 PASS.
- Structural verification: exactly six additional UI-only file deletions, all prior desktop removals preserved, all retained business functions unchanged, training and existing unittest sources byte-identical, Compose/Docker instruction streams unchanged. Only the obsolete UI PSD ignore rule was removed from `.dockerignore`; prior secret/artifact rules remain, with one new local-status ignore rule.
- Markdown/local links and YAML checks passed. The OpenAPI document matches the prior structural contract after excluding descriptions. `git diff --check` passed.
- Hybrid quality judgment: `quality-gate-a`, **PASS**. Its only advisory, em dashes in two new container comment labels, was corrected without executable changes.
- Focused security review: `security-review-specialist-a`, **PASS**, with no blocking findings. It confirmed sanitized error bodies, retained protocol headers, guardrail error-handler precedence and removal of the browser persistence/static surface. Legacy unauthenticated endpoints and cooperative model timeouts remain documented pre-existing deployment constraints, not newly closed risks.

The API-only verification environment was removed after review. No server or container was left running. All cleanup and API-only changes remain unstaged and uncommitted; no push was performed.
