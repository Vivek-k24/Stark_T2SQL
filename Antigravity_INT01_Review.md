# Independent Architecture & Security Review: Gate INT-01 (ISS-15)

**Gate:** INT-01 — Automated Agent Handoffs and Offline Progress UI  
**Tracking Issue:** [Issue #15](https://github.com/Vivek-k24/Stark_T2SQL/issues/15)  
**Implementation PR:** [Draft PR #16](https://github.com/Vivek-k24/Stark_T2SQL/pull/16)  
**Shared Working Branch:** `codex/interim-orchestration-ui`  
**Base Branch:** `gemini/full-remediation-review` (merge base `3855429425020c3619e24fabc64d45d988828009`)  
**Auditor:** Antigravity (Independent Architecture & Security Reviewer)  
**Date:** 2026-10-14  

---

## 1. Executive Summary & Verdict

### Final Verdict: **APPROVE**

Codex's implementation in [Draft PR #16](https://github.com/Vivek-k24/Stark_T2SQL/pull/16) successfully fulfills all requirements set forth in [GitHub Issue #15](https://github.com/Vivek-k24/Stark_T2SQL/issues/15) and `AGENTS.md`. It establishes a robust, fail-closed, supervised multi-agent control plane in `ops/` alongside a safe, strictly loopback-bound Streamlit status and progress UI.

### Plain-Language Summary of Findings:
1. **Fail-Closed Supervised Handoffs:** The orchestration engine (`ops/coordinator.py`, `ops/runtime.py`, `ops/contracts.py`) enforces strict state transitions driven exclusively by validated, machine-readable markers (`<!-- STARK_HANDOFF_V1 ... -->`) embedded in committed report Markdown. Unstructured review text, issue comments, or PR descriptions are never interpreted as instructions.
2. **Process & Workspace Isolation:** Subprocess invocations use argument vectors without shell wrappers (`.cmd`, `.bat`, `.ps1` are explicitly blocked). Subprocess trees are terminated with bounded timeouts. Each phase executes in an isolated, clean git clone in a private state directory outside the repository checkout. Child processes are stripped of database, HR, and GitHub credentials.
3. **Broker-Owned Staging & Push:** AI agents are never given commit or push authority. The supervisor broker clears the clone staging index, verifies that only pre-approved in-scope files were touched, re-hashes frozen assets before and after execution, independently runs pytest, asserts that reported counts match measured counts, and commits/pushes via standard fast-forward git pushes.
4. **Accurate Public Progress & GitHub Sync:** `ops/progress.json` and the generated evidence region in `STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html` accurately document historical merges for Gates R01, R02, and R03 with exact merge SHAs, PR numbers, and offline test counts. Live PostgreSQL and model execution are explicitly labeled `UNVERIFIED` and `BLOCKED`.
5. **Truthful UI Health & Browser Smoke Verified:** The local Streamlit launcher (`ops/serve.py`, `app.py`) strictly binds numeric loopback (`127.0.0.1`), strips connected SQL environment variables, and labels views truthfully (`LIVE` indicates local UI process health, not backend SQL execution; offline E0 examples are clearly marked `DEMO / STATIC / SIMULATED`). Real headless browser startup and navigation were independently verified via Playwright and Microsoft Edge.
6. **No Scope Creep & Frozen Files Untouched:** All five frozen repository assets (`schema.sql`, `seed_data.py`, `fixture_manifest.json`, `fixture_pg_dump.sql`, `src/inference/prompt_template.txt`) and historical R01–R03 reviews/work logs remain 100% byte-for-byte identical to their authoritative references. No R04 source or database changes were introduced.

> [!IMPORTANT]
> **Sequential Gate Stop:** In accordance with `AGENTS.md`, PR #16 must be reviewed and merged into `gemini/full-remediation-review` by the repository owner before Gate R04 may be initiated. Neither agent is authorized to self-merge PR #16 or start R04.

---

## 2. Distinction of Operational Status

To prevent ambiguity, the operational status of INT-01 components is categorized into three explicit states:

### A. Working & Independently Verified Locally
- **Coordinator State Machine & Journal:** SQLite WAL-backed event journal (`ops/coordinator.sqlite`) and kernel-level project file locking (`msvcrt` on Windows, `fcntl` on POSIX) fully verified against concurrent execution, lock contention, out-of-order commits, duplicate phase markers, and crash recovery.
- **Offline Integration Exercise (`python -m ops.coordinator dry-run`):** Simulated fake-agent and fake-GitHub harness executes the complete implementation → verification cycle cleanly with zero external mutations or agent sessions.
- **Local Streamlit Application (`app.py`, `src/stark_t2sql/ui/project_status.py`):** Runs cleanly on `http://127.0.0.1:8501`, renders local UI health, cached public progress, and the embedded offline demo without requiring database or model credentials.
- **Real Browser Smoke Test (`python -m ops.smoke_ui`):** Successfully spun up an ephemeral loopback server, launched Microsoft Edge headless via Playwright, verified `/_stcore/health`, navigated across "Health & Status", "Architecture", and "Progress" views, captured evidence screenshots, and terminated the server cleanly.
- **Offline Test Suite:** 58 focused interim/trace UI tests and 514 full repository regression tests passed with zero failures and zero regressions.

### B. Mocked / Simulated Demonstrations
- **Offline E0 Interactive Prototype:** The prototype rendered in `STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html` and the Streamlit "Offline demo" view uses hardcoded, pre-scripted responses. Prompts and result sets are static simulations; no SQL queries are parsed, generated, or submitted to any engine.
- **Exercise Agent & GitHub Mocks:** `ops/exercise.py` utilizes in-memory mocks (`FakeGitHub`, `FakeAgents`) to test coordinator state transitions without invoking real LLM binaries or performing live GitHub REST mutations.

### C. Features Requiring One-Time Local Setup & Operator Opt-In
- **Windows Task Scheduler Registration:** No scheduled task has been installed or active in the background. Enabling periodic background polling requires the operator to run `ops/enable-coordinator.ps1 -Python <path> -Config <path> -Enable`.
- **Real Headless Agent Dispatches:** As confirmed by `ops.coordinator doctor`, `agy` is not present on PATH, and native Codex headless sandbox write / permission-denial smoke tests have not been executed. Agent handoffs remain intentionally **BLOCKED** and fail-closed until an operator populates a private `cli_smoke_evidence` JSON outside the repository.
- **Operator Enrollment Configuration:** An outside-the-checkout enrollment JSON file (modeled on `ops/enrollment.example.json`) must be created with explicit paths, trusted author logins, and authorized gate path ceilings before live handoffs can run.
- **Live PostgreSQL and SQLCoder Acceptance:** Live database execution remains disabled (`STARK_ENABLE_CONNECTED_UI` unset; `STARK_TEST_ENABLE_DB_INTEGRATION=0`). Verification of real PostgreSQL 16 RLS policies and local LLM inference remains an acceptance milestone for Gate R09.

---

## 3. Detailed Architecture & Security Audits

### A. State Machine & Event Gating (`ops/coordinator.py`, `ops/contracts.py`)
- **Marker Validation:** Reports must match regex `<!-- STARK_HANDOFF_V1\s*\n(.*?)\n-->`. Payloads are strictly parsed with duplicate key detection (`_unique` hook), validating exact required keys (`gate`, `phase`, `status`, `subject_sha`, `implementation_ready`, `tests`).
- **Verdict Semantics:**
  - `design`: Valid statuses are `APPROVE`, `REVISE`, `BLOCKED`. Dispatches occur only when `implementation_ready: true`. A design verdict of `BLOCKED` never dispatches.
  - `implementation`: Valid status is `IMPLEMENTATION_PUSHED`. Requires positive passing test counts (`failed == 0`, `passed > 0`, `scope == "offline"`).
  - `verification`: Valid statuses are `VERIFIED_APPROVE`, `VERIFIED_REVISE`, `VERIFIED_BLOCKED`. `VERIFIED_APPROVE` requires positive passing test evidence and sets readiness to `false`.
- **Concurrency & Locking:** `ownership(directory)` uses `msvcrt.locking` on Windows (`LK_NBLCK` / `LK_UNLCK`) with an open file handle, guaranteeing lock release upon process termination or crash, eliminating stale PID lockfile vulnerabilities.
- **Durable Claiming:** Phases are claimed in SQLite before dispatching subprocesses. An interrupted or failed attempt leaves a `RUNNING` or `ERROR` state, forcing the system into `STOP` to prevent duplicate or looping dispatches.

### B. Runtime Isolation & Broker Publishing (`ops/runtime.py`)
- **Execution Sanitization:** `run()` accepts argument vectors only. Executable paths with extensions `.cmd`, `.bat`, or `.ps1` raise `Stop`. Commands with `git` automatically disable hooks (`core.hooksPath=.git/stark-disabled-hooks`) and disable filesystem monitors (`core.fsmonitor=false`).
- **Timeout Management:** On Windows, subprocess timeouts invoke `taskkill.exe /PID <pid> /T /F` to guarantee termination of the entire child process hierarchy.
- **Fresh Clone Isolation:** Every phase is cloned into a fresh disposable directory (`phase-*`) under the private state directory. No worktree switching or branch switching affects the user's primary working tree.
- **Environment Scrubbing:** `agent_env()` preserves only fundamental Windows operating system paths (`PATH`, `SYSTEMROOT`, `TEMP`, `USERPROFILE`, etc.) and forces `STARK_TEST_ENABLE_DB_INTEGRATION="0"`. No PostgreSQL credentials, database connection strings, or GitHub tokens are passed to child processes.
- **Staging Allowlist & Frozen Asset Protection:** Prior to publication, the broker verifies that all working tree modifications are strictly within the intersection of the gate's built-in prefix ceiling and the owner-enrolled allowlist. All frozen assets are snapshotted via SHA-256 before and after execution; any modification immediately aborts publication with a `Stop`.
- **Git Push Guard:** Normal fast-forward pushes are enforced. `main` is strictly forbidden. Force-pushes and automatic merges are structurally impossible.

### C. GitHub API Adapter & Progress Tracker (`ops/github.py`, `ops/progress.py`)
- **Safe REST Retries:** Read-only calls retry up to 2 times upon transient failure; mutation calls are never retried automatically.
- **PR List Quirk Resolution:** GitHub API's `/pulls` list endpoint omits `merged_at` and `merged_by` for merged PRs; `ops/github.py` detects this and hydrates merged PRs via the individual `/pulls/{number}` endpoint.
- **Evidence Reconciliation:** `ops/progress.json` correctly captures actual merge SHAs for R01 (`51058398182e65a234f5e7da2b27a4ce763436ec`), R02 (`b8d149d7d58b87a35b251980814467cbca61661d`), and R03 (`3855429425020c3619e24fabc64d45d988828009`). Test numbers match independently measured counts.
- **Post-Merge Synchronization:** Post-merge updates require explicit owner opt-in (`postmerge_enabled: true`), verify the merging actor against `trusted_authors`, and allow changes only to `ops/progress.json` and the generated HTML evidence block in `STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html`.

### D. User Interface Security & Truthful Status (`app.py`, `src/stark_t2sql/ui/project_status.py`)
- **Loopback Enforcement:** `ops/serve.py` forces binding to `127.0.0.1`.
- **Connected Execution Lockdown:** If `STARK_ENABLE_CONNECTED_UI` is not explicitly set to `"1"`, `app.py` blocks access to connected query views, displaying a clear warning and directing users to read-only planning views.
- **Accurate Labeling:** UI components distinguish between `LIVE` (Streamlit process running), `LOCAL READY` (offline cached resources available), `DEMO / SIMULATED` (scripted responses without SQL execution), and `BLOCKED` (live database/model backend not configured).

---

## 4. Provenance & Frozen Asset Integrity

All five frozen repository assets were re-hashed independently using SHA-256 in the working tree. Zero drift detected:

| File | Authoritative SHA-256 Hash | Independently Measured Hash | Status |
| :--- | :--- | :--- | :--- |
| `schema.sql` | `f1b5976a08ebeeeb085d7095ddf25edfb06a261b2ebfe9f0653cb3a8b5128bf3` | `f1b5976a08ebeeeb085d7095ddf25edfb06a261b2ebfe9f0653cb3a8b5128bf3` | **MATCH** |
| `seed_data.py` | `ee9fd0a9965b51f6289290caa211460a65f9b2c38728bf99bb1133265d0561bf` | `ee9fd0a9965b51f6289290caa211460a65f9b2c38728bf99bb1133265d0561bf` | **MATCH** |
| `fixture_pg_dump.sql` | `859aa6badb797159f846d0870e377e3aade04049adc4174d2cd7dd6a98dd4fc4` | `859aa6badb797159f846d0870e377e3aade04049adc4174d2cd7dd6a98dd4fc4` | **MATCH** |
| `fixture_manifest.json` | `fb15e54afc4b72e02076614fec108049595ab1879feeabe9871f131fccb2640e` | `fb15e54afc4b72e02076614fec108049595ab1879feeabe9871f131fccb2640e` | **MATCH** |
| `src/inference/prompt_template.txt` | `67d1c6d265202e6bf6abcd1393203e84b92bf9df03207015679339fe807ad6b6` | `67d1c6d265202e6bf6abcd1393203e84b92bf9df03207015679339fe807ad6b6` | **MATCH** |

---

## 5. Independent Test Execution & Verification Evidence

All tests were executed using the approved local Python environment (`Python 3.12.10`, `pytest 8.3.5`, `Faker 40.43.0`, `streamlit 1.66.0`, `playwright 1.64.0`) with `$env:STARK_TEST_ENABLE_DB_INTEGRATION='0'`.

### A. Focused Interim Coordinator & UI Test Suite
```powershell
$env:STARK_TEST_ENABLE_DB_INTEGRATION = '0'
$env:PYTHONPATH = 'src;.'
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest tests/test_interim_coordinator.py tests/test_interim_ui.py tests/test_trace_ui_contracts.py -q -ra
```
**Result:** **58 passed in 4.88s (0 failed, 0 skipped, exit code 0)**.
- Fake integration and repeated ticks execute exactly once: **PASSED**.
- Resume uses durable saved phases: **PASSED**.
- Verification never restarts implementation or begins next gate: **PASSED**.
- Design verdict without explicit ready never dispatches: **PASSED**.
- Malformed markers fail closed (invalid JSON, missing fields, duplicate keys): **PASSED**.
- Out-of-order commits and doc-only updates never dispatch: **PASSED**.
- Untrusted commit authors cannot queue work: **PASSED**.
- Failure is durable and does not blindly retry: **PASSED**.
- Kernel lock excludes concurrent writers and releases upon termination: **PASSED**.
- Scope never accepts frozen or unauthorized paths: **PASSED**.
- Child environment scrubbed of HR/DB/GitHub secrets: **PASSED**.
- CLI timeout bounded and shell wrappers rejected: **PASSED**.
- Real Git doc-only fast-forward publisher to local bare remote: **PASSED**.
- Actual merge required for status update and HTML is properly escaped: **PASSED**.
- GitHub API read retries bounded: **PASSED**.
- Post-merge sync doc-only once and stops: **PASSED**.
- AUTO enrollment reacts only to fresh manual design events: **PASSED**.
- GitHub API PR list shape hydrated for merge metadata: **PASSED**.
- Loopback launch cannot bind externally: **PASSED**.
- Real Streamlit public views operate without connected startup: **PASSED**.
- Original E0 navigation and truthful simulation labels preserved: **PASSED**.

### B. Full Repository Regression Test Suite
```powershell
$env:STARK_TEST_ENABLE_DB_INTEGRATION = '0'
$env:PYTHONPATH = 'src;.'
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest -q -ra
```
**Result:** **514 passed, 177 skipped in 33.56s (0 failed, exit code 0)**.
- Baseline passed tests increased from 463 (R03) to **514** (+51 tests).
- Zero regressions across the entire codebase.

### C. Offline Dry-Run Exercise
```powershell
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m ops.coordinator dry-run
```
**Result:**
```json
{
  "exercise": "FAKE AGENTS / FAKE GITHUB",
  "sequence": ["implementation", "verification"],
  "repeat_dispatches": 0,
  "final_state": "VERIFIED — AWAITING MERGE",
  "next_gate": "NOT_STARTED",
  "real_agent_sessions": 0,
  "real_repository_modified": false
}
```

### D. System Capability & Doctor Check
```powershell
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m ops.coordinator doctor
```
**Result:**
```json
{
  "platform": "win32",
  "codex": {
    "available": true,
    "version": "codex-cli 0.101.0",
    "headless_flags": true,
    "reason": "CLI configuration/auth/status check failed; inspect interactively"
  },
  "antigravity": {
    "available": false,
    "reason": "Native CLI not found on PATH/official npm native package"
  },
  "streamlit": {
    "available": true
  },
  "scheduled_trigger": "NOT_FOUND_OR_QUERY_DENIED",
  "sandbox_write_smoke": "NOT_RUN",
  "state": "BLOCKED",
  "task_scheduler": "QUERY_SUCCEEDED; check did not register a task"
}
```

### E. Independent Headless Browser Smoke Test
```powershell
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m ops.smoke_ui
```
**Result:**
```json
{
  "health_endpoint": "PASSED",
  "browser": "Microsoft Edge headless",
  "browser_views": ["Health & Status", "Architecture", "Progress"],
  "bind": "127.0.0.1",
  "connected_sql": "NOT_EXECUTED",
  "agent_sessions": 0,
  "server_after_smoke": "STOPPED"
}
```
Independently confirmed generation of screenshots in `ops/evidence/`: `ui-health.png`, `ui-architecture.png`, `ui-progress.png`.

---

## 6. Final Recommendation & Sequential Stopping Gate

1. **Gate Acceptance:** The INT-01 implementation in [Draft PR #16](https://github.com/Vivek-k24/Stark_T2SQL/pull/16) is fully verified, architecturally sound, fail-closed, and strictly compliant with repository rules. Verdict: **APPROVE**.
2. **Sequential Promotion:** [Draft PR #16](https://github.com/Vivek-k24/Stark_T2SQL/pull/16) is recommended for merge into `gemini/full-remediation-review` by the repository owner.
3. **Mandatory Stopping Gate:** In strict accordance with `AGENTS.md`, Gate R04 may not begin until PR #16 is merged by the repository owner.

<!-- STARK_HANDOFF_V1
{"gate": "INT01", "implementation_ready": false, "phase": "verification", "status": "VERIFIED_APPROVE", "subject_sha": "4bdc22e0b7c6a01c89c8cae562933fad7ecb62f7", "tests": {"failed": 0, "passed": 514, "scope": "offline", "skipped": 177}}
-->


