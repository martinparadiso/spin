"""Minimal 'database' system to keep track of images
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Optional, Union, overload

from typing_extensions import Literal

from spin.image.image import Image
from spin.utils.config import conf

if TYPE_CHECKING:
    from spin.build.builder import ImageDefinition


class LocalDatabase:
    """Local images ready to be used

    The images in the database are ready to be used, require no download
    or any kind of preparation.

    TODO:
        Update documentation, definition-only images are still reported by the
        images() method.
    """

    def __init__(self) -> None:
        """
        Args:
            folder: Path to the folder where the database was initialized.
        """
        # Load plugin provided images
        from spin.plugin.api import register

        self.image_folder = conf.database_folder
        self.db_file = conf.database_file

        self.definitions: "list[ImageDefinition]" = []
        for prov in register.image_providers:
            self.definitions.extend(prov())

    def add(self, image: Image) -> None:
        """Add an image to the pool

        You can pass a complete image definition, or a file which will be
        properly converted for storage

        Args:
            image: The image to add to the pseudo-database, the image will be
                moved to the new folder.

        Raises:
            If image with same hash already exists in the database.
        """

        with open(self.db_file, "r") as dbfile:
            db = json.load(dbfile)
        digest = image.hexdigest()
        if digest in db["images"].keys():
            raise Exception("Image already in database")
        image.move(self.image_folder / digest)
        data = image.dict()
        db["images"][digest] = data
        with open(self.db_file, "w") as dbfile:
            serialized = json.dumps(db, indent=4)
            dbfile.write(serialized)

    def update(self, image: Image):
        """Update an image in the database.

        Args:
            image: The image to update

        Raises:
            ValueError: If the image is not present.
        """
        with open(self.db_file, "r", encoding="utf8") as dbfile:
            db = json.load(dbfile)
        digest = image.hexdigest()
        if digest not in db["images"].keys():
            raise ValueError("Image not in database")
        db["images"][digest] = image.dict()
        serialized = json.dumps(db, indent=4)
        with open(self.db_file, "w", encoding="utf8") as dbfile:
            dbfile.write(serialized)

    @overload
    def images(self, local_only: Literal[True]) -> list[Image]:
        ...

    @overload
    def images(self, local_only: Literal[False]) -> list[Image | ImageDefinition]:
        ...

    @overload
    def images(
        self, local_only: bool = False
    ) -> list[Image] | list[Image | ImageDefinition]:
        ...

    def images(
        self, local_only: bool = False
    ) -> list[Image] | list[Image | ImageDefinition]:
        """Return a list of the images currently in the local database

        Return:
            The images in the local database. If ``definition_only`` is
            ``True``, images which are not buildable are also returned.
        """
        with open(self.db_file, "r") as dbfile:
            db = json.load(dbfile)
        imgs: "list[Image | ImageDefinition]" = [
            Image(**db["images"][digest]) for digest in db["images"]
        ]
        if not local_only:
            imgs.extend(self.definitions)
        return imgs

    def _get_by_digest(self, key) -> Image | None:
        with open(self.db_file, "r") as dbfile:
            db = json.load(dbfile)
        if key not in db["images"]:
            return None
        return Image(**db["images"][key])

    def _get_by_nametag(self, name, tag) -> list[Image | ImageDefinition]:
        imgs = self.images(local_only=False)
        imgs = [i for i in imgs if i.name == name and i.tag == tag]
        imgs.sort(key=lambda img: 0 if img.usable else 1)
        return imgs

    @overload
    def get(self, key: str) -> Optional[Image]:
        ...

    @overload
    def get(self, key: tuple[None | str, None | str]) -> list[Image | ImageDefinition]:
        ...

    def get(
        self, key: Union[str, tuple[None | str, None | str]]
    ) -> Union[Union[Image, None], list[Image | ImageDefinition]]:
        """Return a specific image from the database

        Args: key: You can pass the image *digest* to find a perfect match, or a
                name,tag pair to find all images matching that combination.

        Returns:
            If you pass a digest you receive a single image or None if the image
            is not present; for the name:tag pair, a list of images matching the
            requested name and tag, the list can be empty if none were found.

        Raises:
            ValueError: If the iterable does not have *exactly* 2 elements.
            IOError: If there was a problem opening the database.
        """
        if isinstance(key, str):
            return self._get_by_digest(key)
        if len(key) != 2:
            raise ValueError("Key must have exactly 2 elements")
        return self._get_by_nametag(key[0], key[1])
