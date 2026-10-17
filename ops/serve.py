"""Foreground local STARK app: database metadata and inference are independent."""
from pathlib import Path
import os
import subprocess
import sys
import signal


def run_foreground(args, *, cwd, env, shell=False):
    """Own and reap the foreground child; normal Ctrl+C has no traceback."""
    process = None
    try:
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        process = subprocess.Popen(args, cwd=cwd, env=env, shell=False, **options)
        # Windows' unbounded WaitForSingleObject can defer Python's pending
        # KeyboardInterrupt until the child exits. Poll the *owned* child so
        # Ctrl+C reaches cleanup even though its new process group is isolated.
        while True:
            try:
                return process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                continue
    except KeyboardInterrupt:
        if process is not None and process.poll() is None:
            try:
                if os.name == "nt": process.send_signal(signal.CTRL_BREAK_EVENT)
                else: os.killpg(process.pid, signal.SIGINT)
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
                process.terminate()
                try: process.wait(timeout=5)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    process.kill()
                    process.wait(timeout=5)
        print("Local UI stopped.", flush=True)
        return 130
    except OSError:
        print("Local UI could not start. Check the existing Python environment and selected local port.", file=sys.stderr)
        return 2

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
    print(f"Local UI: http://127.0.0.1:{args.port} — database and SQLCoder readiness are checked independently in the app",flush=True)
    return run_foreground(command(root,args.port),cwd=root,env=env)

if __name__=="__main__": raise SystemExit(main())
