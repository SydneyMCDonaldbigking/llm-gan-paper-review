from __future__ import annotations

from dataclasses import dataclass

from .config import ProviderConfig

try:
    import dspy
except Exception:  # pragma: no cover - optional dependency
    dspy = None


@dataclass
class DSPyResult:
    content: str
    meta: dict


class DSPyUnavailable(RuntimeError):
    pass


class DSPySynthesisAdapter:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def synthesize(self, prompt: str) -> DSPyResult:
        if dspy is None:
            raise DSPyUnavailable("DSPy is not installed.")
        last_error: Exception | None = None
        signature = dspy.Signature("context -> summary").with_instructions(
            "You are a synthesis engine for adversarial paper review. "
            "Produce a unified summary with these exact sections: "
            "Strengths, Weaknesses, Resolved Disputes, Unresolved Risks, Final Recommendation."
        )
        for model_name in self._candidate_models():
            try:
                lm = self._build_lm(model_name)
                dspy.settings.configure(lm=lm)
                predictor = dspy.Predict(signature)
                result = predictor(context=prompt)
                content = getattr(result, "summary", "").strip()
                if not content:
                    raise RuntimeError("DSPy returned an empty synthesis.")
                return DSPyResult(
                    content=content,
                    meta={"mode": "dspy", "provider": self.config.provider, "model": model_name},
                )
            except Exception as exc:  # pragma: no cover - network/runtime path
                last_error = exc
        raise RuntimeError(f"DSPy synthesis failed: {last_error}")

    def _build_lm(self, model_name: str):
        if self.config.provider == "openrouter":
            return dspy.LM(
                f"openai/{model_name}",
                api_key=self.config.api_key,
                api_base=self.config.base_url,
                temperature=0.3,
                cache=False,
            )
        if self.config.provider == "openai":
            return dspy.LM(
                f"openai/{model_name}",
                api_key=self.config.api_key,
                api_base=self.config.base_url,
                temperature=0.3,
                cache=False,
            )
        if self.config.provider == "google":
            return dspy.LM(
                f"gemini/{model_name}",
                api_key=self.config.api_key,
                temperature=0.3,
                cache=False,
            )
        raise DSPyUnavailable(f"DSPy provider mapping not implemented for {self.config.provider}")

    def _candidate_models(self) -> list[str]:
        normalized = self.config.model.split("/", 1)[-1] if self.config.model else ""
        candidates = ["gpt-3.5-turbo", "gpt-4o-mini"] if self.config.provider in {"openrouter", "openai"} else []
        candidates.append(self.config.model)
        candidates.extend(self.config.preferred_models or [])
        candidates.extend(self.config.fallback_models or [])
        candidates.append(normalized)
        deduped: list[str] = []
        for model_name in candidates:
            if model_name and model_name not in deduped:
                deduped.append(model_name)
        return deduped


class DSPyIssueAdapter:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def refine_canonical_issues(self, canonical_issues: list[dict]) -> list[dict]:
        if not canonical_issues:
            return canonical_issues
        if dspy is None:
            raise DSPyUnavailable("DSPy is not installed.")
        prompt_lines = [
            "Refine these canonical paper-review issues.",
            "For each issue, return one line in this exact format:",
            "canonical_id|||clean_title|||category|||required_response",
            "Use short clean titles, keep categories compact, and make required_response actionable.",
            "",
        ]
        for issue in canonical_issues[:8]:
            prompt_lines.extend(
                [
                    f"{issue['canonical_id']} | status={issue['status']} | category={issue.get('category', 'other')}",
                    f"title={issue['title']}",
                    f"critique={issue['critique_point'][:260]}",
                    f"rebuttal={issue['rebuttal_point'][:260]}",
                    f"history={self._format_history(issue.get('history', []))}",
                    "",
                ]
            )
        last_error: Exception | None = None
        signature = dspy.Signature("context -> summary").with_instructions(
            "Refine canonical review issues and produce concise issue-management lines."
        )
        for model_name in self._candidate_models():
            try:
                lm = self._build_lm(model_name)
                dspy.settings.configure(lm=lm)
                predictor = dspy.Predict(signature)
                result = predictor(context="\n".join(prompt_lines))
                content = getattr(result, "summary", "").strip()
                if not content:
                    raise RuntimeError("DSPy returned empty issue refinement output.")
                return self._apply_refinements(canonical_issues, content)
            except Exception as exc:  # pragma: no cover - runtime/network path
                last_error = exc
        raise RuntimeError(f"DSPy issue refinement failed: {last_error}")

    def _apply_refinements(self, canonical_issues: list[dict], content: str) -> list[dict]:
        refinements: dict[str, dict] = {}
        for line in content.splitlines():
            if "|||" not in line:
                continue
            parts = [part.strip() for part in line.split("|||")]
            if len(parts) < 4:
                continue
            canonical_id, title, category, required_response = parts[:4]
            refinements[canonical_id] = {
                "title": title,
                "category": category.lower().replace(" ", "_"),
                "required_response": required_response,
            }
        if not refinements:
            raise RuntimeError("DSPy issue refinement output could not be parsed.")
        updated: list[dict] = []
        for issue in canonical_issues:
            patch = refinements.get(issue["canonical_id"])
            if patch:
                issue = {**issue, **patch}
            updated.append(issue)
        return updated

    def _build_lm(self, model_name: str):
        if self.config.provider == "openrouter":
            return dspy.LM(
                f"openai/{model_name}",
                api_key=self.config.api_key,
                api_base=self.config.base_url,
                temperature=0.2,
                cache=False,
            )
        if self.config.provider == "openai":
            return dspy.LM(
                f"openai/{model_name}",
                api_key=self.config.api_key,
                api_base=self.config.base_url,
                temperature=0.2,
                cache=False,
            )
        raise DSPyUnavailable(f"DSPy issue refinement is not configured for provider {self.config.provider}")

    def _candidate_models(self) -> list[str]:
        normalized = self.config.model.split("/", 1)[-1] if self.config.model else ""
        candidates = ["gpt-3.5-turbo", "gpt-4o-mini"] if self.config.provider in {"openrouter", "openai"} else []
        candidates.append(self.config.model)
        candidates.extend(self.config.preferred_models or [])
        candidates.extend(self.config.fallback_models or [])
        candidates.append(normalized)
        deduped: list[str] = []
        for model_name in candidates:
            if model_name and model_name not in deduped:
                deduped.append(model_name)
        return deduped

    def _format_history(self, history: list[dict]) -> str:
        if not history:
            return "no-history"
        return "; ".join(f"{entry['round']}:{entry['status']}" for entry in history)


class DSPyPUAAdapter:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def build_interrogation(self, level: str, target_agent: str, reason: str, diff_reasons: list[str]) -> str:
        if dspy is None:
            raise DSPyUnavailable("DSPy is not installed.")
        prompt = "\n".join(
            [
                f"Level: {level}",
                f"Target: {target_agent}",
                f"Reason: {reason}",
                "Diff reasons:",
                *[f"- {item}" for item in diff_reasons],
                "",
                "Write a terse escalation note with these sections:",
                "Title, Why This Was Flagged, Required Recovery.",
                "Keep it strict and operational.",
            ]
        )
        signature = dspy.Signature("context -> summary").with_instructions(
            "Write an escalation interrogation for a degraded adversarial review round."
        )
        last_error: Exception | None = None
        for model_name in self._candidate_models():
            try:
                lm = self._build_lm(model_name)
                dspy.settings.configure(lm=lm)
                predictor = dspy.Predict(signature)
                result = predictor(context=prompt)
                content = getattr(result, "summary", "").strip()
                if not content:
                    raise RuntimeError("DSPy returned empty interrogation.")
                return content
            except Exception as exc:  # pragma: no cover
                last_error = exc
        raise RuntimeError(f"DSPy PUA failed: {last_error}")

    def _build_lm(self, model_name: str):
        if self.config.provider in {"openrouter", "openai"}:
            return dspy.LM(
                f"openai/{model_name}",
                api_key=self.config.api_key,
                api_base=self.config.base_url,
                temperature=0.2,
                cache=False,
            )
        raise DSPyUnavailable(f"DSPy PUA is not configured for provider {self.config.provider}")

    def _candidate_models(self) -> list[str]:
        normalized = self.config.model.split("/", 1)[-1] if self.config.model else ""
        candidates = ["gpt-3.5-turbo", "gpt-4o-mini"] if self.config.provider in {"openrouter", "openai"} else []
        candidates.append(self.config.model)
        candidates.extend(self.config.preferred_models or [])
        candidates.extend(self.config.fallback_models or [])
        candidates.append(normalized)
        deduped: list[str] = []
        for model_name in candidates:
            if model_name and model_name not in deduped:
                deduped.append(model_name)
        return deduped


class DSPyJudgeAdapter:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def summarize(self, review_mode: str, raw_report: str, scorecard: dict) -> str:
        if dspy is None:
            raise DSPyUnavailable("DSPy is not installed.")
        prompt = "\n".join(
            [
                f"Review mode: {review_mode}",
                f"Confidence: {scorecard.get('confidence')}",
                f"Checks: {scorecard.get('checks')}",
                f"Claim alignment: {scorecard.get('claim_alignment', {})}",
                f"Metric alignment: {scorecard.get('metric_alignment', {})}",
                "",
                "Rewrite the judge report into these sections:",
                "Judge Verdict, Verified Signals, Remaining Gaps.",
                "Be concise and grounded in the scorecard.",
                "",
                "Raw report:",
                raw_report[:4000],
            ]
        )
        signature = dspy.Signature("context -> summary").with_instructions(
            "Rewrite a judge report into a concise structured verifier summary."
        )
        last_error: Exception | None = None
        for model_name in self._candidate_models():
            try:
                lm = self._build_lm(model_name)
                dspy.settings.configure(lm=lm)
                predictor = dspy.Predict(signature)
                result = predictor(context=prompt)
                content = getattr(result, "summary", "").strip()
                if not content:
                    raise RuntimeError("DSPy returned empty judge summary.")
                return content
            except Exception as exc:  # pragma: no cover
                last_error = exc
        raise RuntimeError(f"DSPy judge summary failed: {last_error}")

    def _build_lm(self, model_name: str):
        if self.config.provider in {"openrouter", "openai"}:
            return dspy.LM(
                f"openai/{model_name}",
                api_key=self.config.api_key,
                api_base=self.config.base_url,
                temperature=0.2,
                cache=False,
            )
        raise DSPyUnavailable(f"DSPy judge summary is not configured for provider {self.config.provider}")

    def _candidate_models(self) -> list[str]:
        normalized = self.config.model.split("/", 1)[-1] if self.config.model else ""
        candidates = ["gpt-3.5-turbo", "gpt-4o-mini"] if self.config.provider in {"openrouter", "openai"} else []
        candidates.append(self.config.model)
        candidates.extend(self.config.preferred_models or [])
        candidates.extend(self.config.fallback_models or [])
        candidates.append(normalized)
        deduped: list[str] = []
        for model_name in candidates:
            if model_name and model_name not in deduped:
                deduped.append(model_name)
        return deduped


class DSPyDebateAdapter:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def critique_plan(self, paper_title: str, history_summary: str, canonical_context: str) -> str:
        return self._generate(
            "\n".join(
                [
                    f"Paper title: {paper_title}",
                    "",
                    "Build a short critic plan.",
                    "Return 3-5 bullets covering the strongest attack angles for the next round.",
                    "",
                    "History:",
                    history_summary[:1200],
                    "",
                    "Canonical context:",
                    canonical_context[:1200],
                ]
            ),
            "Produce a concise critic attack plan for the next review round.",
        )

    def rebuttal_plan(self, critique: str, history_summary: str, checklist: str) -> str:
        return self._generate(
            "\n".join(
                [
                    "Build a short defender plan.",
                    "Return 3-5 bullets covering what must be answered next.",
                    "",
                    "Critique:",
                    critique[:1600],
                    "",
                    "History:",
                    history_summary[:1000],
                    "",
                    "Checklist:",
                    checklist[:1200],
                ]
            ),
            "Produce a concise defender recovery plan for the next rebuttal.",
        )

    def draft_critique(self, paper_title: str, context: str, history_summary: str, canonical_context: str) -> str:
        return self._generate(
            "\n".join(
                [
                    f"Paper title: {paper_title}",
                    "",
                    "Write a concise adversarial critique with these sections:",
                    "Strongest Concerns, Evidence Risks, Preliminary Verdict.",
                    "",
                    "Context:",
                    context[:2500],
                    "",
                    "History:",
                    history_summary[:1200],
                    "",
                    "Canonical context:",
                    canonical_context[:1200],
                ]
            ),
            "Write a concise but substantive critic round for paper review.",
        )

    def draft_rebuttal(self, paper_title: str, critique: str, history_summary: str, checklist: str) -> str:
        return self._generate(
            "\n".join(
                [
                    f"Paper title: {paper_title}",
                    "",
                    "Write a concise rebuttal with these sections:",
                    "Defense, Evidence Discussion, Remaining Risk.",
                    "",
                    "Critique:",
                    critique[:2200],
                    "",
                    "History:",
                    history_summary[:1200],
                    "",
                    "Checklist:",
                    checklist[:1200],
                ]
            ),
            "Write a concise but substantive defender round for paper review.",
        )

    def escalation_plan(self, level: str, interrogation: str, critique: str, rebuttal: str) -> str:
        return self._generate(
            "\n".join(
                [
                    f"Escalation level: {level}",
                    "",
                    "Build a short escalation recovery plan.",
                    "Return 3-5 bullets describing what the recovery response must do next.",
                    "",
                    "Interrogation:",
                    interrogation[:1200],
                    "",
                    "Critique:",
                    critique[:1200],
                    "",
                    "Rebuttal:",
                    rebuttal[:1200],
                ]
            ),
            "Produce a concise escalation recovery plan.",
        )

    def classify_busywork(self, diff_text: str, content: str) -> tuple[str, list[str]]:
        text = self._generate(
            "\n".join(
                [
                    "Classify whether this rebuttal is busywork.",
                    "Return one line in this format:",
                    "verdict|||reason1; reason2",
                    "",
                    "Diff:",
                    diff_text[:1500],
                    "",
                    "Content:",
                    content[:1800],
                ]
            ),
            "Classify a rebuttal as substantial or busywork.",
        )
        first = text.splitlines()[0] if text else ""
        if "|||" not in first:
            raise RuntimeError("DSPy busywork output was not parseable.")
        verdict, reason_blob = [part.strip() for part in first.split("|||", 1)]
        reasons = [item.strip() for item in reason_blob.split(";") if item.strip()]
        return verdict.lower(), reasons

    def classify_issue_status(self, critique_point: str, rebuttal_point: str, pua_level: str) -> str:
        text = self._generate(
            "\n".join(
                [
                    "Classify issue status as one of:",
                    "open, responded, partially_resolved, escalated",
                    "",
                    f"pua_level={pua_level}",
                    f"critique={critique_point[:900]}",
                    f"rebuttal={rebuttal_point[:900]}",
                    "",
                    "Return one word only.",
                ]
            ),
            "Classify review issue status.",
        )
        first = text.splitlines()[0].strip().lower()
        if first not in {"open", "responded", "partially_resolved", "escalated"}:
            raise RuntimeError("DSPy issue status output was not parseable.")
        return first

    def recommendation(self, summary: str) -> str:
        text = self._generate(
            "\n".join(
                [
                    "Choose one recommendation from:",
                    "accept, weak_accept, borderline, weak_reject, reject",
                    "",
                    "Use the following scorecard summary and risk profile:",
                    summary[:2200],
                    "",
                    "Return one label only.",
                ]
            ),
            "Choose a final paper recommendation label.",
        )
        first = text.splitlines()[0].strip().lower()
        if first not in {"accept", "weak_accept", "borderline", "weak_reject", "reject"}:
            raise RuntimeError("DSPy recommendation output was not parseable.")
        return first

    def _generate(self, prompt: str, instructions: str) -> str:
        if dspy is None:
            raise DSPyUnavailable("DSPy is not installed.")
        signature = dspy.Signature("context -> summary").with_instructions(instructions)
        last_error: Exception | None = None
        for model_name in self._candidate_models():
            try:
                lm = self._build_lm(model_name)
                dspy.settings.configure(lm=lm)
                predictor = dspy.Predict(signature)
                result = predictor(context=prompt)
                content = getattr(result, "summary", "").strip()
                if not content:
                    raise RuntimeError("DSPy returned empty planning output.")
                return content
            except Exception as exc:  # pragma: no cover
                last_error = exc
        raise RuntimeError(f"DSPy debate adapter failed: {last_error}")

    def _build_lm(self, model_name: str):
        if self.config.provider in {"openrouter", "openai"}:
            return dspy.LM(
                f"openai/{model_name}",
                api_key=self.config.api_key,
                api_base=self.config.base_url,
                temperature=0.2,
                cache=False,
            )
        raise DSPyUnavailable(f"DSPy debate adapter is not configured for provider {self.config.provider}")

    def _candidate_models(self) -> list[str]:
        normalized = self.config.model.split("/", 1)[-1] if self.config.model else ""
        candidates = ["gpt-3.5-turbo", "gpt-4o-mini"] if self.config.provider in {"openrouter", "openai"} else []
        candidates.append(self.config.model)
        candidates.extend(self.config.preferred_models or [])
        candidates.extend(self.config.fallback_models or [])
        candidates.append(normalized)
        deduped: list[str] = []
        for model_name in candidates:
            if model_name and model_name not in deduped:
                deduped.append(model_name)
        return deduped
