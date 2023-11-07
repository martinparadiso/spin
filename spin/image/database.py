"""Minimal 'database' managing machine Images
"""

from __future__ import annotations

import dataclasses
import datetime
import importlib
from typing import Collection, List, Optional

from sqlalchemy import Engine, ForeignKey, String, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from typing_extensions import Literal, overload

from spin.build.image_definition import ImageDefinition, Properties
from spin.image.image import Image
from spin.image.local_database import LocalDatabase
from spin.machine.credentials import RawUser
from spin.utils import config
from spin.utils.constants import (
    OS,
    sanitize_arch,
    sanitize_disk_format,
    sanitize_disk_type,
    sanitize_os_id,
)


class Base(DeclarativeBase):
    ...


class SourceModel(Base):
    __tablename__ = "definition_source"

    python_module: Mapped[str] = mapped_column(primary_key=True)
    images: Mapped[List[ImageDefinitionModel]] = relationship(back_populates="source")


class PropsModel(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    architecture: Mapped[Optional[str]]
    supports_backing: Mapped[bool]
    contains_os: Mapped[Optional[bool]]
    usernames: Mapped[Optional[str]]
    cloud_init: Mapped[Optional[bool]]
    ignition: Mapped[Optional[bool]]
    requires_install: Mapped[Optional[bool]]
    format: Mapped[Optional[str]]
    type: Mapped[Optional[str]]
    origin_time: Mapped[Optional[datetime.datetime]]

    image: Mapped[ImageDefinitionModel] = relationship(back_populates="props")


class ImageDefinitionModel(Base):
    __tablename__ = "image_definition"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("definition_source.python_module")
    )
    source: Mapped[Optional[SourceModel]] = relationship(back_populates="images")
    name: Mapped[Optional[str]]
    tag: Mapped[Optional[str]]
    props_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    props: Mapped[PropsModel] = relationship(back_populates="image")
    os_family: Mapped[Optional[str]]
    os_subfamily: Mapped[Optional[str]]
    os_distribution: Mapped[Optional[str]]
    os_version: Mapped[Optional[str]]
    credential_user: Mapped[Optional[str]]
    credential_password: Mapped[Optional[str]]
    retrieve_from: Mapped[Optional[str]]
    digest: Mapped[Optional[str]] = mapped_column(unique=True)


def to_sql(in_: ImageDefinition) -> ImageDefinitionModel:
    """Convert a nice ImageDefinition to a SQL friendly one.

    Raises:
        ValueError: if the image cannot be stored because it
            requires Python code to build.

    Returns:
        The image as SQL friendly object.
    """

    if in_.on_install:
        raise ValueError("Image contains logic (actions to execute on install)")

    props_dict = dataclasses.asdict(in_.props)
    if len(props_dict["usernames"]) == 0:
        props_dict["usernames"] = None
    else:
        if any("," in username for username in props_dict["usernames"]):
            raise ValueError("Username contains invalid character ','")
        props_dict["usernames"] = ",".join(props_dict["usernames"])

    props = PropsModel(**props_dict)
    source: None | SourceModel = None
    if in_.module is not None:
        source = SourceModel(python_module=in_.module.__name__)

    out = ImageDefinitionModel(
        source=source,
        name=in_.name,
        tag=in_.tag,
        props=props,
        os_family=getattr(in_.os, "family", None),
        os_subfamily=getattr(in_.os, "subfamily", None),
        os_distribution=getattr(in_.os, "distribution", None),
        os_version=getattr(in_.os, "version", None),
        credential_user=getattr(in_.credentials, "user", None),
        credential_password=getattr(in_.credentials, "password", None),
        retrieve_from=in_.retrieve_from,
        digest=in_.digest,
    )

    return out


def from_sql(in_: ImageDefinitionModel) -> ImageDefinition:
    """Convert an SQL image definition back into a user friendly one.

    Raises:
        ValueError: If the image cannot be converted back.
    """
    out = ImageDefinition()
    out.name = in_.name
    out.tag = in_.tag
    out.props = Properties(
        architecture=sanitize_arch(in_.props.architecture or ""),
        supports_backing=in_.props.supports_backing,
        contains_os=in_.props.contains_os,
        usernames=in_.props.usernames.split(",")
        if in_.props.usernames is not None
        else [],
        cloud_init=in_.props.cloud_init,
        ignition=in_.props.ignition,
        requires_install=in_.props.requires_install,
        format=sanitize_disk_format(in_.props.format or ""),
        type=sanitize_disk_type(in_.props.type or ""),
        origin_time=in_.props.origin_time,
    )

    out.os = sanitize_os_id(
        in_.os_family, in_.os_subfamily, in_.os_distribution, in_.os_version
    )
    if in_.credential_user is not None:
        out.credentials = RawUser(in_.credential_user, in_.credential_password)
    out.retrieve_from = in_.retrieve_from
    out.digest = in_.digest

    if in_.source is not None:
        out.module = importlib.import_module(in_.source.python_module)

    return out


class DefinitionDatabase:
    """High-level access to the definition database"""

    def __init__(self, url: str) -> None:
        self.url = url
        self._engine: None | Engine = None

    def __enter__(self) -> DefinitionDatabase:
        """Use the object as a context manager; only the engine is cached.

        NOTE: Mainly used to persist the in-memory database while debugging.
        """
        if self._engine is not None:
            raise ValueError("Engine already open")
        self._engine = create_engine(self.url)
        return self

    def __exit__(self, *_):
        self._engine = None
        return

    def exists(self) -> bool:
        """Check if the database exists.

        Warning: extremely rudimentay, mostly used to check if
            the file is present.
        """
        # HACK: Ugly way of checking, but it works
        engine = self._engine or create_engine(self.url)
        with Session(engine) as session:
            return engine.dialect.has_table(
                session.connection(), ImageDefinitionModel.__tablename__
            )

    def initdb(self) -> None:
        """Initialize the database."""
        with Session(self._engine or create_engine(self.url)) as session:
            Base.metadata.create_all(session.connection())

    def query(
        self,
        name: None | str = None,
        tag: None | str = None,
        digest: None | str = None,
        module: None | str = None,
    ) -> Collection[ImageDefinition]:
        """Retrieve the image matching the given parameters"""

        query_args = []
        if name is not None:
            query_args.append(ImageDefinitionModel.name == name)
        if tag is not None:
            query_args.append(ImageDefinitionModel.tag == tag)
        if digest is not None:
            query_args.append(ImageDefinitionModel.digest == digest)
        if module is not None:
            query_args.append(ImageDefinitionModel.source_id == module)

        with Session(self._engine or create_engine(self.url)) as session:
            match = session.execute(select(ImageDefinitionModel).where(*query_args))
            ret = [from_sql(e) for e in match.scalars()]
        return ret

    def add(self, image: ImageDefinition) -> None:
        """Try to add a new image definition to the database.

        Raises:
            ValueError: If the image could not be converted to SQL friendly
                data.
            ValueError: If the image is already present in the database. The
                way to determine if two images are equal may vary.
            If there was an error writing to the database
        """
        sql_obj = to_sql(image)
        if sql_obj is None:
            raise ValueError("Could not convert image to SQL data")
        with Session(self._engine or create_engine(self.url)) as session:
            if sql_obj.source is not None:
                existent = session.get(SourceModel, sql_obj.source.python_module)
                if existent is not None:
                    sql_obj.source = existent
            session.add(sql_obj)
            try:
                session.commit()
            except IntegrityError as e:
                if "UNIQUE" in str(e) and "digest" in str(e):
                    session.rollback()
                    raise ValueError(
                        f"Image with digest {sql_obj.digest} already in database"
                    ) from e
                else:
                    raise

    def delete(self, image: ImageDefinition) -> None:
        """Delete the given image from the database.

        Raises:
            ValueError: If more than one compatible image
                was found when querying the database.
        """
        raise NotImplementedError


class Database:
    """Machine images.

    The images in the database may be ready to use, or may require a build
    procedure.
    """

    def __init__(self, *, definitions_db_file: None | str = None) -> None:
        """
        Args:
            definitions_db_file: SQLite URL to the definitions database file.
                You can pass any sqlite compatible URL. If non is given, the
                path will be generated from the settings.
        """
        if definitions_db_file is None:
            definitions_db_file = "sqlite+pysqlite:///" + str(
                config.conf.definitions_file.absolute()
            )
        self.local = LocalDatabase()
        self.remotes = DefinitionDatabase(definitions_db_file)

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

    def images(self) -> Collection[Image]:
        """Return a list of all local images."""
        return self.local.images()

    def _get_by_digest(self, key) -> Image | None:
        # TODO: Query the definition database
        return self.local._get_by_digest(key)

    def _get_by_nametag(self, name, tag) -> list[Image | ImageDefinition]:
        imgs: list[Image | ImageDefinition] = list(self.images())
        imgs = [i for i in imgs if i.name == name and i.tag == tag]
        if self.remotes.exists():
            imgs.extend(self.remotes.query(name=name, tag=tag))
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
