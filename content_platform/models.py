from dataclasses import asdict, dataclass, field


TERMINAL_STATES = {"blocked", "rejected", "published"}


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    status: str
    external_id: str = ""
    error: str = ""


@dataclass
class GateFailure:
    code: str
    rule_ref: str
    severity: str = "blocking"
    message: str = ""
    remediation: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class GateResult:
    """Gate validation result with gate name, status and failures."""
    gate: str = ""
    status: str = "passed"
    failures: list = field(default_factory=list)
    mode: str = "shadow"

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def to_dict(self):
        return {
            "gate": self.gate,
            "status": self.status,
            "mode": self.mode,
            "passed": self.passed,
            "failures": [
                failure.to_dict() if hasattr(failure, "to_dict") else dict(failure)
                for failure in self.failures
            ],
        }


@dataclass
class ContentPackage:
    content_package_id: str = ""
    status: str = "created"
    platform: str = ""
    account_id: str = ""
    content_type: str = "article"
    topic: str = ""
    title: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class PublishReceipt:
    status: str = ""
    verification_level: str = ""
    platform_content_id: str = ""

    def to_dict(self):
        return asdict(self)


def new_content_package_id(platform: str, account_id: str) -> str:
    import uuid
    return f"cp_{platform}_{account_id}_{uuid.uuid4().hex[:16]}"
