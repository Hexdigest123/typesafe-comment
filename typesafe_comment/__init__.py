"""typesafe-comment: lint code comments with TypeSafe's System One decision model."""

from .classify import (
    HEURISTIC_LABELS,
    DEFAULT_THRESHOLDS,
    CommentItem,
    CommentReport,
    Warning,
    classify_comment,
)
from .client import TypeSafeClient, TypeSafeError
from .env import EnvError, load_env, parse_env_file
from .extractor import Comment, CommentAttachment, extract_comments
from .report import render_report
from .run import evaluate_files

__all__ = [
    "HEURISTIC_LABELS",
    "DEFAULT_THRESHOLDS",
    "CommentItem",
    "CommentReport",
    "Warning",
    "classify_comment",
    "TypeSafeClient",
    "TypeSafeError",
    "EnvError",
    "load_env",
    "parse_env_file",
    "Comment",
    "CommentAttachment",
    "extract_comments",
    "render_report",
    "evaluate_files",
    "__version__",
]

__version__ = "0.1.0"
