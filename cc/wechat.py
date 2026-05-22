import json
import sys
import urllib.error
import urllib.request
from typing import Optional


def _post(webhook_url: str, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(webhook_url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("errcode") != 0:
                print(f"[企微] Webhook 返回错误: {result.get('errmsg')}", file=sys.stderr)
    except (urllib.error.URLError, OSError) as e:
        print(f"[企微] Webhook 发送失败: {e}", file=sys.stderr)


def send_webhook(
    webhook_url: str,
    content: str,
    at_userids: Optional[list[str]] = None,
) -> None:
    if not webhook_url:
        print("[企微] Webhook URL 未配置，跳过通知。", file=sys.stderr)
        return

    seen: set[str] = set()
    mentioned = [uid for uid in (at_userids or []) if uid and not (uid in seen or seen.add(uid))]  # type: ignore[func-returns-value]

    if mentioned:
        _post(webhook_url, {
            "msgtype": "text",
            "text": {
                "content": "请关注以下通知：",
                "mentioned_mobile_list": mentioned,
            },
        })

    _post(webhook_url, {
        "msgtype": "markdown",
        "markdown": {"content": content},
    })


def notify_feature_start(
    webhook_url: str,
    issue_id: int,
    issue_title: str,
    branch_name: str,
    base_branch: str,
    gitlab_url: str,
    project_id: str,
    developer: str,
    author: str,
    at_userids: list[str],
    issue_type: str = "feature",
) -> None:
    issue_link = f"{gitlab_url.rstrip('/')}/{project_id}/-/issues/{issue_id}"
    if issue_type == "improve":
        title_label = "优化开发开始"
        author_label = "优化提出人"
    else:
        title_label = "需求开发开始"
        author_label = "需求提出人"
    content = (
        f"### {title_label}\n"
        f"> **Issue #{issue_id}**：{issue_title}\n"
        f"> **{author_label}**：{author}\n"
        f"> **开发者**：{developer}\n"
        f"> **分支**：`{branch_name}`（基于 `{base_branch}`）\n"
        f"> [查看 Issue]({issue_link})\n\n"
        f"**下一步 · {developer}**\n"
        f"> 1. 当前已切换到分支 `{branch_name}`，直接开始开发\n"
        f"> 2. 每次提交代码执行（自动追加 Issue 编号）：\n"
        f">    `ccg gitlab commit \"具体改动说明\"`\n"
        f"> 3. 开发完成后推送分支并创建 MR：\n"
        f">    `ccg gitlab mr create`\n"
    )
    send_webhook(webhook_url, content, at_userids=at_userids)


def notify_hotfix_start(
    webhook_url: str,
    issue_id: int,
    issue_title: str,
    branch_name: str,
    base_branch: str,
    gitlab_url: str,
    project_id: str,
    developer: str,
    author: str,
    at_userids: list[str],
) -> None:
    issue_link = f"{gitlab_url.rstrip('/')}/{project_id}/-/issues/{issue_id}"
    content = (
        f"### 🚨 线上Bug热修开始\n"
        f"> **Issue #{issue_id}**：{issue_title}\n"
        f"> **问题提出人**：{author}\n"
        f"> **开发者**：{developer}\n"
        f"> **分支**：`{branch_name}`（基于 `{base_branch}`）\n"
        f"> [查看 Issue]({issue_link})\n\n"
        f"**下一步 · {developer}**\n"
        f"> 1. 当前已切换到分支 `{branch_name}`，直接开始修复\n"
        f"> 2. 修复完成后提交代码（自动追加 Issue 编号）：\n"
        f">    `ccg gitlab commit \"修复说明\"`\n"
        f"> 3. 推送分支并创建 MR（直接合入 main）：\n"
        f">    `ccg gitlab mr create`\n"
    )
    send_webhook(webhook_url, content, at_userids=at_userids)


def notify_quickfix_start(
    webhook_url: str,
    issue_id: int,
    issue_title: str,
    branch_name: str,
    base_branch: str,
    gitlab_url: str,
    project_id: str,
    developer: str,
    author: str,
    at_userids: list[str],
) -> None:
    issue_link = f"{gitlab_url.rstrip('/')}/{project_id}/-/issues/{issue_id}"
    content = (
        f"### ⚡ 快速迭代开始\n"
        f"> **Issue #{issue_id}**：{issue_title}\n"
        f"> **提出人**：{author}\n"
        f"> **开发者**：{developer}\n"
        f"> **分支**：`{branch_name}`（基于 `{base_branch}`）\n"
        f"> [查看 Issue]({issue_link})\n\n"
        f"**下一步 · {developer}**\n"
        f"> 1. 当前已切换到分支 `{branch_name}`，直接开始开发\n"
        f"> 2. 完成后提交代码：\n"
        f">    `ccg gitlab commit \"变更说明\"`\n"
        f"> 3. 推送分支并创建 MR（直接合入 main）：\n"
        f">    `ccg gitlab mr create`\n"
    )
    send_webhook(webhook_url, content, at_userids=at_userids)


def notify_mr_created(
    webhook_url: str,
    issue_id: int,
    mr_iid: int,
    mr_title: str,
    mr_url: str,
    target_branch: str,
    author_name: str,
    operator: str,
    reviewer_names: list[str],
    at_userids: list[str],
    required_approvals: int = 1,
) -> None:
    reviewer_label = "、".join(reviewer_names) if reviewer_names else "Reviewer"
    approve_note = f"需要 **{required_approvals} 名** Reviewer 完成 Approve" if required_approvals > 1 else "在页面右侧点击「Approve」完成审批"
    content = (
        f"### MR 待评审\n"
        f"> **MR !{mr_iid}**：{mr_title}\n"
        f"> **关联 Issue**：#{issue_id}\n"
        f"> **合并目标**：`{target_branch}`\n"
        f"> **操作人**：{operator}\n"
        f"> [查看 MR]({mr_url})\n\n"
        f"**下一步 · {author_name}（需求提出人）**\n"
        f"> 点击上方「查看 MR」了解本次改动内容（知悉即可，无需操作）\n\n"
        f"**下一步 · {reviewer_label}**\n"
        f"> 1. 打开 [MR 页面]({mr_url}) 审阅代码改动\n"
        f"> 2. {approve_note}\n\n"
        f"**下一步 · {operator}（研发）**\n"
        f"> 1. 随时查看审批状态：\n"
        f">    `ccg gitlab mr check {mr_iid}`\n"
        f"> 2. 审批通过后执行合并：\n"
        f">    `ccg gitlab mr merge {mr_iid}`\n"
    )
    send_webhook(webhook_url, content, at_userids=at_userids)


def notify_mr_updated(
    webhook_url: str,
    mr_iid: int,
    mr_title: str,
    mr_url: str,
    target_branch: str,
    author_name: str,
    operator: str,
    reviewer_names: list[str],
    at_userids: list[str],
    dev_was_approved: bool = False,
    required_approvals: int = 1,
) -> None:
    reviewer_label = "、".join(reviewer_names) if reviewer_names else "Reviewer"

    stale_lines = ""
    if dev_was_approved:
        stale_lines = (
            f"**⚠ 注意：本次推送使以下已通过的门禁失效**\n"
            f"> - **{reviewer_label}** 的 Approve 基于旧代码，需重新审批\n\n"
        )

    content = (
        f"### MR 代码已更新\n"
        f"> **MR !{mr_iid}**：{mr_title}\n"
        f"> **合并目标**：`{target_branch}`\n"
        f"> **更新人**：{operator}\n"
        f"> [查看 MR]({mr_url})\n\n"
        f"{stale_lines}"
        f"**下一步 · {author_name}（需求提出人）**\n"
        f"> 代码有新改动，请查看改动内容（知悉即可，无需操作）\n\n"
        f"**下一步 · {reviewer_label}**\n"
        f"> 代码有新改动，请重新审阅并完成 Approve。\n"
        f"> 打开 [MR 页面]({mr_url}) 在右侧点击「Approve」"
        + (f"（需要 **{required_approvals} 名**）" if required_approvals > 1 else "")
        + f"\n\n"
        f"**下一步 · {operator}（研发）**\n"
        f"> 1. 随时查看审批状态：\n"
        f">    `ccg gitlab mr check {mr_iid}`\n"
        f"> 2. 审批通过后执行合并：\n"
        f">    `ccg gitlab mr merge {mr_iid}`\n"
    )
    send_webhook(webhook_url, content, at_userids=at_userids)


def notify_mr_merged(
    webhook_url: str,
    issue_id: int,
    mr_iid: int,
    target_branch: str,
    mr_url: str,
    operator: str,
    pre_branch: str,
    main_branch: str,
    tl_names: list[str],
    at_userids: list[str],
    issue_reporter_name: str = "",
    issue_link: str = "",
) -> None:
    tl_label = "、".join(tl_names) if tl_names else "TL"

    if target_branch == pre_branch:
        issue_line = f"> **关联 Issue**：#{issue_id}\n" if issue_id else ""
        issue_notes_link = f"{issue_link}#notes" if issue_link else ""
        issue_ref = f"Issue #{issue_id}" if issue_id else "Issue"
        reporter_label = issue_reporter_name or "需求提出人"
        next_steps = (
            f"**下一步 · {reporter_label}（产品）**\n"
            f"> 1. 登录 `{pre_branch}` 环境，按 {issue_ref} 验收标准逐项验证功能\n"
            f"> 2. 验收通过后，在 [Issue 评论区]({issue_notes_link}) 回复：`product:pass`\n\n"
            f"**下一步 · {operator}（研发）**\n"
            f"> 1. 登录 `{pre_branch}` 环境，按 {issue_ref} 验收标准逐项验证功能\n"
            f"> 2. 验收通过后，在 [Issue 评论区]({issue_notes_link}) 回复：`developer:pass`\n"
        )
    else:
        issue_line = f"> **关联 Issue**：#{issue_id}（已自动关闭）\n" if issue_id else ""
        next_steps = (
            f"**下一步 · {operator}**\n"
            f"> 1. 确认线上 Issue #{issue_id} 问题已修复\n"
            f"> 2. 将热修代码同步到 `{pre_branch}` 保持环境对齐：\n"
            f">    `ccg gitlab mr sync-pre`\n"
        )

    content = (
        f"### MR 已合并\n"
        f"> **MR !{mr_iid}** 已成功合并到 `{target_branch}`\n"
        f"{issue_line}"
        f"> **操作人**：{operator}\n"
        f"> [查看 MR]({mr_url})\n\n"
        f"{next_steps}"
    )
    send_webhook(webhook_url, content, at_userids=at_userids)


def notify_release_merged(
    webhook_url: str,
    mr_iid: int,
    mr_url: str,
    main_branch: str,
    closed_issues: list[dict],
    operator: str,
    at_userids: list[str],
) -> None:
    issue_lines = "\n".join(
        f"> - **#{i['id']}** {i['title']}（提出人：{i['author']}）"
        for i in closed_issues
    ) or "> （无关联 Issue）"
    content = (
        f"### pre → {main_branch} 上线完成\n"
        f"> **MR !{mr_iid}** 已合并，以下需求随本次上线关闭：\n"
        f"> **操作人**：{operator}\n"
        f"> [查看 MR]({mr_url})\n\n"
        f"{issue_lines}\n\n"
        f"**下一步 · 各需求提出人**\n"
        f"> 请登录线上环境，按各自 Issue 的验收标准逐项验证功能是否正常\n"
        f"> 如发现问题请及时提 Bug Issue（标题以【Bug】开头）或联系 {operator}\n"
    )
    send_webhook(webhook_url, content, at_userids=at_userids)


def notify_release_blocked(
    webhook_url: str,
    mr_iid: int,
    mr_url: str,
    main_branch: str,
    operator: str,
    issue_results: list[dict],
    at_userids: list[str],
) -> None:
    failed = [r for r in issue_results if not r["product_passed"] or not r["developer_passed"]]
    issue_blocks = []
    for r in failed:
        pv = r.get("product_verdict", "pending" if not r["product_passed"] else "passed")
        dv = r.get("developer_verdict", "pending" if not r["developer_passed"] else "passed")
        p_note = r.get("product_note", "")
        d_note = r.get("developer_note", "")

        if r["product_passed"]:
            pp = "✓ 已通过"
            if r.get("product_proxy"):
                pp += f"（⚠ 代发：{r['product_proxy_user']}）"
            if p_note:
                pp += f"：{p_note}"
        elif pv == "rejected":
            pp = "✗ 已拒绝"
            if r.get("product_proxy"):
                pp += f"（代发：{r['product_proxy_user']}）"
            if p_note:
                pp += f"：{p_note}"
        else:
            pp = "✗ 未验收"

        if r["developer_passed"]:
            dp = "✓ 已通过"
            if r.get("developer_proxy"):
                dp += f"（⚠ 代发：{r['developer_proxy_user']}）"
            if d_note:
                dp += f"：{d_note}"
        elif dv == "rejected":
            dp = "✗ 已拒绝"
            if r.get("developer_proxy"):
                dp += f"（代发：{r['developer_proxy_user']}）"
            if d_note:
                dp += f"：{d_note}"
        else:
            dp = "✗ 未验收"

        block = (
            f"**Issue #{r['issue_id']}**：{r['issue_title']}（[查看]({r['issue_url']})）\n"
            f"> 产品验收（product:pass）：{pp}  负责人：{r['reporter_name']}\n"
            f"> 研发验收（developer:pass）：{dp}  负责人：{r['assignee_name']}"
        )
        issue_blocks.append(block)

    content = (
        f"### pre → {main_branch} 上线被阻止\n"
        f"> **MR !{mr_iid}** 合入主干失败，以下 Issue 未完成 pre 环境验收\n"
        f"> **操作人**：{operator}\n"
        f"> [查看 MR]({mr_url})\n\n"
        + "\n\n".join(issue_blocks)
        + "\n\n**请以上负责人登录 pre 环境完成验收，在对应 Issue 评论区发布口令后重试**\n"
        f"> 产品验收通过：`product:pass`\n"
        f"> 产品验收拒绝：`product:reject 原因说明`\n"
        f"> 研发验收通过：`developer:pass`\n"
        f"> 研发验收拒绝：`developer:reject 原因说明`\n"
    )
    send_webhook(webhook_url, content, at_userids=at_userids)


def notify_release(
    webhook_url: str,
    mr_iid: int,
    mr_url: str,
    main_branch: str,
    operator: str,
    tl_names: list[str],
    at_userids: list[str],
) -> None:
    tl_label = "、".join(tl_names) if tl_names else "TL"
    content = (
        f"### pre → {main_branch} 上线 MR 已创建\n"
        f"> **MR !{mr_iid}** pre 测试通过，等待审批后合入 `{main_branch}` 上线\n"
        f"> **操作人**：{operator}\n"
        f"> [查看 MR]({mr_url})\n\n"
        f"**下一步 · {tl_label}**\n"
        f"> 1. 打开 [MR 页面]({mr_url}) 审阅本次上线的全部变更内容\n"
        f"> 2. 确认无误后在页面右侧点击「Approve」完成审批\n\n"
        f"**下一步 · {operator}**\n"
        f"> {tl_label} 审批通过后，执行以下命令合并上线：\n"
        f"> `ccg gitlab mr merge {mr_iid}`\n"
    )
    send_webhook(webhook_url, content, at_userids=at_userids)


def notify_issue_invalid(
    webhook_url: str,
    issue_id: int,
    issue_title: str,
    issue_link: str,
    author: str,
    developer: str,
    missing_sections: list[str],
    at_userids: list[str],
    issue_type: str = "feature",
) -> None:
    missing_str = "、".join(missing_sections)
    if issue_type == "bug":
        type_label = "Bug Issue 格式不合规"
        author_label = "Bug 提出人"
    elif issue_type == "improve":
        type_label = "优化 Issue 格式不合规"
        author_label = "优化提出人"
    else:
        type_label = "需求 Issue 格式不合规"
        author_label = "需求提出人"
    content = (
        f"### {type_label}\n"
        f"> **Issue #{issue_id}**：{issue_title}\n"
        f"> **{author_label}**：{author}\n"
        f"> **认领研发**：{developer}\n"
        f"> [查看 Issue]({issue_link})\n\n"
        f"**不合规详情**\n"
        f"> 缺少必填小节：{missing_str}\n\n"
        f"**下一步 · {author}（{author_label}）**\n"
        f"> 请按标准模板补充以上小节内容：[Issue #{issue_id}]({issue_link})\n"
        f"> 完成后通知研发重新认领\n"
    )
    send_webhook(webhook_url, content, at_userids=at_userids)


def notify_daily_report(webhook_url: str, content: str) -> None:
    send_webhook(webhook_url, content)


def notify_daily_report_image(webhook_url: str, image_bytes: bytes) -> None:
    import base64
    import hashlib
    if not webhook_url:
        print("[企微] Webhook URL 未配置，跳过通知。", file=sys.stderr)
        return
    b64 = base64.b64encode(image_bytes).decode()
    md5 = hashlib.md5(image_bytes).hexdigest()
    _post(webhook_url, {
        "msgtype": "image",
        "image": {"base64": b64, "md5": md5},
    })


def notify_sync_pre(
    webhook_url: str,
    mr_iid: int,
    mr_url: str,
    pre_branch: str,
    operator: str,
    tl_names: list[str],
    at_userids: list[str],
) -> None:
    tl_label = "、".join(tl_names) if tl_names else "TL"
    content = (
        f"### main → {pre_branch} 同步 MR 已创建\n"
        f"> **MR !{mr_iid}** 热修代码待同步到 `{pre_branch}`\n"
        f"> **操作人**：{operator}\n"
        f"> [查看 MR]({mr_url})\n\n"
        f"**下一步 · {tl_label}**\n"
        f"> 1. 打开 [MR 页面]({mr_url}) 确认热修内容与 main 一致\n"
        f"> 2. 在页面右侧点击「Approve」完成审批\n\n"
        f"**下一步 · {operator}**\n"
        f"> {tl_label} 审批通过后，执行以下命令完成同步：\n"
        f"> `ccg gitlab mr merge {mr_iid}`\n"
    )
    send_webhook(webhook_url, content, at_userids=at_userids)
