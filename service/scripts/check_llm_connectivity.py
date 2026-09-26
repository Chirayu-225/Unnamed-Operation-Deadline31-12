"""
Live LLM connectivity check — this makes REAL API calls and costs a
tiny amount of real usage against your free tiers. Unlike everything
else so far, this can't be verified in advance for you — it needs your
actual GROQ_API_KEY and GEMINI_API_KEY set as environment variables.

Run from dbcaas/service, after setting both keys:
    PYTHONPATH=. python3 scripts/check_llm_connectivity.py
"""

from app.agent.llm_clients import GeminiClient, GroqClient

print("Testing Groq connectivity (generator's provider)...")
try:
    groq = GroqClient()
    reply = groq.complete(
        system_prompt="Reply with exactly one word.",
        user_prompt="Say 'connected'.",
    )
    print("  OK — Groq replied:", repr(reply))
except Exception as e:
    print("  FAILED:", type(e).__name__, "-", e)
    print("  Checking which models your key actually has access to...")
    try:
        from groq import Groq

        available = Groq().models.list()
        model_ids = [m.id for m in available.data]
        print("  Models available to your key:", model_ids)
        print("  Update GroqClient's default `model` in app/agent/llm_clients.py")
        print("  to one of the IDs above, then re-run this script.")
    except Exception as list_error:
        print("  Could not list models either:", type(list_error).__name__, "-", list_error)

print()
print("Testing Gemini connectivity (verifier's provider)...")
try:
    gemini = GeminiClient()
    reply = gemini.complete(
        system_prompt="Reply with exactly one word.",
        user_prompt="Say 'connected'.",
    )
    print("  OK — Gemini replied:", repr(reply))
except Exception as e:
    print("  FAILED:", type(e).__name__, "-", e)
