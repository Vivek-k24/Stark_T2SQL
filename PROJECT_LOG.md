# STARK T2SQL — project log

FRD 1.8 names this file as the chronological record of decisions and measurements (FR-9.8, T1.3.3). Gate-by-gate records before this date are in `Codex_*_Work_Log.md` and `Antigravity_*_Review.md`. Those are audit records and are not rewritten here. Each entry separates **measured**, **offline-tested** and **not demonstrated**.

---

## 2026-10-16 — Step 29 re-entry (Claude Code, backend/integration owner)

**Original "Step 29" definition:** not found in any repository or `H:\` text record. The handoff states that it is not reproducible, and this work continues from the handoff's provisional packages without inventing earlier approvals.

### Baseline state (observed)
- Branch `codex/r09-remediation` @ `986e4e1`. R01–R08 are merged into `gemini/full-remediation-review`. The R09 draft is PR #24.
- Uncommitted work from the previous session was preserved as-is: `config.py`, `orchestrator.py`, `ops/{policy_plan,runtime_preflight,serve_connected}.py`, `utils/local_sources.py` and 4 test files. It was neither stashed nor reset.
- Offline suite (`STARK_TEST_ENABLE_DB_INTEGRATION=0`): **1,761 passed, 64 skipped, 0 failed** (50 s). The 64 skips are 32 parser representations excluded by the R05 evidence, 16 for the wall-clock review input, 9 for DB/live opt-ins, 6 R09 phase scaffolds and 1 R02 reset. None of them is acceptance evidence.

### Runtime evidence (measured 2026-10-16)
| Item | Observation |
|---|---|
| PostgreSQL | Service `postgresql-x64-17` is running. `listen_addresses='*'`, with listeners on `0.0.0.0:5433` and `[::]:5433`. `pg_hba` admits loopback only (scram-sha-256). The `stark_test` dump header says **17.2**. |
| DB credentials | **None designated for STARK.** No `STARK_*`/`PG*` environment variables and no pgpass. A superuser credential belonging to another project exists on this host. **It was not used.** |
| Cluster roles | Only `postgres` (from the owner's roles backup, 17:03). No STARK roles exist. |
| `stark_test` | 12 fixture tables owned by `postgres`, with no RLS, policies or functions (owner's dump at 16:54, read offline with `pg_restore -l`). |
| llama.cpp | `llama-server` build **b11609-fcac19079**, bound to `127.0.0.1:8081`, `--ctx-size 4096 --parallel 1 --threads 4`, 1 slot. Launcher SHA-256 `a3e80f62…ecb9f0`. |
| GGUF | `sqlcoder-7b-2.Q4_K_M.gguf`, 3.80 GiB, SHA-256 `a23c0412…c0bc2`. Download date and repository are not recorded locally (FR-4.9 provenance still open). |
| Host | i5-1135G7 (4C/8T), 15.8 GB RAM, **0.4 GB free** under load. llama-server private memory 8.1 GB at 4,096 context. |
| Streamlit | Offline UI on `127.0.0.1:8501`. |

### E1 model measurements (T1.3.2): model-only lane, no database
Script outside the repository. It uses the repository's context builder, prompt builder, native-stop parser, extractor and validator, with the **TEST_ONLY** R05 parser profile, greedy decoding (T=0, seed 42, n_predict 300, stop `;`), `as_of_date=2026-10-12`.

**v2 prompt size by role** (llama.cpp `/tokenize`, sample question):

| Role | DDL tokens | Semantic tokens | Prompt tokens | Fits 4,096 ctx with 300 generated? |
|---|---:|---:|---:|---|
| app_payroll | 2,290 | 5,644 | **8,054** | **No.** The server rejects it before generating. |
| app_hr_bp | 969 | 2,160 | 3,249 | Yes |
| app_sales_mgr | 580 | 1,085 | 1,785 | Yes |

**Throughput and latency** (single slot, warm process):

| Case | Prompt tok | Prompt tok/s | Gen tok | Gen tok/s | Wall |
|---|---:|---:|---:|---:|---:|
| sales: direct reports | 1,774 | 16.9 | 47 | 1.59 | 135.6 s |
| sales: email of every employee | 1,775 | 14.3 | 92 | 1.54 | 184.5 s |
| hr_1: hires after 2026-01-01 | 3,261 | 12.5 | 55 | 1.83 | 291.1 s |

- Native stop metadata is present: `stop_type=word`, `stopping_word=";"` → `SEMICOLON_STOP`. Beam search was not tested (FR-4.6), so this is a greedy baseline only.
- **Prefix cache is ineffective:** `cache_n` was 15–22 tokens. The model-card template puts `{user_question}` on line 2, before the schema, so every request re-evaluates the full prompt.
- **Every FULL request exceeds the initial 120 s `generation_timeout` (NFR-4).** On the current runtime they would all end as FC-TIMEOUT-GEN.

**Candidate outcomes** (observations only; not scored and not a benchmark):

| Case | Extracted SQL (abridged) | Validator | Likely DB outcome |
|---|---|---|---|
| sales: direct reports | `… WHERE e.manager_id = 1234567890 AS OF '2026-10-12'` | REJECT `V-PARSE` | not executed |
| sales: email (out of entitlement) | `… JOIN views v …` | REJECT `V-TABLE` | not executed |
| hr_1: hires after 2026-01-01 | `… WHERE e.hire_date > '2026-01-01' AND e.as_of_date <= '2026-10-12'` | ACCEPT | 42703 → MODEL_SQL_ERROR (FC-HALLUC) |

**Observed pattern:** in all three completed generations the `As-of date:` line pushed the model into invented date syntax or columns. If repeated measurement confirms it, this is the dominant failure class E9 S9.2 anticipates. Any prompt change is a new baseline and needs the owner (FR-3.7, FR-9.8).

### Decisions and approvals pending
See `docs/POLICY_INSTALL_PLAN.md` §8 and `H:\STARK_Runtime\CLAUDE_BACKEND_HANDOFF.md`. **No database, service, credential or configuration change was made.**
