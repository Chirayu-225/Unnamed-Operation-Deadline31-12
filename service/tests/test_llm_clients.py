from unittest.mock import MagicMock, patch

import pytest

from app.agent.llm_clients import (
    GeminiClient,
    GroqClient,
    LLMClient,
    LLMRequestTooLargeError,
    LLMUnavailableError,
    _estimate_tokens,
    _TokenBucket,
)
from app.config import ConfigError


class _FakeStatusError(Exception):
    """Stands in for a real SDK exception (e.g. groq.APIStatusError)
    without depending on any specific SDK's class hierarchy —
    `_is_request_too_large` only cares about `.status_code`."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class _CountingLLM(LLMClient):
    """Fails its first N calls, then succeeds — used to test
    `complete_with_retry`'s retry behavior without hitting a real
    provider. `time.sleep` is patched out in these tests so the real
    backoff delays don't slow the suite down."""

    def __init__(self, fail_times: int, error_cls: type[Exception] = RuntimeError):
        self.fail_times = fail_times
        self.error_cls = error_cls
        self.calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error_cls(f"transient failure #{self.calls}")
        return "success"


class _AlwaysFailsLLM(LLMClient):
    def __init__(self):
        self.calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        raise RuntimeError("permanently down")


def test_groq_client_raises_clear_error_without_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        GroqClient()


def test_groq_client_complete_calls_sdk_correctly(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with patch("groq.Groq") as mock_groq_cls:
        mock_client = MagicMock()
        mock_groq_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="hello from groq"))]
        mock_client.chat.completions.create.return_value = mock_response

        client = GroqClient()
        result = client.complete("system prompt", "user prompt")

        assert result == "hello from groq"
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["messages"][0] == {"role": "system", "content": "system prompt"}
        assert call_kwargs["messages"][1] == {"role": "user", "content": "user prompt"}


def test_gemini_client_raises_clear_error_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        GeminiClient()


def test_gemini_client_complete_calls_sdk_correctly(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    with patch("google.genai.Client") as mock_genai_cls:
        mock_client = MagicMock()
        mock_genai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = "hello from gemini"
        mock_client.models.generate_content.return_value = mock_response

        client = GeminiClient()
        result = client.complete("system prompt", "user prompt")

        assert result == "hello from gemini"
        mock_client.models.generate_content.assert_called_once()
        call_kwargs = mock_client.models.generate_content.call_args.kwargs
        assert call_kwargs["contents"] == "user prompt"


def test_complete_with_retry_succeeds_after_transient_failures(monkeypatch):
    monkeypatch.setattr("app.agent.llm_clients.time.sleep", lambda _: None)
    llm = _CountingLLM(fail_times=2)  # fails twice, succeeds on the 3rd (last) attempt

    result = llm.complete_with_retry("sys", "user")

    assert result == "success"
    assert llm.calls == 3


def test_complete_with_retry_raises_llm_unavailable_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr("app.agent.llm_clients.time.sleep", lambda _: None)
    llm = _AlwaysFailsLLM()

    with pytest.raises(LLMUnavailableError) as exc_info:
        llm.complete_with_retry("sys", "user")

    # Exactly 3 attempts (the documented policy), not more, not fewer —
    # and never a raw provider exception escaping to the caller.
    assert llm.calls == 3
    assert "permanently down" in str(exc_info.value)
    assert isinstance(exc_info.value.last_error, RuntimeError)


def test_complete_with_retry_backs_off_between_attempts(monkeypatch):
    sleep_calls: list[float] = []
    monkeypatch.setattr("app.agent.llm_clients.time.sleep", sleep_calls.append)
    llm = _AlwaysFailsLLM()

    with pytest.raises(LLMUnavailableError):
        llm.complete_with_retry("sys", "user")

    # 2 sleeps between 3 attempts, exponentially increasing (1s, 2s) —
    # never a sleep after the final attempt, since there's nothing left
    # to wait for at that point.
    assert sleep_calls == [1.0, 2.0]


def test_complete_with_retry_does_not_retry_on_first_success(monkeypatch):
    monkeypatch.setattr("app.agent.llm_clients.time.sleep", lambda _: None)
    llm = _CountingLLM(fail_times=0)

    result = llm.complete_with_retry("sys", "user")

    assert result == "success"
    assert llm.calls == 1  # no wasted retries when the first attempt works


def test_complete_with_retry_fails_fast_on_413_without_retrying(monkeypatch):
    """A 413 (payload too large) is structurally unretryable — waiting
    or resubmitting the same prompt can never succeed, so this should
    NOT consume the normal 3-attempt retry budget or sleep at all."""
    sleep_calls: list[float] = []
    monkeypatch.setattr("app.agent.llm_clients.time.sleep", sleep_calls.append)

    class _TooLargeLLM(LLMClient):
        def __init__(self):
            self.calls = 0

        def complete(self, system_prompt: str, user_prompt: str) -> str:
            self.calls += 1
            raise _FakeStatusError("Request too large", status_code=413)

    llm = _TooLargeLLM()

    with pytest.raises(LLMRequestTooLargeError) as exc_info:
        llm.complete_with_retry("sys", "user")

    assert llm.calls == 1  # not retried — one failed attempt, not three
    assert sleep_calls == []  # no backoff wait either — waiting can't help
    assert isinstance(exc_info.value.last_error, _FakeStatusError)


def test_complete_with_retry_still_retries_429_and_503_normally(monkeypatch):
    """Only a 413 gets the fail-fast treatment — an ordinary rate-limit
    or server-busy error (no status_code, or a different one) still
    goes through the normal retry/backoff loop unchanged."""
    monkeypatch.setattr("app.agent.llm_clients.time.sleep", lambda _: None)

    class _RateLimitedThenOkLLM(LLMClient):
        def __init__(self):
            self.calls = 0

        def complete(self, system_prompt: str, user_prompt: str) -> str:
            self.calls += 1
            if self.calls == 1:
                raise _FakeStatusError("Rate limit reached", status_code=429)
            return "ok"

    llm = _RateLimitedThenOkLLM()
    result = llm.complete_with_retry("sys", "user")

    assert result == "ok"
    assert llm.calls == 2  # retried normally, unlike the 413 case above


def test_estimate_tokens_is_roughly_chars_over_four():
    assert _estimate_tokens("") == 1  # never zero — a call always costs something
    assert _estimate_tokens("a" * 400) == 100
    assert _estimate_tokens("a" * 401) == 101  # rounds up, never underestimates


class _FakeClock:
    """A controllable fake for time.monotonic()/time.sleep(), so
    _TokenBucket's minute-window behavior can be tested without a real
    test taking a minute (or several) to run. sleep() advances the
    clock by exactly the requested amount, same as real time passing."""

    def __init__(self):
        self.now = 0.0
        self.sleep_calls: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.now += seconds


def test_token_bucket_does_not_block_when_budget_available(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr("app.agent.llm_clients.time.monotonic", clock.monotonic)
    monkeypatch.setattr("app.agent.llm_clients.time.sleep", clock.sleep)

    bucket = _TokenBucket(tokens_per_minute=1000)
    bucket.acquire(200)
    bucket.acquire(300)

    assert clock.sleep_calls == []  # 500/1000 used — never needed to wait


def test_token_bucket_blocks_until_window_rolls_over_when_exceeded(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr("app.agent.llm_clients.time.monotonic", clock.monotonic)
    monkeypatch.setattr("app.agent.llm_clients.time.sleep", clock.sleep)

    bucket = _TokenBucket(tokens_per_minute=100)
    bucket.acquire(80)  # 80/100 used, fits fine
    bucket.acquire(30)  # 80+30=110 > 100 — must wait for the window to roll over

    assert clock.sleep_calls  # blocked at least once instead of firing anyway
    assert clock.now >= 60.0  # actually waited out a full window, not a token amount


def test_token_bucket_lets_an_oversized_single_call_through_when_window_empty(monkeypatch):
    """A call bigger than the entire budget must still be let through
    eventually (once the window is otherwise empty) — refusing it
    forever would mean the client could never complete that call at
    all, which is worse than letting the provider itself reject it."""
    clock = _FakeClock()
    monkeypatch.setattr("app.agent.llm_clients.time.monotonic", clock.monotonic)
    monkeypatch.setattr("app.agent.llm_clients.time.sleep", clock.sleep)

    bucket = _TokenBucket(tokens_per_minute=100)
    bucket.acquire(500)  # way over budget, but window was empty — let through

    assert clock.sleep_calls == []  # no infinite loop, no unnecessary wait either


def test_groq_client_defaults_to_a_conservative_tpm_budget(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.delenv("GROQ_TOKENS_PER_MINUTE", raising=False)
    with patch("groq.Groq"):
        client = GroqClient()
        assert client._token_bucket is not None
        assert client._token_bucket.tokens_per_minute == 7000


def test_groq_client_respects_env_override_for_tpm_budget(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_TOKENS_PER_MINUTE", "3000")
    with patch("groq.Groq"):
        client = GroqClient()
        assert client._token_bucket.tokens_per_minute == 3000


def test_gemini_client_has_no_pacing_by_default(monkeypatch):
    """No TPM limit has actually been observed against Gemini in this
    project — pacing stays off by default rather than guessing a
    number, unlike Groq where a real observed limit exists."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_TOKENS_PER_MINUTE", raising=False)
    with patch("google.genai.Client"):
        client = GeminiClient()
        assert client._token_bucket is None


def test_complete_with_retry_paces_calls_through_the_token_bucket(monkeypatch):
    """End-to-end: a client configured with a real TPM budget actually
    gets paced when used through complete_with_retry, not just when
    _TokenBucket is tested in isolation."""
    clock = _FakeClock()
    monkeypatch.setattr("app.agent.llm_clients.time.monotonic", clock.monotonic)
    monkeypatch.setattr("app.agent.llm_clients.time.sleep", clock.sleep)

    class _PacedLLM(LLMClient):
        def __init__(self):
            self._init_rate_limit(tokens_per_minute=10)  # tiny budget, easy to exceed
            self.calls = 0

        def complete(self, system_prompt: str, user_prompt: str) -> str:
            self.calls += 1
            return "ok"

    llm = _PacedLLM()
    # Each call's prompt is long enough to roughly cost more than the
    # whole 10-token budget on its own, so the second call must wait
    # for a fresh window rather than firing immediately after the first.
    big_prompt = "x" * 40  # ~10 estimated tokens
    llm.complete_with_retry("sys", big_prompt)
    llm.complete_with_retry("sys", big_prompt)

    assert llm.calls == 2  # both eventually went through
    assert clock.sleep_calls  # but the second one had to wait, not fire instantly
