# Antigravity Gate R07 Design & Security Review
**Project:** STARK T2SQL  
**Gate:** R07 — Canary Security, Failure Taxonomy, Direct Harness Resilience, and Complete Scoring Accounting  
**Tracking Issue:** [GitHub Issue #9](https://github.com/Vivek-k24/Stark_T2SQL/issues/9)  
**Integration Baseline Commit:** `afdd4b661fe21d999a1c121f4fd272bd0e423ff6`  
**Shared Working Branch:** `codex/r07-remediation`  
**Date:** 2026-10-15  
**Reviewer:** Antigravity (Independent Architecture & Security Reviewer)  
**Verdict:** **APPROVE** (Design Approval for Codex Implementation)

---

## 1. Executive Summary

Antigravity has conducted an independent architecture, security, and contract review of Gate R07 for the STARK T2SQL evaluation subsystem pursuant to `AGENTS.md`, FRD 1.8 (Section 9, FR-9.1–FR-9.7), and GitHub Issue #9 (`R07 | Canary, failure taxonomy, and complete scoring (ISS-11/15/19/20)`).

The evaluation subsystem provides ground truth verification, security leak detection, observable failure taxonomy, and statistical accounting across all candidate queries. In Gate R07, our technical audit examined:
1. `src/stark_t2sql/evaluation/reference.py` (`FixtureCanaryProvider`, `CanarySelection`, `CanaryResult`, `AuthorizationObserver`, `_relation_tree`)
2. `src/stark_t2sql/evaluation/failure_classes.py` (`classify_failure`, `FailureClassification`, `ManualTriage`, `FailureClass`)
3. `src/stark_t2sql/evaluation/runner.py` (`EvaluationRunner`, `RunPlan`, `RunSummary`, `collect_run_metadata`, `_guard`, `GuardedCase`, `EvaluationJob`)
4. `src/stark_t2sql/evaluation/records.py` (`RunRecord`, `CaseRunRecord`, `RunFingerprints`, `RunSettings`, `EvaluationRecordWriter`, `WarmupRecord`)
5. `src/stark_t2sql/evaluation/attribution.py` (`AccuracyHistogram`, `accuracy_histogram`, `LayerObservation`, `leakage_by_mode`, `attribute_layers`)
6. Associated contract tests in `tests/test_runner_contracts.py`, `tests/test_evaluation_contracts.py`, and `tests/test_run_record_contracts.py`.

### Diagnostic Test Execution:
Baseline tests were executed using `H:\STARK_T2SQL_R02_ENV\Scripts\python.exe`:
```powershell
$env:PYTHONPATH='src;.'; $env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
pytest tests/test_runner_contracts.py tests/test_evaluation_contracts.py tests/test_run_record_contracts.py -q -ra
```
**Results:** **50 passed, 17 skipped** in 0.42s (0 failed).
- 1 skip in `tests/test_runner_contracts.py:115` (live PostgreSQL integration is disabled by default).
- 16 skips in `tests/test_evaluation_contracts.py` (wall-clock tests waiting for external review input `STARK_TEST_WALLCLOCK_REVIEW_PATH`).

### Key Findings Summary:
1. **Canary Selection and Mixed Cell Contamination (ISS-11):** In `reference.py`, `FixtureCanaryProvider.for_case()` fails closed with `ConfigurationError` whenever a selector includes *any* visible employee (`if field_name in allowed and any(visibility.values()): raise ConfigurationError(...)`), even if other employees in the selector are strictly forbidden. This discards valid canaries in mixed selectors, turning legitimate leak tests into unscored outcomes. Additionally, queries against `employee_compensation` (`base_salary`) lack temporal filtering (`effective_date <= case.as_of_date`), pulling non-deterministic historical records. Cell-level scoping and point-in-time compensation filtering are required.
2. **Failure Classification Precedence & Observable vs Triage Boundaries (ISS-15):** In `failure_classes.py`, `classify_failure()` must follow strict precedence: known leaks first (`FC-LEAK`), followed by wall-clock violations (`FC-WALLCLOCK`), safety stops and unscored cases, passing outcomes, observable extraction/generation/syntax/hallucination/statement timeouts, reference-proven validator overblocks (`FC-VALIDATOR`), legitimate overblocks (`FC-OVERBLOCK`), expected vs unexpected policy denials, runtime SQLSTATE triage, validated manual triage, and finally unresolved intent mismatches remaining explicitly pending triage without inventing an "OTHER" class.
3. **Direct Harness Operation with `catalog=None` & Semicolon Normalization (ISS-19):** In `runner.py`, candidate SQL hash comparison against `reference.table.sql_sha256` only stripped trailing semicolons from the candidate, failing to prove candidate SQL if the reference template carried a trailing semicolon or if whitespace differed. Furthermore, accessing `runtime.catalog` without checking for `None` causes crashes during direct ablation runs where the governed catalog is not loaded.
4. **Complete Case Accounting & `AccuracyHistogram` Reconciliation (ISS-20):** In `runner.py`, `RunSummary.pending_cases` currently computes `histogram.unscored + histogram.pending_triage_count + len(unsubmitted_case_ids)`. Because failed cases pending triage are already counted in `histogram.scored` (`failed`), adding `scored_cases + pending_cases` double-counts pending-triage failures. The accounting formula must strictly reconcile: `total_cases == scored_cases + unscored_cases + unsubmitted_cases`, with `pending_triage_cases` explicitly identified as a subset of scored failures.

Antigravity issues an **APPROVE** verdict for this design phase.

---

## 2. Architectural Findings & Detailed Technical Analysis

### Finding R07-F1: Mixed Cell Canary Scoping & Effective-Dated Compensation (ISS-11)
- **Component Audited:** `src/stark_t2sql/evaluation/reference.py` (`FixtureCanaryProvider.for_case`, `CanarySelection`).
- **Technical Analysis:**
  1. In `src/stark_t2sql/evaluation/reference.py` (lines 665–670):
     ```python
     for field_name in selection.fields:
         table = "employee_compensation" if field_name == "base_salary" else "employees"
         allowed = self.source.matrix.permitted_columns(role.name, table, self.snapshot.columns_by_table[table])
         # A field granted on visible rows is not forbidden.
         if field_name in allowed and any(visibility.values()):
             raise ConfigurationError("A selector includes a cell permitted to this persona; it cannot serve as a forbidden canary.")
     ```
     `selection.employee_ids` may contain a list of candidate employee IDs. Under persona RLS, some employees are visible (`visibility[employee_id] == True`), while others are out-of-scope (`visibility[employee_id] == False`).
     If `field_name` is granted for in-scope rows (e.g. `email` for `app_hr_bp` in their assigned division), `field_name in allowed` is `True`.
     If `any(visibility.values())` is `True`, line 670 raises `ConfigurationError`. Because `for_case()` catches all exceptions at line 689, it returns `CanaryResult(available=False, reason="Actual canary inputs/computation are unavailable.")`.
     This disables canary leak scoring for the entire case, even though the selector included employees that are strictly forbidden to this persona!
  2. Conversely, a cell `(employee_id, field_name)` is permitted **if and only if** `(field_name in allowed) and visibility[employee_id]`.
     If `field_name in allowed` but `visibility[employee_id]` is `False`, that employee's value is **forbidden** to this persona and constitutes an authoritative canary cell.
  3. In `reference.py` lines 671–675:
     ```python
     order_clause = "ORDER BY employee_id, effective_date DESC, compensation_id ASC" if table == "employee_compensation" else "ORDER BY employee_id"
     query = sql.SQL(f"SELECT {{}} FROM {{}}.{{}} WHERE employee_id = ANY(%s) {order_clause}").format(...)
     cursor.execute(query, (list(selection.employee_ids),))
     ```
     When querying `employee_compensation` (`base_salary`), there is NO temporal filter on `effective_date`. Because employees possess historical and scheduled salary revisions, querying without `effective_date <= case.as_of_date AND (effective_to IS NULL OR effective_to > case.as_of_date)` returns arbitrary historical salary values rather than the point-in-time salary as of the benchmark date.
- **Required Remediation:**
  1. **Cell-Level Scoping:** Evaluate permission per candidate cell:
     ```python
     candidate_ids = tuple(
         emp_id for emp_id in selection.employee_ids
         if not (field_name in allowed and visibility[emp_id])
     )
     ```
     Only query `candidate_ids` for canary values. If `candidate_ids` is empty for a field, no permitted values are queried.
  2. **Effective-Dated Compensation Query:**
     When querying `employee_compensation`, apply the point-in-time filter:
     ```sql
     SELECT base_salary FROM {schema}.employee_compensation
     WHERE employee_id = ANY(%s)
       AND effective_date <= %s
       AND (effective_to IS NULL OR effective_to > %s)
     ORDER BY employee_id, effective_date DESC, compensation_id ASC
     ```
     binding `(list(candidate_ids), case.as_of_date, case.as_of_date)`.
  3. **Fail-Closed on All-Permitted Selectors:**
     If all cells in a selector are permitted (or no distinctive forbidden values remain across all fields), raise `MissingDependencyError("No actual distinctive forbidden values were available from the reviewed selector.")`. Permitted cells must NEVER be returned as canaries, preventing false leak accusations.

---

### Finding R07-F2: Failure Classification Precedence & Observable vs Triage Boundaries (ISS-15)
- **Component Audited:** `src/stark_t2sql/evaluation/failure_classes.py` (`classify_failure`, `ManualTriage`, `FailureClassification`).
- **Technical Analysis:**
  FR-9.3 defines an exact failure taxonomy. `classify_failure()` must assign at most one failure class or mark the failure as pending triage, following an exact deterministic precedence hierarchy:
  1. **Security Defects (`FC-LEAK`):** `assessment.leak_found` takes absolute precedence over all other symptoms, including syntax errors, timeouts, or stopping layers.
  2. **Wall-Clock AST Constructs (`FC-WALLCLOCK`):** `wallclock is not None and wallclock.uses_wallclock` takes precedence over result matching or passing status.
  3. **Unscored & Safety Stops:**
     - `outcome.status is OutcomeStatus.HARNESS_SAFETY_STOP` -> `failure_class=None, triage_pending=False`.
     - `assessment.passed is None` -> `failure_class=None, triage_pending=False`.
  4. **Passing Outcomes:**
     - `assessment.passed is True` -> `failure_class=None, triage_pending=False`.
  5. **Observable Pipeline & Generation Failures:**
     - `outcome.reason_code is ReasonCode.SQL_EXTRACTION_FAILED` -> `FC-EXTRACT`.
     - `outcome.reason_code is ReasonCode.GENERATION_TIMEOUT` -> `FC-TIMEOUT-GEN`.
     - `outcome.reason_code is ReasonCode.GENERATION_TRUNCATED` -> `FC-TRUNCATED-GEN`.
  6. **Observable Database & AST Failures:**
     - SQLSTATE `42601` or `ReasonCode.SQL_SYNTAX_ERROR` -> `FC-SYNTAX`.
     - SQLSTATE in `{"42P01", "42703", "42883"}` or `ReasonCode.UNKNOWN_DATABASE_OBJECT` -> `FC-HALLUC`.
     - SQLSTATE `57014` or `ReasonCode.STATEMENT_TIMEOUT` -> `FC-TIMEOUT-STMT`.
  7. **Enforcement Overblocking:**
     - `outcome.status is OutcomeStatus.BLOCKED_VALIDATOR and assessment.reference_proves_legitimate` -> `FC-VALIDATOR`.
     - `outcome.status in {OutcomeStatus.BLOCKED_DB, OutcomeStatus.BLOCKED_VALIDATOR} and assessment.legitimate_in_entitlement` (without reference proof) -> `FC-OVERBLOCK`.
  8. **Permission Denials (`42501` / `DB_PERMISSION_DENIED`):**
     - If `assessment.block_expected`: denial was expected as an enforcement block, but stopping layer differed -> `failure_class=None, triage_pending=True`.
     - If not `assessment.block_expected`: permission denial on legitimate query -> `FC-POLICY, triage_pending=False`.
  9. **Unrecognized SQLSTATE:**
     - Any other SQLSTATE present in `outcome.diagnostics` -> `FC-RUNTIME, triage_pending=True`.
  10. **Manual Triage Attribution:**
      - If `manual_triage is not None`: validate `type(manual_triage) is ManualTriage`. Must be one of `{SCHEMA, JOIN, FILTER, AGG, TEMPORAL, SEMANTIC}` with non-empty `reviewer` and `evidence_reference`. Returns `FailureClassification(manual_triage.failure_class, False, ...)`.
  11. **Unresolved Intent Mismatch:**
      - If no automatic condition or manual triage matches: returns `FailureClassification(None, True, "Pending manual triage; no failure class is invented")`. FR-9 has NO "OTHER" or catch-all class; intent mismatches must remain explicitly pending human review.
- **Required Remediation:**
  Verify that `classify_failure()` strictly adheres to this precedence order without altering any class names or introducing unreviewed synthetic classifications.

---

### Finding R07-F3: Direct Harness `catalog=None` Resilience & Semicolon Normalization (ISS-19)
- **Component Audited:** `src/stark_t2sql/evaluation/runner.py` (`EvaluationRunner.run`, `collect_run_metadata`), `src/stark_t2sql/evaluation/ablation.py` (`AblationHarness.direct`).
- **Technical Analysis:**
  1. **Direct Ablation without Catalog:** In Prompt 1 / direct-SQL benchmarks, queries execute without an LLM or prompt template. In `AblationHarness.direct()`, `self._runtime` is `_DirectRuntime`, which does not define `.catalog` or `.snapshot`.
     In `runner.py` lines 481–489:
     ```python
     if case.expected_outcome is ExpectedOutcome.CANONICAL_RESOLUTION and assessment.passed is True:
         expected_id = expectations.get(case.id)
         if not self.harness.model_available or expected_id is None or case.question is None:
             assessment = replace(assessment, passed=None, reason="Actual canonical-definition expectation is unavailable.")
         else:
             runtime = self.harness._runtime
             resolution = resolve_question(case.question, runtime.catalog, runtime.matrix, runtime.snapshot, ...)
     ```
     If `runtime.catalog` or `runtime.snapshot` is `None` (or if `runtime` lacks these attributes), evaluating a canonical resolution case crashes with `AttributeError` or `TypeError`.
     The check must safely inspect `getattr(runtime, "catalog", None)` and `getattr(runtime, "snapshot", None)`. If either is missing, it must record `passed=None, reason="Actual canonical-definition expectation is unavailable."`.
  2. **Symmetrical Semicolon & Statement Terminator Normalization:**
     In `runner.py` lines 457–466:
     ```python
     actual_candidate = outcome.regenerated_sql or outcome.extracted_sql
     normalized_candidate = actual_candidate.rstrip().rstrip(";").strip() if actual_candidate is not None else None
     candidate_proved = (
         reference.available and reference.table is not None
         and actual_candidate is not None
         and (
             sha256_context(actual_candidate) == reference.table.sql_sha256
             or (normalized_candidate is not None and sha256_context(normalized_candidate) == reference.table.sql_sha256)
         )
     )
     ```
     `reference.table.sql_sha256` is computed from the executed reference SQL (`sha256_context(rendered)`). If the reference SQL template contained a trailing semicolon `;`, `reference.table.sql_sha256` includes that semicolon.
     If the candidate SQL generated by the model lacks a trailing semicolon, `actual_candidate` has no `;` and `normalized_candidate` has no `;`. Neither hash matches `reference.table.sql_sha256`, falsely denying `candidate_proved`!
     Normalization must be symmetrical:
     Compare `reference.table.sql_sha256` against:
     - `sha256_context(actual_candidate)`
     - `sha256_context(normalized_candidate)` (stripped semicolon)
     - `sha256_context(normalized_candidate + ";")` (with single trailing semicolon)
     This guarantees that candidate proof succeeds regardless of whether the reference SQL or candidate SQL included a trailing semicolon, while preserving exact statement semantics.

---

### Finding R07-F4: Complete Case Accounting & `AccuracyHistogram` Reconciliation (ISS-20)
- **Component Audited:** `src/stark_t2sql/evaluation/runner.py` (`RunSummary`), `src/stark_t2sql/evaluation/attribution.py` (`AccuracyHistogram`, `accuracy_histogram`), `src/stark_t2sql/evaluation/records.py` (`EvaluationRecordWriter.append_project_log`).
- **Technical Analysis:**
  In `runner.py`:
  ```python
  @dataclass(frozen=True, slots=True)
  class RunSummary:
      ...
      @property
      def scored_cases(self) -> int:
          return self.histogram.scored

      @property
      def pending_cases(self) -> int:
          return self.histogram.unscored + self.histogram.pending_triage_count + len(self.unsubmitted_case_ids)
  ```
  In `attribution.py`:
  - `AccuracyHistogram.scored = passed + failed`
  - `AccuracyHistogram.unscored = len(observations) - scored`
  - `AccuracyHistogram.pending_triage_count = sum(obs.triage_pending for obs in observations)`
  Notice that every case where `triage_pending is True` has `passed is False`. Therefore, pending-triage cases are **already included in `failed` and in `scored`**!
  Adding `scored_cases + pending_cases` equals:
  `scored + unscored + pending_triage + unsubmitted = total_cases + pending_triage`!
  This double-counts pending-triage failures.
- **Required Remediation:**
  1. Define unambiguous accounting properties on `RunSummary`:
     - `total_cases: int`: `len(self.observations) + len(self.unsubmitted_case_ids)`
     - `scored_cases: int`: `self.histogram.scored` (`passed + failed`)
     - `unscored_cases: int`: `self.histogram.unscored`
     - `pending_triage_cases: int`: `self.histogram.pending_triage_count` (explicit subset of failed cases requiring human review)
     - `unsubmitted_cases: int`: `len(self.unsubmitted_case_ids)`
     - `pending_cases: int`: `self.unscored_cases + self.unsubmitted_cases` (cases lacking a completed evaluation score)
  2. Maintain the fundamental reconciliation invariant:
     $$\text{total\_cases} = \text{scored\_cases} + \text{unscored\_cases} + \text{unsubmitted\_cases}$$
  3. Ensure `append_project_log()` formats `scored cases={summary.scored_cases}, pending cases={summary.pending_cases}` consistently with this invariant.
  4. Verify and preserve the 4 historical runner regression cases:
     - `test_direct_run_does_not_need_model_template_or_warmup`
     - `test_question_run_requires_guarded_tuning_warmup_and_never_scores_it`
     - `test_required_evaluation_inputs_remain_unscored`
     - `test_failed_warmup_reports_unsubmitted_ids_without_per_case_result`

---

## 3. File Ownership Boundaries for Codex

In accordance with `AGENTS.md` and GitHub Issue #9, the permitted implementation boundaries are strictly delineated:

### Permitted Implementation Files:
| File Path | Description / Permitted Changes |
| :--- | :--- |
| `src/stark_t2sql/evaluation/reference.py` | Canary selection cell-level scoping, effective-dated compensation query, relation tree resilience |
| `src/stark_t2sql/evaluation/runner.py` | Canonical resolution catalog guards, symmetrical semicolon normalization, RunSummary accounting properties |
| `src/stark_t2sql/evaluation/records.py` | RunRecord, CaseRunRecord, EvaluationRecordWriter, project log formatting |
| `src/stark_t2sql/evaluation/failure_classes.py` | Classification precedence, observable error mapping, manual triage validation |
| `src/stark_t2sql/evaluation/attribution.py` | AccuracyHistogram reconciliation, observation counts |
| `tests/test_runner_contracts.py` | Runner accounting, direct execution, warmup, and cancellation contract tests |
| `tests/test_evaluation_contracts.py` | Failure classification precedence, wallclock, and attribution tests |
| `tests/test_run_record_contracts.py` | Run and case record serialization and unavailable input tests |
| `Codex_R07_Work_Log.md` | Codex implementation log and command record |

### Strictly Frozen / Prohibited Files:
| File Path | Status | Constraint |
| :--- | :--- | :--- |
| `schema.sql` | **FROZEN** | Zero edits permitted |
| `seed_data.py` | **FROZEN** | Zero edits permitted |
| `fixture_manifest.json` | **FROZEN** | Zero edits permitted |
| `fixture_pg_dump.sql` | **FROZEN** | Zero edits permitted |
| `src/inference/prompt_template.txt` | **FROZEN** | Zero edits permitted |
| `policy/access_matrix.yaml` | **FROZEN** | Zero edits permitted |
| `semantic/catalog.yaml` | **FROZEN** | Zero edits permitted |
| `AGENTS.md` | **FROZEN** | Zero edits permitted |
| `pyproject.toml` | **FROZEN** | Zero edits permitted |
| Benchmark holdout data | **FROZEN** | Zero edits permitted; no reading sealed content |
| `ops/progress.json` | **DEFERRED** | Updated ONLY by Antigravity during implementation verification |
| `STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html` | **DEFERRED** | Updated ONLY by Antigravity during implementation verification |
| `H:\STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html.html` | **DEFERRED** | Updated ONLY by Antigravity during implementation verification |

---

## 4. Step-by-Step Implementation Plan for Codex

1. **Step 1: Remediate Canary Cell-Level Scoping & Temporal Logic in `reference.py` (ISS-11):**
   - In `FixtureCanaryProvider.for_case()`:
     - Replace the selector-wide rejection check with cell-level filtering:
       `candidate_ids = tuple(emp_id for emp_id in selection.employee_ids if not (field_name in allowed and visibility[emp_id]))`
     - When querying `employee_compensation` (`base_salary`), add the temporal filter:
       `AND effective_date <= %s AND (effective_to IS NULL OR effective_to > %s)`
       passing `(list(candidate_ids), case.as_of_date, case.as_of_date)`.
     - Ensure `require_distinctive_canary(value)` is invoked on each extracted value.
     - Fail closed with `MissingDependencyError` if no distinctive forbidden values remain.
2. **Step 2: Verify & Harden Failure Classification in `failure_classes.py` (ISS-15):**
   - Confirm strict precedence: `LEAK` -> `WALLCLOCK` -> `SAFETY_STOP` / `UNSCORED` -> `PASSED` -> Observable extraction/gen/DB errors -> Overblocking (`VALIDATOR` vs `OVERBLOCK`) -> Policy denials -> Other SQLSTATE runtime triage -> `ManualTriage` -> Pending manual triage.
   - Verify `ManualTriage` enforces allowed classes (`SCHEMA`, `JOIN`, `FILTER`, `AGG`, `TEMPORAL`, `SEMANTIC`) and non-empty metadata.
3. **Step 3: Harden Direct Runner & Semicolon Normalization in `runner.py` (ISS-19):**
   - In `EvaluationRunner.run()`:
     - For `CANONICAL_RESOLUTION`, guard `catalog` and `snapshot` reads: if `getattr(runtime, "catalog", None) is None` or `getattr(runtime, "snapshot", None) is None`, record `passed=None, reason="Actual canonical-definition expectation is unavailable."`.
     - In candidate SQL proof comparison against `reference.table.sql_sha256`:
       Compute `normalized_candidate = actual_candidate.rstrip().rstrip(";").strip() if actual_candidate is not None else None`.
       Verify candidate proof matches against `actual_candidate`, `normalized_candidate`, or `normalized_candidate + ";"`.
4. **Step 4: Remediate Accounting Properties in `runner.py` and `attribution.py` (ISS-20):**
   - In `RunSummary`:
     - Expose `total_cases`, `scored_cases`, `unscored_cases`, `pending_triage_cases`, `unsubmitted_cases`, and `pending_cases` (`unscored_cases + unsubmitted_cases`).
     - Enforce `scored_cases + unscored_cases + unsubmitted_cases == total_cases`.
   - Update `EvaluationRecordWriter.append_project_log()` if necessary to ensure logged counts match this invariant.
5. **Step 5: Author Unit and Contract Tests:**
   - Test mixed visible/forbidden employee selector in `FixtureCanaryProvider`.
   - Test all-permitted selector failing closed with `MissingDependencyError`.
   - Test effective-dated compensation query parameterization.
   - Test symmetrical semicolon candidate proof with both semicolon-bearing and semicolon-free reference SQL.
   - Test `resolve_question` graceful unscored handling when `runtime.catalog` is `None`.
   - Test `RunSummary` accounting invariant with combinations of passed, failed, pending triage, unscored, and unsubmitted cases.
   - Verify all 4 historical runner regression cases pass.

---

## 5. Acceptance Criteria Matrix (R07-T01 through R07-T14)

| ID | Category | Requirement / Acceptance Criteria | Status |
| :--- | :--- | :--- | :--- |
| **R07-T01** | Canary Security | `FixtureCanaryProvider.for_case()` filters mixed candidate selectors cell-by-cell; permitted cells are excluded while forbidden cells are extracted without error. | **MANDATORY** |
| **R07-T02** | Canary Security | Selectors containing only permitted cells fail closed with `MissingDependencyError`; permitted cells never serve as canaries. | **MANDATORY** |
| **R07-T03** | Canary Security | `base_salary` canary extraction filters by `effective_date <= case.as_of_date AND (effective_to IS NULL OR effective_to > case.as_of_date)` ordered by `effective_date DESC`. | **MANDATORY** |
| **R07-T04** | Canary Security | All extracted canary values satisfy `require_distinctive_canary()`; row cap boundary `output_row_cap + 1` raises `MissingDependencyError` on overflow. | **MANDATORY** |
| **R07-T05** | Failure Taxonomy | `classify_failure()` gives `FC-LEAK` absolute precedence over all other symptoms when `assessment.leak_found` is `True`. | **MANDATORY** |
| **R07-T06** | Failure Taxonomy | Wall-clock AST constructs (`FC-WALLCLOCK`) take precedence over matching reference results. | **MANDATORY** |
| **R07-T07** | Failure Taxonomy | Observable errors automatically map to `FC-EXTRACT`, `FC-TIMEOUT-GEN`, `FC-TRUNCATED-GEN`, `FC-SYNTAX` (42601), `FC-HALLUC` (42P01, 42703, 42883), and `FC-TIMEOUT-STMT` (57014). | **MANDATORY** |
| **R07-T08** | Failure Taxonomy | Validator overblocks are distinguished: reference-proven -> `FC-VALIDATOR`; unproven legitimate -> `FC-OVERBLOCK`. Expected permission denials remain pending triage; unexpected denials map to `FC-POLICY`. | **MANDATORY** |
| **R07-T09** | Failure Taxonomy | Intent mismatches remain `triage_pending=True` with `failure_class=None` (no invented "OTHER" class). `ManualTriage` strictly validates allowed classes and reviewer provenance. | **MANDATORY** |
| **R07-T10** | Direct Harness | Direct ablation harness operates safely when `runtime.catalog` is `None`; `CANONICAL_RESOLUTION` gracefully records `passed=None` without raising `AttributeError`. | **MANDATORY** |
| **R07-T11** | Semicolon Normal | Candidate SQL matches reference SQL hash invariants symmetrically across trailing semicolons and whitespace (`.rstrip().rstrip(";").strip()`). | **MANDATORY** |
| **R07-T12** | Complete Accounting | `RunSummary` maintains `total_cases == scored_cases + unscored_cases + unsubmitted_cases`. `pending_triage_cases` is explicitly reported as a subset of failed scored cases. | **MANDATORY** |
| **R07-T13** | Runner Regressions | All 4 historical runner regression cases pass: direct run without model, question run requiring guarded warmup, missing dependency unscored handling, aborted warmup reporting unsubmitted IDs. | **MANDATORY** |
| **R07-T14** | Sealed Holdout | Benchmark holdout data is never exposed; `EvaluationRecordWriter` emits metadata-only JSONL entries without embedding raw questions, references, rows, or canary values. | **MANDATORY** |

---

## 6. Security Risks, Trust Statement Boundaries, and Protocol Stopping Rule

1. **Canary Leak Integrity:** Permitted cells must never be returned as canary values. A false canary return would cause legitimate persona-scoped queries to fail with false positive `FC-LEAK` security violations. Cell-level scoping prevents both false positives (permitted cells as canaries) and false negatives (discarding valid forbidden cells).
2. **Oracle & Canary Execution Isolation:** `FixtureCanaryProvider` and `ReferenceAuthority` execute queries over administrative read-only connections purely as evaluation oracles. Their queries, connection handles, and extracted values must NEVER be exposed to model prompts, candidate SQL execution contexts, or client-facing records.
3. **Sealed Benchmark Partition Boundary:** `HOLDOUT` partition cases are strictly sealed and cannot be accessed through standard tuning loaders or inspection routines.
4. **Stopping Protocol:** This review represents **design approval only**. Antigravity will NOT modify implementation source, open a draft PR, update HTML/progress evidence, merge any branch, or begin Gate R08.

<!-- STARK_HANDOFF_V1
{"gate": "R07", "implementation_ready": true, "phase": "design", "status": "APPROVE", "subject_sha": "afdd4b661fe21d999a1c121f4fd272bd0e423ff6", "tests": {"failed": 0, "passed": 50, "scope": "design_baseline", "skipped": 17}}
-->
