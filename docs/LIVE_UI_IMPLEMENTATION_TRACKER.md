# Live UI implementation tracker — 2026-10-17

Branch: `feat/live-ui-offline-model`. Existing [draft PR #28](https://github.com/Vivek-k24/Stark_T2SQL/pull/28) targets `main`. This is the first model-off deliverable and the non-destructive portion of the second phase in [the owner handoff](CODEX_LIVE_UI_HANDOFF.md). It is **not full MVP or expanded-product acceptance**. No merge is authorized.

## Ten-point model-off contract

| Requirement | Actual status | Evidence and limit |
| --- | --- | --- |
| 1. One-command real frontend | IMPLEMENTED / WINDOWS VERIFIED | `python -m ops.serve` starts the actual app on numeric loopback 8501. Health, Playground and real metadata views were exercised in Chrome. The separate demo remains explicitly SIMULATED. |
| 2. Independent readiness | IMPLEMENTED / VERIFIED | Bounded TCP and HTTP sensors; authenticated PostgreSQL and installed-policy snapshot are separate from a listening port and model OFFLINE/LOADING/ONLINE. No continuously verified policy claim. |
| 3. Masked fixed-app setup | IMPLEMENTED / LIVE APPTEST VERIFIED | Four existing-role password fields, fixed target and explicit binding/resource inputs. Actual form submission passed against PostgreSQL; password widget state was removed. Session-bound server handles, expiry and retry limits have offline tests. This is local operator setup, not real accounts or secure persistent storage. |
| 4. Four live personas and metadata | IMPLEMENTED / LIVE DB + BROWSER VERIFIED | Actual fixture resolution, installed-policy digest and restricted-login audits. Counts: Payroll 500; HR #1 102; HR #2 102; Sales 10. Native browser inspected all four, role-filtered catalog and policies. Counts are metadata probes, not English-question answers. |
| 5. Model-off prompt behavior | IMPLEMENTED / VERIFIED | Real typed question, disabled Ask, explicit no-generation/no-execution text, stale results cleared. Native Chrome and AppTest; fail-closed server wrapper tested. |
| 6. Model controls | STATUS ONLY / VERIFIED OFFLINE | No model start/stop button or launch side effect. Model stays deliberately off. ONLINE FULL inference was not executed in this delivery. |
| 7. Fixed security boundary | PRESERVED / LIMITED LIVE VERIFICATION | No matrix, schema, fixture, prompt, validator, executor or policy changes. Existing FULL composition retained. Four scoped-count checks and seven actual forbidden projections passed. Known SQL `SET app.principal_id` single-layer dependency remains. |
| 8. Useful default application | IMPLEMENTED / BROWSER VERIFIED | Default Health uses real sensors; metadata pages work without model bindings. Grayscale navigation, settings and persona views. Historical progress is identified as historical. |
| 9. Tests and data preservation | PASS FOR EXECUTED SCOPE | Final offline **1,861 passed, 66 skipped, 0 failed**; focused **124 passed**; separate live tests **2 passed**; actual read-only runner **14/14 checks**. Twelve table row hashes and installed policy unchanged. This is not a rerun of all R09/model/holdout acceptance. |
| 10. Reviewable delivery | DRAFT REVIEW | Implementation, tests, operator/security docs, work log, JSON and native screenshots delivered on the existing branch/PR. Owner review and merge remain pending. |

## Expanded features — do not treat navigation as implementation

| Feature / phase | Implemented now | Remaining work or approval gate |
| --- | --- | --- |
| Admin navigation, phase 2 | Honest disabled Admin Panel with real-auth boundary explained | Account approval UI, administrator authority, durable audit and mutations **NOT IMPLEMENTED**. Threat-model/enablement review required. |
| Safe Settings, phase 2 | Masked, nonpersistent read-only metadata setup; optional genuine FULL runtime inputs | OS-protected persistence, rotation and service/model resource changes **NOT IMPLEMENTED**; separate reviewed design/operation approval. |
| Auth and secrets design, phase 2 | Concrete Django/Argon2id account/session candidate and Windows CurrentUser-DPAPI storage proposal in [security review](LIVE_UI_SECURITY_REVIEW.md) | **PROPOSED, NOT APPROVED OR INSTALLED**. Streamlit session integration, gateway/identity bridge decision, dependency and denial tests required before phase 3 activation. |
| Login/Signup, phase 3 | Navigation identifies NOT IMPLEMENTED; no fake login | Real accounts, reset/lockout, server-side entitlements, first-owner bootstrap, CSRF and revocation **NOT IMPLEMENTED / REVIEW BLOCKED**. |
| Permission management | Existing nonpersistent source-matrix proposal preview, now regression-tested | Authenticated proposer/reviewer/owner, persistence, source/live diff, exact migration, recovery evidence, drift checks and execution confirmation **NOT IMPLEMENTED**. No GRANT/RLS apply. See [approval design](PERMISSION_APPROVAL_DESIGN.md). |
| Faker Data Lab, phase 4 | Navigation identifies NOT IMPLEMENTED | Deterministic fixed-schema diversity preview/export **NOT IMPLEMENTED**. Mandatory planted facts and fixture-validator compatibility must be specified after the preceding review phases. Any database activation requires separately verified disposable clone and approval; `stark_test` cannot be reset or reseeded. |
| Final online acceptance | Model-off database/UI evidence collected | Model RAM/context/provenance/runtime bindings and real allowed/blocked SQLCoder questions per persona **NOT RUN**. No claim of FRD C1–C8 or R09 acceptance. |

## Evidence index

- [Read-only live runner JSON](evidence/live_ui_metadata_20261017.json): fourteen actual checks, row/policy hashes, no model.
- [Health: PostgreSQL verified, model off](evidence/ui_health_model_off.png).
- [Playground: typed question and disabled Ask](evidence/ui_playground_model_off.png).
- [HR #1: governed catalog](evidence/ui_hr_semantic_model_off.png).
- [HR #2: scoped access policy](evidence/ui_hr2_policy_model_off.png).
- [Sales: permitted employee columns and direct-report scope](evidence/ui_sales_policy_model_off.png).
- [Run/evidence index](evidence/live_ui_acceptance_20261017.json): hashes, test counts and explicit unexecuted acceptance categories.
- [Chronological implementation and testing record](../Codex_Live_UI_Work_Log.md).

Native images come from the actual Chrome app against the live read-only metadata workspace. The browser used explicit private server environment; actual masked-form submission was separately demonstrated through live Streamlit AppTest. AppTest and browser evidence are not interchangeable. No screenshot contains a password or model-generated answer.
