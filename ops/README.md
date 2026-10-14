# INT-01 local setup and supervised handoffs

This control plane handles **public source/status only**. It never runs HR
queries, model-generated SQL, database setup/reset, a merge, or the next gate.
It cannot control an existing IDE chat. Read `AGENTS.md` and Issue #15 first.

## What has been tested, and what is still blocked

- `python -m ops.coordinator dry-run` exercises fake GitHub and fake agents with
  the real SQLite journal/lock. It creates no real agent session or repo change.
- Offline tests cover duplicate/out-of-order events, errors/restart, blocked and
  revise verdicts, malformed markers, path scope, concurrency, timeout, PR
  identity, merge gating and a real Git push to a disposable **local bare
  remote**. That is not proof of a deployed GitHub post-merge trigger.
- `ops/evidence/capabilities.json` and `codex-probe.json` record actual sanitized
  machine checks. The PATH Codex launcher and a discovered native Codex can be
  different versions. Use the native executable that was actually probed.
- The native Codex benign read-only headless probe passed. Workspace-write and
  permission-denial smoke tests have **not** been performed. `agy` was unavailable.
  Full real-agent handoff automation remains **BLOCKED**.
- No scheduled task/service was enabled. Automatic post-merge publication is
  **BLOCKED pending explicit one-time task opt-in and its trigger verification**.
  Status-only enrollment needs no agent permission and can be enabled separately.
- The actual loopback Edge/Streamlit browser smoke passed. The health,
  Architecture and Progress screenshots are under `ops/evidence/`. The smoke
  stopped its server. No live PostgreSQL/model acceptance was established.

## Launch the UI safely

From the repository root, use a clean local Python virtual environment. Install
the declared project/dev dependencies; exact fixture regeneration needs
`Faker==40.43.0`. Streamlit 1.66.0 and Playwright 1.64.0 were used for INT-01.
Avoid inheriting unrelated globally installed packages into a fresh environment.
Do not install a model or provision a database for these views.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]' 'Faker==40.43.0' 'streamlit==1.66.0'
.\.venv\Scripts\python.exe -m ops.serve
```

Open `http://127.0.0.1:8501`. Ctrl+C stops the foreground server. `--port 8502`
selects a different unprivileged loopback port. The launcher binds numeric
loopback, disables usage telemetry and removes the connected-UI opt-in from
its child environment. It does not remove XSRF/CORS protections.

Health & Status, Architecture, Progress and the embedded original E0 offline
demo require no database/model credentials. LIVE on the health page means this
UI session is running, **not** that SQLCoder/PostgreSQL integration was proven.
Examples remain **STATIC / DEMO / SIMULATED**. The ordinary connected views are
blocked by default. This milestone does not authorize configuring their live
resources or enabling `STARK_ENABLE_CONNECTED_UI`.

To repeat the actual browser smoke, install Playwright in that environment and
use the existing Microsoft Edge installation:

```powershell
.\.venv\Scripts\python.exe -m pip install 'playwright==1.64.0'
.\.venv\Scripts\python.exe -m ops.smoke_ui
```

This briefly launches only its own loopback server, opens headless Edge, checks
the real page navigation and saves public screenshots, then stops the server.
It does not install a browser or start a DB/model. AppTest tests alone are not
substituted for this browser smoke.

## Canonical public progress

`ops/progress.json` is the versioned cache. `ops.progress` fetches the fixed
repository's actual PR metadata and immutable report blobs at each merge SHA.
Historical test counts must be present in those exact report bytes; a design
review's existence does not mark implementation complete. R01's final review
was not versioned in its historical review file, and is disclosed accordingly.
R02/R03 offline review evidence remains distinct from unverified live behavior.

```powershell
python -m ops.refresh
```

This refreshes only JSON and the generated evidence region in the **same**
tracked `STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html`. It does not push. Opening
that HTML locally works without GitHub. The Streamlit optional public GitHub
refresh is in-memory and falls back to cached evidence on network/auth failure.
No runtime HR question, row, SQL, DSN or credential enters GitHub status requests.

Before merge, Antigravity updates its review plus that HTML/JSON on the shared
gate branch with **VERIFIED — AWAITING MERGE**. It must never pre-label a PR
MERGED. Only a verified `merged` API response with the actual merge SHA advances
that state. Gate merges do not automatically complete entire FRD epics.

## Durable protocol and scope

The parser accepts one current marker per phase, inside the expected named
Markdown file at a corroborated commit. Review prose/comments are not commands.
Schema: `ops/handoff.schema.json`; runtime adds phase/status, positive test,
exact-field/duplicate-key and SHA/path checks.

Design template (replace the placeholder with the actual integration SHA):

```text
<!-- STARK_HANDOFF_V1
{"gate":"R04","phase":"design","status":"REVISE","subject_sha":"REPLACE_WITH_ACTUAL_BASE_SHA","implementation_ready":true,"tests":{"passed":0,"failed":0,"skipped":0,"scope":"not_run"}}
-->
```

`REVISE` may authorize remediation only with explicit `implementation_ready:true`.
`BLOCKED` never dispatches. A fresh design event changes **only** its review,
comes from an enrolled actor, and is bound to the integration baseline. The
previous milestone, including INT-01 before R04, must actually be owner-merged.

The Codex log adds `phase:implementation`, `status:IMPLEMENTATION_PUSHED`, the
design commit as `subject_sha`, and **actual numeric** offline test counts.
Antigravity appends a second marker to the **same review** with
`phase:verification`, `status:VERIFIED_APPROVE`, `VERIFIED_REVISE` or
`VERIFIED_BLOCKED`, the implementation commit reviewed, readiness false and its
actual counts. It preserves the initial design text/marker. No dummy approval,
SHA, count or run reference may be published from these templates.

Only these complete records can advance the state:

```text
explicit design-ready push → Codex editing → broker tests/commit/push/draft PR
→ Antigravity independent verification → broker tests/HTML/JSON/commit/push
→ STOP (VERIFIED — AWAITING MERGE, REVISE or BLOCKED)
→ actual owner merge → optional doc-only synchronization → STOP
```

One project lock excludes subprocess writers and the post-merge writer. SQLite
keys are `(gate, phase, input commit SHA)`. A RUNNING claim is durable **before**
dispatch. Completed inputs do not run again on doc-only updates or restart.
Uncertain attempts STOP instead of pretending exactly-once external execution
can be guaranteed across crashes. Read-only GitHub requests retry twice;
mutation/agent retries are never blind. A timeout terminates the owned process
tree. A crash may require operator reconciliation before any further dispatch.

Each phase uses a fresh clean clone attached to the same existing shared branch.
Agents get fixed prompts, not concatenated issue bodies or shell snippets, and
do not inherit GitHub/DB/HR environment secrets. The broker checks exact scope,
frozen-file bytes before/after agent/tests, branch/history/remote, measured test
counts, named reports and one draft PR. It clears only that isolated clone's
index before staging intended files, disables Git hooks/fsmonitor and uses a
normal fast-forward push. The broker, not the model, owns publication. Runtime
path scope is the intersection of the reviewed built-in gate ceiling and the
owner's narrower enrollment. Holdout/canary/private artifacts remain forbidden.

## One-time owner activation on Windows

No task was installed by this implementation. Run these steps only after
reviewing the source and authorizing the precise account, gate and permissions.
Never change execution policy, approve arbitrary tools or use unsafe CLI flags
to make setup succeed.

1. Use an isolated standard Windows account/profile for agent execution with no
   production DB/HR files, inherited service credentials or stored GitHub write
   credentials available to the agent. Supply the broker's narrow GitHub token
   through a private local secure mechanism, never a tracked file. The profile
   used by agents must pass real credential/network/permission denial probes.
   Application-level path checks alone are **not** an OS sandbox.
2. For agent handoffs, install/authenticate the **native** supported CLIs through
   the official vendor instructions. Existing IDE login does not prove headless
   access. Read [official Codex non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode)
   and [Google's Windows CLI setup](https://antigravity.google/docs/getting-started?tab=cli).
   No CLI installation or global config change is performed by these scripts.
3. Run `python -m ops.coordinator doctor`. `python -m ops.probe_codex` is only a
   fixed public-token read-only check. It cannot attest workspace-write safety.
   For **each** pinned native CLI, separately exercise an authenticated sandbox
   write inside an empty disposable workspace and a denied outside/privileged
   operation, without bypassing permissions. Record its actual executable
   SHA-256, timestamp and results in a private smoke-evidence JSON:

   ```json
   {"codex":{"sha256":"REPLACE_WITH_ACTUAL_BINARY_SHA256","observed_at":"ACTUAL_UTC_TIME","headless_authenticated":true,"workspace_sandbox_write_test":"passed","permission_denial_test":"passed"},"antigravity":{"sha256":"REPLACE_WITH_ACTUAL_BINARY_SHA256","observed_at":"ACTUAL_UTC_TIME","headless_authenticated":true,"workspace_sandbox_write_test":"passed","permission_denial_test":"passed"}}
   ```

   This is a trusted operator record of actual tests, not proof produced by
   setting Booleans. Missing/unperformed checks must remain absent/blocked.
   Do not expose this private file or agent stdout in GitHub/HTML.
4. Copy `ops/enrollment.example.json` to a **private location outside every
   checkout**. Fill actual absolute executable/state paths and set `enabled:true`
   only after approval. All example path/SHA placeholders intentionally fail.
   `status_only`, `gate:INT01` enables only post-owner-merge JSON/HTML updates,
   with no Codex/Antigravity requirement or agent dispatch. Keep CLI fields null.
   It still requires authenticated GitHub push permission and an actual approved
   verification marker. No branch protection is bypassed.
5. For a future pre-enrolled gate, use `mode:handoffs_and_status`, its gate name,
   exact approved paths/prefixes, trusted GitHub actors, native executable paths
   and the real private smoke-evidence path. `design_sha:null` detects the next
   explicit design-ready push, so the owner's starting action for that enrolled
   gate is only prompting Antigravity. An optional exact SHA pins a known event.
   Enrollment never widens itself or auto-selects/starts a following gate.
   To pre-enroll several future gates **once**, use `gate:AUTO`, `design_sha:null`
   and an `approved_paths` object keyed by each explicitly authorized gate:

   ```json
   {"gate":"AUTO","design_sha":null,"approved_paths":{"R04":["Codex_R04_Work_Log.md","src/stark_t2sql/semantic/","src/stark_t2sql/context/","semantic/catalog.yaml","tests/"]}}
   ```

   This is a fragment of the same private enrollment, not an alternative public
   config. Add other gate scopes only with owner authorization. The poller
   synchronizes the prior actual owner merge first, then waits for a **fresh
   explicit Antigravity design-ready push** for the next pre-enrolled gate,
   bound to the current integration SHA. It never creates a new design/branch,
   starts a gate merely because a merge occurred, or widens its scope. Thus the
   owner's starting action for each pre-enrolled gate is only the Antigravity
   design prompt; there is no required SHA-copy/config-edit handoff per phase.
6. From the checkout root, first run the check-only script, then explicitly opt
   in to the persistent trigger if all checks succeed:

   ```powershell
   .\ops\enable-coordinator.ps1 -Python $pythonExecutable -Config $privateEnrollment
   .\ops\enable-coordinator.ps1 -Python $pythonExecutable -Config $privateEnrollment -Enable
   Get-ScheduledTask -TaskName 'STARK-T2SQL-Supervised-Coordinator'
   Get-ScheduledTaskInfo -TaskName 'STARK-T2SQL-Supervised-Coordinator'
   ```

   Variables are owner-selected paths, not secrets. This runs as the current
   limited interactive account, once per minute, with IgnoreNew and bounded
   task duration. No installer infinite loop is started. The machine must be
   on, the account logged in, and network/secure credentials available. The
   durable journal survives restart. StartWhenAvailable covers missed starts;
   verify an actual scheduled tick and its `coordinator-last-result.json` before
   claiming triggers active. Permission denial must be reported, not bypassed.

Inspect the private `coordinator-last-result.json`, SQLite events and retained
phase clones for STOP/ERROR. To pause, use Task Scheduler or
`Disable-ScheduledTask -TaskName 'STARK-T2SQL-Supervised-Coordinator'`. No automatic
cleanup deletes these audit/recovery clones.

## Recovery and protected post-merge update

After an ERROR/crash, stop the old task/agents first and inspect the retained
clone and actual remote. Do not delete the journal or force-push to restart.
For a fully completed **already-pushed** phase with its single draft PR:

```powershell
python -m ops.coordinator reconcile --config $privateEnrollment --confirm-no-running-agent
```

Reconciliation checks the actor/commit/range/report/PR, reruns fixed offline
tests and marks the existing event complete. Unpublished or ambiguous work
remains STOP; resolve it under the same allowed branch/scope, then reconcile.
It never re-executes an uncertain agent automatically.
For AUTO enrollment, add `--recover-gate R04` (the affected enrolled gate).

`postmerge_enabled:true` lets a later `poll`/`sync` read the actual owner merge,
independent marker and document-only verification range. It takes the same
project lock, clones the current integration head, updates **only**
`ops/progress.json` and the generated E0 HTML region and normal-pushes if the
remote is unchanged. A unique gate/merge-SHA key prevents self-trigger loops.
Protected-branch rejection or remote advancement becomes ERROR; arrange the
owner-approved narrow documentation write permission rather than bypass it.
Wait for STOP_POSTMERGE_SYNCED before arming any next gate. There is no workflow
token or Actions file to silently enable, and no automatic merge operation.

## Repeat the offline tests

```powershell
$env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
$env:PYTHONPATH='src;.'
python -m pytest tests/test_interim_coordinator.py tests/test_interim_ui.py tests/test_trace_ui_contracts.py -q -ra
python -m pytest -q -ra
python -m ops.coordinator dry-run
```

Actual live PostgreSQL/model/resource/permission acceptance remains separate.
For headless permission and status semantics also consult Google's
[official headless guide](https://www.antigravity.google/docs/cli/headless/).
