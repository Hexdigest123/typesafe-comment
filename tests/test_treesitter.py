import os
import textwrap

import pytest

from typesafe_comment.extractor import CommentAttachment, extract_comments, extract_comments_from_paths

try:
    from typesafe_comment import treesitter

    HAS_TS = treesitter.is_available()
except Exception:
    HAS_TS = False

pytestmark = pytest.mark.skipif(not HAS_TS, reason="tree-sitter extra not installed")


def write(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(textwrap.dedent(source))
    return str(path)


def test_js_doc_comment_attaches_to_following_function(tmp_path):
    path = write(
        tmp_path,
        "add.js",
        """
        // floating js note

        /** Add two numbers and return the sum. */
        function add(a, b) {
            return a + b; // sum the inputs
        }
        """,
    )
    attached, floating = extract_comments(path)
    docs = [c for c in attached if c.kind == CommentAttachment.DOCSTRING]
    blocks = [c for c in attached if c.kind == CommentAttachment.BLOCK]
    assert len(docs) == 1
    assert docs[0].line == 4
    assert docs[0].structure_name == "add"
    assert "Add two numbers" in docs[0].text
    assert len(blocks) == 1
    assert blocks[0].line == 6
    assert blocks[0].structure_name == "add"
    assert any(c.line == 2 and c.kind == CommentAttachment.FLOATING for c in floating)


def test_ts_function_doc_and_inline_comment(tmp_path):
    path = write(
        tmp_path,
        "add.ts",
        """
        /** Add two numbers and return the sum. */
        function add(a: number, b: number): number {
            return a + b; // sum
        }
        """,
    )
    attached, floating = extract_comments(path)
    assert [c.kind for c in attached] == [CommentAttachment.DOCSTRING, CommentAttachment.BLOCK]
    assert attached[0].structure_name == "add"
    assert attached[1].structure_name == "add"


def test_c_doc_comment_and_inline(tmp_path):
    path = write(
        tmp_path,
        "add.c",
        """
        /** Add two integers and return the result. */
        int add(int a, int b) {
            return a + b; // sum the inputs
        }
        """,
    )
    attached, floating = extract_comments(path)
    assert not floating
    assert {c.kind for c in attached} == {CommentAttachment.DOCSTRING, CommentAttachment.BLOCK}
    assert all(c.structure_name == "add" for c in attached)


def test_cpp_class_method_comment_attaches_to_method(tmp_path):
    path = write(
        tmp_path,
        "calc.cpp",
        """
        class Calculator {
        public:
            /** Add two integers. */
            int add(int a, int b) {
                return a + b; // sum
            }
        };
        """,
    )
    attached, floating = extract_comments(path)
    blocks = [c for c in attached if c.kind == CommentAttachment.BLOCK]
    docs = [c for c in attached if c.kind == CommentAttachment.DOCSTRING]
    assert blocks and blocks[0].structure_name == "add"
    assert docs and docs[0].structure_name == "add"


def test_go_doc_comment_attaches_to_function(tmp_path):
    path = write(
        tmp_path,
        "add.go",
        """
        package main

        // Add adds two integers and returns the result.
        func Add(a, b int) int {
            return a + b // sum
        }
        """,
    )
    attached, floating = extract_comments(path)
    docs = [c for c in attached if c.kind == CommentAttachment.DOCSTRING]
    blocks = [c for c in attached if c.kind == CommentAttachment.BLOCK]
    assert docs and docs[0].structure_name == "Add"
    assert "Add adds two integers" in docs[0].text
    assert blocks and blocks[0].structure_name == "Add"


def test_rust_doc_comment_triple_slash_attaches(tmp_path):
    path = write(
        tmp_path,
        "add.rs",
        """
        // floating rust note

        /// Adds two integers and returns the result.
        fn add(a: i32, b: i32) -> i32 {
            a + b // sum
        }
        """,
    )
    attached, floating = extract_comments(path)
    docs = [c for c in attached if c.kind == CommentAttachment.DOCSTRING]
    blocks = [c for c in attached if c.kind == CommentAttachment.BLOCK]
    assert docs and docs[0].line == 4
    assert docs[0].structure_name == "add"
    assert "Adds two integers" in docs[0].text
    assert blocks and blocks[0].line == 6
    assert any(c.line == 2 and c.kind == CommentAttachment.FLOATING for c in floating)


def test_floating_comment_at_top_level_detected_all_languages(tmp_path):
    cases = {
        "a.js": "// stray js note\n\nfunction f() {}\n",
        "a.ts": "// stray ts note\n\nfunction f() {}\n",
        "a.c": "// stray c note\n\nint f() { return 0; }\n",
        "a.cpp": "// stray cpp note\n\nint f() { return 0; }\n",
        "a.go": "package main\n\n// stray go note\n\nfunc F() {}\n",
        "a.rs": "// stray rust note\n\nfn f() {}\n",
    }
    for name, src in cases.items():
        path = write(tmp_path, name, src)
        _, floating = extract_comments(path)
        assert any(c.kind == CommentAttachment.FLOATING for c in floating), name


def test_extract_from_paths_walks_mixed_language_directory(tmp_path):
    write(tmp_path, "a.py", "def f():\n    return 1  # py comment\n")
    write(tmp_path, "b.js", "function f() { return 1; } // js comment\n")
    write(tmp_path, "c.go", "package main\n\nfunc F() int { return 1 } // go comment\n")
    attached, floating, visited = extract_comments_from_paths([str(tmp_path)])
    assert len(visited) == 3
    assert len(attached) == 3
    assert all(c.structure_name for c in attached)


def test_comment_inside_nested_function_inner_wins(tmp_path):
    path = write(
        tmp_path,
        "nested.js",
        """
        function outer() {
            // outer note
            function inner() {
                // inner note
                return 1;
            }
            return inner();
        }
        """,
    )
    attached, floating = extract_comments(path)
    blocks = {c.line: c for c in attached if c.kind == CommentAttachment.BLOCK}
    assert blocks[3].structure_name == "outer"
    assert blocks[5].structure_name == "inner"


def test_unsupported_extension_returns_empty(tmp_path):
    path = write(tmp_path, "a.txt", "not code // not a comment\n")
    attached, floating = extract_comments(path)
    assert attached == []
    assert floating == []


def test_tsx_file_supported(tmp_path):
    path = write(
        tmp_path,
        "comp.jsx",
        """
        /** Render a button. */
        function Button(props) {
            return null; // placeholder
        }
        """,
    )
    attached, floating = extract_comments(path)
    assert {c.kind for c in attached} == {CommentAttachment.DOCSTRING, CommentAttachment.BLOCK}
