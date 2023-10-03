"""Command Line Interface main file"""

from __future__ import annotations

import pathlib
from pathlib import Path
from typing import Sequence

from jinja2 import Environment, FileSystemLoader

from spin.utils.sizes import Size


def init(
    folder: Path = Path("."),
    filename: str = "spinfile.py",
    nametag: None | str = None,
    stdout: bool = False,
    *,
    cpus: None | int = None,
    memory: None | Size | str = None,
    cloud_init: None | Path | str = None,
    plugins: None | Sequence[str] = None,
) -> int:
    """Initialize a spinfile in the given folder

    Args:
        folder: The folder to create the spinfile in.
        filename: The filename.
        nametag: The name of the image to use in the form of name:tag
        stdout: If ``True``, output the contents to stdout instead of
            writing to ./spinfile.py
        cpus: Number of vCPUs to assign to guest. Minimum 1.
        memory: Amount of vRAM to assign to guest.
        cloud_init: Path to a cloud_init yaml file, passed to the guest on boot.

    Raises:
        TypeError: if you pass a filename type not supported by pathlib.Path
        ValueError:
            - if the ``folder`` does not exists,
            - if there is already a ``spinfile`` in said folder.
    """
    folder_ = folder
    if not isinstance(folder_, Path):
        folder_ = Path(folder_)

    if not folder_.exists():
        raise ValueError(f"Folder {folder_} does not exist")

    if folder_.exists() and not folder_.is_dir():
        raise ValueError(f"{folder_} is not a folder")

    filepath = folder_ / filename

    if nametag is not None:
        if len(nametag.split(":")) > 2:
            raise ValueError("Invalid image format: must be name:tag")

        image = nametag.split(":")[0]
        tag = nametag.split(":")[1] if len(nametag.split(":")) > 1 else None
    else:
        image = None
        tag = None

    if filepath.exists():
        raise ValueError(f"There is already a file in {filepath}")

    if isinstance(cloud_init, str):
        cloud_init = pathlib.Path(cloud_init)

    env = Environment(
        loader=FileSystemLoader(pathlib.Path(__file__).parent), trim_blocks=True
    )
    content = env.get_template("spinfile.jinja").render(
        image=image,
        tag=tag,
        cloud_init=cloud_init,
        cpus=cpus,
        memory=memory,
        plugins=plugins,
    )

    if not stdout:
        with open(filepath, "w", encoding="utf8") as spinfile:
            spinfile.write(content)
    else:
        print(content)

    return 0
