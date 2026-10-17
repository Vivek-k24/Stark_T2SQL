# Local STARK UI with SQLCoder off

From `H:\STARK_T2SQL_MAIN_SYNC`, run:

```powershell
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m ops.serve
```

Open http://127.0.0.1:8501. The real app starts independently of SQLCoder. It does not install policies, start/stop PostgreSQL, start a model or change the fixture. Streamlit 1.66.0 is pinned to the API exercised here. No installation is performed by the launcher.

## Authenticate and inspect the existing database

1. Health distinguishes PostgreSQL TCP reachability, authenticated policy inspection and model health. LISTENING alone is not authorization readiness.
2. Open **Settings**. Supply the four existing role passwords through masked inputs. The trusted `postgres` credential is used only for fixed startup metadata and independent reference inspection; candidate execution uses the three restricted logins. No new password or account is created.
3. Select the actual reviewed installation binding and measurement file. The defaults name existing owner artifacts under `H:\STARK_Runtime`; paths are inputs, not approval. Settings must match installed work/temp budgets. Target remains exactly `127.0.0.1:5433/stark_test`, public schema, twelve tables. There is no arbitrary database/schema selector.
4. Click **Verify database and load metadata — no changes**. The app checks the actual policy-state digest, schema, real fixture principals, every restricted-login privilege audit and fixed scoped counts. Failure is sanitized, clears the old capability and returns no metadata. It cannot apply or repair policy.
5. A successful inspection exposes all four predefined simulated personas in Playground, Semantic Catalog and Access Policy. Definitions are source-governed and live-schema-validated. Permission projections have been checked against installed grants/RLS. The timestamp identifies the inspection snapshot; re-submit Settings for fresh verification.

Passwords are removed from widget state during the submit callback. Metadata-only startup discards all credential-bearing sources and connections before returning the safe facade. The browser retains an opaque capability tied to its server session. It expires after thirty minutes; another session cannot reuse it. Disconnect removes it. Nothing writes passwords to disk, global process environment, URL, logs, traces or evidence. Python memory cannot promise cryptographic zeroization.

Existing explicitly supplied private server environment may alternatively provide `STARK_PG_HOST`, `STARK_PG_PORT`, `STARK_PG_DATABASE`, `STARK_ADMIN_PASSWORD`, `STARK_PAYROLL_PASSWORD`, `STARK_HR_PASSWORD`, `STARK_SALES_PASSWORD`, `STARK_INSTALLATION_BINDING_PATH`, `STARK_RESOURCE_MEASUREMENTS_PATH`, `STARK_DATABASE_WORK_MEM_KIB` and `STARK_DATABASE_TEMP_FILE_LIMIT_KIB`. No defaults, discovery of other projects' secrets or plaintext configuration persistence are used. This path performs the same read-only verification per browser session and never fills password widgets. `STARK_TEST_ENABLE_DB_INTEGRATION=0` prevents automatic environment startup during offline tests.

## Questions and model status

With SQLCoder OFF, type a question in the real Playground: Ask remains disabled and the UI states **SQLCoder offline — no query generated or executed**. Existing safe answers are cleared when inference becomes unavailable. Scoped counts are explicitly labeled metadata probes, not answers to the typed question.

The app offers status only for model management in this delivery. It never autostarts the model and does not adopt the previously unsafe 9,216-context / 6,144-MiB configuration. Model resource/launcher approval and adequate RAM are prerequisites to a later online run.

To activate inference through Settings, explicitly select its checkbox and supply genuine existing runtime bindings, model path and independently reviewed enforced memory budget. The model must already be ONLINE. The unchanged source/template/parser/model/fixture/policy gates run through `compose_persona_runtime`; TEST_ONLY parser declarations cannot activate this path. Missing inputs leave metadata usable and generation unavailable. Actual questions still use `PersonaApplication.answer()` and the single canonical FULL pipeline, with fresh audited restricted connections. No UI mode, SQL editor or administrator candidate lane exists.

## Verification and evidence

Safe offline regression:

```powershell
$env:PYTHONPATH='src;.'
$env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
$env:STARK_R09_OFFLINE_ONLY='1'
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest -q -ra
```

For the two separately authorized, existing-fixture read-only tests, select **only** `tests/test_live_ui_readonly_acceptance.py`, set `STARK_LIVE_UI_READONLY=1`, supply the actual private environment above, and remove the offline DB flag for that command. No passwords belong in a shell script committed to Git. Do not enable and run the entire DB suite: it contains the separately gated R02 destructive reset test.

`python -m ops.live_ui_verify --verify-existing --installation-binding <actual-private-binding.json> --evidence-out <new-evidence.json>` runs only fixed read-only checks. It records independent persona counts, actual denied projections, distinct HR scopes and unchanged row/policy hashes. The output file must be new. It does not establish browser acceptance, model accuracy, holdout clearance or production approval.

Actual evidence and unresolved features are tracked in [LIVE_UI_IMPLEMENTATION_TRACKER.md](LIVE_UI_IMPLEMENTATION_TRACKER.md). Native-browser images contain only the local app; AppTest results are reported separately. Historical E0 files/progress and the model remain untouched.
