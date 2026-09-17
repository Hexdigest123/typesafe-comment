"""Tree-sitter comment extraction, registry-driven and not hard-coded.

Languages are described by :class:`LanguageSpec` entries in the
:data:`LANGUAGES` registry. Each spec points at a grammar loader and the
tree-sitter node types that mark functions, classes, and comments for that
language. File extensions are mapped to languages through :data:`EXTENSIONS`,
so adding a language or an extension is a data change, not a code change.

Grammar imports are lazy and isolated per language: if a grammar package is
missing, only that language is unavailable instead of disabling tree-sitter
support entirely.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .extractor import Comment, CommentAttachment


NAME_NODE_TYPES = (
    "identifier",
    "type_identifier",
    "property_identifier",
    "field_identifier",
    "type_name",
)


@dataclass(frozen=True)
class LanguageSpec:
    """Declarative description of how to extract comments from a language."""

    name: str
    extensions: Tuple[str, ...]
    grammar: str
    functions: Tuple[str, ...]
    classes: Tuple[str, ...]
    comments: Tuple[str, ...]
    block: str
    preceding_doc: bool = True
    name_node: Optional[str] = None
    plain_comment_is_doc: bool = False


def _load_grammar(module_name: str):
    module = importlib.import_module(module_name)

    language_tsx = getattr(module, "language_tsx", None)
    tsx = language_tsx() if callable(language_tsx) else None

    language_typescript = getattr(module, "language_typescript", None)
    typescript = language_typescript() if callable(language_typescript) else None

    if tsx is not None or typescript is not None:
        return {"default": typescript or tsx, "typescript": typescript, "tsx": tsx}

    language = getattr(module, "language", None)
    if not callable(language):
        raise ImportError(
            "grammar module {!r} exposes no language(), language_typescript(), "
            "or language_tsx() callable".format(module_name)
        )
    return language()


LANGUAGES: Dict[str, LanguageSpec] = {}
_EXTENSIONS: Dict[str, str] = {}
_GRAMMAR_CACHE: Dict[str, object] = {}


def register_language(spec: LanguageSpec) -> None:
    """Register a language and its file extensions.

    Re-registering an existing language replaces it. Extensions are mapped to
    the (last) language that claims them.
    """
    LANGUAGES[spec.name] = spec
    for ext in spec.extensions:
        _EXTENSIONS[ext.lower()] = spec.name


def _language_for(file: str) -> Optional[LanguageSpec]:
    ext = os.path.splitext(file)[1].lower()
    name = _EXTENSIONS.get(ext)
    return LANGUAGES.get(name) if name else None


def _grammar_for(spec: LanguageSpec):
    cached = _GRAMMAR_CACHE.get(spec.name)
    if cached is not None:
        return cached
    try:
        from tree_sitter import Language
    except Exception as exc:
        raise ImportError("tree-sitter runtime is not installed: {}".format(exc))
    grammar = _load_grammar(spec.grammar)
    if isinstance(grammar, dict):
        loaded = {
            key: Language(value)
            for key, value in grammar.items()
            if value is not None
        }
    else:
        loaded = Language(grammar)
    _GRAMMAR_CACHE[spec.name] = loaded
    return loaded


def is_available() -> bool:
    try:
        import tree_sitter  # noqa: F401
    except Exception:
        return False
    return True


def supports_file(file: str) -> bool:
    return _language_for(file) is not None


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


def _walk_nodes(node, source_bytes: bytes, spec: LanguageSpec, structures: List[_Range]):
    if node.type in spec.functions:
        kind = "method" if node.type == "method_definition" else "function"
        structures.append(_Range(
            name=_extract_name(node, source_bytes, spec.name_node),
            kind=kind,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
        ))
    elif node.type in spec.classes:
        structures.append(_Range(
            name=_extract_name(node, source_bytes, spec.name_node),
            kind="class",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
        ))
    for child in node.children:
        _walk_nodes(child, source_bytes, spec, structures)


def _find_comments(node, spec: LanguageSpec, comments: List):
    if node.type in spec.comments:
        comments.append(node)
    for child in node.children:
        _find_comments(child, spec, comments)


def _innermost_structure(structures: List[_Range], line: int) -> Optional[_Range]:
    candidates = [s for s in structures if s.start_line <= line <= s.end_line]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (-s.start_line, (s.end_line - s.start_line)))
    return candidates[0]


def _strip_comment_markers(text: str) -> Tuple[str, bool]:
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


def _content_end_line(c) -> int:
    end_row = c.end_point[0]
    if c.end_point[1] == 0 and end_row > c.start_point[0]:
        end_row -= 1
    return end_row + 1


def _attach_preceding_doc(
    comments: List,
    structures: List[_Range],
    doc_candidate_ids: set,
) -> Dict[int, _Range]:
    mapping: Dict[int, _Range] = {}
    structures_by_start = sorted(structures, key=lambda s: s.start_line)
    comment_lines = {c.start_point[0] + 1 for c in comments}

    for c in comments:
        if id(c) not in doc_candidate_ids:
            continue
        c_line = c.start_point[0] + 1
        containing = _innermost_structure(structures, c_line)
        c_end = _content_end_line(c)
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


def _resolve_language_obj(spec: LanguageSpec, file: str):
    """Pick the right Language object for a file within a multi-variant grammar."""
    loaded = _grammar_for(spec)
    if not isinstance(loaded, dict):
        return loaded
    if spec.name in ("typescript", "tsx"):
        ext = os.path.splitext(file)[1].lower()
        if ext in (".tsx", ".jsx"):
            return loaded["tsx"]
        return loaded["typescript"]
    return loaded["default"]


def extract(source: str, file: str) -> Tuple[List[Comment], List[Comment]]:
    spec = _language_for(file)
    if spec is None:
        return [], []
    try:
        from tree_sitter import Parser
        language = _resolve_language_obj(spec, file)
    except Exception:
        return [], []

    parser = Parser(language)
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    root = tree.root_node

    structures: List[_Range] = []
    _walk_nodes(root, source_bytes, spec, structures)

    comment_nodes: List = []
    _find_comments(root, spec, comment_nodes)

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

    plain_doc = spec.plain_comment_is_doc
    doc_candidate_ids = doc_ids if not plain_doc else {id(c) for c, _, _ in parsed_comments}
    preceding_doc = (
        _attach_preceding_doc(comment_nodes, structures, doc_candidate_ids)
        if spec.preceding_doc
        else {}
    )

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


def _supported_extensions() -> frozenset:
    return frozenset(_EXTENSIONS.keys())


register_language(LanguageSpec(
    name="c",
    extensions=(".c",),
    grammar="tree_sitter_c",
    functions=("function_definition",),
    classes=("struct_specifier", "class_specifier", "union_specifier", "enum_specifier"),
    comments=("comment",),
    block="compound_statement",
    preceding_doc=True,
    name_node="function_declarator",
))

register_language(LanguageSpec(
    name="c-header",
    extensions=(".h",),
    grammar="tree_sitter_c",
    functions=("function_definition", "declaration"),
    classes=("struct_specifier", "class_specifier", "union_specifier", "enum_specifier"),
    comments=("comment",),
    block="compound_statement",
    preceding_doc=True,
    name_node="function_declarator",
))

register_language(LanguageSpec(
    name="cpp",
    extensions=(".cc", ".cpp", ".cxx", ".hpp"),
    grammar="tree_sitter_cpp",
    functions=("function_definition",),
    classes=("class_specifier", "struct_specifier", "union_specifier", "enum_specifier"),
    comments=("comment",),
    block="compound_statement",
    preceding_doc=True,
    name_node="function_declarator",
))

register_language(LanguageSpec(
    name="javascript",
    extensions=(".js", ".mjs", ".cjs"),
    grammar="tree_sitter_javascript",
    functions=(
        "function_declaration",
        "generator_function_declaration",
        "method_definition",
        "arrow_function",
        "function",
    ),
    classes=("class_declaration", "class"),
    comments=("comment",),
    block="statement_block",
    preceding_doc=True,
    name_node=None,
))

register_language(LanguageSpec(
    name="typescript",
    extensions=(".ts",),
    grammar="tree_sitter_typescript",
    functions=(
        "function_declaration",
        "generator_function_declaration",
        "method_definition",
        "arrow_function",
        "function",
    ),
    classes=("class_declaration", "class"),
    comments=("comment",),
    block="statement_block",
    preceding_doc=True,
    name_node=None,
))

register_language(LanguageSpec(
    name="tsx",
    extensions=(".jsx",),
    grammar="tree_sitter_typescript",
    functions=(
        "function_declaration",
        "generator_function_declaration",
        "method_definition",
        "arrow_function",
        "function",
    ),
    classes=("class_declaration", "class"),
    comments=("comment",),
    block="statement_block",
    preceding_doc=True,
    name_node=None,
))

register_language(LanguageSpec(
    name="go",
    extensions=(".go",),
    grammar="tree_sitter_go",
    functions=("function_declaration", "method_declaration"),
    classes=("type_declaration",),
    comments=("comment",),
    block="block",
    preceding_doc=True,
    name_node=None,
    plain_comment_is_doc=True,
))

register_language(LanguageSpec(
    name="rust",
    extensions=(".rs",),
    grammar="tree_sitter_rust",
    functions=("function_item",),
    classes=("struct_item", "enum_item", "trait_item", "impl_item", "union_item"),
    comments=("line_comment", "block_comment"),
    block="block",
    preceding_doc=True,
    name_node=None,
))


SUPPORTED_EXTENSIONS = _supported_extensions()
