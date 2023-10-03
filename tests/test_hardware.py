from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from spin.machine.hardware import Disk
from spin.utils.sizes import Size


class TestDisk:
    def test_basic(self) -> None:
        empty = Disk()

        assert empty.location is None
        assert empty.pool is None
        assert empty.size is not None
        assert empty.label is None

    def test_serialization(self) -> None:
        empty = Disk()
        disk_0 = Disk(location="/tmp/some-location.img")
        disk_1 = Disk(location="relative_to_pool.img", pool="some-non-default-pool")

        for disk in (empty, disk_0, disk_1):
            serialized = disk.dict()
            assert json.dumps(serialized) is not None
            assert len(serialized) == 8
            assert Disk(**serialized) == disk
