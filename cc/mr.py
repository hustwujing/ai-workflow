import re
from typing import Optional


MR_TEMPLATE = """\
## 关联Issue
Closes #{issue_id}

## 改动说明
{commit_desc}

## 开发自测
- [x] 本地自测通过
- [x] 无阻断性Bug

## 分支信息
分支类型：{branch_type_label}
合并目标分支：{target_branch}

---
### 产品经理
请勿编辑上方内容，请在评论区回复「已知悉本次变更」表示已了解本次改动。

### 研发
请在GitLab原生页面完成【Approval审批】，勿修改MR文本"""


def build_mr_description(
    issue_id: int,
    branch_type: str,
    target_branch: str,
    commits: list[str],
) -> str:
    branch_type_label = "需求" if branch_type == "feature" else "Bug热修"
    commit_desc = "\n".join(f"- {c}" for c in commits) if commits else "（无提交信息）"
    return MR_TEMPLATE.format(
        issue_id=issue_id,
        commit_desc=commit_desc,
        branch_type_label=branch_type_label,
        target_branch=target_branch,
    )


def check_dev_approved(approvals: dict) -> bool:
    approved_by = approvals.get("approved_by", [])
    return len(approved_by) > 0


def check_issue_pass(
    comments: list[dict],
    keyword: str,
    since_time: Optional[str],
    expected_username: str,
) -> tuple[bool, bool, str]:
    """Check if keyword appears in issue comments after since_time.

    Returns (passed, is_proxy, proxy_username).
    is_proxy=True means someone other than expected_username posted the pass.
    """
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    for note in sorted(comments, key=lambda n: n.get("created_at", ""), reverse=True):
        if note.get("system"):
            continue
        body: str = note.get("body", "")
        if not pattern.search(body):
            continue
        created_at = note.get("created_at", "")
        if since_time and created_at <= since_time:
            continue
        author_username = note.get("author", {}).get("username", "")
        is_proxy = bool(expected_username) and author_username != expected_username
        return True, is_proxy, (author_username if is_proxy else "")
    return False, False, ""


def get_last_push_time(comments: list[dict]) -> Optional[str]:
    last_time: Optional[str] = None
    for note in comments:
        if not note.get("system"):
            continue
        body = note.get("body", "").lower()
        if "commit" in body or "pushed" in body or "added" in body:
            t = note.get("created_at")
            if t and (last_time is None or t > last_time):
                last_time = t
    return last_time


def get_last_approval_time(comments: list[dict]) -> Optional[str]:
    last_time: Optional[str] = None
    for note in comments:
        if not note.get("system"):
            continue
        body = note.get("body", "").lower()
        if "approved" in body:
            t = note.get("created_at")
            if t and (last_time is None or t > last_time):
                last_time = t
    return last_time


def get_mr_target_branch(branch_name: str, main_branch: str, pre_branch: str) -> str:
    if branch_name.startswith("hotfix_"):
        return main_branch
    return pre_branch
