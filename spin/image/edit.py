"""Image access functionality

The current implementation relies on libguestfs
"""
from __future__ import annotations

import pathlib
from typing import Dict, Optional, Tuple, Union, overload

from typing_extensions import Literal

from spin.errors import TODO
from spin.utils import ui

try:
    import guestfs  # type: ignore
except ImportError:
    pass


class ImageEditor:
    """Open an image file for viewing (and maybe editing) the contents

    Todo:
        * Currently supports single-boot images, i. e. no multi-boot support
    """

    read_only: bool
    """True if the image is mounted as read only, false otherwise"""

    InsepctedData = Dict[
        str, Union[str, Tuple[Union[str, None], Union[str, None]], None]
    ]

    inspected_data: Optional[InsepctedData]
    """Image data, dictionary present only after calling inspect()
    
    Please refer to :py:func:`inspect` for information about the dict contents.
    """

    disks: list[str]
    """List of disk or devices found in the image"""

    partitions: list[str]
    """List of partitions in the image"""

    def __init__(self, file: pathlib.Path, read_only: bool = True):
        """
        Args:
            read_only: Mount the image as read-only. Defaults to True for safety,
                    pass False to edit the image file.
        """
        self.file = str(file)
        self.read_only = read_only
        self.guestfs: None | "guestfs.GuestFS" = None
        self.inspected_data = None

    def open_image(self):
        """Open the image"""
        self.guestfs = guestfs.GuestFS(python_return_dict=True)
        g = self.guestfs
        g.add_drive_opts(self.file, readonly=self.read_only)
        g.launch()

        self.disks = g.list_devices()
        self.partitions = g.list_partitions()

        oses = g.inspect_os()
        if len(oses) > 1:
            ui.instance().notice(f"Found {len(oses)}, using only the first")

        if len(oses) == 0:
            raise Exception(f"No OS found in {self.file}")

        self.root = oses[0]
        self.mountpoints = g.inspect_get_mountpoints(self.root)

        for dev, mp in sorted(self.mountpoints.items(), key=lambda k: len(k[0])):
            try:
                if self.read_only:
                    g.mount_ro(mp, dev)
                else:
                    g.mount(mp, dev)
            except:
                ui.instance().warning(f"Could not mount device {dev} in {mp}")
                pass

    def close_image(self):
        """Stop editing the image.

        Automatically called if using the object as context-manager.
        """
        if self.guestfs is not None:
            self.guestfs.close()
        self.guestfs = None

    def __enter__(self):
        self.open_image()
        return self

    def __exit__(self, *args):
        self.close_image()

    def _handle(self) -> "guestfs.GuestFS":
        """Return the handle, checking if the image is opened"""
        if self.guestfs is None:
            raise Exception("Image not opened")
        return self.guestfs

    def _check_write_permission(self):
        if self.read_only:
            raise Exception(
                "Cannot proceed, image opened as read-only, please re-mount"
            )

    def guestfs_handle(self) -> "guestfs.GuestFS":
        """Return the handle to GuestFS, so you can call any function directly

        Please refer to ``libguestfs(3)`` and ``guestfs-python(3)`` manual pages
        for appropriate documentation. Beware the handle is closed when
        ``close()`` or ``__exit__()``  are called in this object.

        Some basic functions are provided with a 'nicer' interface in this object,
        such as :py:func:`exists()`, :py:func:`is_dir()`, and some more.

        Returns:
            A guetfs handle to access the backend directly

        """
        return self._handle()

    def exists(
        self, path: Union[str, pathlib.PurePath], follow_symlinks: bool = False
    ) -> bool:
        """Check if a given path is present in the mounted image

        Returns:
            True if the path exists, false otherwise
        """
        return self._handle().exists(str(path)) == 1

    def is_dir(self, path: Union[str, pathlib.PurePath]) -> bool:
        """Check if a given path is present and is dir

        Args:
            path: The Path to check, must be absolute, and it refers to the path
                inside the image
            follow_symlinks: If True, follows a symlink (or a chain of
                symlinks), and checks if the end is a directory.
        Returns:
            True if ``path`` is a directory, false otherwise
        """
        return self._handle().is_dir(str(path)) == 1

    def is_file(
        self, path: Union[str, pathlib.PurePath], follow_symlinks: bool = False
    ) -> bool:
        """Check if a given path is present and is a file

        Args:
            path: The Path to check, must be absolute, and it refers to the path
                inside the image
            follow_symlinks: If True, follows a symlink (or a chain of
                symlinks), and checks if the end is a regular file.
        Returns:
            True if ``path`` is a 'regular' file, false otherwise
        """
        return self._handle().is_file(str(path), followsymlinks=follow_symlinks)

    def open(self, path: Union[str, pathlib.PurePath], mode: str = "r"):
        """Open a file located inside the image

        For more primitive and simpler interface you can check:

        * :py:func:`read_file()`,
        * :py:func:`read_lines()`, and
        * :py:func:`write()`.

        Args:
            path: Absolute path to the file to access.
            mode: The open mode, similar to standard open(), but supports only:
                'r'.

        Returns:
            A special object that behaves like a file, but is actually wrapping
            different functions of guestfs, depending on the requested mode.
        """
        raise TODO()

    def mkdir(self, path: Union[str, pathlib.PurePath], parents: bool = False):
        """Make a directory inside the image

        Args:
            path: *Absolute* path to the directory to create.
            parents: analog to ``-p`` of mkdir, make the necessary parents.
        """
        if parents:
            self._handle().mkdir_p(str(path))
        else:
            self._handle().mkdir(str(path))

    @overload
    def read_file(
        self,
        path: Union[str, pathlib.PurePath],
        mode: Literal["r", "rt"],
        encoding: str,
    ) -> str:
        ...

    @overload
    def read_file(
        self, path: Union[str, pathlib.PurePath], mode: Literal["rb"], encoding: str
    ) -> bytes:
        ...

    @overload
    def read_file(
        self,
        path: Union[str, pathlib.PurePath],
        mode: Literal["r", "rt"] = "r",
        encoding: str = "utf8",
    ) -> str:
        ...

    def read_file(
        self,
        path: Union[str, pathlib.PurePath],
        mode: Literal["r", "rt", "rb"] = "r",
        encoding: str = "utf8",
    ):
        """Read a file from the image

        Args:
            path: *Absolute* path to the file inside the image.
            mode: Open mode, either ``'r'`` or ``'rt'`` for text mode, or
                ``'rb'`` for binary mode.
            encoding: Text mode encoding.
        """
        modes = ["r", "rt", "rb"]
        if mode not in modes:
            raise Exception(f"Invalid mode {mode}, supported {modes}")

        if mode == "rb":
            return self._handle().read_file(str(path))

        if mode in {"r", "rt"}:
            return str(self._handle().read_file(str(path)), encoding=encoding)

        raise TODO()

    def read_lines(
        self, path: Union[str, pathlib.PurePath], encoding: str = "utf8"
    ) -> list[str]:
        """Read a file and return the contents, as text

        Args:
            path: *Absolute* path to the file inside the image
            encoding: File encoding.
        """
        return self._handle().read_lines(str(path))

    def write(
        self,
        path: Union[str, pathlib.PurePath],
        data: Union[bytes, str],
        append: bool = False,
    ):
        """Write data to a file inside the image

        Note: Requires the image to be opened with read_only=False

        Args:
            path: *Absolute* path to the file inside the image
            data: The content to write to the file
            append: If False, the entire content of the existing file is
                overwritten (just like opening a file in 'w' mode). If set to
                True, ``data`` is added at the end of the file, like 'a' mode.
        """
        self._check_write_permission()
        if append == False:
            self._handle().write(str(path), data)
            return

        if append == True:
            self._handle().write_append(str(path), data)
            return

        raise Exception(f"append must be a bool, got {append.__class__.__name__}")

    def inspect(self) -> InsepctedData:
        """Inspect the image to autodetect information

        This method relies on libguestfs auto-detect features, so results are
        not guaranteed, and not all keys described below are going to be
        present. Use with caution.

        Results are cached, the first call may be expensive, but subsequent
        queries re-use the data stored in the ``inspected_data`` attribute.

        The keys that *may* be present in the returning ``dict`` are:

        * ``arch``: image architecture, as returned by
          ``guestfs_file_architecture``.
        * ``os``: A pair containing operating system and distribution,
          as returned by ``guestfs_inspect_get_type`` and
          ``guestfs_inspect_get_distro``. Any of the values may be None.
        * ``version``: a tuple containing ``(major, minor)`` version, where
          values are populated with ``guestfs_inspect_get_major_version`` and
          ``guestfs_inspect_get_minor_version``. One of the values can be None,
          if both are None then the key is not present.
        * ``package_manager``: the package manager used by the distribution (if,
          any), as returned by ``guestfs_inspect_get_package_management``.
        * ``hostname``: the hostname of the image, as returned by
          ``guestfs_get_hostname``


        Returns:
            A dict, which may contain the keys detailed above.
        """
        if self.inspected_data is not None:
            return self.inspected_data

        h = self._handle()
        self.inspected_data = dict()
        data = self.inspected_data

        data["arch"] = h.inspect_get_arch(self.root)
        ostype, distro = h.inspect_get_type(self.root), h.inspect_get_distro(self.root)

        data["os"] = (
            ostype if ostype != "unknown" else None,
            distro if distro != "unknown" else None,
        )

        major, minor = h.inspect_get_major_version(
            self.root
        ), h.inspect_get_minor_version(self.root)

        if major != 0:
            data["version"] = (major, minor if minor != -1 else None)

        data["package_manager"] = h.inspect_get_package_management(self.root)
        data["hostname"] = h.inspect_get_hostname(self.root)

        return data

    def chmod(self, path: str, mode: int) -> None:
        """Apply a chmod to the given file in the disk image.

        Args:
            path: Path (absolute to the disk image) of the file to
                modify.
            mode: New mode of the file.
        """
        self._handle().chmod(mode, path)

    def chown(self, path: str, uid: int, gid: int) -> None:
        """Apply a chown to a given file in the disk image.

        Args:
            path: Path (absolute to the disk image) of the file
                to modify.
            uid: New user owner of the file.
            gid: New group owner of the file.
        """
        self.guestfs_handle().chown(uid, gid, path)


def open_image(file: pathlib.Path, read_only: bool = True) -> ImageEditor:
    """Open a VM image for inspection

    Args:
        file: image file to open
        read_only: Mount the image as read-only. Defaults to True for safety,
            pass False to edit the image file.
    """
    editor = ImageEditor(file=file, read_only=read_only)
    return editor
