# Codex R05 implementation work log

Date: 2026-10-15. Gate: SQL Validator Safety and Ablation Fidelity.

## Authority, baseline and workspace

- Owner implementation request: Gate R05, [Issue #7](https://github.com/Vivek-k24/Stark_T2SQL/issues/7), FRD 1.8, merged `AGENTS.md`, and the complete `Antigravity_R05_Review.md`.
- Integration baseline: `0e7f643a3577d32ab4e579c4a66ef6666e6ab5fe`, the owner's R04 merge from [PR #19](https://github.com/Vivek-k24/Stark_T2SQL/pull/19).
- Approved design commit: `93f7940243c299f6813505baae1ac812e7e6eeac`.
- Existing shared branch: `codex/r05-remediation`. No new branch was created. Implementation used a clean clone at `H:\STARK_T2SQL_R05` on that same branch.
- The original `H:\STARK T2SQL` checkout contained unrelated edits to `Antigravity_Design_Review.md` and `Antigravity_R05_Review.md`. Those edits were left in that checkout, untouched and uncommitted.
- No installation, database operation, inference service startup, automatic dispatcher, UI update, merge, main-branch push or R06 work was performed.

## Initial findings and chronological implementation

1. Read the gate requirements and inspected the existing validator, function policy, harness, executor, contracts, tests and actual installed parser. The existing interpreter was `H:\STARK_T2SQL_R02_ENV\Scripts\python.exe`: Python 3.12.10, pytest 8.3.5 and SQLGlot **30.22.0**. No dependency was installed for R05.
2. Ran the full offline suite before implementation: **611 passed, 162 skipped, 1 failed**. The sole failure was `tests/test_interim_ui.py::test_health_and_cached_progress_need_no_runtime`. Its all-milestones-MERGED assertion disagrees with checked-in R04 progress marked `VERIFIED — AWAITING MERGE`. This explains the difference from R04's published **612 passed, 162 skipped** result; it is an existing progress mismatch, not a new validator failure.
3. Independently inspected real PostgreSQL-dialect SQLGlot output. `COUNT(*)`, `COUNT(column)` and `COUNT(DISTINCT column)` contain `Count(big_int=True)`. `IS NOT NULL`, `NOT LIKE` and `NOT ILIKE` carry `negate=True` on `Is`, `Like` and `ILike`. Explicit `NOT (manager_id IS NULL)` instead uses `Not(Paren(Is(...)))`.
4. Corrected COUNT and operator metadata handling, retaining exact-class checks and strict `type(value) is bool`. Presence checks run even for falsey values such as `None`, `0` or empty containers. COUNT metadata cannot appear on other AST classes; negation metadata cannot appear on unreviewed operator classes. Function argument values and DISTINCT members must be expression nodes, and malformed argument collections fail closed.
5. Bumped validator and function-policy revisions to `fr5-validator-r05-1` and `fr5-function-r05-1`. Earlier profile revisions cannot silently authorize the changed grammar.
6. Audited proposed parser capabilities through actual SQL, regeneration, reparsing, positive validation and negative mutations. The design's counts were not used as approval evidence. Removed synthetic Anonymous positive AST substitutions from the old contract tests.
7. The first combined evidence run produced **380 passed, 32 skipped, 4 failed**. Three failures arose because a positive arithmetic corpus included division, whose actual `Div(typed=True)` layout the existing guard deliberately rejects. The fourth was a Star mutation rejected earlier by COUNT's own modified-star guard. Preserved the division restriction, excluded `Div` from the test profile, added an explicit division rejection contract, and used a real standalone `SELECT *` source to isolate the Star node's unknown-argument check. The rerun produced **385 passed, 32 skipped, zero failed**.
8. Confirmed the actual harness already widens table visibility for `NO_VALIDATOR` and `UNCONTROLLED`, while retaining structural checks. Corrected its stale docstring and added real-parser harness tests around mocked database connections. Database policy/executor code did not change.
9. Added focused malformed-argument and regeneration tests, including real COUNT forms, negation, outer joins, cross joins, subquery modifiers, unavailable layouts, wrong versions, source revision drift and fail-closed renderer/reparser behavior. Latest standalone argument-safety run: **197 passed, zero failed/skipped**.
10. Ran the prescribed full offline suite on the completed code: **1,111 passed, 58 skipped, 1 failed** in 73.68 seconds. The sole failure was the same pre-existing interim UI progress assertion. Re-ran the prescribed two-file suite on the final source: **237 passed, 32 skipped, zero failed**. The two new evidence files together passed **345 tests, zero failed/skipped**. No new failing test was introduced.

## Files and purposes

| File | Purpose |
| --- | --- |
| `src/stark_t2sql/security/function_policy.py` | Exact COUNT boolean metadata, expression/container validation, DISTINCT safety and revision binding. |
| `src/stark_t2sql/security/validator.py` | Reviewed negated operators, class-specific metadata guards, COUNT scalar metadata traversal, revision binding and accurate harness documentation. |
| `tests/fixtures/parser_approval_sqlglot_30_22_0.json` | Explicit **TEST-ONLY** empirical profile, pinned to SQLGlot 30.22.0 and both R05 source revisions; 59 admitted structural classes and 27 actual function representations. |
| `tests/conftest.py` | Pytest-only profile fallback when `STARK_TEST_PARSER_REVIEW_PATH` is unset; explicit external input retains precedence and existing external acceptance inputs remain required. |
| `tests/test_validator_contracts.py` | Exercise actual parsed function layouts, retain honest excluded-representation skips, preserve safe/unsafe and missing-approval contracts. |
| `tests/test_execution_resources.py` | Real-parser safety/entitlement checks and explicitly mocked connection identity, resource-gate and SQLSTATE attribution checks. |
| `tests/test_r05_parser_evidence.py` | Reproducible per-function and per-shape source evidence, roundtrips, negative mutations and explicit exclusions. |
| `tests/test_r05_argument_safety.py` | Strict metadata/argument tests, safe query variants, invalid regeneration/reparse and invalid-profile failures. |
| `Codex_R05_Work_Log.md` | This implementation record and handoff limitations. |

## Parser evidence and approval status

This is **completed offline empirical test evidence**, not a fabricated human signature or production approval. The JSON reference identifies these executable evidence files and this log, and explicitly disclaims human production approval, database audit and live acceptance. Only pytest loads the fallback. Runtime composition was not changed, and `ReviewedSQLValidator(matrix, approval=None)` continues returning `REVIEW_REQUIRED` / `MISSING_DEPENDENCY` without executable SQL.

The profile pins `sqlglot_version` to **30.22.0**, and the evidence test independently asserts the installed version is exactly that value. Wrong-version profiles fail closed. This is a parser-profile pin and verified test environment, **not** a change to packaging requirements; `pyproject.toml` remains frozen. Production needs a genuine trusted human-approved runtime contract and its matching environment before acceptance can be claimed.

### Admitted and excluded capabilities

- All **60 proposed structural classes were inspected** through real SQL. **59** have passing positive and unknown-argument negative contracts. A 16-query accepted corpus covers those 59 before and after regeneration. `Div` is observed but excluded: PostgreSQL parsing emits `typed=True`, and R05 does not broaden the existing division guard.
- **27 observed function representations** are admitted: 22 known layouts and five actual Anonymous layouts. Every admitted representation has real SQL, exact-class matching, function-policy validation, full validator acceptance, regeneration/reparse checks and unknown-argument rejection.
- Known layouts: Count, Sum, Avg, Min, Max, Lower, Upper, Abs, Round, Coalesce, Nullif, TimestampTrunc, RowNumber, Rank, DenseRank, PercentileCont, Cast, Extract, CurrentDate, CurrentTimestamp, CurrentTime and Localtimestamp.
- Actual Anonymous layouts: `age`, `statement_timestamp`, `transaction_timestamp`, `clock_timestamp` and `timeofday`. Clock acceptance here preserves FR-5.9/FR-9.6 separation; it is not evaluation acceptance of wall-clock-dependent answers.
- **16 proposed function representations remain excluded**. `DATE_TRUNC` produces TimestampTrunc rather than DateTrunc. LocalTimestamp, Age, StatementTimestamp, TransactionTimestamp, ClockTimestamp and TimeOfDay classes are unavailable in the installed release. Nine proposed Anonymous alternatives (`count`, `sum`, `avg`, `min`, `max`, `lower`, `date_trunc`, `percentile_cont`, `now`) normalize to known classes rather than the proposed Anonymous representation. Qualification does not establish an alternate approval path.
- Constructed negative AST mutations test robustness only. COUNT False/absent metadata cases are unit grammar checks; the observed PostgreSQL COUNT layout is True. No constructed positive Anonymous layout is counted as parser evidence.

The review's **60 shapes / 36 function rules** expectation is therefore narrowed to **59 admitted shapes / 27 observed functions**. Its 13 GOOD_SQL count is correct; the actual BAD_SQL tuple has **36**, rather than the review's 33, and all are retained.

Primary semantics checked alongside installed version-specific parser source: PostgreSQL 16 documentation for [aggregates](https://www.postgresql.org/docs/16/functions-aggregate.html), [date/time](https://www.postgresql.org/docs/16/functions-datetime.html), [conditional expressions](https://www.postgresql.org/docs/16/functions-conditional.html), [window functions](https://www.postgresql.org/docs/16/functions-window.html), [math](https://www.postgresql.org/docs/16/functions-math.html) and [strings](https://www.postgresql.org/docs/16/functions-string.html). The local 30.22.0 package supplies version-specific AST facts; current online SQLGlot documentation was not treated as a substitute for that inspection. PostgreSQL overload resolution, trusted search_path, permissions and actual installed object identity still require database verification.

## Ablation behavior and attribution

- FULL application review rejects a Sales Manager's `employee_compensation` query with `TABLE`, `BLOCKED_VALIDATOR`, and `StoppingLayer.VALIDATOR`.
- The mandatory harness remains active in every mode. Real parser tests reject SET, DDL, multiple statements, data-modifying CTEs, catalogs, unsafe calls and locks. Unsafe NO_VALIDATOR/UNCONTROLLED candidates stop before acquiring even the mocked connection or resource budget.
- Structurally safe fixture-table access in NO_VALIDATOR reaches the mocked driver with the persona lease, principal setting and business role. UNCONTROLLED selects the baseline lease (`persona=None`) without setting the business principal/role. This proves Python routing protocol only, not actual Windows credentials or PostgreSQL isolation.
- Simulated driver SQLSTATE `42501` produces `BLOCKED_DB`, `DB_PERMISSION_DENIED`, `StoppingLayer.DATABASE` and rollback. Mock success rows are explicitly unit data, not live query results.
- Reconciled a design inconsistency: R05-F5's sample labels a harness stop as `StoppingLayer.VALIDATOR`. FR-9.5 and the real shared errors/executor contracts instead use **`StoppingLayer.HARNESS`**. Tests preserve that accurate distinction; frozen contracts were not changed.
- Stale NO_VALIDATOR role-table wording also remains in out-of-scope `evaluation/ablation.py` (`direct` docstring) and `evaluation/runner.py` (direct evaluation narrative). Actual reviewer behavior and tests implement the entitlement bypass; these documentation locations are disclosed rather than silently edited.

## Verification commands and results

All pytest runs use the existing interpreter above, working directory `H:\STARK_T2SQL_R05`, `STARK_TEST_ENABLE_DB_INTEGRATION=0`, and `PYTHONPATH=src;.`. No external parser approval environment override was supplied; the authored test-only fixture was exercised.

```powershell
$env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
$env:PYTHONPATH='src;.'
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest tests/test_validator_contracts.py tests/test_execution_resources.py -q -ra
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest tests/test_r05_parser_evidence.py tests/test_r05_argument_safety.py -q -ra
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest -q -ra
```

| Run | Passed | Failed | Skipped | Exit status |
| --- | ---: | ---: | ---: | ---: |
| Full suite before implementation | 611 | 1 | 162 | 1 |
| Final prescribed validator/execution suite | 237 | 0 | 32 | 0 |
| Final parser evidence and argument-safety files | 345 | 0 | 0 | 0 |
| Final full offline suite | 1,111 | 1 | 58 | 1 |

The full suite is **not all-green**: its one failure remains `tests/test_interim_ui.py::test_health_and_cached_progress_need_no_runtime`, line 23. Neither the progress data nor that test was modified or suppressed.

Skip reconciliation:

- The 136 original validator-profile-dependent cases now yield **104 passes and 32 excluded-representation skips**. Those 32 are the 16 excluded function layouts parameterized for positive and negative contracts; they are not acceptance evidence.
- The remaining one of the original 137 parser-dependent skips, `tests/test_runner_contracts.py::test_actual_direct_only_composition_omits_model_and_template`, advances past parser approval but still skips at its separate live-database opt-in prerequisite. It is not relabeled a pass.
- Final 58 skips: 32 excluded parser representations, 16 missing wall-clock-review inputs, one missing adversarial-scope input, one missing reference-review input, six disabled database-integration cases, one disabled runner database case, and one disabled live seed/reset case.
- Pass-count reconciliation from the actual baseline: **611 + 104 activated existing cases + 51 new ablation cases + 148 new parser-evidence cases + 197 new argument-safety cases = 1,111**. The pre-existing failure remains unchanged. Of the 137 initial parser-dependent skips, 104 become passes, 32 remain excluded, and one advances to a database prerequisite.

### Acceptance mapping

| Review criterion | Actual offline evidence / limit |
| --- | --- |
| R05-T01 | All 13 existing GOOD_SQL cases accept and regenerate idempotently. |
| R05-T02 | All 36 actual BAD_SQL cases reject without execution text. |
| R05-T03 | Real COUNT star, column and DISTINCT SQL emit `big_int=True` and accept; malformed flags/values reject. |
| R05-T04 | Real IS NOT NULL / NOT LIKE / NOT ILIKE accept; exact boolean and invalid-class metadata are tested. Explicit NOT wrapper also accepts. |
| R05-T05 | COUNT FILTER accepts and roundtrips. |
| R05-T06 | All **27 genuinely observed** function representations pass; the proposed count of 36 is not claimed. Sixteen alternate representations remain excluded. |
| R05-T07 | All 27 admitted functions reject unknown arguments; additional scalar/container/metadata failures are tested. |
| R05-T08 | Authored TEST-ONLY profile executes the supported subset without an environment override; 137-to-zero skips is deliberately not claimed. Production human approval is still unavailable. |
| R05-T09 | Sales unauthorized table is rejected at the application validator. |
| R05-T10 | Real mandatory harness stops unsafe candidates in all modes; executor tests prove no mocked connection acquisition in NO_VALIDATOR/UNCONTROLLED. |
| R05-T11 | Real reviewer plus mocked driver proves routing and simulated 42501 attribution only. **Live PostgreSQL acceptance remains unverified/R09.** |
| R05-T12 | Existing BAD_SQL cases reject CTE aliases shadowing employees and employee_compensation; implementation retains CTE_SHADOW checks. |
| R05-T13 | Existing unauthorized-column-on-authorized-table case accepts at application review; actual column-grant rejection requires PostgreSQL. |
| R05-T14 | No supplied approval fails closed with REVIEW_REQUIRED / MISSING_DEPENDENCY and no executable text. |

The inherited pytest-asyncio warning about unset `asyncio_default_fixture_loop_scope` remains outside R05 scope.

## Frozen asset checks

Compared working-tree Git blob identities to approved design commit `93f7940243c299f6813505baae1ac812e7e6eeac`; all entries below were unchanged. SHA-256 values are of the actual clean-checkout bytes:

| File | SHA-256 |
| --- | --- |
| `schema.sql` | `f1b5976a08ebeeeb085d7095ddf25edfb06a261b2ebfe9f0653cb3a8b5128bf3` |
| `seed_data.py` | `ee9fd0a9965b51f6289290caa211460a65f9b2c38728bf99bb1133265d0561bf` |
| `fixture_manifest.json` | `fb15e54afc4b72e02076614fec108049595ab1879feeabe9871f131fccb2640e` |
| `fixture_pg_dump.sql` | `859aa6badb797159f846d0870e377e3aade04049adc4174d2cd7dd6a98dd4fc4` |
| `src/inference/prompt_template.txt` | `67d1c6d265202e6bf6abcd1393203e84b92bf9df03207015679339fe807ad6b6` |
| `policy/access_matrix.yaml` | `85efd46ce237aea0dab8aac57af81c667320508ef841dbf79c5f2eebfefd42e9` |
| `semantic/catalog.yaml` | `2eb213d793819e51bbae100a842485adafcde16ea6026fcb918247e652b447ed` |
| `AGENTS.md` | `a1d589b07bc2237f2932faace3fd23c7cd7ce4f789636ff59bf9424c703dc390` |
| `ops/progress.json` | `7874e8b92c300d5e7577f2a8e68f10a28d27045006053fb1d229a6de0cafdd35` |
| Repository E0 HTML | `0e9fb089ae7a4fb280b7ba42bfa29d6771a80b9b57a110c2c10fe0f5b927fecb` |
| `pyproject.toml` | `a28dcde9202d86b19548cf883c9f4765538b89c94f2672e9ed9349d6c0ea6190` |

## Handoff limits

Production parser approval remains unavailable and was not manufactured. Real PostgreSQL SQLSTATE 42501, ACL/RLS, query-resource enforcement, SQLCoder inference and full end-to-end acceptance are **not established by R05 offline tests**. Live security acceptance remains R09 work after owner authorization.

The known progress mismatch is left for owner-prompted Antigravity verification. That later phase must verify the R04 merge, update `ops/progress.json` and canonical HTML, and protect/compare/update the owner's actual browser file at `H:\STARK T2SQL\STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html`, plus the legacy double-extension H-drive copy if still used. Codex has not updated either local browser copy. No Antigravity execution or next gate was initiated.
