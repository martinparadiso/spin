"""All the functionality that should be available to the
client when using a `spinfile.py`
"""

from __future__ import annotations

import pathlib
import secrets
import subprocess
from typing import Callable, Optional

import spin.utils.config
from spin.machine.credentials import SSHCredential
from spin.utils import content, ui


def read_key(
    file: str | pathlib.Path, login: Optional[str] = None
) -> Callable[[], SSHCredential]:
    """Read a public key from a file.

    Args:
        file: The file containing the public key.
        login: The login/username to use with this key.

    Returns:
        A function, when called returns a SSHCredential populated
        with the information provided.
    """

    def reader() -> SSHCredential:
        return SSHCredential(content(file), login=login)

    return reader


def gen_ssh_keys(
    login: Optional[str] = None,
    path: Optional[str | pathlib.Path] = None,
    comment: Optional[str] = None,
) -> Callable[[], SSHCredential]:
    """Return a function capable of generating a pair of SSH keys.

    Args:
        login: The username/login to add to the generated credential.
        path: The path to write the keys to (passed as ``-f path`` to
            ``ssh-keygen``). If None, it will be added to the
            :py:attr:`Configuration.keys_folder` folder with a random
            name.
        comment: Comment to add to the SSH credential.
    """

    def generator() -> SSHCredential:
        if path is None:
            filename = secrets.token_hex(16)
            key_path = spin.utils.config.conf.keys_folder / filename
        else:
            key_path = pathlib.Path(path)
        key_path = key_path.absolute()
        try:
            subprocess.run(
                [
                    "ssh-keygen",
                    "-t",
                    "rsa",
                    "-b",
                    "4096",
                    "-C",
                    comment or "",
                    "-q",
                    "-N",
                    "",
                    "-f",
                    str(key_path),
                ],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exce:
            ui.instance().error(
                (
                    "Failed to generate SSH key. \n"
                    f"ssh-keygen stdout: {exce.stdout}\n"
                    f"ssh-keygen stderr: {exce.stderr}"
                )
            )
            raise
        new_credential = SSHCredential(
            content(pathlib.Path(str(key_path) + ".pub"), encoding="utf8"),
            login=login,
            identity_file=key_path,
            comment=comment,
        )
        ui.instance().info(new_credential)

        return new_credential

    return generator
