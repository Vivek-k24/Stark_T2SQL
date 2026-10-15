# R04 implementation work log

Date: 2026-10-15 (America/Chicago). Assignment: [Issue #6](https://github.com/Vivek-k24/Stark_T2SQL/issues/6).
Branch: `codex/r04-remediation`. PR target: `gemini/full-remediation-review`.
Implementation only; stop for the owner's manual Antigravity handoff.

## 1. Authoritative inputs and baseline

Read the merged `AGENTS.md`, FRD 1.8, Issue #6 including the owner's manual
workflow correction, the complete `Antigravity_R04_Review.md`, and the existing
semantic/catalog/context/pipeline, policy grants, schema and focused tests.
Approved design commit: `6f5ba5f7121ca476665904fb0afebc57f8afa98d`.
Integration baseline: `93ef4a0d12952200b2e5711ae7d3abbf13dcd960`.
Both supplied SHAs matched the actual remote refs at the start.

The original checkout was already on the shared R04 branch, with local edits in
`Antigravity_Design_Review.md` and `Antigravity_R04_Review.md`. A separate clean
clone checked out the **same existing branch** at the approved design commit.
No alternate branch was created and neither original edit was changed/staged.
The R04 review's local difference was a trailing blank line; its committed design
remained the implementation authority. No historical review was modified.

Before implementation, the actual full offline suite returned **468 passed,
177 skipped, 0 failed** (27.61 seconds). This reproduces the owner's current
post-cleanup baseline. The old 514-test result included the subsequently retired
automation state: [cleanup PR #18](https://github.com/Vivek-k24/Stark_T2SQL/pull/18)
removed automation source/tests and merged at the supplied integration baseline.
The 46-pass historical difference is not an R04 regression or a reason to restore
automatic orchestration.

## 2. Changes and rationale

| Approved file | Change |
| --- | --- |
| `semantic/catalog.yaml` | Version 1.1; four monetary metrics, complete join/column/grain/time/null metadata; third headcount interpretation. |
| `src/stark_t2sql/semantic/resolver.py` | Evaluate ambiguity among role-visible targets; keep original-vocabulary longest matching; no empty clarification options. |
| `src/stark_t2sql/semantic/entitlements.py` | Correct the resolver/projection contract documentation. Existing exact-column/scope checks and sales I-01 guard remain intact. |
| `src/stark_t2sql/semantic/metrics.py` | Central explicit-date check; typed omission/invalid-date errors; complete direct/CAST parameter binding and residual-token rejection. |
| `src/stark_t2sql/context/semantic_filter.py` | Require the business date, bind all SQL/temporal fields, emit the explicit date in every serialized role block and reject remaining raw date tokens. |
| `src/stark_t2sql/context/builder.py` | Reject unbound date tokens in directly constructed compiled semantic context before prompt assembly. Existing mode capability checks are preserved. |
| `tests/conftest.py` | Offline DDL-derived structural snapshot, independently cross-checked against the frozen generator's column AST; remove the unrelated parser-review dependency from trusted catalog loading. |
| `tests/test_semantic_contracts.py` | Role/lineage/ambiguity/hidden-intent/date regressions; update the previously skipped drift assertion to expect its actual fail-closed configuration error. |
| `tests/test_context_contracts.py` | Required date, bound serialization, actual immutable-template prompt, deterministic hashes, minimal role DDL and offline snapshot regressions. |
| `tests/test_pipeline_contracts.py` | Make the mocked clarification fixture answerable and assert its options. |
| `tests/test_adversarial_semantic_routing.py` | Multi-persona N2/N5/N6 routing, genuine clarification short circuit and UNCONTROLLED isolation, with external service/capability boundaries explicitly mocked. |
| `Codex_R04_Work_Log.md` | This chronological implementation, test and handoff record. |

### R04-F1: unauthorized intent versus ambiguity

Longest phrase matching still uses the original governed lexicon. This matters:
Sales asking for **active headcount** must not fall back to the shorter visible
**headcount** ambiguity or a convenient employee-count metric. Each matched
target set is then intersected with actual visible concepts. Multiple remaining
meanings ask for clarification; zero remaining meanings assert no interpretation
and proceed to the later security layers. A query containing only unavailable
concepts returns RESOLVED with `concept_ids=()` and no clarification.

`resolve_term` follows the same entitlement rule. An unknown explicitly requested
term offers the available vocabulary, rather than an empty choice list. The
clarification helper never emits a zero-option clarification. No grant, RLS or
SQL-guard permission is conferred by semantic resolution.

### R04-F2: monetary contracts

| Metric | Grain | Expression / join path |
| --- | --- | --- |
| `gross_pay` | payroll result | `payroll_results.gross_pay`; `result_run` |
| `net_pay` | payroll result | `payroll_results.net_pay`; `result_run` |
| `total_earnings_amount` | payroll run | `COALESCE(SUM(payroll_earnings.amount), 0)`; `result_run`, `earning_result` |
| `total_deductions_amount` | payroll run | `COALESCE(SUM(payroll_deductions.amount), 0)`; `result_run`, `deduction_result` |

All use posted/closed status inclusion, `pay_date_as_of`, USD and ALL scope. The
existing backing-data entitlement projection permits them only to Payroll;
HR BP and Sales have no payroll table grants. No access policy is expanded.
Every expression, grain, join endpoint and temporal column passes the existing
catalog lineage contract against the offline structural snapshot. Negative tests
remove amount/status/date access and join paths to verify they cannot silently
remain eligible or valid.

The design's SUM expressions are wrapped in COALESCE to implement its explicit
zero-for-empty-line null semantics. Source amount columns are NOT NULL. The
metadata distinguishes a qualifying run with no lines from a nonexistent run,
retains signed corrections and zero/negative net pay, and explains the needed
outer-join/per-run aggregation semantics. Earning and deduction lines must be
aggregated independently before combining totals to avoid fan-out. No header
or result totals are substituted; no fixture equality or generated-query
correctness is claimed from this metadata contract alone.

### R04-F3: verified headcount reconciliation

The review's summary/two-option narrative conflicts with its mandatory F3
directive and T04 three-option expectation. FR-7.3/7.11, the real catalog and
actual grants resolve this without changing permissions:

| Role/persona | Exact clarification options for `headcount` |
| --- | --- |
| Payroll | Active headcount; Direct report row count; Visible employee row count |
| HR BP #1 and #2 | Active headcount; Direct report row count; Visible employee row count |
| Sales Manager | Direct report row count; Visible employee row count |

Payroll and HR BP can read both `employee_id` and `manager_id`, and the existing
direct-report metric admits their ALL/ASSIGNED_DIVISIONS scopes. Their grants
also contain the canonical active-headcount columns. Sales has precisely five
employee columns and lacks those active-headcount dependencies; I-01 remains
open and its explicit deny guard remains unchanged. Direct-report metadata
retains its existing visible-row scope semantics; no new principal filter or
live count is inferred. A narrowed HR-column test also removes the direct-report
option when `manager_id` is unavailable, proving the options follow lineage,
rather than a hardcoded role-name list.

### R04-F4: explicit business dates

Serialization, filtered/full semantic compilation and metric compilation require
an actual Python `date`. Omission, None, text, datetime, integer and Boolean
values raise `InvalidRequestError`. A private missing-value sentinel exists
solely to report omitted arguments with that typed error; it supplies no default
date and never reaches binding. No wall-clock or inferred fixture date is used.

Entity/metric filters, metric expressions and temporal predicates/selections
are bound before serialization. Both `:as_of_date` and CAST forms become typed
`DATE 'YYYY-MM-DD'` literals; spaced/lowercase CAST syntax is covered too. Every
serialized block includes its explicit business date, including Sales blocks
that cannot contain active-headcount filters. Residual tokens in other metadata
or directly constructed compiled context fail closed before prompt construction.
Tests render the actual immutable R01 template with the existing owner contract
at two supplied dates and assert no raw temporal parameter reaches its metadata.
User questions remain unchanged; no template/prompt-builder source is edited.

### R04-F5/F6: modes, offline metadata and evidence boundaries

FULL still compiles role-filtered physical and semantic metadata. The existing
UNCONTROLLED per-request path already skipped resolution and semantic compilation;
tests now prove that these calls cannot occur and that the original `schema.sql`
bytes, empty semantic block and absent semantic-catalog fingerprint reach v1.
Pipeline/orchestrator production source did not require a change. Only test
capability issuance/consumption is mocked; this is not a real clone audit.

The offline snapshot parses the checked-in PostgreSQL DDL for ordered columns,
types, nullability, primary/unique constraints and foreign keys/actions. It
cross-checks column declarations via `ast.literal_eval` on `seed_data.TABLE_COLUMNS`,
without executing SQL, importing/generating fixture rows or promoting partial
unique indexes into unconditional uniqueness. Explicit external schema input
still takes precedence and retains its missing-file/validation behavior.
Trusted catalog fragment parsing does not require or manufacture an approval
for the generated-SQL validator; that external review remains a real prerequisite.

The first offline-fixture run exposed **13 passed, 1 failed**: a previously
skipped drift test expected returned catalog issues when removing `hire_date`
actually triggers policy/schema `ConfigurationError` first. Its assertion now
checks that existing fail-closed behavior. No frozen policy/catalog validator
implementation was changed to accommodate the test.

## 3. Actual verification

Used the existing isolated Python 3.12.10 environment with pytest 8.3.5 and
sqlglot 30.22.0. No dependency, model, database or service installation occurred.
Commands, from the clean R04 checkout:

```powershell
$env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
$env:PYTHONPATH='src;.'
& $python -m pytest tests/test_semantic_contracts.py tests/test_context_contracts.py tests/test_pipeline_contracts.py tests/test_adversarial_semantic_routing.py -q -ra
& $python -m pytest -q -ra
```

| Actual run | Passed | Failed | Skipped | Exit | Duration |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full baseline before edits | 468 | 0 | 177 | 0 | 27.61s |
| Final focused semantic/context/pipeline/adversarial | **157** | **0** | **0** | **0** | 6.31s |
| Final full offline suite | **612** | **0** | **162** | **0** | 26.73s |

An earlier growing focused set also passed 148 tests before the final lineage
and partial-visibility cases were added. Final counts above are actual executions.
Relative to the verified baseline, 129 new collected cases pass and 15 existing
source-only cases are enabled: the review's 13 semantic/context skips plus one
schema and one benchmark contract sharing the same metadata fixture. No prior
passing case regressed.

Remaining **162** skips are explicit prerequisites: 137 parser-review-dependent
cases (including runner coverage), 16 wall-clock-review cases, one
adversarial scope/canary source, one independent reference review, six disabled
database integration cases and one separately opted-in live reset case. The
existing pytest-asyncio fixture-loop-scope deprecation warning remains unrelated
to R04. No external approval file, canary, reference result or measurement was
invented to reduce these skips.

Acceptance mapping: T01-T03 exact role visibility; T04-T05 role/column-derived
headcount options; T06-T09 real resolver/context with **mocked** generator,
validator rejection or SQLSTATE 42501 executor response; T10 typed date and
actual-template prompt regressions; T11 UNCONTROLLED context isolation; T12
the actual 612/162 full run against the actual 468/177 baseline.

## 4. Scope, limitations and handoff

Only the twelve approved paths listed above are changed. Frozen SHA-256 values
remain unchanged:

| Asset | SHA-256 |
| --- | --- |
| `schema.sql` | `f1b5976a08ebeeeb085d7095ddf25edfb06a261b2ebfe9f0653cb3a8b5128bf3` |
| `seed_data.py` | `ee9fd0a9965b51f6289290caa211460a65f9b2c38728bf99bb1133265d0561bf` |
| `fixture_manifest.json` | `fb15e54afc4b72e02076614fec108049595ab1879feeabe9871f131fccb2640e` |
| `fixture_pg_dump.sql` | `859aa6badb797159f846d0870e377e3aade04049adc4174d2cd7dd6a98dd4fc4` |
| `src/inference/prompt_template.txt` | `67d1c6d265202e6bf6abcd1393203e84b92bf9df03207015679339fe807ad6b6` |

No DB policy/executor, held-out evaluation source, historical review/log, AGENTS,
FRD, orchestration, UI/progress or R05-R09 implementation file was modified.
No PostgreSQL/SQLCoder/real validator/security-enforcement acceptance, historical
dataset fidelity or measured resource result is established by these offline
contracts. N2/N5/N6 tests use public prepared attack families and fake downstream
responses; they are not scored adversarial cases or evidence of real model
behavior. Authorized Payroll ambiguities still legitimately clarify.

The implementation and this log will be committed/pushed on the existing shared
branch and published in exactly one draft PR against the integration branch;
actual publication references will be appended after GitHub confirms them.

**STOP for the owner's separate Antigravity instruction.** Do not launch a
reviewer, merge, start R05 or restore automatic orchestration. Antigravity's
later independent verification must append to the existing R04 review and
update both the repository E0 HTML and the distinct owner browser copy after
protecting local edits and checking the actual copy/hash. **LOCAL_UI_NOT_UPDATED
by Codex:** neither HTML copy nor progress JSON is in this implementation's
write scope. Their later update is an explicit reviewer responsibility.
