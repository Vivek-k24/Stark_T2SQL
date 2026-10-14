# Codex work log — STARK T2SQL R01 and R02

This log records the R01 implementation and the subsequent authorized R02 work
chronologically. Dates below are from Git history; commit times use
America/Chicago (`UTC-05:00` on 2026-10-14). Test results are attributed to their
respective implementation stages. Section 8 records the end of R01
implementation; section 9 records R02 and its remaining verification gate.

| Reference | Location |
| --- | --- |
| Repository | [Vivek-k24/Stark_T2SQL](https://github.com/Vivek-k24/Stark_T2SQL) |
| Assigned issue | [Issue #3 — R01: Authoritative SQLCoder template and runtime bootstrap](https://github.com/Vivek-k24/Stark_T2SQL/issues/3) |
| R01 implementation review | [PR #12](https://github.com/Vivek-k24/Stark_T2SQL/pull/12), subsequently merged into the R02 baseline |
| R02 assigned issue | [Issue #4 — R02: Deterministic Faker fixture and provenance](https://github.com/Vivek-k24/Stark_T2SQL/issues/4) |
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

### R01 status at the end of this implementation stage

**R01 implementation and focused acceptance are complete; the prefix blocker
is cleared. [PR #12](https://github.com/Vivek-k24/Stark_T2SQL/pull/12) is ready for
coordinator/human merge review.** The PR remains a draft against
`gemini/full-remediation-review`; no merge, issue closure or R02 authorization
is implied. Only `codex/r01-remediation` is used for this follow-up.

## 9. R02 implementation: deterministic fixture and isolated reset

### Authorization, references and branch setup — 2026-10-14

The owner explicitly approved R02 implementation based on the supplied
`Antigravity_R02_Design_Review.md`. Its baseline verdict was **REVISE**: retain
the conformant twelve-table `schema.sql`, replace the external-configuration
deadlock in normal fixture generation, implement the CLI/reset/export paths,
and supply deterministic artifacts and tests. The owner added two controlling
requirements: destructive reset must target a verified isolated test database
and never unrelated tables; historical fidelity and live PostgreSQL acceptance
must not be claimed without actual verification.

Codex read that review, [Issue #4](https://github.com/Vivek-k24/Stark_T2SQL/issues/4),
the relevant FRD requirements, existing generator/checks, frozen schema and
database/persona contracts. The supplied review was an untracked file in
`H:\STARK T2SQL`; `Antigravity_Design_Review.md` also had reviewer changes there.
Both reviewer files were preserved without editing or staging them.

Git history established that R01 PR #12 had subsequently been merged by the
coordinator into `gemini/full-remediation-review` at
[`51058398182e65a234f5e7da2b27a4ce763436ec`](https://github.com/Vivek-k24/Stark_T2SQL/commit/51058398182e65a234f5e7da2b27a4ce763436ec).
That later merge supersedes the historical draft status recorded in section 8;
Codex did not perform that merge during R02.

After fetching the latest integration branch, Codex created
`codex/r02-remediation` from that commit in the separate worktree
`H:\STARK_T2SQL_R02`. This kept the original review checkout on
`antigravity/r02-review` and preserved its uncommitted review material. No R01
branch was reused for R02 and no integration/main branch was pushed directly.

### Initial problems and resulting implementation

Normal generation previously required an unavailable, extensive external JSON
configuration. The loader refused populated tables, there was no executable
CLI, exporters were absent, and an existing test expressly prohibited them.
The new default is a **new R02 synthetic baseline**, authorized by the design
review. It is not a reconstruction of an unavailable historical dataset.

`seed_data.py` now builds its default configuration with a private
`Faker("en_US")` instance seeded with 42 and a private `random.Random(42)`.
Instance seeding avoids changing Faker's process-global random state. Seed 42
and as-of date `2026-10-12` are enforced. Faker's documentation limits
repeatability to the same Faker version; the manifest records the exact
version used for this export ([Faker seeding documentation](https://faker.readthedocs.io/en/master/#seeding-the-generator)).
The legacy explicit-configuration loader and its historical-schema binding
checks remain available; the new default supplies no historical binding.

The generated baseline contains ten divisions including Sales and Engineering,
37 departments, seven locations, twenty positions, and 500 synthetic employees
numbered `S00001` through `S00500`. Exactly 435 are active at the fixture date;
the remaining 65 include terminated employees, future hires and cancelled
pre-hires. The manager graph is acyclic, an active Sales manager has reports,
and anchors 326, 47, 361 and 364 are active. Employee emails use the reserved
`starkcorp.example.com` domain. Compensation ranges, regular biweekly payroll,
off-cycle corrections, earning/deduction detail, leave snapshots and HR scopes
are generated and checked.

All **18 previously authored operational checks** are retained, with their
`DRAFT-FIXTURE-01` through `DRAFT-FIXTURE-18` IDs. Those checks are not described
as the recovered original historical invariant list. The manifest records their
actual offline results and computes planted-fact observations from generated
rows rather than merely repeating configured targets.

The CLI defaults to in-memory generation and checks, with no database connection
or output files. It exposes `--dry-run`, `--reset`, `--database-name`,
`--isolation-proof`, `--export-dump` and `--export-manifest`. Reset requires an
explicit opt-in and proof. Export writes deterministic, primary-key-sorted SQL
INSERT statements and a JSON manifest using LF bytes and atomic file
replacement. Output names are restricted to the dedicated fixture artifact
names, preventing these exporters from overwriting `schema.sql` or other
source files. The manifest exporter refuses a dump that differs from the
expected regenerated bytes.

### Reset boundary and deliberate safety choices

The review's example `TRUNCATE ... CASCADE` and `setval` sequence were adapted
to the owner's stronger isolation requirement:

- Require an exact trusted `AdminConnectionSource`, an allowlisted database
  name, a numeric loopback endpoint, and a separately supplied isolation proof.
  Proof binds the real database OID, endpoint, port, isolation token and frozen
  schema hash. No proof or database authorization marker is invented by the
  generator.
- Match the proof against the connected database identity and independently
  provisioned database COMMENT marker. Require the setup role to own the
  database, connection limit 1, and no other active client connections.
- Take bounded exclusive locks and inspect the live schema before destructive
  SQL. Refuse unrelated tables/views/foreign or partitioned relations, unknown
  column shapes/types/nullability/identity flags, mismatched constraint/key
  inventory, inheritance, user triggers/rules, custom routines and foreign keys
  from outside the fixture set.
- Verify the twelve key sequences individually and their ownership before
  truncation. Use an explicit list of the twelve `ONLY public.<table>` targets
  with `CONTINUE IDENTITY RESTRICT`; there is no `CASCADE` path. Restart only
  the twelve verified sequences with transactional `ALTER SEQUENCE ... RESTART`.
- Load parameterized rows, restore `SET CONSTRAINTS ALL IMMEDIATE`, read back
  the inserted data and run all 18 checks plus an exact generated-row comparison
  before commit. Perform fresh read-only verification after commit. Guard,
  insert and pre-commit verification failures roll back the transaction.

PostgreSQL documents the scope of `ONLY`/`RESTRICT` and that sequence `RESTART`
is transactional, unlike `setval`
([TRUNCATE](https://www.postgresql.org/docs/16/sql-truncate.html),
[ALTER SEQUENCE](https://www.postgresql.org/docs/16/sql-altersequence.html)).
These choices explain the departure from the review's example; they are not
evidence that the SQL was executed against PostgreSQL during this work.

### Files created or modified

| Path | Purpose |
| --- | --- |
| `seed_data.py` | Autonomous generation, fact observations, CLI, deterministic exporters and isolated reset/verification boundary; retain legacy explicit-input checks. |
| `fixture_pg_dump.sql` | New deterministic data-only SQL snapshot with explicit sequence restarts, no owner/ACL statements, schema DDL, truncation or drops. |
| `fixture_manifest.json` | Exact dump hashes, row counts, planted facts, all 18 check results, generator/schema/configuration provenance and explicit verification limits. |
| `tests/test_fixture_source.py` | Replace only the two obsolete assertions about absent default configuration and prohibited exporters; retain legacy missing-input/fidelity checks. |
| `tests/test_seed_generation.py` | Repeatability, all 18 positive and negative checks, lifecycle/personas/facts, actual committed-artifact regeneration/hash checks, CLI safety, mocked reset/rollback guards and opt-in live test. |
| `.gitattributes` | Enforce LF for dump, manifest and generator; generator LF also stabilizes its recorded source-byte hash across checkouts. |
| `Codex_work_log.md` | Preserve R01 history and record R02 implementation and evidence. |

`schema.sql`, all `src/` files, prompt resources, policies, semantic/security
code, the inference client, UI, evaluation code and `pyproject.toml` are
unchanged. The work is confined to the seven authorized paths above.

### Offline artifact generation and actual observations

The base Python environment lacked Faker; the initial dry run failed on that
missing dependency. Codex created a separate environment outside the source
tree at `H:\STARK_T2SQL_R02_ENV`, using Python 3.12.10 with existing site
packages. Faker 40.43.0 and psycopg2-binary 2.9.13 were installed only there.
The driver was needed by mocked SQL-composition tests; installing it did not
connect to a database. No model, PostgreSQL server or application service was
installed or started.

The actual offline export command, repeated after the final generator change,
was:

```powershell
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' seed_data.py --export-dump fixture_pg_dump.sql --export-manifest fixture_manifest.json
```

| Table | Observed rows |
| --- | ---: |
| divisions | 10 |
| locations | 7 |
| departments | 37 |
| positions | 20 |
| employees | 500 |
| employee_compensation | 950 |
| payroll_runs | 21 |
| payroll_results | 9,184 |
| payroll_earnings | 18,364 |
| payroll_deductions | 18,368 |
| leave_balances | 2,610 |
| hr_bp_assignments | 6 |

The observed DR-3 facts are: three negative-net results in `PR-2026-006`;
zero total 2026 taxes for exactly employees 10, 20, 30 and 40; the sole
header/detail mismatch in `PR-2026-012` is gross pay plus USD 125.00; approved
off-cycle `PR-2026-024` has four correction lines; departments 1–7 are the seven
small compensated departments; open HR scopes are 47 → [1, 2], 361 → [3, 4],
and fallback 364 → [5, 6]. These were verified from offline rows, not live SQL.

Actual artifact/source SHA-256 values:

| Bytes hashed | SHA-256 |
| --- | --- |
| `fixture_pg_dump.sql` (10,082,657 bytes) | `859aa6badb797159f846d0870e377e3aade04049adc4174d2cd7dd6a98dd4fc4` |
| `fixture_manifest.json` | `fb15e54afc4b72e02076614fec108049595ab1879feeabe9871f131fccb2640e` |
| `seed_data.py` | `ee9fd0a9965b51f6289290caa211460a65f9b2c38728bf99bb1133265d0561bf` |
| Unchanged `schema.sql` | `f1b5976a08ebeeeb085d7095ddf25edfb06a261b2ebfe9f0653cb3a8b5128bf3` |
| Generated configuration | `9b3bfdc67e245d79e9dde9d28afdd2af0ad820c87a4f1b26a7ab982130baa312` |

The manifest's `fixture_dump_sha256` and compatibility key `sha256` agree with
the actual dump bytes and the existing persona digest reader. Tests regenerate
the full dump byte-for-byte, compare repeat exports of both artifacts, reject
tampered/CRLF dump input, and verify the committed manifest's generator and
schema hashes. Reproducing this baseline requires the recorded Faker version;
other Faker releases are not claimed to produce identical names or bytes.

### Tests executed and results

The first focused run reached 70 passes, 4 failures and 2 skips; all four
failures were missing psycopg2 imports in the isolated environment. After
installing that already-declared dependency, the focused suite passed. Further
guard and artifact tests were added before the final runs below. An earlier
full run had 325 passes and 178 skips; the final committed-snapshot regression
test added one passing case. None of these runs established live acceptance.

Final prescribed commands (both with database integration explicitly disabled):

```powershell
$env:STARK_TEST_ENABLE_DB_INTEGRATION = '0'
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest tests/test_fixture_source.py tests/test_schema_contracts.py tests/test_seed_generation.py -q -ra
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest -q -ra
```

| Final run | Passed | Failed | Skipped | Exit code |
| --- | ---: | ---: | ---: | ---: |
| Focused R02 | **84** | **0** | **2** | **0** |
| Full Python suite | **326** | **0** | **178** | **0** |

The focused skips are the absent `STARK_TEST_SCHEMA_METADATA_PATH` input and
the explicitly disabled new R02 live reset test. Full-suite skips comprise the
existing 177 external-review/disabled-integration cases plus that new live
reset case. Missing review inputs include schema metadata, adversarial scope,
reference review, parser review and wall-clock review. These are skips, not
passes or recovered historical evidence. The pre-existing pytest-asyncio
fixture-loop-scope deprecation warning remains. Final outputs were captured
outside the repository in the isolated environment directory.

### Remaining verification and stopping gate

No live database was provisioned, connected, reset or populated in this R02
implementation. The SQL snapshot has not been restored into PostgreSQL. Mocked
guard/rollback tests and successful offline invariants do not establish live
PostgreSQL acceptance. A later opt-in run requires an actual independently
isolated schema clone, database marker/proof and administrative credentials
(`STARK_R02_ADMIN_USER`, `STARK_R02_DB_NAME`, `STARK_R02_DB_PASSWORD`, optional
`STARK_R02_DB_PORT`; the integration test additionally uses
`STARK_R02_ISOLATION_PROOF` and `STARK_TEST_ENABLE_DB_INTEGRATION=1`).

The manifest expressly records `scope: offline_generated_rows`,
`live_postgresql_verified: false`,
`historical_dataset_fidelity_verified: false`,
`historical_schema_fidelity_verified: false`, and
`original_historical_invariant_list_recovered: false`. The unavailable original
historical generator/data/invariant list remain unavailable; the new baseline
does not silently substitute for them.

**R02 source implementation and prescribed offline tests are complete;
independent Antigravity verification and live acceptance remain pending.**
The branch is to be handed off as a draft PR against
`gemini/full-remediation-review`. No merge or R03 work is authorized by this
implementation handoff.
