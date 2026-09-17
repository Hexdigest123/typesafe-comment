# typesafe-comment

Lint code comments with [TypeSafe AI](https://typesafe.ai)'s System One
decision model (`jev`). Each comment is scored against the function/class it
belongs to on five heuristics; comments that fall below configurable thresholds
produce linter-style warnings and a non-zero exit code so the check blocks
pipelines.

Python 3.8+. The core linter is standard-library only (no runtime
dependencies). Multi-language support for C/C++/JavaScript/TypeScript/Go/Rust
uses tree-sitter via an optional extra.

## What it does

For every comment **inside a function or class** (docstring or inline comment),
the tool sends the comment text plus the enclosing code to TypeSafe's
[`/v1/systemone`](https://docs.typesafe.ai/api) endpoint and scores five
heuristics, each on a 0–1 scale (higher is better):

| Heuristic    | Question                                                        |
| ------------ | --------------------------------------------------------------- |
| `usefulness` | Does the comment add information not obvious from the code?     |
| `readability`| Is the comment clear, concise, well-formed?                    |
| `accuracy`   | Does the comment match what the code actually does?             |
| `redundancy` | Is the comment free of redundant restatement of the code?      |
| `coverage`   | Does the comment document the important aspects of the code?    |

If any heuristic falls below its threshold, a warning is printed at
`file:line` and the run exits non-zero (`-1`, shown as `255` by shells).
Default thresholds:

```
usefulness=0.3  readability=0.3  accuracy=0.25  redundancy=0.25  coverage=0.1
```

Comments **outside any function or class** (free-standing at module level) have
no associated code to judge them against, so they are **not evaluated**. They
are detected and reported in a summary at the end of the run, e.g.:

```
note: 2 comment(s) outside any function or class were skipped (no associated code to evaluate against):
  floating.py:1: This is a module-level comment, floating around
  floating.py:4: Another stray note outside any function
```

## Supported languages

| Language                         | Extractor            | Needs extra? |
| -------------------------------- | -------------------- | ------------ |
| Python (`.py`)                   | stdlib `ast`/`tokenize` | no        |
| C (`.c`, `.h`)                   | tree-sitter          | yes         |
| C++ (`.cc`, `.cpp`, `.cxx`, `.hpp`) | tree-sitter       | yes         |
| JavaScript (`.js`, `.mjs`, `.cjs`) | tree-sitter        | yes         |
| TypeScript / TSX (`.ts`, `.jsx`) | tree-sitter          | yes         |
| Go (`.go`)                       | tree-sitter          | yes         |
| Rust (`.rs`)                     | tree-sitter          | yes         |

Without the tree-sitter extra, non-Python files are skipped (Python-only mode).

## Install

```bash
# Python only (core, no dependencies)
pip install -e .

# With multi-language support (C/C++/JS/TS/Go/Rust)
pip install -e ".[tree-sitter]"
# or, via the bundled requirements file:
pip install -r requirements.txt && pip install -e .

# or, after publishing to PyPI:
pip install typesafe-comment
pip install "typesafe-comment[tree-sitter]"
```

On-demand usage without a checkout:

```bash
uvx --from typesafe-comment typesafe-comment --github src/        # ad-hoc
pipx install typesafe-comment && typesafe-comment --github src/   # global
```

This provides the `typesafe-comment` command. You can also run it without
installing: `python -m typesafe_comment`.

## Configuration: the API key

The API key is **never** embedded in any source file. Set it in the environment
or load it from a `.env` file. A template is provided:

```bash
cp .env.example .env
$EDITOR .env          # set TYPESAFE_API_KEY=apikey_...
```

The CLI checks the **general (process) environment first**; values already
present there (e.g. `export TYPESAFE_API_KEY=...` or a CI secret) **always
win** over file values. The `--env` flag only fills gaps:

| Invocation                        | Env file loaded                          |
| --------------------------------- | ---------------------------------------- |
| `typesafe-comment src/`           | none (environment only)                  |
| `typesafe-comment --env src/`     | `./.env` if present, then scan `src/`     |
| `typesafe-comment --env .env src/`| `./.env`, then scan `src/`               |
| `typesafe-comment --env cfg.env src/`| `cfg.env` (required), then scan `src/`|

> `--env` with no path means `./.env` (the current working directory). With an
> explicit path, that file is **required** to exist (missing file errors out).

All other options are optional environment variables (see `.env.example`):
`TYPESAFE_MODEL` (default `jev-latest`), `TYPESAFE_API_BASE`
(default `https://api.typesafe.ai`), `TYPESAFE_TIMEOUT` (default `60`),
`TYPESAFE_MAX_RETRIES` (default `4`).

## Usage

```bash
# Check files or directories (directories are walked recursively)
typesafe-comment path/to/file.py
typesafe-comment src/

# Override thresholds (repeatable; any heuristic not given keeps its default)
typesafe-comment --threshold accuracy=0.4 --threshold coverage=0.2 src/

# Emit GitHub Actions ::warning annotations
typesafe-comment --github src/

# Suppress the floating-note + PASS/FAIL summary (warnings still print)
typesafe-comment --quiet src/

# Emit a JSON object (results + floating + summary) for programmatic consumers
typesafe-comment --json src/ > report.json
```

Example output:

```
warning: src/math.py:7: coverage score 0.00 below threshold 0.10
warning: src/math.py:7: usefulness score 0.00 below threshold 0.30
typesafe-comment: evaluated 2 comment(s) across 1 file(s); 2 warning(s); 0 floating comment(s) skipped
typesafe-comment: FAIL (one or more comments below threshold)
```

### Exit codes

| Code | Meaning                                                                   |
| ---- | ------------------------------------------------------------------------- |
| `0`  | All evaluated comments passed their thresholds.                          |
| `-1` | One or more comments fell below a threshold, or a TypeSafe API error occurred. |
| `2`  | Bad CLI usage (argparse).                                                 |

`-1` becomes `255` in POSIX shells; both are non-zero so scripts and CI gates
fail loudly.

## Integration

### opencode (and similar AI harnesses) post-tool hook

Add a command hook that runs after the agent edits code files. In opencode,
configure a custom command/alias in your config that invokes the linter on the
changed paths:

```jsonc
// opencode config (e.g. opencode.json) — run after edits
{
  "commands": {
    "comment-check": {
      "description": "Lint comments in changed files with TypeSafe",
      "command": "git diff --name-only --cached --diff-filter=AM | xargs -r typesafe-comment --env .env"
    }
  }
}
```

Then `/comment-check` in a session reviews the staged files. Because the tool
exits non-zero on failures, it surfaces problems inline. For a true post-edit
hook, wire the same command into your harness's "after write" event pointing at
the edited file(s):

```bash
# ~/.config/opencode/hooks.sh (or your harness equivalent)
typesafe-comment --env ~/.config/typesafe-comment.env "$@"
```

Set `TYPESAFE_API_KEY` in your shell profile so the harness inherits it, or
keep a `~/.config/typesafe-comment.env` file and pass it with `--env`.

### GitHub Actions

```yaml
# .github/workflows/comment-lint.yml
name: comment-lint
on:
  pull_request:
    paths: ["**/*.py", "**/*.js", "**/*.ts", "**/*.go", "**/*.rs", "**/*.c", "**/*.cpp"]
jobs:
  typesafe-comment:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "typesafe-comment[tree-sitter]"
      - run: typesafe-comment --github src/
        env:
          TYPESAFE_API_KEY: ${{ secrets.TYPESAFE_API_KEY }}
```

The key comes from a repository/organization secret (the general environment),
so no `.env` file is needed. `--github` emits `::warning file=...,line=...`
annotations that show up in the PR Files Changed view; the non-zero exit fails
the check run.

### GitLab CI

```yaml
# .gitlab-ci.yml
typesafe-comment:
  image: python:3.12
  script:
    - pip install "typesafe-comment[tree-sitter]"
    - typesafe-comment src/
  variables:
    TYPESAFE_API_KEY: $TYPESAFE_API_KEY   # CI/CD variable (masked)
  rules:
    - changes: ["**/*.py", "**/*.js", "**/*.go"]
```

Add `TYPESAFE_API_KEY` as a masked CI/CD variable in
**Settings → CI/CD → Variables**. The general environment takes precedence, so
no `.env` file is required; the non-zero exit fails the job and blocks merge.

## How it works

1. **Extract** — for Python, `tokenize` finds `#` comments and `ast` finds the
   enclosing `FunctionDef`/`AsyncFunctionDef`/`ClassDef` and its source. For
   C/C++/JS/TS/Go/Rust, tree-sitter parses a real AST and attaches comments to
   their enclosing function/class (doc comments like `/** */`, `///`, godoc
   attach to the following declaration; inline comments attach to their
   container). Module-level comments with no enclosing structure are flagged as
   floating.
2. **Classify** — one TypeSafe `/v1/systemone` call per comment sends the
   comment + language + enclosing code as `state` and five `score` questions
   (one per heuristic). Each answer's probability-weighted score across 4
   ordered levels is normalized to 0–1.
3. **Report** — any heuristic below its threshold emits a `warning: file:line:
   <heuristic> score X below threshold Y` line; floating comments are listed in
   the summary; the run exits `-1` on any failure.

## Project layout

```
typesafe_comment/
  __init__.py      # public API
  __main__.py      # CLI (argparse, --env, --threshold, --github, --quiet, --json)
  env.py           # .env parsing + env-precedence + --env flag resolution
  extractor.py    # Python comment + code-structure extraction (ast + tokenize)
  treesitter.py    # C/C++/JS/TS/Go/Rust comment extraction via tree-sitter (optional)
  client.py        # stdlib HTTP client for /v1/systemone (retry/backoff)
  classify.py      # heuristics, rubrics, normalization, threshold warnings
  report.py        # linter-style + GitHub ::warning formatting
  run.py           # extract -> classify -> report -> exit code (+ JSON mode)
.env.example      # template; never commit a real .env
requirements.txt  # optional tree-sitter grammars for multi-language support
```

## License

MIT © Hexdigest
