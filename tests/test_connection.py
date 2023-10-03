"""Test communication connection channel with guests"""

import os
import pathlib
import pty
import selectors
import subprocess
import termios
import time
import tty
from threading import Event, Thread
from unittest.mock import MagicMock, Mock, call, patch

import pytest

import spin.machine.connection
from spin.errors import CommandFailed
from spin.machine import term
from spin.machine.connection import (
    PTY,
    SerialPort,
    SerialPortConnection,
    SSHHelper,
    print_console,
)
from spin.machine.machine import Machine


class TestSerialPort:
    """Test stream process functionality"""

    @patch("spin.locks.process_stop", autospec=True)
    @pytest.mark.slow
    def test_simple(self, ps_mock: Mock):
        """Test serial port connection works"""
        ps_mock.is_set.return_value = False

        MESSAGES = [b"FIRST_MSG", b"SECOND_MSG"]

        master_fd, slave_fd = pty.openpty()

        tty.setraw(master_fd, when=termios.TCSANOW)
        tty.setraw(slave_fd, when=termios.TCSANOW)

        # For debugging
        print(f"master_fd  {master_fd} -- {os.readlink(f'/proc/self/fd/{master_fd}')}")
        print(f"slave_fd {slave_fd} -- {os.readlink(f'/proc/self/fd/{slave_fd}')}")

        stop_thread = Event()

        def fake_guest() -> None:
            with open(master_fd, "r+b", buffering=0) as term_file:
                selector = selectors.DefaultSelector()
                selector.register(term_file, selectors.EVENT_READ)
                data = bytes()
                while len(data) < len(MESSAGES[0]):
                    while len(selector.select(-1)) == 0:
                        time.sleep(0.1)
                        continue
                    data += term_file.read(len(MESSAGES[0]) * 2)

                assert len(data) == len(MESSAGES[0])
                assert data == MESSAGES[0]
                term_file.write(MESSAGES[1])
                assert stop_thread.wait(120)

        thread = Thread(target=fake_guest)
        thread.start()

        serial_backend = SerialPortConnection(PTY(slave_fd))
        serial = SerialPort(serial_backend)
        serial.open()
        serial.write(MESSAGES[0])

        data = bytes()
        while len(data) < len(MESSAGES[1]):
            new_data = serial.read(1)
            if new_data is None:
                raise Exception("File closed")
            if len(new_data) == 0:
                continue
            data += new_data
        assert data == MESSAGES[1]
        serial.close()
        stop_thread.set()
        thread.join()


class TestXTerm:
    def test_basic(self):
        proc = term.Loggifier()
        # \b Should be removed since its a Controlchar/bell
        input_ = [
            b"\tInitializing download\n",
            b"\b  0% [                         ]",
            b"\b\r 10% [==                       ]",
            b"\b\r 80% [======================   ]",
            b"\b\r100% [=========================]",
            b"\b\x1B[26D Download complete       ]\n",
        ]
        for i in input_:
            proc.add(i)

        expect = [
            "\tInitializing download",
            "  0% [                         ]",
            " 10% [==                       ]",
            " 80% [======================   ]",
            "100% [=========================]",
            "100% [ Download complete       ]",
            "",
        ]

        assert proc.lines == expect

    def test_individual(self):
        # Some sequences we know must be removed completely
        remove_sequences = [
            b"\x1B[445A",
            b"\x1B[1A",
            b"\x1B[A",
            b"\x1B[32;556;2342X",
            b"\x1B7",
            # b"\x1B[0K",
        ]

        for seq in remove_sequences:
            proc = term.Loggifier()
            proc.add(seq)
            assert proc.lines == [""]

    @pytest.mark.slow
    def test_boot_output(self):
        with open("tests/data/alpine-boot-serial", "rb") as f:
            data = f.read(-1)
        with open("tests/data/alpine-boot-log", "r") as f:
            expected = [l.replace("\n", "") for l in f.readlines(-1)]

        assert len(data) == 57344

        log = term.Loggifier()

        ls = log.add(data)
        with open("/tmp/test-log", "w") as f:
            f.writelines([l + "\n" for l in ls])

        assert len(ls) != 0
        assert ls == expected


@pytest.mark.slow
class TestPrintConsole:
    @patch("spin.machine.connection.Thread", autospec=True)
    @patch("spin.machine.connection.open_serial", autospec=True)
    def test_basic(self, open_serial: Mock, thread_mock: Mock) -> None:
        sp_mock = MagicMock(SerialPort)
        open_serial.return_value = sp_mock
        machine = Mock(Machine())
        handle = print_console(machine)

        thread_mock.assert_has_calls(
            [call(target=handle._print, name=f"Printing console from {machine.name}")]
        )
        thread_mock.return_value.start.assert_called()

        sp_mock.close.assert_not_called()
        handle.close()

        sp_mock.open.assert_called_once()
        sp_mock.close.assert_called_once()

    @patch("spin.locks.process_stop", autospec=True)
    @patch("spin.machine.connection.ui", autospec=True)
    def test_real_threads(self, ui_mock: Mock, pss_mock: Mock) -> None:
        machine = MagicMock(Machine())
        pss_mock.is_set.return_value = False
        handle = print_console(machine)
        assert handle.thread.is_alive()
        handle.close()

        assert handle.stop_event.is_set()
        assert not handle.thread.is_alive()
        ui_mock.instance.return_value.guest.assert_not_called()


@pytest.mark.slow
class TestSSH:
    @patch("spin.machine.connection.has_backend", new=lambda _: True)
    @patch("spin.machine.connection.SSHHelper.sorted_credentials", autospec=True)
    @patch("subprocess.Popen", autospec=True)
    def test_basic(self, popen_mock: Mock, pick_cred: Mock) -> None:
        machine = MagicMock(Machine())
        cmd_mock = Mock(str())
        ret = spin.machine.connection.ssh(machine, cmd_mock)

        pick_cred.assert_called_once()
        cred = pick_cred.return_value[0]
        EXPECTED_COMMAND = [
            "ssh",
            "-q",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={machine.folder / machine.uuid / 'known_hosts'}",
            "-o",
            "BatchMode=no",
            "-o",
            f"User={cred.login}",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            f"IdentityFile={cred.identity_file}",
            f"{machine.backend.main_ip}",
            cmd_mock,
        ]
        popen_mock.assert_called_once_with(
            EXPECTED_COMMAND,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )

        assert ret.cmd == EXPECTED_COMMAND

    @patch("spin.machine.connection.has_backend", new=lambda _: True)
    @patch("spin.machine.connection.SSHHelper.sorted_credentials", autospec=True)
    @patch("spin.machine.connection.subprocess", autospec=True)
    def test_check(
        self, subprocess_mock: Mock, cred_mock: Mock, tmp_path: pathlib.Path
    ) -> None:
        subprocess_mock.run.return_value = MagicMock(returncode=3)
        subprocess_mock.Popen.return_value.__enter__.return_value = MagicMock(
            returncode=3
        )
        under_test = SSHHelper(MagicMock(Machine()))

        with pytest.raises(CommandFailed):
            under_test.run("a-command", check=True)
        subprocess_mock.Popen.assert_called_once()

        subprocess_mock.reset_mock()
        fake_input = tmp_path / "input-file"
        fake_input.touch()
        with pytest.raises(CommandFailed), open(fake_input) as stream:
            under_test.run(stream, check=True)
        subprocess_mock.run.assert_called_once()

        ret = under_test.run("a-command")
        assert ret.returncode == 3
        subprocess_mock.Popen.assert_called_once()

        subprocess_mock.reset_mock()
        fake_input = tmp_path / "input-file"
        fake_input.touch()
        with open(fake_input) as stream:
            ret = under_test.run(stream)
        assert ret.returncode == 3
        subprocess_mock.run.assert_called_once()
