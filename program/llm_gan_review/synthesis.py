from __future__ import annotations

from dataclasses import dataclass

from .llm_clients import BaseLLMClient
from .paper import PaperArtifact
from .config import ProviderConfig
from .dspy_adapter import DSPySynthesisAdapter


@dataclass
class SynthesisResult:
    content: str
    meta: dict


class SynthesisEngine:
    def __init__(self, client: BaseLLMClient, provider_config: ProviderConfig | None = None) -> None:
        self.client = client
        self.dspy = DSPySynthesisAdapter(provider_config) if provider_config else None

    def synthesize(self, paper: PaperArtifact, round_results: list[dict], issues: list[dict]) -> SynthesisResult:
        prompt = self._build_prompt(paper, round_results, issues)
        fallback = self._fallback_synthesis(paper, round_results, issues)
        if self.dspy:
            try:
                result = self.dspy.synthesize(prompt)
                return SynthesisResult(content=result.content, meta=result.meta)
            except Exception as exc:
                dspy_error = str(exc)
            else:
                dspy_error = ""
        try:
            response = self.client.generate(
                system_prompt=(
                    "You are a synthesis engine for adversarial paper review. "
                    "Produce a unified summary with these exact sections: "
                    "Strengths, Weaknesses, Resolved Disputes, Unresolved Risks, Final Recommendation."
                ),
                user_prompt=prompt,
            )
            meta = {"mode": "api", "raw": response.raw}
            if self.dspy:
                meta["dspy_error"] = dspy_error
            return SynthesisResult(content=response.content, meta=meta)
        except Exception as exc:
            error = str(exc)
            if self.dspy:
                error = f"DSPy failed: {dspy_error} | API failed: {error}"
            return SynthesisResult(content=fallback, meta={"mode": "fallback", "error": error})

    def fallback_only(self, paper: PaperArtifact, round_results: list[dict], issues: list[dict], reason: str) -> SynthesisResult:
        fallback = self._fallback_synthesis(paper, round_results, issues)
        return SynthesisResult(content=fallback, meta={"mode": "fallback", "error": reason, "error_type": "provider_blocked"})

    def _build_prompt(self, paper: PaperArtifact, round_results: list[dict], issues: list[dict]) -> str:
        lines = [
            f"Paper title: {paper.title}",
            "",
            "Unify the debate into one concise review summary.",
            "When writing Resolved Disputes and Unresolved Risks, explicitly use issue histories to mention whether a problem persisted across rounds or improved over time.",
            "",
            "Canonical issues:",
        ]
        for issue in issues[:12]:
            lines.extend(
                [
                    f"- [{issue['canonical_id']}] status={issue['status']} category={issue.get('category', 'other')} title={issue['title']}",
                    f"  history={self._format_history(issue.get('history', []))}",
                    f"  critique={issue['critique_point'][:300]}",
                    f"  rebuttal={issue['rebuttal_point'][:300]}",
                ]
            )
        for result in round_results:
            lines.extend(
                [
                    "",
                    f"Round {result['round_id']}:",
                    f"Critique source: {result['critique_meta']['mode']}",
                    f"Defender source: {result['rebuttal_meta']['mode']}",
                    f"Busywork: {result['diff_analysis'].verdict}",
                    f"PUA: {result['pua_result'].level}",
                    f"Critique excerpt: {result['critique'][:1200]}",
                    f"Rebuttal excerpt: {result['rebuttal'][:1200]}",
                    f"Judge summary: {result['judge_report'][:800]}",
                ]
            )
        return "\n".join(lines)

    def _fallback_synthesis(self, paper: PaperArtifact, round_results: list[dict], issues: list[dict]) -> str:
        responded = [issue for issue in issues if issue["status"] in {"responded", "partially_resolved"}]
        unresolved_issues = [issue for issue in issues if issue["status"] in {"open", "escalated", "partially_resolved"}]
        persistent = [issue for issue in issues if len(issue.get("history", [])) > 1]
        strengths = [
            "- The paper presents a concrete task setup and reports benchmark-style evaluation metrics.",
            "- The system description references multiple architectural components rather than a vague high-level idea.",
        ]
        weaknesses = [
            "- Comparative evidence for major design decisions is still thin.",
            "- Reproducibility details remain incomplete at the current extraction depth.",
        ]
        resolved = [f"- {issue['title']} | history={self._format_history(issue.get('history', []))}" for issue in responded[:3]]
        unresolved = [f"- {issue['title']} | history={self._format_history(issue.get('history', []))}" for issue in unresolved_issues[:4]]
        recommendation = "borderline"
        if persistent:
            unresolved.append(
                "- Persistent across rounds: "
                + ", ".join(f"{issue['canonical_id']}" for issue in persistent[:4])
            )
        if any(item["pua_result"].level != "NONE" for item in round_results):
            unresolved.append("- At least one round required escalation, which reduces confidence in the defender's reliability.")
        lines = [
            f"Paper: {paper.title}",
            "",
            "Strengths",
            *strengths,
            "",
            "Weaknesses",
            *weaknesses,
            "",
            "Resolved Disputes",
            *(resolved or ["- No major dispute was fully resolved in fallback synthesis."]),
            "",
            "Unresolved Risks",
            *unresolved,
            "",
            "Final Recommendation",
            f"- {recommendation}",
        ]
        return "\n".join(lines)

    def _format_history(self, history: list[dict]) -> str:
        if not history:
            return "no-history"
        return "; ".join(
            f"{entry['round']}:{entry['status']}/pua={entry['pua_level']}"
            for entry in history
        )
