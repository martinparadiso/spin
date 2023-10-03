"""Tests the resource generic"""

from __future__ import annotations

import json
import pathlib
from unittest.mock import MagicMock

import pytest

from spin.machine import shared
from spin.machine.core import UUID
from spin.machine.machine import Machine


def test_resource_implementer(tmp_path: pathlib.Path) -> None:
    (tmp_path / "networks.json").write_text("{}")

    test_uuid = UUID("3600bb8c-d676-4bed-9f07-f4c3dc68188b")

    class Network(shared.Resource):
        autodestroy = True

        class Serialized(shared.Resource.Serialized):
            users: list[str]

        def __init__(self) -> None:
            self.uuid = test_uuid
            self._users: list[shared.ResourceUser] = []
            self.deleted = False

        @classmethod
        def file(cls) -> pathlib.Path:
            return tmp_path / "networks.json"

        def add(self, machine: shared.ResourceUser) -> None:
            self._users.append(machine)
            self.save()

        def users(self) -> list[shared.ResourceUser]:
            return self._users

        def remove(self, machine: shared.ResourceUser) -> None:
            self._users.remove(machine)
            self.save(update=True)

        def dict(self) -> Serialized:
            return {
                "uuid": self.uuid,
                "users": [u.uuid for u in self._users],
                "autodestroy": self.autodestroy,
            }

    net = Network()
    machine = MagicMock(Machine())
    machine.uuid = "e0370063-8b6e-46b9-9ed5-e83983ebcfc6"
    net.add(machine)

    stored_in_disk = json.loads((tmp_path / "networks.json").read_text("utf8"))

    assert stored_in_disk == {
        "3600bb8c-d676-4bed-9f07-f4c3dc68188b": {
            "uuid": "3600bb8c-d676-4bed-9f07-f4c3dc68188b",
            "users": ["e0370063-8b6e-46b9-9ed5-e83983ebcfc6"],
            "autodestroy": True,
        },
    }

    # Check the auto-destruction
    net.remove(machine)
    assert net.deleted is True
    stored_in_disk = json.loads((tmp_path / "networks.json").read_text("utf8"))
    assert stored_in_disk == {}

    with pytest.raises(ValueError) as exce_info:
        net.add(machine)

    exce_info.match("deleted")
