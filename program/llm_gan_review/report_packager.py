from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import ProviderConfig
from .llm_clients import BaseLLMClient


@dataclass
class TranslationArtifact:
    language_code: str
    language_name: str
    path: str
    mode: str


class FinalReportPackager:
    def __init__(self, workspace_dir: Path, client: BaseLLMClient, provider_config: ProviderConfig) -> None:
        self.workspace_dir = workspace_dir
        self.client = client
        self.provider_config = provider_config

    def package(self, report_text: str, paper_title: str) -> dict:
        output_root = self.workspace_dir / "final_report"
        output_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        task_dir = output_root / f"final_{timestamp}"
        counter = 1
        while task_dir.exists():
            counter += 1
            task_dir = output_root / f"final_{timestamp}_{counter:02d}"
        task_dir.mkdir(parents=True, exist_ok=True)
        paper_dir = task_dir / self._safe_name(paper_title)
        paper_dir.mkdir(parents=True, exist_ok=True)

        final_report_path = paper_dir / "FINAL_REPORT.md"
        final_report_path.write_text(report_text, encoding="utf-8")

        artifacts: list[TranslationArtifact] = []
        for code, language in [("CN", "Simplified Chinese"), ("JP", "Japanese"), ("EG", "English")]:
            translated, mode = self._translate(report_text, language, preserve_english=report_text)
            path = paper_dir / f"FINAL_REPORT_{code}.md"
            path.write_text(translated, encoding="utf-8")
            artifacts.append(
                TranslationArtifact(
                    language_code=code,
                    language_name=language,
                    path=str(path),
                    mode=mode,
                )
            )

        literature_review_en, literature_mode = self._generate_literature_review(report_text, paper_title)
        literature_artifacts: list[TranslationArtifact] = []
        for code, language in [("CN", "Simplified Chinese"), ("JP", "Japanese"), ("EG", "English")]:
            translated, mode = self._translate(literature_review_en, language, preserve_english=literature_review_en)
            if code == "EG":
                mode = literature_mode
            path = paper_dir / f"LITERATURE_REVIEW_{code}.md"
            path.write_text(translated, encoding="utf-8")
            literature_artifacts.append(
                TranslationArtifact(
                    language_code=code,
                    language_name=language,
                    path=str(path),
                    mode=mode,
                )
            )
        return {
            "task_dir": str(task_dir),
            "bundle_dir": str(paper_dir),
            "paper_dir": str(paper_dir),
            "paper_title": paper_title,
            "final_report_path": str(final_report_path),
            "translations": [artifact.__dict__ for artifact in artifacts],
            "literature_reviews": [artifact.__dict__ for artifact in literature_artifacts],
        }

    def _translate(self, report_text: str, target_language: str, preserve_english: str | None = None) -> tuple[str, str]:
        if target_language == "English" and preserve_english is not None:
            return preserve_english, "source"
        prompt = "\n".join(
            [
                f"Target language: {target_language}",
                "Translate the following final paper review report.",
                "Keep the markdown structure, headings, bullets, and code blocks.",
                "Do not summarize. Preserve file names, scores, labels, and recommendation names where sensible.",
                "",
                report_text,
            ]
        )
        try:
            response = self.client.generate(
                system_prompt="You are a precise technical translator for software and research review reports.",
                user_prompt=prompt,
            )
            return response.content, "api"
        except Exception:
            return self._fallback_translation(report_text, target_language), "fallback"

    def _generate_literature_review(self, report_text: str, paper_title: str) -> tuple[str, str]:
        prompt = "\n".join(
            [
                f"Paper title: {paper_title}",
                "Write a concise literature-review style synthesis based only on the final review report below.",
                "Use markdown.",
                "Include these sections exactly:",
                "1. Research Focus",
                "2. Main Contributions",
                "3. Strengths",
                "4. Weaknesses",
                "5. Evidence and Evaluation Notes",
                "6. Overall Positioning",
                "Do not invent new experiments or claims beyond the report.",
                "",
                report_text,
            ]
        )
        try:
            response = self.client.generate(
                system_prompt="You are a precise research writing assistant producing literature-review style summaries.",
                user_prompt=prompt,
            )
            return response.content, "api"
        except Exception:
            fallback = "\n".join(
                [
                    "# Literature Review",
                    "",
                    "## Research Focus",
                    f"- {paper_title}",
                    "",
                    "## Main Contributions",
                    "- Derived from the final review report.",
                    "",
                    "## Strengths",
                    "- See the final review report for structured strengths.",
                    "",
                    "## Weaknesses",
                    "- See the final review report for structured weaknesses and unresolved risks.",
                    "",
                    "## Evidence and Evaluation Notes",
                    "- This fallback keeps the review-grounded summary without inventing new claims.",
                    "",
                    "## Overall Positioning",
                    "- The paper should be interpreted in line with the recommendation and evidence gaps recorded in the final report.",
                ]
            )
            return fallback, "fallback"

    def _fallback_translation(self, report_text: str, target_language: str) -> str:
        header = f"# {target_language} Translation Fallback"
        note = (
            "Translation API was unavailable for this language, so the original report is preserved below "
            "to avoid losing deliverables."
        )
        return f"{header}\n\n{note}\n\n{report_text}"

    def _safe_name(self, value: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
        cleaned = cleaned.strip("_")
        return cleaned[:80] or "paper"
