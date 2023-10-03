"""Utilities for registering CLI commands"""
from __future__ import annotations

import argparse
import dataclasses
from typing import Callable


@dataclasses.dataclass
class Return:
    """Return value required by CLI commands"""

    returncode: int


CallSignature = Callable[[argparse.Namespace], Return]
RegisterSignature = Callable[[argparse.ArgumentParser], CallSignature]

parser = argparse.ArgumentParser(
    "spin",
    description="An under-performing VM manager",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)

parser.add_argument(
    "--dry-run",
    action="store_true",
    help="do not perform any modifications, just simulate. Use with -v, --verbose for debugging",
)
parser.add_argument(
    "--ui",
    choices=("log", "fancy", "auto"),
    default="auto",
    help=(
        "Select the *UI* mode: log contains no colors and is ready to be written to a file; "
        "fancy uses colors; 'animations' and other tricks for a nicer CLI experience."
    ),
)
parser.add_argument(
    "-v",
    "--verbose",
    action="count",
    default=0,
    help=(
        "print additional information. Can be supplied "
        "several times to increase the verbosity level."
    ),
)
parser.add_argument("--version", action="store_true", help="print version and exit")
subparsers = parser.add_subparsers(metavar="command", dest="subcommand")
callbacks: dict[str, CallSignature] = {}


def cli_command(name: str, **kwargs) -> Callable[[RegisterSignature], None]:
    """Decorator to register a CLI sub-parser.

    The decorator first receives arguments (``*args, **kwargs``) to
    forward to ``add_parser``. The register function is expected
    to return a function (or callable) capable of processing the
    eventual argparse.ArgumentParser generated from the user
    input.
    """

    def _wrapper(func: RegisterSignature) -> None:
        subparser = subparsers.add_parser(name, **kwargs)
        to_call = func(subparser)
        callbacks[name] = to_call

    return _wrapper
