# Codex R06 work log

Date: 2026-10-15. Gate: Reference Oracle Security, Comparator Accuracy and Per-Table Scope.

## Authority and workspace

- Owner request, [Issue #8](https://github.com/Vivek-k24/Stark_T2SQL/issues/8), FRD 1.8, `AGENTS.md` and the complete `Antigravity_R06_Review.md` were read before implementation.
- Approved design commit: `3fd4d7986c4fc15e1215cc886946d008271008b4`.
- Integration baseline: `4e50ff9b0087014738dd88b46b457c949f3830d0`, the owner's R05 merge from [PR #20](https://github.com/Vivek-k24/Stark_T2SQL/pull/20).
- Used the existing shared branch `codex/r06-remediation` in a clean clone at `H:\STARK_T2SQL_R06`. No new branch was created.
- Preserved the original `H:\STARK T2SQL` checkout's uncommitted `Antigravity_Design_Review.md` and `Antigravity_R06_Review.md` edits. They were neither overwritten nor included in the implementation commit.
- Existing environment: `H:\STARK_T2SQL_R02_ENV\Scripts\python.exe`, Python **3.12.10**, pytest **8.3.5**, SQLGlot **30.22.0**. No software installation or database operation occurred.

## Chronological implementation

1. Read the review, gate issue including the owner's manual handoff, FRD and current evaluation/reference/comparator/ablation implementation. Verified local and remote design/baseline SHAs. Inspected the actual installed SQLGlot lexical-scope and qualification implementations.
2. Ran the full offline baseline before implementation: **1,112 passed, 58 skipped, zero failed**. This matches Antigravity's independently reported R05 baseline. The existing progress test passes in this R06 baseline; no UI change was necessary or made.
3. Corrected reference scope validation to use parsed physical tables and exact declared lineage. Removed the unconditional employees scope from allowed reference scopes. Enforced the actual table-specific scope and the exact principal marker for controlled references using restricted RLS tables.
4. Added a mandatory owner-evidence boundary for every administrative controlled reference. A scope-review string or principal marker alone cannot authorize an admin query. The new `ScopeReviewStore` requires an existing local record whose exact bytes occur in a separately owner-approved SHA-256 set and whose bindings match the complete immutable review and access matrix. No owner record, approved digest set, signature or default production authorization was fabricated.
5. Added exact physical column-lineage inspection using actual schema metadata. Stars expand to actual columns, and physical reads in filters, joins, nested queries and CTE definitions are checked against declared column lineage and persona entitlements. Metadata analysis never supplies executable SQL; controlled reference SQL still passes the existing reviewed harness safety gate before administrative execution.
6. Replaced direct ablation's leave-balances substring test and employees fallback with lexical physical-relation scope derivation. Comments, literals, aliases and CTE names cannot impersonate physical tables. Unknown/ambiguous relations and conflicting scopes fail closed. Unattributable answered rows are discarded while preserving the actual executed-SQL record. Database-denial attribution is retained without inventing a successful row scope.
7. Preserved comparator multiset, scalar typing, rounding and SCOPED_RESULT row-count behavior. Fixed specific projection-binding gaps found during inspection: missing actual candidate hashes could evade an explicit pin; raw cursor comparisons could lack reference SQL hashes; case folding, competing display/canonical aliases and mixed metadata could create an unsafe mapping. Mapping now requires exact, unique, bijective correspondence. Dynamic candidate SQL remains supported without prehashing.
8. Added focused reference, comparator and direct-harness tests. Conditional reference tests explicitly mock evidence approval, fixture/policy reads, clock lint and database operations; they run the actual safety reviewer and lineage analyzer, but establish no live RLS equivalence or human sign-off.
9. Ran the prescribed focused suite: **203 passed, 1 skipped, zero failed**. The expanded R06 suite including direct-harness scope tests passed **245 tests, 1 skipped, zero failed**. Ran the final full offline suite: **1,319 passed, 58 skipped, zero failed**. All baseline tests remain passing; 207 new cases pass.
10. Checked changed-file scope, frozen Git blob identities and SHA-256 values. Publication details are recorded after the actual commit/push and draft PR creation below.

## Changed files and design findings

| File | Finding and purpose |
| --- | --- |
| `src/stark_t2sql/evaluation/reference.py` | R06-F1/F2: bound owner evidence store; complete review fingerprint; exact persona/date/mode/fixture/policy checks; parsed relation and column lineage; table-specific reference scope; restricted principal slots; mandatory existing safety reviewer. |
| `src/stark_t2sql/evaluation/ablation.py` | R06-F2: actual executed-SQL relation scope; removal of substring/default-employee inference; preserve execution evidence and DB attribution on metadata failure. Also corrected its stale NO_VALIDATOR docstring. |
| `src/stark_t2sql/evaluation/comparator.py` | R06-F3: exact/bijective raw and mixed column correspondence, reference SQL binding, strict explicit candidate pins and safe duplicate-label rules. Existing numerical and multiset logic retained. |
| `tests/test_reference_contracts.py` | R06-F1/F2/F4: binding failures, no-admin-access failures, actual parser lineage, role-specific scopes, conditional mocked reference protocol, explicit TEST-ONLY evidence rejection, immutable unit metadata and retained external-review prerequisite. |
| `tests/test_comparator_contracts.py` | R06-F3: dynamic/fixed mappings, wrong/missing hashes, ambiguous/duplicate/unknown aliases, typed cells, numerical boundaries, duplicates, row order and scoped row counts. |
| `tests/test_r06_ablation_scope.py` | R06-F2: actual direct-harness orchestration with mocked executor outputs across all four modes, persona/table scopes, metadata failures and preserved DB denial. |
| `Codex_R06_Work_Log.md` | Implementation, evidence, limitations and handoff record. |

No `tests/conftest.py` change or checked-in reference-review fixture was needed. Existing frozen reference-review inputs remain required.

## Reconciliations with the approved design

The owner request strengthens the review in three areas:

- **Scope evidence:** the review proposes a non-empty scope attestation plus principal marker. R06 requires a real file pinned by a separate trusted owner-approved digest set. Merely naming a file, constructing a `ReferenceReview`, declaring review text or including a marker in a comment/string/tautology cannot authorize administrative reference execution.
- **Relations:** the review suggests word-boundary matching and an employees fallback. R06 uses SQLGlot 30.22.0 lexical sources instead. A parsed relation-free SELECT has no physical row restriction to attribute; unknown/unbound relations do not receive that treatment.
- **Offline review:** R06-F4/T12 proposes replacing the external input skip with a typed fixture. The owner expressly forbids manufacturing human scope review. No genuine record was supplied, so the real external-review test remains skipped. Separate TEST-ONLY immutability and rejection tests execute offline; they do not satisfy the real human-review prerequisite.

## Scope and reference trust contract

`ScopeReviewStore` is optional in construction so absence can be reported, but its absence prevents every controlled administrative reference from becoming available. Trusted future composition must supply the private record root and an immutable set of independently owner-approved **file-byte** SHA-256 values. Digests must never be obtained from untrusted questions, model output or the file being approved at runtime.

The relative `ReferenceReview.scope_review_reference` must resolve to an existing file inside that root. Reads are bounded to 1 MiB; duplicate JSON keys, unknown fields, unknown/test-only record kinds, digest drift and binding mismatch fail closed. The record has exactly these fields:

- `kind`: `OWNER_APPROVED_REFERENCE_SCOPE_V1`.
- `review_binding_sha256`: `ReferenceReview.binding_sha256`, covering every review field including SQL template hash, case, mode, persona, principal, date, projection, scope, table/column lineage, fixture, policy state and literal markers.
- `matrix_sha256`: actual access-matrix hash.
- `reviewer` and `scope_analysis`: actual independent reviewer and predicate analysis, approved as part of the pinned file bytes.

This is an explicit trusted-configuration boundary, not a digital signature system or a computational proof that a human review happened. Genuine records and owner-approved digests are **currently unavailable**. No record with an owner-approval claim was generated. The unit TEST_ONLY record is rejected even when a unit test pins its digest. Tests which stub `ScopeReviewStore.require` are labeled conditional mocks, never authorization evidence.

The typed `ReferenceReview` constructor retains its existing fields; `binding_sha256` is a new read-only property. R07 must preserve this boundary when coordinating future `reference.py` changes and composition. No R07 case-loader, holdout or runner implementation was changed or started.

Parsed reference business data lineage must include every physical table and every column read, not just projected columns. No implicit hidden-table exception is granted for predicate/control reads. A reference that directly reads persona-forbidden `hr_bp_assignments` or payroll columns is unavailable; R06 does not invent an alternative administrative permission. Independently authored valid scope predicates still need actual owner review and later PostgreSQL verification.

Table behavior follows the real matrix:

| Persona / physical relation | Controlled scope |
| --- | --- |
| Payroll / employees or leave_balances | ALL |
| HR BP / employees | ASSIGNED_DIVISIONS |
| Sales Manager / employees | DIRECT_REPORTS |
| HR BP / leave_balances | VIA_EMPLOYEES |
| Any persona / departments and other permitted unrestricted reference tables | ALL |
| HR BP / employees plus departments | ASSIGNED_DIVISIONS |
| HR BP / employees plus leave_balances | VIA_EMPLOYEES, the known visible-employee policy chain |
| Persona-forbidden, unknown or conflicting relations | Unavailable; no guessed scope |

UNCONTROLLED retains the existing isolated baseline executor and ALL semantics for known fixture relations. It does not acquire an administrative reference connection or business entitlement fallback. The mandatory baseline safety gate remains unchanged.

For dynamic raw cursor comparison, the fixed reviewed reference SQL hash remains necessary; a candidate prehash is unnecessary for unique unambiguous labels. When an exact candidate SQL hash is explicitly approved, missing actual hashes now reject as well as mismatches. Duplicate raw cursor display labels require a stable explicit slot mapping **and** an exact candidate SQL binding; dynamic duplicate labels cannot silently inherit a mapping. Comparisons do not infer semantics from row contents, and equal observed results are not proof of general SQL equivalence.

## Acceptance criteria and evidence limits

| Criterion | Actual evidence |
| --- | --- |
| R06-T01 | Context mismatch tests reject wrong case/mode/persona/principal/date/template before source access; complete binding digest changes across security fields. |
| R06-T02 | HR BP/Sales global row-scope claims reject in FULL, NO_VALIDATOR and NO_PROMPT_FILTER; genuine evidence absence blocks administrative reads. |
| R06-T03 | Missing/wrong principal slots reject restricted employee and leave references. Marker presence alone remains insufficient. |
| R06-T04 | Direct-harness tests cover departments, employees, leave, joins, misleading text, actual executed SQL and all modes. Execution is mocked. |
| R06-T05 | Reference metadata and conditional mocked authority tests distinguish departments ALL from employee restriction and reject borrowed/wrong scope. |
| R06-T06 | Row order ignored; duplicate multiplicity preserved. |
| R06-T07 | NULL/zero, bool/int, int/decimal, date/datetime, exact timezone representation, HALF_UP rounding and non-finite rejection verified. |
| R06-T08 | Unique dynamic cursor labels and explicit mappings work with fixed reference hashes and no candidate prehash. |
| R06-T09 | Duplicate, unknown, competing and case-changed aliases fail; mixed explicit metadata is not discarded. Existing swapped/different-meaning values fail. |
| R06-T10 | Non-bijections, dimension/index errors, empty/duplicate reference identities and missing mapping provenance reject. |
| R06-T11 | SCOPED_RESULT uses reference row counts; empty passes only against empty. These are hand-authored operands, not persona data. |
| R06-T12 | **Real prerequisite retained:** `STARK_TEST_REFERENCE_REVIEW_PATH` absent. TEST-ONLY immutability/rejection tests pass; no fabricated owner review replaces the skip. |

## Actual commands and results

Working directory `H:\STARK_T2SQL_R06`:

```powershell
$env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
$env:PYTHONPATH='src;.'
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest tests/test_reference_contracts.py tests/test_comparator_contracts.py -q -ra
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest tests/test_reference_contracts.py tests/test_comparator_contracts.py tests/test_r06_ablation_scope.py -q -ra
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest -q -ra
```

| Run | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| Baseline full offline | 1,112 | 0 | 58 |
| Final prescribed reference/comparator suite | 203 | 0 | 1 |
| Expanded R06 suite with direct-harness tests | 245 | 0 | 1 |
| Final full offline | 1,319 | 0 | 58 |

Baseline full duration: 38.64 seconds. Final full duration: 34.02 seconds. Earlier development focused runs passed 112, 207 and 228 tests respectively with the same single prerequisite skip, as coverage was added. No failed pytest run occurred during R06 implementation.

The 58 full-suite skips remain: 32 excluded SQLGlot representation contracts, 16 missing wall-clock-review cases, one missing adversarial-scope input, one missing genuine reference-review input, six disabled database-integration cases, one disabled direct-composition DB case and one disabled live seed/reset case. The inherited pytest-asyncio unset loop-scope deprecation warning remains unchanged.

## Frozen assets and primary references

All frozen files below matched the approved design Git blobs. Actual SHA-256 values:

| Asset | SHA-256 |
| --- | --- |
| `schema.sql` | `f1b5976a08ebeeeb085d7095ddf25edfb06a261b2ebfe9f0653cb3a8b5128bf3` |
| `seed_data.py` | `ee9fd0a9965b51f6289290caa211460a65f9b2c38728bf99bb1133265d0561bf` |
| `fixture_manifest.json` | `fb15e54afc4b72e02076614fec108049595ab1879feeabe9871f131fccb2640e` |
| `fixture_pg_dump.sql` | `859aa6badb797159f846d0870e377e3aade04049adc4174d2cd7dd6a98dd4fc4` |
| SQLCoder prompt template | `67d1c6d265202e6bf6abcd1393203e84b92bf9df03207015679339fe807ad6b6` |
| Access matrix | `85efd46ce237aea0dab8aac57af81c667320508ef841dbf79c5f2eebfefd42e9` |
| Semantic catalog | `2eb213d793819e51bbae100a842485adafcde16ea6026fcb918247e652b447ed` |
| `AGENTS.md` | `a1d589b07bc2237f2932faace3fd23c7cd7ce4f789636ff59bf9424c703dc390` |
| `ops/progress.json` | `9e4b461c6151d2a78f85eddbe4454ae7f0836165dbc957082bbdf4a5e1848e3a` |
| Canonical E0 HTML | `7cd526d2ba795b5928a19ff3cb28b262d259a9a15ee3b0758a690601d29471fd` |
| `pyproject.toml` | `a28dcde9202d86b19548cf883c9f4765538b89c94f2672e9ed9349d6c0ea6190` |

Primary references consulted: [PostgreSQL 16 row-security behavior](https://www.postgresql.org/docs/16/ddl-rowsecurity.html) explains the administrator/BYPASSRLS limitation; [SQLGlot v30.22.0 lexical scope implementation](https://github.com/tobymao/sqlglot/blob/v30.22.0/sqlglot/optimizer/scope.py) and the actual installed qualification source support relation inspection; [Python 3.12 decimal rounding](https://docs.python.org/3.12/library/decimal.html#decimal.ROUND_HALF_UP) supports the unchanged numerical contract. Documentation is not live database evidence.

## Remaining prerequisites and owner handoff

Missing: genuine independent reference-review payload, owner-approved scope-evidence files and separately approved file hashes, production-approved parser and wall-clock review composition, and separately authorized disposable PostgreSQL clone/persona execution. Actual fixture/RLS equivalence, ACL/column denial and admin-vs-persona result equivalence require later genuine PostgreSQL verification. SQLCoder/end-to-end acceptance was not attempted. Mocked rows, flags, hashes and SQLSTATE values are never presented as live evidence.

No schema, fixture, policy, RLS/grant/executor, template, catalog, historical review, UI/progress or unrelated R07–R09 source was changed. No merge, main push, automatic Antigravity start, orchestration or R07 work occurred. Stop for the owner's manual Antigravity verification instruction. At that later phase Antigravity must verify the R05 merge, update manual progress, regenerate canonical HTML and protect/compare/synchronize the actual browser copy and legacy copy if used. Codex has not updated either browser file.
