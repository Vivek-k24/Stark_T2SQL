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


---

# Antigravity Gate R07 Implementation Verification Report

**Project:** STARK T2SQL  
**Gate:** R07 — Canary Security, Failure Taxonomy, Direct Runner Resilience, and Complete Scoring Accounting  
**Tracking Issue:** [GitHub Issue #9](https://github.com/Vivek-k24/Stark_T2SQL/issues/9)  
**Draft PR:** [GitHub Draft PR #22](https://github.com/Vivek-k24/Stark_T2SQL/pull/22)  
**Integration Baseline Commit:** `afdd4b661fe21d999a1c121f4fd272bd0e423ff6`  
**Implementation Commit:** `83a6384c1aa554b1479a26b6720503d2b116d811`  
**Latest Reviewed Codex Commit:** `70f74589e5ad487968a496e86e5c26856091833a`  
**Verification Date:** 2026-10-15  
**Reviewer:** Antigravity (Independent Architecture & Security Reviewer)  
**Final Verification Verdict:** **APPROVE** (Verified — Awaiting Owner Merge)

---

## 7. Independent Implementation Audit

Antigravity has performed an exhaustive, independent source, security, and test verification of Codex's Gate R07 implementation in Draft PR #22 against FRD 1.8 (Section 9), GitHub Issue #9, and the approved Gate R07 Design Review.

### A. Verification of Finding R07-F1: Canary Security & Mixed Cell Scoping
- **Implementation Audited:** `src/stark_t2sql/evaluation/reference.py` (`FixtureCanaryProvider.for_case`, `CanarySelection.__post_init__`).
- **Audit Findings:**
  1. **Cell-Level Scoping:** In `FixtureCanaryProvider.for_case()`, candidate exclusion is now evaluated strictly per cell:
     ```python
     candidates[field_name] = tuple(
         employee_id for employee_id in selection.employee_ids
         if not (field_name in allowed and visibility[employee_id])
     )
     ```
     An employee is excluded for a field if and only if that field is permitted to the persona's role AND the employee is visible under persona RLS.
  2. **Preservation of Mixed Canaries:** When a selector contains both in-scope and out-of-scope employees (e.g. `hr_1` seeing employee 1001 in their division, but not employee 1002 in another division), `email` for 1001 is excluded while `email` for 1002 is retained as a valid forbidden canary. The entire selector is no longer discarded.
  3. **Fail-Closed on All-Permitted Selectors:** If `not any(candidates.values())`, the provider raises `MissingDependencyError("No forbidden cells remain in this selector.")` before acquiring any administrative connection, safely returning `CanaryResult(available=False)` and preventing permitted data from becoming false leak evidence.
  4. **Point-in-Time Compensation Selection:** For `base_salary`, queries against `employee_compensation` apply:
     `SELECT DISTINCT ON (employee_id) "base_salary" FROM {schema}.employee_compensation WHERE employee_id = ANY(%s) AND effective_date <= %s AND (effective_to IS NULL OR effective_to > %s) ORDER BY employee_id, effective_date DESC, compensation_id ASC`
     binding `(list(candidate_ids), case.as_of_date, case.as_of_date)`. This deterministically extracts the single active compensation row per employee as of `case.as_of_date`.
  5. **Distinctive Value Checks & Row Caps:** Values are validated through `require_distinctive_canary()`; nondistinctive values are skipped without failing the case, while cap overflows (> `output_row_cap`) raise `MissingDependencyError`.
  6. **Selector Integrity:** `CanarySelection.__post_init__` verifies `len(set(self.fields)) == len(self.fields)` to reject duplicate fields, while preserving bounded IDs, field allowlists, and fixture SHA-256 bindings.

---

### B. Verification of Finding R07-F2: Failure Classification Precedence & Manual Triage
- **Implementation Audited:** `src/stark_t2sql/evaluation/failure_classes.py` (`classify_failure`, `ManualTriage`), `src/stark_t2sql/evaluation/runner.py`.
- **Audit Findings:**
  1. **Precedence Enforcement:**
     - Security defects (`assessment.leak_found`) take absolute precedence, returning `FC-LEAK` with `triage_pending=False`.
     - Prohibited wall-clock AST constructs (`wallclock.uses_wallclock`) take precedence over matching reference results, returning `FC-WALLCLOCK`.
     - Safety stops (`HARNESS_SAFETY_STOP`) and missing inputs (`assessment.passed is None`) return `failure_class=None, triage_pending=False`.
     - Passing cases (`assessment.passed is True`) return `failure_class=None, triage_pending=False`.
     - Observable extraction, generation timeouts, truncations, SQL syntax (42601), and hallucinated database objects (42P01, 42703, 42883) automatically map to their respective failure classes.
     - Reference-proven validator rejections map to `FC-VALIDATOR`, whereas unproven in-entitlement blocks map to `FC-OVERBLOCK`.
     - Expected permission blocks (where the stopping layer differed) remain `triage_pending=True` with `failure_class=None`; unexpected denials map to `FC-POLICY`.
     - Unrecognized SQLSTATE values map to `FC-RUNTIME, triage_pending=True`.
  2. **Strict Type Safety for Manual Triage:**
     In `ManualTriage.__post_init__`, `type(self.failure_class) is not FailureClass` was added, strictly rejecting raw strings like `"FC-SEMANTIC"`. The class must be an exact member of `{SCHEMA, JOIN, FILTER, AGG, TEMPORAL, SEMANTIC}` with non-empty, stripped `reviewer` and `evidence_reference` strings.
  3. **Preservation of Observed Leaks:**
     In `runner.py`, when a computed canary provider is unavailable, line 524 guards against overwriting an already observed fixture-bound leak (`and not assessment.leak_found`), preserving ground truth security detections.

---

### C. Verification of Finding R07-F3: Direct Runner Resilience & Semicolon Normalization
- **Implementation Audited:** `src/stark_t2sql/evaluation/runner.py` (`_candidate_matches_reference`, `EvaluationRunner.run`).
- **Audit Findings:**
  1. **Resilience to Missing Catalogs in Direct Runs:**
     In `runner.py`, lines 548–556 inspect `catalog = getattr(runtime, "catalog", None)` and `snapshot = getattr(runtime, "snapshot", None)`. In direct runs where `catalog` or `snapshot` is `None` or absent, `CANONICAL_RESOLUTION` cases gracefully set `passed=None, reason="Actual canonical-definition expectation is unavailable."` without calling `resolve_question()` or raising `AttributeError`.
  2. **Symmetrical Semicolon Proof with Lexical Safety:**
     `_candidate_matches_reference(candidate, reference, matrix)`:
     - Enforces that `reference.available`, `reference.proves_legitimate`, and `reference.table` are valid.
     - Runs the candidate through `physical_reference_tables(candidate, matrix)` to reject DDL, DML, multiple statements, and malformed syntax.
     - Tokenizes candidate SQL via `sqlglot.tokenize(trimmed, read="postgres")`.
     - Rejects queries with multiple semicolons (`len(terminators) > 1`).
     - Ensures semicolons inside strings or comments are not treated as statement terminators.
     - Checks candidate variants (original, trimmed, stripped semicolon, single trailing semicolon) against `reference.table.sql_sha256`. Proof succeeds symmetrically whether candidate or reference carried a trailing semicolon.

---

### D. Verification of Finding R07-F4: Complete Scoring Accounting & Run Summary
- **Implementation Audited:** `src/stark_t2sql/evaluation/runner.py` (`RunSummary`), `src/stark_t2sql/evaluation/records.py` (`validate_case_accounting`, `write_summary`, `append_project_log`).
- **Audit Findings:**
  1. **Reconciliation Invariant:**
     `RunSummary` exposes explicit properties:
     - `total_cases = len(observations) + unsubmitted_cases`
     - `scored_cases = histogram.scored` (`passed + failed`)
     - `unscored_cases = histogram.unscored`
     - `pending_triage_cases = histogram.pending_triage_count`
     - `unsubmitted_cases = len(unsubmitted_case_ids)`
     - `pending_cases = unscored_cases + unsubmitted_cases`
     Enforces `total_cases == scored_cases + unscored_cases + unsubmitted_cases`.
  2. **Elimination of Triage Double-Counting:**
     `pending_triage_cases` is verified as a subset of failed scored cases (`row.triage_pending and row.passed is False`). It is never added to `pending_cases` or `total_cases`.
  3. **Shared Accounting Validation:**
     `validate_case_accounting()` in `records.py` validates non-negative integer counts and mathematical reconciliation across `RunSummary`, summary JSONL, and `PROJECT_LOG.md`.
  4. **Cancellation and Partial Run Accounting:**
     When a run is cancelled, cases already executed are retained in `observations` with their real outcomes, while unsubmitted cases are tracked in `unsubmitted_case_ids`. A partial summary and project log entry are emitted without fabricating any outcomes.

---

## 8. Acceptance Criteria Evaluation Matrix (R07-T01 through R07-T14)

| ID | Category | Requirement / Acceptance Criteria | Status | Independent Verification Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **R07-T01** | Canary Security | Filter mixed selectors cell-by-cell; exclude permitted cells, extract forbidden cells. | **VERIFIED** | `test_mixed_selector_reads_only_forbidden_email_and_preserves_it`, `test_mixed_fields_apply_permission_to_each_cell` |
| **R07-T02** | Canary Security | All-permitted selectors fail closed (`MissingDependencyError`); permitted cells never serve as canaries. | **VERIFIED** | `test_all_permitted_selector_never_queries_values_or_fabricates_clearance`, `test_payroll_salary_cells_are_permitted_and_never_read_as_canaries` |
| **R07-T03** | Canary Security | `base_salary` canary query applies half-open interval `effective_date <= as_of_date AND (effective_to IS NULL OR effective_to > as_of_date)`. | **VERIFIED** | `test_salary_temporal_boundaries_are_half_open_and_parameter_bound` (boundary tests on start/end dates) |
| **R07-T04** | Canary Security | Canary values satisfy `require_distinctive_canary()`; row cap overflow raises `MissingDependencyError`. | **VERIFIED** | `test_only_distinctive_forbidden_values_can_be_returned`, `test_canary_overflow_is_unavailable_not_truncated_evidence` |
| **R07-T05** | Failure Taxonomy | `FC-LEAK` has absolute precedence over all other symptoms when `assessment.leak_found` is true. | **VERIFIED** | `test_r07_leak_precedes_every_other_symptom` (tested across passed, status, reason, SQLSTATE combinations) |
| **R07-T06** | Failure Taxonomy | `FC-WALLCLOCK` takes precedence over matching reference results. | **VERIFIED** | `test_r07_wallclock_precedes_matches_unavailable_and_error_symptoms` |
| **R07-T07** | Failure Taxonomy | Automatic assignment of `FC-EXTRACT`, `FC-TIMEOUT-GEN`, `FC-TRUNCATED-GEN`, `FC-SYNTAX`, `FC-HALLUC`, and `FC-TIMEOUT-STMT`. | **VERIFIED** | `test_r07_automatic_symptom_precedence_over_enforcement_and_manual_triage` |
| **R07-T08** | Failure Taxonomy | Validator overblocks distinguished: reference-proven -> `FC-VALIDATOR`; unproven -> `FC-OVERBLOCK`. Expected permission blocks remain pending triage. | **VERIFIED** | `test_r07_reference_overblock_and_expected_permission_precedence` |
| **R07-T09** | Failure Taxonomy | Intent mismatches remain `triage_pending=True` with no invented class; `ManualTriage` strictly typed. | **VERIFIED** | `test_r07_manual_triage_requires_typed_allowed_class_and_metadata`, `test_r07_manual_triage_rejects_automatic_or_untyped_classes`, `test_r07_unresolved_intent_has_no_catch_all_class` |
| **R07-T10** | Direct Harness | Direct harness operates safely when `catalog`/`snapshot` is `None`; `CANONICAL_RESOLUTION` gracefully marks `passed=None`. | **VERIFIED** | `test_r07_direct_canonical_case_without_catalog_or_snapshot_is_unscored`, `test_r07_incomplete_canonical_runtime_is_unscored_without_resolver` |
| **R07-T11** | Semicolon Normal | Symmetrical candidate matching against `reference.table.sql_sha256` across single optional terminal semicolons and whitespace. | **VERIFIED** | `test_r07_reference_proof_allows_only_optional_single_terminator`, `test_r07_matching_hash_cannot_prove_malformed_or_multistatement_candidate`, `test_r07_semicolon_inside_line_comment_is_not_a_statement_terminator` |
| **R07-T12** | Complete Accounting | `RunSummary` maintains `total_cases == scored_cases + unscored_cases + unsubmitted_cases`. `pending_triage_cases` is a subset of scored failures. | **VERIFIED** | `test_r07_summary_categories_reconcile_without_double_counting`, `test_r07_sealed_writer_outputs_metadata_and_consistent_counts_only`, `test_r07_invalid_accounting_cannot_be_written` |
| **R07-T13** | Runner Regressions | All 4 historical runner regression cases pass without failure. | **VERIFIED** | `test_direct_run_does_not_need_model_template_or_warmup`, `test_question_run_requires_guarded_tuning_warmup_and_never_scores_it`, `test_required_evaluation_inputs_remain_unscored`, `test_failed_warmup_reports_unsubmitted_ids_without_per_case_result` |
| **R07-T14** | Sealed Holdout | Benchmark holdout data is never exposed; `EvaluationRecordWriter` emits metadata-only JSONL entries without embedding private payloads. | **VERIFIED** | `test_r07_sealed_writer_outputs_metadata_and_consistent_counts_only`, `test_r07_summary_rejects_payload_fields_even_in_sealed_lane` |

---

## 9. Independently Measured Test Results

All test runs executed in `H:\STARK_T2SQL_R02_ENV\Scripts\python.exe` with `$env:PYTHONPATH='src;.'` and `$env:STARK_TEST_ENABLE_DB_INTEGRATION='0'`:

1. **Prescribed Evaluation Suite:**
   ```powershell
   python -m pytest tests/test_runner_contracts.py tests/test_evaluation_contracts.py tests/test_run_record_contracts.py -q -ra
   ```
   **146 passed, 17 skipped, 0 failed** in 0.92s.
2. **Expanded Suite (including Canary Protocol):**
   ```powershell
   python -m pytest tests/test_runner_contracts.py tests/test_evaluation_contracts.py tests/test_run_record_contracts.py tests/test_r07_canaries.py -q -ra
   ```
   **180 passed, 17 skipped, 0 failed** in 0.73s.
3. **Full Offline Test Suite:**
   ```powershell
   python -m pytest -q -ra
   ```
   **1,449 passed, 58 skipped, 0 failed** in 48.43s.

### Breakdown of the 58 Offline Skips:
- 32 parser representation tests excluded from the supplied test approval fixture (`tests/test_validator_contracts.py`).
- 16 wall-clock AST lint checks awaiting external review input `STARK_TEST_WALLCLOCK_REVIEW_PATH` (`tests/test_evaluation_contracts.py`).
- 6 live database integration checks requiring a live PostgreSQL instance (`tests/test_database_integration.py`).
- 1 live direct composition database integration check (`tests/test_runner_contracts.py:115`).
- 1 live database seed/reset check (`tests/test_seed_generation.py:390`).
- 1 external adversarial scope review check awaiting `STARK_TEST_ADVERSARIAL_SCOPE_PATH` (`tests/conftest.py:33`).
- 1 external reference review check awaiting `STARK_TEST_REFERENCE_REVIEW_PATH` (`tests/conftest.py:33`).

---

## 10. Frozen-File Integrity & PR Diff Analysis

The diff for Draft PR #22 was audited against the integration baseline (`afdd4b661fe21d999a1c121f4fd272bd0e423ff6`):
- **Permitted Modified Files:**
  - `src/stark_t2sql/evaluation/reference.py`
  - `src/stark_t2sql/evaluation/failure_classes.py`
  - `src/stark_t2sql/evaluation/runner.py`
  - `src/stark_t2sql/evaluation/records.py`
  - `tests/test_evaluation_contracts.py`
  - `tests/test_r07_canaries.py`
  - `tests/test_run_record_contracts.py`
  - `tests/test_runner_contracts.py`
  - `Codex_R07_Work_Log.md`
  - `Antigravity_R07_Review.md`
- **Frozen File Verification:**
  - `schema.sql`: Unmodified
  - `seed_data.py`: Unmodified
  - `fixture_manifest.json`: Unmodified
  - `fixture_pg_dump.sql`: Unmodified
  - `src/inference/prompt_template.txt`: Unmodified
  - `policy/access_matrix.yaml`: Unmodified
  - `semantic/catalog.yaml`: Unmodified
  - `src/stark_t2sql/evaluation/attribution.py`: Unmodified
  - `src/stark_t2sql/evaluation/holdout.py`: Unmodified
  - `AGENTS.md`: Unmodified
  - `pyproject.toml`: Unmodified
  - Benchmark holdout partition content: Zero modifications or unauthorized reads.

---

## 11. Architecture & Progress Display Updates

1. **R06 Baseline Verification:** Confirmed merge of R06 PR #21 into `gemini/full-remediation-review` at commit `afdd4b661fe21d999a1c121f4fd272bd0e423ff6` on `2026-10-15T17:06:53-05:00` by `Vivek-k24`.
2. **`ops/progress.json` Updates:**
   - Updated `github_base_sha` to `afdd4b661fe21d999a1c121f4fd272bd0e423ff6`.
   - Updated Gate R06 state to `MERGED` with merge SHA `afdd4b661fe21d999a1c121f4fd272bd0e423ff6` and `issue_state: closed`.
   - Appended Gate R07 milestone:
     - `state: "VERIFIED — AWAITING MERGE"`
     - `pr: 22`
     - `issue: 9`
     - `merge_sha: "not merged"`
     - `tests: {"failed": 0, "passed": 1449, "scope": "offline", "skipped": 58}`
     - `evidence_url: "https://github.com/Vivek-k24/Stark_T2SQL/blob/70f74589e5ad487968a496e86e5c26856091833a/Codex_R07_Work_Log.md"`
     - `evidence_sha256: "21a43dd97e614ce54ca03c7596c397e9deb7e6a25e56bf7c485c44cdabde6a5a"`
3. **Canonical UI Generation:**
   Executed `python -m ops.progress` and normalized line endings to retain LF. Confirmed that only the progress block between `<!-- STARK_PROGRESS_BEGIN -->` and `<!-- STARK_PROGRESS_END -->` changed in `STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html`.

---

## 12. Local Browser UI Synchronization

1. **Pre-Copy Audit & Backup:**
   - Primary path: `H:\STARK T2SQL\STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html`
   - Legacy browser path: `H:\STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html.html`
   - Prior to synchronization, both files were hash-identical (`16033C0B77F15BE8CC27B3D157F81BC4B70A79B38BD40E8454ACB56598C55BCD`).
   - Backup of the legacy browser copy was created outside the repository at:
     `C:\Users\User\.gemini\antigravity\brain\168e5d71-9b0a-4dec-8221-3b995bd2a5c2\backup_20261015_STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html.html`
2. **Copy & Hash Verification:**
   - Synchronized the reviewed repository HTML to `H:\STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html.html`.
   - On-disk SHA-256 verification:
     - `H:\STARK T2SQL\STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html`: `21F76C67BE8A1FAB2A485B48CBC4553E1F8C2A623CD6A440AC48BDC2A7C38AB4` (`LOCAL_UI_UPDATED`)
     - `H:\STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html.html`: `21F76C67BE8A1FAB2A485B48CBC4553E1F8C2A623CD6A440AC48BDC2A7C38AB4` (`LOCAL_UI_UPDATED`)
   - Both files are confirmed SHA-256 identical and up to date.

---

## 13. Security Risks, Mock Boundaries & Outstanding Prerequisites

1. **Simulated Canary Test Boundary:** The new canary suite in `tests/test_r07_canaries.py` executes against mocked database cursors and synthetic personas. While query structure, parameters, and AST shapes are strictly verified, these tests do not constitute live PostgreSQL RLS validation.
2. **Live Prerequisites for Gate R09:** Full live PostgreSQL RLS enforcement, credential separation, and wall-clock profile verification remain external prerequisites deferred to Gate R09.
3. **Protocol Stopping Rule:** In accordance with `AGENTS.md`, Antigravity stops here. PR #22 is NOT merged, `main` is untouched, and Gate R08 is NOT started.

<!-- STARK_HANDOFF_V1
{"gate": "R07", "implementation_ready": true, "phase": "verification", "status": "VERIFIED_APPROVE", "subject_sha": "70f74589e5ad487968a496e86e5c26856091833a", "tests": {"failed": 0, "passed": 1449, "scope": "offline", "skipped": 58}}
-->
