# Antigravity Gate R05 Design & Security Review
**Project:** STARK T2SQL  
**Gate:** R05 — SQL Validator Safety, AST Entitlement Enforcement, and Ablation Review Profiles  
**Tracking Issue:** [GitHub Issue #7](https://github.com/Vivek-k24/Stark_T2SQL/issues/7)  
**Integration Baseline Commit:** `0e7f643a3577d32ab4e579c4a66ef6666e6ab5fe`  
**Shared Working Branch:** `codex/r05-remediation`  
**Date:** 2026-10-15  
**Reviewer:** Antigravity (Independent Architecture & Security Reviewer)  
**Verdict:** **APPROVE** (Design Approval for Codex Implementation)

---

## 1. Executive Summary

Antigravity has performed an independent architecture, security, and parser-contract review of Gate R05 for the STARK T2SQL system in accordance with `AGENTS.md`, FRD 1.8 (Sections 5, 6, 12, and 13), and GitHub Issue #7.

The primary security objective of Gate R05 is to establish a rigorous, fail-closed, application-level SQL Validator (`ReviewedSQLValidator`) and a mandatory execution harness safety reviewer (`HarnessSafetyReviewer`) based on an audited abstract syntax tree (AST) parser (`sqlglot 30.22.0`). This layer operates as **defense-in-depth**: it intercepts and rejects non-SELECT statements (DDL/DML), multi-statement chaining, session-altering commands, unauthorized system catalog queries, unreviewed functions, and out-of-entitlement table accesses before any generated SQL reaches the PostgreSQL connection layer.

Crucially, **the SQL Validator is an application-level guard and does not replace PostgreSQL database security**. As mandated by FR-6 and verified during Gate R03, PostgreSQL table-level grants, column-level ACLs, and Row-Level Security (RLS) policies serve as the immutable, definitive security boundary. Live PostgreSQL validation is explicitly deferred to Gate R09.

Our technical audit of the codebase identified key gaps in the current draft implementation:
1. **The `Count(big_int=True)` Gap:** In `sqlglot 30.22.0`, parsing PostgreSQL `COUNT(...)` unconditionally sets `big_int=True`. The current draft in `function_policy.py` rejects any presence of `big_int`, causing valid queries like `SELECT COUNT(*)`, `SELECT COUNT(DISTINCT ...)`, and `SELECT COUNT(*) FILTER (...)` to fail closed.
2. **Operator Incompleteness for Negated Forms:** In `sqlglot 30.22.0`, `IS NOT NULL`, `NOT LIKE`, and `NOT ILIKE` produce AST nodes (`Is`, `Like`, `ILike`) containing `negate=True`. These classes omit `negate` from their `argument_keys` and `scalar_keys`, causing legitimate queries in `GOOD_SQL` to be rejected.
3. **The 137 Skipped Tests & Missing Review Approval Profile:** 136 tests in `test_validator_contracts.py` and 1 test in `test_runner_contracts.py` currently skip due to the absence of an authoritative, versioned `ParserReviewApproval` profile asset.

With the architectural corrections detailed herein, the design is robust, secure, and ready for Codex implementation. Antigravity issues an **APPROVE** verdict for this design phase.

---

## 2. Architectural Findings & Detailed Technical Analysis

### Finding R05-F1: Parser Layout Compatibility & The `Count(big_int=True)` Gap
- **Component Audited:** `src/stark_t2sql/security/function_policy.py` (`_arguments`), `src/stark_t2sql/security/validator.py` (`_ASTReview._walk_all`).
- **Technical Analysis:**
  In PostgreSQL, `COUNT(...)` returns an 8-byte integer (`int8` / `bigint`) by definition. Consequently, the `sqlglot 30.22.0` PostgreSQL dialect parser (`sqlglot.dialects.postgres.Postgres.Parser`) parses `COUNT(...)` via:
  ```python
  "COUNT": lambda args: exp.Count(this=seq_get(args, 0), expressions=args[1:], big_int=True)
  ```
  This unconditionally sets `big_int=True` on `exp.Count` AST instances.
  However, in `src/stark_t2sql/security/function_policy.py` (lines 217–218):
  ```python
  if _present(args.get("big_int")):
      raise FunctionPolicyViolation("A dialect-specific aggregate flag is unreviewed.")
  ```
  Furthermore, `_ASTReview._walk_all` in `src/stark_t2sql/security/validator.py` (lines 476–479) verifies:
  ```python
  for key, value in node.args.items():
      if _present(value) and not isinstance(value, (self.expression_class, list, tuple)):
          if not (rule.parser_class == "Anonymous" and key == "this" and isinstance(value, str)):
              raise _Rejected(ValidationRuleCode.FUNCTION, "A callable argument has unreviewed scalar content.")
  ```
  Because `big_int` is a boolean (`True`), `_walk_all` rejects it as unreviewed scalar content.
  Combined, these two checks reject **all** `COUNT` calls parsed under PostgreSQL dialect in `sqlglot 30.22.0`, failing `GOOD_SQL` contract tests (`SELECT COUNT(DISTINCT employee_id) FROM employees` and `SELECT COUNT(*) FILTER (WHERE manager_id IS NOT NULL) FROM employees`).
- **Required Remediation:**
  1. In `function_policy.py` `_arguments()`, allow `big_int` when `rule.sql_name == "count"` and `isinstance(args.get("big_int"), bool)`:
     ```python
     if rule.sql_name != "count" and _present(args.get("big_int")):
         raise FunctionPolicyViolation("A dialect-specific aggregate flag is unreviewed.")
     if rule.sql_name == "count" and args.get("big_int") is not None and type(args.get("big_int")) is not bool:
         raise FunctionPolicyViolation("A dialect-specific aggregate flag is unreviewed.")
     ```
  2. In `validator.py` `_ASTReview._walk_all()`, permit `big_int` boolean on `Count`:
     ```python
     if not (rule.parser_class == "Anonymous" and key == "this" and isinstance(value, str)):
         if not (rule.sql_name == "count" and key == "big_int" and isinstance(value, bool)):
             raise _Rejected(ValidationRuleCode.FUNCTION, "A callable argument has unreviewed scalar content.")
     ```

---

### Finding R05-F2: Operator Incompleteness for Negated Forms (`negate` on `Is`, `Like`, `ILike`)
- **Component Audited:** `src/stark_t2sql/security/validator.py` (`_SHAPES`, `PROPOSED_NODE_SHAPES`).
- **Technical Analysis:**
  In `sqlglot 30.22.0`, PostgreSQL expressions of the form `x IS NOT NULL`, `x NOT LIKE 'pattern'`, and `x NOT ILIKE 'pattern'` are parsed into AST nodes `Is`, `Like`, and `ILike` with the argument `negate=True`.
  Currently, `validator.py` defines these node shapes as:
  ```python
  NodeShape("Is", frozenset({"this", "expression"})),
  NodeShape("Like", frozenset({"this", "expression"})),
  NodeShape("ILike", frozenset({"this", "expression"})),
  ```
  Neither `negate` nor scalar keys are defined for these shapes. When `manager_id IS NOT NULL` is encountered (as in `GOOD_SQL[5]` `SELECT COUNT(*) FILTER (WHERE manager_id IS NOT NULL) FROM employees`), the validator rejects the query with:
  ```
  V-UNSUPPORTED-ARGUMENT: Unreviewed arguments on Is: ['negate'].
  ```
- **Required Remediation:**
  Update `_SHAPES` in `src/stark_t2sql/security/validator.py` so that `Is`, `Like`, and `ILike` include `negate` in both `argument_keys` and `scalar_keys`:
  ```python
  NodeShape("Is", frozenset({"this", "expression", "negate"}), frozenset({"negate"})),
  NodeShape("Like", frozenset({"this", "expression", "negate"}), frozenset({"negate"})),
  NodeShape("ILike", frozenset({"this", "expression", "negate"}), frozenset({"negate"})),
  ```
  Ensure `_guard_structure()` validates that `args.get("negate")` is strictly a boolean if present (`type(args["negate"]) is bool`).

---

### Finding R05-F3: Resolution of the 137 Skipped Tests & Authoritative Parser Review Approval Profile
- **Component Audited:** `tests/test_validator_contracts.py` (136 skips), `tests/test_runner_contracts.py` (1 skip), `tests/conftest.py` (`parser_approval`).
- **Technical Analysis:**
  Currently, 137 contract tests skip because `tests/conftest.py` calls `required_input("STARK_TEST_PARSER_REVIEW_PATH", project_root)`. When this environment variable is unset, `parser_approval` skips all tests requiring it.
  `ParserReviewApproval` requires:
  - `sqlglot_version`: `"30.22.0"`
  - `validator_revision`: `"fr5-validator-draft-2"`
  - `function_policy_revision`: `"fr5-function-draft-2"`
  - `approved_node_shapes`: `frozenset[str]` (subset of `PROPOSED_NODE_SHAPES.keys()`, must include `"Select"`)
  - `approved_function_rule_ids`: `frozenset[str]` (subset of `RULES_BY_ID.keys()`)
  - `review_reference`: Non-empty review audit string (e.g., `"STARK-R05-SQLGLOT-30.22.0-REVIEW-20261015"`)

  An exhaustive audit of the 60 node shapes and 43 proposed function rules against `sqlglot 30.22.0` revealed:
  1. **Node Shapes (60 total):** All 60 classes defined in `PROPOSED_NODE_SHAPES` exist directly in `sqlglot.expressions` and are valid AST representations.
  2. **Function Rules (43 total):**
     - **36 Observed PostgreSQL Rules:**
       - Direct classes: `count-known-v1`, `sum-known-v1`, `avg-known-v1`, `min-known-v1`, `max-known-v1`, `lower-known-v1`, `upper-known-v1`, `abs-known-v1`, `round-known-v1`, `coalesce-known-v1`, `nullif-known-v1`, `timestamp-trunc-known-v1`, `row-number-known-v1`, `rank-known-v1`, `dense-rank-known-v1`, `percentile-cont-known-v1`, `cast-special-v1`, `extract-special-v1`, `current-date-known-v1`, `current-timestamp-known-v1`, `current-time-known-v1`, `localtimestamp-known-v1`.
       - Anonymous classes: `count-anonymous-v1`, `sum-anonymous-v1`, `avg-anonymous-v1`, `min-anonymous-v1`, `max-anonymous-v1`, `lower-anonymous-v1`, `date-trunc-anonymous-v1`, `percentile-cont-anonymous-v1`, `now-anonymous-v1`, `age-anonymous-v1`, `statement-timestamp-anonymous-v1`, `transaction-timestamp-anonymous-v1`, `clock-timestamp-anonymous-v1`, `timeofday-anonymous-v1`.
     - **1 Unobserved Layout in PostgreSQL Dialect (`date-trunc-known-v1`):** `sqlglot.parse(..., read="postgres")` maps `DATE_TRUNC` to `TimestampTrunc` (handled by `timestamp-trunc-known-v1`). The standalone `DateTrunc` class is not produced by the Postgres dialect parser.
     - **6 Unobserved Class Names (`*-known-v1`):** `localtimestamp-camel-known-v1` (`LocalTimestamp`), `age-known-v1` (`Age`), `statement-timestamp-known-v1` (`StatementTimestamp`), `transaction-timestamp-known-v1` (`TransactionTimestamp`), `clock-timestamp-known-v1` (`ClockTimestamp`), `timeofday-known-v1` (`TimeOfDay`). These classes do not exist in `sqlglot.expressions`; `sqlglot 30.22.0` parses them as `Anonymous` (or `Localtimestamp` lowercase). Admitting them in `ParserReviewApproval` would cause `ReviewedFunctionPolicy` instantiation to fail with `FunctionPolicyViolation("Reviewed parser representation is unavailable: ...")`.
- **Required Remediation:**
  1. Author and check in a canonical review approval profile asset: `src/stark_t2sql/security/profiles/sqlglot_30_22_0.json` (or `tests/fixtures/parser_approval_sqlglot_30_22_0.json`).
  2. The profile must include:
     - `sqlglot_version`: `"30.22.0"`
     - `validator_revision`: `"fr5-validator-draft-2"`
     - `function_policy_revision`: `"fr5-function-draft-2"`
     - `approved_node_shapes`: all 60 shapes in `PROPOSED_NODE_SHAPES`.
     - `approved_function_rule_ids`: the 36 observed rules listed above.
     - `review_reference`: `"STARK-R05-SQLGLOT-30.22.0-REVIEW-20261015"`.
  3. In `tests/conftest.py`, update `parser_approval` to fall back to this canonical offline profile when `STARK_TEST_PARSER_REVIEW_PATH` is not explicitly set in the environment, mirroring the offline snapshot pattern established in R04.
  4. Ensure all 136 tests in `test_validator_contracts.py` and the 1 test in `test_runner_contracts.py` execute cleanly and pass offline.

---

### Finding R05-F4: Ablation Mode Fidelity and Structural Entry Guards
- **Component Audited:** `src/stark_t2sql/security/validator.py` (`HarnessSafetyReviewer`), `src/stark_t2sql/db/executor.py` (`EvaluationExecutor`), `tests/test_execution_resources.py`.
- **Technical Analysis:**
  The evaluation harness defines three critical execution modes with distinct security behaviors:
  1. **`FULL` Mode:**
     - Enforces full semantic resolution and governed context assembly.
     - The candidate SQL undergoes both structural harness safety review AND role-based table entitlement validation (`role.tables`).
     - Only candidate queries referencing tables explicitly granted to the persona's role in `access_matrix.yaml` are admitted.
     - Executed under the persona's restricted PostgreSQL login role (`app_payroll`, `app_hr_bp`, `app_sales_mgr`) with active RLS and session identity (`app.principal_id`).
  2. **`NO_VALIDATOR` Mode:**
     - Simulates an ablation where the application-layer table entitlement validator is bypassed (`allow_all_fixture_tables=True`).
     - **CRITICAL REQUIREMENT:** Candidate queries in `NO_VALIDATOR` mode **strictly retain** `HarnessSafetyReviewer` structural entry guards. Non-SELECT statements, DDL/DML, multi-statement injection, and unreviewed functions are still blocked at the application harness.
     - Candidate queries referencing out-of-entitlement tables (e.g., Sales Manager querying `employee_compensation`) pass structural review and proceed to PostgreSQL under the caller's persona login (`app_sales_mgr`).
     - PostgreSQL engine enforces table ACLs and rejects the query with SQLSTATE `42501` (`BLOCKED_DB`).
  3. **`UNCONTROLLED` Mode:**
     - Bypasses both semantic resolver and application validator.
     - Executes under the unsegmented baseline evaluation login (`stark_eval_baseline`), demonstrating raw baseline behavior without persona scoping.
- **Verification Requirement:**
  Codex must ensure `HarnessSafetyReviewer.review_candidate()` strictly enforces `allow_all_fixture_tables=True` **only** for `NO_VALIDATOR` and `UNCONTROLLED` modes, and never bypasses structural AST/statement-entry checks in any mode.

---

### Finding R05-F5: Error Attribution and Stopping Layer Taxonomy
- **Component Audited:** `src/stark_t2sql/contracts.py` (`StoppingLayer`, `OutcomeStatus`, `ReasonCode`), `src/stark_t2sql/db/executor.py`.
- **Technical Analysis:**
  To guarantee truthful evaluation reporting and prevent regression masking, failures must be accurately attributed to the exact layer that halted execution:
  - **`HARNESS_SAFETY_STOP` (`StoppingLayer.VALIDATOR`):**
    Triggered when a candidate query violates structural harness safety entry guards (e.g., attempting `SET app.principal_id`, DDL/DML, multi-statement injection, or unreviewed functions). This stop occurs before any connection or database query can be initiated, in **all** modes (including `NO_VALIDATOR`).
  - **`BLOCKED_VALIDATOR` (`StoppingLayer.VALIDATOR`):**
    Triggered in `FULL` mode when a candidate query is structurally valid SQL but references fixture tables outside the caller's role grant (e.g., Sales Manager selecting from `employee_compensation`).
  - **`BLOCKED_DB` (`StoppingLayer.DATABASE`):**
    Triggered in `NO_VALIDATOR` mode when the candidate query passes structural validation and reaches PostgreSQL, where the database engine denies access with SQLSTATE `42501` (insufficient privilege).
- **Distinction of Test Evidence:**
  Unit tests in `tests/test_execution_resources.py` and `tests/test_validator_contracts.py` use in-memory connection mocks and simulated SQLSTATE errors. These must remain clearly documented as offline protocol tests. Live PostgreSQL database enforcement evidence is reserved for Gate R09.

---

### Finding R05-F6: Safe SELECT Support, Dangerous SQL Rejection, and AST Idempotence
- **Component Audited:** `src/stark_t2sql/security/validator.py` (`_ASTReview`, `_guard_structure`, `_parse_one`, `_decision`).
- **Technical Analysis:**
  The SQL Validator's admitted grammar and rejection mechanics were thoroughly audited:
  - **Safe SELECT Constructs Admitted:**
    - Standard projections with column identifiers and aliases (`Alias`, `TableAlias`).
    - Joins: `INNER`, `LEFT [OUTER]`, `RIGHT [OUTER]`, `FULL [OUTER]`, and `CROSS` joins.
    - Common Table Expressions (CTEs) via `WITH`: non-recursive only, with lexical scope binding. CTE names cannot shadow physical fixture tables (`ValidationRuleCode.CTE_SHADOW`).
    - Subqueries and existential checks (`EXISTS (SELECT ...)`).
    - Set operations: `UNION [ALL]`, `INTERSECT [ALL]`, `EXCEPT [ALL]`.
    - Explicit aggregate functions: `COUNT(*)`, `COUNT(DISTINCT ...)`, `SUM`, `AVG`, `MIN`, `MAX`.
    - Aggregate `FILTER (WHERE ...)` clauses.
    - Window functions (`ROW_NUMBER()`, `RANK()`, `DENSE_RANK()`) with `OVER (PARTITION BY ... ORDER BY ...)`.
    - Ordered-set aggregates: `PERCENTILE_CONT(fraction) WITHIN GROUP (ORDER BY ...)`.
    - Explicit type casts: `CAST(col AS <approved_scalar_type>)`.
    - Calendar extractions: `EXTRACT(<field> FROM <temporal_col>)`.
    - Read-clock functions: `CURRENT_DATE`, `CURRENT_TIMESTAMP`, `LOCALTIMESTAMP` (recorded by evaluation lint as `FC-WALLCLOCK`).
  - **Dangerous SQL Rejected:**
    - DML / DDL statements: `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `DROP`, `ALTER`, `TRUNCATE`, `COPY`, `DO`.
    - Statement chaining / multi-statement payloads: `SELECT 1; SET ...`.
    - Session and privilege commands: `SET ROLE`, `RESET ROLE`, `SET SESSION AUTHORIZATION`, `SET app.principal_id`, `SELECT set_config(...)`.
    - System catalog & administrative access: `pg_catalog.*`, `information_schema.*`, `pg_temp.*`, `other_schema.*`.
    - Dangerous built-ins: `pg_read_file`, `pg_sleep`, `current_setting`, `dblink`, `query_to_xml`, `RANDOM()`, `generate_series()`.
    - Table-locking clauses: `SELECT ... FOR UPDATE`, `SELECT ... INTO ...`.
  - **AST Idempotence & Normalization:**
    `ReviewedSQLValidator._decision()` enforces a strict two-pass validation:
    1. Parse raw candidate SQL -> Review AST -> Regenerate SQL via `sqlglot.to_sql(dialect="postgres")`.
    2. Reparse regenerated SQL -> Review regenerated AST -> Regenerate second SQL.
    3. Assert `regenerated_again == regenerated`. If normalization alters semantics or introduces unreviewed syntax, the query fails with `ValidationRuleCode.IDEMPOTENCE`.

---

### Finding R05-F7: Progress JSON & Interim UI Test Notice
- **Component Audited:** `ops/progress.json`, `tests/test_interim_ui.py` (`test_health_and_cached_progress_need_no_runtime`).
- **Context:**
  In baseline commit `0e7f643a3577d32ab4e579c4a66ef6666e6ab5fe`, `ops/progress.json` records Gate R04 in state `"VERIFIED — AWAITING MERGE"`. `test_interim_ui.py` line 23 asserts `assert all(m["state"]=="MERGED" ... for m in data["milestones"])`.
  Because Gate R04 was merged by the repository owner to establish this baseline, R04's entry in `ops/progress.json` will be updated to `"MERGED"` with its merge commit SHA `0e7f643a3577d32ab4e579c4a66ef6666e6ab5fe` during the Antigravity implementation verification cycle, at which point `test_interim_ui.py` passes 100%. Codex must not modify `ops/progress.json` during implementation.

---

## 3. File Ownership Boundaries for Codex

In strict compliance with `AGENTS.md` and GitHub Issue #7, file modifications by Codex during Gate R05 implementation are restricted to:

### Permitted Implementation Files:
1. `src/stark_t2sql/security/validator.py`
   - Incorporate `negate` in `argument_keys` and `scalar_keys` for `Is`, `Like`, `ILike`.
   - Permit `big_int` boolean on `Count` in `_ASTReview._walk_all`.
2. `src/stark_t2sql/security/function_policy.py`
   - Permit `big_int` boolean on `Count` in `_arguments`.
3. Canonical Review Profile Asset (New File):
   - `src/stark_t2sql/security/profiles/sqlglot_30_22_0.json` (or `tests/fixtures/parser_approval_sqlglot_30_22_0.json`)
   - Contains versioned review approval payload for `sqlglot 30.22.0`.
4. `tests/conftest.py`
   - Add default offline fallback for `parser_approval` to load the canonical review profile asset when `STARK_TEST_PARSER_REVIEW_PATH` is unset.
5. Focused Test Files:
   - `tests/test_validator_contracts.py`
   - `tests/test_execution_resources.py`
   - Any new targeted validator unit tests (e.g., `tests/test_validator_negation.py`).
6. `Codex_R05_Work_Log.md` (Implementation work log).

### Strictly Frozen / Prohibited Files (DO NOT MODIFY):
- `schema.sql` (FROZEN — baseline DDL)
- `seed_data.py` (FROZEN — Faker 42 generator)
- `fixture_manifest.json` (FROZEN)
- `fixture_pg_dump.sql` (FROZEN)
- `src/inference/prompt_template.txt` (FROZEN — SQLCoder template)
- `policy/access_matrix.yaml` (FROZEN — access matrix)
- `semantic/catalog.yaml` (FROZEN)
- `AGENTS.md` (FROZEN — operational rules)
- `ops/progress.json` and `STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html` (Antigravity updates during verification handoff)
- `Antigravity_Design_Review.md` (Preserve unrelated working tree edits)
- No modification of `main`, no branch creation, no auto-merge, no starting R06.

---

## 4. Step-by-Step Implementation Plan for Codex

When prompted by the repository owner to implement Gate R05 on `codex/r05-remediation`, Codex must follow this sequence:

1. **Phase 1: Update Operator Node Shapes in `validator.py`**
   - In `_SHAPES` within `src/stark_t2sql/security/validator.py`:
     - Update `NodeShape("Is", ...)` to include `negate` in `argument_keys` and `scalar_keys`.
     - Update `NodeShape("Like", ...)` to include `negate` in `argument_keys` and `scalar_keys`.
     - Update `NodeShape("ILike", ...)` to include `negate` in `argument_keys` and `scalar_keys`.
   - In `_guard_structure()`, assert `args.get("negate")` is a boolean when present.

2. **Phase 2: Correct `Count` Boolean Flag Handling in `function_policy.py` & `validator.py`**
   - In `src/stark_t2sql/security/function_policy.py` `_arguments()`:
     - Allow `args.get("big_int")` to be present if `rule.sql_name == "count"` and `isinstance(args.get("big_int"), bool)`.
     - Continue rejecting `big_int` if present on non-count functions, or if `big_int` on count is non-boolean.
   - In `src/stark_t2sql/security/validator.py` `_ASTReview._walk_all()`:
     - Permit `key == "big_int"` with boolean value when `rule.sql_name == "count"`.

3. **Phase 3: Create Canonical Parser Review Approval Asset**
   - Create `src/stark_t2sql/security/profiles/sqlglot_30_22_0.json` (or `tests/fixtures/parser_approval_sqlglot_30_22_0.json`).
   - Populate with:
     - `sqlglot_version`: `"30.22.0"`
     - `validator_revision`: `"fr5-validator-draft-2"`
     - `function_policy_revision`: `"fr5-function-draft-2"`
     - `approved_node_shapes`: list of all 60 shapes in `PROPOSED_NODE_SHAPES`.
     - `approved_function_rule_ids`: list of the 36 observed PostgreSQL rules identified in Finding R05-F3.
     - `review_reference`: `"STARK-R05-SQLGLOT-30.22.0-REVIEW-20261015"`.

4. **Phase 4: Wire Default Offline Fallback in `tests/conftest.py`**
   - In `tests/conftest.py`, update fixture `parser_approval` so that if `STARK_TEST_PARSER_REVIEW_PATH` is not set, it reads the canonical profile asset from Step 3.
   - Ensure `parser_approval` instantiates a valid `ParserReviewApproval` object without skipping.

5. **Phase 5: Validate Ablation Mode Fidelity in `validator.py` & `test_execution_resources.py`**
   - Confirm `HarnessSafetyReviewer.review_candidate()` enforces `allow_all_fixture_tables=True` only for `ExecutionMode.NO_VALIDATOR` and `ExecutionMode.UNCONTROLLED`.
   - Confirm structural entry guards remain active in all modes.
   - Add/verify test coverage demonstrating that an unsafe candidate (e.g. `SET ROLE ...`, `DROP TABLE ...`) in `NO_VALIDATOR` mode is halted with `ReasonCode.HARNESS_SAFETY_STOP` (`StoppingLayer.VALIDATOR`) before connection establishment.
   - Confirm candidate execution in `NO_VALIDATOR` mode on unauthorized tables routes under the persona's login role and returns `BLOCKED_DB` (`StoppingLayer.DATABASE`).

6. **Phase 6: Run Full Regression Test Suite & Open Draft PR**
   - Execute all targeted and full offline test suites:
     ```powershell
     $env:PYTHONPATH='src;.'
     pytest tests/test_validator_contracts.py tests/test_execution_resources.py -v
     pytest tests -v
     ```
   - Confirm the 137 previously skipped parser contract tests now run and pass.
   - Author `Codex_R05_Work_Log.md` detailing changes, test counts, and commit hashes.
   - Commit and push to `origin/codex/r05-remediation`.
   - Open a single Draft PR against `gemini/full-remediation-review` and report the PR URL to the repository owner.

---

## 5. Acceptance Criteria Matrix

| Criterion ID | Target Requirement | Verification Method | Expected Outcome |
| :--- | :--- | :--- | :--- |
| **R05-T01** | Safe SELECT Queries (`GOOD_SQL`) | `test_reviewed_select_shapes_have_positive_contract` | All 13 queries in `GOOD_SQL` accepted; AST regeneration idempotent. |
| **R05-T02** | Dangerous SQL Rejection (`BAD_SQL`) | `test_rejected_shapes_never_provide_execution_text` | All 33 queries in `BAD_SQL` rejected; `regenerated_sql` is None. |
| **R05-T03** | Count with `big_int=True` | Unit test with `COUNT(*)`, `COUNT(col)`, `COUNT(DISTINCT col)` | Accepted without `V-FUNCTION` or `V-UNSUPPORTED-ARGUMENT`. |
| **R05-T04** | Negated Operators (`IS NOT NULL`, `NOT LIKE`, `NOT ILIKE`) | Unit test with `WHERE x IS NOT NULL`, `WHERE x NOT LIKE ...` | Accepted with `negate=True` validated as boolean. |
| **R05-T05** | Filter Aggregate Syntax | `SELECT COUNT(*) FILTER (WHERE ...)` in `GOOD_SQL` | Accepted and correctly mapped to reviewed aggregate. |
| **R05-T06** | Observed Function Positive Contracts | `test_each_reviewed_signature_positive` | All 36 approved function rules pass positive contract tests. |
| **R05-T07** | Function Argument Strictness | `test_each_reviewed_signature_rejects_unreviewed_arguments` | Unreviewed arguments on all approved rules raise `FunctionPolicyViolation`. |
| **R05-T08** | Offline Parser Approval Profile | Run test suite with unset `STARK_TEST_PARSER_REVIEW_PATH` | 137 previously skipped contract tests execute and pass offline. |
| **R05-T09** | `FULL` Mode Table Entitlements | `ReviewedSQLValidator.validate()` with `app_sales_mgr` selecting `employee_compensation` | Rejected with `ValidationRuleCode.TABLE` (`BLOCKED_VALIDATOR`). |
| **R05-T10** | `NO_VALIDATOR` Mode Structural Safety | `HarnessSafetyReviewer.review_candidate("SET app.principal_id='1'", mode=NO_VALIDATOR)` | Raises `HarnessSafetyStopError` (`HARNESS_SAFETY_STOP`). |
| **R05-T11** | `NO_VALIDATOR` Mode Engine ACL Denial | Candidate on unauthorized table under `NO_VALIDATOR` | Execution routed to persona login; mock/live DB returns `BLOCKED_DB` (`42501`). |
| **R05-T12** | CTE Table Shadowing Prevention | Query with `WITH employees AS (SELECT 1) ...` | Rejected with `ValidationRuleCode.CTE_SHADOW`. |
| **R05-T13** | Column Enforcement Reserved to DB | Query referencing unauthorized column on authorized table | Accepted by validator; deferred to PostgreSQL column-level ACLs. |
| **R05-T14** | Absence of Review Fails Closed | `ReviewedSQLValidator(matrix, approval=None).validate(...)` | Returns `accepted=False`, rule `REVIEW_REQUIRED`, reason `MISSING_DEPENDENCY`. |

---

## 6. Security Risks, Limitations & Stopping Gate Protocol

1. **Application Defense-in-Depth vs. Database Security Boundary:**
   The SQL Validator enforces structural query sanity and pre-execution filtering, reducing attack surface and preventing malformed queries from reaching PostgreSQL. However, it cannot guarantee execution cost, statement termination under load, or safety against PostgreSQL server-level vulnerabilities. PostgreSQL ACLs, column grants, RLS policies, connection isolation, and executor timeouts remain the authoritative security boundary.
2. **Deferral of Live PostgreSQL Enforcement to Gate R09:**
   All R05 contract tests must continue to use offline mocks and AST inspections. No connection to live PostgreSQL databases is authorized during Gate R05. Full end-to-end security verification against live PostgreSQL and SQLCoder inference is scheduled for Gate R09.
3. **Preservation of Unrelated Workspace Changes:**
   Working tree changes in `Antigravity_Design_Review.md` must remain untouched and uncommitted across all gate branches in accordance with `AGENTS.md`.
4. **Stopping Gate Protocol:**
   In strict accordance with `AGENTS.md` Rule 3, Antigravity commits and pushes `Antigravity_R05_Review.md` to `origin/codex/r05-remediation` and **STOPS**. Antigravity will not open a PR, merge branches, modify source code, or initiate Codex execution. Codex implementation begins only upon explicit direction from the repository owner.

<!-- STARK_HANDOFF_V1
{"gate": "R05", "implementation_ready": true, "phase": "design", "status": "APPROVE", "subject_sha": "0e7f643a3577d32ab4e579c4a66ef6666e6ab5fe", "tests": {"failed": 0, "passed": 0, "scope": "not_run", "skipped": 0}}
-->
