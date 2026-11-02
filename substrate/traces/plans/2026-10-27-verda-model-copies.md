---
document_type: mycelium-plan
plan_id: 2026-10-27-verda-model-copies
status: completed
created_at: 2026-10-27
planner: orchestrator
baseline_version: 1
execution_owner: orchestrator
execution_started_at: 2026-10-27T11:14:59Z
last_updated_at: 2026-10-28
---

# Verda model-copy comparison

## Current execution snapshot

- **Status:** Phase7 completed:402/402 measured validated200,310activeGPU samples independently matched to provider records; preliminary operational deviations disclosed.
- **Baseline identity:** `2026-10-27-verda-model-copies`, version 1, frozen on 2026-10-27.
- **Execution baseline:** HEAD `89412bf750c2a6bf3e80fcfbb7bebd192597ef46`, synchronized `dev`, pre-existing changes preserved in the ignored status record.
- **Active phase:** Phase7 closed; report delivered, no further benchmark or automatic optimization.
- **Last verified checkpoint:** 2026-10-28T11:10:41Z: parent all402rows/81bursts/6case statistics and310activeGPU samples verified, nativecurrent exactUUID-fixed8/min1/max1/32 withonerunningL40S;56privatefiles credential sweepPASS,21newfiles600, no remaining client.
- **Last successful checks:** Current1041fulltests/69Python3.14focusedtestsPASS, UUIDdelta39lines/allbranches100percent, qualityPASS. Measured402/402 valid200 withfixedbody/oracle,81bursts/27groups;310active of698GPU samples, no clock/owner/run anomalies. Parent6nativewindows matchall310samples;8PIDsstable. Earlierfour-waymatrix759/739success/20HTTP429 remains separatehistory.
- **Open blockers:** None for this completedcontrolledmeasurement. Providercontrolstatus remainsupdating, nothealthy, despiteone runningreplica/ready8/successfulinference; reportexplicitlyrecords it. No productionSLO/accuracy/costguarantee orlargerbatchresult isclaimed. Extraunauthpreliminary404isdisclosed, nothidden.
- **Required approvals and gates:** User explicitly authorizes `dev`, one existing GPU, four copy-count variants, concurrency through 32 and no restoration of the original configuration. Independent deterministic checks and quality judgment precede live changes. Focused security review becomes mandatory if implementation changes API, authentication, sensitive-data handling or comparable core surfaces.
- **Next action:** User reviews measured GPU/latency/power report. Keep existinguser-min1/8copies andunchangedmodel/image/B1; any chunk-batching optimization orproductionHA change is a separate approved task.

## Planner baseline

### Problem statement

Compare 1, 2, 4 and 8 independently loaded model copies on the existing single-L40S Verda deployment. For every feasible variant, measure HTTP bursts of 1, 2, 4, 8, 16 and 32 clients using one identical synthetic 45000-character document. Deliver a report rather than automatically choosing a winner. Retain the final verified experimental configuration; allow normal scale-to-zero without restoring the original settings.

### Research and evidence

- The deployed image remains `ghcr.io/digitalygo/envai-pii@sha256:c1d9d9c089047f7c1e4b7b0815e91a12cd810c963ddb58ba1f0da1233e961714`, source `4c4db76ee1712283ba8f5778da70871b2b43e169`, model v1.5.0, Torch 2.13.0 cu126.
- `Dockerfile.gpu` and `src/app/gunicorn_config.py` use one Gunicorn worker without preload. `src/app/app.py` loads one global pipeline per worker. Native Gunicorn worker configuration can therefore create multiple model copies without modifying the application engine.
- `src/app/runtime_execution.py` serializes model calls per process. `src/app/request_admission.py` already supports 16 active and 32 queued requests with queue timeout up to 30 seconds.
- Existing preview caches and preference globals are process-local. Multiple HTTP workers are an experimental topology for the stateless v1 API, not production validation of legacy stateful routes. This limitation must be explicit before live activation and in the report.
- [The historical capacity report](../../../docs/runpod-single-gpu-capacity.md) describes four-copy A40 diagnostics, not an optimization shipped in this image. Those core timings are not directly comparable with HTTP timings.
- The previous unchanged Verda HTTP test used the same fixed generator case and achieved validated 200 responses for all 28 measured calls. Its source/body hashes and raw rows are in `/home/lorenzo/private/tmp/envai-pii-verda-load-20261027/`.
- Fresh read-only preflight confirms healthy, zero replicas, one L40S, provider concurrency one, default entrypoint, min 0/max 1. CPU/RAM quota is not exposed in that deployment response.
- [Official API documentation](https://api.verda.com/v1/docs) links `/v1/openapi.json`. The independently fetched contract confirms separate deployment and scaling PATCH operations, `entrypoint_overrides` as enabled/entrypoint-array/cmd-array, complete env entries and filtered replica logs. Extract: `/home/lorenzo/private/tmp/envai-pii-verda-replicas-20261027/600JSONprovider-contract.json`.
- [Provider scaling documentation](https://docs.verda.com/containers/scaling/) defines queue TTL as queue plus execution time and a 30-second termination grace. API reads hide plain env values, so runtime telemetry and accepted exact requests must supplement readback.
- Directives and expectations directories are absent. Pre-existing work is recorded in `../status/2026-10-27-verda-model-replicas-workspace-state.md`.

### Hypotheses, decisions, and rationale

1. Use the native Gunicorn worker count rather than implementing a production model pool. The current requirement is an experiment on the stateless API; native platform configuration is the smallest way to compare independent model copies.
2. Keep the existing chunk batch B1 and model precision unchanged to isolate the copy-count effect. The proposed B16 experiment is separate; no B16 result may be claimed from a pipeline that still receives one chunk per call. This first report covers the four copy counts, not an optimized production engine.
3. Keep one physical GPU allocation at a time: compute L40S size one, max replicas one, min zero, no additional deployment or RunPod resource. Wait for zero replicas before changing profiles to avoid overlapping old/new allocations. Physical GPU UUID may change after rescheduling and must not be assumed constant.
4. Fix provider concurrency at 32 for all profiles, and use existing per-process admission settings 16 active, 32 queued, queue timeout 30 seconds, analysis timeout 60 seconds. Fix OMP/MKL threads to one and disable tokenizer parallelism across profiles. Changes from the earlier production baseline must be disclosed.
5. Use a private numeric-only Gunicorn configuration for per-worker readiness and telemetry. Never inspect or log request bodies, URLs, headers, dictionary values, env dumps or credentials. Do not add routes, middleware or application/model monkeypatches. Keep the original cloud factory and authentication boundary.
6. Every worker must finish a fixed synthetic warmup and demonstrate its own CUDA-backed model before an all-worker barrier releases HTTP service. A single successful health response is not proof of N models. Detect worker churn and do not credit invalidated cells.
7. Before increasing model count, use observed GPU memory, own cgroup RAM/PID limits and conservative headroom. Do not intentionally exhaust memory. Guarded or infeasible cells remain explicitly unavailable, not successful or zero-latency samples.
8. Run three predeclared bursts per concurrency level, with no retry or replacement of measured requests. This is 189 measured requests per feasible variant and 756 if all four complete, excluding startup and warmups.
9. Record end-to-end successful and failed outcomes, mean, observed nearest-rank p95, maximum, phase duration and validated throughput. Keep all raw metadata; count actual client overlap and avoid equating it with GPU forwards. Report sampled global memory separately from true per-process Torch high-water marks.
10. Keep the last verified configuration, not an automatically selected winner. On serious failure, stop traffic and retain or return only to the most recent verified experimental profile, never silently to the original setup. A safety pause is allowed to stop an unhealthy allocation. End at zero active replicas when idle while preserving the selected definition.

### Planned phases

#### Phase 1: validate baseline and provider contract

- **Objective:** Establish identity, authorization, baseline files and actual API request shapes before implementation.
- **Planner predictions:** No cloud mutation or GPU wake; exact image/default configuration and provider contract remain available. Only ignored status and plan Markdown are created.
- **Proposed steps:** Verify branch/sync, inspect dirty state, read standards and source, collect sanitized preflight and official schema extracts.
- **Predicted verification:** Inspect actual preflight, API schema, source hashes and `git diff`; verify no existing file was overwritten.
- **Completion criterion:** The orchestrator records exact baseline and authorized request shapes with unresolved runtime quotas explicitly unavailable.

#### Phase 2: prepare portable configuration and measurement tools

- **Objective:** Build tested, portable experiment tooling without changing production application code or handling credentials.
- **Planner predictions:** New files under `tools/verda_model_experiment/` for fixed fixture, numeric runtime hooks, self-contained entrypoint packaging and transport-injected burst measurement; focused tests under `tests/test_verda_model_*.py`. No live CLI, secret loader, network client, new dependency or source-app modification.
- **Proposed steps:** Delegate runtime/package and measurement as disjoint writer tasks. Preserve original factory, preload behavior, access-log suppression, model and source hashes. Reject invalid worker counts, unsafe run IDs, unexpected archive paths and incomplete readiness.
- **Predicted verification:** Unit tests use fake workers, Torch, clocks, transport and temporary files without GPU/model downloads. Cover startup guards, readiness, lifecycle, telemetry privacy, packaging, fixture hashes, every burst size, error accounting and no retries. Executable delta coverage must be at least 80 percent per file.
- **Completion criterion:** Parent inspection and deterministic test/coverage runs pass; no source or baseline collateral changes.

#### Phase 3: review the frozen experiment package

- **Objective:** Independently judge the exact code/config package before live activation.
- **Planner predictions:** Full repository discovery and experiment tests pass without skipped or weakened tests. Quality judgment checks resource guards, API-contract preservation and experiment-only legacy limitations. Security eligibility is assessed from the actual delta, not assumed from this plan.
- **Proposed steps:** Freeze artifact/source hashes, run declared repository tests and coverage, invoke the quality reviewer, resolve findings without changing agreed requirements silently. Invoke focused security review if actual implementation crosses its required boundary; unavailable required reviewers block activation.
- **Predicted verification:** `python -m unittest discover -v tests`, focused coverage and read-only quality verdict. A FAIL or required security BLOCKED prevents live changes.
- **Completion criterion:** All applicable deterministic and judgment gates pass for the exact activation package.

#### Phase 4: calibrate one-copy experimental baseline

- **Objective:** Prove deployment/readiness/measurement on one worker and collect real resource bounds before growth.
- **Planner predictions:** Two minimal PATCH operations set the experimental entrypoint/env and provider concurrency while preserving image, GPU, ports, health, auth and scaling bounds. A new cold start may be required.
- **Proposed steps:** Apply only the reviewed N1 profile, verify exact readback, start through authenticated health, wait for per-worker ready evidence, validate warmup/oracle, run all six concurrency levels with three bursts each, stop endpoint traffic and observe natural zero.
- **Predicted verification:** Actual 189 request rows or explicit failed/incomplete outcomes, same fixed body/hash, worker readiness and churn checks, CUDA/cgroup telemetry, unchanged non-target fields and independent final management reads.
- **Completion criterion:** Parent verifies real rows, timing math, resource headroom and no hidden retries. The N1 experimental configuration remains, not the original default.

#### Phase 5: measure two, four and eight copies

- **Objective:** Produce the remaining three model-count comparisons on the same GPU class/allocation limit.
- **Planner predictions:** Higher counts may become infeasible due to RAM, VRAM, PIDs, availability or correctness. No particular count is presumed to improve throughput.
- **Proposed steps:** Apply growth guards before every profile; change only reviewed worker-count/run identity; wait for all workers, warm and measure the same six levels/three rounds. Capture filtered numeric logs with bounded windows and API polling below documented rate limits. Retain all failures and unavailable cells.
- **Predicted verification:** Expected successful matrix counts where feasible, no credited cells with worker churn or mismatched outputs, conservative memory accounting and no overlapping GPU allocations.
- **Completion criterion:** Every model-count possibility is represented by measured results or a specific verified infeasibility/blocker; the final retained profile is identified without selecting a winner.

#### Phase 6: report and close

- **Objective:** Deliver all four possibilities and an auditable final state for the user's decision.
- **Planner predictions:** A report under `substrate/traces/` contains the four-by-six timing/throughput/error matrix, memory use, limits, changed settings and final configuration. The existing operation record links to this plan/report.
- **Proposed steps:** Recalculate from raw rows, inspect privacy and config preservation, verify idle zero without new endpoint traffic, write the report and update the operation. Do not commit or push unless later required and authorized.
- **Predicted verification:** Calculator-checked means and comparisons, exact Unicode fixture reconstruction, actual-credential membership checks in private evidence, source/diff checks and final management readback. Stop/remove newly created ephemeral local resources; preserve pre-existing verification environments.
- **Completion criterion:** A verified report is delivered, remaining limits are explicit, and no original-config restoration or automatic winner promotion is claimed.

## Execution ledger

### Ledger rules

The orchestrator owns all entries after execution starts. Preserve the planner baseline; append material decisions, gate evidence and variations, not raw tool logs.

### Phase 1 execution checkpoints

#### Checkpoint 2026-10-27T11:14:59Z: baseline and provider contract validated

- **Event:** Phase 1 completed; no live mutation or GPU wake.
- **Planner prediction:** Phase 1 requires a preserved repository baseline and actual API request shapes, with quotas explicitly unavailable until measured.
- **Subagent claims:** The preflight reports healthy/zero, exact c1d9 image, one L40S and default entrypoint. The native schema extract identifies separate deployment/scaling PATCH operations and filtered replica logs.
- **Orchestrator finding:** Native Gunicorn worker configuration is the smallest experiment implementation; an application model-pool feature would be a broader, unnecessary production change. The experimental legacy-state limitation and fixed B1 comparison were surfaced to the user before activation.
- **Independently verified facts:** Parent inspected complete preflight and schema extracts, current AGENTS, original source and prior helpers. Source hashes match the deployed baseline; original non-trace worktree fingerprints are unchanged. The existing Python 3.11 verification environment has Flask 3.1.3, PyMuPDF 1.28.2 and coverage 7.17.0. `git pull --ff-only` and `git diff --check` passed.
- **Decision and impact:** Begin only portable experiment-tool implementation. Backend a/c and primary research/quality providers remain excluded by the known session OpenRouter outage, so the eligible backend writer is b and quality reviewer b. No app API/authentication/sensitive-data code change is intended; eligibility for any further security gate will be reassessed from the actual implementation, and a required unavailable gate would block activation. No failed review can be waived.
- **Next action:** Implement two disjoint tool slices and test them with fake workers/transport, without credentials, GPU or cloud mutations.

### Phase 2 execution checkpoints

#### Checkpoint 2026-10-27T12:02:26Z: portable tools verified after integration corrections

- **Event:** Phase 2 completed for the native-configuration experiment package; Phase 3 judgment is pending.
- **Planner prediction:** Offline helper tools, no application modification or credential handling, at least 80 percent coverage and real readiness/resource constraints before activation.
- **Subagent claims:** Two disjoint writers supplied fixture/runtime/packaging and transport-injected measurement. An initial correction writer used an unsuitable system interpreter and reported skips; that verification is not credited. A measurement-only hardening delegation refused because it adopted a recursive coordination role; it made no change and was not retried unchanged or routed to another writer family.
- **Orchestrator finding:** Initial 954 passing unit tests missed two integration faults: module search paths did not survive exec and Gunicorn rejected the variadic post-request hook. Parent reproduced both failures with an isolated exec probe and pinned Gunicorn 26.2.0. Delegated corrections added persistent module lookup, exact hook arity, encoded-command limits and total-VRAM headroom. The measurement helper's setup barrier remains internally unbounded; an external hard process budget is a mandatory execution precondition, recorded in V-001, rather than a falsely claimed source fix.
- **Independently verified facts:** The final parent run executed 958 tests with no skips using the existing Python 3.11 environment. Coverage is 969/1057 executable helper lines, rounded 92 percent; runtime is 89 percent, fixture 97, measure 95 and package 95. Actual Gunicorn accepts every configuration and hook at workers 1/2/4/8; the fresh-child exec probe imports the unpacked runtime successfully. A fault-injected stalled-barrier process was terminated and reaped by GNU timeout with zero send calls. All new code has zero comment tokens; `git diff --check` and the unchanged app/Docker source checks pass.
- **Decision and impact:** Freeze archive SHA256 `3c5958809df67665a41ab84d801d74d8d1d2506d751bb357f37a321ee40537dd`. All four generated profiles share this archive; bootstrap size is 21801 bytes. Intended new files are the portable tools and three focused test modules only. Runtime read-only hooks do not inspect requests or alter the app, middleware, model, precision or inference functions. No GPU has been started and no provider configuration changed.
- **Next action:** Independent quality judgment and security-eligibility assessment of the actual frozen slice; no live activation on a failed or required unavailable gate.

### Phase 3 execution checkpoints

#### Checkpoint 2026-10-27T12:31:09Z: quality passed and activation bytes verified

- **Event:** Phase 3 completed; no cloud mutation or GPU wake yet.
- **Planner prediction:** Independent deterministic and judgment gates must pass for the exact code/config package before activation.
- **Subagent claims:** Quality-gate-b returned PASS, with the explicit advisory that every live run must use the external watchdog and incomplete cells must not be retried. Artifact generation initially stopped on a binary archive mismatch, then produced all profiles using the specified verifier environment.
- **Orchestrator finding:** The final delta changes portable experiment tooling and native runtime configuration only, not application API, middleware, authentication, model inference or sensitive-data handlers. Numeric hooks do not inspect request context; no credential loader or live transport was added to the tools. A separate core-surface security gate is not triggered by this actual slice. This is not a general security certification.
- **Independently verified facts:** Parent read the full activation manifest and compared every parsed profile to `build_profile` under Python 3.11.16. All four match exactly and share reviewed archive `3c5958809df67665a41ab84d801d74d8d1d2506d751bb357f37a321ee40537dd`. Profile-file hashes are N1 `ba1110bbf74eb6cb661268106e8a8af8201a6c67d8ec98dac26211f3664b0aeb`, N2 `17c376d26cbd5509880e1c6ee675ee61d06e7f716fe297b40ee456f645b12657`, N4 `d12e43620444168bc20b45df31e57a623798a62d7344f7fbb37cb8a6c63fd244`, N8 `a4e88a3ca0f5491fb40c634811de4caf462994011e68ed3ec76ea744f92f5be3`. All request shapes match the actual provider contract. Source fingerprints remain unchanged.
- **Decision and impact:** Advance the quality cursor to the verified source/archive snapshot. Permit N1 calibration only; higher variants still require actual resource evidence. Keep B1 fixed and the final experimental definition rather than automatically restoring the old configuration.
- **Next action:** Apply N1 with strict preservation readback, then prove worker readiness, run declared measurements and verify natural idle zero.

### Phase 4 execution checkpoints

#### Checkpoint 2026-10-27T12:44:54Z: operational delegation blocked before mutation

- **Event:** Phase 4 is blocked; no calibration or measured request has started.
- **Planner prediction:** Apply the independently reviewed N1 profile only through the delegated operational member, then prove runtime and resource behavior.
- **Subagent claims:** Activation calls first requested branch confirmation, then stopped on an incorrectly transcribed filename, and finally read the exact artifact but refused because the adopted orchestrator role required another delegation that a subagent cannot spawn. Every activation attempt reported zero API mutation, health and inference calls. The last refusal is a role/capability blocker, not a provider error or GPU result.
- **Orchestrator finding:** Repeating the operation unchanged, doing the PATCH directly, or routing it to general/read-only agents would evade the loaded delegation and fallback rules. Backend-a/c are already excluded by the known OpenRouter 402; no further eligible backend execution member is available. Preserve verified preparation and stop before live mutation.
- **Independently verified facts:** A bounded management-only parent check confirms the exact c1d9 image, healthy state, zero replicas, original entrypoint with overrides disabled, original two env names, provider concurrency one and min 0/max 1. No endpoint was called. Chezmoi source is under `/home/lorenzo/.local/share/chezmoi`, a separate Git repository from envai-pii.
- **Decision and impact:** Leave the deployment unchanged, not restored: nothing new was applied. All 24 new model-count/concurrency cells remain unmeasured. The code/quality result remains useful but does not complete the experiment. A separate configuration-workflow repair requires user approval before modifying that second repository.
- **Next action:** Report the blocker and obtain multi-repository repair approval, then resume from the exact frozen artifacts rather than reimplementing the experiment.

#### Checkpoint 2026-10-27T15:11:26Z: resume after reported provider repair

- **Event:** Phase 4 resumed; existing plan and immutable baseline retained.
- **Planner prediction:** Recheck baseline, artifacts and gate continuity before trusting a resumed state.
- **Subagent claims:** Two locator-a requests completed successfully through OpenRouter and confirmed the existing resume point, code and manifest identities. Their initial note that no post-recharge request was recorded is superseded by the successful requests themselves.
- **Orchestrator finding:** The user explicitly reports recharging OpenRouter and asks to retry, changing the availability condition underlying the previous provider exclusions. Return to the primary backend route rather than changing global agent instructions or bypassing delegation.
- **Independently verified facts:** Chezmoi sync and fast-forward pull succeeded; approved branch dev and HEAD 89412bf are unchanged. Parent reran 958 tests with no skips, reproduced archive 3c595880 under Python 3.11 and verified all four original profile file hashes plus the manifest. No source changed after the successful quality gate. Original and resumed dirty-state snapshots remain preserved.
- **Decision and impact:** Re-enable primary provider routing on the updated availability evidence. The separate chezmoi repair is not authorized and is unnecessary unless the restored primary also proves unusable. No live mutation occurred during these resumption checks.
- **Next action:** Backend-a applies only N1's reviewed activation requests, followed by independent readback before GPU calibration.

#### Checkpoint 2026-10-27T16:22:45Z: observed API bound corrected without changing experiment behavior

- **Event:** Scaling activation is verified; deployment activation awaits the corrected command representation.
- **Planner prediction:** The reviewed self-contained command must fit the actual provider contract while retaining the original factory and experiment matrix.
- **Subagent claims:** Backend-a applied scaling32, then the old deployment request returned 400. Its later diagnosis call failed with provider finish_reason error and left an unapproved runner file; that file was not executed. Sequential backend-c captured the safe validation reason: each cmd argument must not exceed 253 characters. No hidden retry or GPU probe supplied a performance result.
- **Orchestrator finding:** This is a delivery-encoding mismatch, not a model or app failure. Delegate a signed ordered-chunk representation with the same bootstrap/Gunicorn arguments. Old artifacts and failures remain immutable. Plain env values can be compared when the API returns them; earlier sanitized omissions are not proof that the API always redacts them.
- **Independently verified facts:** Parent read the actual error artifact and management readback: scaling32/min0/max1 applied, image and original entrypoint preserved, healthy/zero. After the encoding correction, parent ran 964 tests without skips. Exact modified executable coverage was initially 27/35 and blocked acceptance; added tests raised it to 35/35. Every argument is <=240 characters and the 159-character loader verifies the reconstructed payload before exec. Fresh-child execution/import passes. Quality-gate-b returned PASS for this correction.
- **Decision and impact:** Advance the quality cursor to package SHA ebdab6d4 and archive ab7756396064daa96f804af8841ac3281039f92682dd644f2f39756deb9f3ed9. New profile-*‑argv253 artifacts equal the current reviewed builder; the actual serialized command is 23534 bytes for the full run IDs, not the shorter test IDs' 23494. No semantic difference, new download, image change or additional GPU is introduced.
- **Next action:** One reviewed deployment PATCH for N1, strict exact readback, then authenticated readiness and the predeclared six-level calibration if all safety checks pass.

#### Checkpoint 2026-10-27T18:40:50Z: N1 and native resource evidence independently verified

- **Event:** Phase 4 complete, including ordinary overload outcomes; Phase 5 may begin under the reviewed controller policy.
- **Planner prediction:** Prove the one-copy topology and collect real bounds before growth; report failures instead of retrying measurements.
- **Subagent claims:** Backend-c activated compact N1 once, captured readiness/warmup and all 18 bursts, then observed natural zero. Its final readiness summary was empty because the ending log query returned no startup events; the raw ready artifact separately records the serving proof.
- **Orchestrator finding:** Accept measured data only after independent row and native-log verification, not the final empty aggregate or the operator's completion label. The initial boot replica naturally stopped before the separate calibration invocation; the 39.13-second POST warmup includes a new cold start and is excluded. The measured window itself used one stable serving replica and PID.
- **Independently verified facts:** Parent reaggregated all 189 rows and oracle/body hashes. Successes by CC1/2/4/8/16/32 are 3/6/12/24/48/76 out of 3/6/12/24/48/96; the other 20 responses are 429 with approximately 30-second waits. Actual matrix window is 18:14:43.575150Z to 18:19:49.055267Z. An independent GET of filtered native logs over 18:13–18:22Z recovered 196 serving-replica events, exactly one ready PID70 and no exit/child-exit/startup-failure during that window. Every PID-limit reading has value null and reason limit_unavailable; pinned source maps that exact reason to literal pids.max=max. Native maximum task count is 42, RAM peak1235337216/limit62277025792 bytes and GPU minimum free49066016768/total50878152704 bytes. Management readback confirms exact N1 override, concurrency32 and healthy/zero after natural shutdown.
- **Decision and impact:** N1 stays valid and is not rerun. Distinguish explicit uncapped PID state from unknown data using V-005's opt-in finite budget. No GPU runtime or profile changed for that local-controller correction. Remaining model counts must use the same runtime archive and body, new measured rows and fresh native evidence.
- **Next action:** Guard and execute N2, then N4 and N8 if feasible, under a continuous supervised operator process to avoid thinking/control gaps between readiness and warmup.

### Phase 5 execution checkpoints

#### Checkpoint 2026-10-27T21:42:34Z: two and four-copy matrices independently verified

- **Event:** N2 and N4 completed; N8 not yet started.
- **Planner prediction:** Grow only after resource checks and report each actual model count over all six concurrency levels.
- **Subagent claims:** A combined higher-profile backend-c call failed with upstream idle timeout before observed activation; a parallel documentation call was aborted by the tool, not by an explicit user cancellation. Atomic primary-backend tasks subsequently activated and measured N2 and N4 successfully. Both finalizers had local summary-scope errors after completing the data; management-only recovery preserved the original rows and proved natural shutdown without replaying requests.
- **Orchestrator finding:** Prefer small coherent per-profile operations after the long-call failure. Provider errors on earlier distinct tasks do not erase successful primary execution; all prior failed/unmeasured cells remain distinguished. Do not infer posttraffic from a completion label when direct lifecycle/readback can verify it.
- **Independently verified facts:** Parent reaggregated all18bursts/189rows for each model count and body/oracle hashes. N2 actual matrix21:00:22.584590–21:03:35.711905Z has189validated200; means atCC1/2/4/8/16/32 are1.951633/2.432783/3.267367/5.859242/12.242901/25.476410s. N4 matrix21:30:14.619858–21:32:31.208430Z also189validated200; means1.972444/2.383756/2.543243/3.973490/7.127901/14.751307s. Native ready PIDsets are N2{82,83} and N4{82,83,84,85}, with unchanged source/settings/model/dtype and no measured-window churn. Manager readback independently confirms retained exact N4, healthy/zero, concurrency32 and unchangedimage. Native scale-to-zero events are N2at21:05:04Z and N4at21:34:19Z.
- **Decision and impact:** Accept N2/N4 data without replay. Conservative N4 resource basis: RAMpeak4755435520/limit62277025792,PIDs73 with explicituncappedleaf/budget512,GPUused7239499776/free43638652928/total50878152704. Parent recomputed N8 guard using N1per-copyfloors and512MiBloadingmargin: requiredPIDs302, requiredRAM12792069120, requiredGPU18781143040, all below respective budget/capacity. No provider PID quota is invented. No source/runtime-profile byte changed.
- **Next action:** Atomic N8 task, then independent row/native/state verification and complete report.

#### Checkpoint 2026-10-27T22:23:37Z: eight-copy measurements verified with retained replay evidence

- **Event:** Phase5 complete with V-006, not a clean-protocol pass.
- **Planner prediction:** Three declared bursts per cell, no replay/discard, all actual outcomes retained, final verified configuration preserved.
- **Subagent claims:** The first N8 attempt returned three valid CC1 responses then stopped at pid_limit_unknown. The operator attributed it to an empty telemetry window, restored lastsafeP4 and restarted the full N8 matrix. It disclosed the extra attempt after completion.
- **Orchestrator finding:** The replay contradicted the declared procedure and is not approved retroactively. Raw rows prove three successes despite the unconsolidated first aggregate reporting zero. Include all six CC1 samples in a labeled descriptive post-hoc pool and retain both attempts separately.
- **Independently verified facts:** Parent validated all 189 main N8 oracle200 and the three initial CC1 rows. Native pagination recovered 1008 events for serving replica envai-pii-test-7f4678554c-v68q7: eight readyPIDs82..89, expected model/GPU/settings, no exit/churn during 22:09:05.780426–22:11:26.932147Z. N8 maxima are RAM9435222016B, GPU14475984896B and109tasks. Lifecycle shows firstN8deleted22:06:34Z, secondcreated22:08:34Z and naturalzero22:13:04Z, without overlap. Main N8 means are1.806289/1.929179/2.720196/3.291829/6.061889/11.839648s; pooled CC1 is1.865984s over6samples.
- **Decision and impact:** Accept factual measurements with explicit method limitation, not another rerun. Retain final eight-copy definition, not an automatic winner. Temporary rollback was P4 only, never the original setup.
- **Next action:** Complete the independent report, privacy/source checks and management-only closure.

### Phase 6 execution checkpoints

#### Checkpoint 2026-10-27T22:30:46Z: report and final state independently verified

- **Event:** Phase6 completed; report delivered for user selection.
- **Planner prediction:** Recalculate all four-by-six results, report errors/resources/limits and preserve last verified experimental state at idle zero.
- **Subagent claims:** Analyzer-a independently confirmed the replay, first-aggregate defect and pooling caveat.
- **Orchestrator finding:** N1/CC32 mean concerns76successes with20HTTP429. N8/CC1 has6samples over2activations; other cells retain3bursts. Moreprocesses also replicate HTTP admission and change connection distribution; benefits are not solely VRAM or measured GPU-forward overlap.
- **Independently verified facts:** Parent reaggregated all759rows and checked every mean against the report. Calculator checked all24means/comparisons, unitconverter checked bytes/GiB. Every success has bodyd2a274f2 and oracleddda56ee. Actual-credential sweep over119files passed. Source/archive unchanged; no app/Dockerdelta or active scopedlocalclient. Freshmanager confirms exactN8, healthy0,concurrency32,min0/max1,oneGPUallocationmaximum, withoutendpointtraffic. Report ../reports/2026-10-27-verda-model-copies.md is complete. Pre-existingverificationvenvpreserved.
- **Decision and impact:** Close with disclosed deviation and explicit production limits. No staging/commit/push, globalagentrepair, original-configrestore or winner promotion.
- **Next action:** User selection.

### Phase 7 execution checkpoints

#### Checkpoint 2026-10-27T23:18Z: user-authorized eight-copy GPU observation

- **Event:** Resume for a new explicitly requested follow-up, not a replay or correction of old measurements.
- **Planner prediction:** The original baseline stays immutable and the four-way report remains completed with its stated limitation. New evidence belongs to a distinct run/directory/report.
- **Subagent claims:** Locators identify no existing observed-utilization helper. Backend-a completed full public-contract inspection but lost sanitized live state in a local serialization error; it stopped without another OAuth call. Analyzer identifies numeric native NVML observation as the smallest dependency-free path and warns about argv size, identity mapping and misleading activity semantics.
- **Orchestrator finding:** The cached contract was only an extract, so absence was checked against the full live OpenAPI. Native public metrics really are absent. Reuse the already reviewed measurement/fixture/runtime rather than modify model inference. Mechanical diagnostic integration is single-writer work, not a high-variance inference-algorithm race. No parallel GPU runs are permitted.
- **Independently verified facts:** Chezmoi/pull pass, HEAD89412bf and approveddev unchanged, dirty baseline recorded in ../status/2026-10-28-verda-eight-gpu-profile-workspace-state.md. Parent current native reads verify exactN8/healthy0, oneGPU/min0/max1/concurrency32. Full OpenAPI SHA bf60650aaf85c03c2f65fe8b19e14e8d34cce6161ac153ec4896bf14ccc36abd has86paths and zero observability paths. No endpoint or live mutation yet.
- **Decision and impact:** Opt-in wrapper may add one global numeric sampler after all-worker readiness, without changing original runtime/app/model/B1/precision/auth/dependencies. Use stdlib NVML through a verified CUDA/NVML identity, explicit unavailable reasons, timestamps and lifecycle cleanup. Power is optional if unsupported. Preserve original default packaging; if new source exceeds argv64/253 use a separately tested bounded hash-verified archive carrier in environment, removed before exec. This is trusted configuration delivery, not network code download.
- **Controlled protocol:** Only N8. Fixed fixture d2a274f2, same oracle and HTTP settings. Concurrency1/2/4/8/16/32, respectively10/6/4/4/2/1 groups of the existing three bursts:402measured requests maximum, calculator-verified. All outcomes persisted after every burst, no retry/substitution. New single run identity and one continuous activation; global1500s process watchdog, finite request/startup/management budgets. Read GPU activity approximately1Hz without CUDA synchronization; correlate samples only with measured transport windows, exclude warmup/idle/gaps, report counts/coverage and unavailable rather than0 for missing data. Require valid matched-owner GPU samples before measurements and at least10active samples per cell for a quantitative GPU summary; insufficient samples retain latency results but GPU summary is unavailable. Serious runtime/model/oracle/churn/resource failures stop further load, never replay a cell.
- **Approval:** User explicitly requests tests monitoring GPU and restricts them to the existing eight-model setup. Existingdev/oneGPU/no-original-restore authorization continues. This does not authorize batch/precision/model/API changes, new resources, globalagent edits, commits or publication.
- **Next action:** Offline implementation, independent deterministic/coverage/quality verification, then one bounded operational task. End with eight-copy definition retained and natural idlezero; safety pause only if a serious fault prevents cleanup.

#### Checkpoint 2026-10-27T23:46:31Z: diagnostic package independently verified and quality passed

- **Event:** Offline diagnostic implementation verified; one monitored-N8 operation may begin.
- **Planner prediction:** Opt-in observation only, fixed original behavior, numeric safe telemetry, bounded signed delivery and offline fake verification before live activation.
- **Subagent claims:** Backend-a supplied gpu_monitor.py, gpu_runtime.py, gpu_profile.py, append-only package additions and three new test modules; no cloud calls or other source changes. It reports1034tests and90percentcoverage.
- **Orchestrator finding:** Actual implementation matches the intended separate wrapper. It resolves NVML device by matching CUDA UUID, claims a unique lowest-ready owner without takeover, samples approximately1Hz without measurement synchronization, retains null/reasons and optionalpower, preserves original hooks and all default archive bytes. Environment carrier is necessary for the monitored package, not a runtime secret, and is bounded/hash-checked/removed before exec.
- **Independently verified facts:** Parent full discovery undercoverage ran1034tests in27.938s, no skips, PASS. Coverage: monitor324/362, runtime96/110, profile340/388, package213/220; all83newpackage executable lines covered,7missespre-existing. New tests/read source and default hashes verified; comments0, whitespace/app/Docker checksPASS. Quality-gate-a returnedPASS. ActualGunicorn26.2 accepts wrapperhookarity1/2. Fresh-subprocess extraction/import passes. Defaultarchive02997f57 still8961bytes; monitoredarchive2b2c5854014afacd059947590e0f3de36d3280ff97a133a52924212361b293a4 is14766bytes. Exactrunidverda-20261028-gpu8, profilecanonicalSHAdd75c6908837ba2226bce6ea940d8cab98b28766f56f0c53dabd9975628ab498, patchcanonicalSHAfe0fc07dfb458fc56bdd3ccc8ec39f55bc3702e2aca3f83a4c808339c31daad3. Command15args/max253; env9; no inference yet.
- **Decision and impact:** Advance qualitycursor to verified diagnostic source. No coreapp/API/auth/sensitive-datahandler delta, so no additional automatic security gate is eligible; no general security certification. Reviewer advisories retained: overall overlap counter excludes unavailable samples, direct-file test main guard omits later classes (canonical discovery includes all), outerwatchdog operator-owned, and setup-owner failure yields no monitor/no takeover. These do not change valid-sample values or authorize load without counters. Parent will independently recompute totals rather than rely on the overlap counter. Outer1500s watchdog and actual counters are mandatory operational preconditions.
- **Next action:** Delegate one exact-profile activation/run, persist perburst, prove current8ready and non-nullGPU counters before measuring; preserve failures without replay, retain8 and idletozero.

#### Checkpoint 2026-10-28T00:45:48Z: hidden environment limit corrected without runtime changes

- **Event:** Activation format corrected; no measured workload started.
- **Planner prediction:** All native string/array limits must be obeyed and failures retained without inference replay.
- **Subagent claims:** Primary-a live call failed with provider finish_reason:error and no deliverable. Sequentialb made one rejectedPATCH400, then stopped. A separately authorizedc diagnosis repeated that rejected configuration once to capture the missing API validation message; its first local launch NameError occurred before requests. All report no endpoint traffic.
- **Orchestrator finding:** Parent observed no live runner/artifacts after the provider failure and independently confirmed oldN8healthy0. Actual diagnosis artifact records env.8.value_or_reference_to_secret must be<=253characters, absent from publicschema. Bothrejectedpatches preserve the old definition; these are delivery failures, not benchmark outcomes. The diagnostic JSON's oauth_post_attempts0 field contradicts its actualHTTPPOST record/count1, so use actualrequestledger rather than that erroneous summary.
- **Independently verified facts:** Parent read the complete diagnosis, exactmessage/bodyhash and preservation evidence. Backend-a changed only build-sideGPUpackage and its tests: halfarchiveinline, remaining39numberedenvchunks,56cmd/47env/max253bytes. Originaldefaultarchive02997f57 andGPUarchive2b2c5854 remainbyteidentical; model/runtime/inferenceunchanged. Parent fullcoverage rerun1036tests/no skipsPASS, overall90percent, newGPUpackage114/120lines=95percent. Quality-gate-a correctionPASS. CorrectedprofilecanonicalSHAe0ee052e6f207e610ae249b84ccd2176a7eece4ffdae60f1ef6b923816eaeb0f, patchSHA9a41eabf815f9baf67bba8ad32ff96a2950c0a3788057d7cd9afff68333e2346. No application/Docker delta.
- **Decision and impact:** Advancequalitycursor to package81ce4303; correctedtransportis equivalent delivery under existingapproval, not altered8/B1semantics. Preserve old failedprofile/activation/ready/diagnosis files. New artifacts use gpu8-hybrid prefix. No extra securityeligibility.
- **Next action:** One corrected monitoredactivation plus fixed402request experiment if validcounters/readiness; stop on a realcounter/runtimeblocker. No hiddenrerun or originalrestore.

#### Checkpoint 2026-10-28T02:41:57Z: operational routes exhausted, final safe state verified

- **Event:** Phase7 blocked; preparation complete but liveGPUobservation not completed.
- **Planner prediction:** Run only through an eligible operational delegate, preserve all partialprogress and stop when family routes fail rather than evade restrictions.
- **Subagent claims:** Primary-a operationalfinish_reason:error; sequentialb initiallyaskedbranchconfirmation thenacceptedexistingdevpermission butrefused because its adopted workflow demands nesteddelegation; sequentialc follow-up ended Upstream error:idle timeout while awaiting response payload. No corrected-profile operation artifact was produced.
- **Orchestrator finding:** Currentqgaccepted code and packaging remain useful, but no liveGPUresults may be invented from missingoutput. No morefamilyrerouting orparentoperation is allowed afterallmemberfailures. No globalagentrepair wasauthorized. Provider-interruptedcalls lackcompleteAPIledgers, so unknowncalls are not retroactively labeledzero.
- **Independently verified facts:** Parent management-only finalread proves exactoldN8entrypoint/env, monitoredcandidateunapplied, healthy0,min0/max1,concurrency32. No scopedclient or verifierPythonprocess remains. Actualcredentialmembership sweep passesall10privateevidencefiles; whitespace andapp/DockeridentityPASS. Source/package tests remain1036/no skips,90percentcoverage andbothqualityPASS; no executablechangedafterlastgate. New report ../reports/2026-10-28-verda-eight-model-gpu-profile.md explicitlymarksblocked/unmeasured. Oldfailedprofiles/results are preserved; originalfour-wayreport unchanged.
- **Decision and impact:** Stopwiththe genuineoperationalblocker, not a cleancompletionclaim. Keep8configured atzeroactiveallocations. No commit/push/staging/reset/stash, sourceauth/modelchange, newGPUresource ororiginalsetuprestore.
- **Next action:** User/harness restores an eligibleoperationalroute or approves a separately scoped workflowrepair ifneeded; resume under thissameplan afterfreshvalidation.

#### Checkpoint 2026-10-28T08:06:25Z: explicit user retry and gate continuity verified

- **Event:** Phase7 resumed after user request to retry now; earlier blocker evidence retained.
- **Planner prediction:** Resume from the same frozen package with fresh repository/provider checks, rather than rebuild instrumentation or silently repeat measured data.
- **Subagent claims:** Two primary locators succeed and confirm same correctedpackage/protocol. Analyzer finds no code blocker; counter precheck, owner discovery, activation and externalwatchdog are caller-owned operational preconditions.
- **Orchestrator finding:** The new request permits a bounded fresh availability attempt, not globalagentrepair or a waiver of failedchecks. Keep inheriteddevapproval; no model/batch/API/resource change. New instructions emphasize the existing helper APIs and avoid another broad implementation task.
- **Independently verified facts:** Chezmoi and pullPASS; HEAD89412bf and all gated SHA values unchanged. Parent reruns1036tests/no skips in25.365s, whitespace/app/DockerPASS. Freshmanagement checks exactoldN8 healthy0,min0/max1,ingress32 and buildercandidatee0ee052e. New ignoredstatus ../status/2026-10-28-verda-gpu-retry-workspace-state.md preserves currentdirtybaseline. No endpointtraffic or livechange during these checks.
- **Decision and impact:** Reuse both previous qualityPASS verdicts and90percentcoverage for unchangedsource; no new automatic codegate is eligible for resumption/Markdown alone. No coresecuritysurface delta. Correctednativeactivation has not yet succeeded and no GPUresult is claimed. Preserve oldfiles and use retry0806 artifactprefix.
- **Next action:** One primary bounded operation with counter proof beforeload, fixed402requests iffeasible and management-only finalzero verification.

#### Checkpoint 2026-10-28T08:35:00Z: accepted profile, unscheduled replica and final zero independently verified

- **Event:** Phase7 attempted through a functioning primary backend; blocked by provider capacity, not the prior execution-workflow issue.
- **Planner prediction:** Apply the exact corrected profile once and prove real eight-worker/counter readiness before warmup or load; preserve failures and stop safely if the allocation cannot start.
- **Subagent claims:** One deploymentPATCH200, no scalingPATCH. Initial10second readback still old, later exactcandidate without anotherPATCH. One authenticatedhealth attempt times out after330s; replica reports error. No warmup, measured requests, GPU samples or correlation. Final healthyzero retains monitored8.
- **Orchestrator finding:** Readiness failure is specifically unschedulable hardware, not an established app/model/bootstrap error. The delegate's empty application logs alone didnot establish cause; parent fetched system logs separately. Systemlogs return a top-level list; parent first dictionary-assumption failed harmlessly, then corrected read recovered actual events. Delegate summary's recorded_at9:35Z is future-relative and isnotused as a timestamp; use action artifacts and provider events.
- **Independently verified facts:** Parent currentcommand+all47env entries exactlymatch candidatee0ee052e, image/compute/scaling preserved, healthy0,min0/max1,32. Independent systemlogs08:19–08:35Z yield7events: ReplicaCreated08:22:52Z; SchedulingFailed08:22:56.700776Z count4 says no nodes available for selected instance type; ScaledToZero08:28:36Z; ReplicaDeleted08:28:37Z. Parent unfiltered exactpod application logs are empty. Creation timestamp isnotcontainerstartup/GPUallocation proof. Private evidence21files600/dir700 and actualcredentialmembershipPASS, no remaining verifier/client, sourcepackage81ce4303 andapp/Docker unchanged. Parent1036tests/no skips and priorquality gates stayvalid.
- **Decision and impact:** Retain the accepted monitored eight-copy definition atzero, without original/4copy restoration or alternateGPU/deployment. This is not a successfulmeasurement or verifiedboot. New report updated with real capacityblocker, old workflowfailures explicitly historical. No globalagentconfiguration repair wasneeded orauthorized. Operation-only/Markdown delta requires no new code gate or coresecurity review.
- **Next action:** Await L40S capacity or explicit approval for a changed hardware scope; no unbounded retry or addedresources.

#### Checkpoint 2026-10-28T09:18:27Z: user hardware change verified, production guidance separated from deployment

- **Event:** User asks retry after manually trying a differentGPU and asks how avoid productioncapacityfailures. No new benchmark is started against a known mismatched guard.
- **Planner prediction:** Preserve userchanges, validate actualhardware/image/readiness before measuring, and require approval for image/runtime or production-capacity changes.
- **Subagent claims:** Locators find L40Shardguard and process-local admission/cache. Webresearcher identifies documentedminwarm, queueTTLincludinginference and onecompute type, separating contractual guarantees from mere scalingconfiguration. Analyzer-a providerfailed withoutoutput; sequentialanalyzer-b confirms sourceblockers and no proof ofnewGPUinference.
- **Orchestrator finding:** CurrentGPUdiffers materially from frozenL40Sscope; directretrywouldfail diagnosticreadiness regardless ofavailablememory. Eightcopies on oneGPU are not hardwareHA. Recommendations are one warmbaseline, explicitcapacityagreement whenneeded, separatelyqualified failover and applicationdurable encrypted/idempotent jobs, not an instruction to apply newbillable resources.
- **Independently verified facts:** Parent freshnativecomputeRTXPRO6000x1, samee0eeentry/env, samec1d9image; initial2listedpods(imagepulling/error), finalhealthy withoneterminatingpod,min0/max1/32. Nativeevents show theuser's newpodscheduled/Created/Started09:05:43–44Z andReplicaDeleted/ScaledToZero09:12:22Z, but no applicationready/inference proof. Parent applicationlogquery returns0rows. Source runtime496–505 hardrequiresL40S; requirements pin2.13cu126, no sourcehashchange. OfficialVerda scaling/Terraformdocuments fetchedandread confirmwarmminimum, queueTTLandoneGPUtype; PyTorchmaintainerguidance identifiesBlackwellsm120 requiringCUDA12.8+ binarysupport. No health/inference/PATCH/productionconfigurationchange byus.
- **Decision and impact:** Do not launch known-incompatibleworkload or changeimage/pinswithoutscopeapproval. Preserve user'shardware/rolloutandalloldresults. New ignoredstatus ../status/2026-10-28-verda-gpu-change-workspace-state.md. Report adds source-grounded productionrecommendations and hardwarecaveats. Read-only/Markdown delta: tests/coverageN/A, existingcodegatesunchanged.
- **Next action:** Userapprovalforcompatibleimage/diagnosticwork; productionHA implementation remains a separately scoped decision.

#### Checkpoint 2026-10-28T09:45:10Z: L40S restored and a pre-existing warm replica is preserved

- **Event:** User explicitly requests the GPU tests after L40S returns. Same frozen source and protocol, no instrumentation reimplementation.
- **Planner prediction:** Revalidate hardware, readiness and frozen package before loading; preserve unrelated/user changes and only clean up task-created ephemeral resources.
- **Subagent claims:** Two locators confirm inheriteddev/L40S/eight/B1/oneGPU permission, acceptedcandidatee0ee and fixed402protocol. Analyzer confirms code-compatibleL40S, caller-ownedcountergate and no codeblocker; providerupdating alone is not a failedGPUproof.
- **Orchestrator finding:** Generic parent preflight expected the historical min0/healthy0 state and failed. Fresh diagnosticread shows user-owned min1 and an alreadyrunning pod started before the task. Do not overwrite it by applying the profile's min0 scalingpatch or force shutdown after testing.
- **Independently verified facts:** Chezmoi/pullPASS, approveddev/HEAD89412bf/dirtywork preserved. All gated sourceSHA match; parent1036tests/no skips in23.659s, app/Docker/whitespacePASS. Native L40Sx1, exactmonitoredentry/env,47env,c1d9image,max1/32,min1; runningpodenvai-pii-test-7b76cfbcfd-9ccx4 started09:41:29Z. No health/inference/configmutation byparent. New ignoredstatus ../status/2026-10-28-l40s-gpu-test-resume-workspace-state.md.
- **Decision and impact:** Reuse pre-existingpod, no PATCH or startuptrigger unless a separately justified failure requires one. Actualready8 andvalidcounterproof beforeload. Preserve min1 and pre-existingresource aftertest; this ownership-aware cleanup differs from historicalzero closure, and was surfaced to the user beforeacting. Codegate continuity holds; onlyoperational/Markdown changes planned.
- **Next action:** One bounded primary operation and independentrow/native/math verification, distinctl40s0944 artifacts; no hiddenretry or loss of oldevidence.

#### Checkpoint 2026-10-28T10:19:28Z: GPU readiness proven and UUID normalization corrected

- **Event:** ExistingL40S has8readyCUDAmodels; a realdiagnosticbug, notGPUcapacity, blockedmonitoring. Correctedofflinepackagepassesquality and isreadyforliveverification.
- **Planner prediction:** Counterproof beforeload, exactCUDA/NVMLidentity, no fabricated0 and no retrying measuredrequests. Mechanicaldiagnosticcorrection preservesmodel/application behavior.
- **Subagent claims:** Backend-a reusedpodwithoutPATCH/health andfoundone ownerfailureuuid_invalid, no warmup/measurements. Its offlinefollow-up adds documentedCUuuid.bytes support andfive tests; onlynewmonitor andtwotestsmodified.
- **Orchestrator finding:** Parentparsed5535savednumericrecords: exactlyreadyPIDs83–90, owner83singleuuid_invalid. OfficialPyTorchC++binds_CUuuidwith.bytes16uint8list; originalnormalizer rejected thatobject. Fixacceptsstrict16-octetshapes/rawbytes, notarbitrarystrcoercion, and exactNVMLmatchremainsmandatory. Singlewritermechanicalfix isappropriate, not anunknown-algorithmrace.
- **Independently verified facts:** Parentfull1041tests/no skipsPASS in27.941s underbranchcoverage; new39executablelines andallbranches covered, wholelinecoverageabout90percent/combinedbranch89percent. ExplicitPython3.14 interpreterfocused69testsPASS afterinitialpythonaliasabsence. Parentreadfix/tests, comments0/whitespace/appDockerPASS. quality-gate-aPASS. Defaultarchive02997f57unchanged. NewmonitorSHA937623dc1e4f14934e331bfcbd3a926c2093a45d505475e8cf9232adb7b6f97d; GPUarchive6c84cf08d6c5299ab520373c6e78bebd3c7797fd6f3634e89c98ed19aabae7a8; runidverda-20261028-gpu8-uuid; canonicalprofile3cc02fb1c11dba32e456020e14c89a1683d9717500a2beb49197a31d11b2a877; patch38cc3656f4c67c3fed5d5953061244184e16436acc3cd209f6ca9b4d6acbede0. Cmd56/env49/allvalues<=253. No inferenceyet.
- **Decision and impact:** Advancequalitycursor fornormalizer only; API/auth/sensitivedata/model unchanged, no coresecuritygateeligible. Applyingfix necessarilyreplacesfailedmonitor; preservefinaluser-min1 butbriefcontrolledmaintenance isneeded. PublicAPIhasPOSTpause/resume/restart, no exposedrolloutstrategy. Toavoidassumingrestartdoesnot surge2GPUs, pause/waitactualzero, patchwhilepaused, resumeonce andrestoreoriginalwarmminimumifneeded. ThisnewnecessitysupersedesV010'spredictionofnorestart, notitsfinalresourceownershiporoneGPUlimit. Briefrestartcommunicatedbeforeaction; normaltestdeploymentmaintenance iswithinrequesteddiagnosticwork, notproductionHAprovisioning.
- **Next action:** Singleboundedcorrectedrolloutandfixedload withfreshcounterproof, preservingallpartialresults andnewprefix; no hiddenrerun.

#### Checkpoint 2026-10-28T11:10:41Z: complete measured GPU matrix independently verified

- **Event:** Phase7 completed with fully accounted preliminary deviations, not a claim of an error-free entire procedure.
- **Planner prediction:**402fixedmeasuredrequests, everyburstpersisted, realownerNVMLsamples afterready8, sameB1/model/image, oneGPUmaintenance andfinaluser-min1 preserved.
- **Subagent claims:** Primary-a reports402successes,81bursts,27groups, onepause/PATCH/resume, no scalingPATCH, fixednewprofile;698samples/310active, oneexcludedwarmup andoneadditionalunauth404. Initialforwardreadinesscursor missedlateevents and wasrecoveredthroughfullpodreread beforevalidwarmup.
- **Orchestrator finding:** Accepttimedmatrix onlyafter fullraw/nativecheck. ExtraunauthPOST wasunplannedpreliminary, provider-rejectedbeforeapp, retainedandnotcredited; exactly402validtimedcalls. Ready-snapshot367 andfinal698 coverdifferent endtimes, notcontradiction. NVMLactivitynotSMoccupancy, powerbelowcapdoesnotprovenonsaturation. No strongerCPU/GPUbottleneck orproductionclaim islicensed.
- **Independently verified facts:** Parentvalidates402uniquecompositeIDs/status/bodyd2a274f2/oracleddda56ee/timing/overlap, entire81burstplan andallrawmeans/p95/RPS. Calculatorverifieslatencymeans/highloadRPS; byte/GiBconverter andexplicitmW/1000=W verified. Parentindependentlyselects310activeowner82samples fromactualtransportwindows, recomputescorrelationexactly; GPUmean51.0516/max100,powermean186.498W/max279.075W, min40samples/case. Native6shortqueries recover331GPU/1328baseevents aroundmatrix andmatchall310usedsamplesexactly, PIDs82–89/nochurn. Matrix10:46:15.855979–10:51:43.096496Z. Oldpoddeleted10:39:14Z, newpodscheduled10:39:44Z, provingnooverlap. Currentexactnewentry/all49env,L40S1,min1/max1/32,one runningpod, providerupdating. Privacy56files/noactualcredentials,21newfiles600, no savedrunner/client. No sourcechangedafterqualitycursor.
- **Decision and impact:** Closewiththerequesteddata/report, preservewarmuserresource andreportcontrolstatusupdating. All402measured200, no measuredfailures orreplay; wholeendpointprocedure404calls=402measured+1authwarm+1unauthextra. No original/fourcopyrestore, alternativehardware,image/model/batchchange orproductionpromotion. No codegate afterMarkdownonlyclosure; coresecurityeligibilityunchanged.
- **Next action:** Deliver ../reports/2026-10-28-verda-eight-model-gpu-profile.md; futurebatchprofilingonlyundernewscope.

## Plan-variation ledger

### Variation V-001: enforce the global client budget outside the measurement library

- **Baseline reference:** Phases 2 through 5 require bounded execution, finite transport calls, complete outcome retention and no abandoned local client resources.
- **Discovered evidence:** The measurement library's transport timeout is caller-enforced and its setup barrier has no internal timeout. A requested hardening subtask refused without editing. Parent inspection confirmed the limitation; a fault-injected subprocess with a missing barrier participant was stopped by GNU timeout, returned 124, was reaped and started zero senders.
- **Decision:** Keep the independently tested measurement library unchanged and require a hard external process watchdog for every live calibration/run, in addition to finite socket timeouts and the overall cloud budget. Do not claim an internal barrier deadline or server-side cancellation. A killed or incomplete cell remains unavailable, with preceding incremental evidence preserved and no hidden rerun.
- **Scope and downstream impact:** Only execution supervision changes; no application behavior, client-body contract, authentication or experimental matrix changes. Provider cleanup must remain possible through a separate management-only action after a client deadline.
- **Approval:** Existing user experiment approval applies; this is equivalent enforcement of the original boundedness requirement, not a scope reduction or permission to waive a failed gate. Independent quality judgment remains required.
- **Resolution:** Phase 2 checkpoint 2026-10-27T12:02:26Z; acceptance is pending Phase 3 judgment.

### Variation V-002: pin the archive build environment

- **Baseline reference:** Phase 3 freezes exact source and activation artifacts before live use.
- **Discovered evidence:** Artifact generation under system Python 3.14.7/zlib-ng produced archive `5949e3...` and correctly stopped. Parent independently rebuilt with both interpreters: all archived source hashes are identical, but compression differs. The prescribed Python 3.11.16/zlib 1.3.2 reproduces reviewed archive `3c595880...` exactly.
- **Decision:** Build every activation artifact with the existing prescribed Python 3.11 verifier. Do not waive a mismatched archive hash or treat different compression as a source change. The runtime only decompresses the pinned bytes; no recompression on the GPU is required.
- **Scope and downstream impact:** No source or user-visible behavior change. All four profiles were regenerated and independently compared with the same reviewed builder and environment.
- **Approval:** Existing experiment approval applies; no additional resource or behavioral change.
- **Resolution:** Phase 3 checkpoint 2026-10-27T12:31:09Z and private activation manifest SHA256 `5498e8272a64682b63bb0f70240ac5fc1f9e1a363ab30d1d5820c1b453b82e27`.

### Variation V-003: honor the observed per-argument command limit

- **Baseline reference:** Phase 4 expected the self-contained command to be accepted using the published API contract.
- **Discovered evidence:** Scaling PATCH succeeded asynchronously. Two known old-format deployment requests were rejected atomically; the controlled diagnosis returned `Each argument must not exceed 253 characters`. The OpenAPI extract did not publish this bound. No model was loaded or measured by those rejected requests.
- **Decision:** Retain the same trusted self-contained Python/bootstrap/archive approach, but reconstruct it from <=240-character argv chunks after SHA256 verification. Reset argv to the original Gunicorn options before execution. No network code delivery, new image, changed inference, model, precision, matrix or resource allocation.
- **Scope and downstream impact:** Only package.py and packaging tests changed. All old artifacts remain preserved; distinct argv253 profiles and manifest are used. The package correction passed both deterministic and independent quality review. The new manifest SHA is ae69a08c8d75ed12c98511c1c82fbdd41331c1bc1c1bab66631bf36a1cf7df62.
- **Approval:** Existing experiment approval covers this equivalent transport correction; no agreed observable behavior or requirement changes. User retention instruction remains active.
- **Resolution:** Phase 4 checkpoint 2026-10-27T16:22:45Z; corrected N1 activation is the next action.

### Variation V-004: compact the self-contained package for both observed argv bounds

- **Baseline reference:** Phase 4 command delivery and V-003's per-argument adaptation.
- **Discovered evidence:** The argv253 request was atomically rejected because cmd may contain at most64 elements. No GPU ran from that rejected format. Both64-elements and253-characters bounds must hold together.
- **Decision:** Ship only GPU runtime/fixture/source init files, omit build-only packaging and local guard modules, and use bounded compressed transport plus hash-verified verifier and source. Preserve the original factory, argv, env8 and model behavior. Move the unchanged local guard to resources.py with a compatibility wrapper.
- **Scope and downstream impact:** Parent verified exact guard AST equivalence, fresh-child import without omitted modules, 969 tests without skips and coverage above80 for each changed file. Portability tests initially failed under Python3.14/zlib-ng; inclusive253-character chunks give headroom and both 3.11/3.14 tests pass. Independent quality returned PASS. Final compact profiles use61 arguments, max253 characters and15292 serialized bytes; archive02997f5797c376163051c1c8c5685f617be93077ebe0ed5b85e7d9dcc0dda753. Native N1 startup has now proved the image's LZMA integration.
- **Approval:** Existing experiment approval applies to equivalent delivery; no runtime downloads, new image, secrets, inference or resource-allocation change. Previous rejected artifacts remain preserved.
- **Resolution:** N1 actual activation/readiness and Phase4 completion checkpoint 2026-10-27T18:40:50Z.

### Variation V-005: explicitly budget tasks when the leaf cgroup reports no PID cap

- **Baseline reference:** Hypothesis7 and Phase5 require conservative resource guards and prohibit assuming an unknown PID limit is unlimited.
- **Discovered evidence:** Parent's independent native-log query recovered null PID limits with reason limit_unavailable in every serving event; pinned parser emits this only for literal max. Missing and invalid files have different reasons. Finite RAM/GPU measurements leave large headroom; the old guard conflated this explicit uncapped leaf state with missing data.
- **Decision:** A local-only opt-in policy may use a separately declared finite experiment task budget512 only with both proven unbounded state and exact native reason. Unknown/missing/invalid limits remain blocked. Any actual finite PID cap takes the minimum with the declared budget. Preserve actual pids_limit null or its real value, label effective guard/budget/source separately, use a distinct budgeted-success reason and retain20 percent headroom. Hidden ancestor/host limits remain unknown and can still cause fork/thread denial; this is not a provider quota or guarantee.
- **Scope and downstream impact:** Only resources.py and focused tests changed; GPU archive/runtime/profiles and N1 measurements are byte-identical. Analyzer-a conditionally accepted the distinction. Parent ran972 tests without skips, resources coverage97 percent, and independent quality-gate-b returned PASS with the explicit hidden-limit advisory. Local controller SHA23b230e6c59986a575f632159de2b9636de5cd2cff99a6955c9f5ac07596c907. Conservative N1-basis required task counts for N2/N4/N8 are105/210/420 under512; RAM/GPU requirements are below actual finite capacities. These are projections, not measured higher-count results.
- **Approval:** Existing bounded experiment approval applies; this corrects a known-unbounded versus unknown classification without increasing any allocation or allowing unknown-as-unlimited behavior. No default budget is inserted and no known smaller quota can be overridden.
- **Resolution:** Local-controller quality PASS and Phase4 completion checkpoint; every subsequent candidate still requires fresh evidence and guards.

### Variation V-006: retain and disclose the N8/CC1 replay

- **Baseline reference:** Hypothesis8 and Phases4–5 predeclare three bursts per cell and prohibit replay/discard.
- **Discovered evidence:** Attempt1 N8 has three validated CC1 rows but an unconsolidated zero-success aggregate. Stop reason is pid_limit_unknown; the empty-window cause is an operator claim, not a saved executable trace. It restored P4 atzero, then repeated the full N8 matrix, producing189 more successes. All first-attempt artifacts remain in the separate attempt1-guard-bug directory.
- **Decision:** The replay is not a clean-method outcome or retroactively approved. Preserve both attempts and report all six CC1 responses as a descriptive post-hoc pool. First3 mean1.925678s, main3 mean1.806289s, all6 mean1.865984s. Other N8 cells use the declared threebursts. No more reruns to hide or balance the deviation.
- **Scope and downstream impact:** Actual totals759/739 success include main756/736 plus3extras. Provenance changes, not body/runtime/model/finalprofile. The pooled low-load cell is not homogeneous; do not claim clean-protocol comparability.
- **Approval:** User approved four variants and final retention, not a waiver of method rules. No retroactive acceptance or quality-FAIL-to-PASS conversion is claimed. Delivery explicitly states the limitation.
- **Resolution:** Phase5/6 closing checkpoints and final report deviation section.

### Variation V-007: user-authorized direct GPU observation on eight copies

- **Baseline reference:** Original B1 comparison and Phase6 were completed; its telemetry measured VRAM but not GPU activity. The prior closure did not authorize further runs.
- **Discovered evidence:** User now provides provider utilization charts and explicitly asks for monitored tests directly on the eight-model setup. Parent verifies the public API has no observed-utilization endpoint.
- **Decision:** Accept a new independent N8/B1-only observation experiment under Phase7. Keep old raw rows/report and source behavior untouched. Add only bounded diagnostic sampling and reuse fixed synthetic loads; do not claim to test larger batches.
- **Scope and downstream impact:** Opt-in diagnostic wrapper/packaging and local correlation/load helpers with fake tests may be necessary. Any executable delta requires80percent delta coverage and independent quality PASS before activation. Core API/authentication/sensitive-data handlers remain outside the intended delta; reassess security eligibility on actual output.
- **Approval:** Explicit current user requests authorize monitored eight-copy load on the same existing allocation. They do not waive gates or the no-replay rule.
- **Resolution:** Phase7 checkpoint and forthcoming new report; original closure below describes only the preceding four-way delivery.

### Variation V-008: carry the diagnostic archive within the native environment-string bound

- **Baseline reference:** Phase7 first opt-in environmentcarrier expected a single bounded19688charvalue to be accepted.
- **Discovered evidence:** RejectednativePATCH400 explicitly limits eachenvvalue to253characters; full publicschema doesnotpublish this constraint. OldN8definition was preserved, noGPUhealth/benchmarkstarted.
- **Decision:** Hybrid signedtransport embeds9844base64chars in verifiedbootstrap and carries9844chars in39ordered envvalues<=253bytes; allpopped beforeexec. Cmd56/env47 staybelow64withheadroom. Hash/path/mode/decompression/sizegates and all runtimebytes unchanged.
- **Scope and downstream impact:** OnlyGPUbuildpackageandtests changed; defaultprofilebaseline unchanged. Parent1036tests/90percentoverall,95percentGPUpackage and qualityPASS cover correction; no credit from rejected activations.
- **Approval:** Equivalent delivery correction under user-authorized8copyobservation, not a newmodel/API/resourcebehavior. Old failureevidence preserved.
- **Resolution:** Phase7 checkpoint2026-10-28T00:45:48Z and correctedprofilee0ee052e.

### Variation V-009: preserve the user's RTX PRO 6000 selection and qualify compatibility

- **Baseline reference:** Original and Phase7 runtime/readiness were qualified only for L40S and cu126 image.
- **Discovered evidence:** User reports a manualGPUchange; nativecompute nowRTXPRO6000. Existingdiagnostic intentionallyrejectsnonL40S, while selectedBlackwellfamily also requires imagearchitecturevalidation.
- **Decision:** Preserve currentGPU and hold load beforeknown-incompatibleprobe. No assumption that8copies/results remaincomparableacrosshardware, no silentGPU/image/pinreplacement. Productionavailability recommendations do not constitute appliedproductionsettings.
- **Scope and downstream impact:** A compatibleimage and configurabletrustedGPUcriterion need their own approvedimplementation/verification slice. Currentchangesareonlyread-onlychecks andtraces; no newcodegate eligible.
- **Approval:** Manualhardwareselection is user-owned. It doesnotbyitselfapprovechangingtheimage/runtimepins, reservedcapacitycontract, additionalGPUs orwarmproductionreplicas. Ask beforethesechanges.
- **Resolution:** Phase7checkpoint2026-10-28T09:18:27Z andupdatedGPUprofilereport.

### Variation V-010: reuse the user's already-running L40S and preserve its minimum1

- **Baseline reference:** Phase7 originally began athealthyzero/min0 and endedatnaturalzero aftertask-createdactivation.
- **Discovered evidence:** User requests returntoL40S; nativecurrentpodstarted09:41:29Z beforetask09:44, min1/max1 alreadyset, sameapprovedGPU/model/image/eightcopyprofile.
- **Decision:** Reuse currentpod withactualready/countergate; no scaling/deploymentPATCH or unwanted shutdown. Preserve pre-existinguser-ownedresource/min1 ratherthan treatingitasnewtestresource. No claim about warm-idle billing or contractualcapacity follows from thissetting.
- **Scope and downstream impact:** Same402callload, body/oracle, timings andoneGPUlimit; newartifactprefix andexplicitlifecycleownership. No code/API/model/batch/image change ornewresource.
- **Approval:** ExistingeightL40S/devtestpermission plusnewexplicitusertestrequest; userconfiguration ispreserved, not a newly imposed billableminimum. Ownership/min1difference explainedbeforeoperation.
- **Resolution:** Phase7checkpoint2026-10-28T09:45:10Z andforthcomingtestevidence.

### Variation V-011: support the documented CUDA UUID object and restart only the diagnostic

- **Baseline reference:** Phase7 expected PythonUUID/string; V010 predictednocodechangeandthereforenorestart ofexistingwarmreplica.
- **Discovered evidence:** RealGPUready8 butsampleremitsuuid_invalid; officialPyTorch_CUuuidexposes16-byteoctetlist, missingfromnormalizer. No inferencewasstarted. Fiveformatregressions reproduceandcoverfixwithoutTorchdownload.
- **Decision:** AcceptstrictdocumentedUUIDdatawithoutlooseningNVMLidentity. A controlledoneGPU restart isnowneededtoapplydiagnosticfix, retainingmodel/image/B1/eight/finaluser-min1. No forcedpermanentzero, noadditionalGPUorproductioncapacity.
- **Scope and downstream impact:** gpu_monitor.py plusmonitorregressiontests andupdatedpreciseGPUpackagegoldens. Sourceapp/runtime/packagebuilderotherwiseunchanged; newGPUbundle/profilehashes, actualNVMLproofstillpending. Parent1041+69tests, delta100percentcoverage andqualityPASS.
- **Approval:** Correctsourdiagnosticimplementationtomeetexistingmonitoringrequirement, no API/businessbehaviorwaiver. Userinformedofbriefreplicamaintenancebeforeoperation; existingtestdeploymentchangepermissionapplies. Finalmin1andoneGPUremainbinding.
- **Resolution:** Phase7checkpoint2026-10-28T10:19:28Z andcorrectedprofile3cc02fb1.

### Variation V-012: disclose preliminary authentication and log-ingestion deviations

- **Baseline reference:** Phase7 plannedonevalidexcludedwarmup andonecontinuous402callmatrix afterready/counterproof.
- **Discovered evidence:** Forward-onlylogcursor missedreadyingestion; fullpodreread recovered8ready/367validsamples beforewarmup. OneadditionalunauthenticatedanalysesPOST10:45:25Z returnedprovider404/19bytes; preservedoutsidewarmup/matrix. Validwarmup10:46:13.875147–10:46:15.850687Z, measuredstart10:46:15.855979Z.
- **Decision:** Retainbothpreliminaryoutcomes, discloseextracall, andaccount404endpointPOSTs total. Do notretroactivelycallitplannedorclaimwholeprocedurezeroHTTPerrors. The402timedrowsarecomplete,unique,all200/oracle-matchedandwere notsubstitutedorreplayed.
- **Scope and downstream impact:** Provenance/operationphasehandling, notmodel/API/body/sourceorstatisticchange. MeansandGPUwindowsuseonlydeclared402calls; preliminary404rejectedbeforeappandbeforemeasuredwindow.
- **Approval:** UserauthorizesGPUtest, not a retroactiveprotocolwaiver. Deviationisexplicitlyreported, notusedtoconvertfailedgateorfailedmeasuredrowintopass.
- **Resolution:** FinalPhase7checkpoint andreportdeviationsection; allsourcequalitygatesremainPASS.

## Closure evidence

### Final outcome

The originalfour-waycomparison iscomplete: [its report](../reports/2026-10-27-verda-model-copies.md) retains759actualattempts/739successes/20HTTP429 andV006methodlimitation. Its historicalclosure retainedN8atidle0; no pastdataarerelabeled.

The separatelyrequestedPhase7 isnowcomplete: [GPU/power report](../reports/2026-10-28-verda-eight-model-gpu-profile.md),402measuredvalid200,310activeNVMLsamples, quantitativeall6cases, no measuredchurn. CorrectedN8/B1/c1d9 isretained withtheuser'sminimum1, maximum1, ingress32 andone runningL40S. Providerstatusupdating andpreliminaryextra404aredisclosed. No productioncertification, largerbatchtest, automaticwinner, originalrestore, staging/commit/push isclaimed.

### Quality and security evidence

Final tools/controller passed972parent-run tests without skips, approximately92percent overallcoverage,97percent localguardcoverage and all applicable independentqualityjudgments. GPUarchive02997f57/runtime/profiles stayedunchanged duringmeasurements; externalprocesswatchdogmandatory. No applicationAPI/authentication/sensitive-datahandler changed, so no additional core-surface security gate was triggered. This is not a securitycertification or waiver of the operator deviation. Final privacy/source/report/whitespace checks pass; later changes are Markdownonly, human-reviewed without another automatic codegate.

### Operation record

[Shared GPU-service operation](../operations/2026-10-21-runpod-service.md) records bothcompletedfour-waydelivery andcompletedPhase7, preservingallolderblockedattempts/history. [The GPUreport](../reports/2026-10-28-verda-eight-model-gpu-profile.md) contains theactual402row/310sampledata, currentwarmN8state, applicablecodegates andexplicitmethodlimitations.
