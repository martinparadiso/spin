"""Minimal 'database' managing machine Images
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import Collection

from typing_extensions import Literal, overload

from spin.build.image_definition import ImageDefinition
from spin.image.image import Image
from spin.image.local_database import LocalDatabase
from spin.plugin.api import register


class Database:
    """Machine images.

    The images in the database may be ready to use, or may require a build
    procedure.
    """

    def __init__(self) -> None:
        """
        Args:
            folder: Path to the folder where the database was initialized.
        """
        self.local = LocalDatabase()
        self.definitions: list[ImageDefinition] = []

    def _update_providers(self) -> None:
        """Load plugin-provided images"""
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
        return self.local.add(image)

    def update(self, image: Image):
        """Update an image in the database.

        Args:
            image: The image to update

        Raises:
            ValueError: If the image is not present.
        """
        self.local.update(image)

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
        """Return a list of all images

        Warning:
            Can be slow; plugins may build image definitions using remote
            data.

        Return:
            The images in the local database. If ``definition_only`` is
            ``True``, images which are not buildable are also returned.
        """
        imgs = self.local.images()
        if local_only:
            return imgs
        self._update_providers()
        return imgs + self.definitions

    def _get_by_digest(self, key) -> Image | None:
        return self.local._get_by_digest(key)

    def _get_by_nametag(self, name, tag) -> list[Image | ImageDefinition]:
        imgs = self.images(local_only=False)
        imgs = [i for i in imgs if i.name == name and i.tag == tag]
        imgs.sort(key=lambda img: 0 if img.usable else 1)
        return imgs

    @overload
    def get(self, key: str) -> None | Image:
        ...

    @overload
    def get(self, key: tuple[None | str, None | str]) -> list[Image | ImageDefinition]:
        ...

    def get(
        self, key: str | tuple[None | str, None | str]
    ) -> Image | None | list[Image | ImageDefinition]:
        """Return a specific image from the database

        Warning:
            Can be slow; plugins may build image definitions using remote
            data.

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


@dataclasses.dataclass
class _BestResult:
    local: None | Image
    all: Image | ImageDefinition


def best(
    name: str, tag: str | None, images: Collection[Image | ImageDefinition]
) -> None | _BestResult:
    """Select the *best* suited image for the given name-tag pair.

    Locally ready images are preferred over remote ones, newer
    images are preferred over old ones.

    Return:
        The best image found
    """

    def ft_name(image: Image | ImageDefinition) -> bool:
        return image.name == name and image.tag == tag

    def sort_newer(image: Image | ImageDefinition) -> int:
        return int(
            (image.props.origin_time or datetime.datetime.fromtimestamp(0)).timestamp()
        )

    locals_ = sorted(
        [i for i in images if isinstance(i, Image) and ft_name(i)], key=sort_newer
    )
    all_ = sorted(filter(ft_name, images), key=sort_newer, reverse=True)

    if not all_:
        return None

    best_local = locals_[0] if locals_ else None
    return _BestResult(best_local, all_[0])
