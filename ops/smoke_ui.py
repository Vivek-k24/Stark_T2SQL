"""Opt-in actual browser smoke, loopback-only; stops its own server afterward."""
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.request import ProxyHandler, build_opener
from .serve import command

def main():
    from playwright.sync_api import sync_playwright
    root=Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0)); port=sock.getsockname()[1]
    env=dict(os.environ); env.pop("STARK_ENABLE_CONNECTED_UI",None)
    env["PYTHONPATH"]=str(root/"src")+os.pathsep+str(root)
    server=subprocess.Popen(command(root,port),cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    try:
        opener=build_opener(ProxyHandler({})); url=f"http://127.0.0.1:{port}"
        for _ in range(60):
            if server.poll() is not None: raise RuntimeError("Local UI exited before health check")
            try:
                with opener.open(url+"/_stcore/health",timeout=1) as response:
                    if response.read()==b"ok": break
            except OSError: time.sleep(.25)
        else: raise RuntimeError("Local UI health endpoint unavailable")
        output=root/"ops/evidence"; output.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel="msedge",headless=True)
            page=browser.new_page(viewport={"width":1440,"height":1100})
            page.goto(url)
            page.get_by_text("Local health & status",exact=True).wait_for(timeout=30000)
            page.get_by_text("Architecture & Progress:",exact=False).first.wait_for()
            page.screenshot(path=str(output/"ui-health.png"))
            page.get_by_test_id("stSidebar").get_by_text("Architecture",exact=True).click()
            page.get_by_text("GitHub-backed remediation progress",exact=True).wait_for()
            page.get_by_text("R03 · MERGED · PR #14",exact=True).wait_for()
            page.screenshot(path=str(output/"ui-architecture.png"))
            page.get_by_test_id("stSidebar").get_by_text("Progress",exact=True).click()
            page.get_by_text("Implementation progress explorer",exact=True).wait_for()
            page.screenshot(path=str(output/"ui-progress.png"))
            browser.close()
        result={"health_endpoint":"PASSED","browser":"Microsoft Edge headless",
                "browser_views":["Health & Status","Architecture","Progress"],"bind":"127.0.0.1",
                "connected_sql":"NOT_EXECUTED","agent_sessions":0,"server_after_smoke":"STOPPED"}
        (output/"ui-smoke.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(result))
    finally:
        server.terminate()
        try: server.wait(timeout=10)
        except subprocess.TimeoutExpired: server.kill(); server.wait(timeout=10)

if __name__=="__main__": main()
