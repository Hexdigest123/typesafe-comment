"""Environment configuration for typesafe-comment.

The CLI checks the general (process) environment first. If a key is already
present in the environment (e.g. set via ``export TYPESAFE_API_KEY=...`` or a
CI secret), it always wins. Values from a ``.env`` file only fill in gaps.

The ``--env`` flag selects where to look for a ``.env`` file:
  * ``--env`` with no path  -> ``./.env`` (cwd)
  * ``--env ./path/to/.env`` -> that exact file
  * not given              -> no file is loaded (environment only)
"""

import os
from typing import Dict, Iterable, Optional, Tuple


class EnvError(Exception):
    """Raised when environment configuration is invalid or missing."""


def parse_env_file(path: str) -> Dict[str, str]:
    """Parse a ``.env`` file into a dict without touching ``os.environ``.

    Rules:
      * ``#`` starts a comment (whole-line and inline, outside quotes).
      * ``KEY=value`` pairs are split on the first ``=``.
      * Surrounding single/double quotes on the value are stripped.
      * ``export KEY=value`` prefixes are accepted.
      * Blank lines are ignored.
    """
    values: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw_lines = handle.readlines()
    except FileNotFoundError:
        raise EnvError("env file not found: {}".format(path))
    except OSError as exc:
        raise EnvError("could not read env file {}: {}".format(path, exc))

    for lineno, raw in enumerate(raw_lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            raise EnvError("invalid env line {}:{}: {!r}".format(path, lineno, raw.rstrip("\n")))
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise EnvError("invalid env line {}:{}: empty key".format(path, lineno))
        value = _strip_value(value)
        values[key] = value
    return values


def _strip_value(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    quote_chars = ('"', "'")
    if value[0] in quote_chars:
        quote = value[0]
        rest = value[1:]
        end = rest.find(quote)
        if end != -1:
            inner = rest[:end]
            return inner
        return value
    if "#" in value:
        in_quote = None
        for idx, char in enumerate(value):
            if in_quote:
                if char == in_quote:
                    in_quote = None
                continue
            if char in quote_chars:
                in_quote = char
                continue
            if char == "#":
                value = value[:idx].rstrip()
                break
    return value


def resolve_env_path(explicit: Optional[str]) -> Optional[str]:
    """Resolve the ``--env`` flag value to a concrete file path (or None)."""
    if explicit is None:
        return None
    if explicit == "":
        return os.path.join(os.getcwd(), ".env")
    return os.path.abspath(explicit)


def _candidate_files(explicit_path: Optional[str]) -> Iterable[Tuple[str, bool]]:
    """Yield (path, required) tuples in precedence order. Required files error
    if they are missing or unreadable; optional ones (the default ``./.env``
    when ``--env`` is given without a path) are silently skipped."""
    if explicit_path is None:
        return
    cwd_default = os.path.join(os.getcwd(), ".env")
    if explicit_path == cwd_default:
        if os.path.exists(explicit_path):
            yield explicit_path, False
        return
    yield explicit_path, True


def load_env(explicit: Optional[str]) -> Dict[str, str]:
    """Load configuration into :data:`os.environ`.

    ``explicit`` mirrors the ``--env`` flag:
      * ``None``      -> environment only, no file loaded.
      * ``""``        -> ``./.env`` (cwd); loaded if it exists, silently skipped
                        otherwise.
      * a path string -> that file; missing/unreadable raises :class:`EnvError`.

    Existing environment variables always take precedence over file values.

    Returns the effective configuration (the merged values currently in the
    environment for the keys this tool manages).
    """
    if explicit is not None and explicit != "":
        path = resolve_env_path(explicit)
        for file_path, required in _candidate_files(path):
            try:
                file_values = parse_env_file(file_path)
            except EnvError:
                if required:
                    raise
                continue
            for key, value in file_values.items():
                if key not in os.environ:
                    os.environ[key] = value
    elif explicit == "":
        path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(path):
            try:
                file_values = parse_env_file(path)
            except EnvError:
                pass
            else:
                for key, value in file_values.items():
                    if key not in os.environ:
                        os.environ[key] = value

    return {
        "TYPESAFE_API_KEY": os.environ.get("TYPESAFE_API_KEY", ""),
        "TYPESAFE_MODEL": os.environ.get("TYPESAFE_MODEL", "jev-latest"),
        "TYPESAFE_API_BASE": os.environ.get("TYPESAFE_API_BASE", "https://api.typesafe.ai"),
        "TYPESAFE_TIMEOUT": os.environ.get("TYPESAFE_TIMEOUT", "60"),
        "TYPESAFE_MAX_RETRIES": os.environ.get("TYPESAFE_MAX_RETRIES", "4"),
    }


def require_api_key() -> str:
    """Return the configured TypeSafe API key or raise :class:`EnvError`."""
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise EnvError(
            "TYPESAFE_API_KEY is not set. Set it in the environment, export it, "
            "or load it from a .env file with --env <path> (or --env with no "
            "argument for ./.env). See .env.example."
        )
    return key
