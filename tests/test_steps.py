from __future__ import annotations

import dataclasses
import pathlib
from typing import Any
from unittest.mock import MagicMock, Mock, call, patch

import pytest

import spin.errors
import spin.machine.creation_steps
import spin.machine.definition_steps
import spin.machine.processor
import spin.machine.shell_input
import spin.machine.start_steps
import spin.machine.steps
from spin.machine.connection import SSHOutput
from spin.machine.credentials import SSHCredential
from spin.machine.hardware import SharedFolder
from spin.machine.machine import (
    CreatedMachine,
    Machine,
    MachineUnderCreation,
    MachineWithBackend,
)
from spin.plugin.cloud_init import GenerateCloudInit
from spin.utils.constants import OS
from spin.utils.load import Machinefile


class TestDefinitionSteps:
    """Unit-test the definition steps"""

    @pytest.mark.parametrize("has_image", [True, False])
    @pytest.mark.parametrize("disk_has_backing", [True, False])
    def test_image_backing_overlad(
        self, has_image: bool, disk_has_backing: bool
    ) -> None:
        machine_mock = Mock(spec=Machine())
        if not has_image:
            machine_mock.image = None
        if not disk_has_backing:
            machine_mock.hardware.disk.backing_image = None
        val = spin.machine.definition_steps.ValidateImageAndDisk(machine_mock, [])

        if has_image and disk_has_backing:
            with pytest.raises(ValueError):
                val.process()
        else:
            val.process()


class TestManualInstall:
    """Test the manual install step"""

    @pytest.mark.parametrize("has_image", [True, False])
    @pytest.mark.parametrize("requires_install", [True, False])
    def test_accept(self, has_image: bool, requires_install: bool) -> None:
        machine_mock = Mock(Machine())
        machine_mock.image = (
            Mock(**{"props.requires_install": requires_install}) if has_image else None
        )

        accept = spin.machine.creation_steps.ManualInstallStep.confidence(
            Mock(machine=machine_mock)
        )

        if has_image:
            assert isinstance(accept, int)
        else:
            assert accept is False


@pytest.mark.slow
class TestFSTAB:
    """Unit-test the creation steps"""

    @pytest.mark.parametrize("tag_hint_support", [True, False])
    @pytest.mark.parametrize("has_disk_file", [True, False])
    @pytest.mark.parametrize("is_DOS", [True, False])
    def test_accept(
        self,
        tag_hint_support: bool,
        has_disk_file: bool,
        is_DOS: bool,
    ) -> None:
        cls = spin.machine.creation_steps.EditFstab
        mock = Mock(MachineWithBackend())

        mock.backend.shared_folder = "tag-hint" if tag_hint_support else None
        if has_disk_file:
            mock.hardware.disk.location = "/tmp/some-path"
        else:
            mock.hardware.disk = None
        if is_DOS:
            mock.image.os.family = "windows"
        expect_accept = all((tag_hint_support, has_disk_file, not is_DOS))
        if expect_accept:
            assert isinstance(cls.confidence(Mock(machine=mock)), int)
        else:
            assert cls.confidence(Mock(machine=mock)) is False

    @pytest.mark.parametrize("ro", [True, False])
    @pytest.mark.parametrize("extra", [None, "auto,user"])
    def test_make_entry(self, ro: bool, extra: None | str) -> None:
        """Test the entry generation"""
        backend_opts = "backend-opts=yes"
        expect_opts = ["ro" if ro else "rw", backend_opts]
        if extra is not None:
            expect_opts.append(extra)
        expect = f"/tag-hint/\t/tag-hint/\tfs-type\t{','.join(expect_opts)}\t0\t0"

        with patch("spin.machine.creation_steps.conf", autospec=True) as cfg:
            machine = Mock(Machine())
            machine.backend.automount_fstab_opts = [backend_opts]
            machine.backend.shared_folder_fs = "fs-type"
            folder = Mock()
            folder.guest_path = "/tag-hint/"
            folder.read_only = ro
            cfg.settings.shared_folder.extra_fstab_o = extra
            step = spin.machine.creation_steps.EditFstab(machine)
            assert expect == step.make_entry(machine, folder)

    @patch("spin.machine.creation_steps.can_write", autospec=True)
    @patch("spin.machine.creation_steps.open_image", autospec=True)
    def test_fstab_edit(self, open_image: Mock, can_write_mock: Mock) -> None:
        """Test editing a real FSTAB"""
        FINAL_FSTAB = [
            "LABEL=cloudimg-rootfs   /        ext4   discard,errors=remount-ro       0 1",
            "LABEL=UEFI      /boot/efi       vfat    umask=0077      0 1",
            "### SPIN MOUNTS BEGIN ###",
            "fstab-entry-a",
            "fstab-entry-b",
            "fstab-entry-c",
            "### SPIN MOUNTS END ###",
        ]

        can_write_mock.return_value = True
        open_image.return_value.__enter__.return_value.read_lines.return_value = (
            FINAL_FSTAB[:3]
        )
        machine = Mock(
            Machine(),
            shared_folders=[
                Mock(guest_path="a"),
                Mock(guest_path="b"),
                Mock(guest_path="c"),
            ],
        )
        machine.image.os.subfamily = "linux"
        make_entry = Mock(side_effect=lambda _, mock: "fstab-entry-" + mock.guest_path)

        edit = spin.machine.creation_steps.EditFstab(machine)
        edit.make_entry = make_entry

        edit.solve(Mock())

        open_image.assert_called_once_with(
            machine.hardware.disk.location, read_only=False
        )
        open_image.return_value.__enter__.return_value.read_lines.assert_called_once()
        open_image.return_value.__enter__.return_value.write.assert_called_with(
            "/etc/fstab", "".join(f"{l}\n" for l in FINAL_FSTAB)
        )
        can_write_mock.assert_called_once_with(machine.hardware.disk.location)


class TestKeyAdder:
    """Test the insertion of SSH keys step."""

    @pytest.mark.parametrize(
        "os",
        [
            (True, OS.Identification("posix", "linux")),
            (False, OS.Identification()),
            (False, OS.Identification("posix")),
            (False, OS.Identification("posix", "freebsd")),  # type: ignore
            (False, OS.Identification("windows", "windows")),
        ],
    )
    def test_accept(self, os: tuple[bool, OS.Identification]) -> None:
        machine = Mock(Machine())
        machine.image.os = os[1]
        machine.cloud_init = None
        under_test = spin.machine.creation_steps.AddSSHKey.confidence
        if os[0] is True:
            assert not under_test(Mock(machine=machine)) is False
        else:
            assert under_test(Mock(machine=machine)) is False

    @patch("spin.machine.creation_steps.open_image")
    @patch("spin.machine.creation_steps.ui")
    @patch("spin.utils.info.os")
    def test_simple(self, os_mock: Mock, ui_mock: Mock, open_image_patch: Mock) -> None:
        machine = Mock(Machine())
        tasks = [
            Mock(
                credential=Mock(spec_set=SSHCredential(Mock()), login=None),
                machine=machine,
            ),
            Mock(
                credential=Mock(spec_set=SSHCredential(Mock()), login="another_user"),
                machine=machine,
            ),
            Mock(
                credential=Mock(spec_set=SSHCredential(Mock()), login="user"),
                machine=machine,
            ),
        ]
        disk_mock = open_image_patch.return_value.__enter__.return_value
        read_file = disk_mock.read_file
        write: Mock = disk_mock.write
        read_file.return_value = "\n".join(
            [
                "root:x:0:0::/root:/bin/bash",
                "user:x:1000:1000::/home/user:/bin/bash",
                "another_user:x:1001:1001::/home/another_user:/bin/bash",
            ]
        )
        obj = spin.machine.creation_steps.AddSSHKey(machine)
        for task in tasks:
            obj.solve(task)

        os_mock.access.assert_called_with(machine.hardware.disk.location, os_mock.W_OK)

        open_image_patch.assert_called_with(
            machine.hardware.disk.location, read_only=False
        )

        user_auth_keys = "/home/user/.ssh/authorized_keys"
        auser_auth_keys = "/home/another_user/.ssh/authorized_keys"
        read_file.assert_called_with("/etc/passwd", encoding="utf8")
        write.assert_has_calls(
            [
                call(user_auth_keys, tasks[0].credential.pubkey, append=True),
                call(auser_auth_keys, tasks[1].credential.pubkey, append=True),
                call(user_auth_keys, tasks[2].credential.pubkey, append=True),
            ]
        )
        disk_mock.chown.assert_has_calls(
            [
                call(user_auth_keys, 1000, 1000),
                call(auser_auth_keys, 1001, 1001),
                call(user_auth_keys, 1000, 1000),
            ],
        )
        disk_mock.chmod.assert_has_calls(
            [
                call(user_auth_keys, 0o644),
                call(auser_auth_keys, 0o644),
                call(user_auth_keys, 0o644),
            ]
        )


class TestPluginCloudInit:
    """Test automatic cloud-init generation"""

    def test_accepts(self) -> None:
        """Accept if the machine does not a have a cloud-init *file*"""

        accept_values: list[Any] = [None, {}, {"arbitrary": {"dict": 3}}]

        for accept in accept_values:
            machine = Mock(
                Machine(),
                cloud_init=accept,
                plugins=[Mock(__name__="spin.plugin.cloud_init")],
            )
            assert GenerateCloudInit.accepts(machine)

    @pytest.mark.parametrize("existing_cloud_init", [{}, None])
    def test_process(self, existing_cloud_init: dict | None) -> None:
        """Test the generation of cloud-init."""
        if existing_cloud_init is not None:
            existing: Mock | None = MagicMock(existing_cloud_init)
        else:
            existing = existing_cloud_init
        machine = MagicMock(Machine(), cloud_init=existing)

        ci = GenerateCloudInit(machine, [])
        ci.process()

        if existing is not None:
            existing.update.assert_called_once()


class TestKeyGeneration:
    """Test the generation of temp. keys"""

    def test_acceptance(self) -> None:
        machine = Mock(Machine())
        assert spin.machine.definition_steps.GenerateInsecureKeys.accepts(machine)

    @patch("spin.machine.definition_steps.gen_ssh_keys", autospec=True)
    @pytest.mark.parametrize("logins", [[], ["user"], ["user", "user2"]])
    def test_process(self, gensshkeys_mock: Mock, logins: list[str]) -> None:
        EXPECTED_LOGIN = logins[0] if len(logins) > 0 else None
        machine = MagicMock(Machine())
        machine.image.props.usernames = logins
        step = spin.machine.definition_steps.GenerateInsecureKeys(machine, [])
        step.process()
        gensshkeys_mock.assert_called_once_with(
            login=EXPECTED_LOGIN, comment=f"insecure-key-for-{machine.uuid}"
        )


class TestBoot:
    """Test boot start step"""

    def test_accepts(self) -> None:
        machine = Mock(CreatedMachine)
        assert spin.machine.start_steps.Boot.accepts(machine)

    def test_boot(self) -> None:
        machine = MagicMock(Machine())
        machine.backend.start.return_value = True
        pre_boot = machine.info.boots
        spin.machine.start_steps.Boot(machine).process()
        pre_boot.assert_has_calls([call.__iadd__(1)])

        # Something fails
        with pytest.raises(spin.errors.BackendError) as exce_info:
            machine.backend.start.return_value = False
            spin.machine.start_steps.Boot(machine).process()
        assert exce_info is not None


class TestSharedFolders:
    """Test creation and rollback of shared folders"""

    @patch("spin.machine.creation_steps.pathlib", autospec=True)
    @pytest.mark.slow
    def test_rollback(self, pathlib_mock: Mock) -> None:
        def return_same(mock):
            assert isinstance(mock, Mock)
            return mock

        pathlib_mock.Path.side_effect = return_same
        machine = Mock(MachineUnderCreation)
        machine.shared_folders = [
            Mock(
                SharedFolder,
                host_path=MagicMock(
                    pathlib.Path,
                    **{"is_file.return_value": False, "exists.return_value": False},
                ),
                guest_path=MagicMock(pathlib.Path),
                read_only=MagicMock(bool()),
            )
            for _ in range(5)
        ]
        step = spin.machine.creation_steps.SharedFolders(machine)
        step.solve(Mock())

        for folder in machine.shared_folders:
            folder.host_path.is_file.assert_called()

        assert len(step.rollback_dirs) == 5
        for rollback, og_mock in zip(step.rollbacks, machine.shared_folders):
            og_mock.host_path.rmdir.assert_not_called()
            rollback()
            og_mock.host_path.rmdir.assert_called_once()


class TestOnCreation:
    """Test commands run on creation"""

    def test_acceptance(self) -> None:
        machine = MagicMock(Machine())
        machine.on_creation.__len__.return_value = 3
        machine.info.boots = 0
        assert spin.machine.start_steps.OnCreation.accepts(machine) is True
        machine.on_creation.__len__.return_value = 3
        machine.info.boots = 1
        assert spin.machine.start_steps.OnCreation.accepts(machine) is False

    @patch("spin.machine.start_steps.as_machine")
    @patch("spin.machine.start_steps.ssh")
    @patch("spin.machine.start_steps.open")
    def test_mocked_process(
        self,
        open_mock: Mock,
        ssh_mock: Mock,
        as_machine_mock: Mock,
    ) -> None:
        """Test the command invocation"""
        machine = MagicMock(Machine())
        machine.folder = MagicMock(pathlib.Path())

        machine.on_creation.__len__.return_value = 3
        machine.on_creation.commands = [
            Mock(spin.machine.shell_input.Script(""), ignore_errors=True)
            for _ in range(3)
        ]
        ssh_mock.return_value = Mock(SSHOutput, returncode=0)

        under_testing = spin.machine.start_steps.OnCreation(machine)
        under_testing.process()

        assert all(
            call_ in open_mock.call_args_list
            for call_ in [
                call(
                    as_machine_mock.return_value.folder
                    / machine.uuid
                    / ("on_creation_" + str(i) + ".sh"),
                    "r",
                    encoding="utf8",
                )
                for i in range(3)
            ]
        )

        assert ssh_mock.call_count == 3
        ssh_mock.assert_has_calls(as_machine_mock(machine), open_mock.__enter__)


class TestCloudInitKeyExtraction:
    def test_acceptance(self) -> None:
        machine = Mock()
        machine.cloud_init = None

        under_test = spin.machine.creation_steps.ExtractCloudInitCreds.confidence
        assert under_test(Mock(machine=machine)) is False

        machine.cloud_init = ""
        assert isinstance(under_test(Mock(machine=machine)), int)
        machine.cloud_init = pathlib.Path
        assert isinstance(under_test(Mock(machine=machine)), int)

    def test_empty_extraction(self) -> None:
        machine = Mock(ssh=[])
        machine.cloud_init = {}
        under_test = spin.machine.creation_steps.ExtractCloudInitCreds(machine).solve
        under_test(Mock())
        assert not machine.ssh

    def test_extraction(self) -> None:
        machine = Mock(spec=["ssh", "cloud_init"])
        machine.ssh = []
        machine.cloud_init = {"ssh_authorized_keys": ["not-a-real-key"]}
        under_test = spin.machine.creation_steps.ExtractCloudInitCreds(machine).solve
        under_test(Mock())
        assert len(machine.ssh) == 1

        # Make sure the same key is not added again
        under_test(Mock())
        assert len(machine.ssh) == 1

        # Add a login-less entry
        machine.cloud_init["users"] = [
            "default",
            {"ssh_authorized_keys": ["not-a-real-key"]},
        ]
        under_test(Mock())
        assert len(machine.ssh) == 1

        # Add a login-ful entry
        machine.cloud_init["users"] = [
            {
                "name": "some-user",
                "ssh_authorized_keys": ["not-a-real-key"],
            }
        ]
        under_test(Mock())
        assert len(machine.ssh) == 2

    def test_file_extraction(self, tmp_path: pathlib.Path) -> None:
        machine = Mock(ssh=[])
        machine.cloud_init = tmp_path / "cloud.yaml"
        machine.cloud_init.write_text("", encoding="utf8")
        under_test = spin.machine.creation_steps.ExtractCloudInitCreds(machine).solve
        under_test(Mock())
        assert not machine.ssh

        machine.cloud_init = tmp_path / "cloud.yaml"
        machine.cloud_init.write_text(
            "{'ssh_authorized_keys': ['fake-key']}", encoding="utf8"
        )
        under_test = spin.machine.creation_steps.ExtractCloudInitCreds(machine).solve
        under_test(Mock())
        assert len(machine.ssh) == 1
        assert machine.ssh[0].pubkey == "fake-key"
        assert machine.ssh[0].login == None


class TestOnBoot:
    def test_acceptance(self) -> None:
        machine = MagicMock(Machine())
        machine.on_boot.__len__.return_value = 3
        machine.on_boot.commands.__len__.return_value = 3
        machine.info.boots = 0
        assert spin.machine.start_steps.OnBoot.accepts(machine) is True
        machine.on_boot.__len__.return_value = 3
        machine.info.boots = 1
        assert spin.machine.start_steps.OnBoot.accepts(machine) is True

    @patch("spin.machine.start_steps.as_machine")
    @patch("spin.machine.start_steps.ssh")
    @patch("spin.machine.start_steps.open")
    def test_mocked_process(
        self,
        open_mock: Mock,
        ssh_mock: Mock,
        as_machine_mock: Mock,
    ) -> None:
        """Test the command invocation"""
        machine = MagicMock(Machine())
        machine.folder = MagicMock(pathlib.Path())

        machine.on_boot.__len__.return_value = 3
        machine.on_boot.commands = [
            Mock(spin.machine.shell_input.Script(""), ignore_errors=True)
            for _ in range(3)
        ]
        ssh_mock.return_value = Mock(returncode=0)

        under_testing = spin.machine.start_steps.OnBoot(machine)
        under_testing.process()

        assert open_mock.call_count == 3
        assert all(
            call_ in open_mock.call_args_list
            for call_ in [
                call(
                    as_machine_mock.return_value.folder
                    / machine.uuid
                    / ("on_boot_" + str(i) + ".sh"),
                    "r",
                    encoding="utf8",
                )
                for i in range(3)
            ]
        )

        assert ssh_mock.call_count == 3
        ssh_mock.assert_has_calls(as_machine_mock(machine), open_mock.__enter__)


def test_simple_task() -> None:
    """Type check simple/basic Task and TaskSolver definition"""

    new_machine_name = Mock()

    @dataclasses.dataclass
    class TestTask(spin.machine.steps.CreationTask):
        """Simple dataclass to test typing"""

        a: int
        b: str
        machine: MachineUnderCreation

    class Other:
        ...

    def accept_other(o: Other):
        ...

    class Solver(spin.machine.steps.CreationStep, Other):
        @classmethod
        def accepts(cls, machine) -> bool:
            return True

        @classmethod
        def confidence(cls, task) -> int:
            return 0

        def solve(self, task: TestTask):
            task.a = 3
            task.machine.name = new_machine_name

    machine = MagicMock()
    solver = Solver(machine)
    accept_other(solver)
    test_task = TestTask(0, "", machine)

    assert test_task.machine.name is machine.name
    solver.solve(test_task)
    assert test_task.machine.name is new_machine_name
    assert test_task.a == 3
