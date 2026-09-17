"""End-to-end orchestration: extract -> classify -> report -> exit code.

``evaluate_files`` is the reusable core used by the CLI and by tests. It returns
``0`` on success and ``-1`` when any comment fell below a threshold (so the tool
blocks pipelines when used in a script, per the task spec).
"""

import json
import sys
from typing import IO, Any, Dict, List, Optional

from .classify import (
    HEURISTICS,
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
    json_output: bool = False,
) -> int:
    """Evaluate comments in ``paths`` and render a report.

    With ``json_output=True`` writes a JSON object (``results`` + ``floating`` +
    ``summary``) suitable for the eval harness; otherwise the linter-style text
    report. Returns ``0`` on success and ``-1`` if any comment fell below a
    threshold or a TypeSafe API call could not complete.
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

    if json_output:
        render_json(
            reports,
            floating,
            len(visited),
            failed,
            thresholds,
            stream=stream or sys.stdout,
        )
    else:
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


def render_json(
    reports: List[CommentReport],
    floating: List[Comment],
    visited_count: int,
    failed: bool,
    thresholds: Dict[str, float],
    *,
    stream: Optional[IO[str]] = None,
) -> None:
    """Write a JSON object with per-comment scores + warnings + floating list."""
    stream = stream or sys.stdout
    results = []
    for report in reports:
        c = report.item.comment
        results.append({
            "file": c.file,
            "line": c.line,
            "column": c.column,
            "text": c.text,
            "kind": c.kind.value,
            "structure_name": c.structure_name,
            "structure_type": c.structure_type,
            "structure_kind": c.structure_kind,
            "scores": {k: round(report.scores.get(k, 0.0), 4) for k in HEURISTICS},
            "confidences": {k: round(report.confidences.get(k, 0.0), 4) for k in HEURISTICS},
            "warnings": [
                {
                    "heuristic": w.heuristic,
                    "value": round(w.value, 4),
                    "threshold": w.threshold,
                }
                for w in report.warnings
            ],
            "failed": report.failed,
        })
    floating_out = [
        {
            "file": c.file,
            "line": c.line,
            "column": c.column,
            "text": c.text,
        }
        for c in sorted(floating, key=lambda x: (x.file, x.line))
    ]
    payload = {
        "results": results,
        "floating": floating_out,
        "summary": {
            "evaluated": len(results),
            "files": visited_count,
            "warnings": sum(len(r.warnings) for r in reports),
            "floating_skipped": len(floating),
            "failed": failed,
            "thresholds": thresholds,
        },
    }
    json.dump(payload, stream, indent=2, sort_keys=True)
    stream.write("\n")


def _state_for(comment: Comment) -> dict:
    from .classify import build_state

    return build_state(comment)
