import re
import subprocess
import sys
from typing import Optional


class BranchError(Exception):
    pass


def _run(cmd: list[str], capture: bool = True) -> str:
    result = subprocess.run(
        cmd, capture_output=capture, text=True
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        raise BranchError(f"命令失败: {' '.join(cmd)}\n{stderr}")
    return result.stdout.strip() if result.stdout else ""


def get_current_branch() -> str:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])


def is_in_rebase() -> bool:
    try:
        git_dir = _run(["git", "rev-parse", "--git-dir"])
        import os
        return (
            os.path.isdir(os.path.join(git_dir, "rebase-merge"))
            or os.path.isdir(os.path.join(git_dir, "rebase-apply"))
        )
    except BranchError:
        return False


def get_issue_id_from_branch(branch: Optional[str] = None) -> Optional[int]:
    b = branch or get_current_branch()
    m = re.match(r"^(?:issue|hotfix)_(\d+)", b)
    if m:
        return int(m.group(1))
    return None


def get_branch_type(branch: Optional[str] = None) -> Optional[str]:
    b = branch or get_current_branch()
    if b.startswith("issue_"):
        return "feature"
    if b.startswith("hotfix_"):
        return "bug"
    return None


def _slugify(text: str, max_len: int = 30) -> str:
    text = re.sub(r"[【】\[\]()（）\s]+", "_", text)
    text = re.sub(r"[^\w\-]", "", text)
    text = text.strip("_")
    return text[:max_len]


def make_branch_name(issue_type: str, issue_id: int, title: str) -> str:
    slug = _slugify(title)
    if issue_type == "feature":
        return f"issue_{issue_id}_{slug}"
    return f"hotfix_{issue_id}_{slug}"


def checkout_and_pull_main(main_branch: str) -> None:
    if is_in_rebase():
        raise BranchError(
            "当前处于 rebase 冲突状态，无法切换分支。\n"
            "请先处理冲突后再执行本命令：\n"
            "  1. 查看冲突文件：       git status\n"
            "  2. 手动解决所有冲突\n"
            "  3. 标记冲突已解决：     git add <冲突文件>\n"
            "  4. 继续 rebase：        git rebase --continue\n"
            "  5. 如需放弃 rebase：    git rebase --abort"
        )
    print(f"[git] 切换到 {main_branch} 并拉取最新代码...")
    _run(["git", "fetch", "origin"])
    try:
        _run(["git", "checkout", main_branch])
    except BranchError as e:
        msg = str(e)
        if "local changes" in msg or "overwritten by checkout" in msg:
            raise BranchError(
                f"切换到 {main_branch} 失败：存在未提交的本地改动。\n"
                f"请先暂存或提交改动后重试：\n"
                f"  git stash        # 暂存改动\n"
                f"  git stash pop    # 完成后恢复"
            ) from e
        raise
    _run(["git", "pull", "origin", main_branch])


def create_local_branch(branch_name: str) -> None:
    print(f"[git] 创建并切换到分支 {branch_name}...")
    try:
        _run(["git", "checkout", "-b", branch_name])
    except BranchError as e:
        if "already exists" in str(e):
            raise BranchError(
                f"本地分支 {branch_name} 已存在。\n"
                f"  切换到该分支继续开发：git checkout {branch_name}\n"
                f"  或删除后重新创建：  git branch -D {branch_name}"
            ) from e
        raise


def push_current_branch() -> bool:
    """推送当前分支到远端。返回 True 表示有新提交被推送，False 表示无变化。"""
    branch = get_current_branch()
    is_feature_branch = bool(re.match(r"^(issue|hotfix)_", branch))
    print(f"[git] 推送分支 {branch} 到远端...")
    result = subprocess.run(
        ["git", "push", "-u", "origin", branch],
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        stderr = result.stderr or ""
        if "non-fast-forward" in stderr or "rejected" in stderr:
            if is_feature_branch:
                # rebase 后本地历史被重写，需要 force push；用 --force-with-lease 保证安全
                print(f"[git] 检测到 rebase 后历史分叉，对功能分支执行 force push...")
                force_result = subprocess.run(
                    ["git", "push", "--force-with-lease", "-u", "origin", branch],
                    capture_output=True,
                    text=True,
                )
                if force_result.stdout:
                    print(force_result.stdout, end="")
                if force_result.stderr:
                    print(force_result.stderr, end="", file=sys.stderr)
                if force_result.returncode != 0:
                    raise BranchError(
                        f"force push 失败：{force_result.stderr.strip()}\n"
                        f"可能是远端分支在你 fetch 后又有新提交，请重新执行：\n"
                        f"  git fetch origin\n"
                        f"  git rebase origin/<目标分支>\n"
                        f"  ccg gitlab mr create"
                    )
                return True
            else:
                raise BranchError(
                    f"推送被拒绝：远端分支 {branch} 有本地不存在的提交。\n"
                    f"请先同步远端变更后重试：\n"
                    f"  git pull --rebase origin {branch}\n"
                    f"  ccg gitlab mr create"
                )
        else:
            raise BranchError(f"命令失败: git push -u origin {branch}\n{stderr}")
    # "Everything up-to-date" 时 returncode=0 且 stderr 含该字样
    everything_up_to_date = "Everything up-to-date" in (result.stderr or "") + (result.stdout or "")
    return not everything_up_to_date


def get_commits_behind(target_remote_branch: str) -> list[str]:
    """Returns commits in origin/<target> that are not in HEAD."""
    try:
        _run(["git", "fetch", "origin"])
        out = _run(["git", "log", f"HEAD..origin/{target_remote_branch}", "--oneline"])
        return [line for line in out.splitlines() if line]
    except BranchError:
        return []


def get_recent_commits(n: int = 10) -> list[str]:
    try:
        out = _run(["git", "log", f"-{n}", "--oneline"])
        return [line for line in out.splitlines() if line]
    except BranchError:
        return []
