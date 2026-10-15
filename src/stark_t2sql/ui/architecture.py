"""Read-only FRD 1.8 architecture and roadmap planning metadata.

This is authored source, not a progress journal or a run-result artifact. The
FRD's Section 7 IDs and hierarchy remain intact. A source label means only
that a draft implements the described responsibility; it establishes no epic
exit condition. Unwritten evaluation/test suites remain Not started.

The supplied authoritative E0 HTML was read as text for its six clickable
stage cards, selected-detail inspector, and epic navigator/story/task layout.
These renderers translate that hierarchy into native Streamlit controls,
without copying HTML/JS. E0 visual approval and later UI assessment remain
pending. FRD 1.8 governs the hierarchy despite the prototype's older 1.7 text.
The user's NFR-6 exception permits drafting only, not E1-E8 execution. No
database, inference, fixture, trace, or progress-file operation occurs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProgressLabel(str, Enum):
    NOT_STARTED = "Not started"
    SOURCE = "Implemented in source"
    FUTURE = "Future verification"


@dataclass(frozen=True, slots=True)
class RuntimeStage:
    number: int
    title: str
    purpose: str
    normal_flow: tuple[str, ...]
    failure_paths: tuple[str, ...]
    dependencies: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    security_controls: tuple[str, ...]
    requirement_refs: tuple[str, ...]
    roadmap_refs: tuple[str, ...]
    source_paths: tuple[str, ...]
    future_evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProgressNode:
    ref: str
    title: str
    state: ProgressLabel
    source_paths: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    children: tuple[ProgressNode, ...] = ()
    entry_condition: str | None = None
    exit_condition: str | None = None


_PERSONAS = ("src/stark_t2sql/db/persona.py",)
_POLICY = (
    "policy/access_matrix.yaml",
    "src/stark_t2sql/policy/loader.py",
    "src/stark_t2sql/policy/compiler.py",
)
_GRANTS = ("src/stark_t2sql/policy/grants.py",)
_RLS = ("src/stark_t2sql/policy/rls.py",)
_PRIVILEGES = ("src/stark_t2sql/policy/privileges.py",)
_APPLY = ("src/stark_t2sql/db/policy_apply.py",)
_EXECUTOR = (
    "src/stark_t2sql/db/connections.py",
    "src/stark_t2sql/db/executor.py",
)
_CATALOG = (
    "semantic/catalog.yaml",
    "src/stark_t2sql/semantic/catalog.py",
    "src/stark_t2sql/semantic/models.py",
)
_SEMANTICS = (
    "src/stark_t2sql/semantic/resolver.py",
    "src/stark_t2sql/semantic/metrics.py",
    "src/stark_t2sql/semantic/entitlements.py",
    "src/stark_t2sql/semantic/contracts.py",
)
_CONTEXT = (
    "src/stark_t2sql/context/builder.py",
    "src/stark_t2sql/context/schema_filter.py",
    "src/stark_t2sql/context/semantic_filter.py",
)
_VALIDATOR = (
    "src/stark_t2sql/security/validator.py",
    "src/stark_t2sql/security/function_policy.py",
)
_PROMPT = (
    "src/stark_t2sql/inference/template.py",
    "src/stark_t2sql/inference/prompt_builder.py",
)
_EXTRACTION = ("src/stark_t2sql/inference/extract.py",)
_CLIENT = ("src/stark_t2sql/inference/client.py",)
_PIPELINE = (
    "src/stark_t2sql/pipeline/answer.py",
    "src/stark_t2sql/pipeline/orchestrator.py",
    "src/stark_t2sql/pipeline/response.py",
    "src/stark_t2sql/contracts.py",
)
_TRACE = ("src/stark_t2sql/pipeline/trace.py",)
_UI = (
    "app.py",
    "src/stark_t2sql/ui/ui_state.py",
    "src/stark_t2sql/ui/views.py",
    "src/stark_t2sql/ui/architecture.py",
)
_E0 = ("STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html",)


STAGES: tuple[RuntimeStage, ...] = (
    RuntimeStage(
        number=1,
        title="Identify persona",
        purpose="Bind a predefined simulated persona to the ordinary FULL request path.",
        normal_flow=(
            "Load the four persona definitions derived from the authoritative fixture.",
            "Resolve the selected display identity through the trusted persona registry.",
            "Keep question text unchanged and require the explicit as-of date.",
            "Set the UI busy flag and acquire the single-flight request guard before calling answer().",
        ),
        failure_paths=(
            "Unavailable fixture-derived personas or a missing configured principal prevent connected startup.",
            "Unknown persona, empty question, or invalid date stops at request input handling.",
            "A bypass mode supplied through UI text, parameters, or request fields is rejected.",
            "An occupied request guard prevents a second generation request; cleanup releases the guard.",
        ),
        dependencies=(
            "Authoritative fixture and generated persona mapping, including the derived sales-manager identity.",
            "Trusted local role/login configuration; credentials remain outside UI metadata.",
            "E0 visual approval plus E1-E6 runtime exit evidence before connected use.",
        ),
        inputs=("Selected predefined persona", "Unchanged question", "Explicit as-of date"),
        outputs=("Trusted persona/request binding", "FULL mode", "Ephemeral busy state"),
        security_controls=(
            "No arbitrary role or principal input; a persona selector is a simulation, not authentication.",
            "Ordinary UI has no ablation control or developer diagnostic route.",
            "Busy flag is set before answer(), with single-flight exclusion and finally cleanup.",
        ),
        requirement_refs=("FR-1.1-FR-1.4", "FR-2.1-FR-2.5", "FR-10.5-FR-10.7", "NFR-10"),
        roadmap_refs=("E0/S0.1/T0.1.1-T0.1.2", "E3/S3.3/T3.3.1-T3.3.2", "E7/S7.1/T7.1.1-T7.1.4"),
        source_paths=_PERSONAS + _PIPELINE + _UI,
        future_evidence=(
            "Fixture-backed principal existence and persona generation assessment.",
            "FULL-only input/route isolation cases and concurrent-click UI scenarios (future Prompt 5 source).",
            "E7 persona walkthrough and keyboard/responsive behavior assessment.",
        ),
    ),
    RuntimeStage(
        number=2,
        title="Build filtered physical + semantic context",
        purpose="Resolve governed vocabulary before generation and provide only entitled context.",
        normal_flow=(
            "Resolve terms to documented meanings using the governed semantic catalog.",
            "Return CLARIFICATION_REQUIRED immediately for unresolved ambiguity, before inference or SQL.",
            "Compile permitted physical DDL, excluding hidden objects and unsafe foreign-key references.",
            "Compile semantic entities, metrics, joins, and temporal rules supported by role permissions.",
            "Create deterministic physical and semantic fingerprints for prompt version 2.",
        ),
        failure_paths=(
            "Ambiguity returns a safe clarification request without generating or executing SQL.",
            "Missing trusted metadata, dependency drift, or entitlement mismatch stops context construction.",
            "A metric backed by inaccessible columns is excluded; I-01 remains unresolved.",
            "Full-schema baseline context requires an isolated harness capability and frozen E2 input binding.",
        ),
        dependencies=(
            "Authoritative schema metadata, access matrix, semantic catalog, and their recorded versions.",
            "Independent canonical definitions and later role-scoped reference cases.",
            "Frozen full-schema baseline bytes and digest only for separately authorized harness use.",
        ),
        inputs=("Trusted role", "Question and as-of date", "Schema, matrix, and governed catalog"),
        outputs=("Role-filtered DDL", "Role-filtered semantic block", "Context fingerprints or clarification"),
        security_controls=(
            "Context filtering minimizes disclosure; validator and database provide authorization.",
            "Metric entitlements follow backing table/column dependencies and approved join paths.",
            "I-01: visible sales-manager rows may be counted without claiming canonical active headcount.",
            "Preserve E2 prompt version 1 unchanged; FULL persona requests use version 2.",
        ),
        requirement_refs=("FR-3.1-FR-3.8", "FR-7", "FR-8.6", "NFR-3", "R-02", "I-01"),
        roadmap_refs=("E5/S5.1/T5.1.1-T5.1.6", "E5/S5.2/T5.2.1-T5.2.4", "E5/S5.3/T5.3.1-T5.3.4"),
        source_paths=_POLICY + _CATALOG + _SEMANTICS + _CONTEXT,
        future_evidence=(
            "Deterministic context fingerprints and absence of restricted vocabulary in each role view.",
            "Independent semantic reference SQL for dates, synonyms, joins, and ambiguity.",
            "Role-scoped accuracy/leak cases, drift cases, and product-owner disposition of I-01.",
        ),
    ),
    RuntimeStage(
        number=3,
        title="Generate local SQL",
        purpose="Build the immutable model-card prompt and extract a complete local generation.",
        normal_flow=(
            "Read the locally supplied authoritative model-card template and retain its fingerprint.",
            "Insert question and as-of line inside QUESTION tags without changing template source bytes.",
            "Generate through the explicitly configured 127.0.0.1 llama.cpp endpoint.",
            "Use temperature zero, fixed seed, 300-token cap, first-semicolon stop, and 120-second timeout.",
            "Apply FR-4.7 whitespace/delimiter extraction and retain raw model text only in private diagnostics.",
        ),
        failure_paths=(
            "Missing authoritative template stops prompt construction; no replacement template is invented.",
            "Non-loopback endpoint configuration is rejected before communication.",
            "Unavailable model service or transport failure maps to a non-sensitive runtime response.",
            "Empty extracted SQL maps to FC-EXTRACT; token exhaustion maps to FC-TRUNCATED-GEN.",
            "Elapsed generation timeout maps to FC-TIMEOUT-GEN; incomplete candidates never execute.",
        ),
        dependencies=(
            "Exact locally present SQLCoder-7B-2 model-card template and recorded template fingerprint.",
            "Later local model binary/service, one slot, prefix caching, and measured workstation budgets.",
            "Actual model/build provenance and later beam-support/repeatability measurements.",
        ),
        inputs=("Filtered physical and semantic context", "Question and as-of date", "Immutable prompt template"),
        outputs=("Extracted candidate SQL (internal)", "Private raw generation", "Generation timings and fingerprints"),
        security_controls=(
            "No cloud inference, runtime downloads, or external hosts.",
            "Warmup is a separate callable excluded from scoring; no warmup is performed by this metadata.",
            "Generated SQL is untrusted and cannot directly invoke an execution connection.",
            "Prompt determinism does not establish byte-identical SQL or result equivalence.",
        ),
        requirement_refs=("FR-4.1-FR-4.9", "FR-3.7", "NFR-1", "NFR-2", "NFR-4", "NFR-5"),
        roadmap_refs=("E1/S1.3/T1.3.1-T1.3.3", "E2/S2.1/T2.1.1-T2.1.3", "E2/S2.2/T2.2.1-T2.2.2", "E5/S5.2/T5.2.4"),
        source_paths=_PROMPT + _CLIENT + _EXTRACTION,
        future_evidence=(
            "Ten hand-authored extraction outputs and token-cap versus elapsed-time scenarios.",
            "Actual service configuration, warmup exclusion, model provenance, and resource measurements.",
            "Separate repeated-run exact-SQL agreement and execution-result equivalence measurements.",
        ),
    ),
    RuntimeStage(
        number=4,
        title="Deterministic validator",
        purpose="Reject untrusted SQL shapes and review functions before issuing regenerated SELECT SQL.",
        normal_flow=(
            "Require the actual installed-parser review profile and individually reviewed function policy.",
            "Parse PostgreSQL SQL with plural parse() and require exactly one SELECT-family statement.",
            "Review every node and executable call, table name, schema qualifier, and CTE alias.",
            "Regenerate PostgreSQL SQL and require parse/regeneration idempotence.",
            "Issue a one-use reviewed execution receipt for the regenerated SQL and bound persona/policy.",
        ),
        failure_paths=(
            "Absent parser/function review evidence, parser failures, or unknown node shapes fail closed.",
            "Writes, commands, multi-statements, forbidden schemas/tables, and table functions are blocked.",
            "Configuration-changing, privilege-bearing, catalog, costly, nested unsafe, or unknown calls are blocked.",
            "Regeneration inconsistency or a receipt binding mismatch leaves the candidate unexecuted.",
        ),
        dependencies=(
            "Actual sqlglot profile evidence with reviewed AST layouts and function signatures.",
            "Role-permitted table set from the shared matrix and trusted policy fingerprint.",
            "Later accepting/rejecting cases and expanding legitimate reference SQL sets.",
        ),
        inputs=("Untrusted extracted SQL", "Trusted persona and matrix", "Reviewed parser/function profile"),
        outputs=("Regenerated reviewed SQL receipt (internal)", "Safe rejection reason", "Private validator diagnostic"),
        security_controls=(
            "Parser recognition is not function safety; executable calls default to deny.",
            "Database grants enforce columns; evaluation lint owns wall-clock misuse.",
            "The validator does not estimate cost; database/executor budgets address resource work.",
            "SET principal spoofing has a known validator-only preventive dependency and is not authentication.",
        ),
        requirement_refs=("FR-5.1-FR-5.11", "FR-6.7", "FR-6.11", "FR-8", "NFR-6", "R-06", "Section 2.4"),
        roadmap_refs=("E4/S4.1/T4.1.1-T4.1.5", "E4/S4.2", "E4/S4.3/T4.3.1-T4.3.3", "E4/S4.4/T4.4.1", "E8/S8.3/T8.3.3-T8.3.4"),
        source_paths=_VALIDATOR + _EXECUTOR,
        future_evidence=(
            "Parser node/function review and positive/negative signature contracts.",
            "Acceptance A: all legitimate references admitted; repeat whenever those sets grow.",
            "Acceptance B: original/regenerated result equivalence; C: direct adversarial cases with validator.",
            "Explicit stopping-layer attribution for principal spoofing and other single-layer cases.",
        ),
    ),
    RuntimeStage(
        number=5,
        title="Least-privilege Postgres execution",
        purpose="Execute only the regenerated reviewed SQL through the existing restricted executor.",
        normal_flow=(
            "Open the persona's permitted local login connection and begin a per-request read-only transaction.",
            "Set the principal session setting before SET LOCAL ROLE in the exact FR-6.3 order.",
            "Apply role/table/column grants and RLS scope with no superuser or BYPASSRLS candidate connection.",
            "Apply statement timeout and measured resource/cancellation controls.",
            "Fetch row cap plus one, report truncation, and close/roll back the transaction in cleanup.",
        ),
        failure_paths=(
            "Missing credentials, installed-policy binding, clone provenance, or measured budgets stops execution.",
            "Database permission denial maps to a safe blocked status; detailed SQLSTATE stays internal.",
            "Statement timeout maps distinctly from generation timeout; cancellation/cleanup remains bounded.",
            "Potentially unsafe harness candidates stop unexecuted with HARNESS_SAFETY_STOP.",
            "RLS-empty results are empty authorized results, not fabricated evidence of a permission denial.",
        ),
        dependencies=(
            "Later installed grants/RLS, hardened helper/defaults, function-level revoke, and real policy fingerprint.",
            "Authoritative fixture plus derived personas and independently assessed role scopes.",
            "Local credentials, measured database budgets, and separately isolated evaluation clone capabilities.",
        ),
        inputs=("One-use reviewed SQL receipt", "Trusted persona", "Runtime resource and connection configuration"),
        outputs=("Authorized columns and rows", "Cap-plus-one truncation flag", "Private SQLSTATE/timings"),
        security_controls=(
            "Database is the role-level boundary; principal identity remains a simulated session setting.",
            "FORCE RLS and explicit payroll scope; no business-role membership or administrative model execution.",
            "Harden helper owner/search path/schema privileges and restrict set_config EXECUTE.",
            "Output row cap does not bound execution work; measured cancellation/resource controls are separate.",
            "Harness bypass modes require least-privilege isolated clone capabilities, never UI controls.",
        ),
        requirement_refs=("FR-6.1-FR-6.11", "FR-8.1", "FR-8.2", "NFR-1", "NFR-4", "NFR-10", "R-03", "R-06"),
        roadmap_refs=("E3/S3.2/T3.2.1-T3.2.6", "E3/S3.4/T3.4.1-T3.4.3", "E3/S3.5/T3.5.1-T3.5.2", "E3/S3.6/T3.6.1-T3.6.2", "E2/S2.3/T2.3.2"),
        source_paths=_GRANTS + _RLS + _PRIVILEGES + _APPLY + _EXECUTOR,
        future_evidence=(
            "Actual matrix versus table/column privileges and independently computed row scopes.",
            "Database-only S1-S9 observations, including catalog exposure and session-setting risks.",
            "Timeout, costly-function/resource limits, cancellation, cleanup, and row truncation scenarios.",
            "Least-privilege clone provenance and unsafe-candidate non-execution evidence.",
        ),
    ),
    RuntimeStage(
        number=6,
        title="Safe results + internal trace",
        purpose="Return only safe persona results and retain one private structured event per future request.",
        normal_flow=(
            "Classify the pipeline outcome with status, safe reason, stopping layer, and explicit as-of date.",
            "Project only authorized results, approved column metadata, scope/cap notes, and safe timings.",
            "Append a single structured JSONL request event through the authored trace writer at future runtime.",
            "Keep SQL, model text, detailed errors, and artifact fingerprints in local CLI/harness diagnostics.",
            "Release request resources and reset the UI busy flag in finally handling.",
        ),
        failure_paths=(
            "Unavailable backend/model maps to a non-sensitive persona error without technical detail.",
            "Trace-write or projection failure requires fail-closed request handling, not a silent disclosure fallback.",
            "Clarification, validator rejection, database rejection, and timeouts retain distinct stopping reasons.",
            "Absent data or metrics remain unavailable; no fake fixture outputs, scores, or run fingerprints appear.",
        ),
        dependencies=(
            "Shared Outcome and safe-response contracts plus policy-aware execution results.",
            "Future writable local trace destination; synthetic-only fixture provenance.",
            "Later independent evaluator, run records, attribution suites, and sealed holdout boundary procedures.",
        ),
        inputs=("Private classified Outcome", "Authorized rows and columns", "Actual request timings/fingerprints"),
        outputs=("Safe persona banner and results", "Optional safe latency summary", "Private runtime JSONL event"),
        security_controls=(
            "Normal persona views never render raw/executed SQL, database errors, model output, or traces.",
            "Developer diagnostics are local CLI/harness logs, with no hidden Streamlit tab or parameter.",
            "Progress metadata does not establish backend privileges or certify security/accuracy.",
            "No real PII; no result-to-model feedback or natural-language result summary path.",
        ),
        requirement_refs=("FR-8", "FR-9.3", "FR-9.7", "FR-10.7-FR-10.8", "NFR-7", "R-04", "R-05"),
        roadmap_refs=("E6/S6.1/T6.1.1-T6.1.3", "E6/S6.2", "E7/S7.1/T7.1.3-T7.1.4", "E8/S8.1-S8.4"),
        source_paths=_PIPELINE + _TRACE + _UI,
        future_evidence=(
            "One-event request tracing for each success/failure path without diagnostic disclosure.",
            "Allowed, scoped, blocked, empty, capped, and clarification persona walkthroughs.",
            "Measured accuracy/over-blocking and adversarial attribution; no zero-leak claim from source alone.",
            "Frozen tuning/holdout assignments and exposure records at defined future boundaries.",
        ),
    ),
)


def _node(
    ref: str,
    title: str,
    state: ProgressLabel = ProgressLabel.NOT_STARTED,
    *,
    paths: tuple[str, ...] = (),
    notes: tuple[str, ...] = (),
    children: tuple[ProgressNode, ...] = (),
    entry: str | None = None,
    exit: str | None = None,
) -> ProgressNode:
    """Construct static source metadata; never infer state from a filesystem."""
    default_note = {
        ProgressLabel.NOT_STARTED: "No completion or runtime evidence is claimed.",
        ProgressLabel.SOURCE: "Source draft only; no runtime or epic-exit evidence is claimed.",
        ProgressLabel.FUTURE: "Callable source is present; later runtime assessment remains outstanding.",
    }[state]
    return ProgressNode(ref, title, state, paths, notes or (default_note,), children, entry, exit)


# Preserve actual FRD Section 7 IDs. Stories without task IDs remain stories;
# E10 has no invented story/task children. Labels are static authoring scope.
EPICS: tuple[ProgressNode, ...] = (
    _node(
        "E0", "STATIC UI PROTOTYPE AND REVIEW GATE [CURRENT]", ProgressLabel.SOURCE,
        paths=_E0,
        notes=("Supplied E0 source is present and its layout was read as text; visual approval and offline/browser evidence remain pending. The artifact is preserved unchanged.",),
        exit="Local browser file demonstrates the intended workflow; feedback collected; user explicitly authorizes further implementation.",
        children=(
            _node("S0.1", "Present architecture and personas", ProgressLabel.SOURCE, paths=_E0, children=(
                _node("T0.1.1", "Static role selector (four personas); mock IDs", ProgressLabel.SOURCE, paths=_E0),
                _node("T0.1.2", "Static question input; fixed as_of_date; mode preview", ProgressLabel.SOURCE, paths=_E0),
                _node("T0.1.3", "Labeled simulated answered, blocked, and scoped outcomes", ProgressLabel.SOURCE, paths=_E0),
            )),
            _node("S0.2", "Visualize the proposed product", ProgressLabel.SOURCE, paths=_E0, children=(
                _node("T0.2.1", "Result, SQL, trace, history mock panels", ProgressLabel.SOURCE, paths=_E0),
                _node("T0.2.2", "Role-filtered semantic catalog and access policy summary", ProgressLabel.SOURCE, paths=_E0),
                _node("T0.2.3", "Six clickable runtime stages with deep dependency, normal-flow, blocked/error, artifact, test, and handoff branches", ProgressLabel.SOURCE, paths=_E0),
                _node("T0.2.4", "Expandable E0-E10 epic/story/task read-only progress hierarchy", ProgressLabel.SOURCE, paths=_E0, notes=("Prototype hierarchy is source only; this E7 planning view uses the actual FRD 1.8 titles and IDs.",)),
                _node("T0.2.5", "Responsive layout; keyboard interaction; no network requests", ProgressLabel.FUTURE, paths=_E0, notes=("CSS/interaction source exists; no browser, keyboard, responsive, or network observation is performed.",)),
            )),
            _node("S0.3", "Review gate", ProgressLabel.FUTURE, paths=_E0, notes=("Prototype source exists; explicit visual approval and runtime observations remain unavailable.",), children=(
                _node("T0.3.1", "User reviews labels, navigation, examples, role behavior, observability placement, and semantic-catalog visibility", ProgressLabel.FUTURE, paths=_E0),
                _node("T0.3.2", "Record requested UI edits and explicit go/no-go"),
                _node("T0.3.3", "No PostgreSQL, llama.cpp, Python service, REST API, Streamlit backend, migration, deployment, or fixture seeding in E0", ProgressLabel.FUTURE, paths=_E0, notes=("E0 source is preserved; browser/network observation remains future evidence, not a source-only conclusion.",)),
            )),
        ),
    ),
    _node(
        "E1", "ENVIRONMENT AND FIXTURE",
        notes=("No toolchain installation, fixture loading/export, service startup, or measurements are authorized by this drafting assignment.",),
        exit="Stack runs; fixture assessed and exported; measurements recorded.",
        children=(
            _node("S1.1", "Toolchain installed and pinned", children=(
                _node("T1.1.1", "Python >= 3.10 venv with pinned requirements"),
                _node("T1.1.2", "PostgreSQL 16 native install; database and superuser admin login"),
                _node("T1.1.3", "llama.cpp prebuilt Windows release; SQLCoder-7B-2 Q4_K_M GGUF", notes=(
                    "Future provenance: repository/download date, post-2024-02-07 weights, model sha256, and llama.cpp build number.",
                )),
            )),
            _node("S1.2", "Fixture loaded and verified", children=(
                _node("T1.2.1", "seed_data.py --reset; all 18 checks pass", notes=("FRD task wording is a future acceptance target; no generator is invoked or result claimed.",)),
                _node("T1.2.2", "Export fixture_pg_dump.sql with --no-owner --no-privileges; record sha256 in manifest"),
                _node("T1.2.3", "Restore the dump into a clean database; re-run the 18 checks"),
            )),
            _node("S1.3", "Model service measured", children=(
                _node("T1.3.1", "Start llama-server on 127.0.0.1; one slot; caching on"),
                _node("T1.3.2", "Measure and record cold-start time, warm latency, tokens per second, resident memory, and token count of the full-schema prompt", notes=("The FRD specifies the server tokenize endpoint; no measurement has been performed.",)),
                _node("T1.3.3", "Set initial values and record in PROJECT_LOG.md", notes=("FRD defaults: generation_timeout 120 s, statement_timeout 15 s, row_cap 1000; no measured budget or log entry is invented.",)),
            )),
        ),
    ),
    _node(
        "E2", "EVALUATION HARNESS AND UNCONTROLLED BASELINE", ProgressLabel.SOURCE,
        paths=_PROMPT + _CLIENT + _EXTRACTION + _PIPELINE,
        notes=("Prompt/client/extraction and isolated pipeline interfaces are drafts; evaluation suites and baseline records belong to future Prompt 5.",),
        exit="BASELINE recorded: accuracy count, failure histogram, latency, and raw-leakage picture of the uncontrolled system.",
        children=(
            _node("S2.1", "Prompt builder and extraction", ProgressLabel.SOURCE, paths=_PROMPT + _EXTRACTION, children=(
                _node("T2.1.1", "Store the model-card template file; record sha256", notes=("Exact authoritative local model-card template is unavailable; loader source stops without it.",)),
                _node("T2.1.2", "Builder: template + full DDL + question + as-of line (prompt_v1)", ProgressLabel.SOURCE, paths=_PROMPT + _CONTEXT, notes=("Harness-only version 1 support is drafted; frozen E2 DDL/digest and template remain required inputs.",)),
                _node("T2.1.3", "Extraction function with 10 hand-written model outputs as tests", ProgressLabel.SOURCE, paths=_EXTRACTION, notes=("Extraction function is drafted; ten-case test source belongs to future Prompt 5 and is absent.",)),
            )),
            _node("S2.2", "Model client", ProgressLabel.SOURCE, paths=_CLIENT, children=(
                _node("T2.2.1", "HTTP call with greedy parameters; stop at ';'; timeout", ProgressLabel.SOURCE, paths=_CLIENT),
                _node("T2.2.2", "Warm-up helper; error handling for server unavailable", ProgressLabel.SOURCE, paths=_CLIENT, notes=("Callable helper and error mapping only; no warmup or model call is performed.",)),
            )),
            _node("S2.3", "Pipeline skeleton in UNCONTROLLED mode", ProgressLabel.SOURCE, paths=_PIPELINE + _EXECUTOR, children=(
                _node("T2.3.1", "answer() with mode UNCONTROLLED and the outcome record", ProgressLabel.SOURCE, paths=_PIPELINE, notes=("Ordinary answer path remains FULL; bypass requires the distinct isolated harness capability interface.",)),
                _node("T2.3.2", "Disposable fixture evaluation database and least-privilege SELECT-only test identity; NO admin/superuser model execution; SQLSTATE capture and unexecuted-unsafe-case tracking (FR-6.10)", ProgressLabel.FUTURE, paths=_EXECUTOR + _PIPELINE, notes=("Clone/privilege/safety guards are drafted; no evaluation database or identity is created and provenance remains unavailable.",)),
            )),
            _node("S2.4", "Comparator", children=(
                _node("T2.4.1", "Implement FR-9.2 with Decimal quantization", notes=("Comparator source belongs to future Prompt 5.",)),
                _node("T2.4.2", "At least 10 unit-test pairs"),
            )),
            _node("S2.5", "Smoke question set", children=(
                _node("T2.5.1", "20 payroll-persona questions with explicit as_of_date"),
                _node("T2.5.2", "Hand-verify every reference SQL in psql", notes=("Future references: no CURRENT_DATE/NOW/CURRENT_TIMESTAMP; posted/closed status; Engineering as division; at least one ambiguity case. No SQL is run.",)),
            )),
            _node("S2.6", "Run records and automatic failure classes", children=(
                _node("T2.6.1", "Run record writer (FR-9.7)"),
                _node("T2.6.2", "Automatic classification from SQLSTATE, lint, and timeouts", notes=("Pipeline status/error mapping is drafted; evaluation failure-class classifier remains future Prompt 5.",)),
                _node("T2.6.3", "Wall-clock lint with a unit test per pattern"),
            )),
            _node("S2.7", "Baseline run", children=(
                _node("T2.7.1", "Run the smoke set in UNCONTROLLED mode; warm-up first"),
                _node("T2.7.2", "Manually triage failures into the manual classes"),
                _node("T2.7.3", "Run 5 through-the-model adversarial prompts in the isolated UNCONTROLLED harness; record actual leakage or blocked/unexecuted outcomes without assuming an unsafe query may execute"),
                _node("T2.7.4", "Write the baseline entry in PROJECT_LOG.md"),
            )),
        ),
    ),
    _node(
        "E3", "ACCESS POLICY AND DATABASE ENFORCEMENT", ProgressLabel.SOURCE,
        paths=_POLICY + _GRANTS + _RLS + _PRIVILEGES + _APPLY + _PERSONAS + _EXECUTOR,
        notes=("Prompt 2 policy/executor source exists; no policy SQL has been applied and no database-only assessment has occurred.",),
        exit="Every role/table/column matches matrix; row counts match; direct-SQL suite run against database alone; database-only gaps listed.",
        children=(
            _node("S3.1", "Access matrix as data", ProgressLabel.SOURCE, paths=_POLICY, children=(
                _node("T3.1.1", "policy/access_matrix.yaml and a loader", ProgressLabel.SOURCE, paths=_POLICY),
                _node("T3.1.2", "Schema check: every table/column named exists", ProgressLabel.SOURCE, paths=_POLICY, notes=("Schema-contract guard is authored; authoritative runtime schema comparison remains future work.",)),
            )),
            _node("S3.2", "Generators", ProgressLabel.SOURCE, paths=_GRANTS + _RLS + _PRIVILEGES + _APPLY, children=(
                _node("T3.2.1", "Grants generator (column-level; rule R1)", ProgressLabel.SOURCE, paths=_GRANTS),
                _node("T3.2.2", "RLS policy generator for the four scope kinds (rules R2, R3)", ProgressLabel.SOURCE, paths=_RLS),
                _node("T3.2.3", "hr_bp_current_divisions() (FR-6.7)", ProgressLabel.SOURCE, paths=_RLS + _PRIVILEGES),
                _node("T3.2.4", "Login-role defaults (FR-6.2)", ProgressLabel.SOURCE, paths=_PRIVILEGES + _EXECUTOR),
                _node("T3.2.5", "set_config revoke/grant (run after dump restore)", ProgressLabel.SOURCE, paths=_PRIVILEGES, notes=("Revoke/grant source is drafted; no restore or SQL application has occurred.",)),
                _node("T3.2.6", "One idempotent apply script; generated files not hand-edited", ProgressLabel.SOURCE, paths=_APPLY, notes=("Apply callable is drafted; idempotence and installed-policy evidence remain future work.",)),
            )),
            _node("S3.3", "Personas", ProgressLabel.SOURCE, paths=_PERSONAS, children=(
                _node("T3.3.1", "Script that selects personas from the loaded fixture", ProgressLabel.SOURCE, paths=_PERSONAS, notes=("Fixture-based derivation source only; generated persona artifacts are unavailable.",)),
                _node("T3.3.2", "Startup assertion that every principal exists", ProgressLabel.SOURCE, paths=_PERSONAS),
            )),
            _node("S3.4", "Authorization tests (no model)", children=(
                _node("T3.4.1", "has_table_privilege and has_column_privilege per role, table, column against the matrix"),
                _node("T3.4.2", "Row counts per persona vs independent admin computation"),
                _node("T3.4.3", "Expected-behavior table (section 6.6) as tests"),
            )),
            _node("S3.5", "Role-aware executor", ProgressLabel.SOURCE, paths=_EXECUTOR, children=(
                _node("T3.5.1", "Per-request transaction in the exact order of FR-6.3", ProgressLabel.SOURCE, paths=_EXECUTOR),
                _node("T3.5.2", "Row cap, timeout mapping, SQLSTATE mapping (FR-8.1)", ProgressLabel.SOURCE, paths=_EXECUTOR),
            )),
            _node("S3.6", "Direct-SQL adversarial suite", children=(
                _node("T3.6.1", "Write cases S1-S9 (see section 8) with expected stopping layers"),
                _node("T3.6.2", "Run in an isolated non-admin test environment with the validator not yet implemented; record actual database behavior, catalog exposure, costly-function paths, and session-setting risks"),
            )),
        ),
    ),
    _node(
        "E4", "QUERY VALIDATOR", ProgressLabel.SOURCE, paths=_VALIDATOR,
        notes=("Fail-closed validator source is drafted; installed-parser/function review evidence and all acceptance outcomes are unavailable.",),
        exit="Acceptance A, B, and C met (FR-5 acceptance); every adversarial SQL case stopped by a layer and attributed.",
        children=(
            _node("S4.1", "Rules", ProgressLabel.SOURCE, paths=_VALIDATOR, children=(
                _node("T4.1.1", "FR-5.2 (single statement) and FR-5.3 (top-level shape)", ProgressLabel.SOURCE, paths=_VALIDATOR),
                _node("T4.1.2", "FR-5.4 (write/DDL/command nodes; verify class names exist first)", ProgressLabel.SOURCE, paths=_VALIDATOR, notes=("Guarded parser-profile source only; actual installed class-layout evidence is required and unavailable.",)),
                _node("T4.1.3", "FR-5.5 (tables, CTE aliases, schema qualifiers, table functions)", ProgressLabel.SOURCE, paths=_VALIDATOR),
                _node("T4.1.4", "FR-5.6 (default-deny anonymous functions)", ProgressLabel.SOURCE, paths=_VALIDATOR, notes=("Reviewed-function policy guard covers recognized and anonymous calls; review evidence is a later dependency.",)),
                _node("T4.1.5", "FR-5.7 (regeneration and idempotence check)", ProgressLabel.SOURCE, paths=_VALIDATOR),
            )),
            _node("S4.2", "Unit tests from FR-5 acceptance", notes=("Test source belongs to future Prompt 5; no tests are invoked.",)),
            _node("S4.3", "Acceptance tests", children=(
                _node("T4.3.1", "A: validator allows every legitimate reference SQL. At E4 this covers the 20 payroll questions. This test MUST be re-run whenever the reference SQL set grows (E5, E6, E8)."),
                _node("T4.3.2", "B: original and regenerated SQL give identical results"),
                _node("T4.3.3", "C: re-run the direct-SQL suite with the validator on"),
            )),
            _node("S4.4", "Version guard", children=(
                _node("T4.4.1", "Record sqlglot version in the run record; test suite is the gate for any upgrade", notes=("Validator review-profile binding is drafted; evaluation version/run-record source remains future Prompt 5.",)),
            )),
        ),
    ),
    _node(
        "E5", "GOVERNED SEMANTIC LAYER AND CONTEXT MINIMIZATION [MVP]", ProgressLabel.SOURCE,
        paths=_CATALOG + _SEMANTICS + _CONTEXT + _PROMPT,
        notes=("Prompt 3 semantic/context drafts and Prompt 4 prompt integration exist; contract/accuracy evidence is unavailable and I-01 remains open.",),
        exit="Role-filtered DDL and semantic metadata correct, versioned, and assessed against reference SQL; no restricted object names leak.",
        children=(
            _node("S5.1", "Versioned semantic catalog (FR-7)", ProgressLabel.SOURCE, paths=_CATALOG + _SEMANTICS, children=(
                _node("T5.1.1", "Define entities, dimensions, metrics, grain, units, join paths", ProgressLabel.SOURCE, paths=_CATALOG + _SEMANTICS),
                _node("T5.1.2", "Define active_headcount, payroll status, as-of rules, synonyms", ProgressLabel.SOURCE, paths=_CATALOG + _SEMANTICS, notes=("Governed definitions are source drafts; canonical active_headcount remains unavailable to sales-manager under I-01.",)),
                _node("T5.1.3", "Resolve \"Engineering\" as division without guessing", ProgressLabel.SOURCE, paths=_SEMANTICS + _CATALOG),
                _node("T5.1.4", "Validate dependencies against fixture schema and access matrix", ProgressLabel.SOURCE, paths=_SEMANTICS + _CONTEXT, notes=("Dependency guards are drafted; actual authoritative fixture/schema assessment remains outstanding.",)),
                _node("T5.1.5", "Create role-scoped accuracy cases for HR BP and sales-manager personas, with reference SQL run under the same persona. These are created here (not in E6) so that S5.3 can re-run them.", notes=("Future case-builder/test source belongs to Prompt 5; no reference SQL is run.",)),
                _node("T5.1.6", "Deterministically test semantic vocabulary, metric contracts, role-filtered context, and schema/entitlement drift (FR-7.9-FR-7.11)", notes=("Contract guard source exists, but deterministic test suites are future Prompt 5 source and are absent.",)),
            )),
            _node("S5.2", "Role-aware prompt context", ProgressLabel.SOURCE, paths=_CONTEXT + _PROMPT, children=(
                _node("T5.2.1", "Generate filtered DDL from matrix and catalog; deterministic sha256", ProgressLabel.SOURCE, paths=_CONTEXT),
                _node("T5.2.2", "Compile only role-permitted semantic definitions; hash output", ProgressLabel.SOURCE, paths=_CONTEXT),
                _node("T5.2.3", "Verify no hidden table, column, metric, or relationship names", ProgressLabel.FUTURE, paths=_CONTEXT, notes=("Filtering source is authored; absence-of-disclosure assessment and test source remain future work.",)),
                _node("T5.2.4", "Integrate schema+semantics with the model-card format as prompt_version 2. The E2 baseline prompt (prompt_version 1) is preserved unmodified for comparison.", ProgressLabel.SOURCE, paths=_PROMPT + _CONTEXT, notes=("Version-separated builder source only; exact template and frozen E2 input are required.",)),
            )),
            _node("S5.3", "Semantic contract acceptance", children=(
                _node("T5.3.1", "Test each canonical definition against independent reference SQL"),
                _node("T5.3.2", "Test dates, synonyms, join path, division ambiguity, role scoping"),
                _node("T5.3.3", "Re-run role-scoped accuracy and leak cases; report flipped cases"),
                _node("T5.3.4", "Keep semantic definition/version fingerprints in run records", notes=("Request-event fingerprint source exists; evaluation run records belong to future Prompt 5.",)),
            )),
        ),
    ),
    _node(
        "E6", "INTEGRATED PIPELINE AND TRACE", ProgressLabel.SOURCE,
        paths=_PIPELINE + _TRACE,
        notes=("Single-path orchestration, safe projection, and trace-writer source are drafted; mode execution and evaluation measurements remain future work.",),
        exit="All four modes operate; role-scoped accuracy and over-blocking measured.",
        children=(
            _node("S6.1", "answer() complete", ProgressLabel.SOURCE, paths=_PIPELINE, children=(
                _node("T6.1.1", "FULL persona path; bypass modes callable from isolated harness ONLY (FR-2.5, FR-6.10)", ProgressLabel.SOURCE, paths=_PIPELINE + _EXECUTOR),
                _node("T6.1.2", "Outcome record, stopping_layer, reason codes (FR-8.5)", ProgressLabel.SOURCE, paths=_PIPELINE),
                _node("T6.1.3", "Safe user messages, CLARIFICATION_REQUIRED, and developer-only diagnostics (FR-8.2, FR-8.6, FR-8.7)", ProgressLabel.SOURCE, paths=_PIPELINE + _TRACE),
            )),
            _node("S6.2", "Trace events (NFR-7) written for every request", ProgressLabel.SOURCE, paths=_TRACE, notes=("Writer source only; no logs/events.jsonl file or request event is created during drafting.",)),
            _node("S6.3", "Extend role-scoped question sets", children=(
                _node("T6.3.1", "Additional legitimate questions for HR BP and sales-manager personas (beyond those created in T5.1.5), with reference SQL run under the same persona"),
                _node("T6.3.2", "Authorization questions through the model (expected blocks and scoped results, with forbidden-value canaries)", notes=("No actual canary values or question datasets are materialized.",)),
                _node("T6.3.3", "Count over-blocked legitimate questions (FC-OVERBLOCK)"),
            )),
        ),
    ),
    _node(
        "E7", "CONNECT REVIEWED UI TO VERIFIED PIPELINE", ProgressLabel.SOURCE, paths=_UI,
        notes=("FRD epic title names a future dependency; UI draft exists, but E0 visual approval and E1-E6 exit evidence remain unavailable.",),
        entry="E0 user approval AND E1-E6 exit conditions met.",
        exit="Each persona completes an allowed and blocked LIVE question; UI accurately names the stopping layer.",
        children=(
            _node("S7.1", "Rebuild the E0 design in Streamlit (FR-10.4). No E0 HTML/JS code is reused; E0 is a visual spec.", ProgressLabel.SOURCE, paths=_UI, notes=("Connected-view and planning-renderer source translates the supplied E0 layout into native Streamlit controls; visual/browser assessment remains pending.",), children=(
                _node("T7.1.1", "Persona selector from generated personas", ProgressLabel.SOURCE, paths=_UI + _PERSONAS, notes=("Selector source consumes trusted generated definitions; actual fixture-derived mapping remains external.",)),
                _node("T7.1.2", "Question box, as_of_date, FULL-only persona runtime (FR-10.5)", ProgressLabel.SOURCE, paths=_UI + _PIPELINE),
                _node("T7.1.3", "Safe banner/authorized results; diagnostics in developer-only surface, not ordinary persona UI (FR-10.8)", ProgressLabel.SOURCE, paths=_UI + _PIPELINE, notes=("Persona source uses safe projection; developer details stay in local CLI/harness logs only.",)),
                _node("T7.1.4", "Busy handling per FR-10.7", ProgressLabel.SOURCE, paths=_UI),
            )),
            _node("S7.2", "Walkthrough", children=(
                _node("T7.2.1", "One scripted scenario per persona: an allowed, a blocked, and a scoped question"),
                _node("T7.2.2", "README: install, load fixture, apply policy, start model, start UI, run tests, run evaluation", notes=("Operational instructions remain future handoff; no installation or runtime action is performed.",)),
            )),
        ),
    ),
    _node(
        "E8", "ADVERSARIAL EVALUATION AND ATTRIBUTION",
        notes=("Evaluation and adversarial/test source belong to future Prompt 5; no suite or result is claimed.",),
        exit="Through-the-model suite executed; attribution complete; regressions populated; every known single-layer dependency explicitly listed in section 10.",
        children=(
            _node("S8.1", "Through-the-model suite N1-N7 (section 8) with forbidden-value canaries"),
            _node("S8.2", "Attribution runs in all four modes (FR-9.5)"),
            _node("S8.3", "Triage loop", children=(
                _node("T8.3.1", "Each FC-LEAK becomes a regression case first, then a fix"),
                _node("T8.3.2", "Re-run both suites after each fix"),
                _node("T8.3.3", "List every case that depends on a single layer"),
                _node("T8.3.4", "Test function-level abuse, resource limits, and diagnostic disclosure"),
            )),
            _node("S8.4", "Holdout check: run sealed holdout at the E8 boundary and subsequently only at defined epic boundaries; record exposures/results", notes=("Sealed holdout remains external and unopened; no holdout questions, answers, or results appear here.",)),
        ),
    ),
    _node(
        "E9", "ACCURACY IMPROVEMENT (CONDITIONAL)",
        notes=("Conditional work requires observed dominant failure classes; no failures or improvements are invented.",),
        entry="Failure histograms from E2, E6, and E8 name a dominant class.",
        children=(
            _node("S9.1", "If FC-SCHEMA/JOIN/FILTER dominate: add few-shot examples, disjoint from every accuracy set", notes=("Future rule: one change, re-run, compare flipped cases; holdout is never used for tuning.",)),
            _node("S9.2", "If FC-SEMANTIC/TEMPORAL dominate: refine the existing E5 metric and temporal definitions based on observed failures. The semantic layer itself is MVP (FR-7); E9 only refines its content. Render as-of date as a literal; avoid array predicate examples the model may copy.", notes=("Future rule: one change, re-run, compare flipped cases.",)),
            _node("S9.3", "Optional: alternative model as a NEW baseline (own template, own run)", notes=("Future rule: one change, re-run, compare flipped cases; no alternative model is introduced.",)),
        ),
    ),
    _node(
        "E10", "AGGREGATE-ONLY ACCESS (DEFERRED - see R-01)",
        notes=("Not authorized for MVP. R-01 requires renewed explicit authorization and inference-risk tests before this epic starts.",),
    ),
)


def _render_items(label: str, items: tuple[str, ...]) -> None:
    import streamlit as st

    st.markdown(f"**{label}**")
    for item in items:
        st.markdown(f"- {item}")


def _select_stage(number: int) -> None:
    import streamlit as st

    st.session_state["architecture_stage"] = number


def _select_epic(ref: str) -> None:
    import streamlit as st

    st.session_state["progress_epic"] = ref


def render_architecture() -> None:
    """Render static clickable stage planning; perform no backend operation."""
    import streamlit as st

    st.subheader("Six-stage runtime architecture")
    from .project_status import render_evidence
    render_evidence()
    st.caption(
        "Public developer planning metadata. Source stages are distinct from verified remediation gates; "
        "stage selection grants no backend capability. Persona identity is simulated, not authentication."
    )
    st.caption(
        "Choose a stage card to inspect its workflow, dependencies, artifacts, controls, and FRD references. "
        "The supplied E0 hierarchy is translated into native Streamlit controls."
    )
    stage_number = st.session_state.get("architecture_stage", 1)
    if stage_number not in tuple(stage.number for stage in STAGES):
        stage_number = 1
        st.session_state["architecture_stage"] = stage_number
    stage_columns = st.columns(6)
    for column, candidate in zip(stage_columns, STAGES):
        with column:
            with st.container(border=True):
                st.caption(f"{candidate.number:02d} / RUNTIME")
                st.button(
                    candidate.title,
                    key=f"architecture_stage_card_{candidate.number}",
                    type="primary" if candidate.number == stage_number else "secondary",
                    use_container_width=True,
                    on_click=_select_stage,
                    args=(candidate.number,),
                )
                st.caption(candidate.purpose)
    stage = STAGES[stage_number - 1]
    with st.container(border=True):
        st.caption(f"STAGE {stage.number:02d} / DETAILED WORKFLOW")
        st.markdown(f"### {stage.title}")
        st.write(stage.purpose)
        normal, failure, dependencies, artifacts, security, references = st.tabs(
            ("Normal flow", "Failure paths", "Dependencies", "Input / output", "Security", "References")
        )
        with normal:
            _render_items("Normal path", stage.normal_flow)
        with failure:
            _render_items("Failure and stopping paths", stage.failure_paths)
        with dependencies:
            _render_items("Dependencies and handoffs", stage.dependencies)
        with artifacts:
            _render_items("Input artifacts", stage.inputs)
            _render_items("Output artifacts", stage.outputs)
        with security:
            _render_items("Security controls", stage.security_controls)
            _render_items("Future acceptance evidence", stage.future_evidence)
        with references:
            _render_items("Requirements", stage.requirement_refs)
            _render_items("Epics / stories / tasks", stage.roadmap_refs)
            _render_items("Source responsibilities", stage.source_paths)


def _render_node(node: ProgressNode, *, level: int = 0) -> None:
    """Use a readable hierarchy inside epic expanders, without nested expanders."""
    import streamlit as st

    prefix = "Story" if level == 0 else "Task"
    st.markdown(f"**{prefix} {node.ref} - {node.title}**")
    st.caption(node.state.value)
    for note in node.notes:
        st.caption(note)
    if node.source_paths:
        st.caption("Source responsibilities: " + "; ".join(node.source_paths))
    for child in node.children:
        _render_node(child, level=level + 1)


def render_progress() -> None:
    """Render the complete read-only FRD roadmap, with no completion controls."""
    import streamlit as st

    st.subheader("Implementation progress explorer")
    from .project_status import render_evidence
    render_evidence()
    st.caption("Read-only FRD 1.8 Section 7 hierarchy. Labels describe authoring scope only.")
    st.info(
        "Not started: work or evidence remains absent. Implemented in source: a draft exists. "
        "Future verification: callable source awaits later runtime assessment. "
        "No epic exit condition is met by source authorship. Actual gate test evidence is shown above."
    )
    st.warning(
        "E0 visual approval and E1 environment/fixture measurements remain pending. "
        "E7 is a source draft; its runtime entry conditions remain unmet. "
        "I-01 is open; E9 is conditional; E10 is deferred under R-01."
    )
    counters = st.columns(3)
    counters[0].metric("Epics", len(EPICS))
    counters[1].metric("Stories", sum(len(epic.children) for epic in EPICS))
    counters[2].metric("Numbered tasks", sum(len(story.children) for epic in EPICS for story in epic.children))
    selected_ref = st.session_state.get("progress_epic", "E0")
    if selected_ref not in tuple(epic.ref for epic in EPICS):
        selected_ref = "E0"
        st.session_state["progress_epic"] = selected_ref
    navigator, inspector = st.columns((1, 2))
    with navigator:
        with st.container(border=True):
            st.markdown("**Epic navigator**")
            for candidate in EPICS:
                st.button(
                    f"{candidate.ref} - {candidate.title}",
                    key=f"progress_epic_card_{candidate.ref}",
                    type="primary" if candidate.ref == selected_ref else "secondary",
                    use_container_width=True,
                    on_click=_select_epic,
                    args=(candidate.ref,),
                )
                st.caption(f"{candidate.state.value} / {len(candidate.children)} stories")
    epic = next(epic for epic in EPICS if epic.ref == selected_ref)
    with inspector:
        with st.container(border=True):
            st.markdown(f"### {epic.ref} - {epic.title}")
            st.caption(epic.state.value)
            for note in epic.notes:
                st.write(note)
            if epic.entry_condition:
                st.markdown("**Future entry condition:** " + epic.entry_condition)
            if epic.exit_condition:
                st.markdown("**Future exit condition (not met):** " + epic.exit_condition)
            if epic.source_paths:
                st.caption("Source responsibilities: " + "; ".join(epic.source_paths))
            for story in epic.children:
                with st.expander(f"{story.ref} - {story.title} | {story.state.value}"):
                    st.caption(f"{len(story.children)} separately numbered tasks")
                    for note in story.notes:
                        st.caption(note)
                    if story.source_paths:
                        st.caption("Source responsibilities: " + "; ".join(story.source_paths))
                    for task in story.children:
                        with st.container(border=True):
                            _render_node(task, level=1)
                    if not story.children:
                        st.caption("This FRD story has no separately numbered tasks; no task IDs are invented.")
            if not epic.children:
                st.caption("No separately numbered stories or tasks are authorized for this deferred epic.")
