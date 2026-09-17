"""End-to-end orchestration: extract -> classify -> report -> exit code.

``evaluate_files`` is the reusable core used by the CLI and by tests. It returns
``0`` on success and ``-1`` when any comment fell below a threshold (so the tool
blocks pipelines when used in a script, per the task spec).
"""

import sys
from typing import IO, List, Optional

from .classify import (
    CommentItem,
    CommentReport,
    DEFAULT_THRESHOLDS,
    classify_comment,
)
from .client import TypeSafeClient, TypeSafeError
from .extractor import Comment, extract_comments_from_paths
from .report import render_report


def _make_client_from_env() -> TypeSafeClient:
    import os

    from .env import require_api_key

    api_key = require_api_key()
    base_url = os.environ.get("TYPESAFE_API_BASE", "https://api.typesafe.ai")
    model = os.environ.get("TYPESAFE_MODEL", "jev-latest")
    try:
        timeout = int(os.environ.get("TYPESAFE_TIMEOUT", "60"))
    except ValueError:
        timeout = 60
    try:
        max_retries = int(os.environ.get("TYPESAFE_MAX_RETRIES", "4"))
    except ValueError:
        max_retries = 4
    return TypeSafeClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
        max_retries=max_retries,
    )


def evaluate_files(
    paths: List[str],
    *,
    thresholds: Optional[dict] = None,
    client: Optional[TypeSafeClient] = None,
    stream: Optional[IO[str]] = None,
    github_format: bool = False,
    quiet: bool = False,
) -> int:
    """Evaluate comments in ``paths`` and render a linter report.

    Returns ``0`` on success and ``-1`` if any comment fell below a threshold or
    a TypeSafe API call could not complete (so CI pipelines fail loudly).
    """
    thresholds = thresholds or dict(DEFAULT_THRESHOLDS)
    attached, floating, visited = extract_comments_from_paths(paths)

    owns_client = client is None
    if owns_client:
        try:
            client = _make_client_from_env()
        except Exception as exc:
            sys.stderr.write("typesafe-comment: error: {}\n".format(exc))
            return -1
    assert client is not None

    reports: List[CommentReport] = []
    api_error = False
    for comment in attached:
        item = CommentItem(comment=comment, state=_state_for(comment))
        try:
            report = classify_comment(item, client, thresholds)
        except TypeSafeError as exc:
            sys.stderr.write(
                "typesafe-comment: error classifying {}:{}: {}\n".format(
                    comment.file, comment.line, exc
                )
            )
            api_error = True
            continue
        except ValueError as exc:
            sys.stderr.write(
                "typesafe-comment: error parsing result for {}:{}: {}\n".format(
                    comment.file, comment.line, exc
                )
            )
            api_error = True
            continue
        reports.append(report)

    failed = any(r.failed for r in reports) or api_error
    render_report(
        reports,
        floating,
        len(visited),
        failed,
        stream=stream or sys.stdout,
        github_format=github_format,
        quiet=quiet,
    )
    return -1 if failed else 0


def _state_for(comment: Comment) -> dict:
    from .classify import build_state

    return build_state(comment)
