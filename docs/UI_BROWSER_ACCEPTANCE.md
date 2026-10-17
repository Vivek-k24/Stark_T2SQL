# STARK T2SQL — UI Offline Acceptance Report (Mock Backend)

**Author:** Antigravity (Frontend, Browser Automation, and UI Acceptance Owner)  
**Date:** October 16, 2026  
**Correction:** 2026-10-16, at the owner's direction. The acceptance scope is relabeled as offline/mock. Test counts and test code are unchanged.  
**Evaluation Standard:** FRD 1.8 (FR-1, FR-3, FR-8, FR-10, S7.1–S7.2, NFR-10)  
**Verification Target:** Native Streamlit UI (`app.py`, `offline_demo.py`, `views.py`)  
**Status:** **OFFLINE / MOCK-BACKEND UI ACCEPTANCE PASSED. LIVE BROWSER ACCEPTANCE (E7) NOT PERFORMED.**

> **Scope of this evidence.** Every result in this report comes from Streamlit `AppTest`. It runs headless and in-process, so it is not a real browser. It used the offline `MockPersonaApplication` and the scripted E0 scenarios. PostgreSQL, SQLCoder/llama.cpp, the SQL validator and the database policy were **not** exercised. "PASS" means the UI rendered the scripted outcome correctly. It is not an observation of validator, database or model behaviour, and it does not meet the E7 exit condition: an allowed and a blocked LIVE question for each persona.

---

## 1. Acceptance Overview

This report records offline UI verification for the STARK T2SQL application. The approved static visual prototype (`STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html`) has been rebuilt as a locally hosted Streamlit application, verified here against a mock backend.

The offline UI acceptance was evaluated across four dimensions:
1. **Interactive Scenario Parity (FR-10.4)**: All 26 scripted business cases, 13 scripted security probes, 16 semantic concepts and 12 database objects from E0 render natively in Streamlit from scripted data.
2. **Four-Persona Presentation (FR-1, FR-10.1)**: The UI shows the scripted entitlement differences for the Payroll specialist, HR business partner #1, HR business partner #2 and Sales manager. Actual database enforcement was not exercised.
3. **Single-Flight Concurrency Control (FR-10.7)**: Strict process-wide nonblocking mutex locking (`_UI_REQUEST_LOCK`) preventing concurrent execution and duplicate click race conditions.
4. **Zero Information Disclosure (FR-8.2, S7.2)**: Total suppression of raw SQL, internal prompts, database connection strings, stack traces, and validator ASTs from ordinary user and persona views.

---

## 2. Test Execution & Automation Results

The complete UI test suite consists of **52 passing automated tests** executed under `H:\STARK_T2SQL_R02_ENV\Scripts\python.exe`:

| Test Suite File | Tests | Status | Scope |
| :--- | :---: | :---: | :--- |
| `tests/test_ui_browser_automation.py` | 5 | **PASS** | Headless Streamlit `AppTest` journeys against the mock backend (not a real browser): multi-tab inspection, stale identity detection and zero info disclosure. |
| `tests/test_ui_e0_scenarios.py` | 12 | **PASS** | Exhaustive verification of all 26 E0 cases across all 4 personas, 13 security probes, and role catalog/policy projections. |
| `tests/test_ui_components.py` | 9 | **PASS** | Individual component rendering tests for `render_safe_response`, `render_semantic_catalog`, and `render_access_policy`. |
| `tests/test_ui_rerun_contracts.py` | 14 | **PASS** | Session state rerun contracts, `request_guard` mutex acquisition/release, orphaned busy recovery, and 7-page navigation. |
| `tests/test_trace_ui_contracts.py` | 7 | **PASS** | Safe response projection, truncation notes, trace serialization, and AST-level mode isolation contracts. |
| `tests/test_interim_ui.py` | 5 | **PASS** | Loopback binding (`127.0.0.1`), health reporting, and progress rendering. |
| **Total UI Test Suite** | **52** | **PASS** | **100% Green (0 Failed, 0 Regressions)** |

Additionally, full repository regression testing confirmed **1,675 passed, 64 skipped** with zero failures across the entire STARK T2SQL codebase.

---

## 3. Scenario Coverage Matrix (26 Scripted Cases)

All 26 scripted cases from the approved visual prototype were rendered across the four personas. The outcomes and stopping layers below are the **E0 scripted expectations** served by the mock backend. They were not observed from the validator, database or model. Sales principal `7` is a mock value. The live sales principal is derived from the fixture at startup.

| # | Case ID | Category | Question Summary | Payroll (326) | HR BP 1 & 2 (47/361) | Sales Mgr (mock 7) | Scripted Stopping Layer | UI render |
| :-: | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :-: |
| 1 | `active` | Headcount | Active employee headcount | **ANSWERED** (435) | **ANSWERED** (Scoped) | **BLOCKED_DB** | None / DB Column | PASS |
| 2 | `engineering` | Headcount | Engineering division headcount | **ANSWERED** | **ANSWERED** (Scoped) | **BLOCKED_DB** | None / DB Column | PASS |
| 3 | `by_department` | Headcount | Headcount grouped by dept | **ANSWERED** | **ANSWERED** (Scoped) | **BLOCKED_DB** | None / DB Column | PASS |
| 4 | `reference_divisions` | Headcount | List division reference | **ANSWERED** (Ref) | **ANSWERED** (Ref) | **ANSWERED** (Ref) | None (Ref Table) | PASS |
| 5 | `direct_reports` | People & leave | List my direct reports | **CLARIFY** | **CLARIFY** | **ANSWERED** (Direct) | Input / None | PASS |
| 6 | `leave` | People & leave | Leave balances in scope | **ANSWERED** (All) | **ANSWERED** (Scoped) | **BLOCKED_VALIDATOR** | None / Validator | PASS |
| 7 | `hr_assignments` | People & leave | Assigned division employees | **ANSWERED** | **ANSWERED** (Scoped) | **ANSWERED** (Direct) | None (RLS) | PASS |
| 8 | `salary` | Compensation | Individual base salaries | **ANSWERED** | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | None / Validator | PASS |
| 9 | `bonus` | Compensation | Bonus target percentage | **ANSWERED** | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | None / Validator | PASS |
| 10 | `negative_pay` | Compensation | Negative-net-pay records | **ANSWERED** (3) | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | None / Validator | PASS |
| 11 | `header_gap` | Compensation | Payroll header/detail mismatch | **ANSWERED** | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | None / Validator | PASS |
| 12 | `completed_runs` | Compensation | Posted & closed payroll runs | **ANSWERED** | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | None / Validator | PASS |
| 13 | `pay_vs_period` | Compensation | Pay date vs period end | **ANSWERED** | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | None / Validator | PASS |
| 14 | `off_cycle` | Compensation | Approved off-cycle run status | **ANSWERED** | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | None / Validator | PASS |
| 15 | `tax_zero` | Compensation | Zero 2026 taxes anomaly | **ANSWERED** (4) | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | None / Validator | PASS |
| 16 | `forbidden_salary` | Auth Boundary | HR compensation synonyms | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | Validator | PASS |
| 17 | `forbidden_number` | Auth Boundary | Sales asks employee_number | **ANSWERED** | **BLOCKED_DB** | **BLOCKED_DB** | DB Column Grants | PASS |
| 18 | `out_of_scope` | Auth Boundary | HR asks out-of-scope leave | **ANSWERED** | **ANSWERED** (0 rows) | **BLOCKED_VALIDATOR** | RLS / Validator | PASS |
| 19 | `show_schema` | Adversarial | Dump hidden system tables | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | Validator | PASS |
| 20 | `role_escalate` | Adversarial | Switch to app_payroll role | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | Validator | PASS |
| 21 | `set_principal` | Adversarial | Spoof app.principal_id | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | Validator | PASS |
| 22 | `function_sleep` | Adversarial | Execute pg_sleep(30) | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | Validator | PASS |
| 23 | `write_attempt` | Adversarial | DELETE FROM payroll records | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | Validator | PASS |
| 24 | `ambiguous` | Semantics | Eng dept payroll headcount | **CLARIFY** | **CLARIFY** | **CLARIFY** | Semantic Input | PASS |
| 25 | `current_date` | Semantics | Count employees active today | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | Lint / Validator | PASS |
| 26 | `result_cap` | Semantics | Large result set (1,000 cap) | **ANSWERED** (Trunc) | **BLOCKED_VALIDATOR** | **BLOCKED_VALIDATOR** | Executor Cap | PASS |

---

## 4. Security Probes — Scripted Display Matrix (13 Probes)

None of these probes was executed against PostgreSQL or the SQL validator. The rows show the scripted E0 result and the *intended* enforcing layer. On the `spoof` row: FRD §2.4 documents SQL `SET app.principal_id` spoofing as a **known single-layer dependency**, with the validator as the only preventive control. It is not proven safe.

| Probe ID | Target Object | Target Column | Attack Classification | Intended Enforcing Layer | Scripted Result | UI render |
| :--- | :--- | :--- | :--- | :--- | :--- | :-: |
| `spoof` | `employees` | `*` | Principal Spoofing | Validator-only (FULL mode) | **BLOCK AT VALIDATOR** | PASS |
| `role` | `employees` | `*` | Role Escalation | Validator + DB membership | **BLOCK ROLE ESCALATION** | PASS |
| `function` | `employees` | `count` | Function Abuse | Validator + Statement Timeout | **BLOCK FUNCTION** | PASS |
| `catalog` | `employees` | `*` | Schema Probing | Validator Schema Restriction | **BLOCK CATALOG PROBE** | PASS |
| `write` | `employees` | `*` | Destructive DML | Validator + Read-Only TX | **BLOCK WRITE** | PASS |
| `salary` | `employee_comp`| `base_salary` | Table Privilege | Validator Check + DB Grants | **DENY TABLE (HR/Sales)** | PASS |
| `leave` | `leave_balances`| `*` | Table Privilege | Database Grants | **DENY TABLE (Sales)** | PASS |
| `employee_num` | `employees` | `employee_number` | Column Privilege | DB Column-Level Grants | **DENY COLUMN (HR/Sales)**| PASS |
| `active_head` | `employees` | `hire_date` | Metric Column Grant | DB Column-Level Grants | **DENY COLUMNS (Sales)** | PASS |
| `hr_assign` | `hr_bp_assign` | `*` | Private Table | No Direct SELECT Privilege | **DENY TABLE (All Roles)** | PASS |
| `select_star` | `employees` | `*` | Unchecked Wildcard | DB Column-Level Grants | **DENY COLUMN (Sales)** | PASS |
| `employee_cnt`| `employees` | `count` | Row Aggregation | Database RLS | **ALLOW SCOPED ROWS** | PASS |
| `payroll` | `payroll_res` | `net_pay` | Table Privilege | Validator Check + DB Grants | **DENY TABLE (HR/Sales)** | PASS |

---

## 5. User Journey & Interaction Acceptance

### 1. Simulated Persona Selector:
- Located above sidebar disclaimers.
- Renders the 4 canonical business personas with descriptive role and entitlement hints.
- Prominently states: *"Persona identity is simulated. This application does not provide authentication."*

### 2. Multi-Tab Outcome Inspection:
- **Decision & Journey**: Displays status pill (`Allowed`, `Scoped result`, `Blocked`, `Clarification needed`), governing policy analysis, stopping layer, reason code, and 6-stage runtime journey stack.
- **Sample Results**: Renders pandas DataFrame with authorized columns and cells. Properly displays empty-row notices (`"No permitted rows matched this question."`) and row truncation warnings (`"Results are limited to 1000 rows and are incomplete."`).
- **Scripted SQL**: Displays formatted SQL with prominent disclaimer: *"Developer-facing SQL illustration · manually scripted · not executed in demo"*.
- **Mock Trace**: Renders structured JSON trace conforming to FR-9.7.
- **Run History**: Tracks executed cases in the current session.

### 3. Single-Flight Concurrency Guard (FR-10.7):
- During active query execution, Ask button is visibly disabled and replaced with a spinner.
- Simultaneous clicks or reruns immediately yield `render_processing()` with a disabled Ask button and a manual status refresh option.
- Interrupted or failed script executions reliably clear the lock in `finally` blocks without stranding the session.

### 4. Stale Identity Detection:
- Changing the selected persona in the sidebar immediately purges `ANSWERED` state from session state.
- Changing the as-of date input immediately clears previous answers.
- No stale answer is ever attributed to a different persona or a different date.

### 5. Strict FULL Mode Isolation:
- AST inspection confirms no `query_params`, `experimental_get_query_params`, or mode selectboxes exist in `app.py` or `views.py`.
- No user controls exist to invoke `NO_VALIDATOR`, `NO_PROMPT_FILTER`, or `UNCONTROLLED`.

---

## 6. Acceptance Verdict

The Streamlit UI **passes offline, mock-backed acceptance** for the FR-10 behaviours tested here: FULL-only controls, the single-flight busy guard, stale-answer invalidation, safe-response rendering, the simulated-identity notice and scripted E0 scenario parity.

This is **not** live E7 acceptance. E7 and FR-10 require each persona to complete an allowed and a blocked LIVE question against PostgreSQL and SQLCoder in a real browser, with the UI naming the actual stopping layer. That has not been performed. The connected backend runtime is blocked pending owner approvals (see `docs/BACKEND_UI_CONTRACT.md` §9). The UI is ready for **integration review**. It is not evidence of live, end-to-end or security acceptance.
