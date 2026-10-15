# Antigravity Gate R08 Architecture, Security and PR Conflict Design Review

**Project:** STARK T2SQL  
**Gate:** R08 — Resolve Overlapping PRs, UI Regressions and Limited Cleanup (ISS-12/17/21/22)  
**Tracking Issue:** [GitHub Issue #10](https://github.com/Vivek-k24/Stark_T2SQL/issues/10)  
**Integration Baseline Commit:** `4364b38dac6dee5b81e946f216a8202cd3bef8c7` (verified owner merge of Gate R07 PR #22 into `gemini/full-remediation-review`)  
**Shared Working Branch:** `codex/r08-remediation`  
**Date:** 2026-10-15  
**Reviewer:** Antigravity (Independent Architecture & Security Reviewer)  
**Verdict:** **APPROVE** (Design Approval for Codex Implementation)  

---

## 1. Executive Summary

Pursuant to `AGENTS.md`, FRD 1.8 (Section 4, FR-4.1–FR-4.8; Section 10, FR-10.4–FR-10.7; S7.1), and GitHub Issue #10 (`R08 | Resolve overlapping PRs, UI regressions and limited cleanup (ISS-12/17/21/22)`), Antigravity has conducted an independent architecture, security, and PR conflict design review.

Gate R08 resolves the divergence between historical unmerged draft PR #1 (`assistant/sqlcoder-runtime-integration`, head `cacffee29234cbbce6b471539e712999a3b435e1`, base `main` at `8df53bf`) and the canonical integration baseline on `gemini/full-remediation-review` (head `4364b38dac6dee5b81e946f216a8202cd3bef8c7`). PR #1 was authored independently against an initial repository snapshot before Gates R01 through R07 were integrated. Consequently, PR #1 cannot be cherry-picked, fast-forwarded, or merged directly without regressing critical security, offline-demo, and schema enhancements introduced in earlier gates.

This design review audits the exact 8 files modified in PR #1 against the integration baseline, classifies each modification, provides technical solutions for ISS-12, ISS-17, ISS-21, and ISS-22, establishes Codex implementation boundaries, and outlines a comprehensive acceptance criteria matrix.

### Diagnostic Test Execution
Baseline offline UI contract tests were verified using `H:\STARK_T2SQL_R02_ENV\Scripts\python.exe`:
```powershell
$env:PYTHONPATH='src;.'; $env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
pytest tests/test_trace_ui_contracts.py -q -ra
```
**Results:** **7 passed** in 0.11s (0 failed).

### Core Findings & Architectural Conclusions:
1. **Inference Client Protocol & Semicolon Inference Hazard (ISS-12):** On the current integration branch, `client.py` contains an architectural vulnerability: lines 313–316 evaluate `stopped_semicolon = (stopped_word and ...) or raw_output.rstrip().endswith(";")`. String-suffix matching guesses that a semicolon was an intentional stop reason, which can falsely treat a truncated query or prompt leak as a successful semicolon stop. PR #1's structured `_completion_termination()` eliminates this guessing, properly parses modern (`stop_type`), legacy (`stopped_*`), and compact (`stop=True`) payloads, and classifies compact completions as `STOP_REASON_UNSPECIFIED` rather than fabricating semicolon stops.
2. **Watchdog Socket Lifecycle Race Condition (ISS-12):** In `_interrupt_socket()`, calling `current_socket.close()` from the background watchdog thread races with the foreground worker thread in `generate()`, where `HTTPConnection.close()` in the `finally` block sets `connection.sock = None`. This leads to `AttributeError` or descriptor corruption. Restricting `_interrupt_socket()` to `current_socket.shutdown(socket.SHUT_RDWR)` cleanly interrupts blocked I/O while leaving descriptor closure strictly to the foreground thread.
3. **Streamlit Rerun Orphan Busy Recovery (ISS-17 / ISS-21):** When a browser refresh, navigation, or exception occurs during a request, Streamlit session state can retain `stark_request_busy = True`. Because `initialize_state()` currently only executes `setdefault(BUSY_KEY, False)`, subsequent script reruns remain permanently locked behind `st.stop()`. PR #1's pattern resets `BUSY_KEY` to `False` in `initialize_state()` if and only if the process-wide `_UI_REQUEST_LOCK` is not held. Adding a `"Refresh status"` button in `render_processing()` provides a safe user-initiated recovery path.
4. **Sidebar Persona Selector Anchoring (ISS-17 / ISS-21):** On the integration branch, `render_persona_selector()` appends the persona selectbox to `st.sidebar` after all static shell elements, placing it *below* the static footer disclaimer captions. PR #1 creates a pre-footer `persona_slot = st.container()` in `render_shell()` before the footer captions, allowing the persona selector to render neatly above the disclaimer text.
5. **Preservation of Integration Baseline Extensions (Conflict Resolution):** PR #1 reverted `NAVIGATION` in `views.py` and removed `render_health()`, `render_demo()`, and the `STARK_ENABLE_CONNECTED_UI` safety gate in `app.py`. These removals must be **REJECTED**. The offline status, progress, and demo tabs added in INT-01/R01-R03 must be preserved.
6. **Policy-Derived Authorization Probes (ISS-22):** In `benchmarks/authorization/spec.py`, PR #1 refactors `build_probes()` to derive directly from canonical `authorization_specs()`, correctly asserting that `SELECT *` requires all projected column grants. This eliminates duplicated privilege logic while preserving public probe IDs and deterministic ordering.
7. **Native Model Response Sample Absence:** An exhaustive repository search confirms that no raw native `llama-server` response capture files (`.json`, `.resp`, `.raw`) exist on disk. Only synthetic test payloads are present. This absence is formally reported.

Antigravity issues an **APPROVE** verdict for this design phase.

---

## 2. Line-by-Line PR #1 vs. Integration Baseline Comparison & Classification Matrix

PR #1 (`cacffee29234cbbce6b471539e712999a3b435e1`) modified exactly 8 files relative to initial commit `8df53bf`. Below is the complete classification and conflict analysis comparing PR #1 against `codex/r08-remediation` (`4364b38dac6dee5b81e946f216a8202cd3bef8c7`):

| File Path | PR #1 Modifications | Integration Baseline State | Classification | Rationale & Conflict Resolution |
| :--- | :--- | :--- | :---: | :--- |
| `src/stark_t2sql/inference/client.py` | Extracted `_completion_termination()`; added `response_fields` to payload; removed `current_socket.close()` from watchdog; used configured timeout. | Has ad-hoc fallback logic that guesses semicolons via `endswith(";")`; calls `current_socket.close()` in watchdog; uses hardcoded `decoding.timeout_seconds`. | **ADOPT** | Adopt PR #1's structured parser and watchdog socket safety. Eliminates dangerous semicolon guessing, prevents socket races, and allows configurable timeouts. |
| `app.py` | Unpacked `(navigation, persona_slot) = render_shell()`; passed `persona_slot` to `render_persona_selector()`. Omitted `render_health`, `render_demo`, and connected check. | Contains `render_health()`, `render_demo()`, and `STARK_ENABLE_CONNECTED_UI` check introduced in INT-01/R01-R03. | **ADAPT** | Adopt the persona slot parameter and layout anchoring. Reject the deletion of `render_health()`, `render_demo()`, and `STARK_ENABLE_CONNECTED_UI`. |
| `src/stark_t2sql/ui/ui_state.py` | In `initialize_state()`, reset `state[BUSY_KEY] = False` if `BUSY_KEY` is True and `_UI_REQUEST_LOCK.locked()` is False. | Calls `state.setdefault(BUSY_KEY, False)` only, leaving orphan busy states permanently stranded. | **ADOPT** | Clean, safe, and necessary fix for ISS-17. Protects concurrency while recovering from aborted runs. |
| `src/stark_t2sql/ui/views.py` | `render_shell()` returns `(selected, persona_slot)`; `render_persona_selector()` targets `persona_slot`; `render_processing()` adds "Refresh status" button; reverted `NAVIGATION` to 5 items. | `render_shell()` returns `str`; `render_persona_selector()` appends to sidebar bottom; `NAVIGATION` has 7 items including "Health & Status" and "Offline demo". | **ADAPT** | Adopt pre-footer persona slot and "Refresh status" button. Reject the reversion of `NAVIGATION` to 5 items (keep 7 items to preserve offline status/demo). |
| `benchmarks/authorization/spec.py` | `build_probes()` derives expectations from `authorization_specs()`; star probe checks `all(spec.expected_select for spec in column_specs)`. | Manually re-checks `matrix.permitted_columns(...)` with dictionary lookups on `role.tables`. | **ADOPT** | Aligns benchmark probes with canonical policy specs without executing SQL. Preserves stable probe IDs and deterministic ordering. |
| `tests/test_inference_protocol.py` | New file: 4 test functions verifying native llama.cpp metadata formats, fail-closed handling, and watchdog socket ownership. | File does not exist on integration branch. | **ADOPT** | Adopt entirely. Provides comprehensive offline coverage for ISS-12 contracts. |
| `tests/test_ui_rerun_contracts.py` | New file: tests orphan busy recovery, lock concurrency, exception unwinding, sidebar anchor positioning, and refresh button. | File does not exist on integration branch. | **ADAPT** | Adopt test logic, but adapt line 105 `assert navigation == "Playground"` to recognize `"Health & Status"` as the default navigation tab. |
| `tests/test_authorization_probe_alignment.py` | New file: tests column probes matching policy specs, star probe alignment, and probe ID/order stability. | File does not exist on integration branch. | **ADOPT** | Adopt entirely. Fully verified against existing `matrix` and `schema_metadata` test fixtures. |

---

## 3. Detailed Technical Audits

### 3.1 Inference Reliability (ISS-12)
- **Component Audited:** `src/stark_t2sql/inference/client.py` and `tests/test_inference_protocol.py`.
- **Termination Protocol Normalization:**
  - `_completion_termination(payload, max_tokens)` cleanly normalizes the three distinct response styles produced by various `llama.cpp` releases:
    1. **Modern (`stop_type`):** Newer builds report `stop_type` in `{"word", "eos", "limit", "none"}` and `stopping_word`. When `stop_type == "word"`, it verifies `stopping_word == ";"`. If `stopping_word` is any unapproved token (e.g. `\n`, `SELECT`), it raises `ModelGenerationError`.
    2. **Legacy (`stopped_*`):** Older builds return booleans `stopped_word`, `stopped_eos`, and `stopped_limit`. The parser requires exactly one flag to be `True`. If `stopped_word == True`, it verifies `stopping_word == ";"`.
    3. **Compact (`stop=True` only):** Minimal builds return only `stop: true` and `tokens_predicted`. Because compact output cannot distinguish an EOS token from a word stop, it must **never claim a semicolon stop occurred**. If `tokens >= max_tokens`, it safely maps to `(True, False, "TOKEN_LIMIT", tokens)`. If `tokens < max_tokens`, it maps to `(False, False, "STOP_REASON_UNSPECIFIED", tokens)`.
  - **Elimination of Guessed Semicolons:**
    The integration branch contained:
    ```python
    stopped_semicolon = (
        (stopped_word and stopping_word in {";", None, ""})
        or raw_output.rstrip().endswith(";")
    )
    ```
    This fallback allowed a model generation that ended with `;` to be classified as a valid semicolon stop, even when the model ran out of tokens or was terminated externally. Adopting PR #1 removes this fallback entirely.
  - **Token Cap & Prompt Truncation:**
    - Any response reporting `tokens_predicted >= max_tokens` (without explicit word stop) is treated as `TOKEN_LIMIT`.
    - If `payload.get("truncated") is True`, the server truncated prompt context; `_completion_termination` immediately fails closed with `ModelGenerationError("The model truncated its supplied prompt context.")`.
  - **Watchdog Socket Ownership & Concurrency:**
    - In `_interrupt_socket(connection)`:
      ```python
      current_socket = getattr(connection, "sock", None)
      if current_socket is not None:
          try:
              current_socket.shutdown(socket.SHUT_RDWR)
          except OSError:
              pass
      ```
      Calling `shutdown(socket.SHUT_RDWR)` causes any blocking read or write on the socket descriptor to abort immediately with an error in the foreground thread. The watchdog never mutates `connection.sock` or calls `close()`, completely eliminating race conditions and `AttributeError` exceptions.
    - Single-flight protection is enforced via `self._single_flight = Lock()`, acquired with `blocking=False` at the beginning of `generate()` and released inside a `finally` block.
    - Deadline calculation uses `self.config.limits.generation_timeout_seconds`, enabling short timeouts in unit tests without arbitrary 120s delays.
- **Native Model Response Sample Audit:**
  - We conducted a recursive scan across the workspace for `.json`, `.resp`, `.raw`, and `.log` files.
  - **Outcome:** **ABSENT**. No raw native response capture from a live `llama-server` process exists in the repository. All existing test cases utilize synthetic dictionaries based on documented `llama.cpp` HTTP API contracts.

### 3.2 Streamlit UI Reliability & State Management (ISS-17 / ISS-21)
- **Component Audited:** `app.py`, `src/stark_t2sql/ui/ui_state.py`, `src/stark_t2sql/ui/views.py`, and `tests/test_ui_rerun_contracts.py`.
- **Orphan Busy State Recovery:**
  - Streamlit re-executes `app.py` upon any browser interaction. If an unhandled exception or browser navigation interrupts a running request, `st.session_state[BUSY_KEY]` can remain `True` while the background thread has exited.
  - On the integration branch, `initialize_state()` simply did `state.setdefault(BUSY_KEY, False)`, stranding the UI permanently on the `render_processing()` screen.
  - PR #1 resolves this:
    ```python
    if state.get(BUSY_KEY) is True and not _UI_REQUEST_LOCK.locked():
        state[BUSY_KEY] = False
    else:
        state.setdefault(BUSY_KEY, False)
    ```
    If `_UI_REQUEST_LOCK.locked()` is `False`, no thread is actively executing a request, so the stale session flag is safely cleared.
- **Status Refresh Button:**
  - In `render_processing()`, PR #1 adds `st.button("Refresh status", key="stark_refresh_busy_status")`. This enables users to trigger a manual rerun if an asynchronous task completed without an automatic UI reload, without bypassing the concurrency lock.
- **Sidebar Layout & Pre-Footer Slot:**
  - In `render_shell()`:
    ```python
    persona_slot = st.container()
    st.caption("Persona identity is simulated. This application does not provide authentication.")
    st.caption("FULL is the only connected request mode.")
    return selected, persona_slot
    ```
  - `render_persona_selector(application, *, persona_slot=persona_slot)` populates this reserved container. This guarantees that the persona dropdown appears above the static disclaimer notes rather than being appended beneath them.
- **Duplicate Ask Prevention & Secret Hygiene:**
  - Inside `render_playground()`, clicking "Ask" enters `with request_guard(st.session_state)`.
  - The "Ask" button is immediately overwritten in `button_slot` with `st.button("Ask", disabled=True, key="stark_processing_ask")` before invoking `application.answer()`.
  - If any exception occurs during processing, it is caught and converted to a sanitized `SafeResponse(status=OutcomeStatus.ERROR, stopping_layer=StoppingLayer.INTERNAL, reason_code=ReasonCode.INTERNAL_ERROR)`. Raw SQL, database error messages, stack traces, and model prompts never enter `st.session_state` or the presentation layer.

### 3.3 Policy-Derived Authorization Probes (ISS-22)
- **Component Audited:** `benchmarks/authorization/spec.py` and `tests/test_authorization_probe_alignment.py`.
- **Policy Alignment:**
  - `build_probes()` in `benchmarks/authorization/spec.py` originally performed ad-hoc role/table/column dictionary queries against `matrix`.
  - PR #1 replaces this with a direct mapping from `authorization_specs(matrix, snapshot.columns_by_table)`:
    ```python
    expectations = {
        (spec.business_role, spec.table, spec.column): spec
        for spec in authorization_specs(matrix, snapshot.columns_by_table)
    }
    ```
  - For individual column probes: `probe.expected_access = spec.expected_select` and `probe.row_scope = spec.row_scope`.
  - For the star probe (`authorization.<role>.<table fire>.star`):
    `all(spec.expected_select for spec in column_specs)`
    Because PostgreSQL rejects `SELECT *` if even a single column grant is missing, the star probe succeeds if and only if all columns in that table are permitted.
  - Probe identifiers (`authorization.<role>.<table fire>.<column>` and `authorization.<role>.<table fire>.star`) and iteration order remain completely stable.
  - The implementation executes entirely offline against `PolicyMatrix` and `SchemaSnapshot` without executing SQL or requiring a database connection.
  - **Scope Limitation:** Unrelated changes to `semantic/catalog.yaml` or semantic resolver APIs are strictly deferred.

---

## 4. Disposition Plan for PR #1 and PR #2

### 4.1 Historical Draft PR #1 (`assistant/sqlcoder-runtime-integration`)
- **Status:** Unmerged, head `cacffee29234cbbce6b471539e712999a3b435e1`, base `main`.
- **Analysis:**
  - PR #1 was branched from commit `8df53bf` (the initial repository commit) before Gates R01 through R07 were implemented.
  - Directly merging or rebasing PR #1 onto `gemini/full-remediation-review` or `main` would overwrite critical architectural fixes from R01–R07 (including offline project health/demo views, validator contracts, and RLS canary security).
  - Its 4 ADOPT items and 2 ADAPT items are being incorporated into `codex/r08-remediation` cleanly and with full regression testing.
- **Recommendation:**
  - **Do NOT merge PR #1.**
  - Once Gate R08 is approved and merged into `gemini/full-remediation-review`, the owner should **close PR #1 without merging**, referencing Issue #10 and Gate R08 PR #23.

### 4.2 Draft PR #2 (`gemini/full-remediation-review`)
- **Status:** Open, targeting `main`, current head `4364b38dac6dee5b81e946f216a8202cd3bef8c7`.
- **Analysis:**
  - PR #2 is the cumulative integration branch containing all approved gates (R01 through R07).
  - Gate R08 PR #23 will target `gemini/full-remediation-review`.
- **Recommendation:**
  - **Keep PR #2 open and unmerged.**
  - `main` remains untouched until Gate R09 post-remediation audit and final end-to-end verification are complete.

> [!IMPORTANT]
> **Owner Handoff Rule:** Neither PR #1 nor PR #2 may be merged, closed, or modified automatically by any agent. All PR actions require explicit owner approval.

---

## 5. File Ownership Boundaries for Codex (Implementation Phase)

In strict accordance with `AGENTS.md` and GitHub Issue #10, file modifications during Gate R08 implementation are strictly limited to:

### Permitted Implementation Files:
1. `src/stark_t2sql/inference/client.py` (ADOPT `_completion_termination`, `response_fields`, watchdog shutdown fix, timeout).
2. `app.py` (ADAPT: wire `persona_slot` while strictly preserving `render_health`, `render_demo`, and `STARK_ENABLE_CONNECTED_UI`).
3. `src/stark_t2sql/ui/ui_state.py` (ADOPT stale busy recovery in `initialize_state`).
4. `src/stark_t2sql/ui/views.py` (ADAPT: pre-footer `persona_slot` and refresh button; retain 7-item `NAVIGATION`).
5. `benchmarks/authorization/spec.py` (ADOPT policy-derived probe generator).
6. `tests/test_inference_protocol.py` (ADOPT new test suite).
7. `tests/test_ui_rerun_contracts.py` (ADAPT new test suite: line 105 navigation assertion).
8. `tests/test_authorization_probe_alignment.py` (ADOPT new test suite).
9. `Codex_R08_Work_Log.md` (Implementation log).

### Strictly Frozen / Prohibited Files (DO NOT MODIFY):
- `schema.sql`, `seed_data.py`, `fixture_manifest.json`, `fixture_pg_dump.sql` (FROZEN)
- `policy/access_matrix.yaml`, `semantic/catalog.yaml` (FROZEN)
- `src/inference/prompt_template.txt` (FROZEN)
- `STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html` and `ops/progress.json` (Reserved for Antigravity at verification)
- `Antigravity_Design_Review.md` (Preserve unrelated working tree edits)
- No modification of `main`, no unapproved database resets, no starting Gate R09.

---

## 6. Step-by-Step Implementation Sequence for Codex

When prompted by the owner to implement Gate R08 on `codex/r08-remediation`, Codex must execute the following sequence:

1. **Phase 1: Implement `_completion_termination` and Watchdog Socket Safety in `client.py`**
   - Add `response_fields` to the `/completion` request body.
   - Implement `_completion_termination(payload, max_tokens)` in `src/stark_t2sql/inference/client.py`.
   - In `_interrupt_socket(connection)`, remove `current_socket.close()`, retaining only `shutdown(socket.SHUT_RDWR)`.
   - Update `deadline = started + self.config.limits.generation_timeout_seconds`.
2. **Phase 2: Implement Stale Busy Recovery in `ui_state.py`**
   - In `src/stark_t2sql/ui/ui_state.py`, update `initialize_state()` to clear `BUSY_KEY` if `state.get(BUSY_KEY) is True and not _UI_REQUEST_LOCK.locked()`.
3. **Phase 3: Adapt Sidebar Persona Slot & Status Refresh in `views.py`**
   - In `render_shell()`, create `persona_slot = st.container()` before footer captions, and return `(selected, persona_slot)`.
   - In `render_persona_selector()`, accept `*, persona_slot` and render into `with persona_slot:`.
   - In `render_processing()`, add `st.button("Refresh status", key="stark_refresh_busy_status")`.
   - **Do NOT alter `NAVIGATION`:** Retain all 7 entries: `("Health & Status", "Architecture", "Progress", "Offline demo", "Playground", "Semantic Catalog", "Access Policy")`.
4. **Phase 4: Adapt `app.py`**
   - Unpack `navigation, persona_slot = render_shell()`.
   - Pass `persona_slot=persona_slot` to `render_persona_selector(application, persona_slot=persona_slot)`.
   - Preserve `render_health()`, `render_demo()`, and the `STARK_ENABLE_CONNECTED_UI` safety block.
5. **Phase 5: Implement Policy-Derived Probes in `benchmarks/authorization/spec.py`**
   - Refactor `build_probes()` to derive expectations from `authorization_specs()`.
   - Set star probe expectation to `all(spec.expected_select for spec in column_specs)`.
6. **Phase 6: Add and Adapt the Three Focused Test Files**
   - Add `tests/test_inference_protocol.py` (as in PR #1).
   - Add `tests/test_authorization_probe_alignment.py` (as in PR #1).
   - Add `tests/test_ui_rerun_contracts.py`, adapting line 105:
     ```python
     assert navigation == "Health & Status"  # or assert navigation in ("Playground", "Health & Status")
     ```
7. **Phase 7: Run Offline Verification & Open Draft PR**
   - Run the 4 focused test suites:
     ```powershell
     $env:PYTHONPATH='src;.'; $env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
     pytest tests/test_inference_protocol.py tests/test_ui_rerun_contracts.py tests/test_authorization_probe_alignment.py tests/test_trace_ui_contracts.py -q -ra
     ```
   - Run the entire offline test suite to confirm 0 regressions.
   - Commit code, tests, and `Codex_R08_Work_Log.md` to `codex/r08-remediation`.
   - Push to `origin/codex/r08-remediation` and open one draft PR targeting `gemini/full-remediation-review`.
   - STOP and report commit SHA, test results, and draft PR URL to the owner.

---

## 7. Acceptance Criteria Matrix

| Criterion ID | Description | Verification Target | Expected Behavior |
| :--- | :--- | :--- | :--- |
| **R08-T01** | Modern `llama.cpp` Completion Formats | `test_native_completion_metadata_formats` | `stop_type` in `{"word", "eos", "limit"}` parsed with correct termination flags and finish reason. |
| **R08-T02** | Legacy `llama.cpp` Completion Formats | `test_native_completion_metadata_formats` | `stopped_word`, `stopped_eos`, `stopped_limit` parsed accurately. |
| **R08-T03** | Compact Completion Formatting | `test_native_completion_metadata_formats` | `stop=True` without stop reason parsed as `STOP_REASON_UNSPECIFIED` with `stopped_semicolon=False`. |
| **R08-T04** | No False Success at Token Cap | `test_native_completion_metadata_formats` | `tokens_predicted == 300` without word stop maps to `TOKEN_LIMIT`, never `SEMICOLON_STOP`. |
| **R08-T05** | Prompt Truncation Detection | `test_missing_conflicting_or_unsafe_terminal_metadata_fails_closed` | `truncated=True` raises `ModelGenerationError`. |
| **R08-T06** | Malformed / Conflicting Stop Data | `test_missing_conflicting_or_unsafe_terminal_metadata_fails_closed` | Conflicting booleans, unknown stop words, or `stop=False` fail closed with `ModelGenerationError`. |
| **R08-T07** | Watchdog Socket Thread Safety | `test_watchdog_shutdown_does_not_close_shared_http_connection` | Watchdog invokes `shutdown(SHUT_RDWR)` only; does not close `HTTPConnection` or mutate `sock`. |
| **R08-T08** | Single-Flight Concurrency Guard | `LocalInferenceClient.generate` unit check | Concurrent requests immediately raise `ModelGenerationError("The local model already has an active request.")`. |
| **R08-T09** | Orphan Busy Flag Recovery | `test_orphaned_session_busy_flag_recovers_when_no_ui_request_is_active` | `initialize_state` clears `BUSY_KEY` when `_UI_REQUEST_LOCK` is unlocked. |
| **R08-T10** | Active Concurrency Lock Protection | `test_busy_state_is_not_cleared_while_another_request_owns_ui_lock` | `initialize_state` retains `BUSY_KEY=True` while `_UI_REQUEST_LOCK` is held. |
| **R08-T11** | Exception Unwind & Guard Release | `test_base_exception_rerun_releases_guard_and_allows_next_request` | `StreamlitLikeRerun` unwinds `request_guard`, resetting `BUSY_KEY` and releasing the lock. |
| **R08-T12** | Pre-Footer Persona Slot Layout | `test_selector_is_visually_anchored_above_sidebar_footer` | Container appears before footer caption in sidebar DOM tree. |
| **R08-T13** | Refresh Button in Busy State | `test_processing_view_offers_refresh_without_enabling_another_ask` | "Refresh status" button rendered while "Ask" remains disabled. |
| **R08-T14** | Policy-Derived Column Probes | `test_every_column_probe_matches_authoritative_policy_spec` | Benchmark probes match `authorization_specs()` expectations without executing SQL. |
| **R08-T15** | Star Probe Requires All Columns | `test_star_probe_is_based_on_all_columns_not_table_level_acl` | `SELECT *` probe expected access requires `all(expected_select)`. |
| **R08-T16** | Probe Order & ID Stability | `test_probe_ids_and_original_order_remain_stable` | Public probe IDs and iteration sequence remain identical to baseline contracts. |
| **R08-T17** | UI Navigation & Demo Preservation | `app.py` & `views.py` offline smoke | "Health & Status" and "Offline demo" remain available without connected model/DB. |

---

## 8. Security Risks, Mock Boundaries & Protocol Stopping Rule

1. **Offline Review Boundary:**
   All contracts evaluated in Gate R08 operate purely offline against ASTs, policy matrices, synthetic payloads, and mock UI containers. No live PostgreSQL database, live `llama-server` process, or browser instance is launched or certified during this gate.
2. **PostgreSQL Security Boundary:**
   The client-side timeout, watchdog, and validator guards protect against runaway local resource consumption. However, PostgreSQL role-based access control, column-level grants, and Row Level Security remain the authoritative data protection boundary.
3. **Stopping Gate Protocol:**
   In strict compliance with `AGENTS.md` Rule 3:
   - Antigravity commits and pushes `Antigravity_R08_Review.md` to `origin/codex/r08-remediation` and **STOPS**.
   - No implementation source code is modified.
   - No PR is opened, merged, or closed.
   - `main` is not touched.
   - Next gate (R09) is not initiated.
   - Codex implementation begins only upon explicit direction from the repository owner.

<!-- STARK_HANDOFF_V1
{"gate": "R08", "implementation_ready": true, "phase": "design", "status": "APPROVE", "subject_sha": "4364b38dac6dee5b81e946f216a8202cd3bef8c7", "tests": {"failed": 0, "passed": 7, "scope": "offline", "skipped": 0}}
-->
