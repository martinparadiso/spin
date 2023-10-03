"""General utilities for reading of common file formats"""

from __future__ import annotations

from typing import NamedTuple, Sequence


class PasswdEntry(NamedTuple):
    """Python structure for storage of passwd entries"""

    username: str
    password: str
    uid: int
    gid: int
    comment: str
    home: str
    shell: str


def passwd(content: list[str]) -> Sequence[PasswdEntry]:
    """Convert the content of a passwd file into a list of PasswdEntry.

    Args:
        content: The content of a passwd file.

    Return:
        A list of all the entries found in the data provided.
    """
    ret: list[PasswdEntry] = []
    for line in content:
        cols = line.split(":", maxsplit=6)
        ret.append(
            PasswdEntry(
                username=cols[0],
                password=cols[1],
                uid=int(cols[2]),
                gid=int(cols[3]),
                comment=cols[4],
                home=cols[5],
                shell=cols[6],
            )
        )
    return ret
