"""Canonical public evidence generated from pinned GitHub PR/report snapshots."""
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
from .contracts import BASE, HTML, PROGRESS, REPOSITORY, PREFIXES, Stop, gate, reports

BEGIN, END = "<!-- STARK_PROGRESS_BEGIN -->", "<!-- STARK_PROGRESS_END -->"
HISTORY = (("R01", 3, 12, "Codex_work_log.md", "Antigravity_Design_Review.md", (260,0,177)),
           ("R02", 4, 13, "Antigravity_R02_Design_Review.md", "Antigravity_R02_Design_Review.md", (326,0,178)),
           ("R03", 5, 14, "Antigravity_R03_Review.md", "Antigravity_R03_Review.md", (463,0,177)))

def build(github):
    milestones = []
    for name, issue, number, evidence_path, review_path, counts in HISTORY:
        pr = github.pull(number)
        if (not pr.get("merged") or pr["base"]["ref"] != BASE
                or pr["head"]["ref"] != f"codex/{name.lower()}-remediation"):
            raise Stop("Historical merge evidence differs from the approved baseline")
        commit = pr["merge_commit_sha"]
        text = github.text(evidence_path, commit)
        # Legacy records have no INT-01 markers. Bind their exact known count
        # statements to immutable fetched bytes rather than extrapolating counts.
        passed, failed, skipped = counts
        if name == "R01":
            found = re.search(r"\| Full Python suite \| \*\*260\*\* \| \*\*0\*\* \| \*\*0\*\* \| \*\*177\*\*", text)
        else:
            found = f"{passed} passed, {skipped} skipped" in text
        if not found: raise Stop("Legacy test-count evidence is not present at the actual merge SHA")
        review = github.text(review_path, commit)
        verdicts=re.findall(r"(?:VERDICT|Verdict):\s*(APPROVE|REVISE|BLOCKED)",review.replace("*",""))
        verified = name != "R01" and "Independent Implementation Verification" in review and bool(verdicts) and verdicts[-1]=="APPROVE"
        milestones.append({"gate":name,"issue":issue,"pr":number,"state":"MERGED",
            "merge_sha":commit,"merged_at":pr["merged_at"],"merged_by":pr["merged_by"]["login"],
            "review_verdict":"APPROVE" if verified else "FINAL REVIEW NOT VERSIONED; owner merged",
            "tests":{"passed":passed,"failed":failed,"skipped":skipped,"scope":"offline"},
            "evidence_url":f"https://github.com/{REPOSITORY}/blob/{commit}/{evidence_path}",
            "evidence_sha256":sha256(text.encode()).hexdigest(),
            "review_url":f"https://github.com/{REPOSITORY}/blob/{commit}/{review_path}",
            "live_postgresql":"UNVERIFIED"})
        milestones[-1].update(github.issue(issue))
    # Future gates are discovered from actual PRs plus validated named reports,
    # never from a design file's existence. No next gate is launched here.
    for name in PREFIXES:
        selected=gate(name)
        candidates=github.pulls(selected.branch)
        if not candidates: continue
        if len(candidates)!=1: raise Stop("Ambiguous future gate PR")
        pr=candidates[0]
        if pr["base"]["ref"]!=BASE or pr["head"]["ref"]!=selected.branch: raise Stop("Future gate PR base/head differs")
        head=pr["head"]["sha"]
        try: text=github.text(selected.review,head)
        except Stop: raise Stop("Named future review evidence is unavailable") from None
        record=reports(text,selected).get("verification")
        state="DRAFT — INDEPENDENT VERIFICATION PENDING"; verdict="PENDING"
        counts={"passed":0,"failed":0,"skipped":0,"scope":"not_run"}
        if record:
            counts=record["tests"]; verdict=record["status"]
            state={"VERIFIED_APPROVE":"VERIFIED — AWAITING MERGE","VERIFIED_REVISE":"REVISE","VERIFIED_BLOCKED":"BLOCKED"}[verdict]
        if pr.get("merged"): state="MERGED"
        elif pr["state"]=="closed": state="CLOSED — NOT MERGED"
        item={"gate":name,"issue":selected.issue,"pr":pr["number"],"state":state,"review_verdict":verdict,"tests":counts,
              "evidence_url":f"https://github.com/{REPOSITORY}/blob/{head}/{selected.review}",
              "evidence_sha256":sha256(text.encode()).hexdigest(),"live_postgresql":"UNVERIFIED"}
        item.update(github.issue(selected.issue))
        if pr.get("merged"): item.update(merge_sha=pr["merge_commit_sha"],merged_at=pr["merged_at"],merged_by=pr["merged_by"]["login"])
        milestones.append(item)
    interim={"gate":"INT-01","issue":15,"state":"IMPLEMENTATION — AWAITING INDEPENDENT VERIFICATION"}
    interim.update(github.issue(15))
    if hasattr(github,"pulls"):
        candidates=[p for p in github.pulls("codex/interim-orchestration-ui") if p["base"]["ref"]==BASE]
        if len(candidates)>1: raise Stop("Ambiguous interim PR")
        if candidates:
            p=candidates[0]
            interim.update(pr=p["number"],url=f"https://github.com/{REPOSITORY}/pull/{p['number']}",head_sha=p["head"]["sha"])
            # A design review alone never establishes implementation verification.
            interim["state"]="MERGED" if p.get("merged") else "DRAFT PR — AWAITING INDEPENDENT VERIFICATION"
            if p.get("merged"): interim["merge_sha"]=p["merge_commit_sha"]
            else:
                try:
                    record=reports(github.text("Antigravity_INT01_Review.md",p["head"]["sha"]),gate("INT01")).get("verification")
                    if record and record["status"]=="VERIFIED_APPROVE":
                        interim.update(state="VERIFIED — AWAITING MERGE",tests=record["tests"])
                except Stop: pass  # Missing/unusable verification is never approval.
    return {"schema_version":1,"frd":"1.8","repository":REPOSITORY,"base":BASE,
        "github_base_sha":github.ref(BASE),"milestones":milestones,
        "interim":interim,
        "automation":{"state":"BLOCKED","reason":"Opt-in task and real agent CLI/auth/sandbox smoke tests required"},
        "query_execution":{"state":"BLOCKED","reason":"Secured PostgreSQL/model/parser integration has not been executed"}}

def validate(data):
    if (type(data) is not dict or type(data.get("schema_version")) is not int or data.get("schema_version") != 1 or data.get("repository") != REPOSITORY
            or data.get("frd") != "1.8" or data.get("base") != BASE or not isinstance(data.get("milestones"), list)):
        raise Stop("Invalid public progress cache")
    if (not isinstance(data.get("interim"),dict) or type(data["interim"].get("state")) is not str
            or not isinstance(data.get("automation"),dict) or type(data["automation"].get("state")) is not str
            or type(data["automation"].get("reason")) is not str): raise Stop("Missing public status fields")
    for item in data["milestones"]:
        if not isinstance(item,dict) or type(item.get("state")) is not str or item.get("state") not in {"MERGED", "VERIFIED — AWAITING MERGE", "REVISE", "BLOCKED", "DRAFT — INDEPENDENT VERIFICATION PENDING", "CLOSED — NOT MERGED"}:
            raise Stop("Invalid milestone status")
        if not {"gate","issue","pr","review_verdict","tests","evidence_url"} <= item.keys(): raise Stop("Incomplete milestone evidence")
        t=item["tests"]
        if (not isinstance(t,dict) or set(t)!={"passed","failed","skipped","scope"}
                or any(type(t[k]) is not int or t[k]<0 for k in ("passed","failed","skipped"))
                or type(t["scope"]) is not str or t["scope"] not in {"offline","not_run"}): raise Stop("Invalid cached test evidence")
        if not str(item.get("evidence_url", "")).startswith(f"https://github.com/{REPOSITORY}/blob/"):
            raise Stop("Evidence links must remain in the public project repository")
        if item["state"] == "MERGED":
            from .contracts import sha
            sha(item.get("merge_sha"))
    return data

def load(root): return validate(json.loads((Path(root) / PROGRESS).read_text(encoding="utf-8")))

def html_block(data):
    validate(data)
    rows = []
    for item in data["milestones"]:
        t = item["tests"]
        rows.append('<tr>' + ''.join(f'<td style="padding:10px">{escape(str(value))}</td>' for value in
            (item["gate"],item["state"],f'PR #{item["pr"]}',item.get("merge_sha", "not merged"),
             item["review_verdict"],f'{t["passed"]} passed / {t["skipped"]} skipped ({t["scope"]})')) +
            f'<td><a href="{escape(item["evidence_url"], quote=True)}" target="_blank" rel="noopener noreferrer">Evidence</a></td></tr>')
    return BEGIN + '\n<div class="card" id="githubProgressEvidence" style="padding:20px;overflow:auto">' + \
        '<h3>GitHub-backed Architecture &amp; Progress · FRD 1.8</h3><p>Cached public evidence. Merged remediation gates do not establish every epic exit or live SQL acceptance.</p>' + \
        '<table><thead><tr><th>Gate</th><th>Status</th><th>PR</th><th>Actual merge commit</th><th>Review</th><th>Offline tests</th><th>Source</th></tr></thead><tbody>' + ''.join(rows) + \
        '</tbody></table><p>INT-01: ' + escape(data["interim"]["state"]) + '</p><p>Agent automation: ' + escape(data["automation"]["state"]) + \
        '. Live PostgreSQL / SQLCoder queries: BLOCKED. Playground examples remain SIMULATED.</p></div>\n' + END

def write(root, data):
    root = Path(root); validate(data)
    target = root / HTML
    text = target.read_text(encoding="utf-8")
    text=text.replace("FRD 1.7","FRD 1.8")
    text=text.replace('<div><strong>0</strong><span>Backend milestones verified</span></div>',
                      '<div><strong id="verifiedGateCount">0</strong><span>Remediation gates merged (offline evidence)</span></div>')
    merged=sum(item["state"]=="MERGED" for item in data["milestones"])
    text=re.sub(r'(<strong id="verifiedGateCount">)\d+(</strong>)',lambda m:m[1]+str(merged)+m[2],text)
    text=text.replace("All statuses are static representations of the current known state. E0 prototype is under review; E1–E8 have no verified implementation evidence; E9 is conditional and E10 is an approved future extension outside the MVP. Updating the tracker in later iterations requires actual implementation and test evidence.",
        "Versioned GitHub remediation evidence is shown above. Epic/story/task labels describe the inherited roadmap and do not claim full epic acceptance. Live PostgreSQL/model integration remains unverified; examples remain SIMULATED. E9 is conditional and E10 is deferred.")
    text=text.replace("The HTML prototype is under expanded UI review. No E1+ implementation evidence is available.",
        "The prototype is a simulated UI. Versioned remediation evidence is shown above; full epic acceptance remains separate.")
    block = html_block(data)
    if BEGIN in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1: raise Stop("Ambiguous HTML evidence region")
        text = text[:text.index(BEGIN)] + block + text[text.index(END)+len(END):]
    else:
        anchor = '<section class="page" id="page-architecture" aria-label="Architecture and progress">'
        if text.count(anchor) != 1: raise Stop("Expected original E0 Architecture pane")
        text = text.replace(anchor, anchor + '\n' + block, 1)
    (root / PROGRESS).parent.mkdir(parents=True, exist_ok=True)
    (root / PROGRESS).write_bytes((json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode())
    target.write_bytes(text.encode())

def apply_merge(data, pr, verdict):
    """Only an owner-authorized actual merge changes VERIFIED to MERGED."""
    if not pr.get("merged") or pr["base"]["ref"] != BASE or verdict != "VERIFIED_APPROVE":
        raise Stop("Not an independently approved actual integration merge")
    from .contracts import sha
    sha(pr.get("merge_commit_sha"))
    matches = [i for i in data["milestones"] if i["pr"] == pr["number"]]
    if len(matches) != 1: raise Stop("Merge does not identify exactly one recorded milestone")
    item = matches[0]
    expected_branch=f'codex/{item["gate"].lower()}-remediation'
    if pr["head"]["ref"]!=expected_branch: raise Stop("Merge head does not match recorded gate")
    item.update(state="MERGED", merge_sha=pr["merge_commit_sha"], merged_at=pr["merged_at"], merged_by=pr["merged_by"]["login"])
    return data
