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


def get_approved_count(approvals: dict) -> int:
    return len(approvals.get("approved_by", []))


def check_dev_approved(approvals: dict, required: int = 1) -> bool:
    return get_approved_count(approvals) >= required


def _normalize_colon(text: str) -> str:
    """Normalize fullwidth colon ：(U+FF1A) to ASCII colon for matching."""
    return text.replace("：", ":")


def check_issue_verdict(
    comments: list[dict],
    pass_keyword: str,
    since_time: Optional[str],
    expected_username: str,
) -> tuple[str, bool, str, str]:
    """Find the most recent pass or reject verdict in issue comments after since_time.

    Returns (verdict, is_proxy, proxy_username, extra_text).
    verdict: 'passed' | 'rejected' | 'pending'
    extra_text is the comment body with the matched keyword stripped, trimmed.

    Matching is case-insensitive and tolerates fullwidth colons (：vs :).
    The most recent qualifying comment wins; reject after pass → rejected, pass after reject → passed.
    """
    reject_keyword = pass_keyword.replace(":pass", ":reject")
    # \b 确保口令不藏在其他单词里（如 myproduct:pass 不应命中）
    # (?:ed)? 兼容 passed / rejected 过去时变体
    pass_pattern = re.compile(
        r"\b" + re.escape(pass_keyword) + r"(?:ed)?\b", re.IGNORECASE
    )
    reject_pattern = re.compile(
        r"\b" + re.escape(reject_keyword) + r"(?:ed)?\b", re.IGNORECASE
    )

    for note in sorted(comments, key=lambda n: n.get("created_at", ""), reverse=True):
        if note.get("system"):
            continue
        raw_body: str = note.get("body", "")
        body = _normalize_colon(raw_body)
        created_at = note.get("created_at", "")
        if since_time and created_at <= since_time:
            continue
        # reject is more conservative: if present in the same comment, treat as reject
        if reject_pattern.search(body):
            author_username = note.get("author", {}).get("username", "")
            is_proxy = bool(expected_username) and author_username != expected_username
            extra_text = reject_pattern.sub("", body).strip()
            return "rejected", is_proxy, (author_username if is_proxy else ""), extra_text
        if pass_pattern.search(body):
            author_username = note.get("author", {}).get("username", "")
            is_proxy = bool(expected_username) and author_username != expected_username
            extra_text = pass_pattern.sub("", body).strip()
            return "passed", is_proxy, (author_username if is_proxy else ""), extra_text
    return "pending", False, "", ""


def check_issue_pass(
    comments: list[dict],
    keyword: str,
    since_time: Optional[str],
    expected_username: str,
) -> tuple[bool, bool, str, str]:
    """Thin wrapper around check_issue_verdict for callers that only need pass/fail."""
    verdict, is_proxy, proxy_user, extra_text = check_issue_verdict(
        comments, keyword, since_time, expected_username
    )
    return verdict == "passed", is_proxy, proxy_user, extra_text


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
    if branch_name.startswith(("hotfix/", "hotfix_", "quickfix/")):
        return main_branch
    return pre_branch
