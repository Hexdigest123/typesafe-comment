"""Comment and code-structure extraction for Python."""

import ast
import io
import os
import tokenize
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple


class CommentAttachment(Enum):
    DOCSTRING = "docstring"
    BLOCK = "block"
    FLOATING = "floating"


@dataclass(frozen=True)
class Comment:
    file: str
    line: int
    column: int
    text: str
    kind: CommentAttachment
    structure_name: Optional[str] = None
    structure_type: Optional[str] = None
    structure_kind: Optional[str] = None
    code: Optional[str] = None


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
    end_line: int
    name: Optional[str]
    kind: str
    code: str


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


def _python_extract(source: str, file: str) -> Tuple[List[Comment], List[Comment]]:
    return extract_comments_from_source(source, file)


def _treesitter_extract(source: str, file: str) -> Tuple[List[Comment], List[Comment]]:
    from . import treesitter
    if not treesitter.is_available():
        return [], []
    return treesitter.extract(source, file)


_EXTRACTORS = {
    ".py": _python_extract,
}


def register_extractor(extension: str, extractor) -> None:
    """Register a comment extractor for a file extension.

    ``extractor`` is called as ``extractor(source, file)`` and must return
    ``(attached, floating)``. Python uses stdlib ``ast``; other languages
    delegate to the tree-sitter registry in :mod:`typesafe_comment.treesitter`.
    Registering an existing extension replaces it.
    """
    _EXTRACTORS[extension.lower()] = extractor


def _tree_sitter_extensions() -> frozenset:
    try:
        from . import treesitter
        if treesitter.is_available():
            return treesitter.SUPPORTED_EXTENSIONS
    except Exception:
        pass
    return frozenset()


def _supported_extensions() -> frozenset:
    return frozenset(_EXTRACTORS.keys()) | _tree_sitter_extensions()


def extract_comments(file: str) -> Tuple[List[Comment], List[Comment]]:
    ext = os.path.splitext(file)[1].lower()
    extractor = _EXTRACTORS.get(ext)
    if extractor is None and ext in _tree_sitter_extensions():
        extractor = _treesitter_extract
    if extractor is None:
        return [], []
    try:
        with open(file, "r", encoding="utf-8") as handle:
            source = handle.read()
    except (OSError, UnicodeDecodeError):
        return [], []
    return extractor(source, file)


def extract_comments_from_paths(
    paths: List[str],
    suffix: str = "",
) -> Tuple[List[Comment], List[Comment], List[str]]:
    attached: List[Comment] = []
    floating: List[Comment] = []
    visited: List[str] = []
    supported = _supported_extensions()

    def walk_file(path: str):
        if not os.path.isfile(path):
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in supported:
            return
        if suffix and not path.endswith(suffix):
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
