from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DiffAnalysis:
    verdict: str
    reasons: list[str]


@dataclass
class ProviderHealth:
    available: bool = True
    last_error: str | None = None
    blocked_reason: str | None = None

    def mark_failure(self, error: str) -> None:
        self.last_error = error

    def block(self, reason: str, error: str) -> None:
        self.available = False
        self.blocked_reason = reason
        self.last_error = error
