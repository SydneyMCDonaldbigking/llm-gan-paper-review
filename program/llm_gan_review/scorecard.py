from __future__ import annotations

from .config import ProviderConfig
from .dspy_adapter import DSPyDebateAdapter


class FinalScorecardBuilder:
    def __init__(self, provider_config: ProviderConfig | None = None) -> None:
        self.dspy = DSPyDebateAdapter(provider_config) if provider_config else None

    def build(self, round_results: list[dict], canonical_issues: list[dict]) -> dict:
        total = len(canonical_issues) or 1
        unresolved = sum(1 for issue in canonical_issues if issue["status"] in {"open", "escalated", "partially_resolved"})
        responded = sum(1 for issue in canonical_issues if issue["status"] == "responded")
        escalated = sum(1 for issue in canonical_issues if issue["status"] == "escalated")
        persistent = sum(1 for issue in canonical_issues if len(issue.get("history", [])) > 1)
        judge_confidence = self._judge_confidence(round_results)
        evidence_checks = self._evidence_checks(round_results)
        latest = round_results[-1]["judge_scorecard"]
        review_mode = latest["artifact_mode"]
        evidence_penalty = 1 if evidence_checks.get("suspicious_table_patterns_found") else 0
        code_bonus = 1 if review_mode == "code" and latest["checks"].get("command_succeeded") else 0

        scorecard = {
            "dimensions": {
                "novelty": self._score_dimension(canonical_issues, positive_categories={"novelty"}, penalty_categories={"evidence", "metrics"}),
                "technical_soundness": self._score_dimension(canonical_issues, positive_categories={"evidence"}, penalty_categories={"evidence", "reproducibility"}),
                "evidence_quality": max(1, min(5, 5 - unresolved - evidence_penalty + code_bonus)),
                "clarity": self._score_dimension(canonical_issues, positive_categories={"metrics"}, penalty_categories={"preprocessing", "embedding"}),
                "reproducibility": self._reproducibility_score(canonical_issues, latest),
            },
            "issue_counts": {
                "canonical_total": total,
                "responded": responded,
                "unresolved_or_partial": unresolved,
                "escalated": escalated,
                "persistent_across_rounds": persistent,
            },
            "judge": judge_confidence,
            "evidence_checks": evidence_checks,
            "review_mode": review_mode,
        }
        overall = round(sum(scorecard["dimensions"].values()) / len(scorecard["dimensions"]), 2)
        scorecard["overall_score"] = overall
        scorecard["recommendation"] = self._recommend(overall, escalated, unresolved)
        if self.dspy:
            try:
                scorecard["recommendation"] = self.dspy.recommendation(self._recommendation_summary(scorecard, canonical_issues))
                scorecard["recommendation_source"] = "dspy"
            except Exception:
                scorecard["recommendation_source"] = "rule"
        else:
            scorecard["recommendation_source"] = "rule"
        return scorecard

    def _score_dimension(self, issues: list[dict], positive_categories: set[str], penalty_categories: set[str]) -> int:
        base = 3
        positive_hits = sum(1 for issue in issues if issue["category"] in positive_categories and issue["status"] == "responded")
        penalty_hits = sum(1 for issue in issues if issue["category"] in penalty_categories and issue["status"] != "responded")
        score = base + min(2, positive_hits) - min(2, penalty_hits)
        return max(1, min(5, score))

    def _judge_confidence(self, round_results: list[dict]) -> dict:
        confidences = [result["judge_scorecard"]["confidence"] for result in round_results]
        return {
            "round_confidences": confidences,
            "final_confidence": "preliminary" if "preliminary" in confidences else "stable",
        }

    def _evidence_checks(self, round_results: list[dict]) -> dict:
        latest = round_results[-1]["judge_scorecard"]
        checks = dict(latest["checks"])
        claim_alignment = latest.get("claim_alignment", {})
        breakdown = {
            "missing_table_support": 0,
            "missing_rank_support": 0,
            "partial_metric_support": 0,
            "missing_metric_support": 0,
            "metric_mismatch_risk": 0,
            "reference_not_grounded": 0,
        }
        for item in claim_alignment.get("alignments", []):
            if item.get("supported", True):
                continue
            reason = item.get("unsupported_reason", "missing_table_support")
            breakdown[reason] = breakdown.get(reason, 0) + 1
        checks["unsupported_claim_breakdown"] = breakdown
        return checks

    def _recommend(self, overall: float, escalated: int, unresolved: int) -> str:
        if escalated > 0:
            return "weak_reject"
        if overall >= 4 and unresolved <= 1:
            return "weak_accept"
        if overall >= 3:
            return "borderline"
        return "weak_reject"

    def _reproducibility_score(self, issues: list[dict], latest_judge: dict) -> int:
        if latest_judge["artifact_mode"] == "code":
            if latest_judge["checks"].get("command_succeeded"):
                return 4
            if latest_judge["checks"].get("command_executed"):
                return 2
            return 1
        return self._score_dimension(
            issues,
            positive_categories={"reproducibility"},
            penalty_categories={"reproducibility", "embedding"},
        )

    def _recommendation_summary(self, scorecard: dict, canonical_issues: list[dict]) -> str:
        unresolved = [issue for issue in canonical_issues if issue["status"] in {"open", "escalated", "partially_resolved"}]
        lines = [
            f"overall_score={scorecard['overall_score']}",
            f"dimensions={scorecard['dimensions']}",
            f"issue_counts={scorecard['issue_counts']}",
            f"judge={scorecard['judge']}",
            f"evidence_checks={scorecard['evidence_checks']}",
            "unresolved_titles:",
        ]
        lines.extend(f"- {issue['title']}" for issue in unresolved[:8])
        return "\n".join(lines)
