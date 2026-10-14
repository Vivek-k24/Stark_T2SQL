"""Explicit benign headless probe in an empty disposable read-only workspace."""
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
from .contracts import Stop
from .runtime import native_codex, run, agent_env, ROOT

def main():
    record={"observed_at":datetime.now(timezone.utc).isoformat(),"sandbox":"read-only",
            "approval_policy":"on-request","scope":"fixed public token; no repository/HR inputs",
            "state":"BLOCKED","workspace_write_smoke":"NOT_RUN"}
    command=native_codex()
    try:
        if not command: raise Stop("Native Codex unavailable")
        record["version"]=run([command,"--version"]).strip()
        with tempfile.TemporaryDirectory(prefix="stark-readonly-probe-") as scratch:
            run(["git","init",scratch])
            answer=Path(scratch)/"answer.txt"
            output=run([command,"exec","--sandbox","read-only","-c",'approval_policy="on-request"',
                "-c",'approvals_reviewer="user"',"--json","--output-last-message",str(answer),"-"],
                cwd=scratch,env=agent_env(),timeout=90,
                input="Without using tools or reading files, reply with exactly STARK_INT01_READONLY_OK.")
            events=[json.loads(line) for line in output.splitlines() if line.strip()]
            tools=[e for e in events if e.get("item",{}).get("type") in {"command_execution","mcp_tool_call","web_search"}]
            if answer.read_text(encoding="utf-8").strip()!="STARK_INT01_READONLY_OK" or tools:
                raise Stop("Probe did not meet no-tool exact-response contract")
            record.update(state="PASSED",tool_calls=0,headless_authenticated=True)
    except (Stop,OSError,ValueError): record["reason"]="Headless read-only probe did not complete its exact-response contract"
    destination=ROOT/"ops/evidence/codex-probe.json"; destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(record,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(record)); return 0 if record["state"]=="PASSED" else 2

if __name__=="__main__": raise SystemExit(main())
