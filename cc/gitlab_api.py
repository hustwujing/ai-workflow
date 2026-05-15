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
