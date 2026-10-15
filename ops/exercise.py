"""Offline integration exercise: fake GitHub + fake agents, real durable journal."""
import tempfile
from .contracts import BASE, HTML, PROGRESS, marker, gate, Stop
from .coordinator import Coordinator, Journal, ownership

COUNTS={"passed":12,"failed":0,"skipped":2,"scope":"offline"}

def report(phase,subject,status,ready=False):
    return {"gate":"R04","phase":phase,"status":status,"subject_sha":subject,
            "implementation_ready":ready,"tests":dict(COUNTS) if phase!="design" else {"passed":0,"failed":0,"skipped":0,"scope":"not_run"}}

class FakeGitHub:
    def __init__(self):
        self.selected=gate("R04"); self.head="2"*40; self.prs=[]
        self.documents={(self.selected.review,self.head):marker(report("design","1"*40,"REVISE",True))}
        self.changes={("1"*40,"2"*40):{self.selected.review}}
    def ref(self,branch): return self.head
    def author(self,commit): return "unit-owner"
    def text(self,path,commit): return self.documents[path,commit]
    def compare(self,before,after):
        if (before,after) not in self.changes: raise Stop("Out-of-order fake commits")
        return self.changes[before,after]
    def pulls(self,branch): return self.prs
    def issue(self,number):
        return {"issue_state":"open","issue_title":"FAKE issue","issue_url":f"https://github.com/Vivek-k24/Stark_T2SQL/issues/{number}"}

class FakeAgents:
    def __init__(self,github,verdict="VERIFIED_APPROVE"):
        self.github=github; self.calls=[]; self.verdict=verdict
    def run(self,selected,phase,input_sha,allowed):
        self.calls.append(phase)
        output=("3" if phase=="implementation" else "4")*40
        path=selected.log if phase=="implementation" else selected.review
        status="IMPLEMENTATION_PUSHED" if phase=="implementation" else self.verdict
        self.github.documents[path,output]=marker(report(phase,input_sha,status))
        paths={path,"src/stark_t2sql/semantic/unit.py"} if phase=="implementation" else {path,HTML,PROGRESS}
        self.github.changes[input_sha,output]=paths
        self.github.head=output
        self.github.prs=[{"number":99,"base":{"ref":BASE},"head":{"ref":selected.branch,"sha":output},"state":"open","draft":True}]
        return output,dict(COUNTS)

def exercise():
    github=FakeGitHub(); agents=FakeAgents(github)
    with tempfile.TemporaryDirectory(prefix="stark-fake-exercise-") as directory, ownership(directory):
        journal=Journal(directory)
        try:
            coordinator=Coordinator(github,agents,journal,trusted_authors=["unit-owner"])
            allowed=["src/stark_t2sql/semantic/","Codex_R04_Work_Log.md"]
            first=coordinator.cycle("R04","2"*40,allowed)
            second=coordinator.cycle("R04","2"*40,allowed)
            assert first==second=="VERIFIED — AWAITING MERGE" and agents.calls==["implementation","verification"]
            return {"exercise":"FAKE AGENTS / FAKE GITHUB", "sequence":agents.calls,"repeat_dispatches":0,
                    "final_state":first,"next_gate":"NOT_STARTED","real_agent_sessions":0,"real_repository_modified":False}
        finally: journal.close()
