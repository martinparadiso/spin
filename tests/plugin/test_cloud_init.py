"""Test the cloud_init plugin"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, NonCallableMock, PropertyMock, patch

import jsonschema
import pytest

import spin.plugin.cloud_init
from spin.machine.credentials import SSHCredential
from spin.machine.machine import Machine

JSON_SCHEMA = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "$id": "https://raw.githubusercontent.com/canonical/cloud-init/main/cloudinit/config/schemas/versions.schema.cloud-config.json",
    "oneOf": [
        {
            "allOf": [
                {"properties": {"version": {"enum": ["v1"]}}},
                {
                    "$ref": "https://raw.githubusercontent.com/canonical/cloud-init/main/cloudinit/config/schemas/schema-cloud-config-v1.json"
                },
            ]
        }
    ],
}


class TestCloudInitGeneration:
    """Test the basic cloud init generation"""

    def test_acceptance(self) -> None:
        machine = MagicMock(Machine())
        machine.plugins = []

        assert spin.plugin.cloud_init.GenerateCloudInit.accepts(machine) is False
        assert spin.plugin.cloud_init.AddSSHKey.accepts(machine) is False
        assert spin.plugin.cloud_init.AddMountFolders.accepts(machine) is False

        machine.plugins = [spin.plugin.cloud_init]
        assert spin.plugin.cloud_init.AddMountFolders.accepts(machine) is False
        machine.shared_folders.__len__.return_value = 1
        assert spin.plugin.cloud_init.GenerateCloudInit.accepts(machine) is True
        assert spin.plugin.cloud_init.AddSSHKey.accepts(machine) is True
        assert spin.plugin.cloud_init.AddMountFolders.accepts(machine) is True

    @patch("spin.utils.info.host_user", new=lambda: "non_existing_user_for_test")
    @pytest.mark.slow
    def test_core(self) -> None:
        """Validate the core structure"""
        machine = MagicMock(Machine())
        machine.cloud_init = None
        machine.plugins = [spin.plugin.cloud_init]
        assert spin.plugin.cloud_init.GenerateCloudInit.accepts(machine) is True

        under_testing = spin.plugin.cloud_init.GenerateCloudInit(machine, [])
        under_testing.process()
        assert isinstance(machine.cloud_init, dict)
        assert "users" in machine.cloud_init
        assert machine.cloud_init["users"][0]["name"] == "non_existing_user_for_test"
        jsonschema.validate(machine.cloud_init, JSON_SCHEMA)

    @patch("spin.plugin.cloud_init.fingerprint", autospec=True)
    @pytest.mark.parametrize(
        "input_cred",
        [
            NonCallableMock(
                spec=["login", "pubkey"],
                login=None,
                pubkey="some-key",
            ),
            NonCallableMock(
                spec=["login", "pubkey"],
                login="ubuntu",
                pubkey="some-key",
            ),
        ],
    )
    @pytest.mark.slow
    def test_add_sshkey(self, _, input_cred: NonCallableMock) -> None:
        """Test addition of SSH keys"""

        GLOBAL_KEYS = 1 if input_cred.login is None else 0

        machine = Mock(Machine())
        machine.cloud_init = {"users": [{"name": "ubuntu"}]}
        machine.ssh = [input_cred]
        machine.plugins = [spin.plugin.cloud_init]

        under_testing = spin.plugin.cloud_init.AddSSHKey(machine, [])
        under_testing.process()

        jsonschema.validate(machine.cloud_init, JSON_SCHEMA)
        if GLOBAL_KEYS == 0:
            assert "ssh_authorized_keys" not in machine.cloud_init
            user_keys = machine.cloud_init["users"][0]["ssh_authorized_keys"]
            assert len(user_keys) == 1
            assert user_keys[0] == "some-key"
        else:
            assert len(machine.cloud_init["ssh_authorized_keys"]) == GLOBAL_KEYS
        assert len(machine.cloud_init["users"]) == 1
        assert len(machine.ssh) == 1

    @patch("spin.utils.config.conf.settings", autospec=True)
    @pytest.mark.slow
    def test_add_mounts(self, setting_mock: Mock) -> None:
        """Test addition of FSTAB entries"""

        machine = Mock()
        machine.cloud_init = {}
        machine.backend.shared_folder_fs = "SharedFolderFilesystem"
        machine.backend.automount_fstab_opts = []
        machine.shared_folders = [Mock(guest_path="/var/guest/path", read_only=False)]
        setting_mock.shared_folder.extra_fstab_o = None

        under_testing = spin.plugin.cloud_init.AddMountFolders(machine, [])
        under_testing.process()

        jsonschema.validate(machine.cloud_init, JSON_SCHEMA)

        assert len(machine.cloud_init["mounts"]) == 1
