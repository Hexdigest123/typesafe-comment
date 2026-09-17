import os
import textwrap

import pytest

from typesafe_comment.env import EnvError, parse_env_file, load_env, require_api_key


def write_env(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(textwrap.dedent(text))
    return str(path)


def test_parse_env_file_basic(tmp_path):
    path = write_env(
        tmp_path,
        """
        # a comment
        TYPESAFE_API_KEY=apikey_123
        TYPESAFE_MODEL=jev-latest
        export TYPESAFE_TIMEOUT=90
        # trailing
        """,
    )
    values = parse_env_file(path)
    assert values["TYPESAFE_API_KEY"] == "apikey_123"
    assert values["TYPESAFE_MODEL"] == "jev-latest"
    assert values["TYPESAFE_TIMEOUT"] == "90"


def test_parse_env_file_quotes_and_inline_comments(tmp_path):
    path = write_env(
        tmp_path,
        '''
        TYPESAFE_API_KEY="secret key # not a comment"
        TYPESAFE_MODEL='jev-latest'  # inline comment
        TYPESAFE_BASE=https://api.typesafe.ai  # endpoint
        ''',
    )
    values = parse_env_file(path)
    assert values["TYPESAFE_API_KEY"] == "secret key # not a comment"
    assert values["TYPESAFE_MODEL"] == "jev-latest"
    assert values["TYPESAFE_BASE"] == "https://api.typesafe.ai"


def test_parse_env_file_missing_raises(tmp_path):
    with pytest.raises(EnvError):
        parse_env_file(str(tmp_path / "nope.env"))


def test_parse_env_file_invalid_line(tmp_path):
    path = write_env(tmp_path, "BROKEN_LINE_NO_EQUALS\n")
    with pytest.raises(EnvError):
        parse_env_file(path)


def test_load_env_env_precedence_over_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "from_env")
    path = write_env(tmp_path, "TYPESAFE_API_KEY=from_file\nTYPESAFE_MODEL=jev-latest\n")
    cfg = load_env(path)
    assert cfg["TYPESAFE_API_KEY"] == "from_env"
    assert cfg["TYPESAFE_MODEL"] == "jev-latest"
    assert os.environ["TYPESAFE_MODEL"] == "jev-latest"


def test_load_env_default_path_when_no_path_given(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("TYPESAFE_API_KEY=from_default_file\n")
    cfg = load_env("")
    assert cfg["TYPESAFE_API_KEY"] == "from_default_file"


def test_load_env_default_path_missing_is_silent(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    cfg = load_env("")
    assert cfg["TYPESAFE_API_KEY"] == ""


def test_load_env_explicit_path_required(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(EnvError):
        load_env(str(tmp_path / "missing.env"))


def test_load_env_none_loads_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("TYPESAFE_API_KEY=should_not_load\n")
    cfg = load_env(None)
    assert cfg["TYPESAFE_API_KEY"] == ""


def test_require_api_key_missing(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(EnvError):
        require_api_key()


def test_require_api_key_present(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_xyz")
    assert require_api_key() == "apikey_xyz"
