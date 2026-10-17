# STARK T2SQL — UI Implementation Notes

**Author:** Antigravity (Frontend, Browser Automation, and UI Acceptance Owner)  
**Date:** October 16, 2026  
**Scope:** Streamlit Application, E0 Native Translation, Concurrency & Security Contracts  
**Authority:** FRD 1.8 (FR-1, FR-3, FR-8, FR-10, S7.1–S7.2, NFR-10)

---

## 1. Executive Summary

This document details the offline-verified Streamlit frontend architecture (mock backend; live connected acceptance not yet performed) for the STARK T2SQL governed Text-to-SQL system. In accordance with FRD 1.8 section FR-10.4, the static visual prototype (`STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html`) has been completely rebuilt as native, safe Streamlit components without embedding or executing legacy HTML/JavaScript iframes.

The frontend operates under strict security boundaries:
1. **FULL Mode Only**: Normal user and persona workflows expose only the governed `FULL` pipeline. Evaluation bypass modes (`NO_VALIDATOR`, `NO_PROMPT_FILTER`, `UNCONTROLLED`) are strictly barred from the UI session state, URL query parameters, and widget trees.
2. **Simulated Identity Boundary**: The UI clearly identifies persona selection as a simulation harness for testing and governance, explicitly disclaiming authentication or access control authority.
3. **Zero Information Disclosure**: Raw SQL, internal model prompts, database connection strings, stack traces, and validator AST representations never reach the persona UI. Public messages are strictly constrained to immutable contract allowlists.
4. **Single-Flight Concurrency Guard (FR-10.7)**: Concurrent requests and rapid duplicate clicks are safely blocked using a process-wide nonblocking mutex (`_UI_REQUEST_LOCK`) coupled with session-level busy tracking and top-level script short-circuiting.
5. **Stale Identity Detection**: Any modification to the active persona or explicit as-of date immediately invalidates cached answers, eliminating cross-persona or temporal data contamination.

---

## 2. Architecture & File Ownership

The frontend is isolated in the Git worktree `H:\STARK_UI_Worktree` on branch `agent/antigravity-ui-step29`. The backend files and primary repository (`H:\STARK T2SQL`) remain completely untouched to preserve concurrent backend engineering by Claude Code.

### Key Components:
- **`app.py`**: Streamlit application entrypoint. Configures loopback execution (`127.0.0.1`), initializes session state, enforces top-level busy short-circuiting, and routes across 7 navigation destinations.
- **`src/stark_t2sql/ui/views.py`**: Presentation layer implementing the navy/blue E0 styling, persona selector, query playground, semantic catalog explorer, and access policy viewer.
- **`src/stark_t2sql/ui/ui_state.py`**: Ephemeral UI state manager and nonblocking request guard (`request_guard`) providing single-flight protection and stale-answer clearing.
- **`src/stark_t2sql/ui/offline_demo.py`**: Native Streamlit E0 scenario explorer and `MockPersonaApplication` implementing the full 26-case E0 catalog, 13 security probes, role projections, and 6-stage runtime journey simulation.
- **`src/stark_t2sql/ui/project_status.py`**: Read-only public health check and manual remediation evidence viewer.
- **`src/stark_t2sql/ui/architecture.py`**: Six-stage runtime architecture and FRD roadmap explorer.

---

## 3. Native E0 Scenario Player (FR-10.4)

In previous versions, `project_status.render_demo()` utilized `streamlit.components.v1.html()` to embed the static E0 HTML document inside an iframe. Under FR-10.4, this iframe embedding has been replaced with a native Streamlit module (`src/stark_t2sql/ui/offline_demo.py`).

### Features:
1. **Curated Scenario Library**:
   - 26 scripted cases spanning 6 functional categories:
     - *Headcount & structure* (`active`, `engineering`, `by_department`, `reference_divisions`)
     - *People & leave* (`direct_reports`, `leave`, `hr_assignments`)
     - *Compensation & payroll* (`salary`, `bonus`, `negative_pay`, `header_gap`, `completed_runs`, `pay_vs_period`, `off_cycle`, `tax_zero`)
     - *Authorization boundaries* (`forbidden_salary`, `forbidden_number`, `out_of_scope`)
     - *Adversarial behavior* (`show_schema`, `role_escalate`, `set_principal`, `function_sleep`, `write_attempt`)
     - *Semantics & reliability* (`ambiguous`, `current_date`, `result_cap`)
2. **Multi-Tab Outcome Inspector**:
   - **Tab 1: Decision & Journey**: Displays the expected outcome (`ANSWERED`, `BLOCKED_VALIDATOR`, `BLOCKED_DB`, `CLARIFICATION_REQUIRED`, `SCOPED_RESULT`), governing policy rationale, stopping layer, reason code, and a six-stage runtime execution trace.
   - **Tab 2: Expected Results**: Formatted data table showing expected results, row-level scope indicators, or explicit refusal banners. Includes truncation warnings for large result sets (e.g. 1,000 row cap on deductions).
   - **Tab 3: Scripted SQL**: Developer-facing reference SQL accompanied by explicit disclaimers: *"Developer-facing SQL illustration · manually scripted · not executed in demo"*.
   - **Tab 4: Mock Trace**: Complete structured JSON trace (`E0_STATIC_SIMULATION_NOT_EXECUTED`) matching FR-9.7 diagnostics.
   - **Tab 5: Run History**: In-session audit trail recording simulated scenarios, personas, and outcomes.
3. **Interactive Security Probes**:
   - 13 adversarial probes verifying defense-in-depth:
     - `spoof`: Tests `SET app.principal_id` (Validator-only layer).
     - `role`: Tests `SET ROLE app_payroll` role escalation (Validator + DB membership).
     - `function`: Tests `pg_sleep()` abuse (Validator + statement timeout).
     - `catalog`: Tests `pg_catalog.pg_tables` probing (Validator schema restriction).
     - `write`: Tests `DELETE FROM employees` DML (Validator + read-only transaction).
     - `salary`: Tests cross-role base_salary access (Validator + DB grants).
     - `leave`: Tests sales access to leave balances (DB table denial).
     - `employee_number`: Tests sales/HR access to sensitive column (DB column grants).
     - `active_headcount`: Tests sales metric calculation without required columns.

---

## 4. Simulated Persona Identity Model (FR-1, FR-10.1)

The application models four canonical business personas:

| Persona Display Name | Business Role | Principal ID | Login Role | Authorized Scope |
| :--- | :--- | :--- | :--- | :--- |
| **Payroll specialist** | `app_payroll` | `326` | `stark_payroll_login` | Full access to employee, compensation, payroll, and leave records. `hr_bp_assignments` restricted. |
| **HR business partner #1** | `app_hr_bp` | `47`* | `stark_hr_login` | Employee and leave records restricted to assigned divisions via `hr_bp_current_divisions()`. Compensation blocked. |
| **HR business partner #2** | `app_hr_bp` | `361`* | `stark_hr_login` | Identical HR role permissions with distinct assigned divisions. |
| **Sales manager** | `app_sales_mgr` | fixture-derived (mock: `7`) | `stark_sales_login` | Direct-report employee rows only (`manager_id = principal_id`). Limited to 5 columns. Compensation and leave denied. |

Login role names follow `policy/access_matrix.yaml`. \*The live runtime resolves the HR principals at startup (`db.persona.resolve_personas`; 364 is the FRD fallback), and it derives the Sales manager from the fixture. The offline mock in `offline_demo.py` currently uses placeholder `app_*_login` names and principal `7`. Those are mock values only and should be aligned with these names.

### Governance Notice:
The sidebar and playground prominently feature the disclaimer:
> *"Persona identity is simulated. This application does not provide authentication."*

---

## 5. Single-Flight Concurrency Guard (FR-10.7)

To prevent simultaneous pipeline execution, database connection pool exhaustion, and race conditions during Streamlit reruns, the UI enforces a two-tier concurrency control:

```
[User Clicks Ask]
        │
        ▼
[Acquire _UI_REQUEST_LOCK (Nonblocking)]
  ├── If Failed ──► Inform User & Abort Request
  └── If Acquired
        │
        ├─► Set session_state[BUSY_KEY] = True
        ├─► Render Disabled Ask Button + Spinner
        ├─► Execute pipeline.answer(persona, question, as_of_date)
        │
        ▼
   [finally]
        ├─► Release _UI_REQUEST_LOCK
        ├─► Set session_state[BUSY_KEY] = False
        └─► Rerun to restore enabled Ask button
```

### Stale State Recovery:
If a user closes their browser or terminates a request mid-flight, `initialize_state()` detects orphaned busy flags and recovers them only after verifying that no process thread currently holds `_UI_REQUEST_LOCK`.

---

## 6. Zero Information Disclosure & Outcome State Mapping

The `render_safe_response()` component renders individual authorized attributes and rejects full outcome serialization:

- **`ANSWERED`**: Displays permitted data cells in an interactive pandas DataFrame (`hide_index=True`). If row scope is active (direct reports, assigned divisions), a "Scoped result" banner is shown. If 0 rows matched, *"No permitted rows matched this question."* is rendered. If truncated, an explicit truncation banner is displayed.
- **`BLOCKED_VALIDATOR`**: Displays *"Blocked"* with public reason message (`public_message_for(ReasonCode.VALIDATOR_REJECTED)`).
- **`BLOCKED_DB`**: Displays *"Blocked"* with public reason message (`public_message_for(ReasonCode.DB_PERMISSION_DENIED)`).
- **`CLARIFICATION_REQUIRED`**: Displays *"Clarification needed"*, the clarifying business question, and selectable disambiguation options.
- **`TIMEOUT`**: Displays *"Answer unavailable"* with a generic time-limit notice.
- **`ERROR`**: Displays *"Answer unavailable"* with generic completion notice. Internal exception messages, database drivers, SQLSTATE codes, and stack traces are completely suppressed.

---

## 7. Verification Evidence

- **Unit & Contract Suite**: 38 tests passing (`tests/test_interim_ui.py`, `tests/test_ui_rerun_contracts.py`, `tests/test_trace_ui_contracts.py`, `tests/test_ui_e0_scenarios.py`).
- **Component Tests**: 9 tests passing (`tests/test_ui_components.py`).
- **Headless AppTest Journey Suite**: 5 tests passing (`tests/test_ui_browser_automation.py`). This is Streamlit `AppTest` against the mock backend, not a real browser, and it is not live acceptance.
- **AST Compliance**: Pinned AST tests verify zero usage of `query_params`, `experimental_get_query_params`, or mode selectors.
