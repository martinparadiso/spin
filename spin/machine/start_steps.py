"""Collection of common start steps."""

from __future__ import annotations

import datetime as dt
import subprocess
from threading import Event, Thread

import spin.locks
from spin.errors import BackendError, CommandFailed
from spin.locks import process_stop
from spin.machine.connection import print_console, ssh
from spin.machine.machine import CreatedMachine, DefinedMachine, Log, as_machine
from spin.machine.steps import StartStep
from spin.utils.dependency import dep
from spin.utils.load import Spinfolder


@dep
class Boot(StartStep):
    """Send boot signal to the machine"""

    name = "Booting"

    @classmethod
    def accepts(cls, machine: DefinedMachine) -> bool:
        return True

    def process(self) -> None:
        ok = self.machine.backend.start()
        if not ok:
            raise BackendError
        self.machine.info.boots += 1

        if self.__class__.print_console:
            handle = print_console(as_machine(self.machine))
            spin.locks.exit_callbacks.append(handle.close)


@dep(requires=Boot)
class WaitForNetwork(StartStep):
    """Block until the machine has an IP"""

    name = "Waiting for network"

    timeout = 240

    @classmethod
    def accepts(cls, machine: DefinedMachine) -> bool:
        return machine.options.wait_for_network and machine.hardware.network is not None

    def process(self) -> None:
        wait_exit = Event()
        spin.locks.global_wakeups.add(wait_exit)

        start_time = dt.datetime.now()

        def time_elapsed():
            return (dt.datetime.now() - start_time) > dt.timedelta(seconds=self.timeout)

        try:
            while not wait_exit.is_set() and not time_elapsed():
                if self.machine.backend.main_ip is not None:
                    return
                wait_exit.wait(0.05)
        finally:
            spin.locks.global_wakeups.remove(wait_exit)
        if self.machine.backend.main_ip is None:
            raise BackendError(f"No IP found after {self.timeout} seconds")


@dep(requires=WaitForNetwork)
class WaitForSSH(StartStep):
    """Wait until SSH is available"""

    name = "Waiting for SSH"
    timeout = 240

    @classmethod
    def accepts(cls, machine: DefinedMachine) -> bool:
        return (
            machine.options.wait_for_ssh
            and WaitForNetwork.accepts(machine)
            and len(machine.ssh) > 0
        )

    def process(self) -> None:
        assert self.machine.backend.main_ip is not None
        wait_exit = Event()
        spin.locks.global_wakeups.add(wait_exit)
        attempts = 0
        start_time = dt.datetime.now()

        def port_open() -> bool:
            ret = ssh(self.machine, "exit")
            return ret.returncode == 0

        def time_elapsed():
            return (dt.datetime.now() - start_time) > dt.timedelta(seconds=self.timeout)

        try:
            while not wait_exit.is_set() and not time_elapsed():
                attempts += 1
                if port_open():
                    return
                # Limit to one attempt every 3 seconds
                wait_exit.wait(3)
        finally:
            spin.locks.global_wakeups.remove(wait_exit)
            wait_exit.set()

        if not port_open():
            raise BackendError(
                f"No SSH server found after {self.timeout} seconds. "
                f"{attempts} attempts"
            )


@dep(requires=WaitForSSH, before="OnBoot")
class OnCreation(StartStep):
    name = "Running on creation"

    @classmethod
    def accepts(cls, machine: CreatedMachine) -> bool:
        return len(machine.on_creation) > 0 and machine.info.boots == 0

    def process(self) -> None:
        up_to = len(self.machine.on_creation)
        files = []
        for index, cmd in zip(range(up_to), self.machine.on_creation.commands):
            shfile = Spinfolder(as_machine(self.machine)).add_file(
                as_machine(self.machine), "on_creation_" + str(index) + ".sh"
            )
            if not cmd.ignore_errors:
                shfile.write_text("set -e\n")
            shfile.write_text(cmd.content)
            files.append(shfile)

        for file in files:
            with open(file, "r", encoding="utf8") as commandfile:
                ret = ssh(as_machine(self.machine), commandfile)
            if ret.returncode != 0:
                raise CommandFailed(ret)


@dep(requires=WaitForSSH)
class OnBoot(StartStep):
    name = "Running on boot"

    @classmethod
    def accepts(cls, machine: CreatedMachine) -> bool:
        return len(machine.on_boot.commands) > 0

    def process(self) -> None:
        up_to = len(self.machine.on_boot.commands)
        files = []
        for index, cmd in zip(range(up_to), self.machine.on_boot.commands):
            shfile = Spinfolder(as_machine(self.machine)).add_file(
                as_machine(self.machine), "on_boot_" + str(index) + ".sh"
            )
            if not cmd.ignore_errors:
                shfile.write_text("set -e\n")
            shfile.write_text(cmd.content)
            files.append(shfile)

        for file in files:
            with open(file, "r", encoding="utf8") as commandfile:
                ret = ssh(as_machine(self.machine), commandfile)
                commandfile.seek(0)
                log: Log.CommandMessage = {
                    "message": commandfile.read(),
                    "message_type": "command",
                    "trigger": "on_boot",
                }
                self.machine.log.log(log)
            if ret.returncode != 0:
                raise CommandFailed(ret)
