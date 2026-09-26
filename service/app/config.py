"""
Configuration — API keys and other secrets come from environment
variables only, never hardcoded and never committed. See .env.example
for what needs to be set locally.
"""

from __future__ import annotations

import os


class ConfigError(RuntimeError):
    """Raised when required configuration (like an API key) is missing."""


def _get_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            f"{name} is not set. Set it as an environment variable "
            f"(see .env.example) before using anything that needs it."
        )
    return value


def groq_api_key() -> str:
    return _get_env("GROQ_API_KEY")


def gemini_api_key() -> str:
    return _get_env("GEMINI_API_KEY")


def _get_optional_int_env(name: str, default: int | None) -> int | None:
    value = os.environ.get(name)
    if not value:
        return default
    return int(value)


def groq_tokens_per_minute() -> int | None:
    """Groq's own free-tier default is conservative-below-observed,
    not the account's real cap — the real cap depends on account/tier
    and Groq's error messages report the actual live number when hit
    (e.g. "Limit 8000... TPM"), which is the source of truth. Override
    with GROQ_TOKENS_PER_MINUTE if your account's real limit differs
    (check https://console.groq.com/settings/billing). 7000 is a
    deliberate safety margin under an observed 8000 TPM free-tier cap,
    not itself Groq's published number."""
    return _get_optional_int_env("GROQ_TOKENS_PER_MINUTE", 7000)


def gemini_tokens_per_minute() -> int | None:
    """Unlike Groq, no TPM limit has actually been observed against
    Gemini yet in this project (failures seen so far were transient
    503s, not 429 rate limits) — so this defaults to None (pacing
    disabled) rather than guessing a number that might be wrong in
    either direction. Google doesn't publish free-tier numbers in
    their docs; check https://aistudio.google.com/rate-limit for your
    account's actual limit and set GEMINI_TOKENS_PER_MINUTE if you
    start seeing 429s from Gemini too."""
    return _get_optional_int_env("GEMINI_TOKENS_PER_MINUTE", None)
