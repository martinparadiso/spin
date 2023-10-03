"""Common utilities and definitions for shared elements"""

from __future__ import annotations

import json
import pathlib
from typing import Generic, Type, TypeVar

from typing_extensions import Protocol, TypedDict

from spin.machine import core
from spin.utils import ui

ResourceUser = core.CoreMachine


class Resource(Protocol):
    uuid: core.UUID
    autodestroy: bool
    deleted: bool
    """If set to ``True`` the resource has been deleted; and this is a dangling reference"""

    class Serialized(TypedDict):
        uuid: str
        autodestroy: bool

    @classmethod
    def resource_name(cls) -> str:
        return cls.__name__

    @classmethod
    def file(cls) -> pathlib.Path:
        ...

    def users(self) -> list[ResourceUser]:
        ...

    def add(self, machine: ResourceUser) -> None:
        ...

    def remove(self, machine: ResourceUser) -> None:
        ...

    def save(self, update: bool = False) -> None:
        Manager(self.__class__).save(self, update=update)

    def dict(self) -> Serialized:
        ...


R = TypeVar("R", bound=Resource)


class _Manager(Generic[R]):
    def __init__(self, resource: Type[R]) -> None:
        self.resource = resource

    def _read_file(self) -> dict[str, Resource.Serialized]:
        with open(self.resource.file(), "r", encoding="utf8") as file:
            data = json.load(file)
        return data

    def _write_file(self, data: dict[str, Resource.Serialized]) -> None:
        json_str = json.dumps(data)
        with open(self.resource.file(), "w", encoding="utf8") as file:
            file.write(json_str)

    def save(self, resource: R, *, update: bool = False) -> None:
        if resource.deleted:
            raise ValueError("Cannot save a deleted resource")
        existing = self._read_file()
        if resource.uuid in existing and update is False:
            raise ValueError("Resource already exists")
        if (
            resource.uuid in existing
            and len(resource.users()) == 0
            and resource.autodestroy is True
        ):
            ui.instance().info(f"Removing empty {resource.resource_name()}")
            existing.pop(resource.uuid)
            resource.deleted = True
        else:
            existing[resource.uuid] = resource.dict()
        self._write_file(existing)

    def load(self, uuid: str) -> None | R:
        serial = self._read_file().get(uuid, None)
        if serial is None:
            return None
        return self.resource(**serial)  # type: ignore[misc]

    def delete(self, resource: R) -> None:
        resources = self._read_file()
        if resource.uuid not in resources:
            raise ValueError(f"Resource {resource} not present")
        resources.pop(resource.uuid)
        self._write_file(resources)
        resource.deleted = True


def Manager(resource_cls: Type[R]) -> _Manager[R]:
    """Build a manager for the given `resource_class`

    Args:
        args, kwargs: Forwarded to ``resource_cls.__init__``.

    Returns:
        A manager for the given resource.
    """
    return _Manager(resource_cls)
