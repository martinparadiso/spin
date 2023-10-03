"""Functionality to connect to a machine.

In particular the module contains functionality to connect
from the CLI interface to any guest.
"""
from __future__ import annotations

import pathlib
import sys
from typing import Optional, TextIO

from spin.cli._utils import load
from spin.errors import NotFound
from spin.machine.connection import SSHHelper
from spin.machine.machine import Machine
from spin.utils import ui


def ssh(
    machine: pathlib.Path | Machine | str,
    command: None | str,
    args: list[str],
    login: None | str = None,
    identity_file: None | pathlib.Path = None,
    ssh_flags: None | list[str] = None,
) -> int:
    """SSH into a machine.

    The command spawns a SSH process, which implicitly
    forwards stdin and stdout to the outer shell. This
    means calling this function is equivalent to calling
    ``ssh destination args`` in the shell.

    If both user and identity_file are ``None``, the system
    will attempt to pull valid credentials from the machine
    :py:attr:`ssh` attribute.

    Args:
        machine: The machine to connect to.
        args: The arguments to pass to SSH after the guest IP.
        login: Login/user to use when generating the SSH destination, to pass
            as ``-o User=login``. If not supplied, the library will attempt
            to extract it from a valid credential.
        identity_file: Same as SSH ``-i``.
        ssh_flags: Flags to pass to the ssh command, for instance
            ``-o RequestTTY=yes`` to force TTY.

    Returns:
        The SSH subprocess returncode.
    """

    if not isinstance(machine, Machine):
        machines = load(machine, disable_definition=False)
        if machines is None or len(machines) == 0:
            raise NotFound(f"Could not found machine: {machine}")
        if len(machines) > 1:
            vm = ui.instance().select(*machines, default=machines[0])
        else:
            vm = machines[0]

    else:
        vm = machine

    if vm is None:
        return 1

    command_or_pipe: str | TextIO
    if command is None:
        command_or_pipe = sys.stdin
    else:
        command_or_pipe = " ".join([command, *args])

    return (
        SSHHelper(
            vm,
            capture_output=False,
            flags=ssh_flags,
            login=login,
            identity_file=identity_file,
        )
        .run(command_or_pipe)
        .returncode
    )


def scp_to(
    machine: Machine,
    source: pathlib.Path,
    target: pathlib.PurePath,
    *,
    ssh_flags: Optional[list[str]] = None,
) -> int:
    """Copy `source` file into `destination` of `machine` using ``scp``.

    Returns:
        The ``scp`` command return value``.
    """
    if not isinstance(machine, Machine):
        machines = load(machine, disable_definition=False)
        if machines is None:
            raise ValueError(f"Could not found machine: {machine}")
        if len(machines) > 1:
            raise ValueError("Multiple machines found")

        vm = machines[0]
    else:
        vm = machine

    return SSHHelper(vm, flags=ssh_flags).scp_to(source, target).returncode
