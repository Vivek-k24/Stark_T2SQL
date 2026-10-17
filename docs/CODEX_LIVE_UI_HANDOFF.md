# STARK T2SQL — live frontend with SQLCoder offline (Codex implementation handoff)

**Status:** owner-authorized implementation on `feat/live-ui-offline-model`; DO NOT merge until the owner reviews live evidence.
**Starting commit:** `9b1ed05c25704c202a9a117238554a4e6fb6a36a` (PR #27 merged).
**Working directory on owner's workstation:** `H:\STARK_T2SQL_MAIN_SYNC`.
**Existing Python:** `H:\STARK_T2SQL_R02_ENV\Scripts\python.exe`.
**Database:** `127.0.0.1:5433/stark_test`, PostgreSQL 17, public schema, 12 fixed fixture tables.

## Owner's requirement

The current Streamlit app is still largely the mid-project static/simulated demo. That is unacceptable as the normal application. **When SQLCoder is OFF, all non-inference areas must use actual local configuration, installed PostgreSQL policy/catalog metadata, and runtime status where their required services are available.** Only model-dependent generation remains unavailable. A typed prompt must never pretend to produce a SQL result while the model is offline. Management of this one fixed application should happen from the frontend, not a succession of terminal commands.

Do not interpret this as authorization for a generic text-to-SQL engine, arbitrary schemas, multi-tenancy, or alternative LLM APIs. Those proposals were **explicitly rejected**. Preserve the *single fixed* `stark_test` public schema, four simulated personas, STARK semantic definitions, PostgreSQL RLS/column grants, SQLCoder-7B-2, local loopback, and FRD 1.8's trust boundaries.

## Additional frontend product requirements (owner clarification, 2026-10-17)

The owner has additionally requested **Admin Panel, Permission Management, UI Settings, Faker-backed synthetic data generation/diversification, and real Login/Signup**. These do **not** exist as completed features in the current repository; do not present existing static or mocked UI as implementation. This expands the original FRD MVP, which deliberately excluded real authentication. Treat this as an explicit design/implementation request on this feature branch, document the change against FRD scope with a security impact assessment, and surface any approval gates before activation. **Do not silently weaken or replace the fixed STARK database/RLS policy.**

### Required frontend navigation and features

- **Dashboard / Health**: real model status (offline when stopped), PostgreSQL listener versus authenticated connectivity, policy-state verification, readiness and concise explanations. Do not confuse TCP-up with DB authorization.
- **Playground**: all four governed personas, an input box, truthful no-answer when SQLCoder is offline; never send SQL, return fabricated rows, or use privileged DB login for candidate execution.
- **Semantic Catalog / Access Policy**: live authenticated, read-only, persona-filtered representations from the authoritative fixed fixture and the reviewed matrix.
- **Admin Panel** (authorized admin only): real, separate security boundary from simulated personas; user/account approval status, operational health, auditable settings and explicit safe setup actions. Never make a sidebar switch or Streamlit session-state flag alone confer administrator authority.
- **Permissions** (authorized admin only): inspect effective PostgreSQL grants/RLS and manage which *authenticated app users* may select each of the existing **four** simulated personas. **Owner has authorized UI proposals to change PostgreSQL table-level SELECT, column-level SELECT and row-level scope permissions** within the frozen schema and roles. The permission-management process must use independently authenticated proposer, security reviewer and owner; source/live catalog diffs; exact-plan hashes; regression/security probes; verified backup/recovery; drift checks; and explicit separate execution confirmation. Account-to-persona grants require administrator approval, server-side authorization on **every** request and audit logging. **No immediate GRANT/RLS execution from frontend forms.** See `docs/PERMISSION_APPROVAL_DESIGN.md`.
- **Settings**: configure fixed loopback PostgreSQL host/port/db, existing-role credentials, local model paths/health, model memory and request timeouts from a privileged, masked frontend; validate values before activation; persist secrets outside Git only if secure OS-backed storage and threat review are implemented. Never display secret plaintext, leak it in logs, traces, state, or URL, or enable non-loopback destinations.
- **Data Lab / Synthetic Data**: offer **Faker**-based diversity options (seed, distributions, identities/names, dates, departments, mix, preview/validation); preserve the fixed 12-table schema and mandatory security/persona fixtures. Prefer deterministic preview/export and separately named disposable clones. **Never rewrite, reseed, reset, or vary the authoritative `stark_test` fixture without a separately approved restore/backup migration.** Larger employee counts or altered planted facts that violate fixture validation require a documented contract change—not a hidden seed reset.
- **Login / Signup**: real local app-user accounts, separate from the three PostgreSQL service logins and four simulated persona identities. Use a reviewed authentication/session library with secure password hashing, server-side session enforcement, CSRF/rate-limit protections, account lockout/expiry, password resets, audit logging, and first-admin bootstrap requiring explicit local operator action. Signup must grant **zero admin/database/persona permissions by default** and require administrator approval. No public internet exposure or undocumented remote authentication. Do not claim real auth exists until demonstrated with independent denial tests.

### Phasing and reviews

1. **First deliverable:** replace simulated main UI with independently live DB/metadata/service screens and honest SQLCoder-offline Playground (the original 10-point contract below). This alone can be reviewed while model is off.
2. **Second deliverable:** admin navigation, safe operator settings, account/auth threat-model proposal and concrete secure-secret design; develop only the non-destructive pieces until review gates are satisfied.
3. **Third deliverable:** actual user authentication/signup, per-user authorization enforcement and admin-driven persona entitlements with adversarial security regression tests. This changes FRD scope and needs explicit review before enabling.
4. **Fourth deliverable:** Faker preview/export for a disposable dataset; activation against any PostgreSQL database requires separate authorization and clone safety checks.
5. **Final deliverable:** real live browser acceptance on owner's machine, four personas, DB accessible with model off, no false claims, documented PR evidence and exact one-command app launch.

These requirements must be covered by a visible implementation tracker in the draft PR; **do not mark an unimplemented feature completed because a design document exists**. If actual secure auth or schema fixture constraints block a feature, report the blocker and approval decision instead of bypassing safety controls.

### Python entrypoint (no rename)

The existing Streamlit application entrypoint is `app.py`. `ops/serve.py` is a Python convenience wrapper that launches `streamlit run app.py`. **Do not rename or create `run.py` because the owner mentioned filenames as examples.** The one-command launcher should run the real application, with functionality gated at individual capability level instead of substituting a static demo.

## PR #28 incremental implementation record (truthful)

On `feat/live-ui-offline-model` the code currently includes **live loopback PostgreSQL listener/SQLCoder health indicators**, and a `Permission Management` page with a **nonpersistent, source-matrix-only draft preview** of table SELECT, column SELECT and RLS scope changes. It computes a SHA-256 digest over the source policy and proposed edit, but **does not verify current DB grants, authenticate an admin, store requests, approve changes, compile a migration, or apply any SQL**. Unit/UI regression tests have been added but have **not been executed** in the owner's Windows runtime. Codex must run and correct them before marking a gate PASS. The full connected UI, real auth/signup, effective permission editing, settings and data lab remain incomplete.

Permission architecture and approval gates are specified in `docs/PERMISSION_APPROVAL_DESIGN.md`. Implement that design incrementally; do not report the future approval and apply path as implemented.

## Known completed backend evidence (do not redo destructive setup)

- PostgreSQL security policy installed using reviewed 97-statement SHA `8dca38bfecc8e4ccc0948adb3749cf8e2bf45dee24912b36a83884c1139da3c5`.
- Installed policy-state SHA `62f34044d75b73bc37730c6e716d9b3a4c01adf4f0777fba309ba0036a519a5d`.
- Official verify: 307/307 checks passed.
- Behavioral probe: 17/17 access/scope cases PASS; known single-layer SQL `SET app.principal_id` dependency documented; no independent proof that principal spoofing is blocked at the database layer.
- 1,811 offline pytest PASS / 64 SKIP / 0 FAIL before this branch.
- SQLCoder-7B-2 Q4_K_M works via llama.cpp native `/completion`: short smoke test returned correct division count SQL in 9.2 sec, but measured 9.02 GiB resident RAM with 9,216 context, 6,144 MiB private-memory cap, and just 0.49 GiB free system RAM. **Model is currently deliberately OFF.** Never autostart it as a side effect of rendering UI.
- Prior full Payroll prompt measured ~8,054 tokens; 4,096 context is insufficient.

## Root cause in current source

- `ops/serve.py` launches Streamlit on loopback `8501` **and explicitly removes** `STARK_ENABLE_CONNECTED_UI`.
- `app.py` allows Health, Architecture, Progress, Offline demo; other views are all-or-nothing behind `STARK_ENABLE_CONNECTED_UI=1` then `load_persona_runtime()`.
- `load_persona_runtime` composes DB, model client, source/provenance evidence and permissions together. A missing model/binding suppresses Playground, Semantic Catalog, and Access Policy even when database/policy are valid.
- `project_status.py` has largely hardcoded readiness text; this branch first adds independent read-only PostgreSQL TCP and model HTTP health indicators. TCP connectivity is not authenticated/database authorization readiness.
- `src/stark_t2sql/config.py` expects `STARK_ADMIN_PASSWORD`, `STARK_PAYROLL_PASSWORD`, `STARK_HR_PASSWORD`, `STARK_SALES_PASSWORD` from process environment. No frontend credential onboarding currently exists.
- `src/stark_t2sql/db/persona.py` requires trusted fixture identity resolution for four predefined personas (payroll=326, hr_1=47, hr_2=361, sales=derived). Do not invent principals.
- `src/stark_t2sql/ui/views.py` already has real `render_playground`, `render_semantic_catalog`, `render_access_policy` against a safe `PersonaViewApplication` facade. Reuse these; do not route model-generated text to PostgreSQL on a privileged connection.

## Acceptance contract (implement in small reviewable commits)

1. **One launch command:** from root `& "H:\STARK_T2SQL_R02_ENV\Scripts\python.exe" -m ops.serve` starts the *actual* Streamlit app at 127.0.0.1:8501. Existing one-command behavior becomes frontend-first rather than defaulting to a static offline demo. The legacy static/simulated demo remains clearly segregated and labeled; never display it as live output.
2. **UI service status:** display truthful, refreshed, independently checked states for PostgreSQL (TCP / authenticated access / installed policy verification distinguished), model (offline/loading/ready), and runtime bindings. Do not claim full pipeline readiness when only a port listens. Readiness checks must be bounded, loopback-only, read-only, and never print credentials/DSNs.
3. **Frontend setup for THIS fixed app:** local operator can supply missing existing-role passwords (postgres admin for trusted setup/reference; 3 restricted logins for candidate use) via masked UI fields, select existing authorized private runtime binding path and review resource settings, and invoke explicit non-mutating connection/metadata checks. No secrets in Git, Streamlit URL/query params, app logs, page content, or standard traces. Prefer nonpersistent in-memory credentials/session-bound mechanism or OS-protected local store that is reviewed; do not write plaintext config. Do not claim real multi-user authentication or expose setup to remote clients. Prevent session leakage and preserve loopback-only binding.
4. **Live personas + metadata without SQLCoder:** when PG is authenticated and policy state confirmed, show the four real fixture-resolved personas, real effective role/column/row-scope metadata, and real governed semantic catalog sourced from the reviewed semantic file with live schema cross-checks. Distinguish DB-verified metadata from source-file declarations and reference count metadata; do not run model SQL to render it. Never show privileged/admin-only data as a persona's data.
5. **Prompt behavior with SQLCoder OFF:** the real Playground is visible. Question input may be accepted, but Ask must fail closed immediately (or be disabled) with a clear `SQLCoder offline — no query generated or executed` result. Never fabricate a SQL answer, enqueue model inference, or silently substitute mock scenarios. When the server becomes ready and all genuine source review bindings are satisfied, the existing FULL-only validated pipeline may answer using role-scoped DB execution.
6. **Frontend model controls:** show actual model health and current resource constraints; an optional explicit Start/Stop control must reuse `ops.launch_model` job-object enforcement, no background automatic launch, no unapproved 9,216/6,144 settings without RAM preflight, no orphaned server, and clear failure feedback. A simple status-only implementation is acceptable for the first PR; do not claim model management is implemented if it is not.
7. **Security:** preserve frozen security matrix, single-schema/4-persona resolver, exact policy-state preflight, role-first segregation, RLS, SQL validator, semantic reviewer, no raw generated SQL while model offline, no arbitrary SQL editor, no new external service/network, no credentials in logs. If exposing admin setup would require an authentication threat-model change, document the blocker and make the screen local-only and explicitly gated. No role/password/schema/policy modifications unless separately approved.
8. **Visibility:** remove stale "development planning" as the default main experience and avoid static placeholder claims; progress can remain historical but service health and policy views should be live wherever possible. The UI must state precisely which prerequisites prevent a particular action.
9. **Tests:** preserve baseline; add unit tests for sensor failure/timeout/port handling and no service autostart; Streamlit AppTest exercising model offline with DB mocked/available, safe credential handling, real persona metadata rendering, no generation/DB execution when model offline; opt-in live tests against existing `stark_test` to verify real policies, negative access cases, and no altered fixture rows. Do not describe mocked browser tests as proof of live acceptance.
10. **Deliverables:** focused, reviewable commits + draft PR on this branch; report new tests and skipped live checks distinctly, exact steps to run actual UI, screenshots of authentic connected/offline-model views, and documented remaining blockers. Do not merge until product owner approval.

## Implementation approach

Start by extracting a **model-independent trusted metadata / policy application facade** (read-only DB/catalog and preexisting policy matrix/semantic catalog) separate from the model inference client. It must not relax `load_persona_runtime` source review gates for actual SQL execution. Wire the existing UI views to the new facade when the model is unavailable; treat model readiness as a capability, not as the entire app's availability.

Avoid coupling UI rendering to private admin connection lifetime. Admin credentials are for one-time approved metadata inspection only and must never appear in Streamlit widgets after retrieval, request traces, or state objects handed to personas. If existing `SafeConcept`/`SafePolicyRow` projections suffice, use them rather than returning raw privileged catalog objects.

Preserve backward compatibility for offline tests where reasonable; explicitly update old tests that assert ALL connected pages must be BLOCKED because those expectations describe the user-rejected behavior.

## Strict exclusions

No generic database/schema selector, cloud deployment, Kubernetes, Docker, external LLM provider, GitHub Actions workflow, automatic PostgreSQL policy re-apply, unreviewed database permission changes, password rotation, backup overwrite, irreversible DB changes, promotion to production, or unsupervised merge. App-user Login/Signup and Admin features are now **requested scope** but require the explicit threat-model, security and enablement review gates above.

**Definition of done:** Owner can start STARK in one PowerShell command, see an actual frontend with real DB and policy/semantic data for the original personas while SQLCoder is down, see only the model marked offline, and get a transparent immediate nonanswer when submitting a question; with SQLCoder online and genuine bindings, existing governed FULL path becomes available.
