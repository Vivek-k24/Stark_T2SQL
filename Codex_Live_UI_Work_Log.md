# Codex live UI work log — 2026-10-17

## Assignment and preserved starting state

The owner requested execution of `docs/CODEX_LIVE_UI_HANDOFF.md` in **`H:\STARK_T2SQL_MAIN_SYNC`**. This continues the existing application, not a fresh implementation. Work stays on **`feat/live-ui-offline-model`**, in existing [draft PR #28](https://github.com/Vivek-k24/Stark_T2SQL/pull/28), targeting `main`. No merge or next-gate automation is authorized.

The handoff names merged PR #27 / `9b1ed05c25704c202a9a117238554a4e6fb6a36a` as its integration starting point. The actual feature-branch starting HEAD was **`9abe82a7ad8ff263f83b3f581a1509095cae61ba`**, including later owner handoff, permission-design and test commits. This checkout was clean. The separate original `H:\STARK T2SQL` checkout had existing modified/untracked work; it was inspected read-only and left alone. No branch was created, switched, reset, stashed or force-pushed.

Read the complete live UI handoff, applicable owner-supplied manual `AGENTS.md` instructions, FRD 1.8, `PROJECT_LOG.md`, backend/UI contract, permission-approval design and relevant application, connection, persona, launcher and test source. No `AGENTS.md` file was present in the live-UI checkout or its applicable parent. The latest explicit handoff authorizes the narrow model-independent metadata extraction; a dated contract amendment records that exception to the earlier UI-only file restriction.

The original FRD excludes real authentication; the newer owner request expands that scope but explicitly requires independent threat-model and enablement review. This delivery implements the first model-off contract and non-destructive operator setup. It does not assert that account authentication, policy management, Data Lab or full SQLCoder acceptance is complete.

## 1. Reconcile the real baseline

- Existing interpreter: `H:\STARK_T2SQL_R02_ENV\Scripts\python.exe`, Python 3.12.10, pytest 8.3.5 and Streamlit 1.66.0. No package was installed.
- PostgreSQL 17 was already installed on `127.0.0.1:5433/stark_test`; policy installation is historical work, not repeated here. SQLCoder was deliberately off, and remained off throughout this delivery.
- The handoff's prior integration count was **1,811 passed / 64 skipped**. The actual later feature-branch baseline was **1,824 passed, 64 skipped, 1 failed** in 53.73 seconds. The failing preexisting offline-service test exposed an `HTTPConnection` constructor outside its error guard.
- Default startup removed the connected opt-in and consequently hid all persona metadata behind model-dependent composition. The six deprecated `use_container_width` calls, unconditional blocked banner and blue/gray mixture were still present. The current permission screen was source-only preview, not authenticated or executable.
- The process initially had no STARK credentials. The owner later supplied temporary development credentials for the existing roles. Their values were used only for the authorized existing-database checks and ephemeral server process environment; they are not recorded in source, evidence, screenshots or this log.

## 2. Implement independent, authenticated read-only metadata

Created `src/stark_t2sql/pipeline/metadata.py` with a fixed-target inspection and safe facade. It bounds and validates the actual local installation binding, rejects duplicate JSON keys, checks the matrix and installed policy digest, cross-checks schema/catalog definitions, resolves all four principals from the actual fixture, and applies existing restricted-connection privilege audits before fixed scoped-count probes. Principal text is set before switching to the existing business role. Administrative and restricted sources close before returning metadata. No model is constructed or called, and the facade exposes no SQL executor, password or raw catalog.

`db/connections.py` now optionally accepts a private credential mapping, copied only for the relevant aliases and cleared on source close. This prevents form credentials from being assigned to global `os.environ`. The optional mapping is forwarded through the existing `compose_persona_runtime` in `pipeline/orchestrator.py`. All existing FULL source/template/parser/model/fixture/policy checks and execution/audit logic remain in place; no evaluator or privileged candidate lane was added.

Created `ui/workspace.py` for a server-side workspace store. Random opaque handles must match the server-assigned Streamlit session ID; handles expire, are replaced/disconnected safely, and are bounded in count. Browser booleans do not authorize a workspace or administrator. The submit callback removes password widget state before inspection, sanitizes failures and rate-limits repeated setup attempts. Metadata-only startup retains no credential source. Explicit configured server environment can use the same path without filling password widgets; ordinary offline tests disable this startup.

The optional inference checkbox never starts SQLCoder. It composes only the existing governed FULL application with genuine review/resource inputs and an already-online model. Missing/TEST_ONLY inputs preserve metadata and keep generation unavailable. The workspace independently fails closed when inference is absent/offline. This online path was not executed in this delivery.

## 3. Connect the real UI and fix launcher/layout behavior

`app.py` now treats metadata and generation as separate capabilities. Existing persona, catalog and policy views consume safe verified projections while SQLCoder is off. Playground accepts a question but disables Ask and clears stale answers. Its scoped employee count is labeled a metadata probe, not a result of the typed question. The legacy explicit connected loader remains compatible and guarded; the simulated demo remains segregated and labeled.

Created `ui/settings.py` with four masked existing-role fields, fixed-target information, actual installation/resource paths and explicit non-mutating verification. No role, password, policy, database, service or account is created or changed. Added honest disabled Admin Panel, Login/Signup and Data Lab navigation. Existing Permission Management remains a nonpersistent, non-executable source-policy preview; it is not relabeled as approved or live policy editing.

Health distinguishes listener reachability, actual authenticated installed-policy inspection and model OFFLINE/LOADING/ONLINE. Sensor construction/error handling is guarded and requests are bounded to numeric loopback. Snapshot time is explicit; a successful snapshot does not prove continuous policy integrity.

Migrated all six deprecated Streamlit calls to supported `width="stretch"`, pinned the already-installed Streamlit 1.66.0 API and applied a grayscale theme/CSS with accessible focus/text distinctions. Preserved the existing CRLF format in `offline_demo.py` to avoid unrelated whole-file churn. Git whitespace checking passes with `cr-at-eol` recognition; no repository/global Git setting was changed.

`ops/serve.py` still launches `app.py` on loopback in the foreground, but owns a separate child process group, reports independent capabilities and cleans up deliberate Ctrl+C. `ops/serve_connected.py` reuses the same lifecycle without loosening its opt-in. Unit checks alone missed Windows' delayed interrupt dispatch during an unbounded child wait. The native shutdown exercise reproduced it; a bounded 0.25-second wait fixes dispatch and is covered by a regression test.

## 4. Focused and full offline tests

All figures below are actual runs, not targets or reconstructed test output.

| Run | Result | Interpretation |
| --- | --- | --- |
| Initial full feature-branch baseline | **1,824 passed, 64 skipped, 1 failed**; 53.73 s | Preexisting health-constructor failure, subsequently corrected. |
| First focused invocation | **No tests ran** | A nonexistent test filename was supplied; corrected the selection. |
| Early focused existing files | **81 passed, 1 failed** | Old UI test expected the question field to disappear offline; updated to the owner's visible-input/disabled-Ask contract. |
| New workspace/launcher tests, initial | **23 passed, 1 failed** | Corrected a test assertion to inspect the password widget protobuf rather than AppTest's element-kind property. |
| Combined focused UI/security/launcher suite | **106 passed, 0 failed, 0 skipped**; 19.17 s | Mocked/unit/AppTest coverage. Two later regressions were included in the final full run. |
| Broad offline suite before final sensor-coverage additions | **1,851 passed, 66 skipped, 0 failed**; 111.95 s | Includes bounded Windows wait and offline environment-startup guard. |
| Final focused UI/security/launcher suite | **124 passed, 0 failed, 0 skipped**; 16.63 s | Nine explicitly selected files; includes loading/timeout/deadline/no-service-launch cases and persona UI alignment. |
| Final full offline suite | **1,861 passed, 66 skipped, 0 failed**; 117.58 s | Includes the ten final health-test additions; no production change after the native/live verification. |
| Separately opted-in live test file | **2 passed, 0 failed**; 16.69 s | Actual existing PostgreSQL plus real Streamlit AppTest form submission and four-persona views. Not a browser test. |

Final offline command, from this checkout:

```powershell
$env:PYTHONPATH='src;.'
$env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
$env:STARK_R09_OFFLINE_ONLY='1'
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest -q -ra
```

The final 66 skips retain the original 64 external-input/live/scaffold skips and add the two separately opted-in read-only UI tests. The original 32 parser-representation and 16 wall-clock-review skips were not converted into approvals. Other skips remain six R09 live scaffolds, six database tests, one runner DB opt-in, one destructive R02 reset and two missing reference/adversarial-scope inputs. No parser profile was widened. The existing pytest-asyncio loop-scope deprecation warning remains; it is unrelated to the removed Streamlit layout deprecation. The final suite has no test failures. Counts from older R01–R09 checkouts are historical, not substituted for these runs.

New focused tests are in `test_live_metadata_workspace.py`, `test_foreground_shutdown.py` and `test_live_ui_readonly_acceptance.py`; existing `test_serve_connected.py`, `test_ui_rerun_contracts.py` and `test_live_service_status.py` were adapted or extended. Coverage includes forged/cross-session handles, expiry/capacity, password removal and sanitized failures, retry limits, fixed-target/binding rejection, offline no-generation, honest gated screens, layout API/palette, owned-child cleanup/escalation and failure exit codes. The final coverage review added ten health cases for invalid/unbounded deadlines, HTTP 503 loading versus denied health, timed-out sensors and no service launch; no production behavior changed after the native walkthrough.

Final focused selection: `test_live_service_status.py`, `test_live_metadata_workspace.py`, `test_foreground_shutdown.py`, `test_serve_connected.py`, `test_ui_rerun_contracts.py`, `test_ui_components.py`, `test_ui_mock_persona_alignment.py`, `test_permission_proposals.py` and `test_interim_ui.py`.

## 5. Actual read-only PostgreSQL evidence

Created `ops/live_ui_verify.py`, an explicitly opted-in runner for the existing fixture only. It cannot install/reset/repair anything. It streams hashes/counts for the twelve existing tables before and after checks, compares restricted counts with independent trusted reference computations, requires distinct nonempty HR scopes, exercises fixed forbidden projections and rechecks the actual policy digest. It creates a new evidence file without overwriting existing evidence.

The actual run at **2026-10-17T19:17:07.700964+00:00** produced **14 passed / 0 failed** in [the JSON evidence](docs/evidence/live_ui_metadata_20261017.json):

| Persona | Restricted employee count | Negative projection denials |
| --- | ---: | ---: |
| Payroll specialist | 500 | 1 |
| HR business partner #1 | 102 | 2 |
| HR business partner #2 | 102 | 2 |
| Sales manager | 10 | 2 |

All seven forbidden projections returned PostgreSQL SQLSTATE **42501**. The HR division-scope sets were nonempty and distinct despite equal employee counts. All twelve table row hashes/counts and installed policy were unchanged. Hash equality establishes preservation over this run, not historical dump/restore fidelity or universal security.

Actual installed policy-state SHA-256: `62f34044d75b73bc37730c6e716d9b3a4c01adf4f0777fba309ba0036a519a5d`.

The handoff's historical 97-statement plan SHA is `8dca38bfecc8e4ccc0948adb3749cf8e2bf45dee24912b36a83884c1139da3c5`. Its historical 307/307 verification and 17/17 behavioral checks were **not rerun or counted** here. No database security installation, role change, data mutation, reset, restore, HBA or service/firewall reconfiguration was performed.

## 6. Native Windows browser and process verification

Used the installed Computer Use skill to control the actual Chrome window and capture the application, preserving the owner's other tabs. The browser used explicitly configured private server environment; the actual masked-form route was separately exercised by the two live tests. Neither mocked AppTest nor database JSON is described as native browser evidence.

The real browser showed authenticated PostgreSQL and verified installed policy while SQLCoder was OFFLINE; a typed Payroll question with disabled Ask/no generation; HR #1's role-filtered semantic catalog; HR #2's scoped policy; and Sales' direct-report scope and permitted employee columns. Five authentic images are linked in the tracker. They contain no password, raw database error, privileged row dump or generated SQL answer. Grayscale controls/views were inspected, and no `use_container_width` warning appeared during the updated native run.

The first native Ctrl+C exercise exposed delayed interrupt handling, as recorded above. After the bounded-wait correction, an isolated test-console Ctrl+C produced `Stopping...` followed by **`Local UI stopped.`**, no Python traceback, no remaining owned launcher/Streamlit process and no 8501 listener. PowerShell's interrupted PTY reported shell exit 1; unit tests separately establish Python helper return 130. They are not the same observed exit status.

Restarted the real UI for review. A second launch against occupied 8501 reported **`Port 8501 is not available`** and exited **1**, demonstrating a visible real startup failure while the first server remained available. This is not a simulated crash test. No existing unrelated service or process was stopped. SQLCoder never started.

## 7. Documentation and exact scope

| Created/modified group | Purpose |
| --- | --- |
| `pipeline/metadata.py`; `db/connections.py`; `pipeline/orchestrator.py` | Read-only metadata facade and private credential plumbing; preserve the canonical candidate executor and FULL gates. |
| `ui/workspace.py`; `ui/settings.py`; `app.py` | Session-bound local setup, safe metadata navigation and offline-model Playground. |
| `ui/project_status.py`; `ui/views.py`; `ui/architecture.py`; `ui/offline_demo.py`; `.streamlit/config.toml`; `pyproject.toml` | Independent health, grayscale presentation and supported Streamlit layout API. |
| `ops/serve.py`; `ops/serve_connected.py`; `ops/live_ui_verify.py` | Truthful launch/owned-child lifecycle and separately authorized read-only evidence runner. |
| Six created/modified test files listed above | Unit/mocked/AppTest and separately opted-in live coverage, with each evidence type distinguished. |
| Operator guide, security review, implementation tracker, backend/UI contract amendment, `PROJECT_LOG.md`, this log and `docs/evidence/` | Reproduction, concrete pending auth/DPAPI proposal, limitations and auditable delivery. |

Compared protected assets against starting `9abe82a` using Git blob bytes: schema, seed generator, dump/manifest, matrix, semantic catalog, official SQLCoder template, FRD and historical E0/progress assets remain unchanged. The official template SHA remains **`67d1c6d265202e6bf6abcd1393203e84b92bf9df03207015679339fe807ad6b6`**. Historical review files and earlier log entries remain unchanged; no holdout or `AGENTS.md` is edited. The separate owner E0 double-extension file is not a target of this live UI phase and was not overwritten.

## 8. Reviewable commits

- **`3f2258f60695c7b6afe9a15bd6f8a7e33b998864`** — `fix(ui): reap foreground Streamlit on Windows interrupts`. Isolates launcher ownership, bounded Windows waiting, explicit cleanup/failure semantics and lifecycle/connected-launcher tests.
- **`5a2f7e232f3f3d00b2cf7b01d3195cd34a31ef63`** — `feat(ui): verify persona metadata independently of SQLCoder`. Contains the narrow metadata/credential adapters, real model-off UI, supported grayscale layout, read-only runner and related tests.
- The separate documentation/evidence commit packages this log, chronological project entry, amended interface contract, operator guide, concrete pending security proposal, visible tracker and actual JSON/native screenshots. The final pushed tip is reported on existing draft PR #28 and in the owner handoff; this file does not invent its own self-referential commit SHA.

## Remaining limitations and next owner handoff

- SQLCoder stays deliberately OFF. No online FULL answer, model accuracy/latency, allowed/blocked question walkthrough, ablation, holdout or final R09 acceptance was executed. Genuine runtime/provenance/parser/model-resource review inputs and adequate RAM/context are still required. Status-only model UI does not constitute start/stop management.
- The SQL `SET app.principal_id` single-layer dependency remains; this work does not prove principal spoofing impossible. Simulated personas are not authenticated app users. PostgreSQL 17 is the explicitly designated live target; no PostgreSQL 16 compliance is claimed.
- Real Login/Signup, administrator authority, per-user persona entitlements, durable approval/apply/rollback and Faker preview/export remain **NOT IMPLEMENTED**. Disabled pages are not substitutes for those features. Phase 2 includes a concrete Django/Argon2id account/session candidate and CurrentUser-DPAPI storage proposal, explicitly **unapproved and uninstalled**. The unresolved Streamlit identity/session bridge is documented rather than bypassed.
- Credentials are nonpersistent development/operator inputs. There is no reviewed OS-protected store, account lockout/recovery or production hardening. Same-Windows-user/process compromise is outside the current boundary. No password rotation or account/security configuration was performed.
- Stop for owner review of this first model-off delivery and the next authentication/secret integration decision. No merge, automatic Antigravity handoff, coordinator, scheduler or next gate is initiated. [Draft PR #28](https://github.com/Vivek-k24/Stark_T2SQL/pull/28) remains the single review surface.
