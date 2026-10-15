# STARK local UI and manual progress updates

The agent dispatcher, Windows scheduled task setup, credential enrollment,
background progress synchronization and CLI probes have been retired at the
owner's request. **There is no automatic agent execution.**

## Run the existing local UI

From the repository root with the required Python dependencies installed:

```powershell
python -m ops.serve
```

Open http://127.0.0.1:8501 in your browser. This launches Streamlit only on
numeric loopback, with connected SQL disabled. Health, Architecture, Progress
and the original E0 offline demonstration work without PostgreSQL or the model.
The example results are **DEMO / STATIC / SIMULATED**.

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
