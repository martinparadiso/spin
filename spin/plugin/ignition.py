"""Support for openSUSE/Fedora Ignition

Ignition is similar to cloud-init, except used mainly
by Fedora and friends.
"""


from __future__ import annotations

import json
import pathlib
import secrets
import subprocess
import tempfile
from typing import Literal

import spin.plugin.api.register
from spin.machine.creation_steps import ExtraStorage, InsertSSHCredential
from spin.machine.definition_steps import GenerateKeys
from spin.machine.hardware import CDROM
from spin.machine.machine import DefinedMachine, Machine, as_machine
from spin.machine.steps import BaseTask, CreationStep, DefinitionStep
from spin.utils import ui
from spin.utils.load import Spinfolder


class IgnitionDatasourceDisk(BaseTask):
    """Generate the ignition datasource for the given machine"""


def _make_iso(config: dict, output: pathlib.Path) -> None:
    """Generate the Ignition directory tree structure.

    Args:
        config: The data to dump into the ignition config file.

    Returns:
        The directory containing the 'root' for the CDROM image.
    """
    # FIXME: We are creating a random folder in /tmp; it's quite dirty.
    # At least create a /tmp/spin-tmp/ subdir.
    tmpdir = pathlib.Path(tempfile.gettempdir()) / ("ignition-" + secrets.token_hex(4))
    tmpdir.mkdir()
    ignition_subdir = tmpdir / "ignition"
    ignition_subdir.mkdir()
    data = json.dumps(config)
    (ignition_subdir / "config.ign").write_text(data, "utf8")
    genisocmd = [
        "mkisofs",
        "-o",
        str(output.absolute()),
        "-V",
        "ignition",
        str(tmpdir.absolute()),
    ]

    ret = subprocess.run(genisocmd, check=False, capture_output=True)
    ui.instance().debug(f'mkisofs: {ret.stdout.decode("utf8")}')
    ui.instance().debug(f'mkisofs: {ret.stderr.decode("utf8")}')


@spin.plugin.api.register.definition_step(requires=GenerateKeys)
class GenerateIgnition(DefinitionStep):
    """Automatically generate Ignition information"""

    name = "Auto Ignition"
    description = "Generating default Ignition information"

    @classmethod
    def accepts(cls, machine: Machine) -> bool:
        return machine.ignition is None

    def process(self):
        assert self.machine.ignition is None
        self.machine.ignition = {
            "ignition": {"version": "3.0.0"},
            "passwd": {
                "users": [
                    {
                        "name": "root",
                    }
                ]
            },
        }

        self.tasks.append(IgnitionDatasourceDisk(self.machine))


@spin.plugin.api.register.solves(IgnitionDatasourceDisk)
@spin.plugin.api.register.creation_step(before=[ExtraStorage])
class GenerateIgnitionDataDisk(CreationStep):
    """Generate the Ignition CDROM"""

    name = "Generating Ignition disk"

    @classmethod
    def accepts(cls, machine: DefinedMachine) -> bool:
        return machine.ignition is not None

    @classmethod
    def confidence(cls, task) -> int:
        return 0

    def solve(self, task) -> None:
        assert self.machine.ignition is not None

        iso_path = Spinfolder(as_machine(self.machine)).add_file(
            as_machine(self.machine), "ignition.img"
        )

        _make_iso(self.machine.ignition, iso_path)

        self.machine.add_disk(CDROM(label="ignition", location=iso_path))


@spin.plugin.api.register.solves(InsertSSHCredential)
@spin.plugin.api.register.creation_step(before=[GenerateIgnitionDataDisk])
class AddSSHKeyToIgnition(CreationStep):
    """Insert the SSH keys in the machine"""

    name = "Inserting SSH keys into Ignition data"

    @classmethod
    def confidence(cls, task: BaseTask | InsertSSHCredential) -> Literal[False] | int:
        if task.machine.ignition is None:
            return False
        return 10

    def solve(self, task: InsertSSHCredential) -> None:
        assert task.machine.ignition is not None
        cred = task.credential

        # TODO: Search the user indicated in the credential and add to
        # that one
        if cred.login is not None:
            raise ValueError("Key already has an username/login -- cannot set")
        cred.login = "root"
        if "sshAuthorizedKeys" not in task.machine.ignition["passwd"]["users"][0]:
            task.machine.ignition["passwd"]["users"][0]["sshAuthorizedKeys"] = []

        task.machine.ignition["passwd"]["users"][0]["sshAuthorizedKeys"].append(
            cred.pubkey
        )
