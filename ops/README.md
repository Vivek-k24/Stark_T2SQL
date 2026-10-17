# STARK local UI and manual progress updates

The agent dispatcher, Windows scheduled task setup, credential enrollment,
background progress synchronization and CLI probes have been retired at the
owner's request. **There is no automatic agent execution.**

## Run the existing local UI

From the repository root with the required Python dependencies installed:

```powershell
python -m ops.serve
```

Open http://127.0.0.1:8501 in your browser. This launches the real app only on
numeric loopback. Open **Settings** to authenticate the existing fixed STARK
database and inspect installed policy/persona metadata read-only. Semantic
Catalog and Access Policy work while SQLCoder is off. The Playground accepts
text but disables Ask while inference is unavailable; it supplies no fake result.
Rendering never starts the model. The separate Offline demo remains **SIMULATED**.

See [the local operator guide](../docs/LIVE_UI_OPERATOR_GUIDE.md) for masked,
nonpersistent setup and the independently gated FULL runtime. Existing private
STARK credential variables plus an explicit installation-binding path may also
supply read-only metadata; credentials never populate widgets or reports.
Ctrl+C stops and reaps the owned foreground child; genuine failures retain a
nonzero status. Real accounts, administrator actions and PostgreSQL permission
mutations remain disabled pending their separate security/enablement reviews.

An optional UI-only Microsoft Edge / Playwright smoke test is available via
`python -m ops.smoke_ui`. It launches and stops its own local server.

## After each reviewed gate

The owner manually asks Antigravity to:
1. Verify the actual PR/merge state and offline vs live test evidence on GitHub.
2. Edit the human-maintained `ops/progress.json` with truthful evidence and
   updated gate state. Never label an unmerged PR as merged.
3. Run `python -m ops.progress` (offline, no network access or git push) to
   update only the Architecture & Progress evidence region in the tracked
   `STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html` file.
4. Commit and push that JSON + HTML with the gate's existing manual-review PR.
5. Also update the owner's separate browser file at
   `H:\STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html.html` from the freshly
   rendered, reviewed GitHub-tracked `.html` file. First preserve any distinct
   local edits in a backup outside the repository, then compare or SHA-256
   hash both copies. Report `LOCAL_UI_UPDATED` only after verifying the
   on-disk file; otherwise report `LOCAL_UI_NOT_UPDATED` and why. No copy
   of the H-drive file or its backup belongs in GitHub.

No scheduler, coordinator, headless agent integration, secret or broker token
is required. No background process updates this information.
