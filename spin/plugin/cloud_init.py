"""Automatic generation of cloud-init information"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

import spin.plugin.api.register
import spin.utils.info
from spin.machine.definition_steps import GenerateKeys
from spin.machine.machine import Machine
from spin.machine.steps import DefinitionStep
from spin.utils import ui
from spin.utils.config import conf
from spin.utils.crypto import fingerprint


@spin.plugin.api.register.definition_step(requires=GenerateKeys)
class GenerateCloudInit(DefinitionStep):
    """Core step of the plugin to auto generate a cloud-init dict"""

    name = "Auto cloud-init"
    description = "Generating default cloud-init information"

    @classmethod
    def accepts(cls, machine: Machine) -> bool:
        return True

    def process(self) -> None:
        if isinstance(self.machine.cloud_init, (str, pathlib.Path)):
            with open(self.machine.cloud_init, encoding="utf8") as f:
                ci_file: dict = yaml.load(f, yaml.SafeLoader)
                self.machine.cloud_init = ci_file
        elif self.machine.cloud_init is not None:
            ui.instance().notice("Existing cloud-init, combining")
        else:
            self.machine.cloud_init = {}

        ci: dict[str, Any] = {"users": []}

        host_usr = spin.utils.info.host_user()

        ci["users"].append(
            {
                "name": host_usr,
                "sudo": "ALL=(ALL) NOPASSWD:ALL",
            }
        )
        compatible_creds = [
            *filter(
                lambda c: not callable(c)
                and c.comment is not None
                and c.comment.startswith("insecure-key-for-"),
                self.machine.ssh,
            )
        ]
        if len(compatible_creds) > 0:
            cred = compatible_creds[0]
            assert not callable(cred)  # For static type-checkers

            if cred.login is not None:
                raise ValueError("Insecure default key already in use")
            cred.login = host_usr
            ci["users"][-1]["ssh_authorized_keys"] = [cred.pubkey]

        # HACK: This 'update' method will probably replace lists instead of
        # appending; we do not want that.
        self.machine.cloud_init.update(ci)


@spin.plugin.api.register.definition_step(requires={GenerateCloudInit, GenerateKeys})
class AddSSHKey(DefinitionStep):
    """Adds new SSH key(s) to cloud-init dict."""

    name = "Add SSH keys to cloud-init"
    description = "Add keys defined outside cloud-init"

    @classmethod
    def accepts(cls, machine: "Machine") -> bool:
        return GenerateCloudInit.accepts(machine)

    def process(self) -> None:
        assert isinstance(self.machine.cloud_init, dict)
        assert "users" in self.machine.cloud_init
        for cred in self.machine.ssh:
            if callable(cred):
                # NOTE: callable is added as a precatuion only; there should be
                # no callables here
                raise ValueError(
                    "Callable SSH should be replaced with actual credential"
                )
            compatible: list[dict] = [
                *filter(
                    lambda entry: entry.get("name", None) == cred.login,  # type: ignore[arg-type]
                    filter(
                        lambda e: isinstance(e, dict), self.machine.cloud_init["users"]
                    ),
                )
            ]
            if len(compatible) == 0:
                ui.instance().warning(
                    "Credential without user/login. Adding as global."
                )
                if "ssh_authorized_keys" not in self.machine.cloud_init:
                    self.machine.cloud_init["ssh_authorized_keys"] = []
                self.machine.cloud_init["ssh_authorized_keys"].append(cred.pubkey)
                continue
            if len(compatible) > 1:
                ui.instance().warning(
                    f"Multiple compatible logins: {', '.join(u['name'] for u in compatible)}"
                )
            for user in compatible:
                if "ssh_authorized_keys" not in user:
                    user["ssh_authorized_keys"] = []
                if cred.pubkey not in user["ssh_authorized_keys"]:
                    ui.instance().notice(f"Adding {fingerprint(cred)}")
                    user["ssh_authorized_keys"].append(cred.pubkey)


@spin.plugin.api.register.definition_step(requires={GenerateCloudInit})
class AddMountFolders(DefinitionStep):
    # FIXME: This is a creation-step
    """Add shared-folders to cloud-init mounts"""

    name = "Auto-mount folders"
    description = "Using clout-init mount functionality"

    @classmethod
    def accepts(cls, machine: Machine) -> bool:
        return GenerateCloudInit.accepts(machine) and len(machine.shared_folders) > 0

    def process(self) -> None:
        assert self.machine.backend is not None
        assert isinstance(self.machine.cloud_init, dict)
        mounts: list[list[str]] = []
        for folder in self.machine.shared_folders:
            tag = str(folder.guest_path)
            mnt_pnt = str(folder.guest_path)
            fs = self.machine.backend.shared_folder_fs
            mount_opts = ["ro" if folder.read_only else "rw"]
            mount_opts.extend(self.machine.backend.automount_fstab_opts)
            if conf.settings.shared_folder.extra_fstab_o is not None:
                mount_opts.append(conf.settings.shared_folder.extra_fstab_o)
            mounts.append([tag, mnt_pnt, fs, ",".join(mount_opts)])
        self.machine.cloud_init["mounts"] = mounts
