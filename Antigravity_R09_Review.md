# Antigravity Gate R09 Final Acceptance Architecture & Security Design Review

**Project:** STARK T2SQL  
**Gate:** R09 — Final Live End-to-End Acceptance and Promotion Gate (FRD 1.8, E2/E6)  
**Tracking Issue:** [GitHub Issue #11](https://github.com/Vivek-k24/Stark_T2SQL/issues/11)  
**Integration Baseline Commit:** [`b926a9c17a83f73800db4a3b8aa0ee03d444743c`](https://github.com/Vivek-k24/Stark_T2SQL/commit/b926a9c17a83f73800db4a3b8aa0ee03d444743c) (verified owner merge of Gate R08 PR #23 into `gemini/full-remediation-review`)  
**Shared Working Branch:** `codex/r09-remediation`  
**Date:** 2026-10-15  
**Reviewer:** Antigravity (Independent Architecture & Security Reviewer)  
**Verdict:** **APPROVE** (Design Approval for Owner-Authorized Live Acceptance Runbook)  

---

## 1. Executive Summary & Verification of Baseline Authority

Pursuant to `AGENTS.md`, FRD 1.8 (Section 4, FR-4.1–FR-4.9; Section 6, FR-6.1–FR-6.11; Section 9, FR-9.1–FR-9.7; Section 10, FR-10.4–FR-10.7; E2/E6), and GitHub Issue #11 (`R09 | Live end-to-end acceptance and promotion gate`), Antigravity has conducted an independent final acceptance architecture and security design review.

Gate R09 constitutes the terminal acceptance gate of the STARK T2SQL sequential multi-agent remediation lifecycle. It designs the end-to-end operational runbook for validating the local system under live runtime conditions: live SQLCoder-7B-2 Q4_K_M inference, live PostgreSQL 16 disposable clone execution with FORCE RLS, live reference oracle and canary leak detection, real browser walkthrough, and sealed holdout governance.

### 1.1 Baseline Authority & Evidence Accounting
1. **R08 Merge Verification:**
   Gate R08 ([Draft PR #23](https://github.com/Vivek-k24/Stark_T2SQL/pull/23)) was verified merged into `gemini/full-remediation-review` at commit [`b926a9c17a83f73800db4a3b8aa0ee03d444743c`](https://github.com/Vivek-k24/Stark_T2SQL/commit/b926a9c17a83f73800db4a3b8aa0ee03d444743c) on 2026-10-16T00:43:38Z by repository owner `Vivek-k24`.
2. **Current Shared Working Branch:**
   Branch `codex/r09-remediation` was pre-created directly from the verified merge SHA `b926a9c17a83f73800db4a3b8aa0ee03d444743c`.
3. **Repository Asset Status:**
   - Historical draft [PR #1](https://github.com/Vivek-k24/Stark_T2SQL/pull/1) (`assistant/sqlcoder-runtime-integration`) remains open and untouched at `cacffee`.
   - Canonical integration draft [PR #2](https://github.com/Vivek-k24/Stark_T2SQL/pull/2) (`gemini/full-remediation-review`) remains open and untouched at `b926a9c`.
   - Production branch `main` remains frozen at initial commit `8df53bf`.
4. **Offline Diagnostic Test Suite Execution:**
   The offline test suite was executed on `codex/r09-remediation` using `H:\STARK_T2SQL_R02_ENV\Scripts\python.exe`:
   ```powershell
   $env:PYTHONPATH='src;.'; $env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
   python -m pytest -q -ra
   ```
   **Results:** **1,574 passed, 58 skipped, 0 failed** in 74.38s.

> [!CAUTION]
> **Evidence Boundary:** The 1,574 passing tests establish offline contract, AST, schema, synthetic protocol, and mock container correctness only. They do **NOT** constitute proof that live PostgreSQL 16 RLS policies, the live SQLCoder GGUF model on `llama-server`, or a real desktop browser have passed acceptance.

---

## 2. Acceptance Evidence Accounting: Present vs. Missing Prerequisites

### 2.1 Present Offline Evidence
- **Syntactic & AST Safety:** 60 approved SQLGlot AST node shapes and 36 PostgreSQL function policy rules pass offline without network or database dependencies.
- **Protocol Normalization:** Synthetic modern (`stop_type`), legacy (`stopped_*`), and compact (`stop: true`) response parsing, duplicate key rejection, and token-cap exhaustion refuse invalid completions in unit mocks.
- **Policy Matrix & Static Probes:** All 273 authorization benchmark probes derive deterministically from canonical `authorization_specs()`, with exact ID SHA-256 `7b409d0df661c0b202f29c8faab97e9d56c20eac1dc2d29f673162b6e4c1730f`.
- **Streamlit AppTest Harness:** Script execution across all seven views, stale busy recovery, and persona slot positioning pass in memory via Streamlit's testing framework.
- **Canary & Failure Taxonomy Algorithms:** Cell-level canary scoping, effective-dated compensation filtering, and the 6-count accounting reconciliation are verified against synthetic fixture trees.

### 2.2 Missing Acceptance Prerequisites (Pending Owner-Authorized Live Execution)
1. **Authentic Native `llama-server` Response Capture:**
   No genuine raw JSON payload captured from a running local Windows CPU `llama-server` exists in the repository.
2. **Local Model Daemon Execution:**
   No running `llama-server` process bound to `127.0.0.1:8081` has been certified or benchmarked.
3. **Hardware Latency & Memory Ceiling Measurements:**
   Actual memory footprint (<=5,120 MiB ceiling) and CPU wall-clock generation latency have not been measured on the owner's hardware.
4. **Live PostgreSQL 16 Disposable Clone:**
   No live database connection to an isolated fixture clone has executed SQLSTATE `42501` denial probes or verified live FORCE RLS row filtering.
5. **Interactive Desktop Browser Walkthrough:**
   Real desktop browser interaction has not been observed (marked `BROWSER_SMOKE_NOT_VERIFIED`).
6. **Owner-Approved External Review Inputs:**
   The 58 currently skipped tests require real external evidence files.

### 2.3 Detailed Accounting of the 58 Skipped Tests

| Skipped Tests | Location | Prerequisite Input / Environment | Requirement to Unskip |
| :---: | :--- | :--- | :--- |
| **32** | `tests/test_validator_contracts.py` (lines 105, 133) | 16 unapproved SQLGlot rules in `parser_approval_sqlglot_30_22_0.json` | Requires owner signoff on an expanded parser profile. Until approved, these 32 tests must remain skipped to prevent accepting unvetted AST shapes. |
| **16** | `tests/test_evaluation_contracts.py` (lines 80, 93) | `STARK_TEST_WALLCLOCK_REVIEW_PATH` | Requires an authentic JSON log of measured hardware wall-clock profiles from the owner's Windows machine. |
| **6** | `tests/test_database_integration.py` (lines 54, 66, 72, 82) | `STARK_TEST_ENABLE_DB_INTEGRATION='1'` & `STARK_TEST_EXPECTED_SCOPE_COUNTS_PATH` | Requires live local PostgreSQL 16 running on `127.0.0.1:5432` with disposable fixture clone and external expected count JSON. |
| **1** | `tests/test_runner_contracts.py` (line 115) | `STARK_TEST_ENABLE_DB_INTEGRATION='1'` | Requires live local PostgreSQL clone. |
| **1** | `tests/test_seed_generation.py` (line 390) | `STARK_TEST_ENABLE_DB_INTEGRATION='1'` | Requires live local PostgreSQL reset authorization. |
| **1** | `tests/test_benchmark_contracts.py` (line 65) | `STARK_TEST_ADVERSARIAL_SCOPE_PATH` | Requires owner-reviewed signed adversarial scope evidence JSON. |
| **1** | `tests/test_reference_contracts.py` (line 89) | `STARK_TEST_REFERENCE_REVIEW_PATH` | Requires owner-reviewed signed reference SQL evidence JSON. |

> [!IMPORTANT]
> **No Synthetic Fabrication:** Skips represent intentional verification boundaries. An agent must never fabricate mock files or relax environment checks solely to reduce the skip count.

---

## 3. Windows & Model-Service Live Acceptance Runbook (FR-4, E2)

### 3.1 Local Environment & Asset Provenance
- **Operating System:** Windows 10/11 Professional / Enterprise on host `H:\STARK T2SQL`.
- **Python Environment:** `H:\STARK_T2SQL_R02_ENV\Scripts\python.exe` (Python 3.12.10).
- **Model GGUF Asset:** `SQLCoder-7B-2 Q4_K_M` GGUF located at `config.paths.model_file` (e.g. `models/sqlcoder-7b-2.Q4_K_M.gguf`).
  - Weights must post-date the 2024-02-07 model-card revision (FR-4.9).
  - SHA-256 of the model file must match trusted `service.model_sha256`.
- **Launcher Asset:** Local `llama-server.exe` executable or launcher script whose SHA-256 matches trusted `service.launcher_sha256`.
- **Build Identification:** Exact `llama.cpp` build tag (e.g. `b2600+`) must be recorded in the run manifest.

### 3.2 Network Binding & Generation Parameters
- **Loopback Enforcement:** Bound exclusively to `http://127.0.0.1:8081` with single inference slot (`--slots 1`) and prompt-prefix caching enabled (`--cache-prompt`). Zero public or external interfaces.
- **Prompt Template:** `src/inference/prompt_template.txt` (exact SHA-256: `67d1c6d265202e6bf6abcd1393203e84b92bf9df03207015679339fe807ad6b6`).
- **Decoding Defaults:**
  - `temperature = 0.0` (greedy decoding)
  - `seed = 42` (deterministic random state)
  - `max_tokens = 300` (hard token ceiling)
  - `stop = [";"]` (explicit stopping delimiter)
  - `timeout_seconds = 120.0` (generation deadline)

### 3.3 Resource Ceilings & Measurements
- **Memory Ceiling:** Resident working set must not exceed `config.resource_budgets.model_memory_limit_mib` (5,120 MiB / 5 GiB).
- **Latency Measurement:** Monotonic wall-clock generation duration (`generation_ms`) recorded on every request.

### 3.4 Live Model Protocol Verification Sequence
Once authorized by the owner to start `llama-server.exe`, execute the following protocol checks:
1. **Authentic Response Capture (No Prompt Leakage):**
   Send one unstreamed POST request to `http://127.0.0.1:8081/completion` with prompt `"SELECT 1"` and `response_fields`. Capture the returned JSON into an offline fixture file (`tests/fixtures/native_llama_cpp_response.json`). Sanitize any proprietary metadata.
2. **Semicolon Stop Verification:**
   Query: `"What is the count of employees?"`. Model must emit SQL ending in `;`. Verify `stop_type == "word"`, `stopping_word == ";"`, and `stopped_semicolon == True`.
3. **EOS Stop Verification:**
   Verify model stopping on `<|endoftext|>` token maps to `finish == "EOS"`.
4. **Token-Cap Exhaustion (`FC-TRUNCATED-GEN`):**
   Submit an artificially constrained request with `n_predict: 5`. Model must exhaust tokens before semicolon. Verify `LocalInferenceClient.generate()` raises `GenerationTruncatedError` before reaching the SQL extractor.
5. **Watchdog Timeout (`FC-TIMEOUT-GEN`):**
   Submit a request with total generation deadline 0.001s. Watchdog thread must trigger `_interrupt_socket` via `shutdown(socket.SHUT_RDWR)`, raise `GenerationTimeoutError`, and release `_single_flight` lock without deadlocks or `AttributeError`.
6. **Cancellation Handling:**
   Trigger `cancel_event.set()` mid-generation. Client must raise `ModelGenerationError("Generation was cancelled; the candidate must not execute.")`.
7. **Single-Flight Guard:**
   Submit two concurrent generation requests. Second request must immediately raise `ModelGenerationError("The local model already has an active request.")`.

---

## 4. PostgreSQL 16 Live Security Acceptance Runbook (FR-6, E2)

### 4.1 Disposable Fixture Clone Isolation
- **Target Connection:** Disposable local PostgreSQL 16 clone database (e.g. `stark_disposable_eval_...`) on `127.0.0.1:5432`.
- **Absolute Rule:** NEVER connect to or modify a production database.
- **Clone Marker Verification:** Inspect `pg_catalog.shobj_description(oid, 'pg_database')`. Must match:
  - `kind = "stark_disposable_evaluation_clone"`
  - Valid `clone_token` regex `[A-Za-z0-9_-]{16,128}`
  - Distinct non-empty `source_database`
  - Matching `fixture_dump_sha256` (`859aa6badb797159f846d0870e377e3aade04049adc4174d2cd7dd6a98dd4fc4`).
- **Asset Integrity Checks:**
  - `schema.sql`: `f1b5976a08ebeeeb085d7095ddf25edfb06a261b2ebfe9f0653cb3a8b5128bf3`
  - `seed_data.py`: `ee9fd0a9965b51f6289290caa211460a65f9b2c38728bf99bb1133265d0561bf`
  - `fixture_manifest.json`: `fb15e54afc4b72e02076614fec108049595ab1879feeabe9871f131fccb2640e`

### 4.2 Role Separation & Persona Credentials
The system enforces five isolated database roles:
1. `app_payroll`: Full SELECT on all 11 business tables; zero grant on `hr_bp_assignments`.
2. `app_hr_bp`: SELECT on 13 columns of `employees` (no salary, no `employee_number`), all columns of `leave_balances`, reference tables. Row visibility filtered by division assignment.
3. `app_sales_mgr`: SELECT on exact 5 public columns of `employees` (`employee_id, first_name, last_name, department_id, manager_id`), reference tables. Zero grant on compensation, payroll, or leave balances. Row visibility filtered by department.
4. `stark_scope_owner`: Dedicated administrative role owning `hr_bp_assignments` for RLS scope lookups. Cannot execute candidate SQL.
5. `stark_eval_baseline_login`: Global SELECT on all 12 tables, active ONLY on the disposable clone for reference oracle scoring.

### 4.3 Live Persona Security Test Matrix

| Persona | Target Query | Expected Live Behavior | Authoritative Security Layer |
| :--- | :--- | :--- | :---: |
| **`app_payroll`** | `SELECT COUNT(*) FROM employee_compensation;` | **200 OK**, returns integer count | Column & Table Grant |
| **`app_payroll`** | `SELECT * FROM hr_bp_assignments;` | **DENIED**, SQLSTATE `42501` | Table Privilege Revoked |
| **`app_hr_bp`** | `SELECT employee_id, first_name, email FROM employees;` | **200 OK**, returns assigned division rows only | Row Level Security (`FORCE RLS`) |
| **`app_hr_bp`** | `SELECT employee_number FROM employees;` | **DENIED**, SQLSTATE `42501` | Column Privilege Revoked |
| **`app_hr_bp`** | `SELECT * FROM employee_compensation;` | **DENIED**, SQLSTATE `42501` | Table Privilege Revoked |
| **`app_sales_mgr`** | `SELECT employee_id, first_name FROM employees;` | **200 OK**, returns managed department rows only | Row Level Security (`FORCE RLS`) |
| **`app_sales_mgr`** | `SELECT * FROM employees;` | **DENIED**, SQLSTATE `42501` (star probe denial) | Column Privilege Revoked |
| **`app_sales_mgr`** | `SELECT * FROM leave_balances;` | **DENIED**, SQLSTATE `42501` | Table Privilege Revoked |
| **All Personas** | `INSERT INTO departments VALUES (99, 'Hacked');` | **DENIED**, SQLSTATE `42501` | DML Denied (Read-Only) |
| **All Personas** | `SET ROLE postgres;` | **DENIED**, SQLSTATE `42501` / Revoked | Engine Role Hierarchy |
| **All Personas** | `SELECT set_config('app.principal_id', '1', false);` | **DENIED**, SQLSTATE `42501` | Function Execute Revoked |

### 4.4 Connection & Transaction Safety
- Session initialization: `SET TRANSACTION READ ONLY;`, `SET statement_timeout = '5000';` (5s hard ceiling), `SET search_path = stark, public;`.
- Execution isolation: Connection released back to pool in `finally` block; single-flight execution lock strictly maintained.

---

## 5. Reference Oracle, Canary & Scoring Acceptance Runbook (FR-9, E6)

### 5.1 Reference Oracle Governance
- Reference queries must be verified against `ScopeReviewStore` using owner-signed SHA-256 fingerprints.
- Reference oracle queries execute under the designated baseline role on the clone database, applying point-in-time temporal filters (`effective_date <= as_of_date`).

### 5.2 Cell-Level Canary Scoping & Compensation Timing (ISS-11)
- **Cell Scoping:** For mixed selectors containing both visible and hidden employees, `FixtureCanaryProvider.for_case()` evaluates visibility per `(employee_id, field)`. Permitted cells are excluded; only strictly forbidden cells become canaries.
- **Effective-Dated Compensation:** Canaries queried from `employee_compensation` must bind:
  ```sql
  WHERE employee_id = ANY(%s)
    AND effective_date <= %s
    AND (effective_to IS NULL OR effective_to > %s)
  ORDER BY employee_id, effective_date DESC, compensation_id ASC
  ```
- **Leak Scoring:** If candidate query results contain any forbidden canary string, the run is immediately classified as `FC-LEAK`.

### 5.3 Complete Failure Taxonomy Precedence (ISS-15)
`classify_failure()` evaluates candidate outcomes in strict descending precedence:
1. `FC-LEAK` (Canary detected in candidate result)
2. `FC-WALLCLOCK` (Non-deterministic time function used)
3. `FC-TIMEOUT-GEN` (Model generation timeout)
4. `FC-TRUNCATED-GEN` (Token cap exhaustion)
5. `FC-EXTRACT` (Empty or unextractable output)
6. `FC-SYNTAX` (SQLGlot AST parse failure)
7. `FC-VALIDATOR` (Validator blocked query that matches reference oracle)
8. `FC-OVERBLOCK` (Validator blocked query on authorized table)
9. `FC-UNEXPECTED-DENIAL` (PostgreSQL denied query permitted by policy matrix)
10. SQLSTATE runtime error classes (`FC-DB-*`)

### 5.4 Reconciled Scoring Accounting (ISS-20)
Run summaries must satisfy the strict conservation law:
$$\text{Total Cases} = \text{Scored Cases} + \text{Unscored Cases} + \text{Unsubmitted Cases}$$
where $\text{Pending Triage Cases}$ is tracked as an explicit subset of failed scored cases, completely eliminating double-counting.

---

## 6. FULL & Ablation End-to-End Acceptance Runbook

### 6.1 Mode Verification Matrix

| Execution Mode | Prompt Pruning | Validator Enforcement | DB Login Role | RLS Enforced | Isolation Boundary |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **`FULL`** | YES (Persona) | YES (`ReviewedSQLValidator`) | Persona Login | YES (`FORCE RLS`) | Standard governed production path |
| **`NO_VALIDATOR`** | YES (Persona) | NO (Bypassed) | Persona Login | YES (`FORCE RLS`) | Mandatory `HarnessSafetyReviewer` active |
| **`NO_PROMPT_FILTER`** | NO (Full Catalog) | YES (`ReviewedSQLValidator`) | Persona Login | YES (`FORCE RLS`) | Tests validator under unpruned prompt |
| **`UNCONTROLLED`** | NO (Full Catalog) | NO (Bypassed) | `stark_eval_baseline_login` | NO (Full View) | Dedicated clone oracle baseline only |

### 6.2 Ablation Integrity Rules
- In `NO_VALIDATOR` mode, candidate queries bypass application AST validation, but `HarnessSafetyReviewer` strictly blocks DML, DDL, catalog queries, and multi-statement attacks before connection. Execution routes under the persona's restricted PostgreSQL role, demonstrating that PostgreSQL ACLs and RLS prevent unauthorized access even if the model outputs malicious SQL.
- In `UNCONTROLLED` mode, execution is prohibited on any database other than a verified disposable clone.

---

## 7. Sealed Holdout Protection Plan (FR-9.7)

### 7.1 Holdout Governance Boundaries
- **Dataset Partitioning:** Partitioning is deterministic and immutable via `split_for_id(case_id)` using SHA-256 (`fr9-case-id-sha256-v1`) with an exact 70/30 split.
- **Sealed Storage:** Held-out benchmark cases are stored in encrypted or external restricted indexes. Zero holdout cases are bundled in repository source or test fixtures.
- **Two-Phase Acceptance Sequence:**
  1. **Phase A (Tuning & Development Acceptance):** All live verification runs (inference, PostgreSQL, ablation, and scoring) must be performed exclusively on the `CasePartition.TUNING` partition.
  2. **Phase B (Sealed Holdout Final Verification):** Execution on `CasePartition.HOLDOUT` is strictly prohibited without:
     - Explicit written owner authorization.
     - A valid `HoldoutBoundaryController` permit.
     - Automated logging of every exposed case ID in `HoldoutExposure`.
- **Leakage Prohibition:** Holdout questions, expected SQL, and reference results must never enter prompts, few-shot examples, test docstrings, or work logs.

---

## 8. Real Browser UI Acceptance Plan (FR-10, S7.1)

### 8.1 Seven-View Navigation Walkthrough
1. **Health & Status:** Default landing view; displays local loopback bindings, offline progress, and component states.
2. **Architecture:** Six-stage runtime architecture visualization; read-only stage inspector.
3. **Progress:** Remediation milestone tracker with verified SHA references.
4. **Offline Demo:** Simulated question walkthrough without database or model connectivity.
5. **Playground:** Connected question builder; active only when `STARK_ENABLE_CONNECTED_UI=1`.
6. **Semantic Catalog:** Governed metrics, business concepts, and grain definitions.
7. **Access Policy:** Matrix viewer showing persona table and column permissions.

### 8.2 Interactive UI Safety Contracts
- **Visual Anchoring:** Persona selector dropdown is visually anchored in `persona_slot = st.container()` above the sidebar disclaimer captions.
- **Single Ask Dispatch:** Clicking "Ask" immediately replaces the button with a disabled "Ask" state before blocking pipeline execution.
- **Stale Busy Recovery:** If a session is aborted, clicking "Refresh status" triggers `initialize_state()`, safely clearing `stark_request_busy` if `_UI_REQUEST_LOCK` is free.
- **Secret Hygiene:** Unhandled exceptions map to `SafeResponse(status=ERROR, stopping_layer=INTERNAL, reason_code=INTERNAL_ERROR)`. Raw SQL queries, connection strings, credentials, and stack traces never enter the UI.
- **Browser Smoke Status:** Recorded as **BROWSER_SMOKE_NOT_VERIFIED** until an interactive desktop browser session is formally executed.

---

## 9. Final Acceptance & Promotion Criteria (GO / NO-GO Matrix)

### 9.1 Evidence Classification Standard
- **`PASSED — LIVE`:** Genuinely executed against running local services (PostgreSQL 16 clone, `llama-server`) and verified by hash/receipt.
- **`PASSED — OFFLINE`:** Verified offline in unit, AST, or synthetic contract suites.
- **`BLOCKED`:** Dependent on pending owner authorization, hardware baseline, or live service startup.
- **`FAILED`:** Any observable contract, security, or scoring failure.
- **`NOT RUN`:** Scheduled live acceptance procedure not yet executed.

### 9.2 GO / NO-GO Criteria for Production Promotion (PR #2 -> `main`)

| Acceptance Domain | Required Criterion for GO | NO-GO Condition |
| :--- | :--- | :--- |
| **Model Service (FR-4)** | Local `llama-server` on `127.0.0.1:8081`; verified model/launcher SHA-256; unstreamed native JSON capture; memory <= 5,120 MiB; greedy temp 0.0. | Outbound network calls; memory leak; false semicolon stop inferred from text; unhandled truncation. |
| **Database Security (FR-6)** | Disposable clone marker verified; all 4 personas pass positive checks and fail negative column/table/RLS checks with SQLSTATE `42501`. | Production DB accessed; `app_sales_mgr` reads salary; `app_hr_bp` reads unassigned division; role spoofing succeeds. |
| **Evaluation & Canaries (FR-9)** | Cell-level canary detection flags leaks as `FC-LEAK`; 6-count accounting reconciles exactly; all-column star probe enforced. | Forbidden cell unflagged; pending triage counted twice; fabricated reference oracle. |
| **Ablation Routing** | `NO_VALIDATOR` preserves `HarnessSafetyReviewer` and PostgreSQL RLS; `UNCONTROLLED` runs only on clone. | DML executed under `NO_VALIDATOR`; uncontrolled mode runs on non-clone DB. |
| **Holdout Boundary** | Zero holdout cases inspected or exposed during tuning; sealed run permitted only by explicit owner authorization. | Holdout cases leaked into prompts, examples, or logs. |
| **Streamlit UI (FR-10)** | All 7 views render; stale busy recovers; pre-footer persona slot; zero raw SQL/secret leakage in error states. | Orphan busy lock permanent; duplicate Ask dispatched; stack trace displayed to user. |
| **Codebase & Git** | All R01–R09 gates approved; PR #1 closed without merging; PR #2 promoted to `main` with explicit owner approval. | Unapproved file modifications; draft PR merged prematurely. |

---

## 10. File Ownership & Permitted Operations for Codex (Implementation Phase)

### Permitted Implementation Scope:
1. `tests/integration/` (Targeted live integration test scripts).
2. Non-sensitive immutable evidence manifests and test runbooks.
3. `Codex_R09_Work_Log.md` (Implementation log).

### Strictly Prohibited Operations:
- NO changes to `schema.sql`, `seed_data.py`, `fixture_manifest.json`, `fixture_pg_dump.sql`.
- NO changes to `policy/access_matrix.yaml`, `semantic/catalog.yaml`, `src/inference/prompt_template.txt`.
- NO modification of core application logic (`client.py`, `validator.py`, `executor.py`, `app.py`, `holdout.py`).
- NO modifications to `main`.
- NO database resets or live SQL execution without explicit owner authorization.
- Preserve uncommitted working tree modifications in `Antigravity_Design_Review.md`.

---

## 11. Protocol Stopping Rule Notice

In strict accordance with `AGENTS.md` Rule 3:
- This report constitutes the **R09 Independent Acceptance Design Review**.
- Antigravity commits and pushes `Antigravity_R09_Review.md` to `origin/codex/r09-remediation` and **STOPS**.
- No live model daemon or PostgreSQL database has been started.
- No live SQL has been executed.
- No sealed holdout data has been accessed.
- Neither PR #1 nor PR #2 has been merged.
- Final production acceptance and promotion to `main` remain strictly subject to the repository owner's explicit direction.

<!-- STARK_HANDOFF_V1
{"gate": "R09", "implementation_ready": true, "phase": "design", "status": "APPROVE", "subject_sha": "b926a9c17a83f73800db4a3b8aa0ee03d444743c", "tests": {"failed": 0, "passed": 1574, "scope": "offline", "skipped": 58}}
-->
