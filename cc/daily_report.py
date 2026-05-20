"""ccg gitlab daily-report — 团队日报生成与发送。"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .config import Config, load_config
from .gitlab_api import GitLabAPI, GitLabError
from .wechat import notify_daily_report, notify_daily_report_image
from .report_image import PIL_AVAILABLE, render_report


# ---------------------------------------------------------------------------
# 生成文件过滤（行数统计时排除）
# ---------------------------------------------------------------------------

_EXCLUDED_PATH_PATTERNS: list[str] = [
    # 依赖锁文件
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "go.sum", "Gemfile.lock", "composer.lock", "poetry.lock",
    # Protobuf / 代码生成
    "*.pb.go", "*_pb2.py", "*.pb.ts", "*_grpc.py",
    # 文档
    "*.md",
    # 压缩 / source map
    "*.min.js", "*.min.css", "*.map",
    # 构建产物 / 第三方依赖 / IDE
    "dist/*", "build/*", "vendor/*", "node_modules/*",
    ".idea/*", ".vscode/*",
]


def _is_excluded(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    for pattern in _EXCLUDED_PATH_PATTERNS:
        if "/" in pattern:
            if fnmatch.fnmatch(path, pattern):
                return True
        else:
            if fnmatch.fnmatch(name, pattern):
                return True
    return False


# ---------------------------------------------------------------------------
# 数据采集
# ---------------------------------------------------------------------------


_VIOLATION_PRINCIPLES: dict[str, str] = {
    "issue_closed_no_assignee": "Issue 必须有人认领才能关闭",
}


def _violation_principle(violation_type: str) -> str:
    return _VIOLATION_PRINCIPLES.get(violation_type, violation_type)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _issue_type(title: str) -> str:
    t = title.lower()
    if "bug" in t or "【bug】" in t:
        return "Bug"
    return "需求"


def _extract_assignees(issue: dict) -> list[str]:
    """从 issue 里提取 assignees 名字列表。"""
    names = []
    for a in issue.get("assignees") or []:
        names.append(a.get("name") or a.get("username") or "")
    if not names and issue.get("assignee"):
        a = issue["assignee"]
        names.append(a.get("name") or a.get("username") or "")
    return [n for n in names if n]


def fetch_violations(hook_url: str, since_dt: datetime) -> list[dict]:
    start = since_dt.strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")
    url = f"{hook_url.rstrip('/')}/violations?start={start}&end={end}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("items") or []
            return [
                {
                    "operator_name": v.get("operator_name") or v.get("operator", ""),
                    "action": v.get("description", ""),
                    "principle": _violation_principle(v.get("violation_type", "")),
                    "time": v.get("created_at", ""),
                }
                for v in items
            ]
    except Exception as e:
        print(f"[daily-report] 查询违规记录失败（{url}）：{e}", file=sys.stderr)
        return []


def collect_report_data(
    api: GitLabAPI,
    cfg: Config,
    hours: int = 24,
) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc)
    since_dt = now - timedelta(hours=hours)
    since_str = _iso(since_dt)

    print(f"[daily-report] 统计过去 {hours} 小时（{since_str} 至今）...")

    # --- 新提出的 Issues ---
    print("[daily-report] 拉取新 Issues...")
    try:
        new_raw = api.get_issues(created_after=since_str)
    except GitLabError as e:
        print(f"[错误] 获取 Issues 失败：{e}", file=sys.stderr)
        sys.exit(1)

    gitlab_base = f"{cfg.gitlab_url.rstrip('/')}/{cfg.gitlab_project_id}"
    new_issues = [
        {
            "id": i["iid"],
            "title": i.get("title", ""),
            "author": (i.get("author") or {}).get("name") or (i.get("author") or {}).get("username", ""),
            "assignees": _extract_assignees(i),
            "type": _issue_type(i.get("title", "")),
            "url": i.get("web_url") or f"{gitlab_base}/-/issues/{i['iid']}",
        }
        for i in new_raw
    ]

    # --- 关闭的 Issues（在时间窗口内关闭的）---
    print("[daily-report] 拉取已关闭 Issues...")
    try:
        closed_raw = api.get_issues(updated_after=since_str, state="closed", closed_after=since_str)
    except GitLabError as e:
        print(f"[错误] 获取已关闭 Issues 失败：{e}", file=sys.stderr)
        sys.exit(1)

    closed_issues = [
        {
            "id": i["iid"],
            "title": i.get("title", ""),
            "type": _issue_type(i.get("title", "")),
            "author": (i.get("author") or {}).get("name") or (i.get("author") or {}).get("username", ""),
            "assignees": _extract_assignees(i),
            "url": i.get("web_url") or f"{gitlab_base}/-/issues/{i['iid']}",
        }
        for i in closed_raw
    ]

    # --- 进行中的 Issues（所有 opened，按 updated_at 倒序前 30 条）---
    print("[daily-report] 拉取进行中 Issues...")
    try:
        open_raw = api.get_issues(state="opened")
    except GitLabError as e:
        print(f"[错误] 获取进行中 Issues 失败：{e}", file=sys.stderr)
        sys.exit(1)

    open_issues = [
        {
            "id": i["iid"],
            "title": i.get("title", ""),
            "type": _issue_type(i.get("title", "")),
            "author": (i.get("author") or {}).get("name") or (i.get("author") or {}).get("username", ""),
            "assignees": _extract_assignees(i),
            "url": i.get("web_url") or f"{gitlab_base}/-/issues/{i['iid']}",
        }
        for i in open_raw
    ]

    # --- 过滤排除的 Issue ---
    if cfg.daily_report_exclude_issues:
        new_issues    = [i for i in new_issues    if i["id"] not in cfg.daily_report_exclude_issues]
        closed_issues = [i for i in closed_issues if i["id"] not in cfg.daily_report_exclude_issues]
        open_issues   = [i for i in open_issues   if i["id"] not in cfg.daily_report_exclude_issues]

    # --- Commits ---
    print("[daily-report] 拉取提交记录（过滤生成文件后统计行数）...")
    try:
        raw_commits = api.get_commits_since(since=since_str)
    except GitLabError as e:
        print(f"[错误] 获取提交记录失败：{e}", file=sys.stderr)
        sys.exit(1)

    # 并发拉取每个 commit 的文件粒度 diff
    shas = [c.get("id") or "" for c in raw_commits]
    sha_to_diffs: dict[str, list[dict]] = {}
    if shas:
        print(f"[daily-report] 并发拉取 {len(shas)} 个 commit 的文件 diff...")
        with ThreadPoolExecutor(max_workers=8) as pool:
            future_to_sha = {pool.submit(api.get_commit_diff, sha): sha for sha in shas if sha}
            for future in as_completed(future_to_sha):
                sha_to_diffs[future_to_sha[future]] = future.result()

    commits = []
    for c in raw_commits:
        sha = c.get("id") or ""
        file_diffs = sha_to_diffs.get(sha, [])
        if file_diffs:
            additions = sum(f["additions"] for f in file_diffs if not _is_excluded(f["path"]))
            deletions = sum(f["deletions"] for f in file_diffs if not _is_excluded(f["path"]))
        else:
            # diff 拉取失败时降级使用聚合统计
            stats = c.get("stats") or {}
            additions = stats.get("additions") or 0
            deletions = stats.get("deletions") or 0
        commits.append({
            "sha": sha[:8],
            "author_name": c.get("author_name") or c.get("committer_name") or "",
            "author_email": c.get("author_email") or c.get("committer_email") or "",
            "title": c.get("title") or c.get("message", "").splitlines()[0] if c.get("message") else "",
            "additions": additions,
            "deletions": deletions,
            "created_at": c.get("created_at") or "",
        })

    # --- 建 email → GitLab username 映射，消除同一人的多个 git 名字 ---
    unique_emails = {c["author_email"] for c in commits if c["author_email"]}
    email_to_username: dict[str, str] = {}
    if unique_emails:
        print(f"[daily-report] 查询 {len(unique_emails)} 个邮箱对应的 GitLab 账号...")
    for email in unique_emails:
        user = api.get_user_by_email(email)
        if user:
            email_to_username[email] = user.get("username") or user.get("name") or email

    # --- 按人聚合 ---
    per_person: dict[str, dict] = {}
    for c in commits:
        name = email_to_username.get(c["author_email"]) or c["author_name"]
        if not name:
            continue
        if name not in per_person:
            per_person[name] = {"commits": 0, "additions": 0, "deletions": 0, "commit_titles": []}
        per_person[name]["commits"] += 1
        per_person[name]["additions"] += c["additions"]
        per_person[name]["deletions"] += c["deletions"]
        per_person[name]["commit_titles"].append(c["title"])

    # 关联 Issue：从 commit title 里提取 #N 编号，再匹配 Issue 标题
    issue_map = {str(i["id"]): i["title"] for i in new_issues + closed_issues + open_issues}
    import re
    for name, stat in per_person.items():
        issue_refs: list[str] = []
        seen_ids: set[str] = set()
        for title in stat["commit_titles"]:
            for issue_id in re.findall(r"#(\d+)", title):
                if issue_id not in seen_ids:
                    seen_ids.add(issue_id)
                    issue_title = issue_map.get(issue_id, "")
                    issue_refs.append(f"#{issue_id}" + (f" {issue_title}" if issue_title else ""))
        stat["issues"] = issue_refs
        del stat["commit_titles"]

    total_additions = sum(c["additions"] for c in commits)
    total_deletions = sum(c["deletions"] for c in commits)

    # --- 违规记录（可选，需配置 GITLAB_HOOK_URL）---
    violations: list[dict] = []
    if cfg.gitlab_hook_url:
        print("[daily-report] 查询违规记录...")
        violations = fetch_violations(cfg.gitlab_hook_url, since_dt)

    return {
        "period": f"过去{hours}小时",
        "since": since_str,
        "new_issues": new_issues,
        "closed_issues": closed_issues,
        "open_issues": open_issues,
        "total_commits": len(commits),
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "per_person": per_person,
        "violations": violations,
    }


# ---------------------------------------------------------------------------
# LLM 总结
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """\
你是一名技术团队助理，请将以下结构化团队工作数据整理成给老板看的日报。

【格式要求】
- 使用企业微信 Markdown 格式（支持 **加粗**、> 引用、- 列表）
- 语言精炼，老板能 30 秒读完
- 需求和 Bug 分两个独立板块，不要混在一起；type 字段为"Bug"的归入 Bug 板块，其余归入需求板块
- 每个子类别（新提出/已完成/进行中/已修复/修复中）下必须逐条列出所有 Issue，不能只写数量；数量为 0 时写「暂无」
- 每条 Issue 使用 Markdown 链接格式：[#编号 标题](url)，url 来自数据中的 url 字段
- 每条 Issue 必须直接使用数据中的 assignees 字段：非空则写"执行者：xxx"，为空列表时才写"待分配"；禁止自行判断或推断执行者
- 代码部分：按人汇总提交次数和行数，并说明在做什么（从 issues 字段推断）；该人无提交则不列出
- 标题用 ### 开头
- 「流程违规记录」板块必须输出，violations 为空时写「暂无」；非空时按人头统计违规次数，按次数从多到少排列

【输出示例】
### 📊 团队日报（过去24小时）

**需求动态**
> 新提出：1 个
> - [#45 用户中心增加消费记录](https://gitlab.example.com/project/-/issues/45)（提出人：Alice，执行者：张三）
> 已完成：1 个
> - [#43 首页改版](https://gitlab.example.com/project/-/issues/43)（执行：张三）
> 进行中：3 个
> - [#40 支付流程优化](https://gitlab.example.com/project/-/issues/40)（提出人：Carol，执行者：李四）
> - [#38 用户画像分析](https://gitlab.example.com/project/-/issues/38)（提出人：Dave，执行者：王五）
> - [#35 消息推送改造](https://gitlab.example.com/project/-/issues/35)（提出人：Eve，待分配）

**Bug 动态**
> 新提出：1 个
> - [#46 登录超时](https://gitlab.example.com/project/-/issues/46)（提出人：Bob，待分配）
> 已修复：0 个
> 暂无
> 修复中：2 个
> - [#42 图片上传失败](https://gitlab.example.com/project/-/issues/42)（提出人：Frank，执行者：张三）
> - [#39 搜索结果乱序](https://gitlab.example.com/project/-/issues/39)（提出人：Grace，执行者：李四）

**代码提交**
> 共 12 次提交，+320 / -45 行
> - 张三：8 次，+210 / -30 行（#43 首页改版）
> - 李四：4 次，+110 / -15 行（#44 支付优化）

**⚠ 流程违规记录**
> - **张三**：3 次
> - **李四**：1 次

【待整理数据】
{data}
"""


def summarize_with_llm(data: dict, cfg: Config) -> Optional[str]:
    if not cfg.llm_api_key:
        return None

    prompt = _PROMPT_TEMPLATE.format(data=json.dumps(data, ensure_ascii=False, indent=2))
    payload = {
        "model": cfg.llm_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1500,
        "temperature": 0.3,
    }
    body = json.dumps(payload).encode("utf-8")
    url = cfg.llm_base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {cfg.llm_api_key}")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"[daily-report] LLM 调用失败 HTTP {e.code}: {err_body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[daily-report] LLM 调用失败: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# 降级：无 LLM 时的文本格式化
# ---------------------------------------------------------------------------


def format_without_llm(data: dict) -> str:
    period = data["period"]
    new_issues = data["new_issues"]
    closed_issues = data["closed_issues"]
    open_issues = data["open_issues"]
    total_commits = data["total_commits"]
    total_additions = data["total_additions"]
    total_deletions = data["total_deletions"]
    per_person = data["per_person"]

    lines = [f"### 📊 团队日报（{period}）", ""]

    def _split(issues: list[dict]) -> tuple[list[dict], list[dict]]:
        bugs = [i for i in issues if i.get("type") == "Bug"]
        reqs = [i for i in issues if i.get("type") != "Bug"]
        return reqs, bugs

    def _issue_line(i: dict) -> str:
        assignees = "、".join(i.get("assignees") or []) if isinstance(i.get("assignees"), list) else ""
        assignee_str = f"，执行者：{assignees}" if assignees else "，待分配"
        link = f"[#{i['id']} {i['title']}]({i['url']})" if i.get("url") else f"#{i['id']} {i['title']}"
        return f"> - {link}（提出人：{i['author']}{assignee_str}）"

    def _closed_line(i: dict) -> str:
        assignees = "、".join(i.get("assignees") or [])
        dev_str = f"执行：{assignees}" if assignees else "执行者未知"
        link = f"[#{i['id']} {i['title']}]({i['url']})" if i.get("url") else f"#{i['id']} {i['title']}"
        return f"> - {link}（{dev_str}）"

    new_reqs, new_bugs = _split(new_issues)
    closed_reqs, closed_bugs = _split(closed_issues)
    open_reqs, open_bugs = _split(open_issues)

    def _append_section(label: str, items: list[dict], line_fn: Any) -> None:
        lines.append(f"> {label}：{len(items)} 个")
        if items:
            for i in items:
                lines.append(line_fn(i))
        else:
            lines.append("> 暂无")

    # 需求动态
    lines.append("**需求动态**")
    _append_section("新提出", new_reqs, _issue_line)
    _append_section("已完成", closed_reqs, _closed_line)
    _append_section("进行中", open_reqs, _issue_line)
    lines.append("")

    # Bug 动态
    lines.append("**Bug 动态**")
    _append_section("新提出", new_bugs, _issue_line)
    _append_section("已修复", closed_bugs, _closed_line)
    _append_section("修复中", open_bugs, _issue_line)
    lines.append("")

    # 代码提交
    lines.append("**代码提交**")
    if total_commits == 0:
        lines.append("> 暂无提交")
    else:
        lines.append(f"> 共 {total_commits} 次提交，+{total_additions} / -{total_deletions} 行")
        for name, stat in per_person.items():
            issue_hint = "、".join(stat["issues"][:3]) if stat["issues"] else ""
            issue_str = f"（{issue_hint}）" if issue_hint else ""
            lines.append(
                f"> - {name}：{stat['commits']} 次，"
                f"+{stat['additions']} / -{stat['deletions']} 行{issue_str}"
            )

    # 违规记录（始终展示，按人头统计）
    violations = data.get("violations") or []
    lines.append("")
    lines.append("**⚠ 流程违规记录**")
    if violations:
        count_by_person: dict[str, int] = {}
        for v in violations:
            name = v["operator_name"]
            count_by_person[name] = count_by_person.get(name, 0) + 1
        for name, cnt in sorted(count_by_person.items(), key=lambda x: -x[1]):
            lines.append(f"> - **{name}**：{cnt} 次")
    else:
        lines.append("> 暂无")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 子命令入口
# ---------------------------------------------------------------------------


def cmd_daily_report(args: argparse.Namespace) -> None:
    cfg = load_config()
    api = GitLabAPI(cfg)

    hours: int = args.hours
    no_llm: bool = args.no_llm
    dry_run: bool = args.dry_run

    data = collect_report_data(api, cfg, hours=hours)

    if no_llm or not cfg.llm_api_key:
        if not no_llm and not cfg.llm_api_key:
            print("[daily-report] 未配置 LLM_API_KEY，使用内置格式化。")
        content = format_without_llm(data)
    else:
        print(f"[daily-report] 调用 LLM（{cfg.llm_model}）生成总结...")
        content = summarize_with_llm(data, cfg)
        if content:
            print(f"[daily-report] LLM 调用成功，返回 {len(content)} 字符。")
        else:
            print("[daily-report] LLM 返回空，降级使用内置格式化。")
            content = format_without_llm(data)

    print("\n" + "=" * 60)
    print(content)
    print("=" * 60 + "\n")

    if dry_run:
        print("[daily-report] --dry-run 模式，不发送企微通知。")
        return

    if PIL_AVAILABLE:
        print("[daily-report] 生成日报图片...")
        try:
            img_bytes = render_report(content)
            notify_daily_report_image(cfg.wechat_daily_report_webhook_url, img_bytes)
            print("[daily-report] 日报图片已发送至企业微信。")
            return
        except Exception as e:
            print(f"[daily-report] 图片生成失败（{e}），降级为文本发送。", file=sys.stderr)

    notify_daily_report(cfg.wechat_daily_report_webhook_url, content)
    print("[daily-report] 日报已发送至企业微信。")
