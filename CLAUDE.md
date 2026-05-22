# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`ccg` (cc-gitlab) is a Python CLI tool that standardizes the product-dev-reviewer collaboration workflow around GitLab. It automates branch creation, MR lifecycle, pre-environment acceptance checks, and WeChat Work (企业微信) notifications.

## Development Commands

```bash
# Install locally (editable)
pip install -e .

# Install with image rendering support (for daily report)
pip install -e ".[image]"

# Run the CLI
ccg --help
ccg gitlab feature start <issue_id>
ccg gitlab daily-report --dry-run
```

No test suite or linter is configured in this project.

## Architecture

Single Python package `cc/` with entry point `ccg = cc.main:main`.

| Module | Responsibility |
|--------|---------------|
| `main.py` | argparse routing + all subcommand implementations (`cmd_*` functions) |
| `config.py` | Loads `.env` / `.env.local` (walks up from cwd), builds `Config` dataclass |
| `gitlab_api.py` | Thin HTTP wrapper around GitLab REST API (urllib, no dependencies) |
| `branch.py` | Git operations: checkout, branch naming, push, commit parsing |
| `mr.py` | MR description building, approval checks, acceptance verdict logic |
| `validator.py` | Issue format validation (required `##` sections per issue type) |
| `wechat.py` | WeChat Work webhook notification formatting and sending |
| `daily_report.py` | Data collection + LLM summarization + image rendering for daily reports |
| `report_image.py` | Pillow-based image rendering for daily report (optional dependency) |

## Key Design Decisions

- Zero external dependencies for core functionality (stdlib `urllib` for HTTP, no `requests`). Only optional dep is `Pillow` for image rendering.
- Config is split: `.env` (team-shared, committed) + `.env.local` (personal token/username, gitignored).
- Issue type detection is purely section-header-based (`## 需求背景` → feature, `## 优化背景` → improve, `## 问题现象` → bug).
- Pre-environment acceptance uses comment-based verdicts (`product:pass`, `developer:pass`) with last-comment-wins semantics relative to the last MR merge time.
- LLM integration (commit message generation, daily report summarization) uses any OpenAI-compatible API and degrades gracefully when unconfigured.

## CLI Command Structure

```
ccg gitlab feature start <issue_id> [--base BRANCH]
ccg gitlab hotfix start <issue_id> [--base BRANCH]
ccg gitlab commit ["message"]
ccg gitlab mr create [--target BRANCH]
ccg gitlab mr check <mr_iid>
ccg gitlab mr merge <mr_iid>
ccg gitlab mr release
ccg gitlab mr sync-pre
ccg gitlab daily-report [--hours N] [--no-llm] [--dry-run]
```
