# Codex R09 work log

- **Gate:** R09, Issue [#11](https://github.com/Vivek-k24/Stark_T2SQL/issues/11)
- **Scope:** acceptance preparation only
- **Branch:** `codex/r09-remediation`
- **Integration baseline / R08 merge:** `b926a9c17a83f73800db4a3b8aa0ee03d444743c`
- **Approved design:** `3c9fb146ca4ca0f98bd09d254b15931e547cbc47`
- **Recorded:** 2026-10-16 UTC

**LIVE_ACCEPTANCE_NOT_EXECUTED**

**PRODUCTION_PROMOTION_NOT_APPROVED**

## Authority, baseline and preservation

The owner's current instruction authorizes a runbook, non-sensitive evidence contracts, safe integration scaffolding, offline tests and one draft PR. It does not authorize services, PostgreSQL connections/SQL, setup/reset/restore/seed, connected Streamlit, a browser session, live benchmarks or sealed holdout access. Issue #11's original live-execution wording is constrained by this later preparation-only instruction and its manual handoff. No next agent is started automatically.

The approved design commit adds `Antigravity_R09_Review.md` to the actual R08 integration merge. GitHub evidence confirms [R08 PR #23](https://github.com/Vivek-k24/Stark_T2SQL/pull/23) merged on 2026-10-16T00:43:38Z at the baseline above. R08's offline implementation approval is not live acceptance.

The primary `H:\STARK T2SQL` checkout was already on the shared R09 branch but contained unrelated changes to `Antigravity_Design_Review.md` and `Antigravity_R09_Review.md`. Those files were not edited, stashed or reset. Work took place in a clean clone at `H:\STARK_T2SQL_R09`, checked out on the **same existing branch** at the approved design SHA. No new branch was created and no branch was switched in the primary checkout. Its two pre-existing dirty paths remained present with the same diff statistics: 1,223 additions/one deletion and one added blank line respectively.

Read sources included `AGENTS.md`, applicable FRD 1.8 requirements, Issue #11 and its owner handoff, the complete approved R09 review, R01-R08 implementation/verification records, current inference/configuration/prompt contracts, persona/connection/grant/RLS contracts, evaluation reference/canary/comparator/failure/runner/holdout code, and actual external-input test gates. Historical records were left unchanged. Earlier gate approvals establish their recorded offline behavior; they do not supply missing native, database, browser or sealed-run evidence.

## Chronology

1. Inspected the existing branch, working trees, approved design and remote integration baseline; preserved the primary checkout's unrelated work by using the clean clone described above.
2. Reproduced the starting safe offline baseline using the existing Python environment: **1,574 passed, 58 skipped, zero failed**. No dependency was installed.
3. Reconciled the approved review against current source before defining acceptance operations. The discrepancies and remaining evidence gaps are recorded below rather than rewriting the review.
4. Added a six-phase, owner-controlled runbook and a 31-criterion GO/NO-GO matrix. Separated file observations, session effects, service execution and setup mutations; excluded destructive reset from blanket live test selection.
5. Added a public initial manifest with real frozen-file digests and **31 NOT_RUN items**, plus a pure evidence-validation contract. No live passes, human approvals, private credentials, native responses, canary values or holdout records were populated.
6. Added offline negative/positive contract tests and six evidence-replay phase scaffolds. The scaffold has no live collector or default evidence provider. Offline mode, absent opt-in and absent approved provider all produce explicit skips.
7. The first focused run exposed a test-import harness error: `runpy` did not register a fresh module in `sys.modules` before Python 3.12 dataclass annotation processing. Corrected the test to use an import spec and temporary registration; no production behavior or evidence requirement was relaxed. Added further matrix-binding/readiness/FAILED-status coverage.
8. Completed the final focused and full offline runs, reviewed scope and source integrity, and recorded the actual results below. Publication details are appended after pushing.

## Source discrepancies and resolutions

| Topic | Verified source and preparation decision |
| --- | --- |
| Four personas, three roles | Actual selectors are `payroll`, `hr_1`, `hr_2`, `sales`. The policy maps business roles to `stark_payroll_login`, `stark_hr_login`, `stark_sales_login`; business role names are not login credentials. Both HR principals require independently observed, distinct nonempty row scopes. Sales means the fixture-derived manager's direct reports, not a whole department. Public records contain only selector/business/login role names. |
| Holdout authority | Actual APIs are `HoldoutAuthority`, `HoldoutPermit`, `HoldoutExposure`, `PriorE8Exposure` and `DefinedBoundarySchedule`; no `HoldoutBoundaryController` exists. E8 is the first boundary; later exposure requires genuine prior E8 evidence and a defined schedule. The ledger must persist before payload access. The tuning CLI rejects HOLDOUT. A 70% hash threshold does not promise exact small-sample 70/30 counts. Preparation issues no permit and reads no genuine holdout record or payload. |
| Failure taxonomy | Actual enum values are FC-EXTRACT, FC-SYNTAX, FC-HALLUC, FC-VALIDATOR, FC-OVERBLOCK, FC-POLICY, FC-WALLCLOCK, FC-TIMEOUT-GEN, FC-TRUNCATED-GEN, FC-TIMEOUT-STMT, FC-LEAK, FC-RUNTIME, FC-SCHEMA, FC-JOIN, FC-FILTER, FC-AGG, FC-TEMPORAL, FC-SEMANTIC. There is no FC-UNEXPECTED-DENIAL or FC-DB-* family. The runbook follows `classify_failure()` order and pending-triage behavior; a mandatory safety stop is not an observed database denial. |
| Budgets and limits | `ResourceBudgets` model/work/temp/measurement inputs default to None. The review's 5,120 MiB is not an enforced deployment default. Require separately approved measurements and enforcement. Existing generation deadline is configured/default 120 seconds and initial statement timeout is 15 seconds; the review's five-second statement claim is not adopted. Small work/temp values in earlier unit tests are operands, not measured production budgets. |
| Hashes versus approval | SHA-256 binds bytes; it is not a digital signature or human authorization. Genuine `ScopeReviewStore` records and separately approved pins remain required for reference SQL, including predicates, physical lineage, persona/principal/mode/date scope. Administrative reference queries are scoped by reviewed predicates; they are not falsely described as persona-RLS execution. R09 receipts do not replace that store. |
| Native stopping | Compact `stop=True` / STOP_REASON_UNSPECIFIED is not proof of EOS or a semicolon. Require genuine native stop metadata and full-pipeline observation. An output suffix or successful SQL validation cannot establish native termination. Missing installed-build compatibility evidence remains blocked. |
| Fixed decoding | Production remains temperature 0, seed 42, max_tokens 300, stop semicolon. A five-token or shortened-deadline diagnostic needs separate owner authorization, a model-only lane without database execution and a separate run identity. No decoding default or model file changed. |
| Parser and wall-clock reviews | R05 evidence admits **59 structural classes and 27 observed function representations**, explicitly TEST_ONLY; the review's 60/36 assertion is inaccurate. Do not turn that fixture into production human approval or widen it to remove 32 excluded cases. Wall-clock review inputs concern AST/parser layout, not hardware latency measurements. |
| Connections and spoofing boundary | `RuntimeConnections` uses fresh audited/discarded leases, not a reusable connection pool. Initial session/current user must match the declared login; principal is TEXT under that login before local business-role transition. Trusted search path is pg_catalog, configured matrix schema, pg_temp. The login legitimately uses `set_config` before switching role; function revocation does not revoke SQL SET. The known single-layer principal-spoofing dependency must be reported, not hidden as universal DB protection. |
| Database negatives | Table/column probes and safe forbidden SELECTs need genuine SQLSTATE observations. Unsafe DML/DDL or role attacks rejected by mandatory harness safety must not be executed merely to obtain 42501. Read-only violations can have a different SQLSTATE. Clone proof needs real source/clone OIDs, full marker and corroboration against every ordinary alias, not just a chosen database name. |
| Execution modes | FULL/NO_VALIDATOR use v2 role-filtered context; NO_PROMPT_FILTER uses full governed context but retains validation and restricted routing. UNCONTROLLED uses v1 frozen full DDL with no resolver/catalog, mandatory safety and a dedicated nonadmin SELECT-only role on a verified disposable clone. No unsafe mode routes to a source/business database. |
| Actual commands and fixtures | The existing tuning CLI is `python -m stark_t2sql.evaluation --execute --mode ... --composition ... --composition-sha256 ...`, with `compose_evaluation_job(root=..., mode=...)`. No missing script path or owner composition is invented. Existing DB fixtures import workspace-local owner code after opt-in; require separate source/hash review. A full DB-enabled suite could select the separately gated R02 reset test, so the runbook selects only explicit observational tests. |
| Browser and launcher | `python -m ops.serve` is an offline UI launcher and removes `STARK_ENABLE_CONNECTED_UI` from its child. Connected foreground Streamlit needs a separate operation and inputs. Seven pages, actual four personas, Ask single-flight, navigation/reruns and hygiene need real browser evidence. Current UI offers Refresh status, not a Cancel button; backend Event cancellation and browser navigation are distinct. R08's blocked launch is not permission to bypass security controls. |
| Historical fidelity | The frozen R02 fixture is an approved synthetic baseline. No historical dataset recovery, fidelity, PostgreSQL acceptance or model/browser compatibility is claimed here. |

No contradiction prevented safe preparation. Actual runtime authorization/evidence and any later source defects remain separate decisions; this PR does not grant or implement live execution.

## New files and purposes

Only these nine files are added by Codex:

| Path | Purpose |
| --- | --- |
| `docs/acceptance/R09_LIVE_ACCEPTANCE_RUNBOOK.md` | Sequential A-F entry conditions, permitted operations, evidence, stop/cleanup rules, actual CLI/test selections and explicit live authorization boundaries. |
| `docs/acceptance/R09_ACCEPTANCE_MATRIX.json` | 31 mandatory requirements, exact phase/mode/environment/scope/procedure bindings, runtime artifact requirements and concrete GO/NO-GO conditions. |
| `docs/acceptance/R09_EVIDENCE_TEMPLATE.json` | Non-sensitive initial record with actual frozen hashes, actual persona/login mapping, no claimed execution and promotion NOT_APPROVED. |
| `docs/acceptance/R09_EVIDENCE_CONTRACT.md` | Public shape, exact statuses, canonical digest rules, private review/authorization provenance, privacy limits and safe offline usage. |
| `tests/integration/__init__.py` | Side-effect-free test package. |
| `tests/integration/r09_evidence.py` | Pure bounded JSON/evidence validation; no filesystem loader, socket, subprocess, database connection or execution permission. |
| `tests/integration/test_r09_evidence_contracts.py` | 75 offline tests, including parametrized negative cases and clearly TEST_ONLY in-memory trust operands. |
| `tests/integration/test_r09_live_acceptance.py` | Six opt-in phase-evidence replay scaffolds; no live executor/provider, setup/reset path or holdout capability. |
| `Codex_R09_Work_Log.md` | This preparation, discrepancy, test, integrity and handoff record. |

The draft PR also includes the **pre-existing Antigravity design file** `Antigravity_R09_Review.md` from commit `3c9fb14`. Codex does not alter it. Consequently the gate PR's total file count is ten while the Codex addition is nine.

## Evidence validation and readiness

Allowed statuses are exactly PASSED_LIVE, PASSED_OFFLINE, BLOCKED, FAILED and NOT_RUN. Unknown keys/statuses, duplicate JSON keys/IDs, missing criteria, altered requirements/modes/scopes/commits, wrong role mappings, digest drift, fabricated unexecuted provenance and offline-for-live substitution are rejected. Mandatory IDs and required evidence levels cannot be dropped to obtain completeness.

Executed records require actual bounded redacted evidence bytes, an exact independently reviewed receipt and separately approved receipt pins. PASSED_LIVE additionally requires separately owner-approved authorization bytes/pins bound to the criterion, revision, artifact set, matrix, endpoints and operation. Relevant service endpoints must match exact numeric loopback allowlists; database/evaluation records additionally bind corroborated clone observations. No default trust pins or actual approvals are supplied. Human review still determines whether the observations prove the requirement; code cannot authenticate a reviewer simply because it receives hashes.

Unit tests exercise synthetic proof operands in memory only. They do not create production review-store records, credentials, actual clone markers or owner permits. The holdout denial test uses a fabricated TEST_ONLY metadata ID and proves its loader is never called; it does not access sealed data.

| Phase | Mandatory items | Current manifest status | Missing evidence |
| --- | --- | --- | --- |
| A: preflight | A01-A04 (4) | All NOT_RUN | Independently reviewed execution revision/assets, deployment prompt contract, actual environment and measured budgets. Local preparation hashes do not pre-fill acceptance. |
| B: native model | B01-B05 (5) | All NOT_RUN | Separate start/inference/stop authorization, genuine weights/build/launcher/native metadata and resource/deadline/concurrency observations. |
| C: PostgreSQL | C01-C08 (8) | All NOT_RUN | Approved disposable PG16 clone, real identity/ACL/RLS/scope/SQLSTATE/session observations, restricted credentials and independent references. |
| D: E2/E6 | D01-D10 (10) | All NOT_RUN | Approved tuning cases/compositions, actual four-persona/mode runs, reference/parser/wall-clock/adversarial/canary inputs and accounting evidence. |
| E: browser | E01-E02 (2) | All NOT_RUN | Separate approved launch/browser/connected operations and real seven-page, busy/recovery/hygiene observations. |
| F: sealed governance/signoff | F01-F02 (2) | All NOT_RUN | Separate private holdout governance/permit/schedule review and final independent signoff; no payload access or automatic run. |

**Readiness: NO_GO.** A01/A04 eventually require independently reviewed PASSED_OFFLINE evidence; the other 29 require PASSED_LIVE evidence. Even hypothetical complete validated evidence returns only EVIDENCE_COMPLETE_AWAITING_OWNER, never production permission. Current phase fixtures deliberately have no provider: a future owner-authorized, independently reviewed provider/collection procedure is still required. An environment variable alone cannot supply one.

## Actual offline verification

Existing interpreter: `H:\STARK_T2SQL_R02_ENV\Scripts\python.exe` (Python 3.12.10). Existing pytest 8.3.5, SQLGlot 30.22.0 and Streamlit 1.66.0 were used without installation. Working directory: `H:\STARK_T2SQL_R09`. Every run used `PYTHONPATH=src;.` and `STARK_TEST_ENABLE_DB_INTEGRATION=0`.

| Run | Passed | Skipped | Failed | Elapsed |
| --- | ---: | ---: | ---: | ---: |
| Before changes: full safe offline baseline | 1,574 | 58 | 0 | 80.34 s |
| First focused integration contract run | 64 | 6 | 1 | 3.05 s |
| After correcting test-import registration and adding coverage | 70 | 6 | 0 | 1.10 s |
| Final focused integration contract run | **75** | **6** | **0** | 1.08 s |
| Final full safe offline suite | **1,649** | **64** | **0** | 38.68 s |

The one earlier failure was the import-test setup error described in the chronology. The final suite adds exactly 75 passing offline contract tests and six deliberately unexecuted phase checks; the pre-existing 1,574 passes and 58 external-prerequisite skips are preserved. The inherited pytest-asyncio unset `asyncio_default_fixture_loop_scope` deprecation warning remains; no unrelated configuration changed.

Focused command:

```powershell
$env:PYTHONPATH='src;.'
$env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
$env:STARK_R09_OFFLINE_ONLY='1'
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest tests/integration -q -ra
```

Final ordinary full-suite command (R09 offline-only flag removed to check the default safe skip path):

```powershell
$env:PYTHONPATH='src;.'
$env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
Remove-Item Env:STARK_R09_OFFLINE_ONLY -ErrorAction SilentlyContinue
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest -q -ra
```

Exact skip accounting:

| Existing prerequisite | Skips | Interpretation |
| --- | ---: | --- |
| Parser representations excluded by actual supplied evidence | 32 | Retained; no widened approval profile. |
| `STARK_TEST_WALLCLOCK_REVIEW_PATH` | 16 | Actual external AST/parser layout review absent; not measured hardware timing. |
| PostgreSQL integration opt-in/composition | 6 | No database operations authorized or executed. |
| Direct-runner DB composition/opt-in | 1 | No live direct SQL executed. |
| R02 live reset opt-in/isolation proof | 1 | Destructive operation not authorized or executed. |
| `STARK_TEST_ADVERSARIAL_SCOPE_PATH` | 1 | Genuine external adversarial review input absent. |
| `STARK_TEST_REFERENCE_REVIEW_PATH` | 1 | Genuine external reference review input absent. |
| **Existing total** | **58** | Unchanged. |
| New R09 phase-evidence scaffolds | **6** | NOT_RUN without reviewed replay/provider; explicit OFFLINE_ONLY skips in the focused run. |
| **Final total** | **64** | No skipped case is acceptance evidence. |

No live PostgreSQL, SQLCoder/llama.cpp, browser or holdout result is established by these tests. No host service/installed model survey is claimed; actual infrastructure may exist but its required runtime evidence was not collected in this preparation.

## Frozen-file and holdout integrity

These exact file SHA-256 values were recomputed offline and bound in the initial template; the contract tests independently read the same named frozen files. File hashing is not database or historical-data acceptance.

| Artifact | SHA-256 |
| --- | --- |
| `schema.sql` | `f1b5976a08ebeeeb085d7095ddf25edfb06a261b2ebfe9f0653cb3a8b5128bf3` |
| `seed_data.py` | `ee9fd0a9965b51f6289290caa211460a65f9b2c38728bf99bb1133265d0561bf` |
| `fixture_manifest.json` | `fb15e54afc4b72e02076614fec108049595ab1879feeabe9871f131fccb2640e` |
| `fixture_pg_dump.sql` | `859aa6badb797159f846d0870e377e3aade04049adc4174d2cd7dd6a98dd4fc4` |
| `policy/access_matrix.yaml` | `85efd46ce237aea0dab8aac57af81c667320508ef841dbf79c5f2eebfefd42e9` |
| `semantic/catalog.yaml` | `2eb213d793819e51bbae100a842485adafcde16ea6026fcb918247e652b447ed` |
| `src/inference/prompt_template.txt` | `67d1c6d265202e6bf6abcd1393203e84b92bf9df03207015679339fe807ad6b6` |
| `STARK_T2SQL FRD 1.8.txt` | `e5814c87f080f8f2bc23c4b7c8299049c9597b3714eb450ad0670ce540f5c162` |

Canonical artifact-set digest: `43bd47267a4520720ed4a60ef3a3b543b87269c4ba9a71b30bb7a437652d7efe`. Canonical matrix digest: `2353d4bee6314a6ce3a026a83bfe4e96204dc2a423dbce380c65ebb9253d12b4`. Canonical JSON format is defined in the evidence contract; these are not hashes of the pretty-printed JSON files.

Git comparison against the approved design shows no changes to existing tracked files: production code, schema/seed/dump/manifest, policy/catalog/prompt, historical tests/fixtures/reviews, `AGENTS.md`, `ops/progress.json` and E0 HTML remain unchanged. Scope checks inspect tracked path/diff metadata for holdout integrity; genuine sealed payloads/exposure records were not opened, hashed or enumerated. No frozen case index/partition/ID was rewritten. The synthetic holdout-denial test has no real payload input.

`git diff --cached --check` passed for the Codex addition after removing Markdown trailing spaces from this log. Checking the pre-existing design commit against the integration baseline reports eight trailing-space Markdown line breaks in `Antigravity_R09_Review.md`; they predate this implementation and are preserved under the historical-review ownership restriction.

Neither repository E0 HTML nor either owner's primary/legacy UI copy was changed. Manual progress regeneration and any protected local-copy synchronization belong to a later separately requested Antigravity verification. No scheduler, background coordinator or automatic next-gate action was introduced.

## Handoff and publication

Preparation is complete for independent review with the live evidence and provider limitations above. The next step is an owner-directed Antigravity verification; this implementation does not start it. Final live execution, any reset/setup, sealed exposure, production remediation, PR #1 closure, R09 merge and PR #2 promotion to `main` each remain outside this authorization.

Implementation commit: [`a5eb39d005a32b559b1371e8e7978ada15c8c548`](https://github.com/Vivek-k24/Stark_T2SQL/commit/a5eb39d005a32b559b1371e8e7978ada15c8c548), `test(r09): prepare gated acceptance runbook and evidence contracts`. It contains the nine allowed additions listed above. The actual pushed branch SHA was verified with `git ls-remote`; the working clone was clean after that push.

Opened exactly one [draft PR #24](https://github.com/Vivek-k24/Stark_T2SQL/pull/24), targeting `gemini/full-remediation-review` from `codex/r09-remediation`. GitHub confirmed OPEN, `isDraft=true`, the exact implementation head SHA above and ten total files: the nine Codex additions plus the unchanged pre-existing Antigravity design. PR #1 and PR #2 remained OPEN drafts on their existing heads; neither was merged or closed.

This publication-record follow-up changes only `Codex_R09_Work_Log.md`. Test source, evidence contracts, matrix, template and runbook remain exactly as tested; pytest is not repeated for this log-only addition. The final branch SHA is reported to the owner after verifying the follow-up push. No merge, promotion, live operation, progress update or next-agent activation is performed.
