"""
gemini.py - The one shared Gemini client and the helpers every feature uses.

Call connect() once at startup. Everything else asks this module for the
client instead of keeping its own copy.
"""

from __future__ import annotations

import json
import os
import re
import time

DEFAULT_MODEL = "gemini-2.5-flash"

# After Google says "quota used up", don't keep asking: every extra call
# just fails slowly. Try again after this many seconds.
RATE_LIMIT_PAUSE_SECONDS = 10 * 60

_client = None
_connect_called = False
_rate_limited_at = 0.0


class RateLimited(RuntimeError):
    """Gemini refused because the daily or per-minute quota is used up."""


def model() -> str:
    """The Gemini model to use. Set GEMINI_MODEL in .env to change it."""
    return os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL


def recently_rate_limited() -> bool:
    return time.time() - _rate_limited_at < RATE_LIMIT_PAUSE_SECONDS


def connect(api_key: str) -> bool:
    """Create the client and make one tiny test call. Returns True when it works."""
    global _client, _connect_called
    _connect_called = True
    _client = None
    if not api_key:
        print("  No Gemini key. Put GEMINI_API_KEY in .env or run with --gemini_key YOUR_KEY")
        return False
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        _client = client
        reply = generate("Say OK", temperature=0, max_tokens=5)
        print(f"  Gemini connected ({model()})! Test: {reply or 'OK'}")
        return True
    except RateLimited:
        # The key works; today's quota is just used up. Keep the client so
        # Ivy recovers on its own when the quota resets.
        print(f"  Gemini connected ({model()}), but today's quota is used up. Translations fall back to opus-mt for now.")
        return True
    except Exception as exc:
        print(f"  Gemini setup failed: {exc}")
        _client = None
        return False


def get_client():
    """Return the shared client, or None. Scripts that never call connect() get one from GEMINI_API_KEY."""
    global _client
    if _client is None and not _connect_called:
        key = os.environ.get("GEMINI_API_KEY", "")
        if key:
            try:
                from google import genai

                _client = genai.Client(api_key=key)
            except Exception:
                _client = None
    return _client


def is_ready() -> bool:
    return get_client() is not None


def generate(prompt: str, *, temperature: float, max_tokens: int) -> str:
    """Send one prompt and return the reply text (stripped). Raises if Gemini fails."""
    global _rate_limited_at
    client = get_client()
    if client is None:
        raise RuntimeError("Gemini is not configured")
    if recently_rate_limited():
        raise RateLimited("Gemini quota used up (paused after a recent 429)")

    from google.genai import types

    settings = {"temperature": temperature, "max_output_tokens": max_tokens}
    if "2.5" in model():
        # 2.5 models think by default, which is slow; turn it off. Newer models reject this setting.
        settings["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

    try:
        response = client.models.generate_content(
            model=model(),
            contents=prompt,
            config=types.GenerateContentConfig(**settings),
        )
    except Exception as exc:
        if is_rate_limited(exc):
            _rate_limited_at = time.time()
            print(f"  [Gemini] quota used up for {model()}; pausing AI calls for {RATE_LIMIT_PAUSE_SECONDS // 60} minutes")
            raise RateLimited(str(exc)[:200]) from exc
        raise
    return (response.text or "").strip()


def strip_wrapping_quotes(text: str) -> str:
    """Remove one pair of quotes the model sometimes wraps around a single answer."""
    text = (text or "").strip()
    for quote in ['"', "'", "“", "”"]:
        if len(text) >= 2 and text.startswith(quote) and text.endswith(quote):
            return text[1:-1].strip()
    return text


def extract_json_payload(raw_text: str):
    """Pull the first JSON object or array out of a model reply (handles ``` fences)."""
    if not raw_text:
        return None

    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}|\[.*\]", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def is_rate_limited(exc: Exception) -> bool:
    if isinstance(exc, RateLimited):
        return True
    text = str(exc).lower()
    return "429" in text or "resource_exhausted" in text or "rate limit" in text


def is_transient(exc: Exception) -> bool:
    text = str(exc).lower()
    return is_rate_limited(exc) or any(
        token in text for token in ["503", "unavailable", "overload", "timeout"]
    )


TRANSLATE_LIMIT_NOTICE = (
    "Ivy has reached today's AI limit, so this is the basic translation. "
    "Formal/casual styles and word details will be back later."
)


def friendly_error(exc: Exception, action: str) -> str:
    """A short message that is safe to show to the learner."""
    if is_rate_limited(exc):
        return f"Ivy has reached today's AI limit, so it can't {action} right now. Please try again later."
    if is_transient(exc):
        return f"The AI service is busy right now, so Ivy couldn't {action}. Please try again in a moment."
    return f"Ivy couldn't {action}. Please try again."
