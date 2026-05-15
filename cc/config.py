import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    """从当前目录向上查找 .env 文件并加载，已有的环境变量不覆盖。"""
    path = Path.cwd()
    for directory in [path, *path.parents]:
        env_file = directory / ".env"
        if env_file.is_file():
            with env_file.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip()
                    if key and key not in os.environ:
                        os.environ[key] = val
            break


@dataclass
class Config:
    gitlab_url: str
    gitlab_token: str
    gitlab_project_id: str
    branch_main: str
    branch_pre: str
    gitlab_username: str                   # 当前开发者的 GitLab 用户名
    wechat_webhook_url: str
    at_tl_list: list[str]                  # TL 的手机号列表（固定）
    gitlab_reviewer_usernames: list[str]   # GitLab reviewer 的用户名
    wechat_user_map: dict[str, str] = field(default_factory=dict)  # gitlab_username -> 手机号

    def resolve_wechat_id(self, gitlab_username: str) -> str:
        """GitLab 用户名 → 手机号，找不到返回空字符串"""
        return self.wechat_user_map.get(gitlab_username, "")

    def resolve_wechat_ids(self, gitlab_usernames: list[str]) -> list[str]:
        return [uid for uid in (self.resolve_wechat_id(u) for u in gitlab_usernames) if uid]


def load_config() -> Config:
    _load_dotenv()
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
        at_tl_list=at_tl_list,
        gitlab_reviewer_usernames=gitlab_reviewer_usernames,
        wechat_user_map=user_map,
    )

    if missing:
        print(f"[错误] 缺少必填环境变量：{', '.join(missing)}", file=sys.stderr)
        print("请参考 .env.example 配置后重试。", file=sys.stderr)
        sys.exit(1)

    return cfg
