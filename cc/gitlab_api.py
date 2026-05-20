import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional


def parse_closing_issue_ids(description: str) -> list[int]:
    """从 MR 描述里解析 Closes #xxx 的 Issue ID 列表"""
    if not description:
        return []
    return [int(m) for m in re.findall(r"[Cc]loses\s+#(\d+)", description)]

from .config import Config


class GitLabError(Exception):
    pass


class GitLabAPI:
    def __init__(self, cfg: Config):
        self.base = f"{cfg.gitlab_url}/api/v4"
        self.token = cfg.gitlab_token
        self.project_id = urllib.parse.quote(str(cfg.gitlab_project_id), safe="")

    def _request(
        self,
        method: str,
        path: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> Any:
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("PRIVATE-TOKEN", self.token)
        if body:
            req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            raise GitLabError(
                f"GitLab API 错误 [{method} {path}] HTTP {e.code}: {body_text}"
            ) from e
        except urllib.error.URLError as e:
            raise GitLabError(f"网络错误 [{method} {path}]: {e.reason}") from e

    def get_issue(self, issue_id: int) -> dict:
        return self._request("GET", f"/projects/{self.project_id}/issues/{issue_id}")

    def close_issue(self, issue_id: int) -> dict:
        return self._request(
            "PUT",
            f"/projects/{self.project_id}/issues/{issue_id}",
            data={"state_event": "close"},
        )

    def create_branch(self, branch_name: str, ref: str) -> dict:
        return self._request(
            "POST",
            f"/projects/{self.project_id}/repository/branches",
            data={"branch": branch_name, "ref": ref},
        )

    def get_branch(self, branch_name: str) -> Optional[dict]:
        try:
            return self._request(
                "GET",
                f"/projects/{self.project_id}/repository/branches/{urllib.parse.quote(branch_name, safe='')}",
            )
        except GitLabError:
            return None

    def get_user_by_username(self, username: str) -> Optional[dict]:
        users = self._request("GET", "/users", params={"username": username})
        return users[0] if users else None

    def get_user_by_email(self, email: str) -> Optional[dict]:
        try:
            users = self._request("GET", "/users", params={"search": email})
            for u in users:
                if u.get("email") == email or u.get("public_email") == email:
                    return u
            return users[0] if users else None
        except GitLabError:
            return None

    def create_mr(
        self,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        issue_id: Optional[int] = None,
        remove_source_branch: bool = True,
        assignee_id: Optional[int] = None,
        reviewer_ids: Optional[list[int]] = None,
    ) -> dict:
        payload: dict = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
            "remove_source_branch": remove_source_branch,
        }
        if assignee_id:
            payload["assignee_id"] = assignee_id
        if reviewer_ids:
            payload["reviewer_ids"] = reviewer_ids
        return self._request(
            "POST", f"/projects/{self.project_id}/merge_requests", data=payload
        )

    def get_open_mr_by_source_branch(self, source_branch: str) -> Optional[dict]:
        mrs = self._request(
            "GET",
            f"/projects/{self.project_id}/merge_requests",
            params={"state": "opened", "source_branch": source_branch},
        )
        return mrs[0] if mrs else None

    def get_mr(self, mr_iid: int) -> dict:
        return self._request(
            "GET", f"/projects/{self.project_id}/merge_requests/{mr_iid}"
        )

    def get_issue_comments(self, issue_id: int) -> list:
        notes = []
        page = 1
        while True:
            batch = self._request(
                "GET",
                f"/projects/{self.project_id}/issues/{issue_id}/notes",
                params={"per_page": 100, "page": page},
            )
            if not batch:
                break
            notes.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return notes

    def get_mr_comments(self, mr_iid: int) -> list:
        notes = []
        page = 1
        while True:
            batch = self._request(
                "GET",
                f"/projects/{self.project_id}/merge_requests/{mr_iid}/notes",
                params={"per_page": 100, "page": page},
            )
            if not batch:
                break
            notes.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return notes

    def get_mr_approvals(self, mr_iid: int) -> dict:
        return self._request(
            "GET",
            f"/projects/{self.project_id}/merge_requests/{mr_iid}/approvals",
        )

    def merge_mr(self, mr_iid: int) -> dict:
        return self._request(
            "PUT",
            f"/projects/{self.project_id}/merge_requests/{mr_iid}/merge",
            data={"should_remove_source_branch": True},
        )

    def get_merged_mrs(self, target_branch: str) -> list:
        """获取所有已合并到指定分支的 MR"""
        mrs: list = []
        page = 1
        while True:
            batch = self._request(
                "GET",
                f"/projects/{self.project_id}/merge_requests",
                params={"state": "merged", "target_branch": target_branch, "per_page": 100, "page": page},
            )
            if not batch:
                break
            mrs.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return mrs

    def get_project_commits(
        self, branch: str, since_ref: Optional[str] = None, per_page: int = 20
    ) -> list:
        params: dict = {"ref_name": branch, "per_page": per_page}
        return self._request(
            "GET",
            f"/projects/{self.project_id}/repository/commits",
            params=params,
        )

    def get_issues(
        self,
        created_after: Optional[str] = None,
        updated_after: Optional[str] = None,
        closed_after: Optional[str] = None,
        state: Optional[str] = None,
    ) -> list:
        """分页获取 Issues，支持时间和状态过滤。时间格式：ISO 8601。"""
        issues: list = []
        page = 1
        while True:
            params: dict = {"per_page": 100, "page": page}
            if created_after:
                params["created_after"] = created_after
            if updated_after:
                params["updated_after"] = updated_after
            if state:
                params["state"] = state
            batch = self._request(
                "GET",
                f"/projects/{self.project_id}/issues",
                params=params,
            )
            if not batch:
                break
            issues.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        if closed_after:
            # GitLab issues API 没有 closed_after 参数，在客户端过滤
            issues = [
                i for i in issues
                if not i.get("closed_at") or i["closed_at"] >= closed_after
            ]
        return issues

    def get_commits_since(self, since: str) -> list:
        """获取 since 时间后所有分支的 commits（带行数统计），去重。
        since 格式：ISO 8601，如 '2026-05-14T00:00:00Z'。
        """
        commits: list = []
        seen_shas: set = set()
        page = 1
        while True:
            batch = self._request(
                "GET",
                f"/projects/{self.project_id}/repository/commits",
                params={
                    "since": since,
                    "all": "true",
                    "with_stats": "true",
                    "per_page": 100,
                    "page": page,
                },
            )
            if not batch:
                break
            for c in batch:
                sha = c.get("id", "")
                if sha and sha not in seen_shas:
                    seen_shas.add(sha)
                    commits.append(c)
            if len(batch) < 100:
                break
            page += 1
        return commits

    def get_commit_diff(self, sha: str) -> list[dict]:
        """返回 commit 每个文件的 {path, additions, deletions}，用于过滤生成文件后重新计算行数。"""
        try:
            diffs = self._request(
                "GET",
                f"/projects/{self.project_id}/repository/commits/{sha}/diff",
                params={"per_page": 200},
            )
            result = []
            for f in (diffs or []):
                path = f.get("new_path") or f.get("old_path") or ""
                diff_text = f.get("diff") or ""
                lines = diff_text.splitlines()
                additions = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
                deletions = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))
                result.append({"path": path, "additions": additions, "deletions": deletions})
            return result
        except GitLabError:
            return []
