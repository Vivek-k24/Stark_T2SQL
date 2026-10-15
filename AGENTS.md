# STARK T2SQL — manual agent workflow

Owner directs each agent phase. There is **no automatic dispatcher, scheduled task,
CLI enrollment, background GitHub synchronization or automatic next-gate start**.
Use FRD 1.8 and the current gate issue as the source of truth. These rules supersede
old handoff prompts where they conflict.

1. **One shared branch per gate**: `codex/r0x-remediation`, created once from the
   latest `gemini/full-remediation-review` baseline. Antigravity and Codex take turns
   on it; do not create separate reviewer/documentation branches. Preserve unrelated
   local edits; use clean worktrees if necessary.
2. **Manual sequence**: Owner prompts Antigravity for design review; it commits and
   pushes `Antigravity_R0x_Review.md`. Owner then prompts Codex to implement on
   that same branch; it commits and pushes code/tests/`Codex_R0x_Work_Log.md` and
   opens one draft PR against `gemini/full-remediation-review`. Owner then prompts
   Antigravity to independently verify; it appends findings to the same review,
   updates the original E0 HTML progress display and pushes to the same PR.
   Report the actual commit SHA, tests and PR URL after every push.
3. **Stop at each owner handoff**. Neither agent initiates the next phase, merges,
   force-pushes, pushes `main`, starts the next gate, or executes unapproved
   database resets. The owner explicitly approves promotion/merges.
4. **Progress is manual, not live**. Antigravity updates `ops/progress.json` from
   *actually verified* GitHub evidence and runs `python -m ops.progress` to
   regenerate only the corresponding section of
   `STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html`. Before merge use
   `VERIFIED — AWAITING MERGE`; in the next manually requested update, use
   `MERGED` only after verifying an actual owner-approved merge SHA.
   Include `ops/progress.json` and the HTML in the same gate PR.
   No agent should recreate a scheduler, automatic dispatch or post-merge bot.
5. **Scope and safety**: Follow the gate issue's file ownership. Do not modify
   frozen R01/R02 artifacts, historical review logs, secrets or holdouts without
   explicit authorization. Distinguish mocked/offline test results from actual
   PostgreSQL, SQLCoder and full end-to-end evidence. Never mislabel scripted
   example SQL as LIVE.
6. **Historical records**: Keep INT-01 implementation/review Markdown as an audit
   record only. Its former automation design was retired at the owner's direction,
   and is no longer operational guidance. No historical evidence is rewritten.

R01–R03 are merged into the integration branch. R04 (Issue #6) is the next gate
after this cleanup is approved and merged. Existing draft PR #1 and `main`
remain untouched until their assigned gates.
