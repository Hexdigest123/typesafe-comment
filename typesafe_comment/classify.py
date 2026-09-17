"""Comment classification via TypeSafe's System One ``score`` primitive."""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from .client import TypeSafeClient
from .extractor import Comment


HEURISTICS = ("usefulness", "readability", "accuracy", "redundancy", "coverage")

HEURISTIC_LABELS: Dict[str, str] = {
    "usefulness": "usefulness",
    "readability": "readability",
    "accuracy": "accuracy",
    "redundancy": "redundancy",
    "coverage": "coverage",
}

DEFAULT_THRESHOLDS: Dict[str, float] = {
    "usefulness": 0.3,
    "readability": 0.3,
    "accuracy": 0.25,
    "redundancy": 0.25,
    "coverage": 0.1,
}

HEURISTIC_LEVELS: Dict[str, List[str]] = {
    "usefulness": [
        "Vacuous or placeholder; conveys no meaningful information (e.g. 'Function.', 'Does a thing.').",
        "Minimal but states something true and specific about the code.",
        "Documents intent, behavior, inputs, outputs, or contracts meaningfully.",
        "Provides valuable context, rationale, or non-obvious detail the reader needs.",
    ],
    "readability": [
        "Confusing, broken, or hard to parse.",
        "Understandable but awkward, verbose, or poorly worded.",
        "Clear and well-formed.",
        "Concise, precise, and easy to read.",
    ],
    "accuracy": [
        "Contradicts what the code does.",
        "Mostly wrong or misleading about the code.",
        "Broadly correct with minor inaccuracies.",
        "Accurately describes what the code does.",
    ],
    "redundancy": [
        "Purely redundant: repeats the code verbatim.",
        "Mostly restates the code with little added value.",
        "Some redundancy but adds useful framing.",
        "Non-redundant: adds information the code does not show.",
    ],
    "coverage": [
        "Documents nothing important about the code.",
        "Documents only a small or minor aspect.",
        "Documents the main points adequately.",
        "Comprehensively documents the important aspects.",
    ],
}

HEURISTIC_INSTRUCTIONS: Dict[str, str] = {
    "usefulness": (
        "Rate how useful this code comment is given the accompanying code. "
        "A comment is useful when it conveys meaningful information about the "
        "code's intent, behavior, or contract. A vacuous or placeholder comment "
        "is not useful. A comment that accurately and specifically states what "
        "the code does is at least somewhat useful, even for simple code; only "
        "comments that convey nothing meaningful should score low."
    ),
    "readability": (
        "Rate how readable this code comment is on its own: clarity, "
        "conciseness, grammar, and structure of the comment text."
    ),
    "accuracy": (
        "Rate how accurately this comment describes the accompanying code. "
        "An accurate comment matches what the code actually does."
    ),
    "redundancy": (
        "Rate how non-redundant this comment is. A non-redundant comment adds "
        "information the code does not already show; a redundant one merely "
        "restates the code. High score means low redundancy."
    ),
    "coverage": (
        "Rate how well this comment covers the important aspects of the "
        "accompanying code (inputs, behavior, side effects, contracts)."
    ),
}


@dataclass
class CommentItem:
    comment: Comment
    state: Dict[str, Any]

    @property
    def location(self) -> str:
        return "{}:{}".format(self.comment.file, self.comment.line)


@dataclass
class Warning:
    file: str
    line: int
    heuristic: str
    value: float
    threshold: float

    @property
    def location(self) -> str:
        return "{}:{}".format(self.file, self.line)


@dataclass
class CommentReport:
    item: CommentItem
    scores: Dict[str, float]
    confidences: Dict[str, float] = field(default_factory=dict)
    warnings: List[Warning] = field(default_factory=list)

    @property
    def location(self) -> str:
        return self.item.location

    @property
    def failed(self) -> bool:
        return bool(self.warnings)


_EXTENSION_LANGUAGE = {
    ".py": "python",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".js": "javascript",
    ".jsx": "typescript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".go": "go",
    ".rs": "rust",
}


def _language_of(file: str) -> str:
    ext = os.path.splitext(file)[1].lower()
    return _EXTENSION_LANGUAGE.get(ext, "unknown")


def build_state(comment: Comment) -> Dict[str, Any]:
    structure_type = comment.structure_type or "module"
    structure_name = comment.structure_name
    header = structure_type
    if structure_name:
        header = "{} {}".format(structure_type, structure_name)
    return {
        "language": _language_of(comment.file),
        "comment_kind": comment.kind.value,
        "structure": header,
        "comment": comment.text,
        "code": comment.code or "",
    }


def build_questions() -> Dict[str, Dict[str, Any]]:
    questions: Dict[str, Dict[str, Any]] = {}
    for key in HEURISTICS:
        questions[key] = {
            "type": "score",
            "instructions": HEURISTIC_INSTRUCTIONS[key],
            "criteria": HEURISTIC_LEVELS[key],
        }
    return questions


def normalize_score(answer: Dict[str, Any]) -> Tuple[float, float]:
    raw = answer.get("score")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("TypeSafe score answer missing numeric 'score' field: {!r}".format(answer))
    raw = float(raw)
    probabilities = answer.get("probabilities")
    n_levels = 0
    if isinstance(probabilities, dict):
        n_levels = len(probabilities)
    if n_levels <= 1:
        n_levels = 4
    normalized = raw / (n_levels - 1) if n_levels > 1 else 0.0
    normalized = max(0.0, min(1.0, normalized))
    confidence = answer.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence_value = 0.0
    else:
        confidence_value = float(confidence)
    return normalized, max(0.0, min(1.0, confidence_value))


def classify_comment(
    item: CommentItem,
    client: TypeSafeClient,
    thresholds: Dict[str, float],
) -> CommentReport:
    answers = client.evaluate_score(item.state, build_questions())
    scores: Dict[str, float] = {}
    confidences: Dict[str, float] = {}
    for key in HEURISTICS:
        answer = answers.get(key)
        if not isinstance(answer, dict):
            raise ValueError("TypeSafe answer for '{}' is not an object: {!r}".format(key, answer))
        if answer.get("type") != "score":
            raise ValueError("TypeSafe answer for '{}' is not a score: {!r}".format(key, answer))
        value, confidence = normalize_score(answer)
        scores[key] = value
        confidences[key] = confidence

    warnings: List[Warning] = []
    for key in HEURISTICS:
        threshold = thresholds.get(key, DEFAULT_THRESHOLDS.get(key, 0.0))
        if scores[key] < threshold:
            warnings.append(
                Warning(
                    file=item.comment.file,
                    line=item.comment.line,
                    heuristic=key,
                    value=scores[key],
                    threshold=threshold,
                )
            )

    return CommentReport(item=item, scores=scores, confidences=confidences, warnings=warnings)
