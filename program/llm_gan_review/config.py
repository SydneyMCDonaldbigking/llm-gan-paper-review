from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProviderConfig:
    provider: str
    model: str
    api_key: str
    base_url: str
    enabled: bool = True
    preferred_models: list[str] | None = None
    fallback_models: list[str] | None = None


@dataclass
class AppConfig:
    gemini: ProviderConfig
    gpt: ProviderConfig

    @classmethod
    def load(cls, config_path: Path) -> "AppConfig":
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return cls(
            gemini=ProviderConfig(**data["gemini"]),
            gpt=ProviderConfig(**data["gpt"]),
        )
