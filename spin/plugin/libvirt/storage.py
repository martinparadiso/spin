"""Pool, volume and storage"""

from __future__ import annotations

import json
import pathlib
import subprocess

from spin.backend.base import DiskPool, ReturnType
from spin.errors import TODO, BackendError, NotFound
from spin.image.database import LocalDatabase
from spin.image.image import Image
from spin.machine.hardware import CDROM, Disk, Storage
from spin.utils import ui
from spin.utils.config import conf
from spin.utils.sizes import Size

from . import xml
from .utils import SUPPORTED_HARDDRIVE_FORMATS, parse_exception

try:
    import libvirt
except ImportError as exce:
    pass


class LibvirtDiskPool(DiskPool):
    """Libvirt pool wrapper"""

    def __init__(self, pool: str | libvirt.virStoragePool, uri: str) -> None:
        """
        Args:
            pool: Name of the pool (if not created yet), or the pool object
                provided by libvirt.
            uri: URI to connect to libvirt.
        """
        self.uri = uri
        self.pool: None | libvirt.virStoragePool
        if isinstance(pool, str):
            self.name = pool
            self.pool = None
        else:
            self.name = pool.name()
            self.pool = pool
        if self.pool is not None and not self.pool.isActive():
            self.pool.create()

        self._created: list[tuple[Storage, libvirt.virStorageVol]] = []

    @property
    def formats(self) -> list[str]:
        return ["raw", "qcow2"]

    @parse_exception
    def create_pool(self) -> DiskPool:
        """Create the pool, raise Exception if already exists.

        Raises:
            Exception: If the pool exists.
            libvirt.libvirtError: If something fails in the libvirt call.

        Returns:
            The newly created storage pool.
        """
        ui.instance().notice(f"Creating {self.name} pool in libvirt")
        if self.pool is not None:
            raise ValueError("Pool already exists")
        xmlpool = xml.storage_pool(
            name=self.name, path=conf.pools.absolute() / self.name
        )
        ui.instance().debug(xmlpool)
        with libvirt.open(self.uri) as conn:
            try:
                self.pool = conn.storagePoolDefineXML(xml.to_str(xmlpool))
                ret = self.pool.build()
                assert ret == 0
                self.pool.setAutostart(True)
                self.pool.create()
            except libvirt.libvirtError:
                if self.pool is not None:
                    self.pool.destroy()
                    self.pool.undefine()
                raise
        return self

    @staticmethod
    def _convert(disk: libvirt.virStorageVol) -> Storage:
        diskxml = xml.from_str(disk.XMLDesc())

        def find(path: str, attr: str | None = None) -> str:
            node = diskxml.find(path)
            if node is None:
                raise ValueError(f"Disk XML missing node {node}")
            if attr is None:
                if node.text is None:
                    raise ValueError(f"Disk XML missing text for node {node}")
                return node.text
            return node.attrib[attr]

        path = pathlib.Path(find("target/path"))
        unit = find("capacity", attr="unit")
        if unit != "bytes":
            raise TODO(f"Unsupported unit: {unit}")
        size = Size(find("capacity"))
        fmt = find("target/format", "type")
        uuid = find("name")
        if fmt == "iso":
            return CDROM(location=path, size=size, fmt="iso", uuid=uuid)
        try:
            backing_image = find("backingStore/path")
        except ValueError:
            backing_image = None
        if fmt not in SUPPORTED_HARDDRIVE_FORMATS:
            raise ValueError("Unsupported format")
        return Disk(
            location=path,
            size=size,
            fmt=fmt,  # type: ignore[arg-type]
            uuid=uuid,
            backing_image=backing_image,
        )

    @parse_exception
    def list_disks(self) -> list[Storage]:
        if self.pool is None:
            raise ValueError("Pool not initialized")
        virtvols = self.pool.listAllVolumes()
        return [self._convert(v) for v in virtvols]

    @parse_exception
    def fill(self, disk: Storage | libvirt.virStorageVol, data: pathlib.Path) -> None:
        """Populate the disk with the source image."""
        assert self.pool is not None
        disk_name = disk.uuid if isinstance(disk, Storage) else str(disk.name())
        assert disk_name is not None
        with libvirt.open(self.uri) as conn:
            # Libvirt requires to use the same connection for both elements
            disk_ = conn.storagePoolLookupByUUID(
                self.pool.UUID()
            ).storageVolLookupByName(disk_name)
            stream = conn.newStream()
            # NOTE: Sparse-ness disabled due to a possible bug
            # disk_.upload(stream, 0, 0, libvirt.VIR_STORAGE_VOL_UPLOAD_SPARSE_STREAM)
            disk_.upload(stream, 0, 0)
            with open(data, "rb") as in_img:
                ui.instance().notice(f"Copying disk {str(data)} -> {str(disk_.path())}")

                eof = False

                def callback(stream: libvirt.virStream, length: int, _) -> bytes:
                    nonlocal eof
                    if eof:
                        raise EOFError
                    data = in_img.read(length)
                    eof = len(data) == 0
                    return data

                stream.sendAll(handler=callback, opaque=None)

    @parse_exception
    def import_image(self, image: Image) -> Disk:
        if image.file is None:
            raise ValueError

        if "libvirt" not in image.pools:
            image.pools["libvirt"] = {}
        if self.name not in image.pools["libvirt"]:
            disk = Disk()
            disk.location = image.file
            disk.new_uuid()
            ok, error_msg = self.create_disk(disk)
            if not ok:
                raise BackendError(error_msg)
            image.pools["libvirt"][self.name] = disk
            LocalDatabase().update(image)
        return image.pools["libvirt"][self.name]

    @parse_exception
    def create_disk(self, disk: Storage) -> ReturnType:
        if self.pool is None:
            raise ValueError("Pool not created")

        if not any(
            hasattr(disk, attr) for attr in ("location", "size", "backing_image")
        ):
            raise ValueError("Disk needs at least a location, size or a backing_image")

        path_node = xml.from_str(self.pool.XMLDesc()).find("target/path")
        assert disk.uuid is not None
        assert path_node is not None
        path_str = path_node.text
        assert path_str is not None
        if disk.size is None:
            read_size_from: str
            if (
                isinstance(disk, Disk)
                and disk.backing_image is not None
                and disk.backing_image.file is not None
            ):
                read_size_from = str(disk.backing_image.file)
            else:
                read_size_from = str(disk.location)
            volinfo = json.loads(
                subprocess.run(
                    [
                        "qemu-img",
                        "info",
                        "--output=json",
                        read_size_from,
                    ],
                    capture_output=True,
                    check=True,
                ).stdout.decode("utf8")
            )
            disk.size = Size(volinfo["virtual-size"])

        if disk.format is None and disk.location is not None:
            volinfo = json.loads(
                subprocess.run(
                    [
                        "qemu-img",
                        "info",
                        "--output=json",
                        str(disk.location.absolute()),
                    ],
                    capture_output=True,
                    check=True,
                ).stdout.decode("utf8")
            )
            disk.format = volinfo["format"]
        if disk.format is None:
            # HACK: I do not know if this has to be here
            disk.format = "qcow2"

        def disk_finder_callback(ref: str) -> Disk:
            real_image = LocalDatabase().get(key=ref)
            if real_image is None:
                raise NotFound(ref)
            as_disk = self.import_image(real_image)
            if as_disk.location is None:
                raise BackendError(f"{as_disk} created from image has no file")
            if as_disk.format is None:
                raise BackendError(f"{as_disk} created from image has unknown format")

            return as_disk

        source_data: pathlib.Path | None = None
        if disk.location is not None:
            source_data = disk.location
        disk.location = (pathlib.Path(path_str.strip()) / disk.uuid).absolute()

        volume = self.pool.createXML(
            xml.to_str(xml.volume(disk, image_to_disk=disk_finder_callback))
        )

        if source_data is not None:
            self.fill(volume, source_data)

        self._created.append((disk, volume))

        return volume is not None, None

    def remove(self, disk: "Storage") -> bool:
        assert self.pool is not None
        libvirt_disk = self.pool.storageVolLookupByName(disk.uuid)
        if libvirt_disk is None:
            return False
        libvirt_disk.delete()
        return True
