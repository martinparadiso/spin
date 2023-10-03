"""Authentication methods for a machine.

Important: The code here has not been audited nor extensively
examined; use only in development environments.
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Optional

from typing_extensions import Protocol, TypedDict

from spin.utils import crypto
from spin.utils.crypto import fingerprint


class RawLogin(Protocol):
    user: str
    password: Optional[str]

    def dict(self):
        """Serialize the object into a JSON friendly dictionary.

        Returns:
            A (typed) dict containing a dictionary capable of being
            serialized by the ``json`` module. And which can be expanded
            in the class constructor.
        """
        ...


class RawUser(RawLogin):
    """Raw user and password combination"""

    class Serialized(TypedDict):
        user: str
        password: Optional[str]

    def __init__(self, user: str, password: None | str) -> None:
        self.user = user
        self.password = password

    def dict(self) -> Serialized:
        return {"user": self.user, "password": self.password}


class PasswordFile(RawLogin):
    """Load the password at the last minute from a file"""

    class Serialized(TypedDict):
        user: str
        file: str

    def __init__(
        self, user: str, file: str | pathlib.Path, *, writable: bool = False
    ) -> None:
        """
        Args:
            user: The user to login as.
            file: File containing only the password in plain text.
            writable: If set to ``True``, the password file can be
                overwritten on assignment.
        """
        self.user = user
        self.file = pathlib.Path(file) if isinstance(file, str) else file
        self.writable = writable

    @property
    def password(self) -> Optional[str]:
        """Read the password from a file"""
        with open(self.file, encoding="utf8") as pass_file:
            return pass_file.read()

    @password.setter
    def password(self, new_password: str) -> None:
        if not self.writable:
            raise Exception("Password is not writable")
        with open(self.file, encoding="utf8") as pass_file:
            pass_file.write(new_password)

    def dict(self) -> Serialized:
        return {"user": self.user, "file": str(self.file.absolute())}


@dataclasses.dataclass
class SSHCredential:
    """SSH information to log into a machine."""

    login: Optional[str] = None
    """Username to login as"""

    identity_file: Optional[pathlib.Path] = None
    """Location of the identity file for pubkey."""

    comment: Optional[str] = None
    """Comment to identify the nature of the key."""

    def __init__(
        self,
        pubkey: str,
        login: None | str = None,
        identity_file: None | pathlib.Path | str = None,
        comment: None | str = None,
    ) -> None:
        self.pubkey = pubkey
        self.login = login
        self.identity_file = None
        self.comment = comment

        if identity_file is not None:
            self.identity_file = pathlib.Path(identity_file)

    def __repr__(self) -> str:
        if self.login is None:
            login = ""
        else:
            login = f"login={self.login}, "
        return f"SSH({login}pubkey={fingerprint(self)}, comment={self.comment})"

    @property
    def pubkey(self) -> str:
        """Public key --of the private-key pair-- stored in the machine."""
        return self._pubkey

    @pubkey.setter
    def pubkey(self, val: str) -> None:
        self._pubkey = crypto.normalize(val)

    class Serialized(TypedDict):
        pubkey: str
        login: Optional[str]
        identity_file: Optional[str]
        comment: Optional[str]

    def dict(self) -> Serialized:
        return {
            "pubkey": self.pubkey,
            "login": self.login,
            "identity_file": None
            if self.identity_file is None
            else str(self.identity_file.absolute()),
            "comment": self.comment,
        }
