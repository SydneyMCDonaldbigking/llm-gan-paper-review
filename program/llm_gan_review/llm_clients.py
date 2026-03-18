from __future__ import annotations

import json
from dataclasses import dataclass

import requests

from .config import ProviderConfig


@dataclass
class LLMResponse:
    content: str
    raw: dict


class BaseLLMClient:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        raise NotImplementedError


def classify_provider_error(error_text: str) -> str:
    normalized = error_text.lower()
    if "quota" in normalized or "insufficient_quota" in normalized:
        return "quota_exhausted"
    if "rate limit" in normalized or "too many requests" in normalized:
        return "rate_limited"
    if "api key" in normalized or "unauthorized" in normalized or "\"code\": 401" in normalized:
        return "auth_error"
    return "generic_error"


class GeminiClient(BaseLLMClient):
    def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        if not self.config.api_key:
            raise RuntimeError("Gemini API key is missing.")
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.4},
        }
        last_error: Exception | None = None
        for model_name in self._candidate_models():
            endpoint = f"{self.config.base_url}/models/{model_name}:generateContent?key={self.config.api_key}"
            response = requests.post(endpoint, json=payload, timeout=120)
            if response.ok:
                data = response.json()
                content = self._extract_text(data)
                return LLMResponse(content=content, raw=data)
            last_error = RuntimeError(f"Gemini model {model_name} failed with {response.status_code}: {response.text[:300]}")
            if response.status_code not in {404, 400, 429}:
                break
        raise last_error or RuntimeError("Gemini request failed without details.")

    def _extract_text(self, data: dict) -> str:
        try:
            candidate = data["candidates"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Gemini response: {json.dumps(data)[:800]}") from exc

        content = candidate.get("content", {})
        parts = content.get("parts", [])
        text_chunks = [part.get("text", "") for part in parts if isinstance(part, dict) and part.get("text")]
        text = "\n".join(text_chunks).strip()
        if text:
            return text

        # Some Gemini responses omit text parts but still carry useful fields.
        for key in ("text", "output_text"):
            value = candidate.get(key) or content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        finish_reason = candidate.get("finishReason", "")
        safety_ratings = candidate.get("safetyRatings", [])
        raise RuntimeError(
            "Unexpected Gemini response: "
            f"{json.dumps(data)[:800]} | "
            f"finishReason={finish_reason} safetyRatings={json.dumps(safety_ratings)[:300]}"
        )

    def _candidate_models(self) -> list[str]:
        candidates = [self.config.model]
        candidates.extend(self.config.preferred_models or [])
        candidates.extend(self.config.fallback_models or [])
        candidates.extend(
            [
                "gemma-3-1b-it",
                "gemma-3-2b-it",
                "gemma-3-4b-it",
                "gemma-3-12b-it",
                "gemma-3-27b-it",
                "gemini-2.0-flash",
                "gemini-1.5-flash",
                "gemini-1.5-pro",
            ]
        )
        deduped: list[str] = []
        for model_name in candidates:
            if model_name and model_name not in deduped:
                deduped.append(model_name)
        return deduped


class OpenAIClient(BaseLLMClient):
    extra_headers: dict[str, str] = {}

    def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        endpoint = f"{self.config.base_url}/chat/completions"
        if not self.config.api_key:
            raise RuntimeError(f"{self.config.provider} API key is missing.")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.extra_headers)
        last_error: Exception | None = None
        for model_name in self._candidate_models():
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.4,
            }
            response = requests.post(endpoint, json=payload, headers=headers, timeout=120)
            if response.ok:
                data = response.json()
                try:
                    content = data["choices"][0]["message"]["content"].strip()
                except (KeyError, IndexError, TypeError) as exc:
                    raise RuntimeError(f"Unexpected OpenAI response: {json.dumps(data)[:500]}") from exc
                return LLMResponse(content=content, raw=data)
            last_error = RuntimeError(f"OpenAI model {model_name} failed with {response.status_code}: {response.text[:300]}")
            if response.status_code not in {404, 400}:
                break
        raise last_error or RuntimeError("OpenAI request failed without details.")

    def _candidate_models(self) -> list[str]:
        normalized = self.config.model.split("/", 1)[-1] if self.config.model else ""
        candidates = [self.config.model]
        candidates.extend(self.config.preferred_models or [])
        candidates.extend(self.config.fallback_models or [])
        candidates.extend([normalized, "gpt-4o-mini", "gpt-4.1-mini"])
        deduped: list[str] = []
        for model_name in candidates:
            if model_name and model_name not in deduped:
                deduped.append(model_name)
        return deduped


class OpenRouterClient(OpenAIClient):
    extra_headers = {
        "HTTP-Referer": "https://local.codex.app",
        "X-Title": "llm-gan-review-prototype",
    }


def build_client(config: ProviderConfig) -> BaseLLMClient:
    if config.provider == "google":
        return GeminiClient(config)
    if config.provider == "openai":
        return OpenAIClient(config)
    if config.provider == "openrouter":
        return OpenRouterClient(config)
    raise ValueError(f"Unsupported provider: {config.provider}")
