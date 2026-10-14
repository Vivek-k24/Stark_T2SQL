# INT-01 implementation work log

Date: 2026-10-14. Assignment: [owner-approved Issue #15](https://github.com/Vivek-k24/Stark_T2SQL/issues/15).
Shared branch: `codex/interim-orchestration-ui`. Target: one draft PR into
`gemini/full-remediation-review`. **No merge or R04 implementation is authorized.**

## 1. Baseline and scope

Codex read `AGENTS.md`, Issue #15, the existing Streamlit entrypoint/UI and
pipeline composition, and the existing multi-agent orchestration instructions.
The remote interim branch already existed at the approved R03 merge
`3855429425020c3619e24fabc64d45d988828009`. A clean linked worktree was attached
to that existing remote branch, without switching the original R03 checkout or
altering its pre-existing `Antigravity_Design_Review.md` edits.

The application originally provided public architecture/planning views but no
working coordinator, durable status cache or activation procedure. Old workflow
instructions conflicted with the one-shared-branch rule and retained R02-only
guidance. The tracked E0 file had FRD 1.7/zero-evidence text despite merged R01–R03.

All changes stay in the INT-01 UI/orchestration/status/setup/test/documentation
scope. Frozen schema, generator, fixture dump/manifest, R01 template, model
client, validator, policy/RLS/compiler/executor, semantic/context/evaluation
source and old agent reviews/logs are unchanged. No runtime database operation
or R04 source implementation occurred.

## 2. Implemented control plane

| Files | Purpose |
| --- | --- |
| `ops/contracts.py`, `ops/handoff.schema.json` | Strict committed-report markers, phase/status rules, exact fields, typed counts, SHA/path validation and gate ownership ceilings. |
| `ops/github.py` | Bounded fixed-repository read API; retrieve actual refs, immutable named reports, issues, PRs, authors and commit ranges. |
| `ops/coordinator.py` | One-shot state machine, kernel-backed project lock, durable SQLite phase claims, STOP/ERROR and explicit recovery interface. |
| `ops/runtime.py` | Owner enrollment, native CLI discovery/probes, fresh isolated phase clones, safe argument vectors/timeouts, environment filtering, measured fixed pytest execution, scope/frozen-byte checks, Git broker and guarded post-merge synchronization. |
| `ops/exercise.py` | Repeatable fake-agent/fake-GitHub integration exercise; no real agent session or repository change. |
| `ops/progress.py`, `ops/refresh.py`, `ops/progress.json` | Canonical public evidence, actual issues/PR merges, immutable report hashes/counts, future gate markers and generated original-HTML evidence region. |
| `ops/setup_check.py`, `ops/enable-coordinator.ps1`, `ops/enrollment.example.json` | Disabled-by-default local enrollment/check-only mode and explicitly opted-in limited Windows scheduled trigger. |
| `ops/serve.py`, `ops/smoke_ui.py` | Safe loopback launcher and actual browser smoke with owned-server cleanup. |
| `ops/probe_codex.py`, `ops/probe_status.py`, `ops/capture_capabilities.py` | Explicit reproducible sanitized capability probes, separate from agent handoff/live SQL acceptance. |
| `ops/README.md` | Setup, real permission prerequisites, marker protocol, AUTO pre-enrollment, task verification, recovery, local UI and test instructions. |
| `tests/test_interim_coordinator.py`, `tests/test_interim_ui.py` | Offline fake-agent/events, actual local Git publisher, timeout/lock checks, status/progress and Streamlit AppTest contracts. |

Dispatch accepts only explicit markers in the expected committed Markdown, not
issue comments or shell snippets. Design REVISE requires explicit readiness;
BLOCKED never dispatches. Unique keys include gate/phase/input SHA. A RUNNING
claim is committed before launch; completed events are not replayed on restart
or doc-only updates. Uncertain failures require operator reconciliation rather
than pretending distributed process execution can be guaranteed exactly once.
Read-only requests retry twice; mutations and agent launches are not blindly
retried. Recovery rechecks existing pushed evidence and actual offline tests.

Each subprocess phase uses a fresh clean clone on the same shared branch.
Agents do not receive inherited GitHub/DB/HR environment secrets or publication
authority in the fixed handoff prompt. The parent checks branch/history/remote,
path scope and frozen bytes before/after execution/tests, clears only its own
clone index, stages exact intended paths, disables Git hooks/fsmonitor, and
normal-pushes. There is no force-push/merge operation. CLI permission controls
remain enabled; missing/denied controls fail closed. A real isolated account
and verified sandbox remain deployment prerequisites, not claims established
by path checking alone.

Single-gate enrollment and optional AUTO pre-enrollment are supported. AUTO
requires owner-scoped paths for each allowed gate. It synchronizes the prior
owner merge first, then reacts only to a **fresh explicit Antigravity design
event** bound to the current integration SHA. It never creates the next design
or branch, infers new scope from Markdown, or dispatches another gate merely
because the previous one merged. The owner's starting action for a pre-enrolled
gate is the Antigravity design prompt; no manual phase/SHA-copy handoff is needed.

Post-merge synchronization is separately opt-in, including an INT01 status-only
mode that does not require agent permissions. It checks the real owner merge,
actor, independent marker and document-only verification range, then changes
only progress JSON/generated HTML on the integration branch under the same
lock. A gate/merge-SHA journal key prevents repeat publication/self-triggering.
Remote advancement or branch protection rejection stops; nothing bypasses it.

An actual REST check found that GitHub's PR-list response omits `merged` and
`merged_by`. The adapter therefore hydrates entries with `merged_at` through
the single-PR endpoint. This actual API shape is covered by a regression test.

## 3. Public progress and UI

`AGENTS.md` and `STARK_MULTI_AGENT_HANDOFF/STARK_MULTI_AGENT_ORCHESTRATION.md`
now agree on shared sequential branches, one review/log per gate, immediate
publication, supervised broker ownership, owner-only merges and STOP gates.
Historic reviews/logs were preserved rather than rewritten.

The same tracked `STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html` retains its demo
navigation and scripted features. Its Architecture & Progress evidence region
is generated from the canonical JSON; version/stale zero-evidence copy was
reconciled to FRD 1.8. Simulation warnings remain. Gate-level evidence does not
mark whole FRD epics complete.

Actual historical merge evidence fetched from GitHub:

| Gate / PR | Actual merge SHA | Versioned full offline result |
| --- | --- | --- |
| R01 / #12 | `51058398182e65a234f5e7da2b27a4ce763436ec` | 260 passed, 177 skipped |
| R02 / #13 | `b8d149d7d58b87a35b251980814467cbca61661d` | 326 passed, 178 skipped |
| R03 / #14 | `3855429425020c3619e24fabc64d45d988828009` | 463 passed, 177 skipped |

The cache stores actual issue state/title, PR/merge metadata, immutable evidence
URLs and SHA-256 values. R01's final independent review was not versioned in
its historical review file; this is disclosed rather than invented. Future
gate statuses use actual PR/report markers, preserving VERIFIED — AWAITING MERGE
until a real merge. Design-file existence alone establishes no implementation.

`app.py` and limited UI modules add a safe default Health & Status view, cached
public evidence in Architecture/Progress and an embedded original offline E0
demo. These return before any pipeline composition. Connected views remain
blocked unless separately opted in; `ops.serve` explicitly removes that opt-in
from its child. Feature labels distinguish LIVE UI, LOCAL READY cached resources,
DEMO/SIMULATED examples and BLOCKED backend/automation. Optional GitHub refresh
is public status only and fails back to cached evidence.

## 4. Actual capabilities and executable checks

Machine checks observed Windows 11 Home, build 10.0.26200, working Task Scheduler
queries and available ScheduledTasks PowerShell commands. The setup script
parsed successfully and its **check-only** path actually ran without an
execution-policy bypass. No task/service was registered.

The PATH launcher reported Codex 0.101.0 and could not load the current `ultra`
configuration. A separately discovered native executable reported
`0.162.0-alpha.17.2`, supported the expected headless flags and passed login
status. A benign fixed-public-token read-only `codex exec` probe actually
completed with zero tools. It did not read project/HR inputs, run implementation
or grant workspace-write permission. No global CLI configuration was changed.

`agy` was unavailable through the supported discovery paths. Its authentication,
headless execution and sandbox behavior were therefore **not tested**. No
Antigravity CLI was installed or existing IDE conversation controlled.

The status-only setup/poller was exercised against actual public GitHub state
using a temporary private enrollment outside the checkout. It returned
STOP_AWAITING_OWNER_MERGE, verified the integration ref unchanged, and performed
zero GitHub mutations/agent sessions. This tested the executable preflight,
**not an installed scheduled trigger or actual baseline post-merge push**.

Streamlit 1.66.0 and Playwright 1.64.0 were installed in the isolated test
environment; no global Python/package manifest/model/database installation was
performed. Pip reported an inherited optional OpenTelemetry/protobuf dependency
conflict in that environment. Actual UI/tests passed; the setup guide recommends
a clean virtual environment rather than inheriting unrelated global packages.

The browser smoke launched a real numeric-loopback Streamlit server and headless
Microsoft Edge. The health endpoint and Health & Status, Architecture and
Progress pages passed. An initial input-radio selector timed out because
Streamlit's visible label intercepted input clicks; selecting the actual label
resolved it. The successful smoke stopped its own server. Its JSON and three
public screenshots are versioned under `ops/evidence/`.

After verification, a separate hidden local UI was launched for the owner at
`http://127.0.0.1:8501`. Its real health endpoint returned `ok`, and the listener
was checked on numeric loopback. Connected SQL remains disabled. Private process
metadata/logs are outside the checkout; no host paths or secrets are committed.
`ops/evidence/local-ui.json` records the running observation, not a promise that
the machine/server will remain on indefinitely.

Sanitized evidence files: `capabilities.json`, `codex-probe.json`,
`status-preflight.json`, `dry-run.json`, `ui-smoke.json`, `local-ui.json` and
`ui-health.png`, `ui-architecture.png`, `ui-progress.png`.

## 5. Final test results

Both prescribed runs used `STARK_TEST_ENABLE_DB_INTEGRATION=0` and
`PYTHONPATH=src;.` with the approved local Python test environment:

```powershell
& $python -m pytest tests/test_interim_coordinator.py tests/test_interim_ui.py tests/test_trace_ui_contracts.py -q -ra
& $python -m pytest -q -ra
& $python -m ops.coordinator dry-run
```

| Final actual run | Passed | Failed | Skipped | Exit |
| --- | ---: | ---: | ---: | ---: |
| Focused INT-01 / UI / trace contracts | **58** | **0** | **0** | **0** |
| Full repository regression | **514** | **0** | **177** | **0** |

Coverage includes fake automatic design/implementation/verification, durable
restart/dedupe, out-of-order and doc-only updates, malformed markers, blocked
verdicts, failed attempts and bounded read retries, lock contention, actual owned
process timeout, denied paths/branches, PR duplication/base/draft checks, merge
and issue status, no-next-gate/no-auto-merge behavior, real local bare-Git doc-only
publication and Streamlit AppTest. Tests grew during implementation; earlier
passing subsets/full runs had fewer cases. Final counts above are the actual
last prescribed runs, not inferred totals.

The 177 skips retain external schema/parser/adversarial/reference/wall-clock
inputs and explicitly disabled live database cases. Existing pytest-asyncio
fixture-loop-scope deprecation remains. None of these skips establish live
PostgreSQL, SQLCoder, measured resources or historical fixture fidelity.

## 6. Deployment blockers and exact owner steps

**Real Antigravity → Codex → Antigravity automation: BLOCKED / NOT ACTIVE.**
Install/authenticate a supported native `agy` through the official instructions,
then perform real authenticated workspace-write and permission-denial probes
for both pinned CLIs in the approved isolated environment. Record actual binary
hashes/results in the private enrollment evidence; never fill success fields
for unperformed tests. The read-only Codex probe is insufficient for this.

**Automatic post-merge trigger: NOT ENABLED.** Status-only preflight works without
agent permissions. After reviewing the enrollment, the owner must explicitly
run `ops/enable-coordinator.ps1` with `-Enable`, then inspect the registered task,
an actual tick and the private last-result file before claiming activation.
The exact setup, private configuration, AUTO scope and recovery commands are
in `ops/README.md`. No permission control, branch rule or execution policy may
be bypassed. Actual baseline post-merge publication remains unexecuted here.

The implementation provides a runnable integration path with tested fake-agent
and real local Git components; it does **not** claim real unattended handoffs
are working. The local UI works in degraded/offline mode. No destructive database
operation, live HR/model query, SQL simulation relabeling, automatic merge or
R04 implementation was performed.

## 7. Publication and stopping point

The implementation/tests/setup/evidence and this single log are being published
to the existing shared interim branch. Actual commit and draft PR links are
recorded in the final handoff update after creation. Independent verification
belongs in **`Antigravity_INT01_Review.md` on this same branch/PR**.

**Stop for Antigravity verification. Do not merge or begin R04.**
