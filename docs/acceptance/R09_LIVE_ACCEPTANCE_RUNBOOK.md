# R09 owner-controlled live acceptance runbook

**Current state: LIVE_ACCEPTANCE_NOT_EXECUTED. PRODUCTION_PROMOTION_NOT_APPROVED.**

This document is an acceptance procedure, not permission to execute it. R09 preparation only authors documents/contracts and runs safe offline tests. Do not start services, connect to PostgreSQL, execute SQL, create/reset/restore/seed a database, open a browser or read held-out cases under this preparation instruction. Design APPROVE and passing pytest counts are not live acceptance.

Reviewed source baseline: `b926a9c17a83f73800db4a3b8aa0ee03d444743c`; approved design: `3c9fb146ca4ca0f98bd09d254b15931e547cbc47`. Current `AGENTS.md` manual handoffs and the owner's specific phase authorization govern. FRD 1.8 and actual source contracts take precedence over illustrative historical prose. Do not alter historical reviews.

## Execution charter and common stop rules

Before each future phase, the owner must identify the exact Git revision, Windows workspace, approved executable/composition hashes, permitted operation class, loopback service tuples, source/clone identities, protected databases/tables, allowed personas/modes/case partition, private evidence location, operator/reviewer, time/resource limits and stop/cleanup authority. Approvals must distinguish observing host files, starting/stopping a model/UI, opening read-only database sessions, session-local setup, tuning evaluation and any setup mutation. Broad agreement with this runbook is insufficient authorization for unspecified live operations.

Store credentials, raw native responses/prompts, fixture rows, reference results, canaries and actual holdout metadata outside Git in owner-controlled private storage. Publish only independently reviewed redacted evidence and opaque references using [the evidence contract](R09_EVIDENCE_CONTRACT.md). Record UTC timestamps, exact Git SHA, actual commands privately and the corresponding public procedure reference. No script should infer owner approval from a hash alone.

STOP on unexpected identity/destination, source/clone mismatch, missing reviewer input, a secret in public output, forbidden returned data, unsupported protocol, budget exceedance, uncertain cleanup, or unexpected mutation. Preserve private evidence; do not retry under administrative credentials, relax controls, reset databases, broaden parser profiles or fix production source. A production defect requires a separate owner-authorized remediation and independent review. Never bypass an automatic policy rejection. Rollback means end/cancel the approved request, roll back/discard its fresh lease and stop only owned processes where authorized; it never means reset/drop unrelated data.

The [31-item acceptance matrix](R09_ACCEPTANCE_MATRIX.json) specifies exact requirements and GO/NO-GO conditions. The initial [manifest](R09_EVIDENCE_TEMPLATE.json) records every criterion NOT_RUN. A phase remains blocked until its conditions have actual evidence. Final GO is unavailable while any mandatory live evidence is absent. Even evidence completeness does not authorize promotion, merges, historical PR closure or the next agent.

## R09_PHASE_A — Read-only local preflight

**Entry:** explicit authorization to observe the selected clean Windows checkout and named local assets, without service startup or database access. Preserve unrelated work using a clean checkout of the shared branch. Do not reset/stash it. Confirm R08's actual merge SHA independently; the current preparation baseline is not automatically the future execution revision.

**Permitted observations:** Windows version/CPU/RAM and installed executable metadata; Python, psycopg2, Streamlit and SQLGlot versions; Git branch/commit/status; hashes and existence of named files; approved non-secret service configuration and exact numeric loopback endpoint allowlists. Reading a file must not execute a launcher. Checking PostgreSQL/model version via a connection or starting an executable is outside this read-only phase unless explicitly separately authorized.

Future operator command examples, not executed by R09 preparation:

```powershell
# Run only in the owner-approved working directory.
git branch --show-current
git rev-parse HEAD
git status --short --branch
Get-FileHash -Algorithm SHA256 -LiteralPath 'schema.sql','seed_data.py','fixture_manifest.json','fixture_pg_dump.sql','policy/access_matrix.yaml','semantic/catalog.yaml','src/inference/prompt_template.txt','STARK_T2SQL FRD 1.8.txt'
# Inspect only the explicitly named model/launcher files supplied by the owner;
# never print private environment variables or execute a discovered binary.
```

Compare frozen bytes with independently reviewed digests, then corroborate the dump against its actual manifest field (`fixture_digest` requires an explicit digest-field path). The committed R02 fixture is a reviewed synthetic baseline, not recovered historical data. Record the exact Python/runtime versions actually installed, not assumed environment names.

Review `ResourceBudgets`: `model_memory_limit_mib`, `database_work_mem_kib`, `database_temp_file_limit_kib` and `measurement_source` default to None. Require independent measured inputs and enforcement evidence; 5,120 MiB in the design is not an installed/enforced default. Record what memory metric is bounded (process/children/resident/commit), approved ceiling and sampling method. A resource file/hash or service declaration alone cannot establish enforcement.

Check the immutable model-card template and genuine `ReviewedTemplateContract`, including exact owner-approved as-of prefix, two QUESTION substitutions and schema substitution. Bind dates before SQLCoder context; no `:as_of_date` survives. Unit/template fixture metadata is not automatically a deployment approval. Do not fabricate a prefix or modify template bytes.

**Evidence/exit:** A01-A04 artifacts, versions, configuration review and explicit unresolved prerequisites. Missing actual model, launcher, owner contracts or budget evidence is BLOCKED. If only files were inspected, report that scope, not live service health. No cleanup mutation is needed.

## R09_PHASE_B — Controlled live model validation

**Entry:** A preflight approved; separate owner authorization names genuine SQLCoder-7B-2 Q4_K_M weights, post-2024-02-07 provenance, exact launcher/executable hash/build, approved startup arguments, inference endpoint and stop authority. No software download/install or security-setting changes are implicit. Inspect installed help/version only under the later authorized procedure; launcher flags differ by build. Do not copy the review's illustrative `--slots` or caching flags as verified commands.

**Operations:** launch only the approved local model process; corroborate the real listening address/PID and one inference slot, prompt-prefix caching, actual build, CPU/offline routing and measured resource enforcement. The client requires exact HTTP at `127.0.0.1` or `::1` on an explicit allowlist; the owner commonly plans port 8081, but a different configured port requires its own exact approval. No external bind or proxy/DNS fallback.

Use the current guarded client and actual R01 prompt builder to submit an approved **tuning** question with its explicit as-of date and reviewed context. Do not replace the full prompt with bare `SELECT 1` and claim template/pipeline acceptance. Retain full native response privately; create a separately reviewed redacted metadata artifact excluding content, prompts and private paths. Bind its digest to the actual model/build/launcher/run. Requested `response_fields` may be omitted; that is not evidence of a stopping reason.

Observe all applicable protocol outcomes through the full pipeline:

- Semicolon proof requires reported word-stop evidence and `stopping_word == ";"`. The native response may omit the stopping word from content; an output suffix is not proof.
- EOS must have genuine native evidence. Compact `stop=True` below the cap stays STOP_REASON_UNSPECIFIED, not EOS or semicolon. SQL validation does not prove native termination. If the installed build cannot supply required termination evidence, B02 is BLOCKED; do not relabel synthetic tests as compatibility.
- Explicit limit or exhaustion without a verified word stop must raise the existing GenerationTruncatedError/FC-TRUNCATED-GEN before extraction/execution. Context truncation and conflicting metadata fail closed.
- Measure real latency and memory under approved normal workloads; observe deadline, cancellation, foreground socket closure and one-flight concurrency. Distinguish elapsed FC-TIMEOUT-GEN from token exhaustion. Capture genuine cleanup and denied duplicate submission, not just final return codes.

**Isolated diagnostic:** production decoding stays temperature 0, seed 42, max_tokens 300 and stop `[";"]`. A five-token experiment requires its own owner-approved diagnostic composition/request, on the model-only isolated lane, with no database capability or candidate execution and a separate diagnostic run identifier. Never patch `DecodingDefaults`, change the production baseline or score that diagnostic as a production E2 result. A deliberately shortened timeout likewise needs a separately declared diagnostic configuration and approval. If the actual model cannot reproduce a needed state safely, leave that check NOT_RUN/BLOCKED.

**Evidence/exit:** B01-B05 with actual native metadata review, process/resource observations, UTC timestamps, private logs and redacted evidence digests. STOP on unavailable build evidence, native ambiguity, false success, overshoot or uncertain owned-process termination. Do not retry with weaker output parsing. Only stop the owned process under the granted stop authority; do not kill unrelated processes.

## R09_PHASE_C — Disposable PostgreSQL security validation

**Entry:** separate authorization to contact the exact PostgreSQL 16 instance and an independently provisioned disposable clone. No setup mutation is included. First obtain read-only catalog/identity observations and compare source and clone OIDs, names, instance tuples, dump hash and installed policy-state binding. A database name or COMMENT alone is insufficient.

`EvaluationCloneProvenance` and `_establish_clone()` corroborate the full marker: kind `stark_disposable_evaluation_clone`, approved clone token, distinct source database, actual source/clone OIDs and matching fixture digest. Confirm the clone is distinct from **every** ordinary business alias and unrelated/production databases. Check ownership, nonadmin SELECT-only baseline role, effective ACLs and no CREATE/TEMP/DDL capability. Do not create a marker to make an unknown database pass.

**Observation versus session effects:** fixed catalog SELECTs observe identity/settings/ACL/policy metadata. Opening a read-only connection still creates a session. Principal `set_config(..., true)`, SET LOCAL ROLE, transaction settings, cancellation and rollback are session effects and need authorization. CREATE/ALTER/GRANT/REVOKE, policy application, restore, reset, seed, truncate and database COMMENT changes are setup mutations requiring their own named-target approval. None is part of this phase's default observation scope.

Resolve actual personas via the trusted registry, using separate administrative **fixed source** only where required for fixture identity derivation. Four choices are payroll, hr_1, hr_2 and sales; three policy login roles are derived from the matrix. Both HR principals need independent nonempty distinct scope observations, not one representative copied twice. Sales is actual direct reports of the fixture-derived Sales manager, not all employees of a department. Private principal/row observations stay private.

Verify `session_user == declared login` and `current_user == session_user` before the role transition. Observe the source executor's order: fresh audited connection, read-only, principal as TEXT under the login, SET LOCAL ROLE business identity, reviewed regenerated SELECT, bounded fetch, transaction completion and discard. Runtime/evaluation sources discard fresh leases; do not invent a reusable pool. After the local role transition current_user is the business role. Membership is exactly the policy business role with safe PG16 membership options and no extra elevation.

Run authorized fixed `AuthorizationObserver`/canonical probes, not arbitrary model SQL under an administrator. Verify all 273 table/column probes and Sales SELECT-star denial; use independent persona-equivalent counts for employees and leave balances, with **both** HR principals. Denied HR employee_number/compensation and Sales forbidden projections must produce observed 42501 at the database, not a validator stop. Check employees/leave FORCE RLS, explicit unrestricted-role policies, HR zero-argument STABLE definer owner/body, no runtime CREATE shadowing, PUBLIC ACLs and installed policy hash plus behavior.

Use actual configured limits: initial statement timeout is 15 seconds, not the review's hardcoded five; the trusted path is pg_catalog, matrix schema, pg_temp, not `stark, public`. Audit persistent LOGIN defaults and measured work/temp budgets. Do not replace them with handwritten settings to obtain passing probes.

**Dangerous negatives:** DML/DDL, SET/RESET ROLE and catalog/resource attacks remain unexecuted where mandatory harness safety rejects them. Do not submit the review's INSERT example to prove a denial. A separately approved defensive diagnostic must remain read-only and bounded; expected SQLSTATE depends on the actual layer (for example a read-only violation is not necessarily 42501). The login legitimately needs set_config before role switching; business-role function revocation does not revoke the SQL SET path. FRD's principal-spoofing/single-layer dependency must be reported accurately rather than claiming universal DB prevention.

Future observational-test selection example, **only after a separately reviewed no-setup composition and evidence are approved**:

```powershell
$env:STARK_TEST_ENABLE_DB_INTEGRATION='1'
# Supply genuinely approved composition/scope paths privately first.
python -m pytest tests/test_database_integration.py::test_actual_matrix_access_equals_controlled_observations tests/test_database_integration.py::test_actual_sales_star_and_hr_employee_number_denied tests/test_database_integration.py::test_actual_four_scopes_match_independent_external_reference_counts tests/test_database_integration.py::test_authorization_observer_has_no_arbitrary_sql_entrypoint -q -ra
```

Do **not** enable DB integration and run the entire suite: `tests/test_seed_generation.py::test_opt_in_live_reset_with_actual_owner_isolation_proof` is a separate destructive-reset test. It requires specific reset authorization and R02 safeguards and is deliberately excluded here. Existing composition fixtures execute supplied Python after opt-in: independently inspect/hash the composition before import. They require workspace-local input paths; keep any non-secret composition untracked/locally excluded by the operator and real credentials/evidence private outside Git. No exclusion/configuration is created by this preparation PR.

**Evidence/exit:** C01-C08, actual PG16 identity and exact login/scope/SQLSTATE observations. STOP on unrelated target, elevation, role drift, missing scope input, unexpected row/column access or fixture ambiguity. Roll back/discard approved sessions; no database reset or cleanup SQL is inferred.

## R09_PHASE_D — Genuine E2/E6 tuning-only evaluation

**Entry:** B/C evidence approved; actual frozen tuning index/case provenance, reviewed parser profile, wall-clock AST-layout review, adversarial scope, projection mappings, canary selectors, `ScopeReviewStore` approved record bytes/pins, model/template/baseline/resource and policy bindings available. Reuse no test-only approvals as production approval. Obtain operation-specific owner authorization for each mode and target.

| Profile | Context | Candidate enforcement and route |
| --- | --- | --- |
| FULL, prompt v2 | Role-filtered physical and governed semantic context with explicit date | Reviewed validator plus restricted persona login on verified clone |
| NO_VALIDATOR, v2 | Same role-filtered context | Application entitlement validation bypassed; mandatory structural/function safety and restricted persona DB boundary remain |
| NO_PROMPT_FILTER, v2 | Full physical/governed semantic context | Validator and restricted persona DB route remain |
| UNCONTROLLED, v1 | Exact frozen full baseline DDL; no resolver/semantic catalog | Mandatory safety and dedicated nonadmin SELECT-only baseline login, only on independently verified clone |

Use `AblationHarness`, actual `RunPlan`, `GuardedCase` tuning loaders and `EvaluationJob`; do not replace them with scripted SQL labeled LIVE. Direct SQL runs are explicitly no-model evidence; model runs need a real tuning warmup that is not scored. Use one approved change/baseline at a time. Bind all FR-9.7 fingerprints and context size/threads/decoding/build/fixture/case-set metadata. No automatic case generation or holder of model-produced SQL may supply the oracle.

The actual existing tuning CLI (future only) accepts the reviewed source/hash and rejects HOLDOUT:

```powershell
# Each mode requires its own explicitly approved isolated evaluation decision.
python -m stark_t2sql.evaluation --execute --mode FULL --composition <reviewed-owner-composition.py> --composition-sha256 <actual-approved-sha256>
```

The composition must expose `compose_evaluation_job(root=..., mode=...)`. Its bytes are hash-checked before execution, but the hash is not owner authorization. No such composition is fabricated or run now. Repeat the exact CLI with other approved modes only after their entry conditions, actual clone evidence and private record lanes are satisfied.

Verify reference predicate/physical column lineage, mode/persona/principal/date bindings, actual source-versus-clone equivalence and independent reviewed result meaning. Controlled references use the trusted administrative lane with human-reviewed scope predicates; do not falsely claim that reference SQL itself ran under persona RLS. Full-scope baseline queries must not become a cross-persona oracle. Preserve typed comparator, multiset duplicates, Decimal HALF_UP rules, NULL/bool/date distinctions and approved bijective projection mappings.

Canary selectors must be genuinely reviewed and fixture-bound; only distinctive forbidden cells are queried. Mixed authorized/forbidden selectors retain forbidden cells; all-permitted/absent/distinctiveness failures remain unavailable. Salary dates are half-open and parameter-bound, latest applicable per employee with deterministic ordering. Never expose values publicly or call unavailable computation a leak clearance.

Classify using actual `FailureClass` values and `classify_failure()` order: observed leak; wall-clock violation; unscored safety/missing inputs; pass; extraction/generation and known SQLSTATE errors; reference-proven VALIDATOR versus legitimate OVERBLOCK; expected/unexpected permission cases; other SQLSTATE RUNTIME pending triage; genuine manual classification; unresolved intent pending. There is no FC-UNEXPECTED-DENIAL, FC-DB-* or invented catch-all. Safe stops are unexecuted, not evidence that PostgreSQL blocked SQL. A wall-clock layout review is AST/parser evidence, not a hardware latency measurement.

Reconcile all six counts: total = scored + unscored + unsubmitted; pending = unscored + unsubmitted; pending triage is a subset of failed scored cases. Preserve partial/cancelled/failed-warmup observations, missing inputs and metadata-only public records. Unknown/unscored cases prevent completion; do not remove them from denominators or label them passed.

**Evidence/exit:** D01-D10 across actual four personas/modes and redacted/private evidence lanes. Missing review, unsupported required parser construct, canary uncertainty, semantic ambiguity or unknown scope remains BLOCKED/NO-GO. The 32 excluded parser cases are not fixed by editing test approvals; a necessary production change requires a separate owner remediation/review. Roll back/discard approved connections and stop the run on defects; do not amend source here.

## R09_PHASE_E — Real browser walkthrough

**Entry:** separate owner permission to start the exact loopback UI process and use a local browser. R08's prior process launch was policy-blocked; no override or alternate security bypass is implied. A real browser walkthrough remains NOT VERIFIED until actually observed. AppTest results are framework/script evidence, not a browser session.

Start disconnected first. `python -m ops.serve --port <approved-unprivileged-port>` is the actual existing offline launcher: it removes `STARK_ENABLE_CONNECTED_UI` from its child environment. It cannot activate connected SQL. Check all seven entries in order: Health & Status, Architecture, Progress, Offline demo, Playground, Semantic Catalog, Access Policy. Preserve SIMULATED/DEMO labels, manual progress and truthful service states. Navigating or displaying E0 does not make it a live SQL result.

After B-D are independently approved and a **separate connected UI operation** is granted, the operator may set `STARK_ENABLE_CONNECTED_UI=1` only for the approved foreground Streamlit command and approved runtime inputs. Do not claim `ops.serve` preserves that flag. Keep numeric loopback binding, telemetry disabled and existing permission controls. Observe all four personas, selector above disclaimer captions, safe filtered catalog/policy views, one Ask request, disabled Ask while processing, status refresh, back/navigation and rerun recovery, exception hygiene and no raw SQL/credentials/trace in public state. Inspect an actual harmless allowed/blocked/scoped tuning scenario per persona.

Do not invent a cancel button: current UI provides Refresh status, while model/pipeline cancellation has an Event contract. Test available browser behavior and independently authorized backend cancellation separately. Record an absent UI cancel affordance as a limitation and ask for a separate remediation decision if the owner's acceptance requires it. Browser navigation is not proof that an active model/database request was cancelled.

**Evidence/exit:** E01/E02 with actual browser/build, UTC observations and redacted screenshots/record references reviewed for private data. STOP on duplicate Ask, stuck guard, unsafe errors or blocked launch. Only close owned tabs/processes under the approved cleanup authority; never overwrite progress HTML to make the UI appear accepted.

## R09_PHASE_F — Separate sealed governance and independent signoff

This phase does **not** schedule an automatic holdout run. Preparation reads no actual holdout question, reference, canary or exposure record. The initial manifest has no holdout case IDs. Deterministic `split_for_id()` uses a 70% hash threshold; small sets need not contain an exact 70/30 count. Do not rebalance or rewrite frozen IDs/payloads.

Before a future owner-approved sealed exposure, privately review the actual frozen index, prior exposure history, boundary schedule, isolated trace writer and explicit owner permit. The APIs are `HoldoutAuthority`, `HoldoutPermit` and `HoldoutExposure`, not HoldoutBoundaryController. First boundary is E8; later boundaries require actual `PriorE8Exposure` plus `DefinedBoundarySchedule` bound from recorded bytes. `RunPlan` requires the exact live permit/run/index match. Exposure is durably recorded **before** payload read; a failed ledger write must prevent access. Records/permits here are not generated, forged or inspected.

No current tuning command may accept HOLDOUT. A separate future sealed operator procedure, explicit owner authorization and independent boundary verification are necessary; R09's public evidence contract cannot issue that capability. Actual sealed traces/records stay in a distinct private lane, and only the permitted current question reaches the assessed local model. No reference answers, other cases or holdout examples enter prompts or agent context.

Independent reviewer checks F01/F02 and every mandatory matrix result, the genuine authorization chain, applicable skips and source/asset integrity. Missing mandatory live evidence means NO-GO. Preparation completion is never final live acceptance. Historical PR #1 closure, R09 promotion and PR #2-to-main merge remain separate explicit owner decisions. No automatic next agent, scheduler or progress update is authorized.

## Skip accounting and preparation-only verification

The starting safe offline baseline is 1,574 passed / 58 skipped / 0 failed. The existing 58 comprise 32 parser-representation exclusions, 16 wall-clock **AST review** input checks, six PostgreSQL integration checks, one direct database composition check, one live reset check, one adversarial scope review and one reference review. Genuine inputs, safe targeted selection and separately authorized live environments are required to resolve them. Do not enable the live reset via a blanket full-suite flag or invent expanded parser evidence.

Safe preparation commands below are the only commands in this document authorized by the current preparation request:

```powershell
$env:PYTHONPATH='src;.'
$env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
$env:STARK_R09_OFFLINE_ONLY='1'
python -m pytest tests/integration -q -ra
python -m pytest -q -ra
```

Six additional phase-evidence scaffolds intentionally skip without a separately reviewed provider. These skips are reported separately from the original 58. Even explicit replay opt-in supplies no provider or live authority. Report actual counts, not expected arithmetic. Later Antigravity verification owns manual progress/HTML updates and both local-copy hash checks; Codex preparation does not perform them.
