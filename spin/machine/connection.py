"""Connectivity functionality for virtual machines"""

from __future__ import annotations

import dataclasses
import ipaddress
import itertools
import pathlib
import re
import selectors
import subprocess
import time
from dataclasses import dataclass
from threading import Event, Lock, RLock, Thread
from typing import Any, BinaryIO, TextIO, Union, cast

from typing_extensions import Literal, Protocol, runtime_checkable

import spin.locks
from spin.errors import (
    TODO,
    BackendError,
    CommandFailed,
    CommandTimeout,
    ConnectionClosed,
    MissingAttribute,
    NoBackend,
    require,
)
from spin.image.image import Image
from spin.machine import credentials, term
from spin.machine.action import Action
from spin.machine.machine import CreatedMachine, Machine, as_machine, has_backend
from spin.machine.shell_input import ShellInput
from spin.utils import ui
from spin.utils.load import Spinfolder

Seconds = Union[int, float]


class Wait(Action):
    """Wait N seconds"""

    seconds: Seconds
    """Seconds to wait. Can be float values for sub-second waits"""

    STORE_NAME = "wait"

    def __init__(self, s: Seconds) -> None:
        """
        Args:
            s: Seconds to wait
        """
        self.seconds = s

    def to_dict(self) -> Action.Serialized:
        return Action.Serialized({"action": self.STORE_NAME, "time": self.seconds})

    @classmethod
    def from_dict(cls, data: dict) -> Wait:
        if data["action"] != cls.STORE_NAME:
            raise ValueError
        return cls(data["time"])

    def execute(self, machine: "Machine") -> bool:
        time.sleep(self.seconds)
        return True


class EjectCDROM(Action):
    """Eject CD-ROM(s) from the machine"""

    STORE_NAME = "eject-cdrom"

    regex: re.Pattern
    """Pattern of the CD-ROMs to eject"""

    def __init__(self, r: Union[str, re.Pattern]) -> None:
        """
        Args:
            r: Pattern of the CD-ROM(s) to eject. The backend will iterate
                over all the CD-ROMs, removing all the matches.
        """
        self.regex = r if isinstance(r, re.Pattern) else re.compile(r)

    def to_dict(self) -> Action.Serialized:
        return Action.Serialized(
            {
                "action": self.STORE_NAME,
                "regex": str(self.regex.pattern),
            }
        )

    @classmethod
    def from_dict(cls, data: dict) -> EjectCDROM:
        if data["action"] != cls.STORE_NAME:
            raise ValueError
        return cls(data["regex"])

    def execute(self, machine: "Machine") -> bool:
        if not machine.is_shutoff():
            raise Exception("Cannot eject if machine is running")
        removed = machine.eject_cdrom(self.regex)
        return len(removed) > 0


class PowerControl(Action):
    """Power control the machine; boot, reboot, poweroff.

    Can be used during 'complex' installations that require multiple boots
    to configure.
    """

    STORE_NAME = "power_control"
    SUPPORTED_OPERATIONS = ("boot", "acpi_reboot", "acpi_poweroff")

    def __init__(
        self, operation: Literal["boot", "acpi_reboot", "acpi_poweroff"]
    ) -> None:
        self.operation = operation

    def to_dict(self) -> Action.Serialized:
        return Action.Serialized(
            {"action": self.STORE_NAME, "operation": self.operation}
        )

    @classmethod
    def from_dict(cls, data: dict) -> PowerControl:
        if data["action"] != cls.STORE_NAME:
            raise ValueError
        return cls(data["operation"])

    def execute(self, machine: "Machine") -> bool:
        if machine.backend is None or isinstance(machine.backend, type):
            raise NoBackend
        if self.operation == "boot":
            if not machine.is_shutoff():
                return True
            machine.start()
            return True
        if self.operation == "acpi_reboot":
            return machine.backend.acpi_reboot(timeout=60)[0]
        if self.operation == "acpi_poweroff":
            return machine.backend.acpi_shutdown(timeout=60)[0]
        return False

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(operation={self.operation})"


class ShellAction(Action):
    """Shell action, to be executed with a Shell object"""

    STORE_NAME = "shell"

    def __init__(self, command=None) -> None:
        """
        Args:
            command: The command to execute, will be processed with
                ShellInput.
        """
        self.input = ShellInput(None)
        if command is not None:
            self.input.add_command(command)

    def to_dict(self) -> Action.Serialized:
        return Action.Serialized(
            {
                "action": self.STORE_NAME,
                "commands": [c.dict() for c in self.input.commands],
            }
        )

    @classmethod
    def from_dict(cls, data: dict) -> ShellAction:
        if data["action"] != cls.STORE_NAME:
            raise ValueError
        shell = cls()
        shell.input.commands = data["commands"]
        return shell

    def __ilshift__(self, cmd: str) -> ShellAction:
        self.input.add_command(cmd)
        return self

    def execute(self, machine: "Machine") -> bool:
        with open_shell(machine) as shell:
            for cmd in self.input.commands:
                exitstatus = shell.execute(cmd.content, timeout=120)
                if exitstatus in ("failure",):
                    return False
        return True


class UserInputSimulator:
    """Simulate person input, for usage with slow interfaces such as serial

    The :py:func:`type` method support 'tokens', which are described in the
    :py:class:`Token` class.
    """

    SerializedSequence = Action.SerializedSequence

    sequence: list[Action]
    """Sequence of inputs"""

    def __init__(self, sequence: None | list[Action] = None) -> None:
        self.sequence = [] if sequence is None else sequence

    def __enter__(self) -> "UserInputSimulator":
        return self

    def __exit__(self, *args):
        # We have no processing to do
        return False

    def wait(self, seconds: Seconds):
        """Wait *s* seconds

        During installation the function will effectively wait *s* **real**
        seconds.
        """
        self.sequence.append(Wait(seconds))

    def __ilshift__(self, cmd: str) -> UserInputSimulator:
        shell = ShellAction(cmd)
        self.sequence.append(shell)
        return self

    def eject_cdrom(self, regex: Union[str, re.Pattern]) -> None:
        """Eject a CDROM from the machine

        The machine has to be powered off.

        Args:
            regex: Pattern of the CD-ROM(s) to eject. The backend will iterate
                over all the CD-ROMs, removing all the matches.
        """
        self.sequence.append(EjectCDROM(r=regex))

    def boot(self) -> None:
        """Boot the machine

        Send a boot/start signal to the backend. Does nothing if the machine is
        already running.

        Can be used during 'complex' installations that require multiple boots
        to configure.
        """
        self.sequence.append(PowerControl("boot"))

    def reboot(self) -> None:
        """Reboot the guest.

        Sends an ACPI signal to reboot the machine. Make sure the guest OS
        is ready to be rebooted.

        Normally used to apply updates, or reboot into the OS after using
        an installation media.
        """
        self.sequence.append(PowerControl("acpi_reboot"))

    def shutdown(self) -> None:
        """Shutdown the guest.

        Sends an ACPI signal to shutdown the machine. Make sure the guest OS
        is ready to be poweredoff.

        Normally used to apply updates, or boot into the OS after using
        an installation media.
        """
        self.sequence.append(PowerControl("acpi_poweroff"))

    poweroff = shutdown

    def to_dict(self) -> Action.SerializedSequence:
        """Export the sequence of commands in JSON compatible dicts

        Returns:
            A list of dictionaries, to be called later with :py:func:`from_dict`.
        """
        return [s.to_dict() for s in self.sequence]


@runtime_checkable
class SerialConnection(Protocol):
    """Protocol specification for serial connections

    The API is file-ish, to ease integration with other classes.

    This acts as a base class for different serial connections specifications,
    since different backends can implement serial port connections differently.
    """

    def __enter__(self) -> SerialConnection:
        ...

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        ...

    def open(self) -> None:
        """Open the serial connection"""

    def close(self) -> None:
        """Close the serial connection."""
        ...

    def read(self, at_most: int) -> bytes:
        """Read at_most bytes from the serial port.

        Args:
            at_most: The maximum number of bytes to retrieve.

        Returns:
            A sequence of bytes with length less or equal to *at_most*. Can
            be empty if there are no bytes.
        """
        ...

    def write(self, data: bytes) -> int:
        """Write data to the serial port.

        Args:
            data: The data to send.

        Returns:
            The number of bytes written.
        """
        ...


class PTY(SerialConnection):
    """Implements a serial connection through a PTY file"""

    def __init__(self, fd) -> None:
        """
        Args:
            fd: File descriptor or path-like object to the TTY.
        """
        self.file = fd
        self._stream: BinaryIO
        self._thread = Thread(target=self._poll, name="pty-read-poll")
        self._stop_polling = Event()
        self._buffer = bytes()
        self._buflock = Lock()

    def _poll(self) -> None:
        select = selectors.DefaultSelector()
        select.register(self._stream, selectors.EVENT_READ)
        while not self._stop_polling.is_set():
            if len(select.select(-1)) > 0:
                data = self._stream.read(4096)
                with self._buflock:
                    self._buffer = self._buffer + data
            self._stop_polling.wait(0.05)

    def __enter__(self) -> SerialConnection:
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> Literal[False]:
        self.close()
        return False

    def open(self) -> None:
        self._stream = open(self.file, "r+b", buffering=0)
        self._thread.start()

    def close(self) -> None:
        if hasattr(self, "_stream") and not self._stream.closed:
            self._stop_polling.set()
            self._thread.join()
            self._stream.close()

    def read(self, at_most: int) -> bytes:
        with self._buflock:
            ret = self._buffer[:at_most]
            self._buffer = self._buffer[at_most:]
        return ret

    def write(self, data: bytes) -> int:
        return self._stream.write(data)


class SerialPortConnection:
    """Serial connection with a machine.

    The object buffers the data sent by the machine so it can be read by
    several clients without losing information.

    The class contains locks to avoid simultaneous writes to the machine.

    Reading is performed on a separate thread.
    """

    def __init__(self, conn: "Machine | SerialConnection") -> None:
        """
        Args:
            pty: a path or file descriptor to the TTY/PTY file, or the machine to
                retrieve the console port file from.

        Raises:
            NoBackend: If, when supplied with a :py:class:`Machine`, it has no
                backend.
            ValueError: If the machine does not have a console port
        """
        from spin.machine.machine import Machine

        self.machine: None | Machine = None

        if isinstance(conn, Machine):
            self.machine = conn
            if isinstance(conn.backend, type) or conn.backend is None:
                raise NoBackend
            port_file = conn.backend.console_port()
            if port_file is None:
                raise ValueError("Machine backend reports no console port")
            conn = port_file

        self.conn: SerialConnection = conn
        """File-like object used as a PTY endpoint."""

        self._is_open = False

        self._lock = RLock()
        """Lock used to read and write information to the read buffer."""

        self._readbuffer: list[int] = []
        """Buffer containing the bytes/data sent by the guest."""

        self._readthread: Thread
        """Thread in charge of reading data sent by the guest."""

        self._reader_event = Event()
        """Synchronization mechanism with the reader thread."""

        self.clients: set[Any] = set()
        """Set of 'clients' read/writing from/to this connection.
        
        Increases on :py:func:`register`, decreases on :py:func:`unregister`. When 
        the set is empty again, the file is closed. Until then there are clients and
        cannot be closed.
        """

        self._async_exce: None | Exception = None
        """Exception raised in reader thread"""

    def _spawn_reader(self) -> None:
        """Create a reader thread, stores stuff in _readbuffer."""

        def read() -> None:
            while not self._reader_event.is_set():
                try:
                    buf = self.conn.read(4096)
                    if len(buf) == 0:
                        self._reader_event.wait(0.1)
                        continue
                    with self._lock:
                        self._readbuffer.extend(buf)
                except Exception as exce:
                    self._async_exce = exce
                    self._is_open = False
                    break

        self._readthread = Thread(target=read, name="serialport-reader")
        self._readthread.start()

    def is_open(self) -> bool:
        """Check if the port is open.

        Returns: ``True`` if the port is open, false otherwise.
        """
        with self._lock:
            return self._is_open

    def _open(self) -> None:
        """Open the serial port to the machine"""
        with self._lock:
            self.conn.open()
            spin.locks.global_wakeups.add(self._reader_event)
            self._spawn_reader()
            self._is_open = True

    def _close(self, *, force: bool = False) -> bool:
        """Close the console port (which is actually a file or pipe)

        Args:
            force: If set to ``True``, ignore any remaining clients.
                Normally used when an exception is raised and the serial port
                `must` be closed.

        Returns:
            ``True`` if the port was closed, ``False`` if there are still clients
            attached.
        """
        with self._lock:
            if force and len(self.clients) > 0:
                ui.instance().warning(
                    f"Serial port {self.conn} has {len(self.clients)}. Closing anyway."
                )
            else:
                if len(self.clients) > 0:
                    ui.instance().debug(
                        f"Serial port {self.conn} has {len(self.clients)}. Not closing."
                    )
                    return False
                ui.instance().debug(f"No remaining clients. Closing {self.conn}")
            self._reader_event.set()
            self._readthread.join()
            self.conn.close()
            self._reader_event.clear()
            self._is_open = False
            spin.locks.global_wakeups.remove(self._reader_event)
            return True

    def buffersize(self) -> int:
        """Length of the buffer; number of bytes sent by the guest.

        Returns:
            The size of the read buffer.
        """
        with self._lock:
            return len(self._readbuffer)

    def check_status(self) -> Literal[True]:
        """Check the status of the port.

        Raises:
            Exception: The exception found in the reader thread.
            ConnectionClosed: If the exception found was ConnectionClosed (the
                most likely one).

        Returns:
            ``True``, or raises an exception.
        """
        if self._async_exce is not None:
            # We do not close here. If the user used the appropriate with
            # statement the port will be closed later
            raise self._async_exce
        return True

    def register(self, client: Any) -> None:
        """Register a new client using this port."""
        self.check_status()
        with self._lock:
            if not self._is_open:
                self._open()
            self.clients.add(client)

    def unregister(self, client: Any) -> None:
        """Remove a previously registered client."""
        self.check_status()
        with self._lock:
            self.clients.remove(client)
            if len(self.clients) == 0:
                self._close()

    def get(self, start: int, count: int = -1) -> bytes:
        """Read data sent by the guest.

        Args:
            start: The index of the first byte
            count: The number of bytes to retrieve (at most). Pass -1 to read
                all available data.

        Returns:
            A byte container with between 0 and *count* elements.
        """
        self.check_status()
        if count < -1 or count == 0:
            raise ValueError(f"Invalid count value {count}")
        if count == -1:
            with self._lock:
                ret = self._readbuffer[start:]
        else:
            with self._lock:
                ret = self._readbuffer[start : start + count]
        return bytes(ret)

    def write(self, data: bytes) -> int:
        """Write *data* to the machine

        Args:
            data: Data to write

        Returns:
            The number of bytes written.
        """
        self.check_status()
        with self._lock:
            try:
                return self.conn.write(data)
            except OSError as excep:
                if excep.errno != 5:
                    raise
                msg = f"File: {self.conn}"
                if self.machine is not None:
                    msg += f", Machine: {self.machine}"
                raise ConnectionClosed(msg) from excep


class Shell:
    """A Shell connected to a machine.

    Warning: the shell(s) run expecting a human user, the library attempts to
        parse and understand the state of the shell based on the characters
        transmitted by console port.
    """

    END_SEQUENCE = b"# \x1b[6n"
    """Final sequence sent by bash when it is ready to accept a new command

    Warning: the original intention of the escape sequence is for the terminal
        to send the current cursor position; so there is a change the sequence
        is used in other circumstances too.

    Warning: currently targets Linux (and possibly POSIX) shells only.
    """

    def __init__(
        self, machine: "Machine", *, method: Literal["ssh", "serial_port"]
    ) -> None:
        """
        Args:
            machine: The machine to connect to.
            method: The channel to use for communication.
        """
        self.machine = machine
        """The machine this shell is going to connect."""

        self.method = method
        """Communication channel used to connect to the machine."""

        self.connection: SerialPort
        """The current connection to the machine"""

        self.encoding: str = "utf8"
        """Encoding used by the guest machine"""

    def open(self) -> None:
        """Open the shell. Connect to console port and login.

        Raises:
            Exception: If the connection could not be opened.
        """
        if self.method != "serial_port":
            raise TODO
        self.connection = open_serial(self.machine)
        self.connection.open()

        assert isinstance(self.machine.image, Image)

        credentials = self.machine.image.credentials
        if not require(credentials):
            raise MissingAttribute(self.machine.image, "credentials")
        user, passwd = credentials.user, credentials.password

        retries = 0
        login_found = False
        while retries < 5 and not login_found:
            try:
                exitstatus = self.write_and_wait("\n", wait_for=b"login:", timeout=30)
                login_found = exitstatus != "failure"
            except CommandTimeout:
                retries += 1
        if retries == 5:
            raise Exception(f"Could not open port after {retries} attempts")

        if passwd is not None:
            exitstatus = self.write_and_wait(
                f"{user}\n", wait_for=b"password:", timeout=10
            )
            if exitstatus in ("failure",):
                raise Exception
            exitstatus = self.write_and_wait(
                f"{passwd}\n", wait_for=self.END_SEQUENCE, timeout=30
            )
            if exitstatus in ("failure", "timeout"):
                raise Exception
        else:
            exitstatus = self.write_and_wait(
                f"{user}\n", wait_for=self.END_SEQUENCE, timeout=10
            )
            if exitstatus in ("failure",):
                raise Exception

        # TODO: Let the user choose the shell
        self.write_and_wait("sh\n", wait_for=self.END_SEQUENCE, timeout=5)

    def close(self, *, force: bool = False) -> None:
        """Close the shell.

        Raises:
            Exception: If the connection was active and could not be closed.

        Returns:
            ``False`` if the connection is already closed.
        """
        # HACK: Find a pattern to check the shell exits successfully
        if force:
            if self.connection.is_open:
                self.connection.close()
            return
        try:
            exitstatus = self.write_and_wait(
                "exit\n", wait_for=self.END_SEQUENCE, timeout=10
            )
            if exitstatus in ("failure",):
                self.connection.close()
                raise Exception
            exitstatus = self.write_and_wait("exit\n", wait_for=b"login:", timeout=10)
            if exitstatus in ("failure",):
                raise Exception
        except CommandTimeout as cmd_tout:
            raise cmd_tout
        finally:
            self.connection.close()

    def __enter__(self) -> Shell:
        try:
            self.open()
        except:
            self.close(force=True)
            raise
        return self

    def __exit__(self, exce_type, *_) -> Literal[False]:
        if exce_type is not None:
            ui.instance().error("Found an exception. Attempting to close the shell")
        self.close(force=exce_type is not None)
        return False

    def write_and_wait(
        self, data: str | bytes, wait_for: bytes, *, timeout: float = 30
    ) -> Literal["ok", "failure", "unknown"]:
        """Write *data* to the console, and wait for *wait_for*.

        Args:
            data: Data to send through the serial port. No newline is appended,
                so be sure to append a carriage return for commands. If a
                :py:class:`str` is given, it is encoded and sent as bytes.
            wait_for: The sequence of bytes to expect after the data is sent.
                For instance the sequence :py:attr:`END_SEQUENCE`.
            timeout: Maximum time to wait.

        Raises:
            CommandTimeout: If after *timeout* seconds, no command end is
                found.

        Returns:
            - ``"ok"`` if the command was successful,
            - ``"failure"`` if the command failed,
            - ``"finish"`` if the end of command was found before *timeout*,
                but the function is unable to determien the exit status, and
        """

        @dataclass
        class ShellOutput:
            """Stores information about an issued command"""

            def __init__(self) -> None:
                self.out: bytes = bytes()
                """Messages sent by the console"""

                self.exit = False
                """True if the command finish"""

                self.exce: None | Exception = None
                """Exception raised by the reader thread."""

        if self.connection is None:
            raise Exception("Communication channel not open")

        stop = Event()
        timeout_event = Event()
        sh_output = ShellOutput()
        if isinstance(data, str):
            data = data.encode(self.encoding)

        def read() -> None:
            """Read until the shell returns control or wakes"""
            loggifier = term.Loggifier()

            console = self.connection
            # The console buffer stores all the information since its creation,
            # we need to consume only from *now* to avoid reading previous
            # sequences
            while not any([stop.is_set(), sh_output.exit, sh_output.exce is not None]):
                try:
                    buf = console.read(-1)
                    if buf is None:
                        raise ConnectionClosed()
                    if len(buf) == 0:
                        stop.wait(0.1)
                        continue
                    new_lines = loggifier.add(buf)
                    for line in new_lines:
                        ui.instance().guest(self.machine.name or "unnamed", line)
                        self.machine.log(line, "console")

                    sh_output.out += buf
                    sh_output.exit = wait_for in sh_output.out
                    if sh_output.exit:
                        ui.instance().debug(f"Found end of command ({wait_for!r})")
                except Exception as exce:
                    sh_output.exce = exce

            timeout_event.set()

        reader_thread = Thread(target=read, name="shell-reader")
        reader_thread.start()
        self.connection.write(data)

        timeout_event.wait(timeout=timeout)
        stop.set()
        reader_thread.join()

        if sh_output.exce is not None:
            ui.instance().error("Exception while waiting for command end")
            raise sh_output.exce

        if not sh_output.exit:
            ui.instance().error(
                f"String {data[:40]!r} timeout. Could not find {wait_for!r}"
            )
            raise CommandTimeout(str(data), timeout=timeout)
        return "unknown"

    def execute(
        self, cmd: str, *, timeout: int | float = 120
    ) -> Literal["ok", "failure", "unknown"]:
        """Execute a command in the shell; wait for it to finish.

        The 'end' of the command is *autodetected*, by searching for special
        control characters normally sent when the shell writes PS1. This can
        fail and works only on ``sh``.

        Args:
            data: The command to execute.
            timeout: Maximum time to wait.

        Raises:
            CommandTimeout: If after *timeout* seconds, no command end is
                found.

        Returns:
            - ``"ok"`` if the command was successful,
            - ``"failure"`` if the command failed,
            - ``"finish"`` if the end of command was found before *timeout*,
                but the function is unable to determien the exit status.
        """
        ui.instance().debug(
            f"Sending command {cmd.encode('utf8')!r}. Waiting {timeout} seconds."
        )
        if not cmd.endswith("\n"):
            cmd += "\n"
        return self.write_and_wait(
            cmd.encode(self.encoding),
            wait_for=self.__class__.END_SEQUENCE,
            timeout=timeout,
        )


class SerialPort:
    """Serial port access through a file-style interface."""

    def __init__(self, conn: SerialPortConnection) -> None:
        self.conn = conn
        """Shared connection to the port."""

        self.is_open = False
        """Indicates whether the serial port is open."""

        self._index = 0

    def __enter__(self) -> SerialPort:
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, traceback) -> Literal[False]:
        if not self.is_open:
            return False
        self.close()
        return False

    def open(self) -> None:
        """Open the serial port

        Raises:
            Exception: If the port is already open.
        """
        if self.is_open:
            raise Exception("Port already open")
        self.conn.register(self)
        self._index = self.conn.buffersize()
        self.is_open = True

    def close(self) -> None:
        """Close the serial port."""
        self.conn.unregister(self)
        self._index = 0
        self.is_open = False

    def read(self, at_most: int) -> None | bytes:
        """Read *at_most* bytes from the serial port. Non-blocking.

        If there is no new data, returns an empty bytes() object.

        If the port has been closed --or EOF is reached--, return None.

        Args:
            at_most: The maximum number of bytes to read. Pass -1 to read
                all the data available.

        Returns:
            A ``bytes`` object with at most *at_most* elements. Or ``None``
            if the port was closed.
        """
        new_data = self.conn.get(self._index, at_most)
        if new_data is not None:
            self._index += len(new_data)
        return new_data

    def write(self, data: bytes) -> int:
        """Write *data* to the port.

        Args:
            data: The sequence of bytes to write

        Returns:
            The number of bytes written
        """
        return self.conn.write(data)


open_serial_ports: dict[str | Any, SerialPortConnection] = {}
"""Contains all the currently open serial ports.

Key can be a UUID (as a string) or ``Any`` for 'detached' serial ports
without an associated machine
"""


def open_serial(machine: "Machine") -> SerialPort:
    """Safely open a serial port.

    The function checks if the port is already open to avoid
    multiple readers.

    Args:
        machine: The machine to connect to.

    Returns:
        A serial port with an file-ish API.
    """
    if machine.uuid not in open_serial_ports:
        open_serial_ports[machine.uuid] = SerialPortConnection(machine)
    else:
        ui.instance().debug("Serial port to machine already open")
    return SerialPort(open_serial_ports[machine.uuid])


@dataclasses.dataclass
class SSHOutput:
    """Structure returned by an SSH incocation."""

    cmd: list[str]
    returncode: int
    stdout: bytes
    stderr: bytes


class SSHHelper:
    """Helper class for performing SSH connections"""

    def __init__(
        self,
        machine: Machine,
        *,
        capture_output: bool = True,
        flags: None | list[str] = None,
        login: None | str = None,
        identity_file: None | pathlib.Path = None,
        decorate_out: bool = False,
    ) -> None:
        """
        Args:
            machine: The machine to connect to.
            capture_output: Same as ``subprocess.run`` ``capture_output`` keyword.
            flags: Extra flags to pass to ``ssh(1)`` or ``scp(1)``.
            login: The user to login as.
            idenity_file: The identity file to use.
            decorate_out: If set to `True`, the output may be decorated by prepending
                the guest name.
        """
        self.target = machine
        if self.target.folder is None:
            raise ValueError("Machine has no folder")

        self.capture_output = capture_output
        self.known_hosts = Spinfolder(location=self.target.folder).add_file(
            self.target, "known_hosts"
        )
        self.host_checking = "accept-new"
        self.flags = [] if flags is None else flags
        self.login = login
        self.identity_file = identity_file
        self.decorate_out = decorate_out

    def __enter__(self) -> SSHHelper:
        return self

    def __exit__(self, *_):
        pass

    def _ip_or_raise(self) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
        if not has_backend(self.target):
            raise NoBackend
        ip = self.target.backend.main_ip
        if ip is None:
            raise BackendError("Machine has no IP")
        return ip

    def run(
        self,
        command: str | TextIO | BinaryIO,
        check: bool = False,
    ) -> SSHOutput:
        """Run the given command or connect the given IO through ``ssh(1)``"""
        ip = self._ip_or_raise()
        creds = self.sorted_credentials()
        cred = creds[0]

        opts = self.connection_opts(
            user=cred.login,
            batch=False,
            identity_file=cred.identity_file,
        )

        kwargs: dict[str, Any] = {}

        if isinstance(command, str):
            last_arg = [command]
        else:
            kwargs["stdin"] = command
            last_arg = []

        cmd = ["ssh", *opts, str(ip), *last_arg]
        if not ui.instance().verbose:
            cmd.insert(1, "-q")
        ui.instance().debug(cmd)

        if isinstance(command, str) or self.decorate_out:
            # We capture the output *only* if we receive an explicit command;
            # in any other case it means we are piping; and we do not want
            # any delay.
            stdout: list[bytes] = []
            stderr: list[bytes] = []

            with subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                **kwargs,
            ) as process:
                assert process.stdout is not None
                for output in process.stdout:
                    output_ = cast("bytes", output)
                    ui.instance().guest(
                        self.target.name or "unknown", output_.decode("utf8")
                    )
                    stdout.append(output_)
                for output in process.stderr or []:
                    output_ = cast("bytes", output)
                    ui.instance().guest(
                        self.target.name or "unknown", output_.decode("utf8")
                    )
                    stderr.append(output_)

            cmdout = SSHOutput(
                cmd, process.returncode, b"".join(stdout), b"".join(stderr)
            )

            if check is True and cmdout.returncode != 0:
                raise CommandFailed(cmdout)

            return cmdout
        ret = subprocess.run(cmd, check=False, **kwargs)

        cmdout = SSHOutput(cmd, ret.returncode, b"", b"")
        if check is True and cmdout.returncode != 0:
            raise CommandFailed(cmdout)
        return cmdout

    execute = run

    def _copy(self, source: str, target: str) -> SSHOutput:
        cred = self.sorted_credentials()[0]

        opts = self.connection_opts(
            user=self.login or cred.login,
            batch=False,
            identity_file=self.identity_file or cred.identity_file,
        )

        kwargs: dict[str, Any] = {}

        cmd = ["scp", *opts, source, target]

        ret = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            **kwargs,
        )
        return SSHOutput(cmd, ret.returncode, ret.stdout, ret.stderr)

    def copy_to(self, source: pathlib.Path, target: pathlib.PurePath):
        """Copy file *src* into *dest* in the guest.

        Returns: ``True`` on success.
        """
        return self._copy(str(source), f"{str(self._ip_or_raise())}:{str(target)}")

    def copy_from(self, target: pathlib.PurePath, source: pathlib.Path):
        """Copy file *source* in host to *target* in the guest.

        Returns: ``True`` on success.
        """
        return self._copy(f"{str(self._ip_or_raise())}:{str(target)}", str(source))

    scp_to = copy_to
    scp_from = copy_from

    def sorted_credentials(self) -> list[credentials.SSHCredential]:
        """Sort credentials according to 'quality'

        The function will check the available credentials
        and sort them according to the values it has.

        The scores are calibrated via trial and error.

        Return: sorted list of credentials, first elements are 'better'.

        Raises: ValueError is sequence is empty
        """

        def cred_score(cred: credentials.SSHCredential) -> int:
            score = 0
            score += +2 if cred.login is not None else -2
            if cred.identity_file is None:
                score -= 1
            if cred.comment is not None and cred.comment.startswith(
                "insecure-key-for-"
            ):
                score += 1
            return score

        creds = [(c() if callable(c) else c) for c in self.target.ssh]

        if len(creds) == 0:
            raise ValueError("Empty sequence")

        ret = sorted(creds, key=cred_score, reverse=True)
        for entry in ret:
            ui.instance().debug(f"{cred_score(entry)}: {entry}")
        return ret

    def connection_opts(
        self,
        user: None | str = None,
        batch: bool = False,
        identity_file: None | pathlib.Path = None,
    ) -> list[str]:
        """Generate the list of options (``-o``) required to connect to the machine.

        Args:
            user: The user/login to connect as.
            batch: same as ``ssh_config(5)`` ``Batch`` option.
            identity_file: same as ``ssh_config(5)`` ``IdenityFile`` option.

        Returns: A list of string, where each pair of elements is the ``-o`` flag
            followed by an option; ready to be passed to ``ssh(1)``.
        """
        args = [
            f"StrictHostKeyChecking={self.host_checking}",
            f"UserKnownHostsFile={self.known_hosts}",
            f"BatchMode={'yes' if batch else 'no'}",
        ]

        if user is not None:
            args.append(f"User={user}")

        if identity_file is not None:
            args.extend(["IdentitiesOnly=yes", f"IdentityFile={identity_file}"])

        return (
            list(
                itertools.chain.from_iterable(
                    zip(["-o" for _ in range(len(args))], args)
                )
            )
            + self.flags
        )


def ssh(
    machine: Machine | CreatedMachine,
    command: str | list[str] | TextIO,
    login: None | str = None,
    identity_file: None | pathlib.Path = None,
    capture_output: bool = True,
    decorate_out: bool = False,
) -> SSHOutput:
    """
    Args:
        machine: The :py:class:`Machine` to connect to.
        command: The command to execute. Can be a str (or list of) to pass as
            command and arguments; or a TextIO which will be connected as
            ``stdin`` simulating a pipe to ``ssh(1)``.
        login: The user to login as.
        idenity_file: The identity file to use.
        capture_output: Same as ``subprocess.run`` ``capture_output`` keyword.
    """
    if isinstance(command, list):
        command = " ".join(command)
    machine = as_machine(machine)
    return SSHHelper(
        machine,
        login=login,
        identity_file=identity_file,
        capture_output=capture_output,
        decorate_out=decorate_out,
    ).run(command)


def open_ssh(machine: "Machine", **kwargs) -> SSHHelper:
    """Open a *maybe* persistent SSH connection to the given machine.

    Args:
        machine: The machine to connect to.
        kwargs: Kwargs to forward to SSHHelper.

    Returns:
        An SSHHelper pointing to the requested machine.

    Raises:
        ValueError if the machine has no folder, i. e. is not created
        yet.
    """
    if machine.folder is None:
        raise ValueError
    return SSHHelper(machine, **kwargs)


def open_shell(
    machine: "Machine", *, method: Literal["ssh", "serial_port"] = "serial_port"
) -> Shell:
    """Open a shell to the given machine."""

    return Shell(machine=machine, method=method)


class _Handle:
    """Manage a console port being forwarded to stdout"""

    def __init__(self, port: SerialPort, machine_name: str) -> None:
        """
        Args:
            port: The serial port to forward to stdout
        """
        self.port: SerialPort = port
        self.machine_name = machine_name

        self.stop_event = Event()
        spin.locks.global_wakeups.add(self.stop_event)
        self.thread = Thread(
            target=self._print, name=f"Printing console from {machine_name}"
        )
        self.thread.start()

    def _print(self) -> None:
        loggifier = term.Loggifier()
        while not self.stop_event.is_set():
            buf = self.port.read(-1)
            if buf is None:
                return
            if len(buf) == 0:
                self.stop_event.wait(0.1)
                continue
            new_lines = loggifier.add(buf)
            for line in new_lines:
                ui.instance().guest(self.machine_name, line)

    def close(self) -> None:
        """Close the port/stop printing to stdout"""
        self.stop_event.set()
        self.port.close()
        self.thread.join(timeout=10)
        spin.locks.global_wakeups.remove(self.stop_event)


def print_console(machine: "Machine") -> _Handle:
    """Print console output to stdout.

    Useful for debugging boot problems and/or inspect the
    boot procedure.
    """
    serial_port = open_serial(machine)
    serial_port.open()
    return _Handle(serial_port, machine.name or "unnamed")
