"""One-shot durable coordinator. A scheduled task invokes poll, never an install loop."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
from .contracts import BASE, HTML, PROGRESS, Stop, gate, reports, sha

@contextmanager
def ownership(directory):
    """Kernel-backed exclusive project lock, released on crash, no stale PID lock."""
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    with (directory / "ownership.lock").open("a+b") as stream:
        stream.seek(0); stream.write(b"0"); stream.flush(); stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError: raise Stop("Another coordinator owns this project") from None
        try: yield
        finally:
            stream.seek(0)
            if os.name == "nt": msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(stream, fcntl.LOCK_UN)

class Journal:
    def __init__(self, directory):
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(Path(directory) / "coordinator.sqlite")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (gate TEXT, phase TEXT, input_sha TEXT, state TEXT, output_sha TEXT, PRIMARY KEY(gate,phase,input_sha))")
        self.db.commit()
    def claim(self, name, phase, commit):
        old = self.db.execute("SELECT state,output_sha FROM events WHERE gate=? AND phase=? AND input_sha=?", (name,phase,commit)).fetchone()
        if old:
            if old[0] == "DONE": return old[1]
            raise Stop("STOP: prior RUNNING/ERROR attempt requires operator reconciliation; never redispatch blindly")
        self.db.execute("INSERT INTO events VALUES (?,?,?,'RUNNING',NULL)", (name,phase,commit)); self.db.commit()
    def finish(self, name, phase, commit, output, state="DONE"):
        self.db.execute("UPDATE events SET state=?,output_sha=? WHERE gate=? AND phase=? AND input_sha=?", (state,output,name,phase,commit)); self.db.commit()
    def rows(self): return self.db.execute("SELECT * FROM events ORDER BY rowid").fetchall()
    def close(self): self.db.close()

def one_pr(items, selected, *, required):
    if any(p["base"]["ref"] != BASE or p["head"]["ref"] != selected.branch for p in items):
        raise Stop("Unexpected gate PR base/head")
    if len(items) != (1 if required else 0): raise Stop("Missing/duplicate/unexpected gate PR")
    if required and (items[0]["state"] != "open" or not items[0]["draft"]): raise Stop("A single open draft PR is required")
    return items[0] if items else None

class Coordinator:
    """Backend handles safe CLI/broker details. No transition starts a new design."""
    def __init__(self, github, backend, journal, *, trusted_authors):
        self.github, self.backend, self.journal = github, backend, journal
        self.trusted_authors = trusted_authors
    def report(self, selected, phase, commit):
        if self.github.author(commit) not in self.trusted_authors: raise Stop("Untrusted branch commit author")
        path = selected.log if phase == "implementation" else selected.review
        result = reports(self.github.text(path, commit), selected).get(phase)
        if result is None: raise Stop("Expected explicit named report marker is absent")
        return result
    def dispatch(self, selected, phase, input_sha, allowed):
        previous = self.journal.claim(selected.name, phase, input_sha)
        if previous:
            if self.github.ref(selected.branch) != previous: raise Stop("Completed phase branch has unexpected drift")
            return previous
        try:
            output, measured = self.backend.run(selected, phase, input_sha, allowed)
            sha(output)
            if self.github.ref(selected.branch) != output or output == input_sha: raise Stop("Agent push not corroborated")
            changed = self.github.compare(input_sha, output)
            required = {selected.log} if phase == "implementation" else {selected.review, HTML, PROGRESS}
            if not required <= changed or any(not selected.allowed(p, phase, allowed) for p in changed): raise Stop("Phase changed unauthorized files or omitted records")
            report = self.report(selected, phase, output)
            if report["subject_sha"] != input_sha or report["tests"] != measured: raise Stop("Report does not match dispatched commit/measured tests")
            pr = one_pr(self.github.pulls(selected.branch), selected, required=True)
            if pr["head"]["sha"] != output: raise Stop("Draft PR head differs from verified branch")
            self.journal.finish(selected.name, phase, input_sha, output)
            return output
        except Exception:
            self.journal.finish(selected.name, phase, input_sha, None, state="ERROR")
            raise
    def cycle(self, name, design_sha, allowed):
        if name=="INT01": raise Stop("INT01 is status-only; no agent dispatch or next-gate start")
        selected = gate(name); sha(design_sha)
        design = self.report(selected, "design", design_sha)
        if design["status"] == "BLOCKED" or not design["implementation_ready"]: return "STOP_BLOCKED"
        # Only this explicit design event starts implementation. REVISE alone cannot.
        self.github.compare(design["subject_sha"], design_sha)
        if self.github.compare(design["subject_sha"], design_sha) != {selected.review}: raise Stop("Design event must change only its named review")
        head = self.github.ref(selected.branch)
        if head == design_sha:
            one_pr(self.github.pulls(selected.branch), selected, required=False)
            head = self.dispatch(selected, "implementation", design_sha, allowed)
        else:
            # A restarted poll corroborates the saved phase, never trusts arbitrary later docs.
            saved = [r for r in self.journal.rows() if r[:3] == (name,"implementation",design_sha) and r[3] == "DONE"]
            if not saved: raise Stop("Out-of-order commit or uncertain prior dispatch; reconcile before resuming")
            head = saved[0][4]
        implementation = self.report(selected, "implementation", head)
        if implementation["subject_sha"] != design_sha: raise Stop("Stale implementation subject")
        saved = [r for r in self.journal.rows() if r[:3] == (name,"verification",head) and r[3] == "DONE"]
        verified = saved[0][4] if saved else self.dispatch(selected, "verification", head, allowed)
        if self.github.ref(selected.branch) != verified: raise Stop("Verification branch drift")
        verdict = self.report(selected, "verification", verified)["status"]
        return {"VERIFIED_APPROVE":"VERIFIED — AWAITING MERGE", "VERIFIED_REVISE":"STOP_REVISE", "VERIFIED_BLOCKED":"STOP_BLOCKED"}[verdict]

def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("doctor", "dry-run", "poll", "sync", "reconcile"))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--confirm-no-running-agent",action="store_true")
    parser.add_argument("--recover-gate")
    args = parser.parse_args(argv)
    from .runtime import doctor, poll, sync, reconcile
    try:
        if args.command == "doctor": print(json.dumps(doctor(), indent=2)); return 0
        if args.command == "dry-run":
            from .exercise import exercise
            print(json.dumps(exercise(), indent=2)); return 0
        if args.config is None: raise Stop("An outside-repository owner enrollment file is required")
        if args.command=="reconcile" and not args.confirm_no_running_agent:
            raise Stop("Reconciliation requires the operator to confirm old agents have stopped")
        action = {"poll":poll, "sync":sync, "reconcile":reconcile}[args.command]
        result=action(args.config,recover_gate=args.recover_gate) if args.command=="reconcile" else action(args.config)
        save_status(args.config,result)
        print(json.dumps(result, indent=2)); return 0
    except Exception as exc:
        result={"state":"STOP/ERROR", "reason":str(exc) if isinstance(exc,Stop) else type(exc).__name__}
        save_status(args.config,result)
        print(json.dumps(result)); return 2

def save_status(config,result):
    if config is None: return
    from .runtime import ROOT
    path=Path(config).resolve()
    if path.is_relative_to(ROOT): return
    from datetime import datetime,timezone
    try:
        payload=dict(result,observed_at=datetime.now(timezone.utc).isoformat())
        target=path.parent/"coordinator-last-result.json"
        temporary=target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
        temporary.replace(target)
    except OSError: pass  # Never conceal the original stop; SQLite also records phase failures.

if __name__ == "__main__": raise SystemExit(main())
