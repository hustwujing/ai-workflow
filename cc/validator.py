import re
import sys
from typing import List, Literal, Optional


class ValidationError(Exception):
    def __init__(self, message: str, missing: Optional[List[str]] = None):
        super().__init__(message)
        self.missing: List[str] = missing or []


IssueType = Literal["feature", "bug"]

FEATURE_SECTIONS = ["需求背景", "功能详细描述", "验收标准", "优先级"]
BUG_SECTIONS = ["问题现象", "复现步骤", "预期正常结果", "实际异常结果", "出现环境", "严重等级"]


def detect_issue_type(title: str) -> Optional[IssueType]:
    if title.startswith("【需求】"):
        return "feature"
    if title.startswith("【Bug】") or title.startswith("【bug】"):
        return "bug"
    return None


def _check_sections(body: str, sections: list[str]) -> list[str]:
    missing = []
    for section in sections:
        pattern = rf"##\s*{re.escape(section)}"
        if not re.search(pattern, body):
            missing.append(section)
    return missing


def validate_feature_issue(body: str) -> None:
    missing = _check_sections(body or "", FEATURE_SECTIONS)
    if missing:
        raise ValidationError(
            f"Issue格式不合规，请产品按标准模板补充完整后再开发\n"
            f"缺少必填小节：{', '.join(missing)}",
            missing=missing,
        )


def validate_bug_issue(body: str) -> None:
    missing = _check_sections(body or "", BUG_SECTIONS)
    if missing:
        raise ValidationError(
            f"Issue格式不合规，请产品按标准模板补充完整后再开发\n"
            f"缺少必填小节：{', '.join(missing)}",
            missing=missing,
        )
