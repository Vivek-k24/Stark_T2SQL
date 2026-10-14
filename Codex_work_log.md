# Codex work log — STARK T2SQL R01 (ISS-14)

This log records the R01 implementation chronologically, including the initial
code fixes, official template restoration, documentation and approved-contract
follow-up. Dates below are from Git history; commit times use America/Chicago
(`UTC-05:00` on 2026-10-14). Test results are attributed to their respective
implementation stages. The current acceptance results appear in section 8.

| Reference | Location |
| --- | --- |
| Repository | [Vivek-k24/Stark_T2SQL](https://github.com/Vivek-k24/Stark_T2SQL) |
| Assigned issue | [Issue #3 — R01: Authoritative SQLCoder template and runtime bootstrap](https://github.com/Vivek-k24/Stark_T2SQL/issues/3) |
| Implementation review | [Draft PR #12](https://github.com/Vivek-k24/Stark_T2SQL/pull/12) |
| Completed design review | [Antigravity_Design_Review.md](Antigravity_Design_Review.md) |
| Requirements | [STARK_T2SQL FRD 1.8.txt](<STARK_T2SQL FRD 1.8.txt>) |
| Implementation handoff | [STARK_CODEX_PROMPT_R01.md](STARK_MULTI_AGENT_HANDOFF/STARK_CODEX_PROMPT_R01.md) |
| Remediation workflow | [STARK_MULTI_AGENT_ORCHESTRATION.md](STARK_MULTI_AGENT_HANDOFF/STARK_MULTI_AGENT_ORCHESTRATION.md) |

## 1. Starting state and objective

R01 addresses ISS-14: restore the authoritative SQLCoder-7B-2 prompt template
and correct the loader/builder assumptions that were incompatible with its
repeated question placeholders. FR-4.3 requires the verbatim model-card template
and its SHA-256; FR-4.4 places the as-of line immediately after the question,
inside its closing QUESTION tag. Prompt versions 1 and 2 must retain their
separate context rules.

The required local branch, `codex/r01-remediation`, already existed. Before
implementation, Codex ran the repository-root, current-branch, working-tree and
latest-commit inspections requested in the execution assignment. The repository
was `H:\STARK T2SQL`, the branch was correct, and the working tree was clean at
`87b9f501badd72d87c2268c0b84fcf4b1f44cad9`.

The branch inherited the Gemini snapshot at
`8f62fb3d77d8e92fba0060944f34b1acf43fc458` and the subsequent review/handoff
documentation. Those inherited files explain why the PR comparison against
`gemini/full-remediation-review` includes documentation predating Codex's R01
implementation. They were not rewritten to change the review history. No new
branch was created and no branch switch, merge or rebase was performed.

## 2. Review findings and official-source investigation

Codex read the FRD, completed Antigravity review, R01 handoff, orchestration
document, relevant inference source/tests and pytest configuration, and reviewed
Issue #3. Antigravity's verdict was **REVISE**. Its findings were implementation
requirements, not evidence of architecture or owner approval.

The initial problems were:

1. `src/inference/prompt_template.txt` was absent.
2. `template.py` required every reviewed marker exactly once and inspected only
   the first tag pair. The official prompt has two question placeholders and
   two QUESTION tag pairs.
3. `_replace_original_slots()` in `prompt_builder.py` found only the first
   occurrence of each placeholder. The second question placeholder in the
   Answer section would remain unsubstituted.
4. Pytest lacked a configured `src` import path. The actual-template placement
   test could also disappear behind missing external fixtures and skips.
5. No owner-approved canonical as-of-line prefix/contract was available. The
   FRD specified its placement but did not supply its exact wording.

The official Defog model card was inspected. Its repository revision was
resolved through the Hugging Face model API, and the README at that immutable
revision was retrieved. The Prompt fenced block confirmed two `[QUESTION]`
openings, two `[/QUESTION]` closings, two `{user_question}` placeholders and one
`{table_metadata_string_DDL_statements}` placeholder. Actual source fingerprints
were computed and recorded; no template text or approval hash was invented.

## 3. First implementation: loader, builder and focused regressions

The first implementation corrected independently verifiable code and test
behavior while leaving the approval-dependent artifact/contract unresolved.

### Files changed in the first implementation

| File | Change and reason |
| --- | --- |
| `src/stark_t2sql/inference/template.py` | Replaced the exactly-once assumption with validation of two complete QUESTION regions and one external schema slot. Retained immutable source bytes, binary loading and digest checks. |
| `src/stark_t2sql/inference/prompt_builder.py` | Collected all original substitution spans so both question occurrences receive the same supplied question/as-of text. |
| `tests/test_inference_contracts.py` | Strengthened actual-template assertions for both regions and made missing owner evidence an explicit acceptance failure instead of an unrelated fixture skip. |
| `tests/test_prompt_template_exact.py` | Added positive/negative regressions, pinned source/hash metadata, explicit acceptance requirements and isolated import-activity guards. |
| `.gitattributes` | Added `src/inference/prompt_template.txt text eol=lf` to protect exact template bytes on Windows. |
| `pyproject.toml` | Added one pytest configuration table with `pythonpath = ["src"]` and the `r01_acceptance` marker, without duplicate settings. |

### Code behavior implemented

- The contract permits the reviewed SQLCoder placeholder/tag names. The source
  must contain two question slots, two corresponding tag pairs, one schema slot
  and one SQL marker.
- Marker validation consumes the original spans in order. It rejects missing,
  reversed, nested, overlapping or mismatched QUESTION regions; duplicate or
  absent slots; schema placement inside either question region; and unreviewed
  marker text. Only whitespace may surround a question slot inside its tags.
- The loader continues to read raw bytes without trimming or newline/BOM
  normalization. Invalid UTF-8, a BOM, CRLF source, incorrect digests and missing
  required inputs fail closed.
- Slot replacement scans the original template, sorts the spans, rejects
  overlap and assembles the result once. Inserted braces or marker-like question
  text are never reparsed as additional placeholders.
- Both question slots use the same question plus the contract-supplied as-of
  line. No canonical prefix was added as a default.
- Version 1 remains restricted to the frozen full-DDL, no-semantics E2 harness
  profile. Version 2 retains the existing governed context/harness profiles and
  schema-plus-semantics assembly. Invalid version/mode combinations fail closed.

The first recorded focused run produced **69 passed, 2 blocked, 0 skipped**.
The first full-suite run produced **257 passed, 2 blocked, 177 skipped**. Pytest
reported the blocked acceptance cases as failures. At this point their missing
inputs included the local template artifact and the owner contract/prefix.

The six-file implementation was committed and pushed as
[`a2066f94379e36dcb4e289d9a0d9cfe3e88c38db`](https://github.com/Vivek-k24/Stark_T2SQL/commit/a2066f94379e36dcb4e289d9a0d9cfe3e88c38db)
on **2026-10-14 at 02:21:38 -05:00**, with purpose:
`Fix R01 repeated prompt slots and expose acceptance blockers`.

Draft PR #12 was opened from `codex/r01-remediation` to
`gemini/full-remediation-review`, referencing Issue #3 and explicitly recording
that R01 acceptance was incomplete.

## 4. Follow-up: restore official bytes without inventing prefix approval

The owner subsequently instructed Codex to continue all independently verifiable
R01 work without waiting for prefix approval, preserve the recorded official
reference/hash, and keep owner-dependent tests explicitly BLOCKED.

Codex retrieved the pinned README again, compared it with the recorded README
hash, extracted the exact Prompt fenced-block contents, and compared the
extraction with the already recorded template hash and 306-byte size before
writing the file. No stripping, newline conversion or replacement prefix was
applied.

This follow-up changed only:

| File | Change and reason |
| --- | --- |
| `src/inference/prompt_template.txt` | Created the exact official template. Its contents retain the upstream placeholders; no as-of prefix is embedded. |
| `tests/test_prompt_template_exact.py` | Added `test_pinned_official_file_matches_frozen_upstream_bytes`, which establishes actual-file byte identity independently of the prefix decision. Updated the acceptance diagnostic to identify the remaining owner contract/prefix input. |
| `tests/test_inference_contracts.py` | Renamed/described the missing-contract test to reflect that the template file now exists while the real owner contract remains unavailable. |

The verified official source reference and hash constants were preserved.
Synthetic unit prefixes remain confined to clearly labelled synthetic unit
templates. They do not substitute for an approved contract on the actual file.
No `tests/fixtures/template_contract.json` approval record was fabricated.

The follow-up was committed and pushed as
[`47d0bc7d2a67261af3d429d9826d7e9b4eb2355e`](https://github.com/Vivek-k24/Stark_T2SQL/commit/47d0bc7d2a67261af3d429d9826d7e9b4eb2355e)
on **2026-10-14 at 10:34:22 -05:00**, with purpose:
`Add pinned official SQLCoder template without inventing prefix approval`.

The existing draft PR #12 was updated with the final implementation, provenance,
test results and single remaining approval decision. A GitHub CLI update
encountered a TLS handshake timeout; the subsequent REST API update succeeded.
No replacement PR, branch change or merge was needed.

### Official template provenance

| Item | Recorded value |
| --- | --- |
| Model repository | `defog/sqlcoder-7b-2` |
| Source revision | `7e5b6f7981c0aa7d143f6bec6fa26625bdfcbe66` |
| Pinned README | [Official raw model card](https://huggingface.co/defog/sqlcoder-7b-2/raw/7e5b6f7981c0aa7d143f6bec6fa26625bdfcbe66/README.md) |
| README SHA-256 | `cb2bcf750243bd1bf77c1e70b3b989bb69da3a5cf37702278c80467b94ecb524` |
| Local template | [src/inference/prompt_template.txt](src/inference/prompt_template.txt) |
| Template SHA-256 | `67d1c6d265202e6bf6abcd1393203e84b92bf9df03207015679339fe807ad6b6` |
| Exact byte representation | 306 bytes; UTF-8 without BOM; LF endings; includes the final LF immediately before the Markdown closing fence, excluding the fence itself |
| Marker multiplicities | Two `[QUESTION]`, two `[/QUESTION]`, two `{user_question}`, one `{table_metadata_string_DDL_statements}` |

These fingerprints identify the actual upstream source and local template.
They are not an owner approval or evidence of a live SQLCoder/model run.

## 5. Recorded tests before final prefix approval

The following commands were executed after the official template addition.
The pyproject import-path configuration was used; no extra PYTHONPATH setting
was necessary.

Focused R01 command:

```powershell
python -m pytest tests/test_inference_contracts.py tests/test_prompt_template_exact.py -q
```

Full Python-suite command, with live database integration explicitly disabled:

```powershell
$env:STARK_TEST_ENABLE_DB_INTEGRATION = '0'
python -m pytest -q -ra
```

| Run | Passed | BLOCKED owner acceptance | Other failed | Skipped |
| --- | ---: | ---: | ---: | ---: |
| Focused R01 | **70** | **2** | 0 | 0 |
| Full Python suite | **258** | **2** | 0 | **177** |

**Pytest reports the two BLOCKED acceptance tests as failures, so both commands
returned exit code 1.** BLOCKED is the documented cause, not a custom passing
pytest outcome. The same two cases appear in both runs; these are not four
different blocked tests:

- `tests/test_inference_contracts.py::test_actual_template_as_of_placement_keeps_original_bytes`
- `tests/test_prompt_template_exact.py::test_load_authoritative_sqlcoder_template`

Both report:

```text
BLOCKED R01 acceptance: missing owner-approved canonical as-of prefix and its contract record. Unit regressions are not acceptance evidence.
```

Neither acceptance test was silently skipped, marked xfail or supplied a
temporary approval contract. The passing independent regressions cover actual
template byte/hash identity, repeated substitutions, schema placement, source
immutability, malformed markers, incorrect hashes, literal braces/marker-like
inputs, v1/v2 isolation and import-activity guards. Existing focused extraction
and decoding contracts also ran.

The full suite's 177 skips concern missing external
schema/catalog/parser/wall-clock/reference/adversarial inputs and six explicitly
disabled database integration cases. These skips are not integration or
security acceptance evidence. An existing pytest-asyncio configuration
deprecation warning was emitted; unrelated plugin settings were not changed.

During implementation, staged whitespace checks reported no errors, and Git's
attribute inspection reported `lf` for the template. No live model/llama.cpp or
PostgreSQL integration was performed. No model weights were downloaded, no
services were launched, and no fixture or holdout data was materialized.

## 6. R01 status before final prefix approval

**At this stage, independently verifiable R01 implementation was complete and
R01 acceptance remained BLOCKED pending the owner decision below. The draft PR
was open for human review.**

The single remaining R01 approval decision was the **exact canonical
as-of-line prefix, including trailing whitespace, and its approval reference**.
That real decision needed to be recorded in the template contract using the already
established source revision/hash. The acceptance helper supports an actual
contract at `tests/fixtures/template_contract.json`, or a workspace-local path
provided through `STARK_TEST_TEMPLATE_CONTRACT_PATH`. At this stage, neither a
prefix nor an approval record had been chosen on the owner's behalf.

The next action was to supply the real contract and rerun the two acceptance
cases for actual approved-prefix evidence. That action had not yet occurred.
Template file presence and passing unit regressions do not establish service
readiness, live database behavior or successful R01 promotion.

Only `codex/r01-remediation` was pushed. `main`,
`gemini/full-remediation-review` and `assistant/sqlcoder-runtime-integration`
were not modified by this R01 work. The inference client, SQL validation and
execution, schema/policies, semantic catalog, generator, UI, scoring code, FRD
and committed handoff documents were outside the implementation changes.
Nothing was merged, Issue #3 was not closed, and R02 was not started.

Review continues in [draft PR #12](https://github.com/Vivek-k24/Stark_T2SQL/pull/12),
with head `codex/r01-remediation` and base
`gemini/full-remediation-review`.

## 7. Documentation-only follow-up

The owner requested this root-level `Codex_work_log.md` alongside
`Antigravity_Design_Review.md`. For that follow-up, Codex read Git history,
Issue #3, draft PR #12 and relevant existing source/review material, then
created only this file. No implementation/configuration/test files were
modified, and no tests were rerun for this documentation-only addition.

The separate documentation commit was
[`88142e534f7e0c07810f93bbc1714bba40a3d1bf`](https://github.com/Vivek-k24/Stark_T2SQL/commit/88142e534f7e0c07810f93bbc1714bba40a3d1bf),
with purpose `Document chronological R01 implementation work log`. Its sole
changed path was `Codex_work_log.md`.

## 8. Final review action: approved prefix and acceptance fixture

The owner then asked Codex to review the latest `Antigravity_Design_Review.md`
and take the necessary action. Its final appended section, **Independent
Architecture & Security Review: Gate R01 (ISS-14) — Final Prefix Evaluation &
PR #12 Approval**, gives verdict **APPROVE** and explicitly approves the exact
canonical prefix `"As-of date: "`.

This latest decision supersedes the earlier intermediate `"as_of_date: "`
suggestion in the same document. The selected value has a capital `A`, a hyphen,
lowercase `of date`, a colon and exactly one trailing ASCII space (`U+0020`).
Codex used this supplied approval; it did not invent a prefix or alter the
official model-card bytes.

The requested minimal implementation was to add
[`tests/fixtures/template_contract.json`](tests/fixtures/template_contract.json).
The fixture contains the seven fields specified in the final review, including
the approved prefix, existing template SHA-256, exact placeholder/tag names and
the pinned Defog revision in `source_reference`. The existing acceptance helper
already supports this default path, so no application or test code changes were
needed. This work log was updated to retain the earlier blocked results as
history and record the new outcome.

### Approval source and existing local changes

The review file already contained uncommitted changes when this follow-up
began. Codex preserved them without editing or staging the review document.
The approval source is the final appended review section named above, supplied
locally and explicitly invoked by the owner's request. This revision commits
the contract fixture and work-log update; it does not silently include another
author's review-file changes.

### Verification performed by Codex

Codex ran both suites again after adding the reviewed fixture. The process-local
`STARK_TEST_TEMPLATE_CONTRACT_PATH` override was unset so the tests exercised
the committed default fixture. Full-suite database integration remained
explicitly disabled.

Focused command:

```powershell
[Environment]::SetEnvironmentVariable('STARK_TEST_TEMPLATE_CONTRACT_PATH', $null, 'Process')
python -m pytest tests/test_inference_contracts.py tests/test_prompt_template_exact.py -q
```

Full-suite command:

```powershell
[Environment]::SetEnvironmentVariable('STARK_TEST_TEMPLATE_CONTRACT_PATH', $null, 'Process')
$env:STARK_TEST_ENABLE_DB_INTEGRATION = '0'
python -m pytest -q -ra
```

| Run | Passed | Failed | BLOCKED | Skipped | Exit code |
| --- | ---: | ---: | ---: | ---: | ---: |
| Focused R01 | **72** | **0** | **0** | **0** | **0** |
| Full Python suite | **260** | **0** | **0** | **177** | **0** |

Both previously blocked acceptance tests now pass with the approved prefix.
The template's 306-byte size and recorded SHA-256 remain unchanged. The 177
skips retain the external-input and disabled-database reasons described above;
they do not establish live model, database or later-gate readiness. The existing
pytest-asyncio deprecation warning also remains.

These are Codex's actual new runs, not merely the reviewer's reported counts.
No live model or PostgreSQL integration was performed, no service was launched,
and no R02 work was started.

### Current R01 status

**R01 implementation and focused acceptance are complete; the prefix blocker
is cleared. [PR #12](https://github.com/Vivek-k24/Stark_T2SQL/pull/12) is ready for
coordinator/human merge review.** The PR remains a draft against
`gemini/full-remediation-review`; no merge, issue closure or R02 authorization
is implied. Only `codex/r01-remediation` is used for this follow-up.
