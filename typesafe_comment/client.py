"""Minimal stdlib HTTP client for the TypeSafe System One API."""

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


class TypeSafeError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_RETRIES = 4

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504, 529}


class TypeSafeClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        if not api_key:
            raise TypeSafeError("api_key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = int(timeout)
        self.max_retries = int(max_retries)

    def evaluate(self, state: Any, questions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "state": state,
            "model": self.model,
            "questions": questions,
        }
        body = json.dumps(payload).encode("utf-8")
        url = "{}/v1/systemone".format(self.base_url)
        headers = {
            "Authorization": "Bearer {}".format(self.api_key),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        last_error: Optional[TypeSafeError] = None
        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                    return _parse_json(raw)
            except urllib.error.HTTPError as exc:
                status = exc.code
                raw = ""
                try:
                    raw = exc.read().decode("utf-8")
                except Exception:
                    raw = ""
                parsed = _safe_json(raw)
                message = _format_error(status, parsed, raw)
                if status in _RETRYABLE_STATUSES and attempt < self.max_retries:
                    last_error = TypeSafeError(message, status=status, body=parsed)
                    time.sleep(_backoff_seconds(attempt))
                    continue
                raise TypeSafeError(message, status=status, body=parsed)
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", str(exc))
                message = "could not reach TypeSafe API at {}: {}".format(url, reason)
                if attempt < self.max_retries:
                    last_error = TypeSafeError(message, status=None, body=None)
                    time.sleep(_backoff_seconds(attempt))
                    continue
                raise TypeSafeError(message, status=None, body=None)
            except TimeoutError:
                message = "TypeSafe API request timed out after {}s".format(self.timeout)
                if attempt < self.max_retries:
                    last_error = TypeSafeError(message, status=None, body=None)
                    time.sleep(_backoff_seconds(attempt))
                    continue
                raise TypeSafeError(message, status=None, body=None)

        raise last_error or TypeSafeError("TypeSafe API request failed")

    def evaluate_score(
        self,
        state: Any,
        questions: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        body = self.evaluate(state, questions)
        answers = body.get("answers")
        if not isinstance(answers, dict):
            raise TypeSafeError("unexpected TypeSafe response: missing 'answers'", body=body)
        return answers


def _backoff_seconds(attempt: int) -> float:
    return min(0.5 * (2 ** attempt), 30.0)


def _parse_json(raw: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise TypeSafeError("TypeSafe API returned non-JSON response: {!r}".format(raw[:200]))
    if not isinstance(parsed, dict):
        raise TypeSafeError("TypeSafe API returned unexpected JSON shape: {!r}".format(raw[:200]))
    return parsed


def _safe_json(raw: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _format_error(status: int, body: Any, raw: str) -> str:
    if isinstance(body, dict):
        detail = body.get("message") or body.get("error") or body.get("detail")
        if detail:
            return "TypeSafe API error {}: {}".format(status, detail)
    if raw:
        return "TypeSafe API error {}: {}".format(status, raw[:200])
    return "TypeSafe API error {}".format(status)
