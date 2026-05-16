"""ccg gitlab daily-report — 团队日报生成与发送。"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .config import Config, load_config
from .gitlab_api import GitLabAPI, GitLabError
from .wechat import notify_daily_report


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
            "author": (i.get("author") or {}).get("name") or (i.get("author") or {}).get("username", ""),
            "assignees": _extract_assignees(i),
            "url": i.get("web_url") or f"{gitlab_base}/-/issues/{i['iid']}",
        }
        for i in open_raw
    ]

    # --- Commits ---
    print("[daily-report] 拉取提交记录（含行数统计）...")
    try:
        raw_commits = api.get_commits_since(since=since_str)
    except GitLabError as e:
        print(f"[错误] 获取提交记录失败：{e}", file=sys.stderr)
        sys.exit(1)

    commits = []
    for c in raw_commits:
        stats = c.get("stats") or {}
        commits.append({
            "sha": (c.get("id") or "")[:8],
            "author_name": c.get("author_name") or c.get("committer_name") or "",
            "author_email": c.get("author_email") or c.get("committer_email") or "",
            "title": c.get("title") or c.get("message", "").splitlines()[0] if c.get("message") else "",
            "additions": stats.get("additions") or 0,
            "deletions": stats.get("deletions") or 0,
            "created_at": c.get("created_at") or "",
        })

    # --- 按人聚合 ---
    per_person: dict[str, dict] = {}
    for c in commits:
        name = c["author_name"]
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
- 需求部分：每条需求列出提出者和执行者（assignees，无则写"待分配"）
- 代码部分：按人汇总提交次数和行数，并说明在做什么（从 issues 字段推断）
- 如果某人当天没有提交，不要列出
- 进行中的需求逐条列出，包含提出者和执行者
- 标题用 ### 开头
- 如果 violations 字段非空，必须输出「流程违规记录」板块，逐条列出：操作人、违规时间、违规动作、违背原则

【输出示例】
### 📊 团队日报（过去24小时）

**需求动态**
> 新提出：2 个
> - #45 用户中心增加消费记录（提出人：Alice，执行者：张三）
> - #46 【Bug】登录超时（提出人：Bob，待分配）
> 已完成：1 个
> - #43 首页改版（执行：张三）
> 进行中：5 个

**代码提交**
> 共 12 次提交，+320 / -45 行
> - 张三：8 次，+210 / -30 行（#43 首页改版）
> - 李四：4 次，+110 / -15 行（#44 支付优化）

**⚠ 流程违规记录**
> - **张三** · 2026-05-16 10:23
>   违规动作：Issue #12「xxx」无人认领即关闭
>   违背原则：Issue 必须有人认领才能关闭

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

    # 需求动态
    lines.append("**需求动态**")
    lines.append(f"> 新提出：{len(new_issues)} 个")
    for i in new_issues:
        assignees = "、".join(i.get("assignees") or []) if isinstance(i.get("assignees"), list) else ""
        assignee_str = f"，执行者：{assignees}" if assignees else "，待分配"
        lines.append(f"> - #{i['id']} {i['title']}（提出人：{i['author']}{assignee_str}）")
    lines.append(f"> 已完成：{len(closed_issues)} 个")
    for i in closed_issues:
        assignees = "、".join(i.get("assignees") or [])
        dev_str = f"执行：{assignees}" if assignees else "执行者未知"
        lines.append(f"> - #{i['id']} {i['title']}（{dev_str}）")
    lines.append(f"> 进行中：{len(open_issues)} 个")
    for i in open_issues:
        assignees = "、".join(i.get("assignees") or []) if isinstance(i.get("assignees"), list) else ""
        assignee_str = f"，执行者：{assignees}" if assignees else "，待分配"
        lines.append(f"> - #{i['id']} {i['title']}（提出人：{i['author']}{assignee_str}）")
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

    # 违规记录
    violations = data.get("violations") or []
    if violations:
        lines.append("")
        lines.append("**⚠ 流程违规记录**")
        for v in violations:
            lines.append(
                f"> - **{v['operator_name']}** · {v['time'][:16]}\n"
                f">   违规动作：{v['action']}\n"
                f">   违背原则：{v['principle']}"
            )

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

    notify_daily_report(cfg.wechat_daily_report_webhook_url, content)
    print("[daily-report] 日报已发送至企业微信。")
