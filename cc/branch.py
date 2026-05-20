import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
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
    # 支持新格式：feature/123-desc, hotfix/456-desc
    # 兼容旧格式：issue_123, hotfix_456
    m = re.match(r"^(?:feature|hotfix)/(\d+)", b)
    if m:
        return int(m.group(1))
    m = re.match(r"^(?:issue|hotfix)_(\d+)", b)
    if m:
        return int(m.group(1))
    return None


def get_branch_type(branch: Optional[str] = None) -> Optional[str]:
    b = branch or get_current_branch()
    # 支持新格式：feature/, hotfix/
    if b.startswith("feature/"):
        return "feature"
    if b.startswith("hotfix/"):
        return "bug"
    # 兼容旧格式：issue_, hotfix_
    if b.startswith("issue_"):
        return "feature"
    if b.startswith("hotfix_"):
        return "bug"
    return None


def _slugify(text: str, max_len: int = 30) -> str:
    """将标题转换为英文 slug，只保留 ASCII 字母、数字、-"""
    # 移除特殊符号，替换为 -
    text = re.sub(r"[【】\[\]()（）\s]+", "-", text)
    # 只保留 ASCII 字母、数字和 -
    text = re.sub(r"[^a-zA-Z0-9\-]", "", text)
    # 移除首尾的 -
    text = text.strip("-")
    # 转小写
    text = text.lower()
    # 合并连续的 -
    text = re.sub(r"-+", "-", text)
    return text[:max_len]


def _generate_slug_with_llm(title: str, llm_base_url: str, llm_api_key: str, llm_model: str, max_len: int = 30) -> Optional[str]:
    """使用 LLM 将中文标题转换为英文 slug"""
    if not llm_api_key:
        return None

    prompt = f"""将以下 Issue 标题转换为简短的英文 slug，用于 Git 分支命名。

要求：
1. 只输出 slug 本身，不要任何解释或其他内容
2. 使用小写字母、数字和连字符（-）
3. 多个单词用连字符连接（kebab-case）
4. 最多 {max_len} 个字符
5. 简洁明了，能体现核心功能

Issue 标题：{title}

输出示例：
- "用户登录优化" → user-login-optimization
- "修复支付页面崩溃" → fix-payment-crash
- "添加商品搜索功能" → add-product-search"""

    payload = {
        "model": llm_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 50,
        "temperature": 0.3,
    }
    body = json.dumps(payload).encode("utf-8")
    url = llm_base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {llm_api_key}")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            slug = result["choices"][0]["message"]["content"].strip()
            # 清理 LLM 输出，确保符合规范
            slug = slug.lower()
            slug = re.sub(r"[^a-z0-9\-]", "", slug)
            slug = slug.strip("-")
            slug = re.sub(r"-+", "-", slug)
            return slug[:max_len] if slug else None
    except Exception as e:
        print(f"[branch] LLM 生成 slug 失败: {e}", file=sys.stderr)
        return None


def make_branch_name(issue_type: str, issue_id: int, title: str, llm_base_url: str = "", llm_api_key: str = "", llm_model: str = "gpt-4o-mini") -> str:
    """生成分支名：feature/<id>-<slug> 或 hotfix/<id>-<slug>

    优先使用 LLM 生成英文 slug（如果配置了 API key），失败则回退到基于规则的提取。
    """
    slug = ""

    # 1. 尝试使用 LLM 生成（如果配置了）
    if llm_api_key:
        slug = _generate_slug_with_llm(title, llm_base_url, llm_api_key, llm_model) or ""

    # 2. LLM 失败或未配置，回退到规则提取
    if not slug:
        slug = _slugify(title)

    if issue_type == "feature":
        prefix = "feature"
    else:
        prefix = "hotfix"

    if slug:
        return f"{prefix}/{issue_id}-{slug}"
    else:
        # 如果标题无法生成有效 slug，只用 ID
        return f"{prefix}/{issue_id}"


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
    # 支持新格式 feature/, hotfix/ 和旧格式 issue_, hotfix_
    is_feature_branch = bool(re.match(r"^(feature|hotfix)/", branch)) or bool(re.match(r"^(issue|hotfix)_", branch))
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
