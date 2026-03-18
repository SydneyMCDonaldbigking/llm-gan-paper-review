from __future__ import annotations

import re
from dataclasses import dataclass

from .config import ProviderConfig
from .dspy_adapter import DSPyDebateAdapter, DSPyIssueAdapter


@dataclass
class IssueTrackerResult:
    issues: list[dict]
    canonical_issues: list[dict]
    summary_text: str


class IssueTracker:
    def __init__(self, provider_config: ProviderConfig | None = None) -> None:
        self.dspy = DSPyIssueAdapter(provider_config) if provider_config else None
        self.dspy_status = DSPyDebateAdapter(provider_config) if provider_config else None

    def build(self, round_results: list[dict]) -> IssueTrackerResult:
        issues: list[dict] = []
        for result in round_results:
            round_id = result["round_id"]
            critique_points = self._extract_points(result["critique"])
            rebuttal_points = self._extract_points(result["rebuttal"])
            limit = max(len(critique_points), len(rebuttal_points), 1)
            for index in range(limit):
                critique_point = critique_points[index] if index < len(critique_points) else ""
                rebuttal_point = rebuttal_points[index] if index < len(rebuttal_points) else ""
                issue_id = f"{round_id}-{index + 1:02d}"
                status = self._classify_status(rebuttal_point, result)
                issues.append(
                    {
                        "issue_id": issue_id,
                        "round": round_id,
                        "title": self._make_title(critique_point, index),
                        "critique_point": critique_point,
                        "rebuttal_point": rebuttal_point,
                        "status": status,
                        "busywork_verdict": result["diff_analysis"].verdict,
                        "pua_level": result["pua_result"].level,
                    }
                )
            issues.extend(self._judge_issues(result))
        canonical_issues = self._merge_canonical(issues)
        if self.dspy:
            try:
                canonical_issues = self.dspy.refine_canonical_issues(canonical_issues)
            except Exception:
                pass
        return IssueTrackerResult(
            issues=issues,
            canonical_issues=canonical_issues,
            summary_text=self._build_summary(issues, canonical_issues),
        )

    def _extract_points(self, text: str) -> list[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        points = [line for line in lines if re.match(r"^(\d+\.|[-*])\s*", line) and not self._is_noise_point(line)]
        if points:
            return points[:6]
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        return [sentence.strip() for sentence in sentences[:4] if sentence.strip() and not self._is_noise_point(sentence)]

    def _make_title(self, critique_point: str, index: int) -> str:
        cleaned = re.sub(r"^(\d+\.|[-*])\s*", "", critique_point).strip()
        cleaned = re.sub(r"^#+\s*", "", cleaned)
        cleaned = cleaned.strip("-*# :")
        if cleaned in {"", "-", "--", "---"}:
            return f"Issue {index + 1}"
        return cleaned[:100] if cleaned else f"Issue {index + 1}"

    def _is_noise_point(self, text: str) -> bool:
        cleaned = text.strip()
        stripped = re.sub(r"^(\d+\.|[-*])\s*", "", cleaned).strip()
        stripped = stripped.strip("*_`# :")
        if stripped in {"", "-", "--", "---"}:
            return True
        if re.fullmatch(r"#+", stripped):
            return True
        if re.match(r"^(defense|evidence discussion|remaining risk)\s*:?$", stripped, flags=re.IGNORECASE):
            return True
        return False

    def _classify_status(self, rebuttal_point: str, result: dict) -> str:
        if self.dspy_status:
            try:
                return self.dspy_status.classify_issue_status(
                    result.get("critique", ""),
                    rebuttal_point,
                    result["pua_result"].level,
                )
            except Exception:
                pass
        if result["pua_result"].level != "NONE":
            return "escalated"
        lowered = rebuttal_point.lower()
        if any(token in lowered for token in ["however", "but", "remaining risk", "uncertain"]):
            return "partially_resolved"
        if rebuttal_point:
            return "responded"
        return "open"

    def _judge_issues(self, result: dict) -> list[dict]:
        judge_scorecard = result.get("judge_scorecard", {})
        claim_alignment = judge_scorecard.get("claim_alignment", {})
        alignments = claim_alignment.get("alignments", [])
        derived: list[dict] = []
        for index, alignment in enumerate(alignments, start=1):
            if alignment.get("supported", True):
                continue
            claim = alignment.get("claim", "").strip()
            if not claim:
                continue
            reason = alignment.get("unsupported_reason", "missing_table_support")
            derived.append(
                {
                    "issue_id": f"{result['round_id']}-J{index:02d}",
                    "round": result["round_id"],
                    "title": self._make_judge_title(claim, reason),
                    "critique_point": f"Judge flagged unsupported claim: {claim}",
                    "rebuttal_point": alignment.get("best_evidence", ""),
                    "status": "open",
                    "busywork_verdict": result["diff_analysis"].verdict,
                    "pua_level": result["pua_result"].level,
                }
            )
        return derived

    def _merge_canonical(self, issues: list[dict]) -> list[dict]:
        groups: list[dict] = []
        for issue in issues:
            target_group = self._find_matching_group(issue, groups)
            if target_group is None:
                target_group = {
                    "canonical_id": f"C{len(groups) + 1:03d}",
                    "title": issue["title"],
                    "rounds": [issue["round"]],
                    "source_issue_ids": [issue["issue_id"]],
                    "statuses": [issue["status"]],
                    "critique_points": [issue["critique_point"]],
                    "rebuttal_points": [issue["rebuttal_point"]],
                    "keywords": self._keywords(issue["title"], issue["critique_point"]),
                    "categories": [self._categorize(issue["title"], issue["critique_point"])],
                    "history": [self._history_entry(issue)],
                }
                groups.append(target_group)
            else:
                target_group["rounds"].append(issue["round"])
                target_group["source_issue_ids"].append(issue["issue_id"])
                target_group["statuses"].append(issue["status"])
                target_group["critique_points"].append(issue["critique_point"])
                target_group["rebuttal_points"].append(issue["rebuttal_point"])
                target_group["keywords"].update(self._keywords(issue["title"], issue["critique_point"]))
                target_group["categories"].append(self._categorize(issue["title"], issue["critique_point"]))
                target_group["history"].append(self._history_entry(issue))
        canonical_issues = []
        for item in groups:
            canonical_issues.append(
                {
                    "canonical_id": item["canonical_id"],
                    "title": item["title"],
                    "rounds": sorted(set(item["rounds"])),
                    "source_issue_ids": item["source_issue_ids"],
                    "status": self._aggregate_status(item["statuses"]),
                    "category": self._aggregate_category(item["categories"]),
                    "history": sorted(item["history"], key=lambda entry: (entry["round"], entry["issue_id"])),
                    "critique_point": max(item["critique_points"], key=len),
                    "rebuttal_point": max(item["rebuttal_points"], key=len) if any(item["rebuttal_points"]) else "",
                }
            )
        canonical_issues.sort(key=lambda issue: issue["canonical_id"])
        return canonical_issues

    def _aggregate_status(self, statuses: list[str]) -> str:
        if "escalated" in statuses:
            return "escalated"
        if "partially_resolved" in statuses:
            return "partially_resolved"
        if all(status == "responded" for status in statuses):
            return "responded"
        if "open" in statuses:
            return "open"
        return statuses[0]

    def _find_matching_group(self, issue: dict, groups: list[dict]) -> dict | None:
        issue_keywords = self._keywords(issue["title"], issue["critique_point"])
        issue_category = self._categorize(issue["title"], issue["critique_point"])
        best_group = None
        best_score = 0.0
        for group in groups:
            category_match = issue_category == self._aggregate_category(group["categories"])
            overlap = self._jaccard(issue_keywords, group["keywords"])
            if category_match:
                overlap += 0.2
            if overlap > best_score:
                best_score = overlap
                best_group = group
        if best_group and best_score >= 0.48:
            return best_group
        return None

    def _keywords(self, title: str, critique_point: str) -> set[str]:
        text = f"{title} {critique_point}".lower()
        tokens = re.findall(r"[a-z0-9]+", text)
        stopwords = {
            "the", "and", "for", "with", "that", "this", "from", "into", "over", "lack", "limited",
            "paper", "authors", "their", "they", "these", "those", "while", "more", "less", "very",
            "using", "used", "does", "make", "made", "being", "have", "has", "had",
        }
        return {token for token in tokens if token not in stopwords and len(token) > 2}

    def _jaccard(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        intersection = len(left & right)
        union = len(left | right)
        return intersection / union if union else 0.0

    def _categorize(self, title: str, critique_point: str) -> str:
        text = f"{title} {critique_point}".lower()
        category_rules = {
            "evidence": ["evidence", "substantiat", "comparative", "experiment", "ablation", "validation", "missing_table_support", "reference_not_grounded"],
            "novelty": ["novelty", "novel", "incremental", "baseline"],
            "reproducibility": ["reproducibility", "hyperparameter", "training", "implementation", "detail"],
            "embedding": ["embedding", "sentiment140", "task-specific", "general-purpose"],
            "preprocessing": ["hashtag", "truncation", "preprocessing", "tweet length", "dictionary"],
            "metrics": ["f1", "recall", "metric", "rank", "performance", "missing_rank_support", "missing_metric_support", "metric_mismatch_risk"],
        }
        for category, patterns in category_rules.items():
            if any(pattern in text for pattern in patterns):
                return category
        return "other"

    def _make_judge_title(self, claim: str, reason: str) -> str:
        cleaned = re.sub(r"^(table|figure)\s+\d+\s+shows?\s+", "", claim, flags=re.IGNORECASE).strip()
        if len(cleaned) > 92:
            cleaned = f"{cleaned[:89]}..."
        reason_label = {
            "missing_rank_support": "Unsupported ranking claim",
            "partial_metric_support": "Metric claim only partially supported",
            "missing_metric_support": "Metric claim lacks metric support",
            "metric_mismatch_risk": "Metric claim has mismatch risk",
            "reference_not_grounded": "Reference claim is not grounded",
            "missing_table_support": "Unsupported claim",
        }.get(reason, "Unsupported claim")
        return f"{reason_label}: {cleaned}"

    def _aggregate_category(self, categories: list[str]) -> str:
        counts: dict[str, int] = {}
        for category in categories:
            counts[category] = counts.get(category, 0) + 1
        return max(counts, key=counts.get)

    def _build_summary(self, issues: list[dict], canonical_issues: list[dict]) -> str:
        lines = ["Issue Summary", "", "Canonical Issues"]
        for issue in canonical_issues:
            lines.extend(
                [
                    "",
                    f"{issue['canonical_id']} | {issue['status']} | category={issue['category']} | rounds={','.join(issue['rounds'])} | {issue['title']}",
                    f"Critique: {issue['critique_point'][:220]}",
                    f"Rebuttal: {issue['rebuttal_point'][:220]}",
                    f"Required response: {(issue.get('required_response') or 'Provide new evidence, a concession, or a direct rebuttal.')[:220]}",
                    f"History: {self._format_history(issue['history'])}",
                ]
            )
        lines.extend(["", "Round-Level Issues"])
        for issue in issues:
            lines.extend(
                [
                    "",
                    f"{issue['issue_id']} | {issue['status']} | {issue['title']}",
                    f"Critique: {issue['critique_point'][:220]}",
                    f"Rebuttal: {issue['rebuttal_point'][:220]}",
                ]
            )
        return "\n".join(lines)

    def _history_entry(self, issue: dict) -> dict:
        return {
            "round": issue["round"],
            "issue_id": issue["issue_id"],
            "status": issue["status"],
            "busywork_verdict": issue["busywork_verdict"],
            "pua_level": issue["pua_level"],
            "rebuttal_excerpt": issue["rebuttal_point"][:180],
        }

    def _format_history(self, history: list[dict]) -> str:
        return "; ".join(
            f"{entry['round']}:{entry['status']}/pua={entry['pua_level']}/busywork={entry['busywork_verdict']}"
            for entry in history
        )
