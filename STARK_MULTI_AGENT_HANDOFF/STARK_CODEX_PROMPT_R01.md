# CODEX PROMPT — STARK T2SQL R01 IMPLEMENTATION (AFTER REVIEW APPROVAL)

You are the **implementation agent**. Work only on R01 / issue #3: https://github.com/Vivek-k24/Stark_T2SQL/issues/3

## Preconditions

Do not start if the attached Antigravity R01 design review has not received my approval, if the official Defog SQLCoder-7B-2 model-card prompt bytes are missing/unverified, or if `git status` is dirty. Ask me for the reviewed prompt file/template contract, not an approximation. Read `STARK_T2SQL FRD 1.8.txt` and issue #3. The source baseline is review branch `gemini/full-remediation-review` / PR #2, **not** `main` by default. Existing PR #1 has independent inference client changes. Do not merge it into this branch.

## Branch and scope

```powershell
git fetch origin
git switch --create codex/r01-remediation origin/gemini/full-remediation-review
```

Do not modify `main`, GitHub PR #1, or the Gemini review branch. Edit only `src/inference/prompt_template.txt` (authoritative verbatim file, if approved), `src/stark_t2sql/inference/template.py`, `src/stark_t2sql/inference/prompt_builder.py`, focused tests, and strictly necessary documentation/config contract changes authorized in the review. No PostgreSQL schema/roles, Faker fixture, benchmark holdout, SQL validator, llama.cpp binaries or GitHub credentials changes.

## Goal

Fix ISS-14's absent authoritative template and the code's incompatible exactly-once assumption while preserving original file bytes and SHA-256. Support the actual repeated `[QUESTION]` spans documented by the model card without silently changing text. Bind schema and reviewed as-of date deterministically; reject missing, drifted or mismatched bindings. Preserve one request/one completion behavior, immutable FRD decoding baseline, and fail-closed configuration behavior.

## Verification

Implement at least one regression for each review finding, including repeated question tags, no template mutation, malformed placeholders, wrong hashes, and tested placement of the as-of date. Run focused tests and report pass/fail/skip counts, then run all locally runnable tests. Do not assert an E2 pass without the actual Windows SQLCoder process and binding/measurement source files. Do not invent SHA-256 values, local file paths beyond the known root, tested DB/model evidence, or reference SQL.

## Deliverable

Create a **draft** PR `codex/r01-remediation` -> approved integration base; link issue #3; list modified files, exact patch, test commands/results, hashes of actual artifacts, security limitations, and anything requiring owner approval. Stop and request review. Do not merge, do not start R02, do not force-push other branches.
