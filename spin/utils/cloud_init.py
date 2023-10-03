"""Cloud init seed generation"""

from __future__ import annotations

import pathlib
import secrets
import shutil
import subprocess
import tempfile
from typing import Any

import yaml

from spin.machine import credentials
from spin.utils import ui


def get_user(cloud_init: dict, name: str) -> None | dict:
    """Find the user in the given cloud-init structure"""
    for user in cloud_init["users"]:
        if user == "default":
            continue
        if name == user.get("name", None):
            return user
    return None


def generate_metadata(instance_id: str, hostname: str) -> dict:
    """Generate a cloud-init metadata structure.

    The function takes the values of a guest, and generates the corresponding
    metadata YAML structure --in the form of a :py:class:`dict`--.

    Args:
        instance_id: Instance ID (see https://cloudinit.readthedocs.io/en/22.4.2/topics/instancedata.html#v1-instance-id)
        hostname: Hostname for the guest (see https://cloudinit.readthedocs.io/en/22.4.2/topics/instancedata.html#v1-local-hostname)

    Returns:
        A :py:class:`dict`, when passed to a JSON o YAML library, generates
        a valid cloud-init meta-data file.
    """
    return {"instance-id": instance_id, "local-hostname": hostname}


def save_in_dir(
    userdata: dict | pathlib.Path, metadata: dict | pathlib.Path
) -> pathlib.Path:
    """Copy all the contents into a single folder.

    Move all the necessary files into a single folder, to generate the
    ISO image later.

    Args:
        userdata: The path to a *user-data* file, or a :py:class:`dict` compatible
            with said cloud-init structure. If a :py:class:`dict` is given, the
            content is dumped into the corresponding YAML file.
        metadata: The path to a *meta-data* file, or a :py:class:`dict` compatible
            with said cloud-init structure. If a :py:class:`dict` is given, the
            content is dumped into the corresponding YAML file.

    Returns:
        The directory containing the seed for cloud-init.
    """
    # FIXME: We are creating a random folder in /tmp; it's quite dirty.
    # At least create a /tmp/spin-tmp/ subdir.
    tmpdir = pathlib.Path(tempfile.gettempdir()) / secrets.token_hex(4)
    tmpdir.mkdir()
    if isinstance(userdata, dict):
        with open(tmpdir / "user-data", "w", encoding="utf8") as userdata_io:
            userdata_io.write("#cloud-config\n")
            yaml.dump(userdata, userdata_io, indent=4)
    else:
        shutil.copy(userdata, tmpdir / "user-data")
    if isinstance(metadata, dict):
        with open(tmpdir / "meta-data", "w", encoding="utf8") as metadata_io:
            yaml.dump(metadata, metadata_io, indent=4)
    else:
        shutil.copy(metadata, tmpdir / "meta-data")
    return tmpdir


def extract_credentials(
    userdata: dict[str, Any], ssh: list[credentials.SSHCredential]
) -> None:
    """Add the SSH credentials in the given cloud-init into the
    Machine object"""

    def try_add(
        login: str | None, key: str, comment: str = "Extracted from cloud-init data"
    ) -> None:
        if len([*filter(lambda c: c.pubkey == key and c.login == login, ssh)]) > 0:
            return
        ssh.append(credentials.SSHCredential(pubkey=key, login=login, comment=comment))

    for key in userdata.get("ssh_authorized_keys", []):
        try_add(None, key)
    for entry in userdata.get("users", []):
        if entry == "default":
            continue
        for key in entry.get("ssh_authorized_keys", []):
            name = entry.get("name", None)
            try_add(name, key)


def make_iso(folder: pathlib.Path, output: pathlib.Path, *, label="cidata") -> None:
    """Store the contents of *folder* into an ISO.

    Args:
        folder: The folder containing the files to put in the ISO image.
        output: The destination of the ISO image.
        label: The ISO image label. The guest uses this to find valid cloud-init
            seeds.

    Raises:
        If the iso generation command fails
    """
    files = [str(f.absolute()) for f in folder.glob("*")]
    genisocmd = [
        "genisoimage",
        "-output",
        str(output.absolute()),
        "-volid",
        label,
        "-joliet",
        "-rock",
        *files,
    ]

    ret = subprocess.run(genisocmd, check=True, capture_output=True)
    ret.check_returncode()
    ui.instance().debug(f'genisoimage: {ret.stdout.decode("utf8")}')
    ui.instance().debug(f'genisoimage: {ret.stderr.decode("utf8")}')
