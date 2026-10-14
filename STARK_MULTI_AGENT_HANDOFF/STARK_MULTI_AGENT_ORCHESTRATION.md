# STARK T2SQL — Multi-Agent Audit Remediation Playbook

Prepared: 2026-10-14. Governing spec: `STARK_T2SQL FRD 1.8.txt`. User-approved intent: orchestrate *sequentially*; do not merge unverified code or modify the running local model.

## 0. Canonical source / review state

- Repository: https://github.com/Vivek-k24/Stark_T2SQL
- `main` is original baseline commit `8df53bf279498813bfa3e0e284e5d567e9d36dac`; it has **not** received Gemini's or ChatGPT's fixes.
- **Gemini ZIP snapshot:** `gemini/full-remediation-review`, commit `8f62fb3d77d8e92fba0060944f34b1acf43fc458`, draft PR https://github.com/Vivek-k24/Stark_T2SQL/pull/2. Exact 21 changed ZIP files imported; Git object hash of each file matches source ZIP. ZIP SHA-256 `81bb8c7441cf2854c4415a6bdd7ef804b1a0f142523d87912c299ea3c17103a0`.
- **ChatGPT Phase 4 source:** `assistant/sqlcoder-runtime-integration`, draft PR https://github.com/Vivek-k24/Stark_T2SQL/pull/1. Eight commits; inference-client changes overlap Gemini's draft. Do not merge these two unreviewed versions of `inference/client.py` sequentially.
- Independent ZIP-only test run: `205 passed, 178 skipped, 0 failed` with Python `pytest`, `PYTHONPATH=src:.`. 178 skipped do **not** imply PostgreSQL/SQLCoder/end-to-end readiness.
- ZIP does not include required `src/inference/prompt_template.txt`, `fixture_pg_dump.sql`, `fixture_manifest.json`. Never invent these authoritative artifacts or hashes.

## 1. Control plane and operating rules

**Reviewer = Antigravity; implementer = Codex; coordinator = ChatGPT; merge approver = user.** Reviewer and implementer may share the repository but not an active branch or writable working tree. Only one remediation gate is *active* at a time; next gate starts after explicit approval. Agents can read in parallel. No agent may merge, force-push, overwrite another branch, or change GitHub main.

Each stage has five transitions:

1. **Scope lock:** Open assigned issue; record baseline SHA, dependency completion, exact permitted paths, and conflict owners.
2. **Review:** Antigravity produces design/test/permissions review; checks ZIP source and FRD; flags incorrect audit recommendations; makes no changes to implementer's branch.
3. **Implementation:** Codex creates `codex/rXX-remediation` from *the approved integration baseline*, implements minimal changes, adds negative and positive tests, posts draft PR. Never branch from stale `main` blindly when fixes depend on PR #2.
4. **Verification:** Reviewer audits changes + output; local-only / PostgreSQL / llama.cpp tests that cannot run in the agent environment stay explicitly *unverified*.
5. **Promotion:** User approves/rejects merging and chooses next gate. Update issue with commit SHA, files changed, tests and known gaps.

Never allow Codex and Antigravity to amend the same branch in parallel. Do not treat synthetic fixture or fake oracle output as measured experimental evidence. All holdout payloads/keys require owner authorization and must not be embedded in repo or prompts. Never submit unreviewed model SQL to a database or disable PostgreSQL RLS on a production role.

## 2. Sequential GitHub issue queue

| Gate | GitHub issue | Audit focus | Main deliverable |
|---|---|---|---|
| R01 | [#3](https://github.com/Vivek-k24/Stark_T2SQL/issues/3) | ISS-14 | Authentic SQLCoder model-card template, immutable hash, correct repeated-question handling, runtime binding docs. |
| R02 | [#4](https://github.com/Vivek-k24/Stark_T2SQL/issues/4) | ISS-16 / ISS-14 assets | Deterministic Faker `--reset` fixture, owner-reviewed schema, immutable dump and manifest evidence. |
| R03 | [#5](https://github.com/Vivek-k24/Stark_T2SQL/issues/5) | ISS-01 / 02 / 04 | Real PostgreSQL ACL/RLS start-up, isolated clone baseline, negative authorization proof. |
| R04 | [#6](https://github.com/Vivek-k24/Stark_T2SQL/issues/6) | ISS-05 / 09 / 18 | Correct semantic vocabulary, metrics, temporal context and role filtering. |
| R05 | [#7](https://github.com/Vivek-k24/Stark_T2SQL/issues/7) | ISS-06 / 13 | Reviewed parser allowlist and true `NO_VALIDATOR` attribution, while preserving safety gates. |
| R06 | [#8](https://github.com/Vivek-k24/Stark_T2SQL/issues/8) | ISS-07 / 08 / 10 | Correctly persona-scoped evaluation references, defensible comparator and table-based row scope. |
| R07 | [#9](https://github.com/Vivek-k24/Stark_T2SQL/issues/9) | ISS-11 / 15 / 19 / 20 | Canary integrity, accurate run classification/counts, unchanged sealed holdout. |
| R08 | [#10](https://github.com/Vivek-k24/Stark_T2SQL/issues/10) | ISS-12 / 17 / 21 / 22 | Reconcile Gemini vs ChatGPT inference code and UI fixes, with regression tests. |
| R09 | [#11](https://github.com/Vivek-k24/Stark_T2SQL/issues/11) | FRD E2/E6 acceptance | Actual local PostgreSQL + SQLCoder end-to-end run evidence; explicit human promotion gate. |

**Caution on report/ZIP drift:** ISS-08 cannot be called simply “unfixed”: the ZIP added reviewed `principal_marker` and `scope_review_reference` bindings but still runs the controlled reference SQL through a privileged admin connection, so role-equivalence proof remains to be tested. ISS-20 uses `AccuracyHistogram` rather than the report's old direct `unscored_count` formula; inspect current source before applying the historical patch. ISS-17 UI source is unchanged in the ZIP; PR #1 has a separate draft fix. ISS-18 payroll monetary metric coverage and ISS-16 Faker CLI remain visibly incomplete.

## 3. Required handoff schema

Post this as an issue comment at the end of every stage:

```text
STARK AUDIT HANDOFF — Rxx
Base commit:
Implementation commit / draft PR:
Changed paths:
Audit IDs verified:
FRD requirement(s):
Design approval link/summary (Antigravity):
Unit tests / status:
PostgreSQL tests / status:
llama.cpp tests / status:
Security-negative tests / status:
Fixture/provenance hashes (only actual measured values):
Known residual risks:
Next stage permitted? YES/NO — reviewer rationale:
User merge authorization? YES/NO:
```

Acceptance must not be inferred from a green subset with skipped integration tests. Log test counts (passed, failed, skipped) and reasons; supply commands without secrets. Require at least one explicitly negative test for every access control or SQL validator change.

## 4. Local Git inspection without disturbing H:\STARK T2SQL

Recommended read-only preview in a **separate worktree** (PowerShell):

```powershell
Set-Location 'H:\STARK T2SQL'
git status --short
git fetch origin
git worktree add --detach 'H:\STARK_GEMINI_REVIEW' 'origin/gemini/full-remediation-review'
Set-Location 'H:\STARK_GEMINI_REVIEW'
git log -1 --oneline
git diff --stat 'origin/main...HEAD'
```

This does not modify your existing worktree. To also inspect PR #1, create a different worktree path from `origin/assistant/sqlcoder-runtime-integration`. Do **not** use `git pull origin main` expecting these draft branches to appear on `main`; neither draft PR is merged.

When a user-approved integration PR is eventually merged into `main`, update the normal working repository using:

```powershell
Set-Location 'H:\STARK T2SQL'
git status --short        # must be clean, or back up/commit your work first
git switch main
git pull --ff-only origin main
```

## 5. Original ZIP vs GitHub evidence

The import preserved precisely the ZIP's 21 altered source files; all 21 Git blob SHA-1 checks matched the ZIP. ZIP contains 103 source files; no new production runtime template/dump/manifest was inserted during import. The GitHub PR therefore represents a reviewable patch, **not a fully deployable distribution**. A separate local ZIP/source manifest is available for provenance.

## 6. Starter workflow

1. Send `STARK_ANTIGRAVITY_PROMPT_R01.md` to Antigravity, with [issue #3](https://github.com/Vivek-k24/Stark_T2SQL/issues/3) and PR #2.
2. Inspect its design/findings. If approved, send `STARK_CODEX_PROMPT_R01.md` to Codex; it must produce a draft PR from an explicit reviewed base.
3. Have Antigravity review the Codex PR and attach test evidence.
4. You approve or reject the merge; then proceed to R02 / issue #4 using the reusable prompt templates in `STARK_AGENT_PROMPTS_FOR_R02_R09.md`.
