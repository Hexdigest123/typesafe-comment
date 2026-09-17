# typesafe-comment

Lint code comments with [TypeSafe AI](https://typesafe.ai)'s System One model.
Comments are scored on five heuristics (usefulness, readability, accuracy,
redundancy, coverage); those below thresholds emit linter warnings and exit
non-zero so pipelines block.

## Install

```bash
pip install -e .                         # Python only (stdlib, no deps)
pip install -e ".[tree-sitter]"         # + C/C++/JS/TS/Go/Rust
pip install -r requirements.txt         # same grammars via requirements file
pip install typesafe-comment             # from PyPI
pipx install typesafe-comment            # global on-demand
uvx --from typesafe-comment typesafe-comment src/   # ad-hoc, no install
```

## API key

Never embedded in source. Set it in the environment or load from a `.env` file
(see `.env.example`):

```bash
export TYPESAFE_API_KEY=apikey_...
typesafe-comment --env .env src/         # load key from ./.env
typesafe-comment --env cfg.env src/      # required file cfg.env, then scan src/
```

General environment always wins over `.env` values. Other env vars:
`TYPESAFE_MODEL` (default `jev-latest`), `TYPESAFE_API_BASE`,
`TYPESAFE_TIMEOUT`, `TYPESAFE_MAX_RETRIES`.

## Usage

```bash
typesafe-comment src/                                     # scan dir recursively
typesafe-comment --threshold accuracy=0.4 --threshold coverage=0.2 src/
typesafe-comment --github src/                            # ::warning annotations
typesafe-comment --quiet src/                             # warnings only, no summary
typesafe-comment --json src/ > report.json                # machine-readable output
```

Supported: Python (`.py`), C (`.c`,`.h`), C++ (`.cc`,`.cpp`,`.cxx`,`.hpp`),
JavaScript (`.js`,`.mjs`,`.cjs`), TypeScript/TSX (`.ts`,`.jsx`), Go (`.go`),
Rust (`.rs`). Python uses stdlib `ast`; others need the tree-sitter extra.

Default thresholds:

```
usefulness=0.3  readability=0.3  accuracy=0.25  redundancy=0.25  coverage=0.1
```

Comments outside any function/class (floating at module level) are not
evaluated but listed in the summary.

## Exit codes

| Code | Meaning                                       |
| ---- | --------------------------------------------- |
| `0`  | All comments passed.                          |
| `-1` | A comment failed a threshold or API error (`255` in shells). |
| `2`  | Bad CLI usage.                                |

## CI

GitHub Actions:

```yaml
- run: pip install "typesafe-comment[tree-sitter]"
- run: typesafe-comment --github src/
  env:
    TYPESAFE_API_KEY: ${{ secrets.TYPESAFE_API_KEY }}
```

GitLab CI:

```yaml
script:
  - pip install "typesafe-comment[tree-sitter]"
  - typesafe-comment src/
variables:
  TYPESAFE_API_KEY: $TYPESAFE_API_KEY
```

opencode post-edit hook:

```jsonc
{ "commands": { "comment-check": {
    "command": "git diff --name-only --cached --diff-filter=AM | xargs -r typesafe-comment --env .env" } } }
```
