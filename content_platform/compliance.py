import re


class ComplianceChecker:
    ABSOLUTE_PATTERNS = ("稳赚", "保证成功", "绝对安全", "100%有效", "第一名", "best ever")

    def evaluate(self, text, brief=None, platforms=None):
        brief, findings = brief or {}, []
        lowered = str(text).lower()
        for phrase in self.ABSOLUTE_PATTERNS:
            if phrase.lower() in lowered:
                findings.append({"code": "absolute_claim", "level": "review", "detail": phrase})
        numeric_claim = re.search(r"(?:\d+(?:\.\d+)?%|\b20\d{2}\b|[$¥￥]\s*\d+)", str(text))
        if numeric_claim and not brief.get("sources"):
            findings.append({"code": "numeric_claim_without_source", "level": "review", "detail": numeric_claim.group(0)})
        if not brief.get("sources") and any(name in lowered for name in ("研究表明", "数据显示", "according to")):
            findings.append({"code": "attribution_without_source", "level": "review", "detail": "source required"})
        return {"level": "review" if findings else "pass", "findings": findings, "platforms": platforms or []}

