# Intra-analysis chunk batching for the guardrail API

This guide describes the server-side chunk batching configuration (`PII_MODEL_BATCH_SIZE`) for the `POST /api/v1/analyses` guardrail endpoint, its execution and deadline boundaries, and the current image and Verda GPU comparison status. The wire contract remains schema version `0.4.0` with no request or response schema changes; see [Guardrail API contract](GUARDRAIL_API.md) and [guardrail-openapi.yaml](guardrail-openapi.yaml).

## Latest verification and shutdown state

**Current state (`2026-11-02`, attempt 5):** the ordinary N8/B8 deployment passed live acceptance: eight CUDA/float32 workers, canonical cold response, health/auth checks and 72/72 valid CC8/CC16 requests. Natural scale-to-zero was observed; the service remains healthy and unpaused at min 0/max 1, CC16 and TTL600, with zero idle replicas. Source and `v1.0.0-dev.8` are unchanged. See the [successful deployment report](../substrate/traces/reports/2026-11-02-verda-n8-b8-online.md).

**Historical state (verified at `2026-11-01T23:06:00.268201+00:00`): ordinary `v1.0.0-dev.8` (`N8 / B8`) image published and configured on `envai-pii-test`, cold start and 8-worker native readiness proven, full live rollout validation partial/blocked at `auth_pre_positive`, deployment failure-safe `paused` with `min_replica_count=0` and zero active replicas.**

On `2026-11-01`, the server-side chunk batching adapter (`src/app/model_batching.py` and `src/app/app.py`), configurable Gunicorn worker count (`src/app/gunicorn_config.py`, `PII_GUNICORN_WORKERS` bounded `1..8`, default `1`, `Dockerfile.gpu` `--workers 1` CLI flag removed), and opt-in per-worker startup warmup verification (`src/app/gpu_worker_startup.py`, `PII_VERIFY_MODEL_STARTUP=1`) were committed to `dev` (`8773c86895577c6040c2cbc6fd2438bfea7d7ef8`, 12-file source package `7dc956b761e4b27100249be3bf9e10053d96286d5809b5b9127167a67a6162eb`, `950` release-tree tests passing in `43.816 s` and `1246` full-worktree tests passing with zero skips, `217/235` = `92.34%` production delta coverage and `680/691` = `98.41%` test delta coverage) and published as prerelease [`v1.0.0-dev.8`](https://github.com/digitalygo/envai-pii/releases/tag/v1.0.0-dev.8) (`ghcr.io/digitalygo/envai-pii@sha256:9d7a579b45513a0ae6de01298e7312e3f849fdef98c84ccc6238541a345c6f53`, config `sha256:9d7ffed2d5008d745321f7740feb6476a16e9261f0340f9620744e908a37aab4`, [Release 41342246921](https://github.com/digitalygo/envai-pii/actions/runs/41342246921), [docker-publish 41342296083](https://github.com/digitalygo/envai-pii/actions/runs/41342296083), remote Trivy gate `0 blocker(s), 239 unfixed ignored`). On `envai-pii-test` (`envai-pii-test-0`), the historical `N16 / B8` diagnostic overlay and all `97` `ENVAIPI_VERDA_*_ARCHIVE_*` carrier variables were removed and replaced by the ordinary `1.0.0-dev.8` image with `entrypoint_overrides.enabled=false`, `11` plain environment variables (`PII_AUTH_MODE=upstream`, `PII_ANALYSIS_TIMEOUT_SECONDS=60`, `PII_GUNICORN_WORKERS=8`, `PII_MODEL_BATCH_SIZE=8`, `PII_VERIFY_MODEL_STARTUP=1`, `PII_MAX_CONCURRENT_ANALYSES=16`, `PII_MAX_QUEUED_ANALYSES=32`, `PII_QUEUE_TIMEOUT_SECONDS=30`, `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `TOKENIZERS_PARALLELISM=false`), and scaling `min_replica_count=0`, `max_replica_count=1`, `concurrent_requests_per_replica=16`, `queue_message_ttl_seconds=600`.

During the second and final user-authorized GPU activation (`2026-11-01T22:54:02.648537Z`, pod `envai-pii-test-5c77d7d87d-fc5n6`), all `8` workers (`PID 202..209`) emitted native `PII_WORKER_READY` (`cuda:0`, `float32`, `parameter_bytes=1230259380`, `buffer_bytes=512`, `model_batch_size=8`, `63` chunks in `8` calls with max batch `8` and tail `7`; `11.128448 s` from Gunicorn `Listening at` to all 8 ready, `34.837916 s` from resume accepted to all 8 ready), and the cold `POST /api/v1/analyses` request (`35.746288 s`) returned HTTP `200` (`45746` wire bytes, wire SHA-256 `b9b5b91fe4a2731a6b6a7cf70382f5b3ffa30af7ecc6a5ac8169fa9f01500651`) with exact canonical JSON SHA-256 `ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40` (matching the first activation's wire bytes after correcting an initial client bug that had compared raw wire SHA-256 against the canonical JSON SHA-256; an intermediate subagent claim that `1.0.0-dev.7` used `cu130` while `1.0.0-dev.8` used `cu126` is false and rejected, as both images use `torch==2.13.0+cu126`). At `22:54:45.239459Z`, the private client stopped at `auth_pre_positive` (`pod_zero_unknown_or_churn`) before any post-cold `/health` or authentication probes (`0` completed), before the `CC8`/`CC16` benchmark bursts (`0/72` completed, so new `CC16` ordinary-image latency/RPS metrics are `N/A`), and before natural idle scale-to-zero could be observed: the client's `running_replica_cohort` check required `entry["name"]` on `GET /v1/container-deployments/{name}/replicas`, whereas Verda's official OpenAPI `ReplicaInfo` schema defines `required: ["id", "status", "started_at"]` with no `name` property (because the raw `/replicas` payload at `22:54:45.239Z` was not persisted, the exact instant replica payload is unverified). Failure-safe cleanup (`POST /pause` + `PATCH /scaling` `min=0`) confirmed `status: "paused"` and `replicas.list=[]` at `22:55:17.079104Z` and in the independent parent read at `23:06:00.268201+00:00` (compute off for this deployment without claiming zero account-wide billing; forced failure-safe pause is not proof of natural scale-to-zero). See the [2026-11-01 ordinary N8/B8 rollout report](../substrate/traces/reports/2026-11-01-verda-n8-b8-ordinary-image-rollout.md), the [2026-11-01 rollout plan](../substrate/traces/plans/2026-11-01-verda-n8-b8-image-scale-to-zero.md), and [gpu-worker-startup.md](gpu-worker-startup.md).

### Historical diagnostic overlay comparisons (2026-10-28 to 2026-10-30, `concurrent_requests_per_replica=32`)

In the earlier diagnostic overlay experiments on `1.0.0-dev.7` (`c1d9...`) at `concurrent_requests_per_replica=32`, all four batch sizes (`1`, `4`, `8`, `16`) completed the 6-level concurrency matrix (`1`, `2`, `4`, `8`, `16`, `32`) on the single-L40S Verda test deployment (`envai-pii-test`) with eight Gunicorn worker copies in `float32`: `402/402` validated HTTP `200` responses per batch (`1206` new measured requests across `B4`, `B8`, and `B16` plus the `402` preserved historical `B1` requests, for `1608` comparable HTTP rows across `81` bursts and `27` groups per batch, plus one excluded authenticated warmup request per matrix), all matching the exact request body (`45174` bytes, `63` chunks) and canonical response oracle (`ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40`). `B1` was not replayed.

At client concurrency `32`, mean latency dropped from `10.872464 s` (`B1`, p95 `14.007766 s`, `2.253740 req/s`) to `6.630575 s` (`B4`, p95 `9.369125 s`, `3.392860 req/s`), `5.974584 s` (`B8`, `-45.05%` vs `B1`, p95 `8.247637 s`, `4.026919 req/s`, a `1.78677x` or `+78.68%` throughput gain), and `5.597851 s` (`B16`, `-48.51%` vs `B1`, p95 `8.063148 s`, `3.919794 req/s`). **`PII_MODEL_BATCH_SIZE=8` (`B8`) was selected as the candidate for ordinary image validation**, delivering the highest observed throughput at `CC8`, `CC16`, and `CC32` with lower mean/p95 latency than `B16` from `CC2` through `CC16` and wider free VRAM headroom (`70.262%` vs `67.789%`).

A follow-up 3x6 copy-count and startup series at fixed `PII_MODEL_BATCH_SIZE=8` (`B8`) (`copy-20261029-n8`, `copy-20261029-n12`, `copy-20261029-n16`, `402/402` validated HTTP `200` responses per copy count, `1206/1206` new measured requests total, zero replay, with a fresh `N8` control rather than reusing the `4.026919 req/s` batch-series row) tested `8`, `12`, and `16` Gunicorn model copies on the same single-L40S deployment: at `CC32`, throughput was `3.861909 req/s` (`N8`, mean `5.971478 s`, p95 `8.015375 s`), `4.001195 req/s` (`N12`, `+3.60665%` vs `N8`, mean `5.793653 s`, p95 `7.899093 s`), and `3.818058 req/s` (`N16`, `-1.13547%` vs `N8`, mean `5.637245 s`, p95 `8.197978 s`), while same-pod Gunicorn readiness (`first_gunicorn_listening_to_all_ready`) grew from `15.450720 s` (`N8`) to `17.542707 s` (`N12`) and `19.874904 s` (`N16`, `+4.424184 s` / `+28.63416%`) and peak VRAM grew from `14.106934 GiB` (`70.224%` min free of `47.376160 GiB`) to `21.160950 GiB` (`55.334%` min free) and `28.213013 GiB` (`40.449%` min free). **`8` model copies with `PII_MODEL_BATCH_SIZE=8` (`N8 / B8`) was selected as the candidate resource-footprint and startup tradeoff**, while the source default remains `1`. Those historical `CC32` diagnostic-overlay tables are preserved below and must not be quoted as benchmark measurements of the `2026-11-01` `CC16` ordinary image rollout. See the [copy-count and startup report](../substrate/traces/reports/2026-10-30-copy-count-startup.md), the [copy-count and startup plan](../substrate/traces/plans/2026-10-29-copies-startup-comparison.md), and the [historical chunk batching report](../substrate/traces/reports/2026-10-28-chunk-batching.md).

## Configuration

| Variable | Supported values | Default and fallback | Scope |
|---|---|---|---|
| `PII_MODEL_BATCH_SIZE` | `1`, `4`, `8`, `16` | `1` | Server startup only (`POST /api/v1/analyses` model adapter) |

- `src/app/model_batching.py` reads `PII_MODEL_BATCH_SIZE` once when `src/app/app.py` starts, strips surrounding whitespace, and matches canonical string values `"1"`, `"4"`, `"8"`, or `"16"`.
- Unset, blank, non-string, boolean, or unsupported values fall back safely to `1`.
- Without the environment variable, both the helper default (`model_batching.DEFAULT_BATCH_SIZE`) and the application startup setting (`app.MODEL_BATCH_SIZE`) are `1`. With a valid value, `app.MODEL_BATCH_SIZE` is set at startup to `4`, `8`, or `16`.
- The setting is server-only and frozen for the lifetime of the process. No request field, header, or query parameter can set or override it.

Example runtime environment configuration on a checkout or image that contains `src/app/model_batching.py` (do not include secret values in command lines):

```bash
export PII_MODEL_BATCH_SIZE=4
export PII_ANALYSIS_TIMEOUT_SECONDS=60
```

## Scope and isolation boundaries

- Chunk batching applies only to the `POST /api/v1/analyses` detector (`_guardrail_detect`). Legacy routes (`/analyze`, `/pdf`, `/pdf/preview`, `/preview`, `/settings`, `/health`) keep their existing `detect_model` path unchanged.
- Grouping stays strictly inside a single unprotected text gap of a single input within one request.
- Chunks are never batched across requests, across multipart files or inputs, or across seed-protected or placeholder-protected gaps.
- Seed normalization, seed protection, category whitelisting (`categories` filtered before `_merge`), deterministic overlap resolution, and sequential placeholder ID allocation across inputs remain unchanged.
- With `PII_MODEL_BATCH_SIZE=1`, the adapter keeps the singleton call path: one `[chunk]` per `MODEL_LANE.run` call without passing `batch_size`, preserving singleton compatibility.
- With `PII_MODEL_BATCH_SIZE` set to `4`, `8`, or `16`, consecutive chunks of the same unprotected gap are grouped in input order (up to `batch_size` chunks, with a smaller tail group when `len(chunks)` is not a multiple of `batch_size`) and passed to `MODEL_LANE.run(model, inputs, check_deadline=check_deadline, batch_size=MODEL_BATCH_SIZE)`.
- Batched pipeline outputs are validated fail-closed by `normalize_batch_results`: the pipeline must return a `list` or `tuple` with exactly one nested row of entity mappings per input chunk, finite scores, non-empty string labels, and integer offsets within each chunk (`0 <= start < end <= len(chunk)`). Any cardinality mismatch or malformed entity raises `ModelBatchResultError`, which fails the whole analysis with the generic `500` `internal_error` response without partial output or PII leakage.

## Cooperative deadline and native lane behavior

- The processing budget (`PII_ANALYSIS_TIMEOUT_SECONDS`, default `60` seconds) is unchanged and is not automatically increased when batching is enabled.
- The cooperative deadline is checked before each chunk group is submitted to `MODEL_LANE`, while waiting to acquire `MODEL_LANE` (polling every `0.05` seconds), immediately before the owner thread invokes the pipeline, and immediately after `MODEL_LANE.run` returns.
- Time spent waiting for `MODEL_LANE` counts toward the request's processing budget and can abort the wait with `504` `deadline_exceeded` before the native call starts.
- Once a chunk group is running inside the native pipeline on `MODEL_LANE`, the forward pass is not interruptible. Larger batch sizes (`4`, `8`, `16`) hold `MODEL_LANE` for a multi-chunk group at once, which makes cooperative deadline checks coarser and can increase per-call lane hold time, peer wait time, and peak memory use.

## Static chunk group counts

On the 6252-word synthetic benchmark fixture (`MAX_WORDS=120`, `OVERLAP=20`, step `100`), `chunk_text` produces `63` chunks (`62` chunks of `120` words and `1` tail chunk of `52` words). For a single unprotected gap covering that fixture, the static pipeline invocation counts are:

| `PII_MODEL_BATCH_SIZE` | Pipeline invocations for 63 chunks | Group breakdown |
|---:|---:|---|
| `1` | `63` | `63` singleton calls |
| `4` | `16` | `15` groups of `4` plus `1` tail group of `3` |
| `8` | `8` | `7` groups of `8` plus `1` tail group of `7` |
| `16` | `4` | `3` groups of `16` plus `1` tail group of `15` |

These figures are static call counts from the [chunk batching inspection](../substrate/traces/research/2026-10-28-chunk-batching-inspection.md), not measured GPU speedups.

## Container image requirement and Verda comparison status

- **Current published image (`v1.0.0-dev.8`, `2026-11-01`):** `src/app/model_batching.py`, the updated `_guardrail_detect` in `src/app/app.py`, `src/app/gunicorn_config.py` (`PII_GUNICORN_WORKERS`), `src/app/gpu_worker_startup.py` (`PII_VERIFY_MODEL_STARTUP`), and `Dockerfile.gpu` without `--workers 1` are now committed on `dev` (`8773c86895577c6040c2cbc6fd2438bfea7d7ef8`) and published in `ghcr.io/digitalygo/envai-pii@sha256:9d7a579b45513a0ae6de01298e7312e3f849fdef98c84ccc6238541a345c6f53` (`1.0.0-dev.8`, config `sha256:9d7ffed2d5008d745321f7740feb6476a16e9261f0340f9620744e908a37aab4`). The image bakes all `20` ordinary `src/app/*.py` files (with `DEFAULT_BATCH_SIZE = 1` and default `1` Gunicorn worker) and contains no `tools/verda_model_experiment/` diagnostic overlay code. Both `1.0.0-dev.7` and `1.0.0-dev.8` use `torch==2.13.0+cu126`.
- **Current Verda deployment configuration (`envai-pii-test`):** updated on `2026-11-01` to the ordinary `1.0.0-dev.8` image with `entrypoint_overrides.enabled=false`, all `97` `ENVAIPI_VERDA_*_ARCHIVE_*` carrier variables deleted, `11` plain environment variables (`PII_GUNICORN_WORKERS=8`, `PII_MODEL_BATCH_SIZE=8`, `PII_VERIFY_MODEL_STARTUP=1`, `PII_AUTH_MODE=upstream`, `PII_ANALYSIS_TIMEOUT_SECONDS=60`, `PII_MAX_CONCURRENT_ANALYSES=16`, `PII_MAX_QUEUED_ANALYSES=32`, `PII_QUEUE_TIMEOUT_SECONDS=30`, `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `TOKENIZERS_PARALLELISM=false`), and scaling `min=0`, `max=1`, `concurrent_requests_per_replica=16`, `queue_message_ttl_seconds=600`. Live validation on `2026-11-01` verified all `8` worker `PII_WORKER_READY` events (`PID 202..209`) and the cold `POST /api/v1/analyses` response (`35.746288 s`, exact canonical oracle `ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40`), then stopped at `auth_pre_positive` (`pod_zero_unknown_or_churn`) before post-cold `/health`/auth checks, `CC8`/`CC16` bursts (`0/72`), and natural scale-to-zero, leaving the deployment in failure-safe `paused` state with `min_replica_count=0` and `0` active replicas (`2026-11-01T23:06:00.268201+00:00`). See the [2026-11-01 ordinary N8/B8 rollout report](../substrate/traces/reports/2026-11-01-verda-n8-b8-ordinary-image-rollout.md).
- **Older images (`1.0.0-dev.7` and earlier, historical):** setting `PII_MODEL_BATCH_SIZE` or `PII_GUNICORN_WORKERS` on `ghcr.io/digitalygo/envai-pii@sha256:c1d9d9c089047f7c1e4b7b0815e91a12cd810c963ddb58ba1f0da1233e961714` (`1.0.0-dev.7`) alone has no effect, because `1.0.0-dev.7` predates `src/app/model_batching.py`, `src/app/gpu_worker_startup.py`, and the `Dockerfile.gpu` `CMD` update.
- **Historical diagnostic overlay harness (2026-10-28 to 2026-10-30, no longer configured on `envai-pii-test`):** during the pre-release comparisons on `1.0.0-dev.7`, the application core (`src/app/app.py`, `src/app/model_batching.py`, `tests/test_model_batching.py`), `tools/verda_model_experiment/fixture.py`, and `tools/verda_model_experiment/transport.py` (`base_app_sha256` `b0ec5163cd0d9eee05922d4b80718eb26abc762b0612935e1f1ad8275dc3848e`, `helper_sha256` `31a9d653891e401e86f2c110311bba2417dee5c2450c4081c55bee88e328424d`, `detector_source_sha256` `1a0f57a3e4563e8f66b245d38db175f5c368238a53334176c4cd49045e16477e`) were tested via an uncommitted 21-file diagnostic/test package (`46d02491337709447e475ebaca92e61f444bf0ae9871f638a04ffce585047a0e`, XZ archive `17216` bytes SHA-256 `015dd46695c207a36af412bafde7e96031ccce1c5b81ae5a34726f9bbe13dcdb`, `56` command arguments and `56` `ENVAIPI_VERDA_BATCH_ARCHIVE_*` environment carrier variables `<=253` bytes each; the earlier 9-file `0fcada80...` manifest is archived privately as historical baseline). At that 2026-10-30 checkpoint, the repository suite passed 1233 tests with zero skips (`74.308 s` post-N16), with `412/443` (`93.0023%`) production executable delta coverage and `946/949` (`99.6839%`) test delta coverage on the 21-file package, `quality-gate-a` PASS, and `security-review-specialist-a` PASS on `2979376b44178d5a6568c421d8a529ec86372d9282010621901e9c07fc822acf`). That `N16 / B8` diagnostic overlay was removed from `envai-pii-test` on `2026-11-01` (with a mode-`0600` rollback snapshot preserved privately). Full details and the 18-cell `N8`/`N12`/`N16` table are in the [copy-count and startup report](../substrate/traces/reports/2026-10-30-copy-count-startup.md); the historical 4x6 batch-size comparison (`B1`, `B4`, `B8`, `B16` at `8` copies) is retained below.

### Measured L40S comparison across batch sizes 1, 4, 8, and 16

Measured windows (UTC):

- `B1` (historical, preserved without replay): `2026-10-28T18:37:31.379614Z` to `18:42:29.808810Z`
- `B4`: `2026-10-29T16:41:46.700559Z` to `16:46:02.938611Z`
- `B8`: `2026-10-29T17:44:44.862892Z` to `17:48:39.565890Z`
- `B16`: `2026-10-29T18:45:55.480513Z` to `18:49:57.710973Z`

Per-cell latency, throughput, and NVML GPU metrics (`B1` per-cell memory-controller percentages and local NVML JSONL were not archived in the historical run and are marked `n/a`):

| Batch | Concurrency | Successes | Mean (s) | P95 (s) | Requests/s | GPU mean (%) | Mem ctrl mean (%) | Active samples | 1 Hz coverage (%) | Power mean (W) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `1` | `1` | `30/30` | `1.823119` | `1.852424` | `0.548491` | `16.11` | `n/a` | `54` | `n/a` | `153.00` |
| `1` | `2` | `36/36` | `1.938944` | `2.028758` | `1.015401` | `45.83` | `n/a` | `36` | `n/a` | `185.00` |
| `1` | `4` | `48/48` | `2.574119` | `3.612551` | `1.281759` | `64.06` | `n/a` | `36` | `n/a` | `205.00` |
| `1` | `8` | `96/96` | `3.560389` | `5.472892` | `1.662793` | `71.65` | `n/a` | `57` | `n/a` | `235.00` |
| `1` | `16` | `96/96` | `6.288389` | `9.395524` | `1.768621` | `71.59` | `n/a` | `54` | `n/a` | `240.00` |
| `1` | `32` | `96/96` | `10.872464` | `14.007766` | `2.253740` | `87.14` | `n/a` | `42` | `n/a` | `273.00` |
| `4` | `1` | `30/30` | `1.153778` | `1.249313` | `0.866661` | `11.94` | `1.09` | `35` | `100.00` | `132.81` |
| `4` | `2` | `36/36` | `1.198030` | `1.309262` | `1.640053` | `29.00` | `3.37` | `19` | `86.36` | `152.67` |
| `4` | `4` | `48/48` | `1.509908` | `2.564284` | `2.274139` | `45.05` | `5.38` | `21` | `95.45` | `196.70` |
| `4` | `8` | `96/96` | `2.201538` | `3.488409` | `2.641691` | `53.05` | `7.11` | `38` | `100.00` | `221.39` |
| `4` | `16` | `96/96` | `3.735209` | `5.626851` | `3.033092` | `63.61` | `8.45` | `31` | `96.88` | `244.99` |
| `4` | `32` | `96/96` | `6.630575` | `9.369125` | `3.392860` | `69.62` | `9.28` | `29` | `100.00` | `259.52` |
| `8` | `1` | `30/30` | `1.027804` | `1.094380` | `0.972887` | `15.03` | `4.83` | `30` | `96.77` | `144.38` |
| `8` | `2` | `36/36` | `1.102440` | `1.622194` | `1.766362` | `28.70` | `9.10` | `20` | `95.24` | `159.68` |
| `8` | `4` | `48/48` | `1.341716` | `1.923248` | `2.520777` | `43.67` | `13.67` | `18` | `90.00` | `174.03` |
| `8` | `8` | `96/96` | `1.981459` | `2.677468` | `3.124087` | `69.25` | `21.79` | `28` | `90.32` | `230.66` |
| `8` | `16` | `96/96` | `3.223674` | `4.614377` | `3.452352` | `71.00` | `21.50` | `26` | `92.86` | `251.96` |
| `8` | `32` | `96/96` | `5.974584` | `8.247637` | `4.026919` | `81.17` | `25.09` | `23` | `95.83` | `283.06` |
| `16` | `1` | `30/30` | `1.014894` | `1.072646` | `0.985266` | `12.94` | `4.33` | `33` | `100.00` | `139.09` |
| `16` | `2` | `36/36` | `1.165427` | `1.760677` | `1.609574` | `25.30` | `8.26` | `23` | `100.00` | `164.13` |
| `16` | `4` | `48/48` | `1.364104` | `2.016599` | `2.545938` | `37.39` | `12.28` | `18` | `94.74` | `167.96` |
| `16` | `8` | `96/96` | `1.988593` | `2.751272` | `3.027711` | `63.93` | `20.86` | `28` | `87.50` | `236.45` |
| `16` | `16` | `96/96` | `3.550220` | `5.548307` | `3.213059` | `60.10` | `19.38` | `29` | `96.67` | `249.37` |
| `16` | `32` | `96/96` | `5.597851` | `8.063148` | `3.919794` | `75.96` | `24.56` | `25` | `100.00` | `276.44` |

Resource peaks and sample accounting (visible VRAM `47.384 GiB`, container RAM limit `58 GiB`, cgroup leaf `pids.max` unbounded with experimental budget `512` and guard `409`):

- `B4`: max VRAM `13.7943115234 GiB` (`70.888%` min free), kernel RAM peak `8.8021812439 GiB` (`84.826%` min free), max PIDs `106`, `275` NVML samples (`173` active), `1091` base samples.
- `B8`: max VRAM `14.0911865234 GiB` (`70.262%` min free), kernel RAM peak `8.80100250244 GiB` (`84.829%` min free), max PIDs `103`, `249` NVML samples (`145` active), `990` base samples.
- `B16`: max VRAM `15.2630615234 GiB` (`67.789%` min free), kernel RAM peak `8.80948638916 GiB` (`84.812%` min free), max PIDs `105`, original collector `263` NVML samples (`156` active) and `1054` base samples; parent read-only historical recovery `268` NVML samples (`156` active) and `1070` base samples.

Methodological notes and operational disclosures:

- `B8` required three subagent attempts: primary failed with a provider error before writing files; fallback-b stopped once pre-resume on a stale config readback (`live-b8`) and once on a readiness log deadline after activation with zero HTTP requests and a partial post-cleanup API ledger after an `AttributeError` (`live-b8-ready`), both safely returned to `paused`/`min=0`/`0` replicas and preserved; member-c (`live-b8-c`) reused the proven `B4` collector path with consistent monotonic clocks for readiness deadlines and completed the run.
- `B16` required three subagent attempts and **two sequential single-GPU activations** (never simultaneous GPUs, zero measured HTTP replay): attempt 1 failed preflight on a healthcheck key mismatch with zero mutations (`live-b16-attempt1-preflight-failed`); attempt 2 applied the `B16` entrypoint PATCH and activated the replica (`min=1` + `resume`) but missed readiness log ingestion with zero inference requests and cleaned up to `paused`/`min=0`/`0` (`live-b16-attempt2-gate-failed`); attempt 3 (`live-b16-c`) found `B16` already configured, activated the GPU once, completed the warmup and all `402/402` measured HTTP requests, and cleaned up to `paused`/`min=0`/`0`.
- In `live-b16-c/matrix-b16/result.json` (preserved unaltered), `stop_reason` is `gpu_log_collection_failed` because the final 30-second post-matrix log reread timed out. The original `263` NVML samples already contained all `156` active samples across all 6 concurrency levels (including all `25` active samples of the final `CC32` case; a delegate claim of 40 missing samples in the final 26 seconds is refuted by the raw data). A parent read-only audit across 6 non-truncated `<=55 s` log queries (`2026-10-29T18:44:50.480513+00:00` to `18:50:07.710973+00:00`) recovered `268` NVML and `1070` base samples, adding `1` pre-matrix and `4` post-HTTP correlation-inactive samples while leaving all `156` active samples and every per-case and overall GPU statistic identical.
- These measurements come from a single 45000-character synthetic fixture on separate time windows and pod allocations; they do not isolate physical host node, connection distribution across the 8 worker processes, or counter timing, and they are not an SLA or model-accuracy certification. NVML percentages measure device-global activity rather than SM/FLOP occupancy, and sampled watts are not provider billing.

### Historical Verda state before the measured B1 run (2026-10-28 14:40Z, superseded)

- At the initial `2026-10-28T14:40:37Z` checkpoint (before L40S capacity returned later that day), the deployment was `unhealthy`: desired GPU L40S, `min_replicas=1`, `max_replicas=1`, concurrency `32`, unpaused, one replica in `ERROR` (metadata only) and no `RUNNING` GPU.
- One pause, `PATCH`, and resume cycle had run. Verda merged the previous `49` environment entries with the new `56` into `105` (confirmed by parent `GET` as the exact known union), and reported `SchedulingFailed` (`NoNodes` for L40S).
- That initial capacity block and the intermediate `2026-10-29T13:13:51Z` collector timeout were subsequently resolved as documented above. See the [chunk batching implementation plan](../substrate/traces/plans/2026-10-28-chunk-batching.md), the [chunk batching report](../substrate/traces/reports/2026-10-28-chunk-batching.md), and the [Verda service guide](verda-service.md) for full details.
