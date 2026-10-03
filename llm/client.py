"""Groq LLM client with robust structured-output handling.

Groq exposes an OpenAI-compatible API, so the standard ``openai`` client is used.
``generate_structured`` asks the model for JSON, parses it, validates it with a
Pydantic schema and retries with corrective feedback when something is wrong.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Callable, List, Optional, Tuple, Type, TypeVar

import openai
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from prompts.templates import SYSTEM_MESSAGE

# Local development: read variables from a .env file if one exists.
load_dotenv()

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_MAX_TOKENS = 4000  # used when a stage does not set its own budget
TRUNCATION_MAX_TOKENS = 12000
MAX_ATTEMPTS = 4  # attempts that produced unusable model output
MAX_API_RETRIES = 5  # extra retries for rate limits, network errors and 5xx
REQUEST_TIMEOUT_SECONDS = 90
MAX_WAIT_SECONDS = 60

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """An error with a message that is safe and helpful to show to the user."""


# --------------------------------------------------------------------------- #
# Configuration (.env locally, Streamlit secrets when deployed)
# --------------------------------------------------------------------------- #
def get_setting(name: str, default: Optional[str] = None) -> Optional[str]:
    """Look up a setting in environment variables, then in Streamlit secrets."""
    value = os.getenv(name)
    if value:
        return value.strip()
    try:
        import streamlit as st

        secret = st.secrets.get(name)
        if secret:
            return str(secret).strip()
    except Exception:
        # No secrets file, or not running under Streamlit: fall through.
        pass
    return default


def get_model() -> str:
    return get_setting("GROQ_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL


def has_api_key() -> bool:
    return bool(get_setting("GROQ_API_KEY"))


def _max_tokens_override() -> Optional[int]:
    """GROQ_MAX_TOKENS, when set, overrides the per-stage token budgets."""
    raw = get_setting("GROQ_MAX_TOKENS")
    try:
        return max(1000, int(raw)) if raw else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Low-level call (tests can replace this function)
# --------------------------------------------------------------------------- #
def _complete(messages: List[dict], max_tokens: int) -> Tuple[str, Optional[str]]:
    """Send one chat completion request. Returns (text, finish_reason)."""
    api_key = get_setting("GROQ_API_KEY")
    if not api_key:
        raise LLMError(
            "GROQ_API_KEY is not set. Add it to a local .env file, or to Streamlit "
            "secrets when deployed."
        )
    client = OpenAI(
        api_key=api_key,
        base_url=GROQ_BASE_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=0,  # retries are handled in generate_structured
    )
    response = client.chat.completions.create(
        model=get_model(),
        messages=messages,
        temperature=0.2,
        max_tokens=max_tokens,
    )
    if not response.choices:
        return "", None
    choice = response.choices[0]
    return (choice.message.content or ""), choice.finish_reason


# --------------------------------------------------------------------------- #
# Error handling helpers
# --------------------------------------------------------------------------- #
_TRY_AGAIN_RE = re.compile(r"try again in (?:(\d+)m)?\s*(\d+(?:\.\d+)?)s", re.IGNORECASE)


def _retry_after_seconds(exc: Exception) -> Optional[float]:
    """Seconds Groq asks us to wait: Retry-After header, else the error message."""
    try:
        value = exc.response.headers.get("retry-after")  # type: ignore[attr-defined]
        if value:
            return min(float(value), MAX_WAIT_SECONDS)
    except Exception:
        pass
    match = _TRY_AGAIN_RE.search(str(exc))
    if match:
        minutes = int(match.group(1) or 0)
        return min(minutes * 60 + float(match.group(2)), MAX_WAIT_SECONDS)
    return None


def _classify_api_error(exc: openai.APIError, attempt: int) -> Tuple[LLMError, bool, float]:
    """Return (user-facing error, is_retryable, seconds_to_wait)."""
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return (
            LLMError("The Groq API key was rejected. Check that GROQ_API_KEY is correct and active."),
            False,
            0,
        )
    if isinstance(exc, openai.RateLimitError):
        wait = (_retry_after_seconds(exc) or min(10 * attempt, MAX_WAIT_SECONDS)) + 1
        return (
            LLMError(
                "The Groq rate limit (tokens per minute) was reached and retrying did not "
                "help. Wait about a minute and use 'Resume', or set GROQ_MODEL to a model "
                "with higher limits."
            ),
            True,
            wait,
        )
    if isinstance(exc, openai.APIConnectionError):  # includes timeouts
        return (
            LLMError("Could not reach the Groq API (network problem or timeout). Please try again."),
            True,
            2 * attempt,
        )
    if isinstance(exc, (openai.BadRequestError, openai.NotFoundError)):
        return (
            LLMError(
                f"Groq rejected the request. The model '{get_model()}' may be unavailable "
                "or the request too large. Check GROQ_MODEL."
            ),
            False,
            0,
        )
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status >= 500:
        return (
            LLMError(f"The Groq service had a temporary problem (HTTP {status}). Please try again."),
            True,
            2 * attempt,
        )
    return LLMError(f"The Groq API returned an error ({type(exc).__name__}). Please try again."), False, 0


def _extract_json(text: str):
    """Parse JSON from model text, tolerating code fences and stray prose."""
    cleaned = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as first_error:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise first_error


def _describe_validation_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:8]:
        location = ".".join(str(p) for p in err["loc"]) or "(root)"
        if err["type"] == "extra_forbidden":
            parts.append(f"{location}: unexpected field, remove it")
        elif err["type"] == "missing":
            parts.append(f"{location}: required field is missing")
        else:
            parts.append(f"{location}: {err['msg']}")
    return "; ".join(parts)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def generate_structured(
    prompt: str,
    schema: Type[T],
    *,
    stage: str,
    validator: Optional[Callable[[T], None]] = None,
    max_attempts: int = MAX_ATTEMPTS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> T:
    """Call the LLM and return a validated ``schema`` instance.

    Retries on API hiccups, rate limits, empty or truncated output, invalid JSON
    and schema violations. ``validator`` may raise ValueError for extra checks.
    Raises LLMError with a user-friendly message if every attempt fails.
    """
    base_messages = [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {"role": "user", "content": prompt},
    ]
    follow_up: List[dict] = []
    max_tokens = _max_tokens_override() or max_tokens
    last_error = LLMError(f"{stage}: the request failed.")
    attempt = 0  # attempts that returned model output
    api_retries = 0  # rate limits, network errors and 5xx responses

    while attempt < max_attempts:
        # ---- 1. call the API ------------------------------------------------
        try:
            text, finish_reason = _complete(base_messages + follow_up, max_tokens)
        except LLMError:
            raise
        except openai.APIError as exc:
            api_retries += 1
            error, retryable, wait = _classify_api_error(exc, api_retries)
            last_error = LLMError(f"{stage}: {error}")
            if not retryable or api_retries > MAX_API_RETRIES:
                raise last_error from None
            time.sleep(wait)
            continue
        attempt += 1

        # ---- 2. detect empty / truncated output ----------------------------
        problem: Optional[str] = None
        retry_hint: Optional[str] = None
        keep_output = True

        if not text.strip():
            problem = "the model returned an empty response"
            retry_hint = "Your previous reply was empty. Return the complete JSON object now."
            keep_output = False
        elif finish_reason == "length":
            problem = "the response was cut off because it was too long"
            retry_hint = (
                "Your previous reply was cut off because it was too long. Return the COMPLETE "
                "JSON object again, but much shorter: fewer and shorter list items and less code."
            )
            keep_output = False
            max_tokens = min(int(max_tokens * 1.5), TRUNCATION_MAX_TOKENS)

        # ---- 3. parse and validate ----------------------------------------
        if problem is None:
            try:
                data = _extract_json(text)
                if not isinstance(data, dict):
                    raise ValueError("the top-level JSON value must be an object")
                result = schema.model_validate(data)
                if validator is not None:
                    validator(result)
                return result
            except json.JSONDecodeError as exc:
                problem = f"the response was not valid JSON ({exc.msg} at position {exc.pos})"
                retry_hint = (
                    f"Your previous reply was not valid JSON ({exc.msg}). Return ONLY one valid "
                    "JSON object, with newlines inside strings escaped as \\n."
                )
            except ValidationError as exc:
                detail = _describe_validation_error(exc)
                problem = f"the response did not match the required format ({detail})"
                retry_hint = (
                    f"Your previous JSON was invalid: {detail}. Return the corrected, complete "
                    "JSON object using exactly the required fields."
                )
            except ValueError as exc:
                problem = f"the response failed a check ({exc})"
                retry_hint = f"Your previous reply failed a check: {exc}. Return the corrected JSON object."

        last_error = LLMError(f"{stage}: {problem}.")
        if attempt == max_attempts:
            break

        follow_up = []
        if keep_output:
            follow_up.append({"role": "assistant", "content": text[:3000]})
        follow_up.append({"role": "user", "content": retry_hint or "Return the corrected JSON object."})

    raise LLMError(
        f"{stage} stage failed after {max_attempts} attempts. Last problem: "
        f"{str(last_error).split(': ', 1)[-1]} Try again, or simplify the idea."
    )