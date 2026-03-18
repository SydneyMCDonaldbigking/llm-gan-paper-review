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
        bundle_dir = output_root / timestamp
        counter = 1
        while bundle_dir.exists():
            counter += 1
            bundle_dir = output_root / f"{timestamp}_{counter:02d}"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        artifacts: list[TranslationArtifact] = []
        for code, language in [("CN", "Simplified Chinese"), ("JP", "Japanese"), ("EG", "English")]:
            translated, mode = self._translate(report_text, language)
            path = bundle_dir / f"{code}.md"
            path.write_text(translated, encoding="utf-8")
            artifacts.append(
                TranslationArtifact(
                    language_code=code,
                    language_name=language,
                    path=str(path),
                    mode=mode,
                )
            )
        return {
            "bundle_dir": str(bundle_dir),
            "paper_title": paper_title,
            "translations": [artifact.__dict__ for artifact in artifacts],
        }

    def _translate(self, report_text: str, target_language: str) -> tuple[str, str]:
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

    def _fallback_translation(self, report_text: str, target_language: str) -> str:
        header = f"# {target_language} Translation Fallback"
        note = (
            "Translation API was unavailable for this language, so the original report is preserved below "
            "to avoid losing deliverables."
        )
        return f"{header}\n\n{note}\n\n{report_text}"
