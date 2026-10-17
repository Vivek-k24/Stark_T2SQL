# STARK T2SQL — Backend ↔ UI contract

**Owner:** backend/integration (Claude Code). **Consumer:** Streamlit UI (Antigravity, branch `agent/antigravity-ui-step29`).
**Status:** describes the API that exists in source on `codex/r09-remediation` at `986e4e1` plus the primary checkout's uncommitted runtime-path changes. It doesn't certify a live runtime. On 2026-10-16 the live persona runtime is **BLOCKED**. See §9.

If something in this file conflicts with the code, the code wins. Report the mismatch here; do not work around it in the UI.

---

## 1. The single capability the UI receives

The UI gets **one object**, a `PersonaApplication`. It does not import `answer()`, executors, connections, the validator, or `ExecutionMode`.

```python
from stark_t2sql.pipeline.orchestrator import load_persona_runtime

application = load_persona_runtime()      # -> PersonaApplication (process-cached)
```

`app.py` already does this, and only when `STARK_ENABLE_CONNECTED_UI == "1"` and the E0 visual baseline file exists. If the call raises anything, the UI shows `views.SERVICE_UNAVAILABLE` and stops. It never shows exception text.

The structural type the views depend on is `stark_t2sql.ui.views.PersonaViewApplication`:

```python
class PersonaViewApplication(Protocol):
    @property
    def personas(self) -> tuple[Persona, ...]: ...
    def answer(self, persona: Persona, question: str, as_of_date: date) -> SafeResponse: ...
    def semantic_view(self, persona: Persona) -> tuple[SafeConcept, ...]: ...
    def policy_view(self, persona: Persona) -> tuple[SafePolicyRow, ...]: ...
```

### FR-8.4 single entry point

`PersonaApplication.answer(...)` calls the canonical
`stark_t2sql.pipeline.answer.answer(persona, question, as_of_date, mode) -> Outcome`
with `mode=ExecutionMode.FULL` **hard-coded in source** (`orchestrator.py`, `PersonaApplication.answer`). It then projects the result with `safe_response()`. The evaluation harness calls the same `answer()` through `HarnessApplication`. No other execution path exists.

**FULL-only (FR-2.4, FR-2.5, FR-10.5, NFR-10).** The UI signature has no `mode` parameter. Do not add one, and do not read a mode from widgets, query parameters, session state or environment variables. `NO_PROMPT_FILTER`, `NO_VALIDATOR` and `UNCONTROLLED` are reachable only through `HarnessApplication`. That requires a sealed capability and a disposable-clone `EvaluationConnectionSource`. A direct `answer(..., mode=UNCONTROLLED)` call without that capability raises `HarnessSafetyStopError`.

## 2. Personas

`application.personas` returns exactly four `stark_t2sql.contracts.Persona` objects. They are frozen dataclasses with these fields: `display_name`, `business_role`, `principal_id`, `login_role`.

| Registry key | `display_name` | `business_role` | Principal |
|---|---|---|---|
| `payroll` | Payroll specialist | `app_payroll` | 326 |
| `hr_1` | HR business partner #1 | `app_hr_bp` | resolved from fixture at startup |
| `hr_2` | HR business partner #2 | `app_hr_bp` | resolved from fixture at startup |
| `sales` | Sales manager | `app_sales_mgr` | derived from fixture at startup |

Rules:
- Pass the `Persona` object you got from `application.personas` back to `answer()`, `semantic_view()` or `policy_view()`. Never construct a `Persona` in the UI, and never let the user type a principal ID (FR-1.2).
- The UI may show `display_name` and `business_role`. Don't show `login_role` or `principal_id` in the ordinary persona view. They're harmless synthetic values, but FR-8.7 keeps the persona view minimal.
- The UI must state that identity is simulated and no security claim depends on real authentication (FR-10.6).

## 3. Request arguments

| Argument | Type | Rule |
|---|---|---|
| `persona` | `Persona` | One of `application.personas`. |
| `question` | `str` | Non-empty after strip. ≤ 16,384 UTF-8 bytes. Pass through **unchanged**: no trimming, rewriting or filtering (FR-2.3). |
| `as_of_date` | `datetime.date` | Required. UI default is `stark_t2sql.config.FIXTURE_AS_OF_DATE` (2026-10-12) (FR-2.2). Never derive it from the wall clock. |

An invalid input returns `status=ERROR`, `reason_code=INVALID_INPUT`, `stopping_layer=INPUT`. It does not raise.

## 4. The response: `SafeResponse` (only these fields reach the persona view)

`stark_t2sql.contracts.SafeResponse` is frozen. Prefer `response.to_dict()` for rendering:

```python
{
  "status": str,            # OutcomeStatus value, see §5
  "stopping_layer": str,    # StoppingLayer value, see §5
  "reason_code": str,       # ReasonCode value
  "as_of_date": "YYYY-MM-DD",
  "message": str,           # static public text keyed by reason_code; never DB/model text
  "columns": [str, ...],    # ANSWERED only, else []
  "rows": [[cell, ...], ...],  # ANSWERED only; cells are str|int|bool|float|None (Decimals as exact strings, dates ISO)
  "truncated": bool,
  "scope_note": str | None, # e.g. "Results are limited to direct reports."
  "truncation_note": str | None,  # "Results are limited to 1000 rows and are incomplete."
  "elapsed_ms": float | None,
  "clarification": {"question": str, "options": [str, ...]} | None
}
```

**Forbidden in the ordinary persona view (FR-8.7, FR-10.8, R-05):** raw model output, extracted, regenerated or executed SQL, database error text, SQLSTATE, tracebacks, fingerprints, the trace path and request IDs. These live only on the internal `Outcome` and in `logs/events.jsonl`. `SafeResponse` has no such fields. Do not reach into `Outcome` or the trace from the UI, and do not add a "developer" tab or hidden expander. Developer diagnostics stay in local harness reports and logs.

## 5. Status vocabulary

`OutcomeStatus`, with the persona-facing interpretation:

| Status | Meaning | UI treatment |
|---|---|---|
| `ANSWERED` | Validated SQL ran under the persona's DB role. | Show the table, `scope_note`, and `truncation_note` if `truncated`. A truncated result must not look complete (FR-8.3). |
| `BLOCKED_VALIDATOR` | The AST validator refused the SQL (for example a non-permitted table, write, or catalog/function abuse). | "Blocked" banner. Name the layer: **Query validator**. |
| `BLOCKED_DB` | PostgreSQL refused it (SQLSTATE 42501: grant/column/RLS boundary). | "Blocked" banner. Name the layer: **Database permissions**. |
| `CLARIFICATION_REQUIRED` | Governed vocabulary was ambiguous. **No model call and no SQL ran.** | Show `clarification.question` and `options`. It's neither an answer nor a security block (FR-8.6). |
| `MODEL_SQL_ERROR` | The model produced SQL that failed with a syntax or unknown-object error. | "Couldn't produce a usable query." |
| `MODEL_ERROR` | Model unavailable, extraction failed, or generation hit the token cap. | Neutral error banner. |
| `TIMEOUT` | Generation deadline (120 s), statement timeout (15 s) or client deadline exceeded. | Neutral timeout banner. |
| `ERROR` | Invalid input, configuration, dependency, internal fault, or single-flight contention. | Neutral error banner. |
| `HARNESS_SAFETY_STOP` | Harness-only. Should never appear in the persona UI. | Treat as an error if seen. |

`StoppingLayer` values: `NONE` (answered), `CONFIGURATION`, `INPUT`, `CONTEXT` (clarification), `MODEL`, `EXTRACTION`, `VALIDATOR`, `DATABASE`, `HARNESS`, `RESPONSE`, `INTERNAL`. The UI names the stopping layer for blocked outcomes (E7 exit, C5).

Use `response.message` for the reason text. Don't map `reason_code` to your own prose that adds detail the backend withheld.

## 6. Results shape

- `columns` holds names only. `rows` is a list of equal-width lists. Values are already JSON-safe through `to_dict()`.
- An empty result is `ANSWERED` with `rows == []`. Show "No rows." and do not treat it as a block.
- The row cap is 1,000 (`limits.output_row_cap`). `truncated=True` means more rows existed. `truncation_note` is set.
- `row_scope` and `scope_note` describe the *policy* scope (all, direct reports, assigned divisions). They are not a count claim.

## 7. Concurrency (FR-10.7)

The UI owns the session busy flag through `stark_t2sql.ui.ui_state.request_guard(st.session_state)`. It sets the flag before `answer()`, resets it in `finally`, and uses a process-wide non-blocking lock. `app.py` short-circuits at the top when `session_is_busy()` is true. The backend additionally holds `_REQUEST_LOCK` in `answer()`. A second concurrent request gets `status=ERROR` back, and nothing is queued. Keep both guards. Disable the Ask button while busy.

A request can take **minutes** on this CPU-only workstation (see §9). Show a visible processing state. Don't add client-side retry loops.

## 8. Offline UI testing: injecting a fake backend

Don't start PostgreSQL or llama.cpp for UI tests. Satisfy `PersonaViewApplication` with a fake and pass it to the view functions:

```python
from datetime import date
from stark_t2sql.contracts import (Persona, SafeResponse, OutcomeStatus, StoppingLayer,
                                   ReasonCode, RowScopeKind, Clarification)

PERSONAS = (
    Persona("Payroll specialist", "app_payroll", 326, "stark_payroll_login"),
    Persona("HR business partner #1", "app_hr_bp", 47, "stark_hr_login"),
    Persona("HR business partner #2", "app_hr_bp", 361, "stark_hr_login"),
    Persona("Sales manager", "app_sales_mgr", 999, "stark_sales_login"),  # TEST_ONLY principal
)

class FakeApplication:
    personas = PERSONAS
    def answer(self, persona, question, as_of_date):
        if "salary" in question and persona.business_role != "app_payroll":
            return SafeResponse(OutcomeStatus.BLOCKED_VALIDATOR, StoppingLayer.VALIDATOR,
                                ReasonCode.VALIDATOR_REJECTED, as_of_date)
        if question.strip() == "headcount":
            return SafeResponse(OutcomeStatus.CLARIFICATION_REQUIRED, StoppingLayer.CONTEXT,
                                ReasonCode.CLARIFICATION_REQUIRED, as_of_date,
                                clarification=Clarification("Which headcount?", ("active_headcount",)))
        return SafeResponse(OutcomeStatus.ANSWERED, StoppingLayer.NONE, ReasonCode.ANSWERED,
                            as_of_date, columns=("n",), rows=((42,),), row_cap=1000,
                            row_scope=RowScopeKind.ALL, elapsed_ms=12.0)
    def semantic_view(self, persona): return ()
    def policy_view(self, persona): return ()
```

Then call `views.render_playground(FakeApplication(), PERSONAS[0])`, or, for `app.py` tests, monkeypatch `stark_t2sql.pipeline.orchestrator.load_persona_runtime` to return the fake. Fake data must be labelled TEST_ONLY or SIMULATED. Never present it as LIVE (AGENTS.md §5). The `SafeResponse` constructor enforces the invariants: no rows unless `ANSWERED`, `truncated` requires `row_cap`, and clarification only with `CLARIFICATION_REQUIRED`.

## 9. Local startup and integration verification

### Offline UI (works today)
```powershell
cd "H:\STARK T2SQL"
python -m ops.serve            # http://127.0.0.1:8501, connected SQL disabled
```

### Offline test suite
```powershell
$env:PYTHONPATH='src;.'; $env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest -q -ra
```
Recorded on 2026-10-16 in the primary checkout: **1,761 passed, 64 skipped, 0 failed**. The skips are pending external inputs or opt-in live gates, not passes.

### Connected UI (BLOCKED as of 2026-10-16)
```powershell
$env:STARK_ENABLE_CONNECTED_UI='1'
python -m ops.serve_connected --enable-connected-ui --runtime-bindings <absolute path to private bindings JSON outside repo>
# serves http://127.0.0.1:8502
```
`load_persona_runtime()` will refuse to start until all of the following exist. Each one needs owner action:
1. STARK security policy installed in `stark_test` (roles, grants, RLS), with its `policy_state_sha256`.
2. Private env vars: `STARK_PG_DATABASE`, `STARK_PAYROLL_PASSWORD`, `STARK_HR_PASSWORD`, `STARK_SALES_PASSWORD`, and the admin password variable named in the bindings.
3. Measured budgets: `STARK_DATABASE_WORK_MEM_KIB`, `STARK_DATABASE_TEMP_FILE_LIMIT_KIB`, `STARK_MODEL_MEMORY_LIMIT_MIB`, `STARK_RESOURCE_MEASUREMENTS_PATH`, `STARK_GGUF_PATH`.
4. A private runtime-bindings JSON holding the owner's attestations (model-service, template and parser review).
5. A model context window that fits the payroll v2 prompt. It measures **8,054 tokens** against the server's **4,096**. HR (3,249) and sales (1,785) fit.

Until then the connected pages show `SERVICE_UNAVAILABLE`, which is correct behaviour. The UI should not try to bypass it.

### Expected latency
On this i5 CPU-only host every request re-processes the whole prompt. The model-card template places the question before the schema, so the prefix cache cannot reuse the schema. The UI must tolerate requests that take minutes. Measured figures are in `H:\STARK_Runtime\CLAUDE_BACKEND_HANDOFF.md`.

## 10. Change protocol

- UI needs a new backend field: request it here. The backend adds it to `SafeResponse` only after checking it is FR-8.7-safe.
- Backend changes `SafeResponse` or `PersonaViewApplication`: update this file in the same commit.
- The UI branch must not modify `src/stark_t2sql/{pipeline,db,security,inference,context,semantic,policy,evaluation}/`, `policy/`, `semantic/`, `schema.sql`, the fixtures or `contracts.py`.

## 2026-10-17 amendment — owner-authorized model-independent metadata

The later `docs/CODEX_LIVE_UI_HANDOFF.md` explicitly authorizes extracting a trusted metadata facade so the actual UI works while SQLCoder is off. This narrowly supersedes the old all-or-nothing startup description and the blanket backend-file restriction above for `pipeline/metadata.py`, optional private-environment plumbing in `db/connections.py`, and its forwarding in `pipeline/orchestrator.py`. It does not authorize a new execution lane or changes to security enforcement, frozen assets or persona contracts.

`inspect_metadata(config, installation_binding=..., environment=...)` performs fixed, read-only inspection of `127.0.0.1:5433/stark_test`. It checks live schema, reviewed installed-policy digest, fixture-derived principals, governed catalog lineage and every restricted connection's existing audits. The returned `MetadataApplication` exposes only predefined personas, `SafeConcept`/`SafePolicyRow` projections, inspection UTC time and scoped employee-count metadata. It has no `answer`, connection, password or raw-catalog surface. Trusted startup sources close before it is returned.

The UI's server-side `Workspace` wraps that facade and optionally the existing genuine `PersonaApplication`. An opaque handle is bound to the server-assigned Streamlit session ID and expires; a browser boolean or another session's handle grants nothing. Masked setup clears password widget state and uses private source mappings rather than global environment assignment. This local operator boundary is **not app-user authentication**. The optional explicitly configured server environment uses the same verification path without populating password widgets.

Playground accepts a typed question even with the model off. Ask is disabled, old results are cleared, and the wrapper independently fails closed if inference is absent/offline. Scoped count metadata is explicitly distinct from a question's answer. Actual online generation still requires all genuine template/parser/model/fixture/policy/runtime inputs and invokes the unchanged canonical FULL-only `PersonaApplication.answer()` path with freshly audited restricted connections. Model startup is not a rendering side effect. ONLINE inference was not executed in this delivery.

The correct launch directory is now `H:\STARK_T2SQL_MAIN_SYNC`; run `& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m ops.serve`. The original checkout, historical startup observations and E0 copies remain untouched. See [operator guide](LIVE_UI_OPERATOR_GUIDE.md), [tracker](LIVE_UI_IMPLEMENTATION_TRACKER.md) and [security impact / pending review](LIVE_UI_SECURITY_REVIEW.md) for actual tested capabilities and remaining gates.
