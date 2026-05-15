import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _load_file(env_file: Path, override: bool = False) -> None:
    with env_file.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if key and (override or key not in os.environ):
                os.environ[key] = val


def _load_dotenv() -> tuple[bool, bool]:
    """从当前目录向上查找 .env（团队公共）和 .env.local（个人私有）并加载。
    返回 (found_shared, found_local)。
    """
    path = Path.cwd()
    for directory in [path, *path.parents]:
        shared = directory / ".env"
        local = directory / ".env.local"
        if shared.is_file() or local.is_file():
            if shared.is_file():
                _load_file(shared, override=False)
            if local.is_file():
                _load_file(local, override=True)
            return shared.is_file(), local.is_file()
    return False, False


@dataclass
class Config:
    gitlab_url: str
    gitlab_token: str
    gitlab_project_id: str
    branch_main: str
    branch_pre: str
    gitlab_username: str                   # 当前开发者的 GitLab 用户名
    wechat_webhook_url: str
    wechat_daily_report_webhook_url: str   # 日报专用群 Webhook，未配置时回退到 wechat_webhook_url
    at_tl_list: list[str]                  # TL 的手机号列表（固定）
    gitlab_reviewer_usernames: list[str]   # GitLab reviewer 的用户名
    wechat_user_map: dict[str, str] = field(default_factory=dict)  # gitlab_username -> 手机号
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    def resolve_wechat_id(self, gitlab_username: str) -> str:
        """GitLab 用户名 → 手机号，找不到返回空字符串"""
        return self.wechat_user_map.get(gitlab_username, "")

    def resolve_wechat_ids(self, gitlab_usernames: list[str]) -> list[str]:
        return [uid for uid in (self.resolve_wechat_id(u) for u in gitlab_usernames) if uid]


_PERSONAL_KEYS = {"GITLAB_PRIVATE_TOKEN", "GITLAB_USERNAME"}


def load_config() -> Config:
    found_shared, found_local = _load_dotenv()

    if not found_shared and not found_local:
        print("[错误] 未找到 .env 配置文件。", file=sys.stderr)
        print("请在项目根目录创建 .env 和 .env.local。", file=sys.stderr)
        print("参考：README.md 二、安装与配置", file=sys.stderr)
        sys.exit(1)

    missing = []

    def require(key: str) -> str:
        val = os.environ.get(key, "").strip()
        if not val:
            missing.append(key)
        return val

    def optional(key: str, default: str = "") -> str:
        return os.environ.get(key, default).strip()

    # 扫描所有 WECHAT_USER_<gitlab_username>=<wechat_userid> 映射
    prefix = "WECHAT_USER_"
    user_map = {
        key[len(prefix):]: val.strip()
        for key, val in os.environ.items()
        if key.startswith(prefix) and val.strip()
    }

    tl_raw = optional("WECHAT_AT_TL")
    at_tl_list = [uid.strip() for uid in tl_raw.split(",") if uid.strip()]

    reviewer_raw = optional("GITLAB_REVIEWER_USERNAMES")
    gitlab_reviewer_usernames = [x.strip() for x in reviewer_raw.split(",") if x.strip()]

    cfg = Config(
        gitlab_url=require("GITLAB_URL").rstrip("/"),
        gitlab_token=require("GITLAB_PRIVATE_TOKEN"),
        gitlab_project_id=require("GITLAB_PROJECT_ID"),
        branch_main=optional("GITLAB_BRANCH_MAIN", "main"),
        branch_pre=optional("GITLAB_BRANCH_PRE", "pre"),
        gitlab_username=require("GITLAB_USERNAME"),
        wechat_webhook_url=optional("WECHAT_WEBHOOK_URL"),
        wechat_daily_report_webhook_url=optional("WECHAT_DAILY_REPORT_WEBHOOK_URL") or optional("WECHAT_WEBHOOK_URL"),
        at_tl_list=at_tl_list,
        gitlab_reviewer_usernames=gitlab_reviewer_usernames,
        wechat_user_map=user_map,
        llm_base_url=optional("LLM_BASE_URL", "https://api.openai.com/v1"),
        llm_api_key=optional("LLM_API_KEY"),
        llm_model=optional("LLM_MODEL", "gpt-4o-mini"),
    )

    if missing:
        personal_missing = [k for k in missing if k in _PERSONAL_KEYS]
        team_missing = [k for k in missing if k not in _PERSONAL_KEYS]
        if personal_missing and not found_local:
            print(f"[错误] 缺少个人配置（通常在 .env.local）：{', '.join(personal_missing)}", file=sys.stderr)
            print("请在项目根目录创建 .env.local 并填写：", file=sys.stderr)
            print("  GITLAB_PRIVATE_TOKEN=glpat-xxxxxxxxxxxx", file=sys.stderr)
            print("  GITLAB_USERNAME=你的GitLab用户名", file=sys.stderr)
        else:
            print(f"[错误] 缺少必填配置：{', '.join(missing)}", file=sys.stderr)
        if team_missing:
            print(f"以下团队配置请在 .env 中补充：{', '.join(team_missing)}", file=sys.stderr)
        print("参考：README.md 二、安装与配置", file=sys.stderr)
        sys.exit(1)

    return cfg
