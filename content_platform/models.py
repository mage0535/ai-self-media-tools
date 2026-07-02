from dataclasses import dataclass


TERMINAL_STATES = {"blocked", "rejected", "published"}


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    status: str
    external_id: str = ""
    error: str = ""

