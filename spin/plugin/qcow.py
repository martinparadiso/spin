"""qcow2 disk support
"""

import spin.machine.hardware
import spin.plugin.api


@spin.plugin.api.register.disk_creator(fmt={"qcow", "qcow2"})
def create(disk: spin.machine.hardware.Disk) -> None:
    """Create a qcow2 disk

    Args:
        disk: The disk to create.

    Raises:
        ValueError: If the disk misses information.
        ValueError: If the path in the filesystem is already in use.
        Exception: If the disk creation fails.
    """
    if disk.size is None:
        raise ValueError("Missing disk size.")
    if disk.location is None:
        raise ValueError("Missing disk location.")
    if disk.location.exists():
        raise ValueError(f"Path {disk.location.absolute()} in use.")
    if disk.format is None:
        raise ValueError(f"Missing disk format")

    import subprocess

    cmd = ["qemu-img", "create", "-f", "qcow2"]
    if disk.backing_image is not None:
        if disk.backing_image.file is None:
            raise ValueError("Image has no local file")
        cmd.extend(
            [
                "-b",
                str(disk.backing_image.file.absolute()),
                "-F",
                disk.format,
            ]
        )
    cmd.extend([str(disk.location.absolute()), str(disk.size.bytes)])

    sp = subprocess.run(cmd, capture_output=True)
    if sp.returncode != 0:
        emsg = "".join(
            [
                "Disk creation failed.\n",
                f"With command: {sp.args}. qemu-img says: \n",
                str(sp.stdout, "utf8"),
                "\n",
                str(sp.stderr, "utf8"),
                "\n",
                f"Return code: {sp.returncode}",
            ]
        )
        raise Exception(emsg)
