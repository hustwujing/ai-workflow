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
请勿编辑上方内容，仅在评论区回复验收口令：
通过：product:pass
驳回：product:reject 具体问题

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


def check_product_pass(comments: list[dict], mr_description: str = "") -> bool:
    _PASS_RE = re.compile(r"product:pass", re.IGNORECASE)
    desc = mr_description.strip()
    # Only a product:pass AFTER the most recent push counts; earlier ones are stale.
    last_push = get_last_push_time(comments)
    for note in comments:
        if note.get("system"):
            continue
        body: str = note.get("body", "")
        if desc and body.strip() == desc:
            continue
        if _PASS_RE.search(body):
            created_at = note.get("created_at", "")
            if last_push is None or (created_at and created_at > last_push):
                return True
    return False


def check_dev_approved(approvals: dict) -> bool:
    approved_by = approvals.get("approved_by", [])
    return len(approved_by) > 0


def has_stale_product_pass(comments: list[dict], mr_description: str = "") -> bool:
    """Returns True if there IS a product:pass comment but it predates the last push."""
    _PASS_RE = re.compile(r"product:pass", re.IGNORECASE)
    desc = mr_description.strip()
    last_push = get_last_push_time(comments)
    if last_push is None:
        return False
    for note in comments:
        if note.get("system"):
            continue
        body: str = note.get("body", "")
        if desc and body.strip() == desc:
            continue
        if _PASS_RE.search(body):
            created_at = note.get("created_at", "")
            if created_at and created_at <= last_push:
                return True
    return False


def get_last_product_pass_time(comments: list[dict], mr_description: str = "") -> Optional[str]:
    _PASS_RE = re.compile(r"product:pass", re.IGNORECASE)
    desc = mr_description.strip()
    last_time: Optional[str] = None
    for note in comments:
        if note.get("system"):
            continue
        body: str = note.get("body", "")
        if desc and body.strip() == desc:
            continue
        if _PASS_RE.search(body):
            t = note.get("created_at")
            if t and (last_time is None or t > last_time):
                last_time = t
    return last_time


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
