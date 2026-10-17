# STARK security policy: audit and gated installation plan

**Prepared:** 2026-10-16 by Claude Code (backend/integration owner).
**Status:** **APPROVAL REQUIRED. Nothing has been installed.** No database connection was made to prepare this document. All database facts below come from the owner's own pre-change backups, read offline (`pg_restore -l`, `CREATE ROLE` lines only), and from read-only config files.

## 1. What would be installed

| Item | Value |
|---|---|
| Draft file | `H:\STARK_Runtime\stark_security_policy_DRAFT_20261016.sql`, 19,681 bytes, SHA-256 `0d00d8b1fe035f257ff20a66790ea408116e16c57ac25aa054457b6471f6df93` |
| Provenance | **Identical** (after CRLF→LF normalization) to `compile_policy()` output from `policy/access_matrix.yaml`. Verified by `python -m ops.policy_plan` and `python -m ops.install_policy plan`. |
| **Approval digest** (compiler SQL text) | **`8dca38bfecc8e4ccc0948adb3749cf8e2bf45dee24912b36a83884c1139da3c5`**, 97 statements |
| Access matrix | `85efd46ce237aea0dab8aac57af81c667320508ef841dbf79c5f2eebfefd42e9` |
| Fixture dump (manifest-verified) | `859aa6badb797159f846d0870e377e3aade04049adc4174d2cd7dd6a98dd4fc4` |
| Login budgets | `statement_timeout=15000ms`, `work_mem=4096kB`, `temp_file_limit=65536kB`, `default_transaction_read_only=on`, `row_security=on`, `search_path=pg_catalog, public, pg_temp` |
| Resource evidence | `H:\STARK_Runtime\stark_pg_resource_20261016_171019.txt`, SHA-256 `c2bb48ff6c913fe9d43fb60652a0a600d378f4ce6f2f56aa1775b14680129b14` (full hash; the handoff showed only a prefix) |
| Target | `127.0.0.1:5433/stark_test`, PostgreSQL 17.2 (dump header), service `postgresql-x64-17` |

**Install mechanism.** Use `python -m ops.install_policy apply`, which wraps the existing `stark_t2sql.db.policy_apply`. Do **not** run `psql -f` on the raw draft: it has no transaction wrapper and no target-identity guard. `policy_apply` runs as one transaction. It first checks the database name and that the session is the admin login, not a managed role. It then **recompiles the plan from the live catalog** and refuses the install if that differs from the approved plan. It returns the `policy_state_sha256` that the persona runtime pins. The wrapper also refuses to run if the digest is not the approved one, if the live row counts differ from `fixture_manifest.json`, if the session is not superuser, if no backup file is given, or if the binding output path is inside the repository.

## 2. Observed pre-state (offline evidence)

- `pg17_roles_before_stark_20261016_170339.sql` (SHA-256 `866f0d7f…c647`) contains **one role, `postgres`**, and no memberships. None of the seven managed roles exist.
- `stark_test_before_security_20261016_165431.dump` (SHA-256 `7f0feec8…b0ae`, PG 17.2): 12 fixture tables plus sequences, constraints, indexes and foreign keys, **all owned by `postgres`**. It has **no RLS, no policies and no functions**.
- `postgresql.conf`: `listen_addresses = '*'`, `port = 5433`. Live listeners: `0.0.0.0:5433` and `[::]:5433`.
- `pg_hba.conf`: only `127.0.0.1/32`, `::1/128` and local socket entries, all `scram-sha-256`.
- The cluster also hosts other projects' databases. A superuser credential belonging to another project exists on this host. **It was not used**, because it is not a designated STARK credential.

## 3. Audit findings

| # | Area | Finding | Severity / action |
|---|---|---|---|
| A1 | Roles (FR-6.1, R5) | Creates `app_payroll`, `app_hr_bp`, `app_sales_mgr` (NOLOGIN) and `stark_{payroll,hr,sales}_login` (LOGIN). Also creates `stark_scope_owner` (NOLOGIN, definer owner). All are NOINHERIT, NOSUPERUSER, NOBYPASSRLS, NOCREATEDB, NOCREATEROLE and NOREPLICATION. A guard aborts the transaction if any managed role already exists with privileged attributes or owns unauthorized objects. | OK |
| A2 | Memberships | Revokes every membership edge that touches a managed role, then grants exactly `business TO login WITH ADMIN FALSE, INHERIT FALSE, SET TRUE`. That syntax needs PG16 or later and is valid on 17. Only new roles are touched. | OK |
| A3 | Login separation | Logins get only `USAGE` on `public` and `EXECUTE` on `set_config`. They get no table privileges, and `INHERIT FALSE` means none arrive implicitly. They can reach data only through `SET LOCAL ROLE` to their single business role. | OK |
| A4 | Grants (FR-6.5, R1) | Revokes all table, sequence and **column** privileges in `public` from PUBLIC and managed roles. Then it grants table-level SELECT only for full-access tables, and column-level SELECT on `employees` (HR: 13 columns without `employee_number`; sales: 5 columns). There is no table-level grant on `employees` for HR or sales. This matches FRD §6.2 exactly. | OK |
| A5 | RLS (FR-6.6, R2, R3) | Drops all existing policies on `employees` and `leave_balances`. It then ENABLEs and FORCEs RLS and creates 5 explicit SELECT policies: payroll `true` on both tables; HR scoped by division through the definer helper, and `leave_balances` by visible employees; sales `manager_id = principal`. Every role with a grant on an RLS table has a policy. FORCE RLS doesn't restrict superusers, so admin reference counts still work. | OK |
| A6 | Empty-string safety (FR-6.8) | Every principal read is `NULLIF(pg_catalog.current_setting('app.principal_id', true), '')::int`. | OK |
| A7 | Definer helper (FR-6.7) | `public.hr_bp_current_divisions()`: zero arguments, `STABLE SECURITY DEFINER`, `SET search_path = pg_catalog, public, pg_temp`, schema-qualified body. Owner is `stark_scope_owner`, with column SELECT on 3 `hr_bp_assignments` columns only. EXECUTE is revoked from PUBLIC and granted to `app_hr_bp` only. A guard refuses to proceed if a principal-argument variant exists. `public` stays on the trusted path, but CREATE on `public` is revoked from PUBLIC and managed roles, so only superusers could plant a shadowing object. | OK (low residual) |
| A8 | `set_config` (FR-6.4) | REVOKE from PUBLIC and managed roles, then GRANT to the 3 logins. It is the **last** statement, after the fixture restore. `pg_proc` is per-database, so **other databases are unaffected**. Any future non-superuser restore into `stark_test` would fail on `set_config` calls, so restore as superuser. | OK; note |
| A9 | Known gap (FRD §2.4) | SQL `SET app.principal_id = …` is **not** blocked by the database. The validator (FR-5) is the only preventive control. `install_policy probe` measures this explicitly in a rolled-back read-only transaction. | Documented single-layer dependency |
| A10 | Read-only (FR-6.2/6.3) | `default_transaction_read_only=on` is set on the logins both globally and `IN DATABASE`. The executor also sets `conn.readonly=True` on every transaction. | OK |
| A11 | Resource limits (FR-6.11) | The settings live on the login role, so they survive `SET LOCAL ROLE`. `temp_file_limit` is superuser-only and is applied by a superuser. **The evidence file holds three fixture-scale `EXPLAIN ANALYZE` plans (≤32 kB memory, no temp files).** That supports `work_mem=4 MB`. It doesn't measure `temp_file_limit` or an S8 abuse case. | **Medium.** Treat 64 MB as an owner-accepted initial value and re-measure in the S8 probes. |
| A12 | Idempotency | Guarded `CREATE ROLE`, normalizing `ALTER ROLE`, rebuilt memberships, `CREATE OR REPLACE FUNCTION`, drop-and-recreate policies, and idempotent GRANT/REVOKE. A re-run converges to the same state, and `policy_apply` refuses stale plans. | OK |
| A13 | Cross-database | New roles are cluster-global. Their `ALTER ROLE … SET` defaults apply in every database, but only to these roles. **The logins can CONNECT to other databases in the cluster** through the default PUBLIC CONNECT, and `pg_hba` admits `all` databases. There they have PUBLIC privileges only. | **Medium.** Optional `pg_hba` hardening, see §6. |
| A14 | Passwords | The draft creates LOGIN roles **without passwords**. Under scram-sha-256 they can't authenticate until the owner sets passwords out-of-band. | **Blocker for live runtime.** Owner step 4 below. |
| A15 | Exposure (FRD §2.1) | `listen_addresses='*'` deviates from loopback-only. It is mitigated because `pg_hba` admits loopback addresses only, so remote attempts fail authentication. | **Deviation.** Owner decision, see §6. |
| A16 | Version (FRD §1.2) | PostgreSQL 17.2 runs instead of 16. The policy uses only PG16+ features that behave the same on 17. | **Deviation.** Owner decision: accept and record it, or install PG16. |
| A17 | Unrelated port | Apache `httpd` listens on `0.0.0.0:8080`. `load_config` puts `127.0.0.1:8080` on the allowlist as an alternate model endpoint. The client only ever uses the configured 8081 URL. | Low; note |

## 4. Expected catalog changes

- **Roles (global):** +7 roles and +3 membership edges.
- **`stark_test` ACLs:** PUBLIC loses CREATE on schema `public` (already absent on PG15+ by default), CREATE and TEMPORARY on the database, any table, sequence or column privilege in `public`, and EXECUTE on `set_config`. The managed roles receive the grants in A3, A4, A7 and A8.
- **Objects:** +1 function owned by `stark_scope_owner`, +5 policies, and RLS enabled and forced on 2 tables.
- **Role settings:** 6 settings × 3 logins, both global and `IN DATABASE stark_test`.
- **Data:** none. No row is modified.

## 5. Procedure (owner-executed, or by Claude after explicit approval)

Run from `H:\STARK T2SQL` in one PowerShell window. Passwords are read interactively into process environment only. Never put them on the command line or in a file.

```powershell
$py = 'H:\STARK_T2SQL_R02_ENV\Scripts\python.exe'
$pg = 'C:\Program Files\PostgreSQL\17\bin'
$env:PYTHONPATH = 'src;.'
$env:STARK_PG_DATABASE = 'stark_test'; $env:STARK_PG_PORT = '5433'
$env:STARK_DATABASE_WORK_MEM_KIB = '4096'; $env:STARK_DATABASE_TEMP_FILE_LIMIT_KIB = '65536'
$env:STARK_RESOURCE_MEASUREMENTS_PATH = 'H:\STARK_Runtime\stark_pg_resource_20261016_171019.txt'
$s = Read-Host -AsSecureString 'postgres password'
$env:STARK_ADMIN_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
$ts = Get-Date -Format yyyyMMdd_HHmmss

# 1. Read-only inventory (no changes). Confirms version, address, row counts and pre-state ACLs.
& $py -m ops.install_policy inspect --database stark_test --out "H:\STARK_Runtime\policy_inspect_before_$ts.json"

# 2. Fresh backups outside the repo. The roles dump contains password hashes: keep it private.
$env:PGPASSWORD = $env:STARK_ADMIN_PASSWORD
& "$pg\pg_dump.exe" -h 127.0.0.1 -p 5433 -U postgres -Fc -d stark_test -f "H:\STARK_Runtime\stark_test_pre_policy_$ts.dump"
& "$pg\pg_dumpall.exe" -h 127.0.0.1 -p 5433 -U postgres --roles-only -f "H:\STARK_Runtime\roles_pre_policy_$ts.sql"
Remove-Item Env:PGPASSWORD

# 3. Apply (single transaction; refuses on any mismatch).
& $py -m ops.install_policy apply --database stark_test `
    --approve-sha256 8dca38bfecc8e4ccc0948adb3749cf8e2bf45dee24912b36a83884c1139da3c5 `
    --confirm-fixture-restored --confirm-dedicated-database `
    --backup "H:\STARK_Runtime\stark_test_pre_policy_$ts.dump" `
    --binding-out "H:\STARK_Runtime\stark_policy_installation_binding_$ts.json"

# 4. Owner sets login passwords interactively (never logged, never in argv):
& "$pg\psql.exe" -h 127.0.0.1 -p 5433 -U postgres -d stark_test
#    \password stark_payroll_login
#    \password stark_hr_login
#    \password stark_sales_login
#    \q

# 5. Catalog verification (read-only) and behavioural probes (rolled back).
& $py -m ops.install_policy verify --database stark_test --out "H:\STARK_Runtime\policy_verify_$ts.json"
#    probe needs the three login passwords in STARK_PAYROLL_PASSWORD / STARK_HR_PASSWORD / STARK_SALES_PASSWORD
& $py -m ops.install_policy probe --database stark_test --out "H:\STARK_Runtime\policy_probe_$ts.json"
```

`probe` checks the following, computing every expected count independently as superuser using the documented predicates. It never trusts a zero.

- Employee and leave counts for all four personas against those independent counts.
- Refusals with SQLSTATE 42501 for:
  - `SELECT *` by sales
  - `employee_compensation` access by sales
  - `employee_number` and payroll tables by HR
  - direct `hr_bp_assignments` reads
  - `SET ROLE` to another business role
  - `set_config` after the role switch
  - `pg_read_file`
- A write inside the read-only transaction refused with 25006 (or 42501).
- The documented `SET app.principal_id` spoof gap (A9).

## 6. Rollback

**Preferred (exact):** within the single apply transaction, any error rolls back automatically. After a successful install, run as superuser:

```sql
BEGIN;
DROP POLICY IF EXISTS stark_select_app_hr_bp      ON public.employees;
DROP POLICY IF EXISTS stark_select_app_payroll    ON public.employees;
DROP POLICY IF EXISTS stark_select_app_sales_mgr  ON public.employees;
DROP POLICY IF EXISTS stark_select_app_hr_bp      ON public.leave_balances;
DROP POLICY IF EXISTS stark_select_app_payroll    ON public.leave_balances;
ALTER TABLE public.employees      NO FORCE ROW LEVEL SECURITY, DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.leave_balances NO FORCE ROW LEVEL SECURITY, DISABLE ROW LEVEL SECURITY;
DROP FUNCTION IF EXISTS public.hr_bp_current_divisions();
GRANT EXECUTE ON FUNCTION pg_catalog.set_config(text, text, boolean) TO PUBLIC;
GRANT TEMPORARY ON DATABASE stark_test TO PUBLIC;      -- restore PUBLIC defaults recorded by step 1
DROP OWNED BY app_hr_bp, app_payroll, app_sales_mgr,
              stark_hr_login, stark_payroll_login, stark_sales_login, stark_scope_owner;
COMMIT;
DROP ROLE stark_hr_login, stark_payroll_login, stark_sales_login,
          app_hr_bp, app_payroll, app_sales_mgr, stark_scope_owner;
```

Compare against `policy_inspect_before_*.json` afterwards. Restore any PUBLIC ACL that step 1 recorded differently.

**Fallback:** `pg_restore --clean --if-exists -d stark_test stark_test_pre_policy_<ts>.dump` plus the `DROP ROLE` above. This is a destructive restore and needs its own approval.

## 7. Separate, optional hardening (each needs its own approval)

1. **Loopback binding (A15):** `listen_addresses = '127.0.0.1'` in `postgresql.conf`, then restart `postgresql-x64-17`. Every client on this machine already uses 127.0.0.1.
2. **Restrict STARK logins to `stark_test` (A13):** add these lines above the generic `host all all 127.0.0.1/32` entries, then run `SELECT pg_reload_conf();`:
   ```
   host  stark_test  stark_payroll_login,stark_hr_login,stark_sales_login  127.0.0.1/32  scram-sha-256
   host  stark_test  stark_payroll_login,stark_hr_login,stark_sales_login  ::1/128       scram-sha-256
   host  all         stark_payroll_login,stark_hr_login,stark_sales_login  all           reject
   ```
3. **PostgreSQL 16 (A16):** either record an FRD deviation accepting 17.2, or install PG16 side-by-side and re-restore. The second option is a large change and not recommended for the MVP.

## 8. Approvals requested

| ID | Operation | Scope |
|---|---|---|
| **AP-1** | Use the `postgres` superuser credential, supplied by the owner in the session environment, for read-only `inspect` and trusted startup metadata | `stark_test`, read-only |
| **AP-2** | `apply` with digest `8dca38bf…39da3c5` | Cluster-global roles plus `stark_test` ACL/RLS/function changes listed in §4 |
| **AP-3** | Owner sets the 3 login passwords (§5 step 4) | Credentials, owner-only |
| AP-4 | Optional `pg_hba` restriction (§7.2) | Cluster config reload |
| AP-5 | Optional `listen_addresses` change (§7.1) | Service restart |
| AP-6 | Accept PostgreSQL 17.2 as a recorded FRD deviation (A16) | Requirements |
