# Live UI security impact and pending enablement reviews

This implements the first model-off frontend deliverable and non-destructive operator setup requested in `CODEX_LIVE_UI_HANDOFF.md`. It does not approve real account authentication, administrator mutation or PostgreSQL permission execution.

## Current trust boundary

- One fixed local synthetic fixture on numeric loopback. No generic schema, remote host, arbitrary SQL, model-provider or role editor is introduced.
- Existing administrator authentication authorizes only fixed read-only metadata/fixture resolution. Those connections close before safe projections are returned. The metadata facade has no answer/executor/connection capability.
- Restricted connections use isolated private mappings rather than assigning browser credentials to `os.environ`. The administrative source retains only its own alias inputs; the business source retains only its configured restricted credentials. The canonical FULL executor and its live audits are preserved.
- Browser session flags never grant a workspace. A cryptographically random handle is useful only with the same server-assigned Streamlit session ID; server-side expiry, replacement, disconnect and capacity limits apply. No session handle grants app-admin authority.
- Form password state is removed on submit. Exception text, SQL, passwords and raw catalogs do not enter user notices. Five setup attempts per session and twenty process-wide per minute bound authentication retries. These limits are local process controls, not reviewed multi-user account lockout.
- Optional configured environment is an explicit operator-supplied server configuration. It does not read another project's credentials. The ordinary offline pytest configuration prevents automatic database startup.
- Metadata is a verified snapshot, labeled with UTC inspection time. Later drift can make it stale. Each real candidate still receives the existing fresh installed-policy and privilege audits. A snapshot does not certify continuous policy integrity.
- SQLCoder readiness is checked independently. No rendering path starts it; an offline/missing generation capability returns no SQL result. The known SQL `SET app.principal_id` single-layer dependency remains. It is not claimed database-proof.

## Scope expansion against FRD 1.8

Original FR-1.4 and MVP scope excluded real user authentication. The owner now requests it, but the handoff explicitly requires threat-model and enablement review. Existing simulated personas and PostgreSQL service passwords must never be relabeled as real app-user accounts or administrator login. Admin Panel, Login/Signup and Data Lab explicitly identify their unimplemented state; disabled controls do not constitute feature completion.

The following is a concrete proposal for independent review, not an installed or approved authentication implementation. No dependency, account store, identity service or new listener is created in this delivery.

### Proposed local accounts and session boundary — REVIEW REQUIRED

Use Django 5.2's authentication, database-backed sessions, CSRF middleware and password-reset primitives as the candidate account/session foundation. Propose its Argon2id hasher through `argon2-cffi`; benchmark parameters against this workstation's RAM before selecting them. Pin supported patch versions and review dependencies before any installation. These are library capabilities, not evidence of a working Streamlit integration. [Django authentication](https://docs.djangoproject.com/en/5.2/topics/auth/default/), [password hashing](https://docs.djangoproject.com/en/5.2/topics/auth/passwords/).

Keep account, entitlement, revocable-session and append-only audit records in a separate local application store outside Git, never in the frozen `stark_test` schema. A proposed operator-selected path is `%LOCALAPPDATA%\STARK_T2SQL\accounts.sqlite3`; its ACL, backup and recovery design need approval before creation. A pending signup has no active account, persona selection, database access or administrator permissions. The first owner is bootstrapped only by an explicit interactive local operator step; there is no default administrator password. Proposer, security reviewer and owner are distinct real account identities, separate from the four simulated personas and PostgreSQL service logins.

An authenticated identity must be verified server-side before every persona selection, query, administrative action and proposal transition. Revocation must affect existing tabs and long-lived Streamlit connections. Use server-side expiry, session rotation, logout/revocation, account approval/lockout and generic error messages. Persistent retry limits must cover login, signup, bootstrap and reset; the present in-memory database setup throttle is insufficient. Reset is an independently authorized local recovery action, with single-use expiry and session revocation; no email or external identity provider is silently introduced.

**Integration decision still required:** Streamlit's native login uses OIDC and does not supply application authorization. It does not turn this proposed Django account store into a compatible login provider. An authentication-only loopback gateway or a reviewed local OIDC bridge would require explicit architecture review, precise origin/cookie/WebSocket session binding, and independent denial tests. Neither is implemented or selected as an approved service. A new generic data API remains excluded. Do not fill this gap with a custom password checker plus `session_state['is_admin']`. [Streamlit authentication and cookie/session behavior](https://docs.streamlit.io/develop/concepts/connections/authentication).

The enablement evidence must include cross-session theft/replay, forged browser claims, direct backend calls, CSRF, fixation, enumeration, throttling, expired/revoked/reset sessions, zero-rights signup, self-approval and same-person multi-role approval denials. Review the existing local operator setup separately: possession of all four service passwords permits metadata inspection today; it is not an application administrator login. Until the account boundary is verified, account creation, per-user persona grants and administrator mutation stay disabled.

The future proposer, security reviewer and owner must be independently authenticated and distinct for high-risk policy changes. `PERMISSION_APPROVAL_DESIGN.md` remains authoritative for digest-locked plans, source/live diffs, regression evidence, tested recovery, fresh drift checks and separate execution confirmation. The current permission preview is not persistent, authenticated, compiled, approved or executable. No submit/approve/apply implementation is claimed.

## Secrets and deployment limits

No secure OS-backed persistent credential store is implemented. The masked setup and optional environment remain development/operator mechanisms. Local OS peers, a compromised browser/process or memory inspection are outside their protection; loopback HTTP is not authenticated user transport. Temporary shared development service passwords do not satisfy real account security. Rotation, persistence, HBA/firewall/service configuration and authentication activation each need their explicit review/operation approval.

### Proposed persistent secret design — REVIEW REQUIRED

Use Windows DPAPI `CryptProtectData` under the operator's current Windows user, with UI prompts forbidden and **without** `CRYPTPROTECT_LOCAL_MACHINE`. Store only the encrypted, versioned role-secret bundle in an operator-selected file under `%LOCALAPPDATA%\STARK_T2SQL\secrets`, outside Git. Require a reviewed current-user ACL, fixed-target/role binding, atomic replacement, restrictive backup handling and explicit confirmation before saving or replacing secrets. DPAPI's machine-wide flag would allow other users of the same machine to decrypt and is unsuitable here. [Microsoft DPAPI contract](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata).

Only a verified local operator or, after authentication review, an authorized server-side administrator may request decryption. Decrypt only into a private connection-source mapping; never publish plaintext through widget defaults, session objects exposed to personas, URLs, shell arguments, traces or error text. Distinguish Windows-user binding from app-user authorization: another process running as the same Windows user, an administrator or a compromised STARK process can still defeat this protection. Proposed recovery must test wrong-user, corrupted-blob, missing-key and backup-restore failures without falling back to plaintext or a machine-wide key. Secure deletion/zeroization is not promised. This proposal has not created a key, ACL, encrypted file or credential-manager entry and has not passed its required Windows storage tests.

PostgreSQL 17 is the owner-designated installed target in this handoff; FRD 1.8 historically specifies 16. This delivery records the deviation and actual tests rather than claiming PostgreSQL 16 compliance. No listener/service/HBA changes are made.

Faker work must remain deterministic preview/export in a separately reviewed fixed-schema contract; no authoritative reset, reseed or planted-fact change is authorized. No sealed holdout, real employee data, cloud service, unattended coordinator or production promotion is introduced.
