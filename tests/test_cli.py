import os

import pytest

from typesafe_comment.__main__ import main, _threshold_action


class FakeClient:
    def __init__(self, answer_for_heuristic):
        self.answer_for_heuristic = answer_for_heuristic

    def evaluate_score(self, state, questions):
        return {
            k: {
                "type": "score",
                "score": self.answer_for_heuristic[k],
                "probabilities": {"0": 0, "1": 0, "2": 0, "3": 1},
                "confidence": 0.8,
            }
            for k in questions
        }


def write_sample(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source)
    return str(path)


@pytest.fixture
def fake_client(monkeypatch):
    from typesafe_comment import run as run_module
    from typesafe_comment.classify import HEURISTICS

    client = FakeClient({k: 3 for k in HEURISTICS})
    monkeypatch.setattr(run_module, "_make_client_from_env", lambda: client)
    return client


def test_cli_pass_returns_zero(tmp_path, fake_client, capsys, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    path = write_sample(tmp_path, "good.py", "def f():\n    return 1  # ok comment\n")
    rc = main([path])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PASS" in out


def test_cli_fail_returns_minus_one(tmp_path, monkeypatch, capsys):
    from typesafe_comment import run as run_module
    from typesafe_comment.classify import HEURISTICS

    low = FakeClient({k: 0 for k in HEURISTICS})
    monkeypatch.setattr(run_module, "_make_client_from_env", lambda: low)
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    path = write_sample(tmp_path, "bad.py", "def f():\n    return 1  # bad\n")
    rc = main([path])
    out = capsys.readouterr().out
    assert rc == -1
    assert "FAIL" in out
    assert "bad.py:2:" in out


def test_cli_env_disambiguation_when_no_positional(tmp_path, fake_client, capsys, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    write_sample(tmp_path, "scanme.py", "def f():\n    return 1  # note\n")
    monkeypatch.chdir(tmp_path)
    rc = main(["--env", "scanme.py"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 file(s)" in out


def test_cli_env_explicit_path_with_positional(tmp_path, fake_client, capsys, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TYPESAFE_API_KEY=apikey_from_file\n")
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_from_env")
    path = write_sample(tmp_path, "scanme.py", "def f():\n    return 1  # note\n")
    rc = main(["--env", str(env_file), path])
    assert rc == 0


def test_cli_env_explicit_missing_path_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    path = write_sample(tmp_path, "scanme.py", "def f():\n    return 1  # note\n")
    rc = main(["--env", str(tmp_path / "missing.env"), path])
    err = capsys.readouterr().err
    assert rc == -1
    assert "env file not found" in err


def test_cli_missing_api_key_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    path = write_sample(tmp_path, "scanme.py", "def f():\n    return 1  # note\n")
    rc = main([path])
    err = capsys.readouterr().err
    assert rc == -1
    assert "TYPESAFE_API_KEY is not set" in err


def test_cli_no_paths_errors(tmp_path, fake_client, monkeypatch, capsys):
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    with pytest.raises(SystemExit):
        main([])


def test_cli_threshold_override(tmp_path, monkeypatch, capsys):
    from typesafe_comment import run as run_module
    from typesafe_comment.classify import HEURISTICS

    mid = FakeClient({k: 3 for k in HEURISTICS})
    mid.answer_for_heuristic["accuracy"] = 2
    monkeypatch.setattr(run_module, "_make_client_from_env", lambda: mid)
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    path = write_sample(tmp_path, "x.py", "def f():\n    return 1  # note\n")
    rc = main(["--threshold", "accuracy=0.9", path])
    out = capsys.readouterr().out
    assert rc == -1
    assert "accuracy score" in out


def test_cli_threshold_invalid_heuristic_rejected():
    with pytest.raises(Exception):
        _threshold_action("bogus=0.5")


def test_cli_threshold_out_of_range_rejected():
    with pytest.raises(Exception):
        _threshold_action("accuracy=1.5")


def test_cli_github_format(tmp_path, monkeypatch, capsys):
    from typesafe_comment import run as run_module
    from typesafe_comment.classify import HEURISTICS

    low = FakeClient({k: 0 for k in HEURISTICS})
    monkeypatch.setattr(run_module, "_make_client_from_env", lambda: low)
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    path = write_sample(tmp_path, "x.py", "def f():\n    return 1  # note\n")
    main(["--github", path])
    out = capsys.readouterr().out
    assert "::warning file=" in out


def test_cli_env_precedence_env_beats_file(tmp_path, monkeypatch, capsys, fake_client):
    env_file = tmp_path / ".env"
    env_file.write_text("TYPESAFE_API_KEY=apikey_from_file\n")
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_from_env")
    path = write_sample(tmp_path, "x.py", "def f():\n    return 1  # note\n")
    rc = main(["--env", str(env_file), path])
    assert rc == 0
    assert os.environ["TYPESAFE_API_KEY"] == "apikey_from_env"
