"""Foreground loopback Streamlit launcher. Does not activate connected SQL."""
from pathlib import Path
import os
import subprocess
import sys

def command(root, port=8501):
    if type(port) is not int or not 1024 <= port <= 65535: raise ValueError("Use an unprivileged local port")
    return [sys.executable,"-m","streamlit","run",str(Path(root)/"app.py"),"--server.address=127.0.0.1",
            f"--server.port={port}","--server.headless=true","--browser.gatherUsageStats=false"]

def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--port",type=int,default=8501)
    args=parser.parse_args(); root=Path(__file__).resolve().parents[1]
    env=dict(os.environ); env.pop("STARK_ENABLE_CONNECTED_UI",None)
    env["PYTHONPATH"]=str(root/"src")+os.pathsep+str(root)
    print(f"Local UI: http://127.0.0.1:{args.port} — connected SQL remains BLOCKED",flush=True)
    return subprocess.call(command(root,args.port),cwd=root,env=env)

if __name__=="__main__": raise SystemExit(main())
