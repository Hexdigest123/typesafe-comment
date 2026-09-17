"""Command-line entry point for typesafe-comment."""

import argparse
import sys
from typing import List, Optional

from .classify import DEFAULT_THRESHOLDS, HEURISTICS
from .env import load_env
from .run import evaluate_files


def _threshold_action(value: str) -> dict:
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "threshold must be HEURISTIC=VALUE, got {!r}".format(value)
        )
    name, raw = value.split("=", 1)
    name = name.strip()
    raw = raw.strip()
    if name not in HEURISTICS:
        raise argparse.ArgumentTypeError(
            "unknown heuristic {!r}; choose from {}".format(name, ", ".join(HEURISTICS))
        )
    try:
        number = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "threshold value for {} must be a number, got {!r}".format(name, raw)
        )
    if not 0.0 <= number <= 1.0:
        raise argparse.ArgumentTypeError(
            "threshold value for {} must be in [0, 1], got {!r}".format(name, number)
        )
    return {name: number}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="typesafe-comment",
        description=(
            "Lint code comments with TypeSafe's System One decision model. "
            "Supports Python (stdlib ast) and C/C++/JS/TS/Go/Rust (tree-sitter)."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help=(
            "Files or directories to check (directories are walked recursively). "
            "Supported: Python, C/C++, JavaScript, TypeScript, Go, Rust."
        ),
    )
    env_group = parser.add_mutually_exclusive_group()
    env_group.add_argument(
        "--env",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help=(
            "Load a .env file for configuration. Without a path, loads ./.env if "
            "present. With a path, that file is required. The general environment "
            "always takes precedence over file values."
        ),
    )
    parser.add_argument(
        "--threshold",
        action="append",
        type=_threshold_action,
        default=[],
        metavar="HEURISTIC=VALUE",
        help=(
            "Override a per-heuristic pass/fail threshold in [0, 1]. "
            "Repeatable. Heuristics: {}. "
            "Defaults: {}.".format(
                ", ".join(HEURISTICS),
                ", ".join("{}={}".format(k, v) for k, v in DEFAULT_THRESHOLDS.items()),
            )
        ),
    )
    parser.add_argument(
        "--github",
        action="store_true",
        help="Emit warnings in GitHub Actions ::warning command format.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the floating-comment note and the PASS/FAIL summary.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit a JSON object (results + floating + summary) with per-comment, "
            "per-heuristic scores instead of the text report. Useful for the "
            "eval harness / programmatic consumers."
        ),
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    env_arg, paths = _resolve_env_and_paths(args)

    if not paths:
        parser.error("the following arguments are required: PATH")

    try:
        load_env(env_arg)
    except Exception as exc:
        sys.stderr.write("typesafe-comment: error: {}\n".format(exc))
        return -1

    thresholds = dict(DEFAULT_THRESHOLDS)
    for override in args.threshold:
        thresholds.update(override)

    return evaluate_files(
        paths,
        thresholds=thresholds,
        stream=sys.stdout,
        github_format=args.github,
        quiet=args.quiet,
        json_output=args.json,
    )


def _resolve_env_and_paths(args):
    env_arg = args.env
    paths = list(args.paths)
    if env_arg is not None and env_arg != "" and not paths:
        paths = [env_arg]
        env_arg = ""
    return env_arg, paths


if __name__ == "__main__":
    raise SystemExit(main())
