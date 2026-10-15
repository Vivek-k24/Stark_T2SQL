# Shared remediation workflow — FRD 1.8

`AGENTS.md` is the durable authority. Historic prompts are not new permissions.
Integration target: `gemini/full-remediation-review`. Never push to `main`,
merge draft PR #1/#2, force-push or automatically design/start a following gate.

The owner starts a future gate by asking Antigravity for a pushed design review
on the single existing shared `codex/r0x-remediation` branch. Once the narrow
local enrollment is explicitly enabled, the Windows coordinator detects that
review's machine-ready event, corroborates GitHub SHA/scope and launches Codex
in an isolated clean clone. The parent broker checks allowed files and actual
offline tests, publishes one draft PR, then launches Antigravity in a new clone.
Antigravity appends independent findings to the same review and updates the
original E0 HTML and canonical progress evidence. The coordinator STOPS.

The owner alone approves/merges. A separately opted-in post-merge pass checks
the real merge SHA, reviewer marker and enrolled actors before changing only
progress JSON/generated HTML on the integration branch. It shares the exclusive
project lock with dispatch. Remote advancement causes STOP, never overwrite.
It does not enroll or start the next gate. Scope/CLI enrollment is chosen once
for the selected gate; further gates require fresh explicit scope authorization
and their own Antigravity design event. This is a deliberate safety boundary,
not an inference of permission from the preceding merge.

| Milestone | Issue | Focus |
| --- | --- | --- |
| R01 | #3 | Immutable SQLCoder template |
| R02 | #4 | Deterministic fixture/provenance |
| R03 | #5 | ACL/RLS and isolated clone bootstrap |
| INT-01 | #15 | Coordinator, public progress, safe local UI |
| R04 | #6 | Semantic context, after INT-01 merge |
| R05 | #7 | Reviewed parser/safety attribution |
| R06 | #8 | Scoped references/comparator |
| R07 | #9 | Evaluation integrity/holdout boundary |
| R08 | #10 | Inference/UI integration |
| R09 | #11 | Actual isolated database/model acceptance |

Setup, schemas, test commands and recovery: [ops/README.md](../ops/README.md).
Automation remains BLOCKED until actual native CLI authentication, sandbox and
permission probes and the opt-in Windows trigger are verified. Markdown cannot
command existing VS Code conversations. Older source-only restrictions do not
override a current explicit authorization to implement and test a milestone.

AUTO enrollment may pre-authorize several fixed gate scopes once. Each new gate
still requires the owner-triggered Antigravity design-ready push against the
current integration SHA, after the prior owner merge and status sync. The
coordinator never generates that next design or infers it from a merge.
