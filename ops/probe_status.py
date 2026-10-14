"""Read-only real GitHub/Windows setup-path probe. Never registers a task."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import tempfile
from .contracts import BASE, Stop
from .github import GitHub
from .runtime import ROOT,run,poll

def main():
    github=GitHub(); before=github.ref(BASE)
    if any(p.get("merged") for p in github.pulls("codex/interim-orchestration-ui")):
        raise Stop("This pre-merge read-only probe must not run after INT01 merge")
    with tempfile.TemporaryDirectory(prefix="stark-status-preflight-") as scratch:
        cfg=json.loads((ROOT/"ops/enrollment.example.json").read_text(encoding="utf-8"))
        cfg.update(enabled=True,python=sys.executable,state_directory=str(Path(scratch)/"private-state"))
        path=Path(scratch)/"enrollment.json"; path.write_text(json.dumps(cfg),encoding="utf-8")
        checked=json.loads(run([sys.executable,"-m","ops.setup_check","--config",str(path)],cwd=ROOT))
        if sys.platform=="win32":
            run(["powershell.exe","-NoProfile","-File",str(ROOT/"ops/enable-coordinator.ps1"),
                 "-Python",sys.executable,"-Config",str(path)],cwd=ROOT)
        result=poll(path)
        if checked["enrollment"]!="CHECKED" or result["state"]!="STOP_AWAITING_OWNER_MERGE" or github.ref(BASE)!=before:
            raise Stop("Status-only preflight did not remain read-only")
    record={"observed_at":datetime.now(timezone.utc).isoformat(),"mode":"status_only","setup_check":"PASSED",
            "actual_github_poll":result["state"],"integration_ref_unchanged":True,
            "task_registered":False,"agent_sessions":0,"github_mutations":0}
    record["windows_check_only_script"]="PASSED" if sys.platform=="win32" else "NOT_RUN"
    (ROOT/"ops/evidence/status-preflight.json").write_text(json.dumps(record,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(record))

if __name__=="__main__": main()
