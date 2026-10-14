"""Fail-closed enrollment check before Task Scheduler registration."""
import argparse
import json
import sys
from pathlib import Path
from .runtime import doctor, enrollment, run
from .contracts import Stop, REPOSITORY

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--config",type=Path,required=True)
    args=p.parse_args()
    try:
        cfg,selected,state=enrollment(args.config)
        if Path(cfg["python"]).resolve()!=Path(sys.executable).resolve(): raise Stop("Setup Python differs from enrollment")
        if cfg["mode"]!="status_only":
            capability=doctor()
            if not capability["antigravity"]["available"] or not capability["codex"].get("headless_flags"):
                raise Stop("Installed native CLI capabilities are incomplete")
            if "reason" in capability["codex"] or "reason" in capability["antigravity"]:
                raise Stop("CLI configuration/authentication is not ready")
        if not json.loads(run(["gh","api",f"repos/{REPOSITORY}"]))["permissions"].get("push"):
            raise Stop("GitHub push permission is unavailable")
        print(json.dumps({"enrollment":"CHECKED","gate":selected.name if selected else "AUTO","trigger":"NOT_REGISTERED_BY_CHECK"})); return 0
    except (Stop,OSError,ValueError):
        print(json.dumps({"enrollment":"BLOCKED","reason":"Review doctor, native CLI auth/sandbox smoke evidence and owner enrollment"})); return 2

if __name__=="__main__": raise SystemExit(main())
