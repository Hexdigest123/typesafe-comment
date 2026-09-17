"""Comment and code-structure extraction.

The TypeSafe classifier needs, per comment, the comment text and the code of
the enclosing function/class. This module finds Python comments with
:mod:`tokenize`, then attaches each comment to the nearest enclosing function or
class node from :mod:`ast`.

Comments with no enclosing function/class (free-standing, flying around at
module level) are *detected and reported* but *not evaluated* -- there is no
associated code to judge the comment against, so a classification would be
meaningless. A summary of these "floating" comments is surfaced to the user at
the end of the run, per the task spec.
"""

import ast
import io
import os
import tokenize
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple


class CommentAttachment(Enum):
    """Where a comment sits relative to the code structure."""

    DOCSTRING = "docstring"
    """A docstring (string statement as the first statement of a function/class/module)."""

    BLOCK = "block"
    """An inline comment inside the body of a function or class."""

    FLOATING = "floating"
    """At module level, outside any function or class -- no associated code."""


@dataclass(frozen=True)
class Comment:
    """A single comment discovered in a source file."""

    file: str
    line: int
    """1-based line number where the comment starts."""

    column: int
    """0-based column where the comment starts."""

    text: str
    """The comment text including its leading ``#`` (docstrings: the raw string)."""

    kind: CommentAttachment
    """Where the comment sits relative to code structure."""

    structure_name: Optional[str] = None
    """``func``/``Class`` name the comment belongs to, or ``None`` when floating."""

    structure_type: Optional[str] = None
    """``function``, ``class`` or ``module`` for docstrings; ``None`` otherwise."""

    structure_kind: Optional[str] = None
    """``function``/``async function``/``class``; ``None`` for floating comments."""

    code: Optional[str] = None
    """The source of the enclosing function/class (with the comment included)."""


@dataclass
class _NodeRange:
    name: Optional[str]
    kind: str
    start: int
    end: int
    code: str


@dataclass
class _DocstringRange:
    line: int
    """1-based line of the docstring statement (for location + overlap)."""

    end_line: int
    """1-based last line of the docstring statement."""

    name: Optional[str]
    kind: str
    """Container kind: function / async function / class / module."""

    code: str
    """Full source of the enclosing container (for the classifier)."""


def _kind_of(node: ast.AST) -> str:
    if isinstance(node, ast.AsyncFunctionDef):
        return "async function"
    if isinstance(node, (ast.FunctionDef, ast.Lambda)):
        return "function"
    if isinstance(node, ast.ClassDef):
        return "class"
    return "other"


def _node_name(node: ast.AST) -> Optional[str]:
    name = getattr(node, "name", None)
    if isinstance(name, str):
        return name
    return None


def _collect_structures(tree: ast.AST, source_lines: List[str]) -> List[_NodeRange]:
    structures: List[_NodeRange] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = node.lineno
        end = max(getattr(node, "end_lineno", node.lineno), node.lineno)
        try:
            segment = "\n".join(source_lines[start - 1: end])
        except IndexError:
            segment = ""
        structures.append(
            _NodeRange(
                name=_node_name(node),
                kind=_kind_of(node),
                start=start,
                end=end,
                code=segment,
            )
        )
    return structures


def _contains(structure: _NodeRange, line: int) -> bool:
    if structure.kind == "class":
        return structure.start <= line <= structure.end
    if structure.kind == "function" or structure.kind == "async function":
        return structure.start < line <= structure.end
    return structure.start <= line <= structure.end


def _innermost(structures: List[_NodeRange], line: int) -> Optional[_NodeRange]:
    """Return the narrowest function/class node whose body contains ``line``.

    The innermost container is the most deeply nested one: in Python a nested
    function/class always starts after its parent, so we prefer the largest
    ``start`` (deepest), then the smallest span (narrowest), then a function over
    a class at the same site.
    """
    candidates = [s for s in structures if _contains(s, line)]
    if not candidates:
        return None
    candidates.sort(
        key=lambda s: (-s.start, (s.end - s.start), 0 if s.kind in ("function", "async function") else 1)
    )
    return candidates[0]


def _strip_comment(text: str) -> str:
    text = text.strip()
    if text.startswith("#"):
        text = text[1:]
    return text.strip()


def _docstring_nodes(tree: ast.AST, source_lines: List[str]) -> List[_DocstringRange]:
    """Collect function/class/module docstrings so they are not double-counted."""
    docstrings: List[_DocstringRange] = []

    def add(container: ast.AST, body: List[ast.stmt], kind: str, name: Optional[str],
            container_start: int, container_end: int):
        if not body:
            return
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                start = max(getattr(first, "lineno", 0), 0)
                end = max(getattr(first, "end_lineno", start), start)
                full_code = "\n".join(source_lines[container_start - 1:container_end]) if source_lines else ""
                docstrings.append(
                    _DocstringRange(
                        line=start,
                        end_line=end,
                        name=name,
                        kind=kind,
                        code=full_code,
                    )
                )

    module_end = max(getattr(tree, "end_lineno", len(source_lines)), len(source_lines))
    add(tree, getattr(tree, "body", []), "module", None, 1, module_end)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno
            end = max(getattr(node, "end_lineno", start), start)
            add(node, node.body, _kind_of(node), _node_name(node), start, end)
    return docstrings


def _overlaps_docstring(docstrings: List[_DocstringRange], line: int) -> bool:
    return any(d.line <= line <= d.end_line for d in docstrings)


def _tokenize_comments(source: str) -> List[Tuple[int, int, str]]:
    """Return ``[(line, col, comment_text)]`` for every ``#`` comment token."""
    comments: List[Tuple[int, int, str]] = []
    reader = io.StringIO(source).readline
    try:
        for tok in tokenize.generate_tokens(reader):
            if tok.type == tokenize.COMMENT:
                comments.append((tok.start[0], tok.start[1], tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return comments
    return comments


def extract_comments_from_source(source: str, file: str) -> Tuple[List[Comment], List[Comment]]:
    """Extract comments from Python source text.

    Returns ``(attached, floating)`` where ``attached`` are comments linked to a
    function/class (docstrings and block comments) and ``floating`` are comments
    at module level with no associated code.
    """
    try:
        tree = ast.parse(source, filename=file)
    except SyntaxError:
        return [], []

    source_lines = source.splitlines()
    structures = _collect_structures(tree, source_lines)
    docstrings = _docstring_nodes(tree, source_lines)
    token_comments = _tokenize_comments(source)

    attached: List[Comment] = []
    floating: List[Comment] = []
    seen: set = set()

    for line, col, text in token_comments:
        key = (line, col, text)
        if key in seen:
            continue
        seen.add(key)

        if _overlaps_docstring(docstrings, line):
            continue

        structure = _innermost(structures, line)
        if structure is None:
            floating.append(
                Comment(
                    file=file,
                    line=line,
                    column=col,
                    text=_strip_comment(text),
                    kind=CommentAttachment.FLOATING,
                )
            )
            continue

        attached.append(
            Comment(
                file=file,
                line=line,
                column=col,
                text=_strip_comment(text),
                kind=CommentAttachment.BLOCK,
                structure_name=structure.name,
                structure_type=structure.kind,
                structure_kind=structure.kind,
                code=structure.code,
            )
        )

    for d in docstrings:
        if d.kind == "module":
            continue
        doc_text = "\n".join(source_lines[d.line - 1:d.end_line]) if source_lines else ""
        attached.append(
            Comment(
                file=file,
                line=d.line,
                column=0,
                text=doc_text.strip().strip('"""').strip("'''").strip(),
                kind=CommentAttachment.DOCSTRING,
                structure_name=d.name,
                structure_type=d.kind,
                structure_kind=d.kind,
                code=d.code,
            )
        )

    return attached, floating


def extract_comments(file: str) -> Tuple[List[Comment], List[Comment]]:
    """Read ``file`` and return ``(attached, floating)`` comments.

    Non-``.py`` files are skipped and return empty lists.
    """
    if not file.endswith(".py"):
        return [], []
    try:
        with open(file, "r", encoding="utf-8") as handle:
            source = handle.read()
    except (OSError, UnicodeDecodeError):
        return [], []
    return extract_comments_from_source(source, file)


def extract_comments_from_paths(
    paths: List[str],
    suffix: str = ".py",
) -> Tuple[List[Comment], List[Comment], List[str]]:
    """Walk ``paths`` (files and directories) and collect comments.

    Returns ``(attached, floating, visited)``. Directories are walked
    recursively; only ``.py`` files are read.
    """
    attached: List[Comment] = []
    floating: List[Comment] = []
    visited: List[str] = []

    def walk_file(path: str):
        if not os.path.isfile(path):
            return
        if not path.endswith(suffix):
            return
        visited.append(path)
        a, f = extract_comments(path)
        attached.extend(a)
        floating.extend(f)

    for path in paths:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", ".venv", "venv", "env", "node_modules", ".tox", ".nox", "build", "dist")]
                for name in sorted(files):
                    walk_file(os.path.join(root, name))
        else:
            walk_file(path)

    return attached, floating, visited
