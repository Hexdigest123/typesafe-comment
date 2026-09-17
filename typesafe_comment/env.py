"""Environment configuration for typesafe-comment."""

import os
from typing import Dict, Iterable, Optional, Tuple


class EnvError(Exception):
    pass


def parse_env_file(path: str) -> Dict[str, str]:
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
        values[key] = _strip_value(value)
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
            return rest[:end]
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


def _candidate_files(explicit: Optional[str]) -> Iterable[Tuple[str, bool]]:
    if explicit is None:
        return
    if explicit == "":
        path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(path):
            yield path, False
        return
    yield os.path.abspath(explicit), True


def load_env(explicit: Optional[str]) -> Dict[str, str]:
    for file_path, required in _candidate_files(explicit):
        try:
            file_values = parse_env_file(file_path)
        except EnvError:
            if required:
                raise
            continue
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
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise EnvError(
            "TYPESAFE_API_KEY is not set. Set it in the environment, export it, "
            "or load it from a .env file with --env <path> (or --env with no "
            "argument for ./.env). See .env.example."
        )
    return key
