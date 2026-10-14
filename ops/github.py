"""Bounded fixed GitHub API calls; no issue/comment/body is executed."""
import base64
import json
import subprocess
from urllib.parse import quote
from .contracts import REPOSITORY, Stop, sha, safe_path

class GitHub:
    def api(self, path):
        # Read retries are safe. Mutation retries are deliberately not automatic.
        for attempt in range(2):
            try:
                done = subprocess.run(["gh", "api", f"repos/{REPOSITORY}/{path}"], capture_output=True,
                                      text=True, encoding="utf-8", timeout=45, check=True)
                return json.loads(done.stdout)
            except (subprocess.SubprocessError, ValueError, OSError):
                if attempt: raise Stop("GitHub read unavailable; cached evidence retained") from None
    def ref(self, branch): return sha(self.api("git/ref/heads/" + quote(branch, safe="/"))["object"]["sha"])
    def text(self, path, commit):
        safe_path(path); sha(commit)
        data = self.api(f"contents/{quote(path, safe='/')}?ref={commit}")
        if data.get("type") != "file" or data.get("size", 0) > 2_000_000: raise Stop("Expected bounded named report file")
        return base64.b64decode(data["content"], validate=False).decode("utf-8")
    def compare(self, before, after):
        data = self.api(f"compare/{sha(before)}...{sha(after)}")
        if data.get("status") not in {"ahead", "identical"} or len(data.get("files", [])) >= 300 or data.get("total_commits", 0) > 100:
            raise Stop("Commit order/compare limit requires manual review")
        paths = set()
        for item in data.get("files", []):
            paths.add(safe_path(item["filename"]))
            if "previous_filename" in item: paths.add(safe_path(item["previous_filename"]))
        return paths
    def pulls(self, branch):
        data = self.api("pulls?state=all&head=" + quote(REPOSITORY.split('/')[0] + ':' + branch, safe="") + "&per_page=100")
        if len(data) >= 100: raise Stop("PR history exceeds safe bound")
        # List responses omit merged/merged_by. Hydrate actual merges from the
        # single-PR endpoint rather than mistaking closed for merged or pending.
        return [self.pull(p["number"]) if p.get("merged_at") else dict(p,merged=False) for p in data]
    def pull(self, number):
        if type(number) is not int or number <= 0: raise Stop("Invalid PR number")
        return self.api(f"pulls/{number}")
    def issue(self, number):
        if type(number) is not int or number<=0: raise Stop("Invalid issue number")
        result=self.api(f"issues/{number}")
        if "pull_request" in result or result.get("number")!=number or result.get("state") not in {"open","closed"}:
            raise Stop("Unexpected issue evidence")
        return {"issue_state":result["state"],"issue_title":result["title"],
                "issue_url":f"https://github.com/{REPOSITORY}/issues/{number}"}
    def author(self, commit):
        item = self.api("commits/" + sha(commit))
        return (item.get("author") or {}).get("login")
