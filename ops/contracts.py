"""Strict report data and fixed gate ownership. Markdown never becomes commands."""
from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import re

REPOSITORY = "Vivek-k24/Stark_T2SQL"
BASE = "gemini/full-remediation-review"
HTML = "STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html"
PROGRESS = "ops/progress.json"
SHA = re.compile(r"[0-9a-f]{40}")
MARKER = re.compile(r"<!-- STARK_HANDOFF_V1\s*\n(.*?)\n-->", re.S)
PREFIXES = {
    "R04": ("src/stark_t2sql/semantic/", "src/stark_t2sql/context/", "semantic/catalog.yaml"),
    "R05": ("src/stark_t2sql/security/", "src/stark_t2sql/db/executor.py", "src/stark_t2sql/evaluation/ablation.py"),
    "R06": ("src/stark_t2sql/evaluation/reference.py", "src/stark_t2sql/evaluation/comparator.py", "benchmarks/authorization/"),
    "R07": ("src/stark_t2sql/evaluation/", "benchmarks/"),
    "R08": ("src/stark_t2sql/inference/", "src/stark_t2sql/ui/", "app.py"),
    "R09": ("ops/evidence/",),
}
FROZEN = {"schema.sql", "seed_data.py", "fixture_manifest.json", "fixture_pg_dump.sql",
          "src/inference/prompt_template.txt", "src/stark_t2sql/evaluation/holdout.py", "AGENTS.md"}

class Stop(RuntimeError):
    """Visible stop, requiring an operator or new authorized evidence."""

def sha(value):
    if type(value) is not str or SHA.fullmatch(value) is None:
        raise Stop("Invalid commit SHA")
    return value

def safe_path(path):
    if (type(path) is not str or not path or any(ord(c)<32 for c in path) or "\\" in path or ":" in path
            or PurePosixPath(path).is_absolute() or any(p in {"", ".", "..", ".git"} for p in path.split("/"))):
        raise Stop("Unsafe repository path")
    return path

@dataclass(frozen=True)
class Gate:
    name: str
    @property
    def branch(self): return "codex/interim-orchestration-ui" if self.name=="INT01" else f"codex/{self.name.lower()}-remediation"
    @property
    def issue(self): return 15 if self.name=="INT01" else int(self.name[1:]) + 2
    @property
    def review(self): return f"Antigravity_{self.name}_Review.md"
    @property
    def log(self): return f"Codex_{self.name}_Work_Log.md"
    def allowed(self, path, phase, approved_paths):
        path = safe_path(path)
        if path in FROZEN or "holdout" in path.lower() or "canary" in path.lower(): return False
        if phase == "verification": return path in {self.review, HTML, PROGRESS}
        if self.name=="INT01": return False
        # Operator-approved exact paths/prefixes further narrow the built-in gate ceiling.
        ceiling = path == self.log or path.startswith("tests/") or any(
            path.startswith(p) if p.endswith("/") else path == p for p in PREFIXES[self.name])
        selected = any(path.startswith(p) if p.endswith("/") else path == p for p in approved_paths)
        return ceiling and selected

def gate(name):
    if type(name) is not str or name not in {*PREFIXES,"INT01"}: raise Stop("Only explicitly enrolled INT01 status / R04–R09 gates are supported")
    return Gate(name)

def reports(text, selected):
    if len(text.encode()) > 1_000_000: raise Stop("Report exceeds size limit")
    result = {}
    for payload in MARKER.findall(text):
        try: item = json.loads(payload, object_pairs_hook=_unique)
        except (ValueError, TypeError) as exc: raise Stop("Malformed handoff JSON") from exc
        fields = {"gate", "phase", "status", "subject_sha", "implementation_ready", "tests"}
        if type(item) is not dict or set(item) != fields or item["gate"] != selected.name:
            raise Stop("Unexpected report fields/gate")
        phase, status = item["phase"], item["status"]
        statuses = {"design": {"APPROVE", "REVISE", "BLOCKED"},
                    "implementation": {"IMPLEMENTATION_PUSHED"},
                    "verification": {"VERIFIED_APPROVE", "VERIFIED_REVISE", "VERIFIED_BLOCKED"}}
        if type(phase) is not str or type(status) is not str or phase not in statuses or status not in statuses[phase] or phase in result:
            raise Stop("Ambiguous or invalid handoff phase/status")
        sha(item["subject_sha"])
        if type(item["implementation_ready"]) is not bool: raise Stop("Readiness must be explicit")
        tests = item["tests"]
        if (type(tests) is not dict or set(tests) != {"passed", "failed", "skipped", "scope"}
                or any(type(tests[k]) is not int or tests[k] < 0 for k in ("passed", "failed", "skipped"))
                or type(tests["scope"]) is not str or tests["scope"] not in {"offline", "not_run"}): raise Stop("Invalid test evidence")
        if phase != "design" and status in {"IMPLEMENTATION_PUSHED", "VERIFIED_APPROVE"}:
            if tests["scope"] != "offline" or tests["passed"] == 0 or tests["failed"]: raise Stop("Passing test evidence required")
        result[phase] = item
    return result

def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("duplicate key")
        result[key] = value
    return result

def marker(item): return "<!-- STARK_HANDOFF_V1\n" + json.dumps(item, sort_keys=True) + "\n-->"
