import argparse
import sys
from datetime import date
from typing import Optional

from .branch import (
    BranchError,
    checkout_and_pull_main,
    create_local_branch,
    get_branch_type,
    get_commits_behind,
    get_current_branch,
    get_issue_id_from_branch,
    get_recent_commits,
    is_in_rebase,
    make_branch_name,
    push_current_branch,
)
from .config import load_config
from .gitlab_api import GitLabAPI, GitLabError, parse_closing_issue_ids
from .mr import (
    build_mr_description,
    check_dev_approved,
    check_issue_verdict,
    get_approved_count,
    get_last_approval_time,
    get_last_push_time,
    get_mr_target_branch,
)
from .validator import get_missing_sections, detect_issue_type
from .daily_report import cmd_daily_report
from .wechat import (
    notify_feature_start,
    notify_hotfix_start,
    notify_issue_invalid,
    notify_mr_created,
    notify_mr_merged,
    notify_mr_updated,
    notify_release,
    notify_release_blocked,
    notify_release_merged,
    notify_sync_pre,
)


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------


def _friendly_issue_error(e: "GitLabError", issue_id: int) -> str:
    msg = str(e)
    if "HTTP 404" in msg:
        return f"Issue #{issue_id} 不存在或无权访问，请确认 Issue ID 正确，并检查账号是否有该项目权限。"
    if "HTTP 401" in msg or "HTTP 403" in msg:
        return "GitLab Token 无效或权限不足，请检查 .env 中的 GITLAB_PRIVATE_TOKEN 是否正确。"
    return str(e)


def cmd_feature_start(args: argparse.Namespace) -> None:
    cfg = load_config()
    api = GitLabAPI(cfg)

    issue_id = int(args.issue_id)
    print(f"[gitlab] 获取 Issue #{issue_id}...")
    try:
        issue = api.get_issue(issue_id)
    except GitLabError as e:
        print(f"[错误] {_friendly_issue_error(e, issue_id)}", file=sys.stderr)
        sys.exit(1)

    title: str = issue.get("title", "")
    body: str = issue.get("description", "") or ""

    issue_type = detect_issue_type(body)
    if issue_type == "bug":
        print("[错误] 该 Issue 为 Bug 类型，请使用 ccg gitlab hotfix start 创建热修分支", file=sys.stderr)
        sys.exit(1)
    if issue_type is None:
        print("[错误] 无法识别 Issue 类型，请确认 description 是否使用了标准模板（需求/优化/Bug）", file=sys.stderr)
        sys.exit(1)

    missing = get_missing_sections(body, issue_type)
    if not (issue.get("assignees") or issue.get("assignee")):
        missing.append("负责人（指派研发）")
    if missing:
        print(f"[错误] Issue格式不合规，缺少：{', '.join(missing)}", file=sys.stderr)
        author = issue.get("author", {})
        author_username: str = author.get("username", "")
        author_name: str = author.get("name", "") or author_username
        issue_link = f"{cfg.gitlab_url.rstrip('/')}/{cfg.gitlab_project_id}/-/issues/{issue_id}"
        notify_issue_invalid(
            cfg.wechat_webhook_url,
            issue_id=issue_id,
            issue_title=title,
            issue_link=issue_link,
            author=author_name,
            developer=cfg.gitlab_username,
            missing_sections=missing,
            at_userids=cfg.resolve_wechat_ids([author_username]),
            issue_type=issue_type,
        )
        sys.exit(1)

    clean_title = title.replace("【需求】", "").replace("【优化】", "").strip()
    branch_name = make_branch_name("feature", issue_id, clean_title)
    base_branch = args.base or cfg.branch_main

    try:
        checkout_and_pull_main(base_branch)
        create_local_branch(branch_name)
    except BranchError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n[成功] 已创建功能分支：{branch_name}（基于 {base_branch}）")

    author = issue.get("author", {})
    author_username: str = author.get("username", "")
    author_name: str = author.get("name", "") or author_username
    at_userids = cfg.resolve_wechat_ids([author_username, cfg.gitlab_username])
    for u in [author_username, cfg.gitlab_username]:
        if u and not cfg.resolve_wechat_id(u):
            print(f"[提示] {u} 未配置手机号映射（WECHAT_USER_{u}），企微无法 @ 到该用户")
    notify_feature_start(
        cfg.wechat_webhook_url,
        issue_id=issue_id,
        issue_title=title,
        branch_name=branch_name,
        base_branch=base_branch,
        gitlab_url=cfg.gitlab_url,
        project_id=cfg.gitlab_project_id,
        developer=cfg.gitlab_username,
        author=author_name,
        at_userids=at_userids,
        issue_type=issue_type,
    )


def cmd_hotfix_start(args: argparse.Namespace) -> None:
    cfg = load_config()
    api = GitLabAPI(cfg)

    issue_id = int(args.issue_id)
    print(f"[gitlab] 获取 Issue #{issue_id}...")
    try:
        issue = api.get_issue(issue_id)
    except GitLabError as e:
        print(f"[错误] {_friendly_issue_error(e, issue_id)}", file=sys.stderr)
        sys.exit(1)

    title: str = issue.get("title", "")
    body: str = issue.get("description", "") or ""

    missing = get_missing_sections(body, "bug")
    if not (issue.get("assignees") or issue.get("assignee")):
        missing.append("负责人（指派研发）")
    if missing:
        print(f"[错误] Issue格式不合规，缺少：{', '.join(missing)}", file=sys.stderr)
        author = issue.get("author", {})
        author_username: str = author.get("username", "")
        author_name: str = author.get("name", "") or author_username
        issue_link = f"{cfg.gitlab_url.rstrip('/')}/{cfg.gitlab_project_id}/-/issues/{issue_id}"
        notify_issue_invalid(
            cfg.wechat_webhook_url,
            issue_id=issue_id,
            issue_title=title,
            issue_link=issue_link,
            author=author_name,
            developer=cfg.gitlab_username,
            missing_sections=missing,
            at_userids=cfg.resolve_wechat_ids([author_username]),
            issue_type="bug",
        )
        sys.exit(1)

    branch_name = make_branch_name("bug", issue_id, title.replace("【Bug】", "").replace("【bug】", "").strip())
    base_branch = args.base or cfg.branch_main

    try:
        checkout_and_pull_main(base_branch)
        create_local_branch(branch_name)
    except BranchError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n[成功] 已创建热修分支：{branch_name}（基于 {base_branch}）")

    author = issue.get("author", {})
    author_username: str = author.get("username", "")
    author_name: str = author.get("name", "") or author_username
    at_userids = cfg.resolve_wechat_ids([author_username, cfg.gitlab_username]) + cfg.at_tl_list
    notify_hotfix_start(
        cfg.wechat_webhook_url,
        issue_id=issue_id,
        issue_title=title,
        branch_name=branch_name,
        base_branch=base_branch,
        gitlab_url=cfg.gitlab_url,
        project_id=cfg.gitlab_project_id,
        developer=cfg.gitlab_username,
        author=author_name,
        at_userids=at_userids,
    )


def cmd_commit(args: argparse.Namespace) -> None:
    try:
        branch = get_current_branch()
    except BranchError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    if branch == "HEAD" and is_in_rebase():
        print(
            "[错误] 当前处于 rebase 冲突状态，无法直接提交。\n"
            "\n"
            "  请按以下步骤处理冲突后继续：\n"
            "  1. 查看冲突文件：       git status\n"
            "  2. 手动解决所有冲突\n"
            "  3. 标记冲突已解决：     git add <冲突文件>\n"
            "  4. 继续 rebase：        git rebase --continue\n"
            "  5. 如需放弃 rebase：    git rebase --abort",
            file=sys.stderr,
        )
        sys.exit(1)

    issue_id = get_issue_id_from_branch(branch)
    message = args.message
    if issue_id:
        message = f"[#{issue_id}] {message}"

    import subprocess
    result = subprocess.run(["git", "commit", "-m", message])
    sys.exit(result.returncode)


def _get_reviewer_names(cfg, api) -> list[str]:
    names = []
    for username in cfg.gitlab_reviewer_usernames:
        info = api.get_user_by_username(username)
        if info:
            names.append(info.get("name") or username)
        else:
            print(f"[提示] reviewer '{username}' 在 GitLab 中找不到，企微通知将不显示该用户名")
    return names


def cmd_mr_create(args: argparse.Namespace) -> None:
    cfg = load_config()
    api = GitLabAPI(cfg)

    try:
        branch = get_current_branch()
    except BranchError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    branch_type = get_branch_type(branch)
    if not branch_type:
        if branch == "HEAD" and is_in_rebase():
            print(
                "[错误] 当前处于 rebase 冲突状态，请先解决冲突后再创建 MR。\n"
                "\n"
                "  1. 查看冲突文件：\n"
                "       git status\n"
                "  2. 手动编辑冲突文件，解决所有冲突\n"
                "  3. 标记冲突已解决并继续 rebase：\n"
                "       git add <冲突文件>\n"
                "       git rebase --continue\n"
                "  4. 如需放弃 rebase 回到操作前状态：\n"
                "       git rebase --abort\n"
                "  5. rebase 完成后重新执行：\n"
                "       ccg gitlab mr create",
                file=sys.stderr,
            )
        else:
            print(
                f"[错误] 当前分支 '{branch}' 不符合 issue_xxx 或 hotfix_xxx 命名规范，无法创建 MR。",
                file=sys.stderr,
            )
        sys.exit(1)

    issue_id = get_issue_id_from_branch(branch)
    if not issue_id:
        print("[错误] 无法从分支名解析 Issue ID。", file=sys.stderr)
        sys.exit(1)

    target_branch = args.target or get_mr_target_branch(branch, cfg.branch_main, cfg.branch_pre)

    print(f"[gitlab] 获取 Issue #{issue_id}...")
    try:
        issue = api.get_issue(issue_id)
    except GitLabError as e:
        print(f"[错误] {_friendly_issue_error(e, issue_id)}", file=sys.stderr)
        sys.exit(1)

    issue_title: str = issue.get("title", f"Issue #{issue_id}")
    commits = get_recent_commits(10)
    description = build_mr_description(
        issue_id=issue_id,
        branch_type=branch_type,
        target_branch=target_branch,
        commits=commits,
    )

    mr_title = f"[{'需求' if branch_type == 'feature' else 'Bug热修'}] #{issue_id} {issue_title}"

    assignee_id: Optional[int] = None
    user_info = api.get_user_by_username(cfg.gitlab_username)
    if user_info:
        assignee_id = user_info.get("id")

    reviewer_ids: list[int] = []
    reviewer_names: list[str] = []
    for username in cfg.gitlab_reviewer_usernames:
        info = api.get_user_by_username(username)
        if info:
            reviewer_ids.append(info["id"])
            reviewer_names.append(info.get("name") or username)
        else:
            print(f"[提示] reviewer '{username}' 在 GitLab 中找不到，已跳过")

    print(f"[gitlab] 推送分支并创建 MR → {target_branch}...")
    try:
        had_new_commits = push_current_branch()
        mr = api.create_mr(
            source_branch=branch,
            target_branch=target_branch,
            title=mr_title,
            description=description,
            issue_id=issue_id,
            assignee_id=assignee_id,
            reviewer_ids=reviewer_ids or None,
        )
    except GitLabError as e:
        if "HTTP 409" in str(e):
            existing_mr = api.get_open_mr_by_source_branch(branch)
            if existing_mr:
                ex_mr_iid: int = existing_mr.get("iid", 0)
                ex_mr_url: str = existing_mr.get("web_url", "")
                ex_mr_title: str = existing_mr.get("title", f"MR !{ex_mr_iid}")
                if had_new_commits:
                    print(
                        f"[提示] 分支已有 MR !{ex_mr_iid}，本次推送已更新其代码，无需重新创建。\n"
                        f"  MR 页面：{ex_mr_url}",
                    )
                else:
                    print(
                        f"[提示] 分支已有 MR !{ex_mr_iid}，且代码无变更，无需重新创建。\n"
                        f"  MR 页面：{ex_mr_url}",
                    )
                if had_new_commits:
                    dev_was_approved = False
                    try:
                        ex_approvals = api.get_mr_approvals(ex_mr_iid)
                        dev_was_approved = check_dev_approved(ex_approvals)
                    except GitLabError:
                        pass
                    issue_author = issue.get("author", {})
                    issue_author_username: str = issue_author.get("username", "")
                    issue_author_name: str = issue_author.get("name", "") or issue_author_username
                    at_userids = cfg.resolve_wechat_ids([issue_author_username]) + cfg.at_tl_list
                    notify_mr_updated(
                        cfg.wechat_webhook_url,
                        mr_iid=ex_mr_iid,
                        mr_title=ex_mr_title,
                        mr_url=ex_mr_url,
                        target_branch=target_branch,
                        author_name=issue_author_name,
                        operator=cfg.gitlab_username,
                        reviewer_names=reviewer_names,
                        dev_was_approved=dev_was_approved,
                        required_approvals=cfg.hotfix_required_approvals if (branch_type == "bug" and target_branch == cfg.branch_main) else 1,
                        at_userids=at_userids,
                    )
                sys.exit(0)
            else:
                print("[错误] 该分支已存在未合并的 MR，请勿重复创建。", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"[错误] {e}", file=sys.stderr)
            sys.exit(1)
    except BranchError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    mr_iid: int = mr.get("iid", 0)
    mr_url: str = mr.get("web_url", "")
    print(f"\n[成功] MR !{mr_iid} 已创建：{mr_url}")

    issue_author = issue.get("author", {})
    issue_author_username: str = issue_author.get("username", "")
    issue_author_name: str = issue_author.get("name", "") or issue_author_username
    at_userids = cfg.resolve_wechat_ids([issue_author_username]) + cfg.at_tl_list
    notify_mr_created(
        cfg.wechat_webhook_url,
        issue_id=issue_id,
        mr_iid=mr_iid,
        mr_title=mr_title,
        mr_url=mr_url,
        target_branch=target_branch,
        author_name=issue_author_name,
        operator=cfg.gitlab_username,
        reviewer_names=reviewer_names,
        required_approvals=cfg.hotfix_required_approvals if (branch_type == "bug" and target_branch == cfg.branch_main) else 1,
        at_userids=at_userids,
    )


def _do_mr_check(cfg, api, mr_iid: int) -> tuple[int, dict, list]:
    """Returns (approved_count, mr_info, comments)"""
    try:
        mr = api.get_mr(mr_iid)
    except GitLabError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    mr_state = mr.get("state", "")
    if mr_state == "merged":
        print(f"[提示] MR !{mr_iid} 已合并。")
        sys.exit(0)
    if mr_state == "closed":
        print(f"[错误] MR !{mr_iid} 已关闭，无法合并。", file=sys.stderr)
        sys.exit(1)

    try:
        comments = api.get_mr_comments(mr_iid)
        approvals = api.get_mr_approvals(mr_iid)
    except GitLabError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    approved_count = get_approved_count(approvals)
    return approved_count, mr, comments


def cmd_mr_check(args: argparse.Namespace) -> None:
    cfg = load_config()
    api = GitLabAPI(cfg)
    mr_iid = int(args.mr_iid)

    approved_count, mr, comments = _do_mr_check(cfg, api, mr_iid)

    source_branch: str = mr.get("source_branch", "")
    mr_target: str = mr.get("target_branch", "")
    is_hotfix = source_branch.startswith("hotfix_")
    required = cfg.hotfix_required_approvals if (is_hotfix and mr_target == cfg.branch_main) else 1
    dev_ok = approved_count >= required

    last_push_time = get_last_push_time(comments)
    stale_dev = False
    if dev_ok and last_push_time:
        last_approval_time = get_last_approval_time(comments)
        if last_approval_time and last_push_time > last_approval_time:
            stale_dev = True

    dev_label = f"✓ 通过（{approved_count}/{required}）" if dev_ok else f"✗ 未通过（{approved_count}/{required}）"
    if stale_dev:
        dev_label += "  ⚠ 审批后有新提交，建议 Reviewer 重新审阅"

    print(f"\n=== MR !{mr_iid} 门禁状态 ===")
    print(f"  研发 Approval 审批：{dev_label}")

    if dev_ok and not stale_dev:
        print("\n[结论] 满足合并条件，可执行 ccg gitlab mr merge。")
    elif dev_ok and stale_dev:
        print("\n[结论] 门禁已通过，但审批后有新提交，建议 Reviewer 确认后再执行合并。")
    else:
        print("\n[结论] 尚不满足合并条件，请等待研发 Approve 审批。")


def _check_pre_acceptance(cfg, api) -> tuple[bool, list[dict]]:
    """Step 9: check all issues linked to merged pre MRs have product:pass and developer:pass in issue comments."""
    print(f"[gitlab] 查询 {cfg.branch_pre} 上已合并的 MR 及关联 Issue...")
    pre_mrs = api.get_merged_mrs(cfg.branch_pre)

    issue_merged_at: dict[int, str] = {}
    for mr in pre_mrs:
        merged_at: str = mr.get("merged_at", "") or ""
        for issue_id in parse_closing_issue_ids(mr.get("description", "") or ""):
            if issue_id not in issue_merged_at or merged_at > issue_merged_at[issue_id]:
                issue_merged_at[issue_id] = merged_at

    if not issue_merged_at:
        return True, []

    issue_results: list[dict] = []
    all_passed = True

    for issue_id, merged_at in issue_merged_at.items():
        try:
            issue = api.get_issue(issue_id)
        except GitLabError as e:
            print(f"[警告] 获取 Issue #{issue_id} 失败：{e}", file=sys.stderr)
            continue

        if issue.get("state") != "opened":
            continue

        reporter = issue.get("author", {})
        reporter_username: str = reporter.get("username", "")
        reporter_name: str = reporter.get("name", "") or reporter_username

        assignee = issue.get("assignee", {}) or {}
        assignee_username: str = assignee.get("username", "")
        assignee_name: str = assignee.get("name", "") or assignee_username

        issue_url = f"{cfg.gitlab_url.rstrip('/')}/{cfg.gitlab_project_id}/-/issues/{issue_id}"

        try:
            comments = api.get_issue_comments(issue_id)
        except GitLabError as e:
            print(f"[警告] 获取 Issue #{issue_id} 评论失败：{e}", file=sys.stderr)
            comments = []

        product_verdict, product_proxy, product_proxy_user, product_note = check_issue_verdict(
            comments, "product:pass", merged_at, reporter_username
        )
        developer_verdict, developer_proxy, developer_proxy_user, developer_note = check_issue_verdict(
            comments, "developer:pass", merged_at, assignee_username
        )

        product_passed = product_verdict == "passed"
        developer_passed = developer_verdict == "passed"

        if not product_passed or not developer_passed:
            all_passed = False

        issue_results.append({
            "issue_id": issue_id,
            "issue_title": issue.get("title", f"Issue #{issue_id}"),
            "reporter_username": reporter_username,
            "reporter_name": reporter_name,
            "assignee_username": assignee_username,
            "assignee_name": assignee_name,
            "issue_url": issue_url,
            "product_passed": product_passed,
            "product_verdict": product_verdict,
            "product_proxy": product_proxy,
            "product_proxy_user": product_proxy_user,
            "product_note": product_note,
            "developer_passed": developer_passed,
            "developer_verdict": developer_verdict,
            "developer_proxy": developer_proxy,
            "developer_proxy_user": developer_proxy_user,
            "developer_note": developer_note,
        })

    return all_passed, issue_results


def cmd_mr_merge(args: argparse.Namespace) -> None:
    cfg = load_config()
    api = GitLabAPI(cfg)
    mr_iid = int(args.mr_iid)

    approved_count, mr, _comments = _do_mr_check(cfg, api, mr_iid)

    mr_url: str = mr.get("web_url", "")
    source_branch: str = mr.get("source_branch", "")
    target_branch: str = mr.get("target_branch", "")
    tl_names = _get_reviewer_names(cfg, api)

    is_hotfix = source_branch.startswith("hotfix_")
    is_release = (source_branch == cfg.branch_pre and target_branch == cfg.branch_main)
    required_approvals = cfg.hotfix_required_approvals if (is_hotfix and target_branch == cfg.branch_main) else 1
    dev_ok = approved_count >= required_approvals

    if not dev_ok:
        reviewer_label = "、".join(tl_names) if tl_names else "Reviewer"
        if is_hotfix:
            print(
                f"[错误] 热修 MR 需要至少 {required_approvals} 名 Reviewer Approve，"
                f"当前 {approved_count}/{required_approvals}。\n"
                f"  请 {reviewer_label} 在 GitLab 完成审批后再合并。\n"
                f"  MR 页面：{mr_url}",
                file=sys.stderr,
            )
        else:
            print(
                f"[错误] 研发 Approval 审批未通过，请 {reviewer_label} 在 GitLab 完成审批后再合并。\n"
                f"  MR 页面：{mr_url}",
                file=sys.stderr,
            )
        sys.exit(1)

    # Step 9: pre→main 合并前检查所有 issue 的验收状态
    if is_release:
        all_passed, issue_results = _check_pre_acceptance(cfg, api)
        if not all_passed:
            failed_at_userids: list[str] = []
            for r in issue_results:
                if not r["product_passed"]:
                    uid = cfg.resolve_wechat_id(r["reporter_username"])
                    if uid:
                        failed_at_userids.append(uid)
                if not r["developer_passed"]:
                    uid = cfg.resolve_wechat_id(r["assignee_username"])
                    if uid:
                        failed_at_userids.append(uid)
            seen_fail: set[str] = set()
            failed_at_userids = [u for u in failed_at_userids if u and not (u in seen_fail or seen_fail.add(u))]  # type: ignore[func-returns-value]
            notify_release_blocked(
                cfg.wechat_webhook_url,
                mr_iid=mr_iid,
                mr_url=mr_url,
                main_branch=cfg.branch_main,
                operator=cfg.gitlab_username,
                issue_results=issue_results,
                at_userids=failed_at_userids,
            )
            print("[错误] pre 环境验收未完成，以下 Issue 缺少验收记录，已通知相关人员：", file=sys.stderr)
            for r in issue_results:
                if not r["product_passed"] or not r["developer_passed"]:
                    pp = "✓" if r["product_passed"] else "✗"
                    dp = "✓" if r["developer_passed"] else "✗"
                    print(f"  Issue #{r['issue_id']} 产品:{pp} 研发:{dp}", file=sys.stderr)
            sys.exit(1)

        proxy_warnings = [r for r in issue_results if r["product_proxy"] or r["developer_proxy"]]
        for r in proxy_warnings:
            if r["product_proxy"]:
                note_str = f"  备注：{r['product_note']}" if r.get("product_note") else ""
                print(f"[警示] Issue #{r['issue_id']} product:pass 由 {r['product_proxy_user']} 代发（负责人：{r['reporter_name']}）{note_str}")
            if r["developer_proxy"]:
                note_str = f"  备注：{r['developer_note']}" if r.get("developer_note") else ""
                print(f"[警示] Issue #{r['issue_id']} developer:pass 由 {r['developer_proxy_user']} 代发（负责人：{r['assignee_name']}）{note_str}")

    print(f"[gitlab] 合并 MR !{mr_iid}...")
    try:
        api.merge_mr(mr_iid)
    except GitLabError as e:
        if "HTTP 406" in str(e):
            tl_label = "、".join(tl_names) if tl_names else "TL"
            behind = get_commits_behind(target_branch)
            if behind:
                behind_preview = "\n".join(f"    {c}" for c in behind[:5])
                more = f"\n    ...（共 {len(behind)} 个）" if len(behind) > 5 else ""
                print(
                    f"[错误] 分支落后 {target_branch}，需先同步再合并。\n\n"
                    f"  {target_branch} 上有以下提交你的分支尚未包含：\n"
                    f"{behind_preview}{more}\n\n"
                    f"  执行以下命令同步后重试（rebase 后会自动 force push）：\n"
                    f"    git rebase origin/{target_branch}\n"
                    f"    ccg gitlab mr create   # 会自动 force push，推送成功后直接执行下一步\n"
                    f"    ccg gitlab mr merge {mr_iid}\n\n"
                    f"  如 rebase 遇到冲突：\n"
                    f"    git status               # 查看冲突文件\n"
                    f"    git add <冲突文件>        # 解决后标记\n"
                    f"    git rebase --continue\n\n"
                    f"  ⚠ 注意：rebase 后请勿执行 git pull，否则会拉回旧提交造成死循环\n\n"
                    f"  如有疑问请联系 {tl_label}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[错误] 分支无法合并，请打开 MR 页面确认阻塞原因：\n"
                    f"  MR 页面：{mr_url}\n\n"
                    f"  常见原因：\n"
                    f"  1. 存在合并冲突 — 在本地解决冲突后重新推送\n"
                    f"  2. CI 流水线未通过 — 等待或修复后重试\n\n"
                    f"  如有疑问请联系 {tl_label}",
                    file=sys.stderr,
                )
        else:
            print(f"[错误] 合并失败：{e}", file=sys.stderr)
        sys.exit(1)

    print(f"[成功] MR !{mr_iid} 已合并到 {target_branch}。")

    if is_hotfix and target_branch == cfg.branch_main:
        # 热修：关闭单个 Issue
        issue_id = get_issue_id_from_branch(source_branch)
        if issue_id:
            try:
                api.close_issue(issue_id)
                print(f"[gitlab] Issue #{issue_id} 已自动关闭。")
            except GitLabError as e:
                print(f"[警告] 关闭 Issue 失败：{e}", file=sys.stderr)
        at_userids = cfg.resolve_wechat_ids([cfg.gitlab_username]) + cfg.at_tl_list
        notify_mr_merged(
            cfg.wechat_webhook_url,
            issue_id=issue_id or 0,
            mr_iid=mr_iid,
            target_branch=target_branch,
            mr_url=mr_url,
            operator=cfg.gitlab_username,
            pre_branch=cfg.branch_pre,
            main_branch=cfg.branch_main,
            tl_names=tl_names,
            at_userids=at_userids,
        )

    elif is_release:
        # Release：关闭所有关联 Issue
        issue_ids = [r["issue_id"] for r in issue_results]

        closed_issues: list[dict] = []
        author_usernames: list[str] = []
        for iid in issue_ids:
            try:
                issue = api.get_issue(iid)
                if issue.get("state") == "opened":
                    api.close_issue(iid)
                    print(f"[gitlab] Issue #{iid} 已关闭。")
                author = issue.get("author", {})
                closed_issues.append({
                    "id": iid,
                    "title": issue.get("title", ""),
                    "author": author.get("name", "") or author.get("username", ""),
                })
                author_usernames.append(author.get("username", ""))
            except GitLabError as e:
                print(f"[警告] 处理 Issue #{iid} 失败：{e}", file=sys.stderr)

        at_userids_release = (
            cfg.resolve_wechat_ids(list(dict.fromkeys(author_usernames)))
            + cfg.resolve_wechat_ids([cfg.gitlab_username])
            + cfg.at_tl_list
        )
        seen_rel: set[str] = set()
        at_userids_release = [u for u in at_userids_release if u and not (u in seen_rel or seen_rel.add(u))]  # type: ignore[func-returns-value]

        notify_release_merged(
            cfg.wechat_webhook_url,
            mr_iid=mr_iid,
            mr_url=mr_url,
            main_branch=cfg.branch_main,
            closed_issues=closed_issues,
            operator=cfg.gitlab_username,
            at_userids=at_userids_release,
        )

    else:
        # feature → pre：通知产品和研发前往 pre 验收
        issue_id = get_issue_id_from_branch(source_branch) or 0
        issue_reporter_name = ""
        issue_link = ""
        reporter_wechat_ids: list[str] = []
        if issue_id:
            try:
                issue = api.get_issue(issue_id)
                reporter = issue.get("author", {})
                reporter_username: str = reporter.get("username", "")
                issue_reporter_name = reporter.get("name", "") or reporter_username
                issue_link = f"{cfg.gitlab_url.rstrip('/')}/{cfg.gitlab_project_id}/-/issues/{issue_id}"
                reporter_wechat_ids = cfg.resolve_wechat_ids([reporter_username])
            except GitLabError:
                pass

        seen_pre: set[str] = set()
        at_userids_pre = [
            u for u in cfg.resolve_wechat_ids([cfg.gitlab_username]) + reporter_wechat_ids + cfg.at_tl_list
            if u and not (u in seen_pre or seen_pre.add(u))  # type: ignore[func-returns-value]
        ]
        notify_mr_merged(
            cfg.wechat_webhook_url,
            issue_id=issue_id,
            mr_iid=mr_iid,
            target_branch=target_branch,
            mr_url=mr_url,
            operator=cfg.gitlab_username,
            pre_branch=cfg.branch_pre,
            main_branch=cfg.branch_main,
            tl_names=tl_names,
            at_userids=at_userids_pre,
            issue_reporter_name=issue_reporter_name,
            issue_link=issue_link,
        )


def cmd_mr_release(args: argparse.Namespace) -> None:
    cfg = load_config()
    api = GitLabAPI(cfg)

    today = date.today().strftime("%Y-%m-%d")
    title = f"[Release] {today} pre → {cfg.branch_main}"
    description = (
        f"## pre 上线\n\n"
        f"将 `{cfg.branch_pre}` 测试通过的代码合并到 `{cfg.branch_main}` 上线。\n\n"
        f"日期：{today}"
    )

    print(f"[gitlab] 创建 pre → {cfg.branch_main} MR...")
    try:
        mr = api.create_mr(
            source_branch=cfg.branch_pre,
            target_branch=cfg.branch_main,
            title=title,
            description=description,
            remove_source_branch=False,
        )
    except GitLabError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    mr_iid: int = mr.get("iid", 0)
    mr_url: str = mr.get("web_url", "")
    print(f"\n[成功] Release MR !{mr_iid} 已创建：{mr_url}")

    notify_release(
        cfg.wechat_webhook_url,
        mr_iid=mr_iid,
        mr_url=mr_url,
        main_branch=cfg.branch_main,
        operator=cfg.gitlab_username,
        tl_names=_get_reviewer_names(cfg, api),
        at_userids=cfg.resolve_wechat_ids([cfg.gitlab_username]) + cfg.at_tl_list,
    )


def cmd_mr_sync_pre(args: argparse.Namespace) -> None:
    cfg = load_config()
    api = GitLabAPI(cfg)

    today = date.today().strftime("%Y-%m-%d")
    title = f"[SyncPre] {today} {cfg.branch_main} → {cfg.branch_pre}"
    description = (
        f"## 热修同步\n\n"
        f"将 `{cfg.branch_main}` 热修代码同步到 `{cfg.branch_pre}` 保持对齐。\n\n"
        f"日期：{today}"
    )

    print(f"[gitlab] 创建 {cfg.branch_main} → {cfg.branch_pre} MR...")
    try:
        mr = api.create_mr(
            source_branch=cfg.branch_main,
            target_branch=cfg.branch_pre,
            title=title,
            description=description,
            remove_source_branch=False,
        )
    except GitLabError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    mr_iid: int = mr.get("iid", 0)
    mr_url: str = mr.get("web_url", "")
    print(f"\n[成功] SyncPre MR !{mr_iid} 已创建：{mr_url}")

    notify_sync_pre(
        cfg.wechat_webhook_url,
        mr_iid=mr_iid,
        mr_url=mr_url,
        pre_branch=cfg.branch_pre,
        operator=cfg.gitlab_username,
        tl_names=_get_reviewer_names(cfg, api),
        at_userids=cfg.resolve_wechat_ids([cfg.gitlab_username]) + cfg.at_tl_list,
    )


# ---------------------------------------------------------------------------
# argparse 路由
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ccg",
        description="GitLab 标准化协作 CLI",
    )
    sub = parser.add_subparsers(dest="platform")

    # ccg gitlab ...
    gitlab_parser = sub.add_parser("gitlab", help="GitLab 相关命令")
    gitlab_sub = gitlab_parser.add_subparsers(dest="resource")

    # ccg gitlab feature ...
    feature_parser = gitlab_sub.add_parser("feature", help="功能需求分支管理")
    feature_sub = feature_parser.add_subparsers(dest="action")
    feature_start = feature_sub.add_parser("start", help="拉取功能分支（自动校验需求 Issue）")
    feature_start.add_argument("issue_id", help="GitLab Issue ID")
    feature_start.add_argument("--base", default=None, metavar="BRANCH", help="基准分支，默认为 main")
    feature_start.set_defaults(func=cmd_feature_start)

    # ccg gitlab hotfix ...
    hotfix_parser = gitlab_sub.add_parser("hotfix", help="Bug 热修分支管理")
    hotfix_sub = hotfix_parser.add_subparsers(dest="action")
    hotfix_start = hotfix_sub.add_parser("start", help="拉取热修分支（自动校验 Bug Issue）")
    hotfix_start.add_argument("issue_id", help="GitLab Issue ID")
    hotfix_start.add_argument("--base", default=None, metavar="BRANCH", help="基准分支，默认为 main")
    hotfix_start.set_defaults(func=cmd_hotfix_start)

    # ccg gitlab commit ...
    commit_parser = gitlab_sub.add_parser("commit", help="规范提交代码")
    commit_parser.add_argument("message", help="提交说明")
    commit_parser.set_defaults(func=cmd_commit)

    # ccg gitlab mr ...
    mr_parser = gitlab_sub.add_parser("mr", help="MR 管理")
    mr_sub = mr_parser.add_subparsers(dest="action")

    mr_create = mr_sub.add_parser("create", help="一键创建 MR")
    mr_create.add_argument(
        "--target",
        metavar="BRANCH",
        default=None,
        help="指定 MR 目标分支（默认：hotfix→main，其他→pre）",
    )
    mr_create.set_defaults(func=cmd_mr_create)

    mr_check = mr_sub.add_parser("check", help="检查 MR 双审核状态")
    mr_check.add_argument("mr_iid", help="MR IID")
    mr_check.set_defaults(func=cmd_mr_check)

    mr_merge = mr_sub.add_parser("merge", help="带门禁合并 MR")
    mr_merge.add_argument("mr_iid", help="MR IID")
    mr_merge.set_defaults(func=cmd_mr_merge)

    mr_release = mr_sub.add_parser("release", help="pre 上线合入 main")
    mr_release.set_defaults(func=cmd_mr_release)

    mr_sync_pre = mr_sub.add_parser("sync-pre", help="热修同步 main 到 pre")
    mr_sync_pre.set_defaults(func=cmd_mr_sync_pre)

    # ccg gitlab daily-report
    daily_report_parser = gitlab_sub.add_parser("daily-report", help="生成并发送每日工作日报")
    daily_report_parser.add_argument(
        "--hours", type=int, default=24, metavar="N", help="统计过去 N 小时，默认 24"
    )
    daily_report_parser.add_argument(
        "--no-llm", action="store_true", help="跳过 LLM 总结，使用内置格式化"
    )
    daily_report_parser.add_argument(
        "--dry-run", action="store_true", help="只打印报告，不发送企微通知"
    )
    daily_report_parser.set_defaults(func=cmd_daily_report)

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)

    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n[中断]", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
