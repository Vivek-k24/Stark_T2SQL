"""Render manually maintained, public milestone evidence into the offline HTML UI.

No background polling, agent dispatch, GitHub API calls, credentials or commits.
After each human-approved merge, Antigravity verifies and edits ops/progress.json,
runs `python -m ops.progress`, and includes the updated HTML in its next
manually initiated review PR. All example SQL results remain SIMULATED.
"""
from html import escape
import json
from pathlib import Path

BEGIN = "<!-- STARK_PROGRESS_BEGIN -->"
END = "<!-- STARK_PROGRESS_END -->"
ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Vivek-k24/Stark_T2SQL"


def load(root=ROOT):
    data = json.loads((Path(root) / "ops/progress.json").read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or data.get("repository") != REPOSITORY or data.get("frd") != "1.8"
            or not isinstance(data.get("milestones"), list)
            or not isinstance(data.get("interim"), dict)
            or not isinstance(data.get("query_execution"), dict)):
        raise ValueError("Invalid human-maintained progress record")
    for entry in data["milestones"]:
        if not isinstance(entry, dict) or not all(
                field in entry for field in ("gate", "state", "pr", "review_verdict", "tests", "evidence_url")):
            raise ValueError("Incomplete manually reviewed milestone")
        if not str(entry["evidence_url"]).startswith(f"https://github.com/{REPOSITORY}/blob/"):
            raise ValueError("Evidence must point to versioned STARK repository content")
        counts = entry["tests"]
        if (not isinstance(counts, dict)
                or any(type(counts.get(k)) is not int or counts[k] < 0
                       for k in ("passed", "failed", "skipped"))):
            raise ValueError("Invalid test counts")
    return data


def html_block(data):
    rows = []
    for entry in data["milestones"]:
        t = entry["tests"]
        cells = (
            entry["gate"], entry["state"], f'PR #{entry["pr"]}',
            entry.get("merge_sha", "not merged"), entry["review_verdict"],
            f'{t["passed"]} passed / {t["skipped"]} skipped ({t.get("scope", "offline")})',
        )
        row = "<tr>" + "".join(f'<td style="padding:10px">{escape(str(v))}</td>' for v in cells)
        row += (f'<td><a href="{escape(entry["evidence_url"], quote=True)}"'
                ' target="_blank" rel="noopener noreferrer">Evidence</a></td></tr>')
        rows.append(row)
    interim = data["interim"]
    return (
        BEGIN + '\n<div class="card" id="githubProgressEvidence" style="padding:20px;overflow:auto">'
        '<h3>Verified remediation progress · FRD 1.8</h3>'
        '<p>Manually updated from reviewed GitHub merges and agent reports. '
        'No automatic agent execution or synchronization.</p>'
        '<table><thead><tr><th>Gate</th><th>Status</th><th>PR</th><th>Actual merge commit</th>'
        '<th>Review</th><th>Offline tests</th><th>Source</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table>'
        '<p>INT-01: ' + escape(str(interim["state"])) + '.</p>'
        '<p>Antigravity and Codex are coordinated manually by the owner. '
        'Live PostgreSQL / SQLCoder integration remains unverified. '
        'Playground examples remain SIMULATED.</p></div>\n' + END
    )


def write(root=ROOT):
    root = Path(root)
    data = load(root)
    target = root / "STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html"
    html = target.read_text(encoding="utf-8")
    if html.count(BEGIN) != 1 or html.count(END) != 1:
        raise ValueError("HTML progress block missing or ambiguous")
    start = html.index(BEGIN)
    end = html.index(END) + len(END)
    if start >= end:
        raise ValueError("Invalid HTML progress block order")
    target.write_text(html[:start] + html_block(data) + html[end:], encoding="utf-8")


if __name__ == "__main__":
    write()
    print("Updated local HTML from human-reviewed ops/progress.json; nothing pushed or polled.")
