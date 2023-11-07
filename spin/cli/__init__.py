"""Module containing all the CLI/high level interface"""

from __future__ import annotations

import argparse
import json
import pathlib
import pprint
import sys
from typing import Any, Callable, Sequence, get_args

import pkg_resources

import spin.cli._build
import spin.cli._image
import spin.utils.config
from spin.cli import _register
from spin.cli._check_system import check_system
from spin.cli._connect import scp_to, ssh
from spin.cli._destroy import destroy
from spin.cli._down import down
from spin.cli._init import init
from spin.cli._list import list_machines
from spin.cli._status import print_status
from spin.cli._up import up
from spin.cli._version import print_version
from spin.utils import ui

AUTOMATIC_DETECTION_VALUE = "-"

parser = _register.parser
subparsers = _register.subparsers

init_parser = subparsers.add_parser(
    "init", help="Initialize a machine configuration by creating a spinfile.py"
)

init_parser.add_argument(
    "image", help="the image to use for the machine, in the format name:tag"
)
init_parser.add_argument(
    "--stdout",
    action="store_true",
    help="output the contents of the spinfile.py to STDOUT instead of spinfile.py",
)
init_parser.add_argument(
    "--cpus", type=int, required=False, help="Number of vCPUs for the guest"
)
init_parser.add_argument(
    "--memory",
    type=str,
    required=False,
    help=(
        "Amount of vRAM for the guest. "
        "Expressed in SI notation (e.g. 512MB) "
        "or binary (e.g. 4GiB)."
    ),
)
init_parser.add_argument(
    "--plugin",
    action="append",
    type=str,
    help="Plugin to add to the list of plugins enabled for the guest.",
)
init_parser.set_defaults(
    func=lambda arg: init(
        folder=pathlib.Path("."),
        nametag=arg.image,
        stdout=arg.stdout,
        cpus=arg.cpus,
        memory=arg.memory,
        plugins=arg.plugin,
    )
)
check_system_parser = subparsers.add_parser(
    "check-system",
    help="Check the system (hardware and software) to determine capabilities and problems",
)
check_system_parser.set_defaults(
    func=lambda _: 0 if all(ret[0] for ret in check_system(print_=True)) else 1
)
MACHINE_HELP = "the name, UUID or path for the machine"
up_parser = subparsers.add_parser("up", help="Spin up a machine")
up_parser.add_argument(
    "--console", action="store_true", help="Print the console output to stdout"
)
up_parser.add_argument(
    "machine", nargs="?", default=AUTOMATIC_DETECTION_VALUE, help=MACHINE_HELP
)
up_parser.set_defaults(func=lambda arg: up(arg.machine, print_console=arg.console))

down_parser = subparsers.add_parser("down", help="Stop a machine")
down_parser.add_argument(
    "machine", nargs="?", default=AUTOMATIC_DETECTION_VALUE, help=MACHINE_HELP
)
down_parser.set_defaults(func=lambda arg: down(arg.machine))


def _status_wrap(args: argparse.Namespace) -> int:
    if len(args.machine) == 0:
        args.machine = ["."]
    retcodes: list[int] = []
    for i, machine in zip(range(len(args.machine)), args.machine):
        retcodes.append(print_status(machine))
        if i < (len(args.machine) - 1):
            print()
    return max(retcodes)


status_parser = subparsers.add_parser("status", help="Retrieve the status of a machine")
status_parser.add_argument(
    "machine",
    nargs="*",
    help=MACHINE_HELP
    + '. If no argument is given, is the same as calling "spin status ."',
)
status_parser.set_defaults(func=_status_wrap)

list_arg = subparsers.add_parser("list", help="List tracked machines")
list_arg.add_argument(
    "-a", "--all", action="store_true", help="list machines not currently running"
)
list_arg.add_argument("--full", action="store_true", help="show the full UUID")
list_arg.add_argument("--path", action="store_true", help="show machine folder path")


def _list_wrap(arg) -> int:
    list_machines(full_uuid=arg.full, list_all=arg.all, path=arg.path)
    return 0


list_arg.set_defaults(func=_list_wrap)

destroy_parser = subparsers.add_parser("destroy", help="Destroy a machine")
destroy_parser.add_argument(
    "machine", nargs="?", default=AUTOMATIC_DETECTION_VALUE, help=MACHINE_HELP
)
destroy_parser.add_argument(
    "--storage", action="store_true", help="Destroyed all associated storage."
)
destroy_parser.set_defaults(
    func=lambda arg: destroy(arg.machine, remove_disk=arg.storage)
)

ssh_parser = subparsers.add_parser("ssh", help="Connect to a machine through SSH")
ssh_parser.add_argument(
    "-i",
    "--identity-file",
    nargs="?",
    type=pathlib.Path,
    help="same as -i in ssh",
)
ssh_parser.add_argument(
    "--user", type=str, nargs="?", help="user to prepend to the destination IP"
)
ssh_parser.add_argument(
    "machine", nargs="?", default=AUTOMATIC_DETECTION_VALUE, help=MACHINE_HELP
)
ssh_parser.add_argument("command", nargs="?", help="Command to pass to SSH")
ssh_parser.add_argument(
    "arguments",
    nargs=argparse.REMAINDER,
    help="Arguments to append to SSH invocation",
)


def _ssh_wrapper(args: argparse.Namespace) -> None:
    sys.exit(
        ssh(
            args.machine,
            command=args.command,
            args=args.arguments,
            login=getattr(args, "user", None),
            identity_file=getattr(args, "identity_file", None),
        )
    )


ssh_parser.set_defaults(func=_ssh_wrapper)

init_conf_parser = subparsers.add_parser(
    "init-conf", help="Initialize the configuration folders and files"
)
init_conf_parser.set_defaults(
    func=lambda arg: spin.utils.config.conf.init_conf(arg.dry_run)
)

version_parser = subparsers.add_parser(
    "version", help="Show extended version information"
)
version_parser.set_defaults(func=lambda _: print_version())


def _dump_config(args: argparse.Namespace) -> int:
    pprint.pprint(spin.utils.config.conf.settings.dict(), width=60)

    return 0


dump_conf_parser = subparsers.add_parser(
    "dump-config", help="Dump the configuration loaded. Useful for debugging"
)
dump_conf_parser.set_defaults(func=_dump_config)


def run(args: Sequence[str] | None = None) -> None:
    """Run the CLI interface.

    Args:
        args: Arguments to use instead of reading the defaults.
    """

    arguments = parser.parse_args(args=args)
    level = get_args(spin.utils.ui.LEVEL_LITERAL)[
        ui.NOTICE - min(arguments.verbose, ui.NOTICE)
    ]
    spin.utils.init_ui(arguments.ui, level, arguments.verbose != 0)

    if arguments.version:
        print(f"spin {pkg_resources.get_distribution('spin').version}")
        sys.exit(0)

    func: Callable[[argparse.Namespace], int | Any]
    if "func" not in arguments:
        if arguments.subcommand not in _register.callbacks:
            parser.print_help()
            sys.exit(127)
        func = _register.callbacks[arguments.subcommand]
    else:
        func = arguments.func
    # NOTE: Without this; the app *may* lock after an unhandled exception
    try:
        ret = func(arguments)
        if isinstance(ret, _register.Return):
            sys.exit(ret.returncode)
        sys.exit(ret or 0)
    finally:
        spin.exit_procedure()
