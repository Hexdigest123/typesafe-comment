import pytest

from typesafe_comment.classify import (
    DEFAULT_THRESHOLDS,
    HEURISTICS,
    CommentItem,
    classify_comment,
    normalize_score,
    build_state,
    build_questions,
)
from typesafe_comment.extractor import Comment, CommentAttachment


class FakeClient:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def evaluate_score(self, state, questions):
        self.calls.append((state, questions))
        return self.answers


def make_comment(text="A useful comment.", line=5, kind=CommentAttachment.BLOCK, structure_name="add", code="def add(a, b):\n    return a + b"):
    return Comment(
        file="sample.py",
        line=line,
        column=4,
        text=text,
        kind=kind,
        structure_name=structure_name,
        structure_type="function",
        structure_kind="function",
        code=code,
    )


def make_answer(score, n_levels=4, confidence=0.8):
    probs = {str(i): (1.0 if i == int(round(score)) else 0.0) for i in range(n_levels)}
    probs[str(min(int(round(score)), n_levels - 1))] = 1.0
    return {"type": "score", "score": float(score), "probabilities": probs, "confidence": confidence}


def test_normalize_score_full_scale():
    value, conf = normalize_score({"type": "score", "score": 3, "probabilities": {"0": 0, "1": 0, "2": 0, "3": 1}, "confidence": 0.9})
    assert value == 1.0
    assert conf == 0.9


def test_normalize_score_zero():
    value, _ = normalize_score({"type": "score", "score": 0, "probabilities": {"0": 1, "1": 0, "2": 0, "3": 0}, "confidence": 0.5})
    assert value == 0.0


def test_normalize_score_clamps():
    value, _ = normalize_score({"type": "score", "score": 2, "probabilities": {"0": 0.25, "1": 0.25, "2": 0.5}})
    assert 0.0 <= value <= 1.0


def test_normalize_score_fallback_levels():
    value, _ = normalize_score({"type": "score", "score": 2, "confidence": 0.7})
    assert value == pytest.approx(2 / 3)


def test_normalize_score_rejects_missing_score():
    with pytest.raises(ValueError):
        normalize_score({"type": "score", "confidence": 0.5})


def test_build_state_includes_comment_and_code():
    comment = make_comment()
    state = build_state(comment)
    assert state["comment"] == "A useful comment."
    assert "def add(a, b):" in state["code"]
    assert state["structure"] == "function add"
    assert state["comment_kind"] == "block"


def test_build_questions_has_five_scores():
    questions = build_questions()
    assert set(questions.keys()) == set(HEURISTICS)
    for q in questions.values():
        assert q["type"] == "score"
        assert isinstance(q["criteria"], list)
        assert len(q["criteria"]) >= 2


def test_classify_comment_passing():
    answers = {k: make_answer(3) for k in HEURISTICS}
    client = FakeClient(answers)
    item = CommentItem(comment=make_comment(), state=build_state(make_comment()))
    report = classify_comment(item, client, DEFAULT_THRESHOLDS)
    assert not report.failed
    assert all(v == 1.0 for v in report.scores.values())
    assert report.warnings == []


def test_classify_comment_failing_emits_warning_per_heuristic():
    answers = {k: make_answer(0) for k in HEURISTICS}
    client = FakeClient(answers)
    item = CommentItem(comment=make_comment(), state=build_state(make_comment()))
    report = classify_comment(item, client, DEFAULT_THRESHOLDS)
    assert report.failed
    assert len(report.warnings) == len(HEURISTICS)
    for warning in report.warnings:
        assert warning.file == "sample.py"
        assert warning.line == 5
        assert warning.value == 0.0
        assert warning.threshold == DEFAULT_THRESHOLDS[warning.heuristic]


def test_classify_comment_only_low_coverage_fails():
    answers = {k: make_answer(3) for k in HEURISTICS}
    answers["coverage"] = make_answer(0)
    client = FakeClient(answers)
    item = CommentItem(comment=make_comment(), state=build_state(make_comment()))
    report = classify_comment(item, client, DEFAULT_THRESHOLDS)
    assert report.failed
    assert [w.heuristic for w in report.warnings] == ["coverage"]
    assert report.scores["coverage"] == 0.0


def test_classify_comment_respects_custom_thresholds():
    answers = {k: make_answer(3) for k in HEURISTICS}
    answers["accuracy"] = make_answer(2)
    client = FakeClient(answers)
    item = CommentItem(comment=make_comment(), state=build_state(make_comment()))
    strict = dict(DEFAULT_THRESHOLDS)
    strict["accuracy"] = 0.9
    report = classify_comment(item, client, strict)
    assert report.failed
    assert [w.heuristic for w in report.warnings] == ["accuracy"]


def test_classify_comment_threshold_examples_from_spec():
    answers = {
        "usefulness": make_answer(3),
        "readability": make_answer(3),
        "accuracy": make_answer(0),
        "redundancy": make_answer(3),
        "coverage": make_answer(1),
    }
    client = FakeClient(answers)
    item = CommentItem(comment=make_comment(), state=build_state(make_comment()))
    thresholds = {"accuracy": 0.25, "coverage": 0.1, "usefulness": 0.3, "readability": 0.3, "redundancy": 0.3}
    report = classify_comment(item, client, thresholds)
    assert report.failed
    failing = {w.heuristic for w in report.warnings}
    assert "accuracy" in failing
    assert "coverage" not in failing
