# STARK T2SQL — human-directed remediation handoffs (FRD 1.8)

Automation has been retired. The owner manually sends each prompt to each agent.
The human owner alone authorizes every merge and the start of the next gate.

The sequence for R04–R09 is:

1. **Antigravity design:** independently review the FRD, gate issue and current
   code; use the gate's one shared `codex/r0x-remediation` branch. Push
   `Antigravity_R0x_Review.md` and wait for owner instruction.
2. **Codex implementation:** read that review, implement approved scoped changes,
   test, push source/tests/`Codex_R0x_Work_Log.md`, open one draft PR against
   `gemini/full-remediation-review`, and stop.
3. **Antigravity verification:** independently rerun checks, append implementation
   verification to the same review, and update `ops/progress.json` plus
   `STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html` based on actual evidence.
   Push these changes to the existing PR. Also synchronize the separately
   stored local browser file
   `H:\STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html.html` to the final reviewed
   canonical HTML (the tracked file has only one `.html` extension). Protect
   independent local edits before copying, compare or hash the resulting files,
   and report whether the H: file was actually updated. If the H: drive is
   inaccessible, say so; GitHub publication does not update a `file://` URL.
   Stop after reporting. Before merge the status is
   `VERIFIED — AWAITING MERGE`.
4. **Owner:** review and merge or request corrections. At the next manual review
   refresh the previous gate's status to `MERGED` only with its actual GitHub
   merge SHA. Never automatically push to `main`.

| Gate | Issue | Focus |
| --- | --- | --- |
| R01 | #3 | SQLCoder prompt template (merged) |
| R02 | #4 | Synthetic fixtures and provenance (merged) |
| R03 | #5 | PostgreSQL permissions and clone isolation (merged) |
| R04 | #6 | Semantic catalog and as-of-date governance |
| R05 | #7 | SQL validator and safety boundaries |
| R06 | #8 | Evaluation references and comparator |
| R07 | #9 | Canary and evaluation integrity |
| R08 | #10 | Inference/UI reconciliation |
| R09 | #11 | Local PostgreSQL + SQLCoder end-to-end acceptance |

See the current root `AGENTS.md` for branch/log/safety constraints.
Past INT-01 automation records are historical only. Offline UI operation and
human-updated progress instructions are in `ops/README.md`.
