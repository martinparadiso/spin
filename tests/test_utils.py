"""Test the `spin.utils` module"""

import pathlib
from hashlib import sha256
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, call, patch

import pytest

import spin.machine.machine
import spin.utils.config
import spin.utils.fileparse
import spin.utils.info
import spin.utils.load
import spin.utils.spinfile
from spin.machine.credentials import SSHCredential
from spin.utils import Size


def test_size():
    # Note: the list should cover more combinations

    assert Size(1024).bytes == 1024
    assert Size("1024B").bytes == 1024
    assert Size("1024Bytes").bytes == 1024

    assert Size("1024KB").bytes == 1024000
    assert Size("1024KBytes").bytes == 1024000
    assert Size("1024KiloBytes").bytes == 1024000
    assert Size("1024MBytes").bytes == 1024000000
    assert Size("1024MegaBytes").bytes == 1024000000
    assert Size("1024GBytes").bytes == 1024000000000
    assert Size("1024GigaBytes").bytes == 1024000000000

    assert Size("1024KiB").bytes == pow(2, 20)
    assert Size("1024MiB").bytes == pow(2, 30)
    assert Size("1024GiB").bytes == pow(2, 40)
    assert Size("1024TiB").bytes == pow(2, 50)

    assert Size("1024Ki").bytes == pow(2, 20)
    assert Size("1024Mi").bytes == pow(2, 30)
    assert Size("1024Gi").bytes == pow(2, 40)
    assert Size("1024Ti").bytes == pow(2, 50)


class TestDownload:
    LOCALSERVER = "localhost:12633"
    NULLIMG_PATH = "null.img"
    NULLIMG_1024_DIGEST = (
        "5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef"
    )

    class LocalServer:
        def __init__(self):
            pass

        def start(self):
            import http.server as server
            import threading

            server_address = ("", int(TestDownload.LOCALSERVER.split(":")[-1]))
            self.httpd = server.HTTPServer(
                server_address, server.SimpleHTTPRequestHandler
            )
            self.thread = threading.Thread(target=lambda: self.httpd.serve_forever())
            self.thread.start()

            with open(TestDownload.NULLIMG_PATH, "wb") as ni:
                ni.write(bytes(1024))

        def stop(self):
            try:
                Path(TestDownload.NULLIMG_PATH).unlink()
                self.httpd.shutdown()
                self.thread.join()
            except:
                raise

    @pytest.mark.parametrize("file", [f"http://{{server}}/{NULLIMG_PATH}"])
    @pytest.mark.slow
    def test_download(self, file: str, tmpdir):
        """

        This test requires an instance of the Server class to be running; if
        the variable
        """
        from pathlib import Path

        from spin.utils.transfer import NetworkTransfer

        local_file_server = None
        server = self.__class__.LOCALSERVER

        try:
            local_file_server = self.__class__.LocalServer()
            local_file_server.start()

            remotefile = file.format(server=server)
            localfile = Path(tmpdir) / "download"

            with open(localfile, "wb") as dst, NetworkTransfer(
                remotefile, dst
            ) as transfer:
                transfer.download()

            with open(localfile, "rb") as f:
                h = sha256(f.read())
                digest = h.hexdigest()

            assert digest == self.NULLIMG_1024_DIGEST

        finally:
            if local_file_server is not None:
                local_file_server.stop()


class TestInfo:
    """Test the retrieval of information from several sources."""

    @patch("platform.machine")
    def test_host_arch(self, MockPlatformMachine: Mock) -> None:
        MockPlatformMachine.return_value = "x86_64"
        assert spin.utils.info.host_architecture() == "x86_64"
        MockPlatformMachine.assert_called_once()
        MockPlatformMachine.reset_mock(return_value=True)
        MockPlatformMachine.return_value = "mistery_arch"

        with pytest.raises(Exception) as exce_info:
            spin.utils.info.host_architecture()
        assert "Unknown architecture" in str(exce_info)
        assert "mistery_arch" in str(exce_info)


CONF_DATA = """
[defaults]
backend = 'libvirt'
cpus = 2
memory = '2GiB'

[plugins.libvirt]
uri = 'qemu:///session'
"""


class TestConfig:
    """Test configuration construction, deserialization, etc."""


class TestSettingLoad:
    """Load settings/configurations"""

    def test_load_toml(self, tmpdir) -> None:
        """Load the configuration from a TOML file"""
        with open(pathlib.Path(tmpdir) / "conf.toml", "w", encoding="utf8") as conf:
            conf.write(CONF_DATA)

        some_conf = spin.utils.config.Configuration(home=tmpdir)
        spin.utils.config.load_config(pathlib.Path(tmpdir) / "conf.toml", some_conf)

    def test_empty_load(self) -> None:
        spin.utils.config.Settings()

    def test_invalid_size(self) -> None:
        INVALID_INPUT: Any = {"defaults": {"memory": -3}}
        with pytest.raises(ValueError):
            spin.utils.config.Settings(**INVALID_INPUT)


class TestSpinfileUtils:
    """Test the utilities designed to be used from within a spinfile"""

    def test_read_key(self) -> None:
        assert spin.utils.spinfile.read_key("tests/data/key.pub")() == SSHCredential(
            "ssh-rsa THIS_IS_NOT_A_KEY and_a_comment\n", None, None
        )
        assert spin.utils.spinfile.read_key(
            "tests/data/key.pub", "user"
        )() == SSHCredential("ssh-rsa THIS_IS_NOT_A_KEY and_a_comment\n", "user", None)

    @patch("spin.utils.spinfile.subprocess", autospec=True)
    @patch("spin.utils.spinfile.content")
    @patch("spin.utils.spinfile.ui", autospec=True)
    def test_gen_key(
        self, ui_mock: Mock, content_mock: Mock, subp_mock: Mock, tmpdir: pathlib.Path
    ) -> None:
        new_key = spin.utils.spinfile.gen_ssh_keys()()
        assert new_key.pubkey == content_mock().strip()
        assert new_key.login is None
        assert new_key.identity_file is not None
        subp_mock.run.assert_called_with(
            [
                "ssh-keygen",
                "-t",
                "rsa",
                "-b",
                "4096",
                "-C",
                "",
                "-q",
                "-N",
                "",
                "-f",
                str(new_key.identity_file),
            ],
            check=True,
            capture_output=True,
        )

        new_key = spin.utils.spinfile.gen_ssh_keys(None, tmpdir / "my-key")()
        assert new_key.pubkey == content_mock().strip()
        assert new_key.login is None
        assert new_key.identity_file is not None
        subp_mock.run.assert_called_with(
            [
                "ssh-keygen",
                "-t",
                "rsa",
                "-b",
                "4096",
                "-C",
                "",
                "-q",
                "-N",
                "",
                "-f",
                str(tmpdir / "my-key"),
            ],
            check=True,
            capture_output=True,
        )

        user = Mock()
        new_key = spin.utils.spinfile.gen_ssh_keys(user, tmpdir / "my-key")()
        assert new_key.pubkey == content_mock().strip()
        assert new_key.login == user
        assert new_key.identity_file is not None
        subp_mock.run.assert_called_with(
            [
                "ssh-keygen",
                "-t",
                "rsa",
                "-b",
                "4096",
                "-C",
                "",
                "-q",
                "-N",
                "",
                "-f",
                str(tmpdir / "my-key"),
            ],
            check=True,
            capture_output=True,
        )


class TestPasswdParser:
    """Test the *basic* passwd in the library"""

    @pytest.mark.parametrize("sample", ["tests/data/passwd-ubuntu-focal"])
    def test_real(self, sample: str) -> None:
        with open(sample, encoding="utf8") as passwd_content:
            ret = spin.utils.fileparse.passwd(passwd_content.readlines())
        assert ret is not None
        assert len(ret) > 0


class TestMachineFileLoad:
    """Test `spin.utils.load.Machinefile`"""

    @patch("spin.utils.load.deserialize_machine", autospec=True)
    def test_empty(
        self, deserialize_machine_mock: MagicMock, tmp_path: pathlib.Path
    ) -> None:
        deserialize_machine_mock.reset_mock()
        empty = tmp_path / "empty.json"
        empty.write_text("[]")
        assert spin.utils.load.Machinefile(empty).load() == []

        deserialize_machine_mock.reset_mock()
        single = tmp_path / "single.json"
        single.write_text('[ {"name": "single-serialized-machine"} ]')
        assert spin.utils.load.Machinefile(single).load() == [
            deserialize_machine_mock.return_value
        ]
        deserialize_machine_mock.assert_called_once_with(
            {"name": "single-serialized-machine"}
        )

        deserialize_machine_mock.reset_mock()
        double = tmp_path / "double.json"
        double.write_text('[ {"name": "first-machine"}, {"name": "second-machine"} ]')
        assert spin.utils.load.Machinefile(double).load() == [
            deserialize_machine_mock.return_value,
            deserialize_machine_mock.return_value,
        ]
        deserialize_machine_mock.assert_has_calls(
            [call({"name": "first-machine"}), call({"name": "second-machine"})]
        )
