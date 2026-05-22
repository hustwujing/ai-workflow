import re
import sys
from typing import List, Literal, Optional


class ValidationError(Exception):
    def __init__(self, message: str, missing: Optional[List[str]] = None):
        super().__init__(message)
        self.missing: List[str] = missing or []


IssueType = Literal["feature", "improve", "bug", "quickfix"]

FEATURE_SECTIONS = ["需求背景", "功能详细描述", "验收标准", "优先级"]
IMPROVE_SECTIONS = ["优化背景", "现状问题", "优化方案", "预期收益", "优先级"]
BUG_SECTIONS = ["问题现象", "复现步骤", "预期正常结果", "实际异常结果", "出现环境", "严重等级"]
QUICKFIX_SECTIONS = ["变更说明", "影响范围", "验收标准", "优先级"]


def detect_issue_type(body: str) -> Optional[IssueType]:
    """根据 description 中的唯一标识章节推断 issue 类型。"""
    b = body or ""
    if re.search(r"##\s*优化背景", b):
        return "improve"
    if re.search(r"##\s*需求背景", b):
        return "feature"
    if re.search(r"##\s*问题现象", b):
        return "bug"
    if re.search(r"##\s*变更说明", b):
        return "quickfix"
    return None


def _check_sections(body: str, sections: list[str]) -> list[str]:
    missing = []
    for section in sections:
        pattern = rf"##\s*{re.escape(section)}"
        if not re.search(pattern, body):
            missing.append(section)
    return missing


def get_missing_sections(body: str, issue_type: IssueType) -> list[str]:
    """返回缺失的必填小节列表，不抛异常，供外部与其他校验项合并后统一处理。"""
    sections = {"feature": FEATURE_SECTIONS, "improve": IMPROVE_SECTIONS, "bug": BUG_SECTIONS, "quickfix": QUICKFIX_SECTIONS}[issue_type]
    return _check_sections(body or "", sections)


def validate_feature_issue(body: str) -> None:
    missing = _check_sections(body or "", FEATURE_SECTIONS)
    if missing:
        raise ValidationError(
            f"Issue格式不合规，请产品按标准模板补充完整后再开发\n"
            f"缺少必填小节：{', '.join(missing)}",
            missing=missing,
        )


def validate_improve_issue(body: str) -> None:
    missing = _check_sections(body or "", IMPROVE_SECTIONS)
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
