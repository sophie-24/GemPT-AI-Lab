"""Thin Gemini model adapter backed by Google's maintained ``google-genai`` SDK.

Importing this module does not require an API key or initialize the SDK client.
The SDK and client are loaded lazily when ``generate_text`` is first called.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any


DEFAULT_GEMINI_MODEL = "gemini-2.5-pro"
MODEL_ENV_VAR = "GEMINI_MODEL_NAME"
API_KEY_ENV_VAR = "GOOGLE_API_KEY"


class ModelClientError(RuntimeError):
    """Sanitized adapter error with safe diagnostic metadata."""

    def __init__(self, message: str, *, stage: str, provider_code: int | str | None = None):
        super().__init__(message)
        self.stage = stage
        self.provider_code = provider_code


class ModelClientConfigurationError(ModelClientError):
    """Raised when the SDK or its required configuration is unavailable."""


class ModelGenerationError(ModelClientError):
    """Raised when the provider rejects or cannot complete a generation call."""


class GeminiModelClient:
    """Minimal synchronous text generation interface for Gemini.

    Args:
        api_key: Optional Google API key. Defaults to ``GOOGLE_API_KEY``.
        model_name: Optional model override. Defaults to ``GEMINI_MODEL_NAME``
            and then ``gemini-2.5-pro``.

    The model and key are deliberately excluded from error messages and logs.
    """

    def __init__(self, api_key: str | None = None, model_name: str | None = None):
        self._api_key = api_key if api_key is not None else os.environ.get(API_KEY_ENV_VAR)
        self.model_name = model_name or os.environ.get(MODEL_ENV_VAR) or DEFAULT_GEMINI_MODEL
        self._client: Any | None = None
        self._sdk_types: Any | None = None

    def _ensure_client(self) -> None:
        key = self._api_key.strip() if isinstance(self._api_key, str) else ""
        if not key or key.lower().startswith("your_"):
            raise ModelClientConfigurationError(
                f"Gemini API key is missing. Set {API_KEY_ENV_VAR} or pass api_key.",
                stage="configuration",
            )
        if self._client is not None:
            return
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ModelClientConfigurationError(
                "Gemini SDK is unavailable. Install the google-genai package.",
                stage="dependency",
            ) from None
        try:
            self._client = genai.Client(api_key=key)
            self._sdk_types = types
        except Exception as exc:
            raise ModelClientConfigurationError(
                f"Gemini SDK client initialization failed ({type(exc).__name__}).",
                stage="client_initialization",
            ) from None

    @staticmethod
    def _validate_contents(contents: str | Sequence[Any]) -> str | list[Any]:
        if isinstance(contents, str):
            if not contents.strip():
                raise ValueError("contents must not be empty")
            return contents
        if not isinstance(contents, Sequence) or isinstance(contents, (bytes, bytearray)):
            raise TypeError("contents must be text or a sequence containing text and PIL images")
        normalized = list(contents)
        if not normalized:
            raise ValueError("contents must not be empty")
        if not all(isinstance(item, str) or _is_pil_image(item) for item in normalized):
            raise TypeError("contents items must be strings or PIL.Image.Image instances")
        if not any(isinstance(item, str) and item.strip() for item in normalized):
            raise ValueError("contents must include non-empty text")
        return normalized

    def generate_text(self, contents: str | Sequence[Any], *, response_schema: Any = None) -> str:
        """Generate and return text, optionally constrained by a JSON response schema.

        ``contents`` accepts a prompt string or a sequence of prompt strings and
        ``PIL.Image.Image`` values. For structured output, pass a JSON Schema
        mapping or a Pydantic model as ``response_schema``.
        """
        normalized = self._validate_contents(contents)
        self._ensure_client()

        config = None
        if response_schema is not None:
            try:
                config = self._sdk_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema,
                )
            except Exception as exc:
                raise ModelClientConfigurationError(
                    f"Invalid Gemini response schema ({type(exc).__name__}).",
                    stage="response_schema",
                ) from None

        try:
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=normalized,
                config=config,
            )
        except Exception as exc:
            provider_code = getattr(exc, "code", None)
            if not isinstance(provider_code, int):
                provider_code = None
            # Do not forward SDK text: provider messages can contain request data.
            raise ModelGenerationError(
                f"Gemini generation failed ({type(exc).__name__})"
                + (f", provider code {provider_code}." if provider_code is not None else "."),
                stage="generation",
                provider_code=provider_code,
            ) from None

        text = getattr(response, "text", None)
        if not isinstance(text, str):
            raise ModelGenerationError(
                "Gemini returned no text content.",
                stage="response",
            )
        return text


def _is_pil_image(value: Any) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return False
    return isinstance(value, Image.Image)
