# Gate R03: Implementation Log

Date: 2026-10-14 (America/Chicago). This is the single R03 Codex record required
by `AGENTS.md`. R01/R02 history remains in `Codex_work_log.md` unchanged.

| Reference | Location |
| --- | --- |
| Assignment and owner approval | [Issue #5](https://github.com/Vivek-k24/Stark_T2SQL/issues/5), including the [approved implementation handoff](https://github.com/Vivek-k24/Stark_T2SQL/issues/5#issuecomment-6176930373) |
| Standing instructions | [AGENTS.md](AGENTS.md) |
| Approved design and later independent verification record | [Antigravity_R03_Review.md](Antigravity_R03_Review.md) |
| FRD | [STARK_T2SQL FRD 1.8.txt](<STARK_T2SQL FRD 1.8.txt>) — FR-6.1–6.11, DR-5, sections 6–8 |
| Shared branch | `codex/r03-remediation` |
| Integration target | `gemini/full-remediation-review` |
| Implementation PR | [Draft PR #14](https://github.com/Vivek-k24/Stark_T2SQL/pull/14) |

## 1. Starting state and objective

Codex first read `AGENTS.md`, the supplied R03 review and Issue #5, then read
the relevant FRD and policy/database/test source. The review is **APPROVE** for
implementation. The owner's issue comment supersedes its older work-log naming
instruction: create this root-level `Codex_R03_Work_Log.md`, rather than append
R03 to the R01/R02 log.

The existing branch was `codex/r03-remediation` at
[`ed9ad988710a4eb9f814c3f86e58da03a6d533a9`](https://github.com/Vivek-k24/Stark_T2SQL/commit/ed9ad988710a4eb9f814c3f86e58da03a6d533a9),
the committed Antigravity review. It incorporates merged-R02 integration commit
[`b8d149d7d58b87a35b251980814467cbca61661d`](https://github.com/Vivek-k24/Stark_T2SQL/commit/b8d149d7d58b87a35b251980814467cbca61661d).
Codex fetched the shared and integration branches; the local shared branch and
its remote had zero commits ahead/behind. No new branch was created or selected.

The working tree already contained edits in `Antigravity_Design_Review.md` and
an extra blank line in `Antigravity_R03_Review.md`. These review edits were
preserved byte-for-byte and excluded from Codex's commits. Implementation paths
had no pre-existing edits. Work proceeded in `H:\STARK T2SQL` on the existing
shared branch, staging explicit paths only.

R03 addresses ISS-01/ISS-02/ISS-04: complete the isolated evaluation baseline
login bootstrap, verify exact matrix-derived grants offline, and exercise
connection/DDL/role/column/clone/drift safety stops. Authorization covers a draft
PR, not merging, R04, or unverified live database provisioning.

## 2. Findings and source changes

### R03-F1: complete baseline login creation and defaults

Previously, `baseline_eval_login` enabled full fixture SELECT grants and
permissive RLS policies but was absent from managed-role creation and persistent
login defaults. It was also absent from the schema/table/column/sequence and
function ACL cleanup lists. That could leave a clone plan incomplete or retain
pre-existing privileges on its intended baseline identity.

The optional baseline is now threaded through all those managed-role paths.
Only when explicitly provided, the plan creates/normalizes the baseline with
`LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION`,
includes it in privileged-role/ownership safety checks, clears old defaults and
membership edges, and grants no business-role membership to it. The name must
be a distinct dedicated identifier, cannot reuse business/logins/helper owner
or reserved identities, and must fit its generated policy name without
PostgreSQL identifier truncation.

The baseline receives the same supplied login controls as ordinary business
logins: statement timeout, default read-only mode, row security, work-memory
budget, temporary-file budget and trusted search path. These are emitted both
globally and for the current database after clearing stale overrides. No
guessed measured-budget defaults were introduced into production source.

Schema usage and SELECT are the baseline's intended application capabilities.
Its stale table/column/sequence privileges, database CREATE/TEMP privileges,
helper-function EXECUTE and `set_config` EXECUTE are included in cleanup.
`set_config` is still granted only to the three ordinary persona logins; the
HR helper remains executable only by its designated business role.

Production compilation **must use `baseline_eval_login=None`**. Tests verify
that this emits no baseline identity/grants/policies. Clone compilation adds
SELECT on all twelve tables and explicit baseline `USING (true)` policies on
the two forced-RLS tables, while its business-role SELECT grants remain
identical to production compilation.

### Clone-only administrative application

Because baseline grants must never be installed on a business database merely
because a caller supplies a role name, `policy_apply` now checks the actual
target's independently provisioned clone marker before reproducing/applying a
baseline plan. A dedicated-database Boolean or database name alone is
insufficient.

The check uses the existing `EvaluationConnectionSource` JSON marker contract:
`kind`, `clone_token`, `source_database`, `source_database_oid`,
`clone_database_oid`, and `fixture_dump_sha256`. It matches the expected target
name and fixture digest, actual target OID and a real separately named source
database/OID on the same instance. Missing, malformed, extra or inconsistent
marker fields fail closed before any generated DDL. The applier also excludes
the baseline and helper-owner identities from the trusted administrative setup
identity. No database, marker, authorization token or runtime credential was
created by this implementation.

### R03-F2: self-contained policy verification

The grant test now uses the committed frozen R02 `seed_data.TABLE_COLUMNS`
contract directly, with production and clone cases. It checks the exact set of
SELECT grants, including exact restricted column lists, helper backing columns
and baseline-only grants. It no longer skips for absent external catalog
metadata. This verifies source contracts, not an installed PostgreSQL catalog.

Additional compiler tests cover deterministic SQL for identical inputs,
metadata-mapping order independence, preflight success, every missing table,
every explicitly entitled/scope column, extra unmanaged tables, invalid or
colliding baseline names, global/per-database defaults, cleanup, no unexpected
membership and login-only principal-setting permissions. Repeated SQL-text
compilation is proven offline; repeated live policy installation is not.

### R03-F3: retain the documented principal-setting boundary

FR-6.4 documents that revoking function EXECUTE on `set_config` does not block
the utility command `SET app.principal_id`. A read-only transaction and RLS do
not by themselves authenticate that setting or prevent every within-role
identity spoof. This remains an explicit limitation, not a newly claimed DB
guarantee.

The unchanged executor requires the harness safety reviewer for `NO_VALIDATOR`.
Tests confirm fail-closed execution when actual parser approval is absent and
exercise the existing command/multiple-statement entry guard without inventing
an approval profile. Separate unit-only reviewer/driver mocks verify that
`NO_VALIDATOR` keeps the business persona, sets the principal before assuming
the business role and submits the reviewed candidate. Only `UNCONTROLLED`
uses the baseline connection without principal-setting or role switching.
Mocked SQLSTATE `42501` is attributed to a submitted database failure, not a
harness stop. These mocks do not prove real PostgreSQL enforcement.

## 3. Exact file scope

| Created/modified path | Reason |
| --- | --- |
| `src/stark_t2sql/policy/privileges.py` | Optional baseline identity validation, creation, membership/privilege cleanup and global/database login defaults. |
| `src/stark_t2sql/policy/compiler.py` | Document production/clone setting contract and pass the optional baseline into helper-function cleanup. |
| `src/stark_t2sql/policy/grants.py` | Include baseline in stale table/column/sequence ACL cleanup; preserve exact business entitlements. |
| `src/stark_t2sql/policy/rls.py` | Include optional baseline in helper-function EXECUTE revocation; preserve helper body and existing business RLS predicates. |
| `src/stark_t2sql/db/policy_apply.py` | Refuse baseline plans on unmarked/inconsistent database targets before generated DDL; preserve separate trusted setup identities. |
| `tests/test_policy_contracts.py` | Self-contained exact grant, baseline/production, defaults, preflight and deterministic compiler tests. |
| `tests/test_database_integration.py` | Keep six opt-in live cases; distinguish offline setup mocks and test marker validation plus its real `policy_apply` call ordering. |
| `tests/test_execution_resources.py` | Mock role flags, DDL denial, settings, endpoint and membership audit; column ACL/FORCE-RLS stops; actual fingerprint algorithm over mock metadata; mandatory safety and ablation routing. |
| `Codex_R03_Work_Log.md` | This single R03 implementation record. |

`schema.sql`, `seed_data.py`, both R02 artifacts, R01 template, access-matrix
YAML, `AGENTS.md`, semantic/catalog/validator/evaluation source, and all other
out-of-scope files are unchanged. No edits to `connections.py`, `executor.py`
or the fingerprint implementation were needed; the new tests exercise their
existing behavior. Existing review-document edits are excluded from the PR.

Frozen bytes checked during the handoff:

| File | SHA-256 |
| --- | --- |
| `schema.sql` | `f1b5976a08ebeeeb085d7095ddf25edfb06a261b2ebfe9f0653cb3a8b5128bf3` |
| `seed_data.py` | `ee9fd0a9965b51f6289290caa211460a65f9b2c38728bf99bb1133265d0561bf` |
| `fixture_pg_dump.sql` | `859aa6badb797159f846d0870e377e3aade04049adc4174d2cd7dd6a98dd4fc4` |
| `fixture_manifest.json` | `fb15e54afc4b72e02076614fec108049595ab1879feeabe9871f131fccb2640e` |
| `src/inference/prompt_template.txt` | `67d1c6d265202e6bf6abcd1393203e84b92bf9df03207015679339fe807ad6b6` |

## 4. Commands executed and test evidence

Tests used the review's existing isolated environment at
`H:\STARK_T2SQL_R02_ENV`, with Python 3.12.10, pytest 8.3.5, Faker 40.43.0 and
psycopg2-binary 2.9.13. The first focused run returned **149 passed, 4 failed,
7 skipped**. One failure was an overly broad new test assertion treating the
PUBLIC-only schema CREATE revoke as a role-specific cleanup statement; three
were a missing `sqlglot` dependency in that environment. The assertion was
corrected. The already-declared `sqlglot>=25.0` dependency was installed only in
the isolated environment, resolving to 30.22.0. No parser approval/reference was
created and no dependency manifest was changed. Further explicit RLS/membership
and mocked permission-denial cases were added before the final runs.

Final focused command from the repository root:

```powershell
$env:STARK_TEST_ENABLE_DB_INTEGRATION = '0'
$env:PYTHONPATH = 'src;.'
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest tests/test_policy_contracts.py tests/test_database_integration.py tests/test_execution_resources.py tests/test_schema_contracts.py -q -ra
```

Final full-suite command:

```powershell
$env:STARK_TEST_ENABLE_DB_INTEGRATION = '0'
$env:PYTHONPATH = 'src;.'
& 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe' -m pytest -q -ra
```

| Final actual run | Passed | Failed | Skipped | Exit code |
| --- | ---: | ---: | ---: | ---: |
| Focused R03 | **163** | **0** | **7** | **0** |
| Full Python suite | **463** | **0** | **177** | **0** |

Focused skips are six explicitly disabled live database cases and the external
schema-metadata test. The full suite retains the other external schema/parser,
adversarial-scope, independent-reference and wall-clock review dependencies,
disabled database cases and the disabled R02 live reset test. One previous
policy metadata skip is removed because exact grant generation now runs
offline. Skips are not passing acceptance tests. The pre-existing
pytest-asyncio fixture-loop-scope deprecation warning remains.

The full suite includes the frozen R02 artifact regeneration/hash checks. No
fixture artifact was regenerated or modified during R03. No PostgreSQL server,
model or application server was started, and no database connection,
provisioning, policy application, reset or live SQL submission occurred.

## 5. Pending live provisioning and verification sequence

The following is a future owner/Antigravity verification sequence, **not actions
executed or evidence obtained by Codex**:

1. Use an explicitly authorized isolated PostgreSQL 16 test instance on numeric
   loopback TCP. Establish an isolated business fixture database and a physically
   distinct disposable evaluation clone on that instance. Exclude production
   and all unverified databases; no destructive commands are authorized here.
2. Initialize the empty targets with the unchanged `schema.sql` and restore the
   committed, digest-verified R02 data snapshot through separate trusted setup
   credentials. Independently verify actual loaded rows and counts.
3. Supply real reviewed resource-budget measurements and their source/hash.
   The 64 KiB / 10,000 KiB values in unit mocks are not measurement evidence or
   new recommended production limits. Configure distinct administrative,
   business-login and dedicated SELECT-only baseline aliases and private
   credentials outside source control.
4. Independently provision the clone COMMENT marker using actual source/clone
   OIDs, fixture digest and private token. Compile the business plan with
   `baseline_eval_login=None`; compile the clone plan with its dedicated
   baseline login. Apply compiler-produced plans only after fixture restore
   through the trusted administrative `policy_apply` path. Record the actual
   resulting `InstallationBinding` policy-state digest for each target.
5. Resolve actual personas and compose audited runtime/clone sources with the
   real bindings and provenance. Supply an owner composition helper and
   independently recorded employee/leave scope counts; do not derive acceptance
   solely from the same RLS policy being tested.
6. Set `STARK_TEST_ENABLE_DB_INTEGRATION=1`,
   `STARK_TEST_AUTHORIZATION_COMPOSITION_PATH` and
   `STARK_TEST_EXPECTED_SCOPE_COUNTS_PATH`, then run
   `python -m pytest tests/test_database_integration.py -v` in that explicitly
   isolated environment. Use actual reviewed parser/harness inputs for separate
   `NO_VALIDATOR` adversarial execution, never a unit-only reviewer.
7. Record real role/default/DDL/column checks, FORCE-RLS scope results, baseline
   full-clone visibility without production access, forbidden projections and
   function SQLSTATEs, actual drift rejection and repeated apply behavior.
   Preserve unexecuted safety cases as safety stops, not database blocks.

**Live ACL/RLS enforcement, clone isolation behavior, negative PostgreSQL
SQLSTATEs, live `NO_VALIDATOR` behavior, actual installation idempotence and
measured resource limits remain pending.** The original historical dataset
fidelity is not newly claimed. No live evidence or owner approval record was
fabricated to close these gaps.

## 6. Publication and stopping gate

Codex committed the nine implementation/test/log paths as
[`1bbd5950494f1dda592127c68bfafea5700652bc`](https://github.com/Vivek-k24/Stark_T2SQL/commit/1bbd5950494f1dda592127c68bfafea5700652bc),
`Fix R03 baseline login bootstrap and clone-only policy application`, at
2026-10-14 15:05:13 America/Chicago. The commit was pushed explicitly to
`origin/codex/r03-remediation`. GitHub's contents API confirmed that the pushed
work-log blob matched the local committed blob before the PR was created.

Codex opened the single [draft PR #14](https://github.com/Vivek-k24/Stark_T2SQL/pull/14)
from `codex/r03-remediation` into `gemini/full-remediation-review`. This handoff
update records the actual commit and PR URL in the same work log/branch/PR; it
changes no tested source or artifact bytes. No tests are rerun for this
documentation-only update.

**Source implementation and prescribed offline verification are complete and
published for independent review. Live acceptance remains pending.**

**Stop for Antigravity's independent implementation verification in the same
`Antigravity_R03_Review.md`. Do not merge, close the gate as live-accepted, or
begin R04.**
