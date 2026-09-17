import io
import textwrap

from typesafe_comment.classify import HEURISTICS
from typesafe_comment.extractor import Comment, CommentAttachment
from typesafe_comment.run import evaluate_files


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
    path.write_text(textwrap.dedent(source))
    return str(path)


def make_comment(text, line, name, code):
    return Comment(
        file="x.py",
        line=line,
        column=4,
        text=text,
        kind=CommentAttachment.BLOCK,
        structure_name=name,
        structure_type="function",
        structure_kind="function",
        code=code,
    )


def test_evaluate_files_pass(tmp_path):
    path = write_sample(
        tmp_path,
        "good.py",
        '''
        def add(a, b):
            return a + b  # sum the inputs
        ''',
    )
    high = {k: 3 for k in HEURISTICS}
    client = FakeClient(high)
    out = io.StringIO()
    rc = evaluate_files([path], client=client, stream=out)
    text = out.getvalue()
    assert rc == 0
    assert "PASS" in text
    assert "warning:" not in text
    assert "0 floating comment(s) skipped" in text


def test_evaluate_files_fail_exit_minus_one(tmp_path):
    path = write_sample(
        tmp_path,
        "bad.py",
        '''
        def add(a, b):
            return a + b  # comment
        ''',
    )
    low = {k: 0 for k in HEURISTICS}
    client = FakeClient(low)
    out = io.StringIO()
    rc = evaluate_files([path], client=client, stream=out)
    text = out.getvalue()
    assert rc == -1
    assert "FAIL" in text
    assert "bad.py:3:" in text
    assert len([l for l in text.splitlines() if l.startswith("warning:")]) == len(HEURISTICS)


def test_evaluate_files_reports_floating_comments(tmp_path):
    path = write_sample(
        tmp_path,
        "floating.py",
        '''
        # TODO refactor this whole module
        # another stray note
        def add(a, b):
            return a + b  # sum
        ''',
    )
    high = {k: 3 for k in HEURISTICS}
    client = FakeClient(high)
    out = io.StringIO()
    rc = evaluate_files([path], client=client, stream=out)
    text = out.getvalue()
    assert rc == 0
    assert "2 floating comment(s) skipped" in text
    assert "floating.py:2:" in text
    assert "floating.py:3:" in text


def test_evaluate_files_github_format(tmp_path):
    path = write_sample(
        tmp_path,
        "bad.py",
        '''
        def add(a, b):
            return a + b  # comment
        ''',
    )
    low = {k: 0 for k in HEURISTICS}
    client = FakeClient(low)
    out = io.StringIO()
    evaluate_files([path], client=client, stream=out, github_format=True)
    text = out.getvalue()
    assert "::warning file=" in text
    assert ",line=3::accuracy" in text


def test_evaluate_files_quiet_suppresses_summary(tmp_path):
    path = write_sample(
        tmp_path,
        "good.py",
        '''
        def add(a, b):
            return a + b  # sum
        ''',
    )
    high = {k: 3 for k in HEURISTICS}
    client = FakeClient(high)
    out = io.StringIO()
    evaluate_files([path], client=client, stream=out, quiet=True)
    text = out.getvalue()
    assert "PASS" not in text
    assert "note:" not in text
    assert text == ""


def test_evaluate_files_directory_walk(tmp_path):
    sub = tmp_path / "pkg"
    sub.mkdir()
    write_sample(sub, "a.py", '''
    def a(x):
        return x  # a comment
    ''')
    write_sample(sub, "b.py", '''
    def b(x):
        return x  # b comment
    ''')
    high = {k: 3 for k in HEURISTICS}
    client = FakeClient(high)
    out = io.StringIO()
    rc = evaluate_files([str(tmp_path)], client=client, stream=out)
    text = out.getvalue()
    assert rc == 0
    assert "2 file(s)" in text


def test_evaluate_files_json_output(tmp_path):
    import json
    path = write_sample(
        tmp_path,
        "good.py",
        '''
        def add(a, b):
            return a + b  # sum the inputs
        ''',
    )
    high = {k: 3 for k in HEURISTICS}
    client = FakeClient(high)
    out = io.StringIO()
    rc = evaluate_files([path], client=client, stream=out, json_output=True)
    payload = json.loads(out.getvalue())
    assert rc == 0
    assert payload["summary"]["evaluated"] == 1
    assert payload["summary"]["failed"] is False
    result = payload["results"][0]
    assert result["file"].endswith("good.py")
    assert set(result["scores"].keys()) == set(HEURISTICS)
    assert all(v == 1.0 for v in result["scores"].values())
    assert result["warnings"] == []


def test_evaluate_files_json_output_fail(tmp_path):
    import json
    path = write_sample(
        tmp_path,
        "bad.py",
        '''
        def add(a, b):
            return a + b  # comment
        ''',
    )
    low = {k: 0 for k in HEURISTICS}
    client = FakeClient(low)
    out = io.StringIO()
    rc = evaluate_files([path], client=client, stream=out, json_output=True)
    payload = json.loads(out.getvalue())
    assert rc == -1
    assert payload["summary"]["failed"] is True
    assert len(payload["results"][0]["warnings"]) == len(HEURISTICS)
    assert "thresholds" in payload["summary"]
