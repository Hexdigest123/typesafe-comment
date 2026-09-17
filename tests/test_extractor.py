import textwrap

from typesafe_comment.extractor import (
    CommentAttachment,
    extract_comments_from_source,
)


def parse(source, filename="sample.py"):
    return extract_comments_from_source(textwrap.dedent(source), filename)


def test_docstring_inside_function_is_attached():
    attached, floating = parse(
        '''
        def add(a, b):
            """Add two numbers."""
            return a + b
        '''
    )
    assert not floating
    doc = [c for c in attached if c.kind == CommentAttachment.DOCSTRING]
    assert len(doc) == 1
    assert doc[0].structure_name == "add"
    assert doc[0].line == 3
    assert "Add two numbers" in doc[0].text
    assert "def add(a, b):" in doc[0].code


def test_inline_comment_inside_function_is_attached():
    attached, floating = parse(
        '''
        def add(a, b):
            return a + b  # sum the inputs
        '''
    )
    assert not floating
    block = [c for c in attached if c.kind == CommentAttachment.BLOCK]
    assert len(block) == 1
    assert block[0].text == "sum the inputs"
    assert block[0].structure_name == "add"
    assert block[0].line == 3
    assert "return a + b" in block[0].code


def test_floating_comment_at_module_level_is_detected_not_evaluated():
    attached, floating = parse(
        '''
        # TODO: refactor this module later
        x = 1
        # another floating note
        y = 2
        '''
    )
    assert not attached
    assert len(floating) == 2
    assert all(c.kind == CommentAttachment.FLOATING for c in floating)
    assert floating[0].line == 2
    assert floating[1].line == 4
    assert floating[0].structure_name is None
    assert floating[0].code is None


def test_comment_inside_method_attaches_to_method_not_class():
    attached, floating = parse(
        '''
        class Calculator:
            """A simple calculator."""

            def add(self, a, b):
                # returns the sum
                return a + b
        '''
    )
    assert not floating
    blocks = [c for c in attached if c.kind == CommentAttachment.BLOCK]
    assert len(blocks) == 1
    assert blocks[0].structure_name == "add"
    assert blocks[0].line == 6
    docs = [c for c in attached if c.kind == CommentAttachment.DOCSTRING]
    assert len(docs) == 1
    assert docs[0].structure_name == "Calculator"


def test_async_function_comment_attached():
    attached, floating = parse(
        '''
        async def fetch(url):
            # performs an HTTP GET
            return await client.get(url)
        '''
    )
    assert not floating
    blocks = [c for c in attached if c.kind == CommentAttachment.BLOCK]
    assert len(blocks) == 1
    assert blocks[0].structure_kind == "async function"
    assert blocks[0].structure_name == "fetch"


def test_nested_function_inner_wins():
    attached, floating = parse(
        '''
        def outer():
            # outer note
            def inner():
                # inner note
                return 1
            return inner()
        '''
    )
    assert not floating
    blocks = {c.line: c for c in attached if c.kind == CommentAttachment.BLOCK}
    assert blocks[3].structure_name == "outer"
    assert blocks[5].structure_name == "inner"


def test_syntax_error_returns_empty():
    attached, floating = extract_comments_from_source("def broken(:\n", "bad.py")
    assert attached == []
    assert floating == []


def test_module_docstring_is_not_counted_as_floating():
    attached, floating = parse(
        '''
        """Module docstring at the top."""
        x = 1
        '''
    )
    docs = [c for c in attached if c.kind == CommentAttachment.DOCSTRING]
    module_docs = [d for d in docs if d.structure_name is None]
    assert module_docs == []
    assert not floating


def test_comment_text_strips_leading_hash():
    attached, _ = parse(
        '''
        def f():
            x = 1   #   spaced comment
            return x
        '''
    )
    block = [c for c in attached if c.kind == CommentAttachment.BLOCK][0]
    assert block.text == "spaced comment"
