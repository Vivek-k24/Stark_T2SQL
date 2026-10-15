"""Capture sanitized actual capability checks, with no host paths or credentials."""
from datetime import datetime,timezone
import json
from .runtime import ROOT,doctor,run

def main():
    record=doctor(); record["observed_at"]=datetime.now(timezone.utc).isoformat()
    record["github_cli_version"]=run(["gh","--version"]).splitlines()[0]
    if record["platform"]=="win32":
        query="Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version | ConvertTo-Json -Compress"
        record["windows"]=json.loads(run(["powershell.exe","-NoProfile","-Command",query]))
    destination=ROOT/"ops/evidence/capabilities.json"; destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(record,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(record))

if __name__=="__main__": main()
