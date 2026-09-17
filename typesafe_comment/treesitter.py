"""Tree-sitter based comment extraction for multiple languages.

When the optional ``typesafe-comment[tree-sitter]`` extra is installed, this
module extracts comments and their enclosing function/class code from C, C++,
JavaScript, TypeScript (and TSX), Go, Rust, and Python using a real AST.

Design:
  * Comments are real AST nodes in every supported grammar, each carrying a
    byte range, so the comment text is sliced from the source bytes.
  * Function/class node ranges are collected; each comment is attached to its
    innermost enclosing function/class (or flagged floating at top level).
  * A comment that immediately *precedes* a function/class (with no blank-line
    gap, or one blank line) is treated as a doc comment for that function --
    this mirrors how ``/** */`` / ``///`` / JSDoc / godoc are written.

The Python path keeps using the stdlib :mod:`ast` extractor (which handles
docstrings as first-statement string literals, not preceding comments), so it
lives in :mod:`typesafe_comment.extractor`. This module covers the rest and is
only imported when tree-sitter is available and the file is not Python.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .extractor import Comment, CommentAttachment


try:
    from tree_sitter import Language, Parser
    import tree_sitter_c
    import tree_sitter_cpp
    import tree_sitter_go
    import tree_sitter_javascript
    import tree_sitter_python
    import tree_sitter_rust
    import tree_sitter_typescript

    _TREE_SITTER_AVAILABLE = True
except Exception:
    _TREE_SITTER_AVAILABLE = False


# Per-language grammar configuration.
#   extension -> (language factory, function node types, class node types,
#                 comment node types, block node type that holds the body,
#                 whether doc comments are preceding siblings)
_LANGUAGE_CONFIG: Dict[str, dict] = {
    ".c": {
        "language": lambda: Language(tree_sitter_c.language()),
        "functions": ("function_definition",),
        "classes": ("struct_specifier", "class_specifier", "union_specifier", "enum_specifier"),
        "comments": ("comment",),
        "block": "compound_statement",
        "preceding_doc": True,
        "name_node": "function_declarator",
    },
    ".h": {
        "language": lambda: Language(tree_sitter_c.language()),
        "functions": ("function_definition", "declaration"),
        "classes": ("struct_specifier", "class_specifier", "union_specifier", "enum_specifier"),
        "comments": ("comment",),
        "block": "compound_statement",
        "preceding_doc": True,
        "name_node": "function_declarator",
    },
    ".cc": {
        "language": lambda: Language(tree_sitter_cpp.language()),
        "functions": ("function_definition",),
        "classes": ("class_specifier", "struct_specifier", "union_specifier", "enum_specifier"),
        "comments": ("comment",),
        "block": "compound_statement",
        "preceding_doc": True,
        "name_node": "function_declarator",
    },
    ".cpp": {
        "language": lambda: Language(tree_sitter_cpp.language()),
        "functions": ("function_definition",),
        "classes": ("class_specifier", "struct_specifier", "union_specifier", "enum_specifier"),
        "comments": ("comment",),
        "block": "compound_statement",
        "preceding_doc": True,
        "name_node": "function_declarator",
    },
    ".cxx": {
        "language": lambda: Language(tree_sitter_cpp.language()),
        "functions": ("function_definition",),
        "classes": ("class_specifier", "struct_specifier", "union_specifier", "enum_specifier"),
        "comments": ("comment",),
        "block": "compound_statement",
        "preceding_doc": True,
        "name_node": "function_declarator",
    },
    ".hpp": {
        "language": lambda: Language(tree_sitter_cpp.language()),
        "functions": ("function_definition",),
        "classes": ("class_specifier", "struct_specifier", "union_specifier", "enum_specifier"),
        "comments": ("comment",),
        "block": "compound_statement",
        "preceding_doc": True,
        "name_node": "function_declarator",
    },
    ".js": {
        "language": lambda: Language(tree_sitter_javascript.language()),
        "functions": ("function_declaration", "generator_function_declaration", "method_definition", "arrow_function", "function"),
        "classes": ("class_declaration", "class"),
        "comments": ("comment",),
        "block": "statement_block",
        "preceding_doc": True,
        "name_node": None,
    },
    ".jsx": {
        "language": lambda: Language(tree_sitter_typescript.language_tsx()),
        "functions": ("function_declaration", "generator_function_declaration", "method_definition", "arrow_function", "function"),
        "classes": ("class_declaration", "class"),
        "comments": ("comment",),
        "block": "statement_block",
        "preceding_doc": True,
        "name_node": None,
    },
    ".mjs": {
        "language": lambda: Language(tree_sitter_javascript.language()),
        "functions": ("function_declaration", "generator_function_declaration", "method_definition", "arrow_function", "function"),
        "classes": ("class_declaration", "class"),
        "comments": ("comment",),
        "block": "statement_block",
        "preceding_doc": True,
        "name_node": None,
    },
    ".cjs": {
        "language": lambda: Language(tree_sitter_javascript.language()),
        "functions": ("function_declaration", "generator_function_declaration", "method_definition", "arrow_function", "function"),
        "classes": ("class_declaration", "class"),
        "comments": ("comment",),
        "block": "statement_block",
        "preceding_doc": True,
        "name_node": None,
    },
    ".ts": {
        "language": lambda: Language(tree_sitter_typescript.language_typescript()),
        "functions": ("function_declaration", "generator_function_declaration", "method_definition", "arrow_function", "function"),
        "classes": ("class_declaration", "class"),
        "comments": ("comment",),
        "block": "statement_block",
        "preceding_doc": True,
        "name_node": None,
    },
    ".go": {
        "language": lambda: Language(tree_sitter_go.language()),
        "functions": ("function_declaration", "method_declaration"),
        "classes": ("type_declaration",),
        "comments": ("comment",),
        "block": "block",
        "preceding_doc": True,
        "name_node": None,
        "plain_comment_is_doc": True,
    },
    ".rs": {
        "language": lambda: Language(tree_sitter_rust.language()),
        "functions": ("function_item",),
        "classes": ("struct_item", "enum_item", "trait_item", "impl_item", "union_item"),
        "comments": ("line_comment", "block_comment"),
        "block": "block",
        "preceding_doc": True,
        "name_node": None,
    },
}

SUPPORTED_EXTENSIONS = frozenset(_LANGUAGE_CONFIG.keys())


def is_available() -> bool:
    """Return True if tree-sitter and the grammar packages are importable."""
    return _TREE_SITTER_AVAILABLE


def supports_file(file: str) -> bool:
    """Return True if this extractor handles ``file`` by extension."""
    ext = os.path.splitext(file)[1].lower()
    return ext in _LANGUAGE_CONFIG


@dataclass
class _Range:
    name: Optional[str]
    kind: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int


def _node_text(node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


NAME_NODE_TYPES = ("identifier", "type_identifier", "property_identifier", "field_identifier", "type_name")


def _extract_name(node, source_bytes: bytes, name_node_type: Optional[str]) -> Optional[str]:
    if name_node_type:
        declarator = node.child_by_field_name("declarator")
        if declarator is not None:
            node = declarator
    name = node.child_by_field_name("name")
    if name is not None:
        return _node_text(name, source_bytes)
    for child in node.children:
        if child.type in NAME_NODE_TYPES:
            return _node_text(child, source_bytes)
        if child.type == name_node_type:
            for inner in child.children:
                if inner.type in NAME_NODE_TYPES:
                    return _node_text(inner, source_bytes)
    return None


def _walk_nodes(node, source_bytes: bytes, config: dict, structures: List[_Range]):
    if node.type in config["functions"]:
        kind = "method" if node.type == "method_definition" else "function"
        structures.append(_Range(
            name=_extract_name(node, source_bytes, config.get("name_node")),
            kind=kind,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
        ))
    elif node.type in config["classes"]:
        structures.append(_Range(
            name=_extract_name(node, source_bytes, config.get("name_node")),
            kind="class",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
        ))
    for child in node.children:
        _walk_nodes(child, source_bytes, config, structures)


def _find_comments(node, config: dict, comments: List):
    if node.type in config["comments"]:
        comments.append(node)
    for child in node.children:
        _find_comments(child, config, comments)


def _innermost_structure(structures: List[_Range], line: int) -> Optional[_Range]:
    candidates = [s for s in structures if s.start_line <= line <= s.end_line]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (-s.start_line, (s.end_line - s.start_line)))
    return candidates[0]


def _strip_comment_markers(text: str) -> Tuple[str, bool]:
    """Strip comment delimiters. Returns (text, is_doc).

    ``is_doc`` is True for ``/**``/``/*!`` (JSDoc/Doxygen), ``///`` or ``//!``
    (Rust/Doxygen inner doc) -- heuristics for "this is documentation, not a
    casual note".
    """
    raw = text
    is_doc = False
    if raw.startswith("///") or raw.startswith("//!"):
        is_doc = True
        body = raw.lstrip("/!").lstrip()
        return body, is_doc
    if raw.startswith("/**") or raw.startswith("/*!"):
        is_doc = True
        body = raw
        if body.startswith("/*"):
            body = body[3:]
        if body.endswith("*/"):
            body = body[:-2]
        if body.startswith("!"):
            body = body[1:]
        return body.strip(" *").strip(), is_doc
    if raw.startswith("/*"):
        body = raw[2:]
        if body.endswith("*/"):
            body = body[:-2]
        return body.strip(" *").strip(), is_doc
    if raw.startswith("//"):
        return raw[2:].strip(), is_doc
    if raw.startswith("#"):
        return raw[1:].strip(), is_doc
    return raw.strip(), is_doc


def _attach_preceding_doc(
    comments: List,
    structures: List[_Range],
    doc_candidate_ids: set,
) -> Dict[int, _Range]:
    """Map comment-node-id -> structure for comments that document the next
    function/class.

    Only comments in ``doc_candidate_ids`` are considered -- by default that is
    marker-style docs (``/** */``/``/*!``/``///``/``//!``). Go sets
    ``plain_comment_is_doc`` so a plain ``//`` directly preceding a ``func`` is
    treated as godoc. A plain ``//`` inside a function body stays a block
    comment of its container, not a doc for the next nested declaration.

    A doc comment attaches to the *next* structure whose start line follows it
    (within a small gap of <= 2 lines, no non-comment lines between), provided
    that structure is nested inside (or equal to) the comment's current
    container. This handles leading docs both at module level and inside a
    class body (a doc before a method).

    Some grammars (notably Rust's ``///``) include the trailing newline in the
    comment node's byte range, so we use the comment's *content* end line
    (``end_point[0]`` adjusted for a trailing-newline column of 0).
    """
    mapping: Dict[int, _Range] = {}
    structures_by_start = sorted(structures, key=lambda s: s.start_line)
    comment_lines = {c.start_point[0] + 1 for c in comments}

    def content_end_line(c) -> int:
        end_row = c.end_point[0]
        if c.end_point[1] == 0 and end_row > c.start_point[0]:
            end_row -= 1
        return end_row + 1

    for c in comments:
        if id(c) not in doc_candidate_ids:
            continue
        c_line = c.start_point[0] + 1
        containing = _innermost_structure(structures, c_line)
        c_end = content_end_line(c)
        for s in structures_by_start:
            if s.start_line <= c_end:
                continue
            if s.start_line - c_end > 2:
                break
            nested_ok = containing is None or (
                s.start_line >= containing.start_line and s.end_line <= containing.end_line and s is not containing
            )
            if not nested_ok:
                continue
            gap_ok = True
            for between in range(c_end + 1, s.start_line):
                if between in comment_lines:
                    continue
                gap_ok = False
                break
            if gap_ok:
                mapping[id(c)] = s
            break
    return mapping


def extract(source: str, file: str) -> Tuple[List[Comment], List[Comment]]:
    """Extract ``(attached, floating)`` comments via tree-sitter.

    Returns empty lists if tree-sitter is unavailable or the extension is
    unsupported.
    """
    if not _TREE_SITTER_AVAILABLE:
        return [], []
    ext = os.path.splitext(file)[1].lower()
    config = _LANGUAGE_CONFIG.get(ext)
    if config is None:
        return [], []

    language = config["language"]()
    parser = Parser(language)
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    root = tree.root_node

    structures: List[_Range] = []
    _walk_nodes(root, source_bytes, config, structures)

    comment_nodes: List = []
    _find_comments(root, config, comment_nodes)

    doc_ids: set = set()
    parsed_comments = []
    seen: set = set()
    for c in comment_nodes:
        key = (c.start_point[0], c.start_point[1])
        if key in seen:
            continue
        seen.add(key)
        raw = _node_text(c, source_bytes)
        text, is_doc = _strip_comment_markers(raw)
        if is_doc:
            doc_ids.add(id(c))
        parsed_comments.append((c, text, is_doc))

    plain_doc = config.get("plain_comment_is_doc", False)
    doc_candidate_ids = doc_ids if not plain_doc else {id(c) for c, _, _ in parsed_comments}
    preceding_doc = _attach_preceding_doc(comment_nodes, structures, doc_candidate_ids) if config["preceding_doc"] else {}

    attached: List[Comment] = []
    floating: List[Comment] = []

    for c, text, is_doc in parsed_comments:
        line = c.start_point[0] + 1
        col = c.start_point[1]

        target = preceding_doc.get(id(c))
        if target is not None:
            code = source_bytes[target.start_byte:target.end_byte].decode("utf-8", errors="replace")
            attached.append(Comment(
                file=file,
                line=line,
                column=col,
                text=text,
                kind=CommentAttachment.DOCSTRING,
                structure_name=target.name,
                structure_type=target.kind,
                structure_kind=target.kind,
                code=code,
            ))
            continue

        target = _innermost_structure(structures, line)
        if target is None:
            floating.append(Comment(
                file=file,
                line=line,
                column=col,
                text=text,
                kind=CommentAttachment.FLOATING,
            ))
            continue

        code = source_bytes[target.start_byte:target.end_byte].decode("utf-8", errors="replace")
        attached.append(Comment(
            file=file,
            line=line,
            column=col,
            text=text,
            kind=CommentAttachment.BLOCK,
            structure_name=target.name,
            structure_type=target.kind,
            structure_kind=target.kind,
            code=code,
        ))

    return attached, floating
