"""Formatting of classification results into linter-style output."""

import sys
from typing import List

from .classify import CommentReport, Warning
from .extractor import Comment


def format_warning(warning: Warning) -> str:
    """Format a single threshold failure like a linter finding."""
    return "warning: {}:{}: {} score {:.2f} below threshold {:.2f}".format(
        warning.file,
        warning.line,
        warning.heuristic,
        warning.value,
        warning.threshold,
    )


def format_warning_github(warning: Warning) -> str:
    """Format a warning using GitHub's ``::warning`` command syntax."""
    return "::warning file={},line={}::{} score {:.2f} below threshold {:.2f}".format(
        warning.file,
        warning.line,
        warning.heuristic,
        warning.value,
        warning.threshold,
    )


def format_reports(reports: List[CommentReport], github_format: bool = False) -> List[str]:
    """Return one output line per warning, sorted by file then line."""
    formatter = format_warning_github if github_format else format_warning
    warnings: List[Warning] = []
    for report in reports:
        warnings.extend(report.warnings)
    warnings.sort(key=lambda w: (w.file, w.line, w.heuristic))
    return [formatter(w) for w in warnings]


def format_floating_summary(floating: List[Comment]) -> List[str]:
    """Build the end-of-run note about skipped floating comments.

    Floating comments are comments outside any function/class; there is no
    associated code to judge them against, so they are not evaluated. We still
    tell the user where they are so nothing is silently dropped.
    """
    lines: List[str] = []
    if not floating:
        return lines
    lines.append(
        "note: {} comment(s) outside any function or class were skipped (no "
        "associated code to evaluate against):".format(len(floating))
    )
    for comment in sorted(floating, key=lambda c: (c.file, c.line)):
        snippet = comment.text.replace("\n", " ")
        if len(snippet) > 60:
            snippet = snippet[:57] + "..."
        lines.append("  {}:{}: {}".format(comment.file, comment.line, snippet))
    return lines


def format_summary(
    reports: List[CommentReport],
    floating_count: int,
    visited_count: int,
    failed: bool,
) -> List[str]:
    """Build the end-of-run summary line(s)."""
    total = len(reports)
    warning_count = sum(len(r.warnings) for r in reports)
    lines: List[str] = []
    lines.append(
        "typesafe-comment: evaluated {} comment(s) across {} file(s); "
        "{} warning(s); {} floating comment(s) skipped".format(
            total, visited_count, warning_count, floating_count
        )
    )
    if failed:
        lines.append("typesafe-comment: FAIL (one or more comments below threshold)")
    else:
        lines.append("typesafe-comment: PASS")
    return lines


def render_report(
    reports: List[CommentReport],
    floating: List[Comment],
    visited_count: int,
    failed: bool,
    *,
    stream=None,
    github_format: bool = False,
    quiet: bool = False,
) -> None:
    """Write the full report (warnings + floating note + summary) to ``stream``."""
    stream = stream or sys.stdout
    warning_lines = format_reports(reports, github_format=github_format)
    for line in warning_lines:
        stream.write(line + "\n")
    if not quiet:
        floating_lines = format_floating_summary(floating)
        for line in floating_lines:
            stream.write(line + "\n")
        summary_lines = format_summary(reports, len(floating), visited_count, failed)
        for line in summary_lines:
            stream.write(line + "\n")
