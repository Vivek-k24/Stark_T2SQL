# R09 evidence contract

`R09_ACCEPTANCE_MATRIX.json` defines 31 mandatory items, their exact requirements, procedures, environments, operation classes, modes, required artifact digests and GO/NO-GO conditions. `R09_EVIDENCE_TEMPLATE.json` is the initial public manifest: **all items are NOT_RUN**, execution/reviewer/authorization fields are null and production promotion is NOT_APPROVED.

The equivalent executable schema is [r09_evidence.py](../../tests/integration/r09_evidence.py) (repository path: `tests/integration/r09_evidence.py`). Its tests are offline contract tests, not live acceptance. No JSON-schema dependency, runtime service or default approval store is introduced.

## Public record shape

The manifest has exactly `schema_version`, `git_commit`, `artifacts`, `persona_logins`, `items` and `production_promotion`.

- `schema_version` is `stark-r09-evidence-v1`.
- `git_commit` is the exact 40-character reviewed revision. The template refers to integration baseline `b926a9c17a83f73800db4a3b8aa0ee03d444743c`; an actual future acceptance record must instead bind the revision actually reviewed/executed. Do not silently substitute the latest branch head.
- `artifacts` maps public artifact identifiers to actual lowercase SHA-256 digests. Eight frozen sources are mandatory: schema, seed, fixture manifest/dump, policy, catalog, prompt template and FRD. Additional required runtime/evidence artifacts must exist before an executed item is validated. Missing model/launcher/budget inputs are not populated with dummy hashes.
- `persona_logins` maps exactly payroll, hr_1, hr_2 and sales to public business/login role names derived from the actual policy. It contains no principals, passwords, database names or scope rows. Both HR entries share the restricted HR login; private registry/scope observations must still distinguish the two principals.
- `production_promotion` is always `NOT_APPROVED`. This record cannot authorize a merge, execution or production promotion.

Each item has exactly these fields:

| Field | Meaning |
| --- | --- |
| `criterion_id`, `requirement` | Unique known ID and verbatim matrix requirement |
| `environment_id`, `mode`, `scope` | Exact matrix bindings; NONE/ALL_MODES are metadata labels, not executable modes |
| `git_commit` | Exact reviewed run revision, matching the manifest and independent verification inputs |
| `artifact_set_sha256` | SHA-256 of canonical JSON of the complete reviewed artifact-digest map |
| `matrix_sha256` | SHA-256 of canonical JSON of the exact acceptance matrix |
| `procedure_reference` | Exact runbook phase reference |
| `status` | Exactly PASSED_LIVE, PASSED_OFFLINE, BLOCKED, FAILED or NOT_RUN |
| `executed_at` | Actual UTC ISO timestamp ending Z; null before execution, never a future time |
| `observation_reference`, `evidence_sha256` | Opaque redacted-evidence ID and actual bounded evidence-byte digest; null before execution |
| `reviewer_reference`, `authorization_reference` | Genuine opaque references, with identities/approval verified privately; null when unavailable |
| `unresolved_prerequisites` | Unique uppercase metadata codes; mandatory for unexecuted items, empty for passed items |

Unknown/private payload keys, duplicate JSON keys, duplicate/unknown criterion IDs, missing matrix items, changed requirements, altered modes, hashes or commit bindings are rejected. BLOCKED/NOT_RUN cannot carry fabricated execution timestamps or receipts. PASSED_OFFLINE cannot replace a required PASSED_LIVE result. A FAILED observation remains NO-GO and needs real review/evidence if recorded as executed.

Public values are deliberately limited. Do not add full commands containing private paths, DSNs, raw errors, prompts, generated/reference SQL, private result rows, emails, salary canaries, holdout IDs or exposure records. Use the fixed procedure reference and opaque artifact reference; retain sensitive evidence in the approved private lane. Structural validation is not a universal secret-redaction system: a human must review even opaque identifiers and public metadata before publication.

## Independent verification inputs

`validate_manifest()` requires independent expected Git/artifact/persona bindings. An executed record additionally requires a `VerificationInputs` object from an owner-controlled reviewer composition, **not reconstructed from the public manifest**:

1. Actual redacted evidence bytes keyed by the item's observation reference.
2. A review receipt with kind `R09_REVIEWED_EXECUTION_V1`, exact `item_sha256`, `evidence_sha256`, reviewer reference and authorization reference. Its entire bytes must match a separately approved receipt digest pin.
3. For PASSED_LIVE, an actual operation authorization with kind `R09_OWNER_AUTHORIZATION_V1`, authorization reference, criterion, environment, mode, reviewed Git commit, scope, artifact/matrix digests, canonical endpoint-map digest and the matrix operation class. Its bytes must match a **separately owner-approved authorization pin**.
4. Exact observed/approved numeric loopback endpoints for the relevant service; no credentials, DNS routing, arbitrary paths or external hosts.
5. For PostgreSQL/harness items, corroborated private clone catalog observations with distinct positive source/clone OIDs, distinct database names and the full production marker fields. The canonical observation digest must equal `CLONE_CATALOG` in the reviewed artifact set. A marker declaration is not proof that those observations were actually collected; the independent execution/review receipt is still required.

Canonical JSON means UTF-8 of `json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)` without a trailing newline. Actual file evidence digests instead cover their exact bytes. A changed matrix or artifact set requires new review and authorization bindings. Keep private source/clone names and clone tokens outside public records.

**SHA-256 is an integrity binding, not a digital signature or proof of owner identity.** The approval pin sets must be approved out of band by the actual owner after independent review; computing a hash from a self-authored file does not authorize it. No real pin sets, credentials, reviewer attestations or trust bootstrap ship in this PR. If an external workflow needs cryptographic signatures, that separate trust mechanism must be independently specified and approved. Current `ScopeReviewStore` remains mandatory for reference SQL; R09 receipts never replace its owner pins or predicate analysis.

`readiness()` reruns full validation; it never accepts a standalone list of claimed statuses. It returns NO_GO with any missing mandatory item. Even complete verified evidence returns only EVIDENCE_COMPLETE_AWAITING_OWNER. Final signoff and any promotion are separate owner decisions. A receipt cannot issue a `HoldoutPermit` or grant service/database capability.

## Safe scaffolding and use

```powershell
# Safe offline-only verification; no live collection or provider import.
$env:PYTHONPATH='src;.'
$env:STARK_TEST_ENABLE_DB_INTEGRATION='0'
$env:STARK_R09_OFFLINE_ONLY='1'
python -m pytest tests/integration -q -ra
```

The six phase tests in `test_r09_live_acceptance.py` are **evidence replay scaffolding**, not collectors. Without an independently reviewed `r09_verified_evidence` provider they skip. OFFLINE_ONLY takes precedence; setting `STARK_R09_EVIDENCE_REPLAY=1` alone still skips. The scaffold imports no environment-selected Python module, loads no private files, opens no connection, starts no process and has no reset/restore/holdout path. A future separately approved provider can supply already collected redacted evidence and independent trust bindings; its source must be reviewed before any use. None is supplied or activated now.

Unit tests manufacture clearly TEST_ONLY in-memory receipts to exercise positive/negative binding checks. They are not owner approvals or runtime observations and are never written to the public template or genuine review stores. No fixture silently provisions credentials, datasets or a clone.
