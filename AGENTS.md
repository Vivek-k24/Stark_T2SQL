# STARK T2SQL — Standing Instructions for Codex and Antigravity

These repository-root rules apply to **every remediation gate (R01–R09)** and both agents. They supersede older handoff prompts/playbooks on branch creation, reporting and documentation delivery where those instructions conflict. Read the gate's FRD, GitHub issue and current review before acting.

## One shared working branch per gate

- **Exactly one working branch for a gate, shared sequentially by both agents.** For R02 the existing branch is `codex/r02-remediation`. For later gates, create the gate's working branch **once** from the latest reviewed `gemini/full-remediation-review` baseline, then both agents use it. The historical `codex/` prefix denotes the shared implementation branch, not Codex-exclusive ownership.
- **Do not create Antigravity-specific review/verification branches, extra documentation branches, or documentation-only PRs.** The gate has at most one implementation PR from its shared branch into `gemini/full-remediation-review`.
- Antigravity and Codex work **sequentially**, not concurrently, on the same branch. Fetch and fast-forward to the latest remote branch before beginning each handoff. Check the working tree and branch before editing. Do not discard, stash, overwrite or switch away from unrelated uncommitted work automatically; use a clean worktree attached to the **same existing branch** where appropriate, or stop for owner direction.
- Never push to `main`, force-push, merge PRs, or start the next gate without explicit owner authorization.

## Two root-level agent records per gate — no duplicates

1. **Antigravity: one review Markdown per gate.** It contains the *initial design review* and, after Codex finishes, an appended *independent implementation verification* section with findings, tests actually run, verdict (APPROVE / REVISE / BLOCKED) and outstanding evidence. Do not create a second `Verification_Review.md` file. For R02, **reuse `Antigravity_R02_Design_Review.md`** and append the verification there. The R01 historical file is `Antigravity_Design_Review.md`; retain it. For R03 onward use `Antigravity_R0x_Review.md`.
2. **Codex: one implementation work-log Markdown per gate.** Include objectives, exact source edits, commits, tests and counts, evidence, provenance, blockers, PR URL and final state. R01/R02 already use the root `Codex_work_log.md` with gate sections; **continue its R02 section instead of creating a duplicate R02 file**. For R03 onward use `Codex_R0x_Work_Log.md`.

Both records belong **in the repository root**, are versioned alongside code, and must be present on GitHub. Historical filenames may differ; preserve existing content, add date-stamped sections, and do not delete prior review evidence.

## Automatically publish completed work to GitHub

- **As soon as any phase is finished** (Antigravity design review; Codex implementation; Antigravity verification), stage only the intended in-scope files, commit and **push to the current gate's shared branch immediately**, *before* telling the owner the phase is complete.
- Antigravity commits/pushes its single review Markdown after design review, then commits/pushes an additional verification section to **that same file and branch** after inspecting Codex's PR. Antigravity does not alter implementation source during review.
- Codex commits/pushes implementation, tests and its single work-log file to the **same gate branch** before reporting completion. Update the existing draft PR, do not open a second PR just for documentation.
- After every push, verify that the commit and Markdown file are visible on the remote shared branch; report the GitHub file URL, commit SHA and PR URL. If publishing is blocked by credentials, Git conflicts, or unavailable network permissions, explicitly report **NOT PUSHED** and request the minimum intervention; never claim that local-only files are on GitHub.
- Do not commit secrets, real PII, machine-specific credentials, or fabricated test/provenance evidence. Clearly distinguish offline tests from live PostgreSQL/llama.cpp verification.

## Immediate R02 handoff

- Current shared branch: `codex/r02-remediation` (Draft PR #13 against `gemini/full-remediation-review`).
- The existing local `Antigravity_R02_Design_Review.md` must be added to the **shared R02 branch** if not already there. Preserve any unsaved/unstaged work, using a safe copy into a clean worktree if needed. Do **not** create `antigravity/r02-verification`.
- Antigravity appends its independent PR #13 verification to `Antigravity_R02_Design_Review.md`, then commits/pushes this file directly to `codex/r02-remediation`. It must not merge PR #13 or begin R03.
