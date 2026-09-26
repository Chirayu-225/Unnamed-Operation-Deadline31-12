import pytest

from app.config import ConfigError, gemini_api_key, groq_api_key


def test_groq_api_key_raises_clear_error_when_missing(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        groq_api_key()


def test_groq_api_key_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-123")
    assert groq_api_key() == "test-key-123"


def test_gemini_api_key_raises_clear_error_when_missing(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        gemini_api_key()
