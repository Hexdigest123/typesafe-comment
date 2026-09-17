"""Environment configuration for typesafe-comment (via python-dotenv)."""

import os
from typing import Dict, Optional

from dotenv import load_dotenv


class EnvError(Exception):
    pass


def parse_env_file(path: str) -> Dict[str, str]:
    from dotenv import dotenv_values

    if not os.path.exists(path):
        raise EnvError("env file not found: {}".format(path))
    values = dotenv_values(path)
    return {k: v for k, v in values.items() if v is not None}


def _resolve_path(explicit: Optional[str]) -> Optional[str]:
    if explicit is None:
        return None
    if explicit == "":
        return os.path.join(os.getcwd(), ".env")
    return os.path.abspath(explicit)


def load_env(explicit: Optional[str]) -> Dict[str, str]:
    path = _resolve_path(explicit)
    if path is not None:
        required = explicit not in (None, "")
        if required and not os.path.exists(path):
            raise EnvError("env file not found: {}".format(path))
        load_dotenv(path, override=False)

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
