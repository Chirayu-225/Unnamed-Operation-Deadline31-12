"""
LLM client wrappers — same spirit as the Connector interface: callers
depend on `LLMClient`, never on Groq or Gemini specifics directly.
This is what makes the generator/verifier provider split (Groq for the
generator, Gemini for the verifier, per the locked design decision to
avoid correlated blind spots between the two) a config choice, not a
code fork.

SDK imports are deliberately deferred to inside each class's
__init__, not at module load time — so importing this module (e.g. for
type-checking or testing unrelated code) never requires either SDK
package or either API key to be present.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from app.config import (
    gemini_api_key,
    gemini_tokens_per_minute,
    groq_api_key,
    groq_tokens_per_minute,
)

# Retry policy, applied uniformly to every provider via
# `complete_with_retry` below rather than duplicated per client.
# Numbers per the explicit product decision: 3 attempts total,
# exponential backoff (1s -> 2s -> 4s between attempts), so total
# added wait before giving up is ~7s — comfortably under the ~10-15s
# budget a user will wait for one dashboard section, even accounting
# for the calls' own latency.
#
# This is deliberately a SEPARATE, secondary mechanism from the token
# bucket below, not a replacement for it. Retry/backoff reacts after a
# call fails; it was never going to prevent a self-inflicted rate-limit
# violation in the first place — see _TokenBucket's docstring for why.
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.0


def _is_request_too_large(exc: Exception) -> bool:
    """True for a provider error whose HTTP status is 413 (payload too
    large) — e.g. Groq's "Request too large ... tokens per minute"
    response when a single call's prompt exceeds its per-request token
    cap. Duck-typed on `status_code` rather than importing Groq's
    exception classes, so this works for any SDK's error object without
    a hard dependency, and safely returns False for exceptions (like
    Gemini's transient 503s, or Groq's own 429 daily-cap error) that
    either lack this attribute or carry a different status."""
    return getattr(exc, "status_code", None) == 413


def _estimate_tokens(text: str) -> int:
    """Rough, provider-agnostic token estimate — no tokenizer
    dependency, deliberately conservative (rounds up). ~4 characters
    per token is the standard rule-of-thumb approximation for English
    text used by most providers' own docs; it doesn't need to be exact
    to do its job here, only close enough that the bucket doesn't let
    a call through that will actually blow the real budget."""
    return max(1, (len(text) + 3) // 4)


class _TokenBucket:
    """A fixed-window (not a precise rolling log — simple and close
    enough for pacing) tokens-per-minute budget, shared by every call
    a client makes. This is the fix for the failure mode retry/backoff
    can't touch: firing a batch of calls back-to-back can push a full
    minute's token budget through in a few seconds, which a provider's
    TPM cap rejects outright — no number of retries recovers from that,
    because the retries hit the same still-exhausted window. `acquire`
    blocks (sleeps) BEFORE a call goes out if there isn't enough budget
    left in the current window, rather than firing and hoping.

    A single call larger than the entire per-minute budget is let
    through once the window is otherwise empty — refusing it outright
    would mean no client could ever complete a large single call, which
    is worse than the (unavoidable) risk of that one call being
    rejected by the provider on its own terms."""

    _WINDOW_SECONDS = 60.0

    def __init__(self, tokens_per_minute: int):
        self.tokens_per_minute = tokens_per_minute
        self._window_start = time.monotonic()
        self._tokens_used = 0

    def _roll_window_if_elapsed(self) -> None:
        now = time.monotonic()
        if now - self._window_start >= self._WINDOW_SECONDS:
            self._window_start = now
            self._tokens_used = 0

    def acquire(self, estimated_tokens: int) -> None:
        while True:
            self._roll_window_if_elapsed()
            fits = self._tokens_used + estimated_tokens <= self.tokens_per_minute
            window_otherwise_empty = self._tokens_used == 0
            if fits or window_otherwise_empty:
                self._tokens_used += estimated_tokens
                return
            remaining = self._WINDOW_SECONDS - (time.monotonic() - self._window_start)
            time.sleep(max(remaining, 0.1))


class LLMUnavailableError(Exception):
    """Raised by `complete_with_retry` when a provider call failed on
    every retry attempt. This is the signal callers (Verifier,
    SemanticReasoner) catch to fail safe — mark the affected section
    as genuinely unavailable rather than crash the whole scan or
    silently show unverified/incomplete results as if they were
    complete. Wraps the last underlying exception so the real cause
    isn't lost."""

    def __init__(self, message: str, last_error: Exception):
        super().__init__(message)
        self.last_error = last_error


class LLMRequestTooLargeError(Exception):
    """Raised by `complete_with_retry` immediately — on the FIRST
    attempt, no retries spent — when the provider rejects a call
    specifically because this one payload is too big for a single
    request (see `_is_request_too_large`). This is deliberately NOT
    folded into the normal retry/backoff loop: retrying an unchanged,
    oversized payload can never succeed no matter how long you wait or
    how many attempts you spend, since waiting doesn't shrink the
    prompt. Backing off here would just waste the whole retry budget
    reproducing the identical failure three times (this is exactly
    what happened before this was added — a batch-size-100 run burned
    3 retries on a 413 that was never going to change).

    Distinct from `LLMUnavailableError` on purpose: this is the
    caller's problem to fix (shrink the payload and try again with
    less), not something a client-level retry can paper over — only
    the caller (e.g. `SemanticReasoner`, which knows it can drop rows
    from its batch) has enough context to actually shrink anything."""

    def __init__(self, message: str, last_error: Exception):
        super().__init__(message)
        self.last_error = last_error


class LLMClient(ABC):
    """`tokens_per_minute`, when set by a subclass, gates every call
    (both `complete` and `complete_with_retry`) through a `_TokenBucket`
    — pacing calls BEFORE they fire, so a burst of batches can't
    self-inflict a provider's rate limit in the first place. `None`
    (the default) disables pacing entirely — unset unless a subclass
    opts in with a real budget, so nothing sleeps unexpectedly for a
    client whose provider limit is unknown or untested."""

    _token_bucket: _TokenBucket | None = None

    def _init_rate_limit(self, tokens_per_minute: int | None) -> None:
        """Subclasses call this from `__init__` with their provider's
        TPM budget (or None to leave pacing off)."""
        self._token_bucket = _TokenBucket(tokens_per_minute) if tokens_per_minute else None

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Send a system + user prompt, return the model's text reply.
        A single, unretried attempt — implement the raw provider call
        here. Callers that want retry/backoff use
        `complete_with_retry` instead, which wraps this."""
        raise NotImplementedError

    def _paced_complete(self, system_prompt: str, user_prompt: str) -> str:
        """`complete`, but blocking first if the token bucket says this
        call would exceed the per-minute budget. Both `complete_with_retry`
        and a direct `complete_with_retry`-less caller go through this,
        since pacing needs to happen before EVERY attempt, not just the
        first — a retried call still costs the same tokens again."""
        if self._token_bucket is not None:
            self._token_bucket.acquire(_estimate_tokens(system_prompt + user_prompt))
        return self.complete(system_prompt, user_prompt)

    def complete_with_retry(self, system_prompt: str, user_prompt: str) -> str:
        """Retry/backoff wrapper around `complete`, shared by every
        provider so resilience isn't reimplemented per subclass. Paces
        every attempt through the token bucket first (see
        `_paced_complete`) — pacing is the primary defense against a
        self-inflicted rate limit, retry/backoff is the fallback for
        the rarer provider-side blip that pacing can't prevent. Never
        lets a raw provider exception escape — after every attempt
        fails, raises `LLMUnavailableError` instead, so callers have
        one exception type to catch and fail safe on, regardless of
        which provider or underlying error caused it."""
        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return self._paced_complete(system_prompt, user_prompt)
            except Exception as exc:  # noqa: BLE001 - deliberately broad:
                # any provider failure (busy server, rate limit, network
                # blip) gets the same fail-safe treatment, not just a
                # hand-picked subset of exception types — EXCEPT the
                # "payload too large" class below, which is structurally
                # different (see LLMRequestTooLargeError's docstring).
                if _is_request_too_large(exc):
                    raise LLMRequestTooLargeError(
                        f"Request rejected as too large on first attempt "
                        f"(not retried — retrying an unchanged oversized "
                        f"payload can't succeed): {exc}",
                        exc,
                    ) from exc
                last_error = exc
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_BACKOFF_BASE_SECONDS * (2**attempt))
        raise LLMUnavailableError(
            f"LLM call failed after {_MAX_ATTEMPTS} attempts: {last_error}",
            last_error,  # type: ignore[arg-type]
        )


class GroqClient(LLMClient):
    """Generator's provider — fast, cheap, suited to high-volume
    reasoning over samples.

    Default model (`openai/gpt-oss-20b`) is picked from what's actually
    available on the account this was tested against — Groq's model
    access varies by account, so if this 404s for you, run
    `scripts/check_llm_connectivity.py` to see your own key's list and
    update this default. `openai/gpt-oss-120b` is the larger, more
    capable sibling if 20b's quality isn't enough once real usage
    starts."""

    def __init__(self, model: str = "openai/gpt-oss-20b", tokens_per_minute: int | None = None):
        from groq import Groq

        self._client = Groq(api_key=groq_api_key())
        self._model = model
        # Defaults to a conservative budget under the observed
        # free-tier TPM cap (see app.config.groq_tokens_per_minute) —
        # this is what prevents the semantic reasoning loop's batches
        # from firing faster than Groq's own rate limit allows, rather
        # than firing them all immediately and relying on retry to
        # clean up the 429s afterward.
        self._init_rate_limit(
            tokens_per_minute if tokens_per_minute is not None else groq_tokens_per_minute()
        )

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""


class GeminiClient(LLMClient):
    """Verifier's provider — deliberately a different model family than
    the generator, so it isn't prone to the same blind spots when
    checking the generator's evidence."""

    def __init__(self, model: str = "gemini-3.6-flash", tokens_per_minute: int | None = None):
        from google import genai

        self._client = genai.Client(api_key=gemini_api_key())
        self._model = model
        # Defaults to None (pacing disabled) — see
        # app.config.gemini_tokens_per_minute for why: no TPM limit
        # has actually been observed against Gemini in this project
        # yet, only transient 503s, so there's no evidence-based number
        # to pace against. Set GEMINI_TOKENS_PER_MINUTE if that changes.
        self._init_rate_limit(
            tokens_per_minute if tokens_per_minute is not None else gemini_tokens_per_minute()
        )

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=types.GenerateContentConfig(system_instruction=system_prompt),
        )
        return response.text or ""
