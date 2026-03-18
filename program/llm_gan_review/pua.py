from __future__ import annotations

from dataclasses import dataclass

from .config import ProviderConfig
from .dspy_adapter import DSPyPUAAdapter
from .review_types import DiffAnalysis


@dataclass
class PUAResult:
    triggered: bool
    level: str
    target_agent: str
    reason: str
    interrogation: str


class PUAEngine:
    def __init__(self, provider_config: ProviderConfig | None = None) -> None:
        self.dspy = DSPyPUAAdapter(provider_config) if provider_config else None

    def assess(
        self,
        diff_analysis: DiffAnalysis,
        critique_meta: dict,
        rebuttal_meta: dict,
    ) -> PUAResult:
        if diff_analysis.verdict == "busywork":
            return PUAResult(
                triggered=True,
                level="L3",
                target_agent="GPT Defender",
                reason="Busywork detected after rebuttal commit.",
                interrogation=self._build_interrogation(
                    level="L3",
                    target_agent="GPT Defender",
                    reason="Busywork detected after rebuttal commit.",
                    diff_reasons=diff_analysis.reasons,
                    fallback=self._build_l3(diff_analysis.reasons),
                ),
            )
        if critique_meta.get("error_type") == "quota_exhausted":
            return PUAResult(
                triggered=True,
                level="L1",
                target_agent="Gemini Critic",
                reason="Critic quota exhausted before completing a live round.",
                interrogation=self._build_interrogation(
                    level="L1",
                    target_agent="Gemini Critic",
                    reason="Critic quota exhausted before completing a live round.",
                    diff_reasons=[],
                    fallback=self._build_quota_notice("Gemini Critic"),
                ),
            )
        if critique_meta.get("mode") == "fallback":
            return PUAResult(
                triggered=True,
                level="L1",
                target_agent="Gemini Critic",
                reason="Critic did not complete a live API-backed round.",
                interrogation=self._build_interrogation(
                    level="L1",
                    target_agent="Gemini Critic",
                    reason="Critic did not complete a live API-backed round.",
                    diff_reasons=[],
                    fallback=self._build_l1("Gemini Critic"),
                ),
            )
        if rebuttal_meta.get("error_type") == "quota_exhausted":
            return PUAResult(
                triggered=True,
                level="L2",
                target_agent="GPT Defender",
                reason="Defender quota exhausted before completing a live round.",
                interrogation=self._build_interrogation(
                    level="L2",
                    target_agent="GPT Defender",
                    reason="Defender quota exhausted before completing a live round.",
                    diff_reasons=[],
                    fallback=self._build_quota_notice("GPT Defender"),
                ),
            )
        if rebuttal_meta.get("mode") == "fallback":
            return PUAResult(
                triggered=True,
                level="L2",
                target_agent="GPT Defender",
                reason="Defender did not complete a live API-backed round.",
                interrogation=self._build_interrogation(
                    level="L2",
                    target_agent="GPT Defender",
                    reason="Defender did not complete a live API-backed round.",
                    diff_reasons=[],
                    fallback=self._build_l2("GPT Defender"),
                ),
            )
        return PUAResult(
            triggered=False,
            level="NONE",
            target_agent="",
            reason="No escalation needed. Both agents produced substantive output.",
            interrogation="# PUA Status\n\nNo escalation triggered in this round.",
        )

    def _build_interrogation(
        self,
        level: str,
        target_agent: str,
        reason: str,
        diff_reasons: list[str],
        fallback: str,
    ) -> str:
        if not self.dspy:
            return fallback
        try:
            return self.dspy.build_interrogation(level, target_agent, reason, diff_reasons)
        except Exception:
            return fallback

    def _build_l1(self, target_agent: str) -> str:
        return "\n".join(
            [
                "# Escalation L1",
                "",
                f"Target: {target_agent}",
                "",
                "This round did not complete cleanly. Restate the paper's core claim, identify the strongest evidence anchor, and explain what blocked a full response.",
            ]
        )

    def _build_quota_notice(self, target_agent: str) -> str:
        return "\n".join(
            [
                "# Escalation Quota",
                "",
                f"Target: {target_agent}",
                "",
                "The round degraded because provider quota was exhausted, not because the argument was accepted.",
                "Record the interruption, preserve the strongest available critique/rebuttal context, and resume only when budget is restored.",
            ]
        )

    def _build_l2(self, target_agent: str) -> str:
        return "\n".join(
            [
                "# Escalation L2",
                "",
                f"Target: {target_agent}",
                "",
                "The response path degraded before producing a trustworthy round. Provide a structured recovery plan with:",
                "- the missing evidence you should have cited",
                "- the concrete argument delta you intended to add",
                "- the failure mode that prevented completion",
            ]
        )

    def _build_l3(self, reasons: list[str]) -> str:
        bullets = [f"- {reason}" for reason in reasons] or ["- No explicit reasons recorded."]
        return "\n".join(
            [
                "# Escalation L3",
                "",
                "Busywork was detected. Cosmetic edits do not count as progress.",
                "",
                "## Why This Was Flagged",
                *bullets,
                "",
                "## Required Recovery",
                "- add a new logical increment",
                "- cite concrete evidence or experiment details",
                "- acknowledge what was previously missing",
                "- specify what would falsify your own position",
            ]
        )
