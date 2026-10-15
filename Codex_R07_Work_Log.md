# Codex R07 work log

## Authority, baseline and working copy

Implementation date: 2026-10-15. Gate: R07, Canary Security, Failure Taxonomy, Direct Runner Resilience and Complete Scoring.

- Tracking issue: [Issue #9](https://github.com/Vivek-k24/Stark_T2SQL/issues/9), including the [owner's manual handoff](https://github.com/Vivek-k24/Stark_T2SQL/issues/9#issuecomment-6203324502).
- Approved design: [Antigravity_R07_Review.md](Antigravity_R07_Review.md) at `a313f3cf87d2433bac1349ab209d431389c3ab06`, verdict **APPROVE for implementation**. This is not independent acceptance of these changes.
- Integration baseline: `afdd4b661fe21d999a1c121f4fd272bd0e423ff6`, the owner merge of [R06 PR #21](https://github.com/Vivek-k24/Stark_T2SQL/pull/21).
- Existing shared branch: `codex/r07-remediation`. PR base: `gemini/full-remediation-review`.
- Read `AGENTS.md`, FRD 1.8's evaluation and temporal requirements, Issue #9, the complete R07 design review, and the relevant implementation and tests before editing.

The original checkout at `H:\STARK T2SQL` already had unrelated changes to `Antigravity_Design_Review.md` and `Antigravity_R07_Review.md`. They were left intact. Implementation used a separate clean clone at `H:\STARK_T2SQL_R07`, checked out on the same existing remote branch at the approved design commit. No alternate branch, reset, stash, force push or original-checkout overwrite was used. A final inspection still showed only those two pre-existing review modifications in the original checkout.

The user's implementation instructions take precedence over the design review's broader ownership table: `evaluation/attribution.py` was inspected but **not modified**. Accounting was completed in the four issue-owned source files. The review's illustrative `rstrip(";")` recipe was replaced with a stricter token-aware implementation to satisfy the owner's explicit single-statement safety requirement.

## Chronological implementation record

### 1. Reproduce the starting state

Using the existing environment `H:\STARK_T2SQL_R02_ENV\Scripts\python.exe`, reproduced both baselines before making changes:

| Scope | Passed | Skipped | Failed |
| --- | ---: | ---: | ---: |
| Prescribed three evaluation contract files | 50 | 17 | 0 |
| Full offline suite | 1,319 | 58 | 0 |

The baseline matched the approved review and R06 integration evidence. No packages were installed. The environment reports Python 3.12.10, pytest 8.3.5 and SQLGlot 30.22.0.

### 2. R07-F1: select only forbidden cells and bind salary dates

Changed `FixtureCanaryProvider.for_case()` in `evaluation/reference.py`:

- Observe each selected employee's row visibility through the existing business-persona observer. Accept only an exact integer count of zero or one; unknown or malformed visibility evidence makes the computation unavailable.
- For each selected field, exclude an employee only when that column is granted **and** the employee is visible. Build a separate forbidden employee list for each field. A permitted field/cell is never included in its administrative value query.
- Keep forbidden cells from mixed selectors. Skip fields with no forbidden employees. An entirely permitted selector stops before opening the administrative connection and returns an unavailable `CanaryResult` through the existing exception boundary.
- Preserve the exact case/persona/selector binding, actual fixture digest checks, field allowlist, bounded employee IDs, read-only administrative lane, source-employee existence check and row cap. Reject duplicate selector fields and inconclusive administrative RLS-bypass flags.
- Apply the half-open salary interval `effective_date <= as_of_date AND (effective_to IS NULL OR effective_to > as_of_date)`. Bind both dates as parameters alongside the forbidden employee IDs.
- Use `DISTINCT ON (employee_id)` with `ORDER BY employee_id, effective_date DESC, compensation_id ASC` to choose one latest applicable compensation row per employee. The frozen schema already has unique `(employee_id, effective_date)` and a compensation primary key. The final key makes the ordering deterministic; the synthetic equal-date tie test exercises the ordering rule, not a claim that duplicate-date data is valid under that schema.
- Validate every extracted value with `require_distinctive_canary()`. Skip nondistinctive cells, retain distinctive forbidden cells, and deduplicate with the existing typed canonical representation. No applicable salary row supplies no invented value. If no distinctive forbidden value remains, return unavailable rather than clear or positive leak evidence. A row-cap overflow remains unavailable rather than truncated evidence.

The added `DISTINCT ON` refines the design's ordered salary query into the owner's explicitly required per-employee selection. PostgreSQL's documented ordering requirements were checked against the query: [SELECT / DISTINCT ON](https://www.postgresql.org/docs/16/sql-select.html). The SQL was parsed with the installed SQLGlot in offline tests. It was not executed against PostgreSQL. Closed compensation interval overlaps are not disproved by source inspection, and no historical fixture fidelity is claimed.

### 3. R07-F2: verify taxonomy, fix typed manual input

Independently inspected `classify_failure()` and the actual `AccuracyHistogram` implementation. The classifier's existing branch order already implements the required precedence, so its classification branches and class vocabulary were left unchanged:

1. Observed leak, then prohibited wall-clock use.
2. Harness safety stops and missing evaluation evidence remain unscored; passing outcomes have no failure class.
3. Extraction, generation and observable SQLSTATE errors.
4. Reference-proven validator rejection, then other legitimate overblocking.
5. Expected versus unexpected permission denials; unknown SQLSTATE remains runtime triage.
6. Supplied typed manual triage, otherwise unresolved intent remains pending without an invented catch-all class.

Found one actual validation defect: `FailureClass` is a string enum, so raw `"FC-SEMANTIC"` passed the previous membership test. `ManualTriage` now requires an actual `FailureClass` member as well as an allowed manual class and nonempty reviewer/evidence strings. The six allowed manual classes remain SCHEMA, JOIN, FILTER, AGG, TEMPORAL and SEMANTIC. This validates the input contract; it does not authenticate a reviewer or create a human review. Unit metadata is explicitly synthetic/TEST-ONLY.

Later, a runner precedence regression exposed a separate loss of evidence: an unavailable computed-canary provider overwrote an already observed, fixture-bound case-canary leak. The runner now preserves that observed leak. Unavailable computation without an observed leak still produces an unscored assessment. No replacement canary or fabricated clearance is introduced.

### 4. R07-F3: incomplete runtimes and safe optional terminators

In `evaluation/runner.py`, canonical-resolution assessment now checks `getattr(runtime, "catalog", None)` and `getattr(runtime, "snapshot", None)`, as well as model availability, question and expected concept ID. Missing inputs produce `passed=None` with `Actual canonical-definition expectation is unavailable.` The resolver is not called and no catalog/schema evidence is synthesized. Catalog fingerprint collection also tolerates an absent or null catalog.

Added `_candidate_matches_reference()` for reference proof:

- Require an available reference, its existing legitimate-query proof and its executed-SQL hash.
- Reuse R06's strict physical-reference parser to reject malformed, write-bearing and multiple-statement candidates.
- Tokenize with the pinned PostgreSQL parser. Allow only original candidate bytes, outer-whitespace trimming and addition/removal of **one actual terminal semicolon**. Multiple semicolons are not stripped away. Semicolons in strings or comments are not mistaken for statement terminators; appending inside a trailing line comment does not create a variant.
- Compare those limited candidate variants against the unchanged reference hash. Do not rewrite operators, internal whitespace, projections, aliases or statements, and do not create a new reference receipt or approval.

The SQLGlot token API was checked in installed 30.22.0 source and [its token documentation](https://sqlglot.com/sqlglot/tokens.html). Both terminator directions have helper and runner-level tests. A syntactically safe candidate still cannot acquire reference proof without the existing available, legitimate, hash-bound reference.

The first post-change focused run had **49 passed, 17 skipped, 1 failed**. The existing canonical-ID mismatch test used a stub resolver with no catalog/snapshot, so the new required guard correctly made it unscored. Its test setup was corrected to supply explicit synthetic catalog/snapshot capabilities; the original concept-ID mismatch assertion remains. The production guard was not weakened.

### 5. R07-F4: reconcile all six counts and publish partial results

Added explicit `RunSummary` properties and one accounting mapping:

| Count | Definition |
| --- | --- |
| `total_cases` | Observed cases plus unsubmitted case IDs |
| `scored_cases` | Actual passed plus failed observations |
| `unscored_cases` | Observations with unavailable scores |
| `pending_triage_cases` | Failed scored observations still requiring triage |
| `unsubmitted_cases` | Selected case IDs not submitted |
| `pending_cases` | Unscored plus unsubmitted cases |

Enforce `total_cases == scored_cases + unscored_cases + unsubmitted_cases`. Pending triage is a subset of failed scored cases, not an additional pending category. `RunSummary` rejects duplicate/overlapping IDs, histogram/record drift, triage on nonfailed observations and an unjustified complete flag.

Added shared accounting validation in `evaluation/records.py`. Summary JSONL includes all six counts and checks agreement with the actual accuracy histogram. `PROJECT_LOG.md` uses those same counts, including separately reported pending triage, without adding case IDs or private content. The existing two-count writer interface remains usable by older callers.

At cancellation boundaries, the runner now emits a partial summary for already observed cases, records remaining IDs as unsubmitted and marks cancellation unavailable. Failed warmup emits zero case observations and records every selected case as unsubmitted. Tests cover a partial run containing one pass, one failed pending-triage case, one unscored case and one unsubmitted case: total 4, scored 2, unscored 1, pending triage 1, unsubmitted 1, pending 2. Summary JSONL and project-log counts agree. A cancellation before any submission is also covered.

These are tested case-boundary cancellation and failed-warmup paths, not a claim of recovery from every possible process crash or external exception. Unexpected failures that cannot safely yield a score are not converted into invented observations.

Also corrected a stale runner limitation string: NO_VALIDATOR bypasses application table entitlements while retaining mandatory structure safety and the business database identity. No ablation policy or executor code was changed.

### 6. Add offline regressions and verify protected scope

All added data is synthetic, in memory or in pytest temporary directories. Canary protocol tests mock database cursors, persona observations and the deadline wrapper; their SQL shape is additionally checked by the real parser. These establish Python/query-construction behavior, not live PostgreSQL/RLS or deadline enforcement.

The sealed-writer tests use synthetic sentinels and temporary sealed roots. They check metadata-only JSONL/project-log output and reject question, reference SQL, rows and forbidden-value fields. No actual holdout question, reference or canary payload was inspected or changed. The existing holdout split, owner permits, ledger, trace isolation and loader boundaries remain unchanged.

| Acceptance criteria | Evidence in focused tests |
| --- | --- |
| T01-T02 | Mixed employee/field selectors, role grants, all-permitted selectors and forbidden-only deduplication in `test_r07_canaries.py` |
| T03-T04 | Bound inclusive-start/exclusive-end dates, latest applicable salary, deterministic ordering, absent salary rows, distinctive values, row cap and unavailable source/visibility evidence |
| T05-T06 | Leak precedence across simultaneous symptoms; wall-clock precedence over matching, unscored and error outcomes; runner preserves an already observed leak |
| T07-T09 | Observable-error precedence, proven/unproven overblocks, expected/unexpected permissions, runtime triage, six manual classes, invalid class/provenance negatives and unresolved intent |
| T10-T11 | Absent and null catalog/snapshot; both semicolon directions; malformed/multiple statements, comments, literal semicolons, changed meaning and unproven reference negatives |
| T12 | Mixed accounting categories, histogram drift rejection, partial/pre-submission cancellation, consistent JSONL/project logs and invalid-count rejection |
| T13 | All four named historical runner regressions pass in the prescribed suite |
| T14 | Synthetic sealed writer metadata tests plus the unchanged existing holdout isolation regressions |

The four historical tests preserved and executed are `test_direct_run_does_not_need_model_template_or_warmup`, `test_question_run_requires_guarded_tuning_warmup_and_never_scores_it`, `test_required_evaluation_inputs_remain_unscored` (all four dependency variants), and `test_failed_warmup_reports_unsubmitted_ids_without_per_case_result`.

R06's `ScopeReviewStore`, `ReferenceReview.binding_sha256`, reference authority, physical lineage functions and persona observer were not edited. A byte comparison of the normalized-LF `reference.py` prefix preceding `CanarySelection` against the approved design commit succeeded; its SHA-256 is `b59aecf5bc221ddd47536e415b89bac85225a325f09c4aa780f7f3dd60da44c9`. The comparator and evaluation connection/scope code are outside the implementation diff.

Git blob checks against the approved design commit confirmed unchanged `schema.sql`, `seed_data.py`, `fixture_manifest.json`, `fixture_pg_dump.sql`, `src/inference/prompt_template.txt`, `policy/access_matrix.yaml`, `semantic/catalog.yaml`, `AGENTS.md`, `pyproject.toml`, `evaluation/attribution.py`, `evaluation/holdout.py`, `ops/progress.json` and the repository HTML. No protected holdout payload was opened for this check. `git diff --check` passed.

## Actual test execution and results

All pytest runs used the existing interpreter and these settings:

```powershell
$env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
$env:PYTHONPATH='src;.'
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest tests/test_runner_contracts.py tests/test_evaluation_contracts.py tests/test_run_record_contracts.py -q -ra
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest tests/test_runner_contracts.py tests/test_evaluation_contracts.py tests/test_run_record_contracts.py tests/test_r07_canaries.py -q -ra
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest -q -ra
```

| Execution stage | Passed | Skipped | Failed |
| --- | ---: | ---: | ---: |
| Initial prescribed baseline | 50 | 17 | 0 |
| Initial full offline baseline | 1,319 | 58 | 0 |
| First source-change check, before correcting canonical test capabilities | 49 | 17 | 1 |
| Expanded focused suite after initial regressions | 168 | 17 | 0 |
| Expanded focused suite after additional terminator/runtime/role cases | 179 | 17 | 0 |
| Final expanded focused suite, including observed-leak regression | **180** | **17** | **0** |
| Final prescribed three-file suite | **146** | **17** | **0** |
| Final full offline suite | **1,449** | **58** | **0** |

Final full duration: 33.72 seconds. The prescribed final run took 0.60 seconds; the expanded final run took 0.74 seconds. There are **130 additional passing tests** relative to the reproduced full baseline, with unchanged skip count and zero final regressions. Subsequent changes to this log/PR metadata do not alter tested source or tests.

The 17 focused skips are 16 wall-clock checks requiring actual external review input and one separately opted-in database composition check. The full 58 skips comprise:

- 32 validator representation cases excluded from the supplied parser evidence.
- 16 checks requiring `STARK_TEST_WALLCLOCK_REVIEW_PATH`.
- One adversarial scope input and one real reference-review input (`STARK_TEST_ADVERSARIAL_SCOPE_PATH` and `STARK_TEST_REFERENCE_REVIEW_PATH`).
- Six database integration checks, one direct composition database check and one live seed/reset check.

The inherited pytest-asyncio warning about an unset default fixture loop scope remains; no environment/configuration changes were made for it. Skipped checks are not acceptance evidence. No database reset, live PostgreSQL query, SQLCoder inference, model/server startup, production benchmark or actual sealed holdout execution was performed.

## Exact implementation file scope

| File | Purpose |
| --- | --- |
| `src/stark_t2sql/evaluation/reference.py` | Forbidden-cell filtering, bounded/evidenced selectors and point-in-time salary selection |
| `src/stark_t2sql/evaluation/failure_classes.py` | Require a typed, allowed manual class; retain inspected classifier precedence |
| `src/stark_t2sql/evaluation/runner.py` | Missing runtime evidence, safe terminator comparison, preserved leak precedence and complete/partial accounting |
| `src/stark_t2sql/evaluation/records.py` | Validate and serialize consistent accounting without private payloads |
| `tests/test_r07_canaries.py` | New synthetic canary protocol, date, scope and evidence regressions |
| `tests/test_evaluation_contracts.py` | Combined-symptom taxonomy and manual-triage regressions |
| `tests/test_runner_contracts.py` | Proof, runtime guards, historical regressions, partial cancellation and accounting |
| `tests/test_run_record_contracts.py` | Synthetic sealed metadata and count validation |
| `Codex_R07_Work_Log.md` | This implementation and verification record |

`Antigravity_R07_Review.md` is already part of the shared branch at the approved design commit and will appear in the gate PR; Codex did not edit it. No progress JSON, HTML, browser copy, historical review, other gate source or dependency file was modified.

## Outstanding prerequisites and handoff

Implementation and final offline regression checks are complete. Independent Antigravity implementation verification and any owner promotion/merge decision remain pending. Genuine owner scope-review records, real reference provenance, reviewed canary selectors and fixture/clone bindings are still required where the existing runtime contracts demand them. Production parser/wall-clock approval, actual PostgreSQL persona/RLS equivalence and any SQLCoder/end-to-end evidence remain separate prerequisites; this gate supplies no fabricated approval or live security result.

During a separately owner-requested Antigravity verification, that reviewer must independently verify R06's merge, update the manual progress evidence and synchronize the primary repository/browser HTML and the separate legacy `H:\STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html.html` when used, preserving local edits and reporting actual per-path copy/hash status. Those UI changes are deliberately deferred from this implementation phase.

No merge, `main` push, automatic reviewer launch, R08 work, scheduler or orchestration activation is authorized or performed. Stop for the owner after publishing the draft PR.

## Publication record

- Implementation commit: [`83a6384c1aa554b1479a26b6720503d2b116d811`](https://github.com/Vivek-k24/Stark_T2SQL/commit/83a6384c1aa554b1479a26b6720503d2b116d811), `fix(r07): harden canary evidence and reconcile evaluation accounting`. Contains the nine implementation/test/log files listed above. Pushed to the existing `codex/r07-remediation` branch and verified against `git ls-remote`.
- Draft PR: [#22 - R07: secure canary selection and complete evaluation accounting](https://github.com/Vivek-k24/Stark_T2SQL/pull/22). GitHub reported `OPEN`, `isDraft=true`, head `codex/r07-remediation`, base `gemini/full-remediation-review`, and the matching implementation SHA. Listing all PRs for that head returned exactly this one PR.
- Verified PR scope: the nine Codex files above plus the pre-existing approved `Antigravity_R07_Review.md` from `a313f3cf87d2433bac1349ab209d431389c3ab06`. No other paths appear in the PR.
- A documentation-only follow-up records these actual publication details. It changes only this log and does not change the tested implementation or test results. Its final pushed SHA is reported in the owner handoff and is available in this file's Git history.

Final implementation status: **complete, offline tests passing, draft PR awaiting owner-requested independent Antigravity verification**. No merge or next phase was initiated.
